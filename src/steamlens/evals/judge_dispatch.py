"""The judge's dispatch engine — single-review, temperature-0, shared by its shells.

The judge is one instrument with two dispatch surfaces: calibration re-labels
gold's reviews (``judge_gold``), the census-sample read re-labels drawn census
reviews (``judge_sample``). Everything instrument-defining lives here so the
two runs cannot drift apart: the model pick and its measured generation
config, the single-review/temperature-0 riders (the measured −0.033
batch-composition effect must not reach the instrument), both refusal shapes
converging on the typed failure path, and the durable-mark-on-first-attempt
rule (at N=1 a malformed answer is already the isolate case — a temperature-0
retry would replay the identical cached response). The shells own what
genuinely differs: where their reviews come from, their pre-dispatch
handshakes, and their manifests.

The engine's unit is a ``JudgeItem`` — identity plus the exact text prompted —
so a shell decides what the judge reads and the engine guarantees how.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from typing import Final

from steamlens.contracts import (
    AspectOntology,
    ClassifierVersions,
    FinishReason,
    LlmRequest,
    LlmStage,
    Origin,
    Provenance,
    ReviewClassification,
    StageEvent,
    StageKind,
    TokenUsage,
)
from steamlens.core.classify import (
    CLASSIFY_RESPONSE_SCHEMA,
    BatchParseResult,
    IdxFailure,
    build_classify_prompt,
    parse_classify_response,
)
from steamlens.llm_client import (
    GenerationIncompleteError,
    LlmClient,
    LlmClientConfig,
    ModelSpec,
    ProviderEntry,
    ProviderPermanentError,
    Route,
)
from steamlens.store import Store
from steamlens.studies.label_corpus import DriftWatch, RunAbort, TeeSink

JUDGE_MODEL_ID: Final = "gemini-3-flash-preview"
"""The requested model id — the judge triple's ``model_version`` (keys are
contracts; the provider-reported version is journaled per call instead).
Picked 2026-07-23 over the design's generic "Gemini flash": the bake-off's
best-F1 flash arm against gold (0.801 at N=20, 0.789 at N=50 — the only
candidate consistently above production's 0.766) at $0.50/$3.00 per 1M."""

PROVIDER: Final = "gemini"
KEY_ENV: Final = "GEMINI_API_KEY"
# One review per request: C1's measured base already holds one worst-case
# dense review's answer, and nothing batched ever grows it.
_MAX_OUTPUT_TOKENS: Final = 2_048
# Paid-tier politeness backstop; single-review requests take minutes at this
# pace, so the worker pool, not pacing, is the real throttle.
_RPM: Final = 60
_INPUT_USD_PER_1M: Final = 0.50
_OUTPUT_USD_PER_1M: Final = 3.00
# Every text this engine dispatches labeled cleanly at scale before (gold
# passed two human annotators and the census; the census itself took 1
# durable content-filter refusal in 135K requests) — more than a handful of
# refusals in one run means a systemic request problem (a bad key, a broken
# payload), never this much toxic text.
REFUSED_LIMIT: Final = 5

_GEMINI_PARAMS: Final[dict[str, object]] = {
    "temperature": 0,
    "responseMimeType": "application/json",
    "responseSchema": CLASSIFY_RESPONSE_SCHEMA,
    "thinkingConfig": {"thinkingBudget": 0},
}
"""The bake-off's exact measured generation config for this model — constrained
decoding on the classify schema, thinking off, deterministic."""


@dataclass(frozen=True, slots=True)
class JudgeItem:
    """One review as the judge will read it — the engine's unit of work.

    ``text`` is exactly what gets prompted; the shell that built the item owns
    verifying it matches the stored review the envelope will land on (gold's
    strip-equality handshake, the sample's sha256 pin).
    """

    review_id: str
    text: str


@dataclass(slots=True)
class JudgeTotals:
    """The run's accumulating counters — one place, narrated and manifested."""

    requests: int = 0
    labeled: int = 0
    empty_envelopes: int = 0
    repairs: int = 0
    failed_durable: int = 0
    refused: int = 0
    prompt_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    model_versions_seen: set[str] = field(default_factory=set[str])


@dataclass(frozen=True, slots=True)
class JudgeOutcome:
    """One judged review's full account, carried from worker to writer.

    ``refusal`` is set when the provider rejected the request outright OR
    finished with a refusal (Gemini's safety block answers with an empty
    body rather than an error) — either way the review takes the typed
    failure path and the refusal counts toward the circuit breaker.
    """

    item: JudgeItem
    parse: BatchParseResult
    model_version: str
    finish: str
    usage: TokenUsage
    refusal: str | None = None


def build_judge_client(
    entry: ProviderEntry, budget_usd: float, client_store: Store, sink: TeeSink
) -> LlmClient:
    """The judge-route client over the *client's* store connection."""
    config = LlmClientConfig(
        routes={
            LlmStage.JUDGE: Route(
                provider=PROVIDER,
                model=JUDGE_MODEL_ID,
                max_output_tokens=_MAX_OUTPUT_TOKENS,
                params=dict(_GEMINI_PARAMS),
            )
        },
        models={
            JUDGE_MODEL_ID: ModelSpec(
                rpm=_RPM,
                rpd=None,
                input_usd_per_1m=_INPUT_USD_PER_1M,
                output_usd_per_1m=_OUTPUT_USD_PER_1M,
            )
        },
        budget_usd=budget_usd,
    )
    return LlmClient(
        config,
        client_store.responses,
        client_store.spend_ledger,
        sink,
        registry={PROVIDER: entry},
    )


def narrate(sink: TeeSink, kind: StageKind, message: str) -> None:
    """One judge-driver stage event onto the run's sink."""
    sink.emit(StageEvent(stage="judge.driver", kind=kind, message=message))


def judge_review(
    client: LlmClient,
    ontology: AspectOntology,
    surface_index: Mapping[str, str],
    item: JudgeItem,
) -> JudgeOutcome:
    """One review through prompt → door → parse; the worker-side unit of work.

    Both refusal shapes converge on the typed path: a request-level rejection
    (``ProviderPermanentError``) and a generation-level refusal (Gemini's
    safety block — a ``REFUSAL`` finish with an empty body). A truncated or
    otherwise-incomplete generation is salvaged instead: its spend is already
    journaled and cached, so the partial text is parsed and the finish reason
    rides the outcome.
    """

    def refused(reason: str) -> JudgeOutcome:
        return JudgeOutcome(
            item=item,
            parse=BatchParseResult(
                parsed=(),
                failures=(IdxFailure(0, f"provider refused the request: {reason}"),),
                repairs=(),
            ),
            model_version="",
            finish="refused",
            usage=TokenUsage(prompt_tokens=0, output_tokens=0, thinking_tokens=0),
            refusal=reason,
        )

    prompt = build_classify_prompt([item.text], ontology)
    try:
        response = client.complete(LlmRequest(stage=LlmStage.JUDGE, prompt=prompt))
        finish = response.finish_reason.value
    except GenerationIncompleteError as exc:
        if exc.reason is FinishReason.REFUSAL:
            return refused(f"generation refused (finish={exc.reason.value})")
        response = exc.response
        finish = f"incomplete:{exc.reason.value}"
    except ProviderPermanentError as exc:
        return refused(str(exc))
    return JudgeOutcome(
        item=item,
        parse=parse_classify_response(response.text, [item.text], surface_index),
        model_version=response.model_version,
        finish=finish,
        usage=response.usage,
    )


def _write_outcome(
    outcome: JudgeOutcome,
    store: Store,
    versions: ClassifierVersions,
    run: Provenance,
    totals: JudgeTotals,
    drift: DriftWatch,
    sink: TeeSink,
) -> None:
    """Consume one outcome on the main thread: envelope in, or the durable mark.

    No retry stage exists at N=1 (see the module docstring) — a parse failure
    goes straight to its failure mark, closing the review's selection under
    the judge triple.
    """
    if outcome.refusal is not None:
        totals.refused += 1
        narrate(
            sink, StageKind.WARN,
            f"provider refused review {outcome.item.review_id}: {outcome.refusal}",
        )
        if totals.refused > REFUSED_LIMIT:
            raise RunAbort(
                f"{totals.refused} provider refusals exceeds the {REFUSED_LIMIT}-request "
                f"circuit breaker — this text labeled cleanly at scale before, so "
                f"suspect a systemic request problem"
            )
    else:
        drift.check(outcome.model_version)
        totals.model_versions_seen.add(outcome.model_version)
    totals.requests += 1
    totals.prompt_tokens += outcome.usage.prompt_tokens
    totals.output_tokens += outcome.usage.output_tokens
    totals.thinking_tokens += outcome.usage.thinking_tokens
    totals.repairs += len(outcome.parse.repairs)
    for parsed in outcome.parse.parsed:
        store.labels.put(
            ReviewClassification(
                review_id=outcome.item.review_id,
                origin=Origin.SURVEY,
                versions=versions,
                run=run,
                mentions=parsed.mentions,
            )
        )
        totals.labeled += 1
        if not parsed.mentions:
            totals.empty_envelopes += 1
    for failure in outcome.parse.failures:
        store.labels.record_failure(
            outcome.item.review_id, versions, run.run_id, failure.reason
        )
        totals.failed_durable += 1
        narrate(
            sink, StageKind.WARN,
            f"review {outcome.item.review_id} took a durable mark: {failure.reason}",
        )


def dispatch_items(
    pending: Sequence[JudgeItem],
    max_workers: int,
    client: LlmClient,
    ontology: AspectOntology,
    surface_index: Mapping[str, str],
    store: Store,
    versions: ClassifierVersions,
    run: Provenance,
    totals: JudgeTotals,
    drift: DriftWatch,
    sink: TeeSink,
) -> None:
    """Single pass over the pending items, consumed as futures finish.

    The first request runs synchronously before the pool opens — one completed
    call seeds the provider's prefix cache (the ~7K codebook prefix repeats on
    every request) and sets the drift watch's baseline before concurrency.
    Abort means stop: queued requests are cancelled; in-flight ones finish and
    cache harmlessly.
    """
    total = len(pending)
    done = 0

    def worker(item: JudgeItem) -> JudgeOutcome:
        return judge_review(client, ontology, surface_index, item)

    def consume(outcome: JudgeOutcome) -> None:
        nonlocal done
        _write_outcome(outcome, store, versions, run, totals, drift, sink)
        done += 1
        if done % 25 == 0 or done == total:
            narrate(sink, StageKind.PROGRESS, f"judged {done}/{total}")

    consume(worker(pending[0]))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures: set[Future[JudgeOutcome]] = {
            pool.submit(worker, item) for item in pending[1:]
        }
        try:
            while futures:
                completed, futures = wait(futures, return_when=FIRST_COMPLETED)
                for future in completed:
                    consume(future.result())
        except BaseException:
            for future in futures:
                future.cancel()
            raise
