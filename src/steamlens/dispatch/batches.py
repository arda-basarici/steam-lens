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

from collections.abc import Callable, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field

from steamlens.contracts import Review, Sink, StageKind, TokenUsage
from steamlens.core.classify import BatchParseResult
from steamlens.dispatch.narration import narrate


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
