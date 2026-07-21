"""Behavioral claims on the LLM door — guards, accounting, cache, and the hammers.

The two hammer tests are the commit's load-bearing claims: under a racing
thread pool, admissions never overshoot the daily quota or the budget cap, and
they never *undershoot* either — an exact admission count catches both a racy
check-then-spend and a leaked reservation/in-flight count, without reaching
into the client's private state.
"""

from __future__ import annotations

import json
import random
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest

from steamlens.contracts import (
    FinishReason,
    LlmRequest,
    LlmResponse,
    LlmStage,
    SinkEvent,
    StageEvent,
    StageKind,
    TokenUsage,
)
from steamlens.llm_client import (
    AtCapacityError,
    GenerationIncompleteError,
    InMemoryResponseArchive,
    InMemorySpendLedger,
    LlmClient,
    LlmClientConfig,
    LlmConfigError,
    LlmUnavailableError,
    ModelSpec,
    ProviderEntry,
    ProviderPayload,
    ProviderTransientError,
    Route,
)

_USAGE = TokenUsage(prompt_tokens=100, output_tokens=50, thinking_tokens=25)
_EPOCH = datetime(2000, 1, 1, tzinfo=UTC)  # a `since` before every test's spend


class FakeProvider:
    """A scripted vendor: JSON wire format, failure injection, a sent-payload log."""

    def __init__(
        self,
        *,
        finish: FinishReason = FinishReason.STOP,
        transient_failures: int = 0,
        usage: TokenUsage = _USAGE,
        send_delay_s: float = 0.0,
    ) -> None:
        self.sent: list[dict[str, object]] = []
        self._finish = finish
        self._transient_remaining = transient_failures
        self._usage = usage
        self._send_delay_s = send_delay_s

    def entry(self) -> ProviderEntry:
        return ProviderEntry(build_payload=self._build, send=self._send, parse=self._parse)

    def _build(
        self, *, model: str, prompt: str, max_output_tokens: int, params: dict[str, object]
    ) -> dict[str, object]:
        return {"model": model, "prompt": prompt, "max_output_tokens": max_output_tokens, **params}

    def _send(self, *, model: str, payload: ProviderPayload) -> str:
        if self._transient_remaining > 0:
            self._transient_remaining -= 1
            raise ProviderTransientError("fake 429")
        if self._send_delay_s:
            time.sleep(self._send_delay_s)
        self.sent.append(dict(payload))
        return json.dumps(
            {
                "text": f"reply to {payload['prompt']}",
                "model_version": f"{model}-001",
                "finish": str(self._finish),
                "usage": [
                    self._usage.prompt_tokens,
                    self._usage.output_tokens,
                    self._usage.thinking_tokens,
                ],
            }
        )

    def _parse(self, raw: str) -> LlmResponse:
        data = json.loads(raw)
        u = data["usage"]
        return LlmResponse(
            text=data["text"],
            model_version=data["model_version"],
            finish_reason=FinishReason(data["finish"]),
            usage=TokenUsage(prompt_tokens=u[0], output_tokens=u[1], thinking_tokens=u[2]),
        )


class CollectingSink:
    """Satisfies ``Sink`` structurally; keeps every event for assertions."""

    def __init__(self) -> None:
        self.events: list[SinkEvent] = []

    def emit(self, event: SinkEvent) -> None:
        self.events.append(event)


def _config(
    *,
    rpd: int | None = None,
    budget: float | None = None,
    rpm: int = 100_000,
    max_out: int = 1000,
    model: str = "fake-model",
) -> LlmClientConfig:
    """One CLASSIFY route on a fake model priced 1/2 USD per 1M input/output tokens."""
    return LlmClientConfig(
        routes={
            LlmStage.CLASSIFY: Route(provider="fake", model=model, max_output_tokens=max_out)
        },
        models={
            model: ModelSpec(rpm=rpm, rpd=rpd, input_usd_per_1m=1.0, output_usd_per_1m=2.0)
        },
        budget_usd=budget,
    )


def _client(
    provider: FakeProvider,
    config: LlmClientConfig,
    *,
    cache: InMemoryResponseArchive | None = None,
    record_sleeps: list[float] | None = None,
) -> tuple[LlmClient, InMemorySpendLedger, CollectingSink]:
    """A client on the fake registry, no-op sleep (or a recording one), seeded RNG."""
    ledger = InMemorySpendLedger()
    sink = CollectingSink()
    sleeps = record_sleeps

    def _sleep(seconds: float) -> None:
        if sleeps is not None:
            sleeps.append(seconds)

    client = LlmClient(
        config,
        cache if cache is not None else InMemoryResponseArchive(),
        ledger,
        sink,
        registry={"fake": provider.entry()},
        sleep=_sleep,
        rng=random.Random(7),
    )
    return client, ledger, sink


