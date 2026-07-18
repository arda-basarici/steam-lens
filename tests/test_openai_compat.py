"""Behavioral claims on the OpenAI-compatible adapter — canned wire fixtures, no network.

Everything runs against ``httpx.MockTransport`` with bodies shaped like the
real chat-completions wire, so the normalization claims (finish-reason mapping,
the reasoning-subtraction usage split, null-content handling, the keyless
Ollama mode) are pinned without spending a request. No live smoke here — each
vendor's first live round-trip happens naturally when the bake-off runner
dials it.
"""

from __future__ import annotations

import json
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
    openai_compat_entry,
)
from steamlens.llm_client.openai_compat import build_payload, parse_response

_KEY = "test-key-123"
_BASE = "https://compat.example/v1"


class NullSink:
    def emit(self, event: SinkEvent) -> None:
        pass


def _wire(
    text: str | None = "OK",
    finish: str = "stop",
    *,
    completion_tokens: int = 5,
    reasoning: int | None = None,
    model_version: str = "llama-3.3-70b-versatile",
) -> str:
    """A chat-completions body shaped like the real wire.

    ``reasoning`` present adds the nested ``completion_tokens_details`` block
    (the DeepSeek/OpenAI reasoning shape); absent omits it entirely, the
    common non-reasoning case.
    """
    usage: dict[str, object] = {"prompt_tokens": 10, "completion_tokens": completion_tokens}
    if reasoning is not None:
        usage["completion_tokens_details"] = {"reasoning_tokens": reasoning}
    return json.dumps(
        {
            "choices": [
                {"message": {"role": "assistant", "content": text}, "finish_reason": finish}
            ],
            "usage": usage,
            "model": model_version,
        }
    )


def _entry(
    handler: Callable[[httpx.Request], httpx.Response], api_key: str = _KEY
) -> ProviderEntry:
    return openai_compat_entry(api_key, base_url=_BASE, transport=httpx.MockTransport(handler))


# --- build_payload -------------------------------------------------------------


def test_payload_carries_model_message_ceiling_and_spread_params() -> None:
    """The typed fields land as model/messages/max_tokens; params spread in as
    top-level siblings — the compat dialect has no nested config object."""
    payload = build_payload(
        model="llama-3.3-70b-versatile",
        prompt="label this",
        max_output_tokens=4096,
        params={"temperature": 0, "response_format": {"type": "json_object"}},
    )
    assert payload == {
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": "label this"}],
        "max_tokens": 4096,
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }


@pytest.mark.parametrize("key", ["model", "messages", "max_tokens"])
def test_payload_rejects_a_params_claim_on_a_reserved_key(key: str) -> None:
    """Each typed field has one home; a params duplicate is a config
    contradiction, not a silent override."""
    with pytest.raises(LlmConfigError, match=key):
        build_payload(model="m", prompt="p", max_output_tokens=100, params={key: "x"})


# --- parse_response ------------------------------------------------------------


def test_parse_reads_text_version_and_subtracts_the_reasoning_split() -> None:
    """completion_tokens includes reasoning on this wire — the parser recovers
    the contract's disjoint split (output = completion - reasoning) so the
    ledger never bills thinking twice."""
    response = parse_response(_wire("hello", completion_tokens=30, reasoning=25))
    assert response.text == "hello"
    assert response.model_version == "llama-3.3-70b-versatile"
    assert response.finish_reason is FinishReason.STOP
    assert (
        response.usage.prompt_tokens,
        response.usage.output_tokens,
        response.usage.thinking_tokens,
    ) == (10, 5, 25)


def test_parse_reads_reasoning_exceeding_completion_as_already_disjoint() -> None:
    """OpenRouter's convention: reasoning is NOT a completion subset — seen
    live exceeding it. That signature switches to the disjoint read instead of
    minting negative output tokens."""
    response = parse_response(_wire("hello", completion_tokens=1212, reasoning=1292))
    assert response.usage.output_tokens == 1212
    assert response.usage.thinking_tokens == 1292


def test_parse_defaults_an_absent_details_block_to_an_explicit_zero() -> None:
    """Non-reasoning vendors omit completion_tokens_details entirely — the split
    still records an explicit 0 and completion passes through as pure output."""
    response = parse_response(_wire())
    assert response.usage.output_tokens == 5
    assert response.usage.thinking_tokens == 0


def test_parse_reads_null_content_as_empty_text() -> None:
    """Some vendors ship content: null on filtered responses — empty text,
    never a crash on NoneType."""
    response = parse_response(_wire(None, finish="content_filter"))
    assert response.text == ""
    assert response.finish_reason is FinishReason.REFUSAL


