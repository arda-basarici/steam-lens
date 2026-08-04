"""Simulated sampling draws — execute compiled plans against stored corpus reviews.

The sampling study's executor half: ``core/sampling`` compiles the plan, and
this module performs the draw the live door would perform, against the frozen
corpus instead of the API. The study's certification argument rests on this
pairing — same compiler, same plan type, and an executor that implements the
contract's own selection rule (newest-first within a window, up to quota) —
so the convergence it measures describes the draw production ships, not a
simulation-only cousin.

Everything here is pure and deterministic. ``corpus_histogram`` builds the
snapshot a live histogram fetch would have served — contiguous monthly UTC
buckets, claimed-empty months included — with ``fetched_at`` derived from the
data (the month boundary after the newest review), never from a wall clock,
so the same corpus always compiles the same plans. "Newest-first" is modeled
as created-at descending with the review id as tie-break — the tie-break is
arbitrary but fixed, chosen for determinism, not for being a truer "newer".
The uniform-random reference draw lives here rather than in the policy
vocabulary because it is not runtime-expressible: it is the study shell's
measuring stick, seeded per draw by the caller, never a plan.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from datetime import UTC, datetime

from steamlens.contracts import (
    FetchPlan,
    HistogramBucket,
    HistogramSnapshot,
    Review,
    RollupUnit,
    SamplingPolicyKind,
)


def corpus_histogram(reviews: Sequence[Review]) -> HistogramSnapshot:
    """Build the histogram snapshot a live fetch would have served for this pool.

    Buckets are contiguous UTC calendar months from the oldest review's month
    through the newest's, zero-claim months included — mirroring the
    contiguous series Steam serves, so the compiler sees the same shape either
    way. Counts split by the review's overall vote, matching the live
    histogram's up/down series. ``recent_daily`` and ``past_events`` are empty
    by honest construction: the corpus predates this project's window
    tracking and holds no marked-window reviews (the design constraint that
    forces the marked-floor tuning onto fresh fetches). Raises ``ValueError``
    on an empty pool or a pool spanning more than one game — either means the
    caller wired the wrong reviews, and a histogram built from them would
    compile confidently wrong plans.
    """
    if not reviews:
        raise ValueError("cannot build a histogram from an empty review pool")
    app_ids = {review.app_id for review in reviews}
    if len(app_ids) != 1:
        raise ValueError(
            f"review pool spans app_ids {sorted(app_ids)} — a histogram "
            "describes exactly one game"
        )

    months: dict[tuple[int, int], list[int]] = {}
    for review in reviews:
        created = review.created_at.astimezone(UTC)
        counts = months.setdefault((created.year, created.month), [0, 0])
        counts[0 if review.voted_up else 1] += 1

    first = min(months)
    last = max(months)
    buckets: list[HistogramBucket] = []
    year, month = first
    while (year, month) <= last:
        up, down = months.get((year, month), [0, 0])
        buckets.append(
            HistogramBucket(
                start=datetime(year, month, 1, tzinfo=UTC),
                recommendations_up=up,
                recommendations_down=down,
            )
        )
        year, month = _next_month(year, month)

    return HistogramSnapshot(
        app_id=app_ids.pop(),
        rollup_unit=RollupUnit.MONTH,
        rollups=tuple(buckets),
        recent_daily=(),
        past_events=(),
        fetched_at=datetime(*_next_month(*last), 1, tzinfo=UTC),
    )


def execute_plan(reviews: Sequence[Review], plan: FetchPlan) -> tuple[Review, ...]:
    """Perform ``plan``'s draw against the pool — the simulated fetch.

    Cursor-prefix plans take the newest-first prefix of the whole pool, up to
    the policy's target (the whole pool when the target exceeds it — the
    take-all the plan could not know about). Windowed plans take each
    window's members newest-first up to its quota, windows in plan order —
    the contract's selection rule, verbatim. A windowed quota the pool cannot
    fill raises ``ValueError`` rather than under-delivering silently: study
    plans are compiled from a histogram built off this same pool, so a
    shortfall means the histogram and the pool disagree — a wiring bug, not a
    sampling outcome. Also raises on an empty pool and on a pool whose game is
    not the plan's — both wiring bugs, never draws.
    """
    if not reviews:
        raise ValueError("cannot execute a plan against an empty review pool")
    mismatched = {review.app_id for review in reviews if review.app_id != plan.app_id}
    if mismatched:
        raise ValueError(
            f"plan is for app_id {plan.app_id} but the pool holds reviews "
            f"from {sorted(mismatched)}"
        )
    pool = newest_first(reviews)
    if plan.policy.kind is SamplingPolicyKind.CURSOR_PREFIX:
        return tuple(pool[: plan.policy.target_size])

    drawn: list[Review] = []
    for window in plan.windows:
        members = [
            review
            for review in pool
            if window.start <= review.created_at < window.end
        ]
        if len(members) < window.quota:
            raise ValueError(
                f"window {window.start:%Y-%m-%d}..{window.end:%Y-%m-%d} of app_id "
                f"{plan.app_id} holds {len(members)} reviews but owes quota "
                f"{window.quota} — the plan's histogram disagrees with this pool"
            )
        drawn.extend(members[: window.quota])
    return tuple(drawn)


def uniform_reference_draw(
    reviews: Sequence[Review], target_size: int, *, seed: int
) -> tuple[Review, ...]:
    """The study's measuring stick: a seeded uniform-random draw from the pool.

    Not runtime-expressible — Steam offers no random access — so this never
    compiles to a plan; it exists to give every raced policy the textbook
    baseline to be judged against. The pool is put in canonical newest-first
    order before sampling so the draw depends only on ``(reviews, target_size,
    seed)``, never on the caller's iteration order. A target at or beyond the
    pool size returns the whole pool, mirroring the planner's take-all
    behavior. Raises ``ValueError`` on an empty pool or a non-positive target
    — both are caller bugs, not draws.
    """
    if not reviews:
        raise ValueError("cannot draw from an empty review pool")
    if target_size < 1:
        raise ValueError(f"target_size is {target_size} — a draw must ask for at least one review")
    pool = newest_first(reviews)
    if target_size >= len(pool):
        return tuple(pool)
    return tuple(random.Random(seed).sample(pool, target_size))


def newest_first(reviews: Sequence[Review]) -> list[Review]:
    """The pool in the simulation's canonical order — created-at descending.

    Models the API's newest-first return order offline. Ties (same second)
    break by review id, descending as strings — determinism is the point of
    the tie-break, not chronology. Public because it *is* the study package's
    canonical-order definition: every seeded operation over a pool (the draws
    here, the mixing blend) sorts through this one function, so "depends only
    on the pool's contents, never the caller's iteration order" stays a single
    fact.
    """
    return sorted(reviews, key=lambda review: (review.created_at, review.review_id), reverse=True)


def _next_month(year: int, month: int) -> tuple[int, int]:
    """The calendar month after ``(year, month)`` — pure month arithmetic."""
    if month == 12:
        return year + 1, 1
    return year, month + 1