def _request(prompt: str = "label this review") -> LlmRequest:
    return LlmRequest(stage=LlmStage.CLASSIFY, prompt=prompt)


# --- construction-time validation -------------------------------------------


def test_unknown_provider_fails_at_construction() -> None:
    """A route naming an unregistered provider is a startup failure, not a run failure."""
    with pytest.raises(LlmConfigError, match="unknown provider"):
        LlmClient(
            _config(),
            InMemoryResponseArchive(),
            InMemorySpendLedger(),
            CollectingSink(),
            registry={},
        )


def test_route_to_missing_model_spec_fails_in_config() -> None:
    """A route referencing a model with no spec row fails when the config is built."""
    with pytest.raises(LlmConfigError, match="no ModelSpec"):
        LlmClientConfig(
            routes={LlmStage.CLASSIFY: Route(provider="fake", model="ghost", max_output_tokens=1)},
            models={},
        )


def test_unrouted_stage_raises() -> None:
    """A request for a stage the dial doesn't serve fails typed, not with a KeyError."""
    client, _, _ = _client(FakeProvider(), _config())
    with pytest.raises(LlmConfigError, match="no route"):
        client.complete(LlmRequest(stage=LlmStage.JUDGE, prompt="judge this"))


# --- the happy path and the cache --------------------------------------------


def test_happy_path_journals_actual_cost_and_returns_response() -> None:
    """A clean call returns the normalized response and journals the settled cost."""
    provider = FakeProvider()
    client, ledger, sink = _client(provider, _config())
    response = client.complete(_request())
    assert response.text == "reply to label this review"
    assert response.model_version == "fake-model-001"
    assert response.usage == _USAGE
    # 100 prompt tokens @ 1/1M + (50 output + 25 thinking) @ 2/1M — thinking bills as output.
    expected_cost = (100 * 1.0 + 75 * 2.0) / 1_000_000
    assert len(ledger.records) == 1
    row = ledger.records[0]
    assert row.cost == pytest.approx(expected_cost)
    assert row.model == "fake-model"
    assert row.model_version == "fake-model-001"
    cost_metrics = [e for e in sink.events if not isinstance(e, StageEvent) and e.name == "cost"]
    assert len(cost_metrics) == 1


def test_cache_hit_skips_send_and_ledger() -> None:
    """The same request twice buys once: one send, one journal row, then a hit."""
    provider = FakeProvider()
    client, ledger, _ = _client(provider, _config())
    first = client.complete(_request())
    second = client.complete(_request())
    assert first == second
    assert len(provider.sent) == 1
    assert ledger.request_count_since("fake-model", _EPOCH) == 1


def test_cache_does_not_leak_across_models() -> None:
    """The model rides inside the cache key: same prompt, different model, fresh buy."""
    shared_cache = InMemoryResponseArchive()
    provider = FakeProvider()
    client_a, _, _ = _client(provider, _config(model="fake-model"), cache=shared_cache)
    client_b, _, _ = _client(provider, _config(model="fake-model-2"), cache=shared_cache)
    client_a.complete(_request())
    client_b.complete(_request())
    assert len(provider.sent) == 2


def test_incomplete_generation_is_paid_cached_and_raised() -> None:
    """A truncated answer still cost money: journaled and cached first, then raised —
    and a re-ask raises from the cache without re-paying."""
    provider = FakeProvider(finish=FinishReason.LENGTH)
    client, ledger, _ = _client(provider, _config())
    with pytest.raises(GenerationIncompleteError) as excinfo:
        client.complete(_request())
    assert excinfo.value.reason is FinishReason.LENGTH
    assert excinfo.value.response.usage == _USAGE
    assert ledger.request_count_since("fake-model", _EPOCH) == 1
    with pytest.raises(GenerationIncompleteError):
        client.complete(_request())
    assert len(provider.sent) == 1  # the second failure came from the cache


# --- retries ------------------------------------------------------------------


def test_transients_are_retried_then_succeed_with_warn_narration() -> None:
    """Two fake 429s are absorbed by the retry loop; the caller sees only success,
    the sink sees the WARN story."""
    provider = FakeProvider(transient_failures=2)
    client, ledger, sink = _client(provider, _config())
    response = client.complete(_request())
    assert response.finish_reason is FinishReason.STOP
    assert ledger.cost_since(_EPOCH) > 0
    warns = [e for e in sink.events if isinstance(e, StageEvent) and e.kind is StageKind.WARN]
    assert len(warns) == 2