@pytest.mark.parametrize(
    ("wire_reason", "normalized"),
    [
        ("length", FinishReason.LENGTH),
        ("model_length", FinishReason.LENGTH),
        ("content_filter", FinishReason.REFUSAL),
        ("tool_calls", FinishReason.OTHER),
        ("some_future_reason", FinishReason.OTHER),
    ],
)
def test_parse_normalizes_the_finish_vocabulary(
    wire_reason: str, normalized: FinishReason
) -> None:
    """The compat vocabulary (with Mistral's model_length variant) maps into the
    closed set; the unknown falls to OTHER, never guessed into a clean stop."""
    assert parse_response(_wire(finish=wire_reason)).finish_reason is normalized


def test_parse_treats_an_empty_choices_list_as_a_refusal() -> None:
    """No choices at all — normalized to a refusal with no text instead of an
    IndexError, mirroring the Gemini blocked-request precedent."""
    raw = json.dumps({"choices": [], "usage": {"prompt_tokens": 7}, "model": "m"})
    response = parse_response(raw)
    assert response.finish_reason is FinishReason.REFUSAL
    assert response.text == ""
    assert response.usage.prompt_tokens == 7


# --- send ----------------------------------------------------------------------


def test_send_posts_the_bearer_header_and_returns_the_raw_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == f"Bearer {_KEY}"
        assert str(request.url) == f"{_BASE}/chat/completions"
        return httpx.Response(200, text=_wire("raw body"))

    raw = _entry(handler).send(model="m", payload={"model": "m", "messages": []})
    assert json.loads(raw)["choices"][0]["message"]["content"] == "raw body"


def test_send_omits_the_auth_header_when_the_key_is_empty() -> None:
    """The local-Ollama mode: no key means no Authorization header at all,
    not a fake credential."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert "Authorization" not in request.headers
        return httpx.Response(200, text=_wire())

    _entry(handler, api_key="").send(model="m", payload={})


@pytest.mark.parametrize("status", [429, 500, 503])
def test_send_raises_transient_for_the_retryable_statuses(status: int) -> None:
    entry = _entry(lambda _: httpx.Response(status, text="try later"))
    with pytest.raises(ProviderTransientError, match=str(status)):
        entry.send(model="m", payload={})


def test_send_raises_permanent_for_a_rejection_without_leaking_the_key() -> None:
    """A 401 is a config bug: typed permanent, and the message names the base
    URL and status — never the credential."""
    entry = _entry(lambda _: httpx.Response(401, text="invalid api key"))
    with pytest.raises(ProviderPermanentError, match="401") as excinfo:
        entry.send(model="m", payload={})
    assert _KEY not in str(excinfo.value)
    assert _BASE in str(excinfo.value)


def test_send_raises_transient_on_transport_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("boom")

    with pytest.raises(ProviderTransientError, match="transport"):
        _entry(handler).send(model="m", payload={})


# --- end to end through the client ----------------------------------------------


def test_the_door_serves_a_classify_call_through_a_compat_entry() -> None:
    """The full path — route, payload, wire, normalization, journal — on one
    call routed to a registered compat vendor."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "llama-3.3-70b-versatile"
        assert body["max_tokens"] == 1000
        assert body["temperature"] == 0
        return httpx.Response(200, text=_wire("labeled"))

    config = LlmClientConfig(
        routes={
            LlmStage.CLASSIFY: Route(
                provider="groq",
                model="llama-3.3-70b-versatile",
                max_output_tokens=1000,
                params={"temperature": 0},
            )
        },
        models={
            "llama-3.3-70b-versatile": ModelSpec(
                rpm=30, rpd=1000, input_usd_per_1m=0.0, output_usd_per_1m=0.0
            )
        },
    )
    ledger = InMemorySpendLedger()
    client = LlmClient(
        config,
        InMemoryClassifyCache(),
        ledger,
        NullSink(),
        registry={
            "groq": openai_compat_entry(
                _KEY, base_url=_BASE, transport=httpx.MockTransport(handler)
            )
        },
    )
    response = client.complete(LlmRequest(stage=LlmStage.CLASSIFY, prompt="review text"))
    assert response.text == "labeled"
    assert response.model_version == "llama-3.3-70b-versatile"
    assert response.usage.thinking_tokens == 0
    assert len(ledger.records) == 1
    assert ledger.records[0].model == "llama-3.3-70b-versatile"
