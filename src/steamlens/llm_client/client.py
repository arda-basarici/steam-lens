"""The one door to models — routing, guards, accounting, and pacing in one sync client.

Responsibility map, placed once: adapters *normalize* (finish reason, the usage
split), this client *enforces and accounts* above them, provider-independent.
``complete`` is the whole public surface — a stage-keyed request in, a
normalized response out, with the archive consulted first, the budget reserved
worst-case before dispatch and settled to actual after, the daily quota derived
by ledger query, dispatch paced per model, transients retried with bounded
jittered backoff, and every paid call journaled and archived before any guard is
allowed to raise.

Threading: ``complete`` is safe to call from many threads. All mutable state —
the budget reservation, the in-flight quota counts, the pacing slots, and every
archive/ledger touch — lives behind one lock, so the bound archive and ledger
implementations may stay dumb. The worker pool itself belongs to the *caller*
(``max_workers`` is caller config, defaulting to sequential); this client only
promises to stay correct underneath one.
"""

from __future__ import annotations

import hashlib
import json
import random
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from threading import Lock

from steamlens.contracts import (
    FinishReason,
    LlmRequest,
    LlmResponse,
    LlmStage,
    MetricEvent,
    ResponseArchive,
    Sink,
    SpendLedger,
    SpendRecord,
    StageEvent,
    StageKind,
    TokenUsage,
)
from steamlens.llm_client.config import LlmClientConfig, ModelSpec, Route
from steamlens.llm_client.errors import (
    AtCapacityError,
    GenerationIncompleteError,
    LlmConfigError,
    LlmUnavailableError,
    ProviderTransientError,
)
from steamlens.llm_client.registry import PROVIDERS, ProviderEntry