def test_transient_exhaustion_surfaces_unavailable_and_releases_the_reservation() -> None:
    """Exhausted retries raise LlmUnavailableError with nothing journaled — and the
    reservation is released, so the SAME client's next call still fits a budget
    sized for one call (a leaked reservation would refuse it at capacity)."""
    est = (1 * 1.0 + 1000 * 2.0) / 1_000_000  # 1-token prompt, 1000-token ceiling
    # exactly _MAX_ATTEMPTS failures: the first call exhausts, then the fake heals
    provider = FakeProvider(transient_failures=4)
    client, ledger, _ = _client(provider, _config(budget=est * 1.5))
    with pytest.raises(LlmUnavailableError):
        client.complete(_request("hi"))  # 2 chars -> 1 estimated token
    assert ledger.cost_since(_EPOCH) == 0
    client.complete(_request("hi"))  # would raise AtCapacityError on a leak


# --- capacity guards ----------------------------------------------------------


def test_budget_cap_refuses_before_any_send() -> None:
    """AtCapacityError is our reserve refusing: no request leaves the building."""
    provider = FakeProvider()
    client, ledger, _ = _client(provider, _config(budget=0.0000001))
    with pytest.raises(AtCapacityError, match="budget cap"):
        client.complete(_request())
    assert provider.sent == []
    assert ledger.cost_since(_EPOCH) == 0


def test_daily_quota_refuses_at_the_cap() -> None:
    """rpd admits exactly rpd distinct calls, then refuses typed."""
    provider = FakeProvider()
    client, _, _ = _client(provider, _config(rpd=2))
    client.complete(_request("one"))
    client.complete(_request("two"))
    with pytest.raises(AtCapacityError, match="daily quota"):
        client.complete(_request("three"))
    assert len(provider.sent) == 2


def test_reservation_settles_to_actual_cost() -> None:
    """Worst-case is reserved, actual is journaled: a budget too small for two
    worst-cases still serves two calls once the first settles cheap."""
    est = (7 * 1.0 + 1000 * 2.0) / 1_000_000  # 19-char prompts -> 7 estimated tokens
    actual = (100 * 1.0 + 75 * 2.0) / 1_000_000
    budget = est + actual + est * 0.5  # fits est+actual, never est+est
    assert budget < 2 * est
    provider = FakeProvider()
    client, ledger, _ = _client(provider, _config(budget=budget))
    client.complete(_request("one one one one one"))
    client.complete(_request("two two two two two"))
    assert ledger.request_count_since("fake-model", _EPOCH) == 2


# --- the hammers --------------------------------------------------------------


def test_hammer_daily_quota_admits_exactly_rpd_under_racing_threads() -> None:
    """8 racing workers, 50 distinct calls, rpd=25: exactly 25 succeed. Overshoot
    means the used+in-flight admission check races; undershoot means an in-flight
    count leaked."""
    provider = FakeProvider(send_delay_s=0.001)
    client, ledger, _ = _client(provider, _config(rpd=25))

    def call(i: int) -> str:
        try:
            client.complete(_request(f"prompt {i}"))
            return "ok"
        except AtCapacityError:
            return "capacity"

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(call, range(50)))
    assert results.count("ok") == 25
    assert results.count("capacity") == 25
    assert ledger.request_count_since("fake-model", _EPOCH) == 25


def test_hammer_budget_admits_exactly_the_cap_under_racing_threads() -> None:
    """Actual cost tuned equal to the worst-case estimate, budget set to 25 calls:
    exactly 25 succeed under race. More means check-then-spend raced; fewer means
    a reservation leaked."""
    # 3-char prompts -> exactly 1 estimated token; usage makes actual == estimate.
    usage = TokenUsage(prompt_tokens=1, output_tokens=900, thinking_tokens=100)
    per_call = (1 * 1.0 + 1000 * 2.0) / 1_000_000
    provider = FakeProvider(send_delay_s=0.001, usage=usage)
    client, ledger, _ = _client(provider, _config(budget=25 * per_call + 1e-9))

    def call(i: int) -> str:
        try:
            client.complete(_request(f"a{i:02d}"))  # 3 chars, all distinct
            return "ok"
        except AtCapacityError:
            return "capacity"

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(call, range(50)))
    assert results.count("ok") == 25
    assert results.count("capacity") == 25
    assert ledger.cost_since(_EPOCH) == pytest.approx(25 * per_call)


# --- pacing -------------------------------------------------------------------


def test_pacing_spaces_dispatches_at_the_model_rpm() -> None:
    """rpm=60 books one dispatch slot per second. The injected sleep records
    instead of waiting, so real time barely advances and the booked slots pile
    up: the second call waits ~1s, the third ~2s — which is exactly the claim,
    each dispatch books the next free slot."""
    sleeps: list[float] = []
    provider = FakeProvider()
    client, _, _ = _client(provider, _config(rpm=60), record_sleeps=sleeps)
    client.complete(_request("one"))
    client.complete(_request("two"))
    client.complete(_request("three"))
    assert len(sleeps) == 2  # the first call dispatches immediately
    assert 0.9 < sleeps[0] <= 1.0
    assert 1.9 < sleeps[1] <= 2.0
