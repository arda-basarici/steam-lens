"""Behavioral claims on the Gemini adapter — canned wire fixtures, no network.

Every test but the last runs against ``httpx.MockTransport`` with bodies shaped
like real generateContent responses, so the normalization claims (finish-reason
mapping, the usage split, blocked-request handling) are pinned without spending
a request. The env-gated live smoke at the bottom is the only test that spends:
it runs only when ``GEMINI_API_KEY`` is deliberately set.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable

import httpx
import pytest

from steamlens.contracts import (
    FinishReason,
    LlmRequest,
    LlmStage,
    SinkEvent,
)
from steamlens.llm_client import (
    InMemoryClassifyCache,
    InMemorySpendLedger,
    LlmClient,
    LlmClientConfig,
    LlmConfigError,
    ModelSpec,
    ProviderEntry,
    ProviderPermanentError,
    ProviderTransientError,
    Route,
    gemini_entry,
)
from steamlens.llm_client.gemini import build_payload, parse_response

_KEY = "test-key-123"


class NullSink:
    def emit(self, event: SinkEvent) -> None:
        pass


def _wire(
    text: str = "OK",
    finish: str = "STOP",
    *,
    thoughts: int | None = None,
    model_version: str = "gemini-2.5-flash-002",
) -> str:
    """A generateContent body shaped like the real wire (see the probe's captures)."""
    usage: dict[str, int] = {"promptTokenCount": 10, "candidatesTokenCount": 5}
    if thoughts is not None:
        usage["thoughtsTokenCount"] = thoughts
    return json.dumps(
        {
            "candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": finish}],
            "usageMetadata": usage,
            "modelVersion": model_version,
        }
    )


def _entry(handler: Callable[[httpx.Request], httpx.Response]) -> ProviderEntry:
    return gemini_entry(_KEY, transport=httpx.MockTransport(handler))


# --- build_payload -------------------------------------------------------------


def test_payload_carries_prompt_ceiling_and_merged_params() -> None:
    """Params merge into generationConfig untranslated; the typed ceiling lands as
    maxOutputTokens — Gemini 2.5 counts thinking against it, matching the
    reservation's total-ceiling semantics."""
    payload = build_payload(
        model="gemini-2.5-flash",
        prompt="label this",
        max_output_tokens=32768,
        params={"temperature": 0, "thinkingConfig": {"thinkingBudget": 0}},
    )
    assert payload["contents"] == [{"parts": [{"text": "label this"}]}]
    assert payload["generationConfig"] == {
        "maxOutputTokens": 32768,
        "temperature": 0,
        "thinkingConfig": {"thinkingBudget": 0},
    }


def test_payload_rejects_a_params_claim_on_the_ceiling() -> None:
    """maxOutputTokens has one home (the typed route field); a params duplicate is
    a config contradiction, not a silent override."""
    with pytest.raises(LlmConfigError, match="max_output_tokens"):
        build_payload(
            model="m", prompt="p", max_output_tokens=100, params={"maxOutputTokens": 200}
        )


# --- parse_response ------------------------------------------------------------


def test_parse_reads_text_version_and_the_usage_split() -> None:
    response = parse_response(_wire("hello", thoughts=25))
    assert response.text == "hello"
    assert response.model_version == "gemini-2.5-flash-002"
    assert response.finish_reason is FinishReason.STOP
    assert (
        response.usage.prompt_tokens,
        response.usage.output_tokens,
        response.usage.thinking_tokens,
    ) == (10, 5, 25)


def test_parse_defaults_absent_thoughts_to_an_explicit_zero() -> None:
    """thinkingBudget 0 makes Gemini omit thoughtsTokenCount entirely — the split
    still records an explicit 0, never a missing field."""
    assert parse_response(_wire()).usage.thinking_tokens == 0


def test_parse_joins_multi_part_text() -> None:
    body = json.loads(_wire("ignored"))
    body["candidates"][0]["content"]["parts"] = [{"text": "one "}, {"text": "two"}]
    assert parse_response(json.dumps(body)).text == "one two"


@pytest.mark.parametrize(
    ("wire_reason", "normalized"),
    [
        ("MAX_TOKENS", FinishReason.LENGTH),
        ("SAFETY", FinishReason.REFUSAL),
        ("RECITATION", FinishReason.REFUSAL),
        ("SOME_FUTURE_REASON", FinishReason.OTHER),
    ],
)
def test_parse_normalizes_the_finish_vocabulary(
    wire_reason: str, normalized: FinishReason
) -> None:
    """Gemini's vocabulary maps into the closed set; the unknown falls to OTHER,
    never guessed into a clean stop."""
    assert parse_response(_wire(finish=wire_reason)).finish_reason is normalized