# Six attempts at base 2s: ~30s expected / ~60s worst-case patience per request
# under full jitter — matching the Gemini SDK's own retry ceiling (≤60s max
# delay, per the troubleshooting docs). Widened from 4/1s during the 2026-07-23
# capacity event, where load-shed 503s arrived faster than full jitter's
# near-zero draws and a single request could exhaust its attempts inside a
# second, aborting a run mid-window.
_MAX_ATTEMPTS = 6
_BACKOFF_BASE_S = 2.0
_BACKOFF_CAP_S = 30.0
# Pessimistic English tokenization for the worst-case reserve — real prompts run
# nearer 4 chars/token, so estimating at 3 over-reserves, never under.
_PESSIMISTIC_CHARS_PER_TOKEN = 3


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _archive_key(model: str, payload: Mapping[str, object]) -> str:
    """Content hash of (request payload + model) — the bought-response identity.

    Sorted-key JSON makes the hash independent of dict insertion order; the
    model rides inside because the same payload sent to a different model is a
    different purchase.
    """
    canonical = json.dumps(
        {"model": model, "payload": payload}, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _quota_window_start(now: datetime, reset_utc_hour: int) -> datetime:
    """The most recent daily-quota rollover at or before ``now``."""
    start = now.replace(hour=reset_utc_hour, minute=0, second=0, microsecond=0)
    return start if start <= now else start - timedelta(days=1)


def _worst_case_cost(prompt: str, route: Route, spec: ModelSpec) -> float:
    """The reservation estimate: pessimistic prompt tokens, full output ceiling."""
    prompt_tokens = -(-len(prompt) // _PESSIMISTIC_CHARS_PER_TOKEN)
    return (
        prompt_tokens * spec.input_usd_per_1m
        + route.max_output_tokens * spec.output_usd_per_1m
    ) / 1_000_000


def _actual_cost(usage: TokenUsage, spec: ModelSpec) -> float:
    """What the call really cost — thinking tokens billed at the output rate."""
    return (
        usage.prompt_tokens * spec.input_usd_per_1m
        + (usage.output_tokens + usage.thinking_tokens) * spec.output_usd_per_1m
    ) / 1_000_000


class LlmClient:
    """The provider seam: every model call in the system goes through ``complete``.

    Construction validates the dial against the registry — an unknown provider
    name is a startup failure (``LlmConfigError``), never a surprise mid-run.
    ``registry``, ``now``, ``sleep``, and ``rng`` are injection seams: tests bind
    a fake provider, a fixed clock, a recording sleep, and a seeded RNG; real
    composition leaves the defaults.
    """

    def __init__(
        self,
        config: LlmClientConfig,
        archive: ResponseArchive,
        ledger: SpendLedger,
        sink: Sink,
        *,
        registry: Mapping[str, ProviderEntry] | None = None,
        now: Callable[[], datetime] = _utc_now,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
    ) -> None:
        resolved = PROVIDERS if registry is None else registry
        for stage, route in config.routes.items():
            if route.provider not in resolved:
                raise LlmConfigError(
                    f"stage {stage!r} routes to unknown provider {route.provider!r}; "
                    f"registered: {sorted(resolved)}"
                )
        self._config = config
        self._archive = archive
        self._ledger = ledger
        self._sink = sink
        self._registry = dict(resolved)
        self._now = now
        self._sleep = sleep
        self._rng = rng if rng is not None else random.Random()
        self._started_at = now()
        self._lock = Lock()
        self._reserved_usd = 0.0
        self._inflight: dict[str, int] = {}
        self._next_slot_monotonic: dict[str, float] = {}

    def complete(self, request: LlmRequest) -> LlmResponse:
        """One stage-keyed completion — cached, guarded, accounted.

        Returns the normalized response on a clean finish. Raises
        ``AtCapacityError`` when our own budget or daily-quota reserve refuses
        (before any money moves), ``LlmUnavailableError`` when provider
        transients outlive the retry loop, and ``GenerationIncompleteError``
        when the provider answered without finishing cleanly — that spend is
        already journaled and cached, so a re-ask hits the cache instead of
        re-paying for the same truncation.
        """
        route = self._config.routes.get(request.stage)
        if route is None:
            raise LlmConfigError(f"no route configured for stage {request.stage!r}")
        entry = self._registry[route.provider]
        spec = self._config.models[route.model]

        payload = entry.build_payload(
            model=route.model,
            prompt=request.prompt,
            max_output_tokens=route.max_output_tokens,
            params=route.params,
        )
        key = _archive_key(route.model, payload)
        with self._lock:
            archived = self._archive.get(key)
        if archived is not None:
            self._emit_metric(request.stage, "cache_hit", 1.0, "count")
            return self._guard_finish(entry.parse(archived))

        estimate = _worst_case_cost(request.prompt, route, spec)
        pace_wait = self._reserve(request.stage, route.model, spec, estimate)
        try:
            if pace_wait > 0:
                self._sleep(pace_wait)
            dispatched = time.monotonic()
            raw = self._send_with_retry(entry, route.model, payload, request.stage)
            latency_s = time.monotonic() - dispatched
            response = entry.parse(raw)
        except BaseException:
            self._release(route.model, estimate)
            raise
        cost = _actual_cost(response.usage, spec)
        record = SpendRecord(
            created_at=self._now(),
            stage=request.stage,
            model=route.model,
            model_version=response.model_version,
            usage=response.usage,
            cost=cost,
        )
        with self._lock:
            # Settle inside one lock hold: the journal row replaces both the
            # reservation and the in-flight count, so no interleaving can see
            # the spend counted twice or not at all.
            self._reserved_usd -= estimate
            self._inflight[route.model] -= 1
            self._ledger.append(record)
            self._archive.put(key, raw)
        self._emit_metric(request.stage, "prompt_tokens", response.usage.prompt_tokens, "tokens")
        self._emit_metric(request.stage, "output_tokens", response.usage.output_tokens, "tokens")
        self._emit_metric(
            request.stage, "thinking_tokens", response.usage.thinking_tokens, "tokens"
        )
        self._emit_metric(request.stage, "cost", cost, "usd")
        self._emit_metric(request.stage, "latency", latency_s, "s")
        return self._guard_finish(response)

    def _reserve(self, stage: LlmStage, model: str, spec: ModelSpec, estimate: float) -> float:
        """Admit or refuse one dispatch, atomically; returns the pacing wait in seconds.

        Daily headroom counts journaled calls *plus* in-flight ones — the ledger
        alone lags dispatch, and that lag is exactly the window where concurrent
        workers would oversubscribe the quota. The pacing slot is claimed inside
        the same lock hold (each dispatch books the next free slot), while the
        sleep itself happens outside so pacing never serializes the pool.
        """
        with self._lock:
            if spec.rpd is not None:
                window_start = _quota_window_start(self._now(), self._config.daily_reset_utc_hour)
                used = self._ledger.request_count_since(model, window_start)
                inflight = self._inflight.get(model, 0)
                if used + inflight >= spec.rpd:
                    raise AtCapacityError(
                        f"model {model!r} daily quota exhausted: {used} journaled + "
                        f"{inflight} in flight of {spec.rpd} per day"
                    )
            budget = self._config.budget_usd
            if budget is not None:
                spent = self._ledger.cost_since(self._started_at)
                if spent + self._reserved_usd + estimate > budget:
                    raise AtCapacityError(
                        f"budget cap would be exceeded: {spent:.4f} spent + "
                        f"{self._reserved_usd:.4f} reserved + {estimate:.4f} estimated "
                        f"> {budget:.4f} USD (stage {stage!r})"
                    )
            self._reserved_usd += estimate
            self._inflight[model] = self._inflight.get(model, 0) + 1
            interval = 60.0 / spec.rpm
            now_m = time.monotonic()
            slot = max(now_m, self._next_slot_monotonic.get(model, 0.0))
            self._next_slot_monotonic[model] = slot + interval
            return slot - now_m

    def _release(self, model: str, estimate: float) -> None:
        """Undo a reservation whose dispatch failed — no spend happened."""
        with self._lock:
            self._reserved_usd -= estimate
            self._inflight[model] -= 1

    def _send_with_retry(
        self, entry: ProviderEntry, model: str, payload: dict[str, object], stage: LlmStage
    ) -> str:
        """Dispatch with bounded full-jitter backoff; transients only, then give up loud."""
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                return entry.send(model=model, payload=payload)
            except ProviderTransientError as exc:
                if attempt == _MAX_ATTEMPTS:
                    raise LlmUnavailableError(
                        f"provider transient trouble outlived {_MAX_ATTEMPTS} attempts: {exc}"
                    ) from exc
                delay = min(_BACKOFF_CAP_S, _BACKOFF_BASE_S * 2 ** (attempt - 1))
                delay *= self._rng.random()
                self._sink.emit(
                    StageEvent(
                        stage=f"llm.{stage}",
                        kind=StageKind.WARN,
                        message=(
                            f"transient provider failure (attempt {attempt}/{_MAX_ATTEMPTS}), "
                            f"retrying in {delay:.1f}s: {exc}"
                        ),
                    )
                )
                self._sleep(delay)
        raise AssertionError("unreachable: the retry loop returns or raises")

    def _guard_finish(self, response: LlmResponse) -> LlmResponse:
        """The truncation/refusal guard — only a clean stop passes as a result."""
        if response.finish_reason is not FinishReason.STOP:
            raise GenerationIncompleteError(response.finish_reason, response)
        return response

    def _emit_metric(self, stage: LlmStage, name: str, value: float, unit: str) -> None:
        self._sink.emit(MetricEvent(stage=f"llm.{stage}", name=name, value=value, unit=unit))
