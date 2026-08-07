"""The batch pass engine — chunking, dispatch, and the run's accumulating account.

One engine for every driver that labels reviews in batches (the census and
cell drivers today): compose batches, dispatch them across a worker pool,
consume outcomes on the calling thread as futures finish. The engine owns
*how* a pass runs; what a batch means — its attempt semantics, its retry
policy, where its envelopes land — stays with the driver's ``consume``
callback, which is why the callback takes only the outcome. The two
per-driver copies this replaced had already drifted (progress modulus,
finality plumbing); the drift is now a parameter, not a fork.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field

from steamlens.contracts import (
    AspectOntology,
    LlmRequest,
    LlmStage,
    Review,
    Sink,
    StageKind,
    TokenUsage,
)
from steamlens.core.classify import (
    BatchParseResult,
    IdxFailure,
    build_classify_prompt,
    parse_classify_response,
)
from steamlens.dispatch.narration import narrate
from steamlens.llm_client import (
    GenerationIncompleteError,
    LlmClient,
    ProviderPermanentError,
)


@dataclass(slots=True)
class RunTotals:
    """The run's accumulating counters — one place, narrated and manifested."""

    batches: int = 0
    labeled: int = 0
    empty_envelopes: int = 0
    salvaged: int = 0
    repairs: int = 0
    unattributable: int = 0
    rebatched: int = 0
    isolated: int = 0
    failed_durable: int = 0
    refused_batches: int = 0
    prompt_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    model_versions_seen: set[str] = field(default_factory=set[str])


@dataclass(frozen=True, slots=True)
class BatchOutcome:
    """One dispatched batch's full account, carried from worker to writer.

    ``refusal`` is set when the provider rejected the whole request (a content
    filter, typically) — the parse then carries every idx as failed with the
    refusal as reason, no tokens were reported, and ``model_version`` is the
    empty string (nothing served the call, so the drift watch skips it).
    """

    batch: tuple[Review, ...]
    parse: BatchParseResult
    model_version: str
    finish: str
    usage: TokenUsage
    refusal: str | None = None


def chunk(reviews: Sequence[Review], n: int) -> list[tuple[Review, ...]]:
    """Consecutive batches of ``n`` (the last may be short), preserving order."""
    return [tuple(reviews[start : start + n]) for start in range(0, len(reviews), n)]


def classify_batch(
    client: LlmClient,
    ontology: AspectOntology,
    surface_index: Mapping[str, str],
    batch: tuple[Review, ...],
) -> BatchOutcome:
    """One batch through prompt → door → parse; the worker-side unit of work.

    Shared by every driver that labels with the production instrument (the
    census driver and the serving runner today) — the worker is pure
    instrument, all attempt semantics stay with each driver's consume side.

    A truncated-or-refused generation is salvaged, not lost: its spend is
    already journaled and cached, so the partial text is parsed and the finish
    reason rides the outcome. A ``ProviderPermanentError`` — the provider
    rejecting the request itself (DeepSeek's content filter, live-observed
    2026-07-20) — becomes an all-rows-failed outcome so the ordinary sweep
    isolates the offending review to its durable mark instead of the whole
    run dying on one batch forever (composition is deterministic — an abort
    here would re-form the same batch every relaunch). Provider trouble
    outliving the client's retries and budget refusals still propagate —
    those end the run, not the batch.
    """
    texts = [review.text for review in batch]
    prompt = build_classify_prompt(texts, ontology)
    try:
        response = client.complete(LlmRequest(stage=LlmStage.CLASSIFY, prompt=prompt))
        finish = response.finish_reason.value
    except GenerationIncompleteError as exc:
        response = exc.response
        finish = f"incomplete:{exc.reason.value}"
    except ProviderPermanentError as exc:
        reason = f"provider refused the request: {exc}"
        return BatchOutcome(
            batch=batch,
            parse=BatchParseResult(
                parsed=(),
                failures=tuple(IdxFailure(idx, reason) for idx in range(len(batch))),
                repairs=(),
            ),
            model_version="",
            finish="refused",
            usage=TokenUsage(prompt_tokens=0, output_tokens=0, thinking_tokens=0),
            refusal=str(exc),
        )
    return BatchOutcome(
        batch=batch,
        parse=parse_classify_response(response.text, texts, surface_index),
        model_version=response.model_version,
        finish=finish,
        usage=response.usage,
    )


def run_pass(
    batches: Sequence[tuple[Review, ...]],
    attempt: str,
    worker: Callable[[tuple[Review, ...]], BatchOutcome],
    consume: Callable[[BatchOutcome], list[Review]],
    pool: ThreadPoolExecutor,
    sink: Sink,
    *,
    stage: str,
    warmup: bool,
    progress_every: int = 10,
) -> list[Review]:
    """One labeling pass over pre-composed batches, consumed as futures finish.

    Callers own composition (the census chunks at its N, the recomposed cell
    hands its seeded batches over verbatim) and bind their attempt semantics
    into ``consume``; ``attempt`` here is the narration label only. ``warmup``
    runs the first batch synchronously before the pool opens, so the
    provider's prefix cache is seeded by one completed request instead of
    ``max_workers`` concurrent cold misses — a pilot's cost-per-review then
    measures steady-state behavior. Consumption happens as futures finish;
    total ordering is not needed because every write is per-review keyed.
    """
    total = len(batches)
    failed: list[Review] = []
    done = 0
    start_at = 0
    if warmup and batches:
        failed.extend(consume(worker(batches[0])))
        done += 1
        narrate(sink, stage, StageKind.PROGRESS, f"{attempt}: warmup batch 1/{total} consumed")
        start_at = 1
    pending: set[Future[BatchOutcome]] = {
        pool.submit(worker, batch) for batch in batches[start_at:]
    }
    try:
        while pending:
            completed, pending = wait(pending, return_when=FIRST_COMPLETED)
            for future in completed:
                failed.extend(consume(future.result()))
                done += 1
                if done % progress_every == 0 or done == total:
                    narrate(
                        sink, stage, StageKind.PROGRESS,
                        f"{attempt}: batch {done}/{total} consumed",
                    )
    except BaseException:
        # Abort means stop: queued batches must not keep dispatching (and
        # spending) behind a dying run. In-flight requests finish and cache
        # harmlessly; cancellation only stops what never started.
        for future in pending:
            future.cancel()
        raise
    return failed