def test_parse_treats_a_blocked_request_as_a_refusal() -> None:
    """No candidates at all means Gemini blocked the request outright — normalized
    to a refusal with no text instead of a KeyError."""
    raw = json.dumps(
        {
            "promptFeedback": {"blockReason": "SAFETY"},
            "usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 0},
        }
    )
    response = parse_response(raw)
    assert response.finish_reason is FinishReason.REFUSAL
    assert response.text == ""
    assert response.usage.prompt_tokens == 7


# --- send ----------------------------------------------------------------------


def test_send_posts_the_key_in_the_header_and_returns_the_raw_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-goog-api-key"] == _KEY
        assert str(request.url).endswith("models/gemini-2.5-flash:generateContent")
        return httpx.Response(200, text=_wire("raw body"))

    raw = _entry(handler).send(model="gemini-2.5-flash", payload={"contents": []})
    assert json.loads(raw)["candidates"][0]["content"]["parts"][0]["text"] == "raw body"


@pytest.mark.parametrize("status", [429, 500, 503])
def test_send_raises_transient_for_the_retryable_statuses(status: int) -> None:
    entry = _entry(lambda _: httpx.Response(status, text="try later"))
    with pytest.raises(ProviderTransientError, match=str(status)):
        entry.send(model="m", payload={})


def test_send_raises_permanent_for_a_rejection_without_leaking_the_key() -> None:
    """A 400 is a config/code bug: typed permanent, and the message carries the
    status and body — never the credential."""
    entry = _entry(lambda _: httpx.Response(400, text="API key not valid"))
    with pytest.raises(ProviderPermanentError, match="400") as excinfo:
        entry.send(model="m", payload={})
    assert _KEY not in str(excinfo.value)


def test_send_raises_transient_on_transport_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("boom")

    with pytest.raises(ProviderTransientError, match="transport"):
        _entry(handler).send(model="m", payload={})


# --- end to end through the client ----------------------------------------------


def test_the_door_serves_a_classify_call_through_the_gemini_entry() -> None:
    """The full path — route, payload, wire, normalization, journal — on one call."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["generationConfig"]["maxOutputTokens"] == 1000
        assert body["generationConfig"]["temperature"] == 0
        return httpx.Response(200, text=_wire("labeled", thoughts=3))

    config = LlmClientConfig(
        routes={
            LlmStage.CLASSIFY: Route(
                provider="gemini",
                model="gemini-2.5-flash",
                max_output_tokens=1000,
                params={"temperature": 0},
            )
        },
        models={
            "gemini-2.5-flash": ModelSpec(
                rpm=100_000, rpd=None, input_usd_per_1m=0.0, output_usd_per_1m=0.0
            )
        },
    )
    ledger = InMemorySpendLedger()
    client = LlmClient(
        config,
        InMemoryClassifyCache(),
        ledger,
        NullSink(),
        registry={"gemini": gemini_entry(_KEY, transport=httpx.MockTransport(handler))},
    )
    response = client.complete(LlmRequest(stage=LlmStage.CLASSIFY, prompt="review text"))
    assert response.text == "labeled"
    assert response.model_version == "gemini-2.5-flash-002"
    assert response.usage.thinking_tokens == 3
    assert len(ledger.records) == 1
    assert ledger.records[0].model_version == "gemini-2.5-flash-002"


# --- the live smoke (spends one request; explicit opt-in only) ------------------
# Gated on a flag, not on key presence: the key lives permanently in the dev
# machine's user environment, and a plain `pytest` run must never spend quota.
# Run it deliberately: STEAMLENS_LIVE_SMOKE=1 uv run pytest -k live_smoke


@pytest.mark.skipif(
    os.environ.get("STEAMLENS_LIVE_SMOKE") != "1" or "GEMINI_API_KEY" not in os.environ,
    reason="live smoke spends quota; set STEAMLENS_LIVE_SMOKE=1 (and GEMINI_API_KEY) to run",
)
def test_live_smoke_one_real_call() -> None:
    """One real generateContent round-trip: clean stop, a real usage split, text back."""
    entry = gemini_entry(os.environ["GEMINI_API_KEY"])
    payload = entry.build_payload(
        model="gemini-2.5-flash",
        prompt="Reply with exactly: OK",
        max_output_tokens=2048,
        params={"temperature": 0, "thinkingConfig": {"thinkingBudget": 0}},
    )
    raw = entry.send(model="gemini-2.5-flash", payload=payload)
    response = entry.parse(raw)
    assert response.finish_reason is FinishReason.STOP
    assert response.usage.prompt_tokens > 0
    assert "OK" in response.text
