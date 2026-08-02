"""The plan compiler — histogram + policy into an executable ``FetchPlan``.

This is the sampling study's certification target: the same pure function
plans production draws at deployment and simulated draws in the study, so the
measured convergence describes code that actually ships. It is deterministic
by construction — no clock, no randomness, no I/O — and all integer
arithmetic, so identical inputs compile byte-identical plans on any platform.

Windows come from the histogram's full-lifetime rollup series alone; the
last-30-days daily strip is deliberately ignored, because it overlaps the
rollup tail and planning from two overlapping series would double-count the
recent weeks. Buckets tile time contiguously (each window ends where the next
bucket starts; the last runs to the snapshot's fetch time), and a bucket
claiming zero reviews gets no window — its span is knowingly left unfetched
rather than spending requests on claimed emptiness. The claims are Steam's
own and are not trusted as ground truth: the compiler caps quotas at claimed
volume so a plan never *asks* for more than the evidence supports, and
under-delivery at execution time is the executor's contract to disclose.

Quota allocation is capped largest-remainder: proportional to each policy's
weights (claimed volume for time-proportional, a flat weight for
equal-per-window), with any share a small bucket cannot absorb re-flowing to
the buckets that can. Remainder ties break toward the earlier bucket — an
arbitrary rule, fixed so that determinism never depends on dict order.
"""

from __future__ import annotations

from collections.abc import Sequence

from steamlens.contracts import (
    FetchPlan,
    HistogramSnapshot,
    PlannedWindow,
    SamplingPolicy,
    SamplingPolicyKind,
)


def compile_plan(histogram: HistogramSnapshot, policy: SamplingPolicy) -> FetchPlan:
    """Compile ``policy`` against ``histogram`` into the plan an executor runs.

    Cursor-prefix policies plan no windows — the draw is "walk newest-first,
    take ``target_size``" and needs only the budget the policy already
    carries. Windowed policies get one quota-bearing window per non-empty
    rollup bucket, chronological, quotas summing to ``target_size`` — or to
    the histogram's whole claimed supply when that is smaller, the take-all
    case. Raises ``ValueError`` on a non-positive ``target_size`` and on a
    windowed policy over a histogram claiming no reviews at all: there is
    nothing to plan, and inventing windows from an empty claim would let a
    caller "succeed" at drawing nothing.
    """
    if policy.target_size < 1:
        raise ValueError(
            f"target_size is {policy.target_size} — a sampling policy must ask "
            "for at least one review"
        )
    if policy.kind is SamplingPolicyKind.CURSOR_PREFIX:
        return FetchPlan(
            app_id=histogram.app_id,
            policy=policy,
            windows=(),
            histogram_fetched_at=histogram.fetched_at,
        )

    buckets = sorted(histogram.rollups, key=lambda bucket: bucket.start)
    ends = [bucket.start for bucket in buckets[1:]] + [histogram.fetched_at]
    populated = [
        (bucket, end, bucket.recommendations_up + bucket.recommendations_down)
        for bucket, end in zip(buckets, ends, strict=True)
        if bucket.recommendations_up + bucket.recommendations_down > 0
    ]
    if not populated:
        raise ValueError(
            f"app_id {histogram.app_id}: histogram claims no reviews in any "
            "rollup bucket — a windowed plan has nothing to draw from"
        )

    volumes = [volume for _, _, volume in populated]
    proportional = policy.kind is SamplingPolicyKind.TIME_PROPORTIONAL
    weights = volumes if proportional else [1] * len(volumes)
    quotas = _allocate_quotas(weights, volumes, policy.target_size)

    windows = tuple(
        PlannedWindow(start=bucket.start, end=end, quota=quota)
        for (bucket, end, _), quota in zip(populated, quotas, strict=True)
        if quota > 0
    )
    return FetchPlan(
        app_id=histogram.app_id,
        policy=policy,
        windows=windows,
        histogram_fetched_at=histogram.fetched_at,
    )


def _allocate_quotas(weights: Sequence[int], caps: Sequence[int], target: int) -> list[int]:
    """Split ``target`` units across buckets proportional to ``weights``, capped.

    Integer largest-remainder apportionment with caps: each bucket's ideal
    share is ``target`` weighted by ``weights``; floors are handed out first,
    the remainder goes one unit at a time to the largest fractional parts,
    ties toward the earlier bucket. A bucket never receives more than its cap
    (its claimed volume); share it cannot absorb re-flows proportionally to
    the unsaturated buckets on further passes, so the result always sums to
    ``min(target, sum(caps))``. Preconditions are the caller's — parallel
    sequences, every weight and cap positive — and violating them raises
    rather than misallocating.

    >>> _allocate_quotas([60, 30, 10], [60, 30, 10], 10)
    [6, 3, 1]
    >>> _allocate_quotas([1, 1, 1], [5, 5, 5], 10)  # ties toward earlier
    [4, 3, 3]
    >>> _allocate_quotas([1, 1, 1], [2, 100, 100], 30)  # cap re-flows
    [2, 14, 14]
    """
    if len(weights) != len(caps):
        raise ValueError(f"{len(weights)} weights against {len(caps)} caps")
    if any(weight < 1 for weight in weights) or any(cap < 1 for cap in caps):
        raise ValueError("every weight and cap must be positive")

    quotas = [0] * len(weights)
    remaining = min(target, sum(caps))
    while remaining > 0:
        active = [i for i in range(len(weights)) if quotas[i] < caps[i]]
        total_weight = sum(weights[i] for i in active)
        grants: dict[int, int] = {}
        for i in active:
            ideal = remaining * weights[i]
            grants[i] = min(ideal // total_weight, caps[i] - quotas[i])
        leftover = remaining - sum(grants.values())
        by_remainder = sorted(
            active, key=lambda i: (-(remaining * weights[i] % total_weight), i)
        )
        for i in by_remainder:
            if leftover == 0:
                break
            if quotas[i] + grants[i] < caps[i]:
                grants[i] += 1
                leftover -= 1
        for i in active:
            quotas[i] += grants[i]
        remaining -= sum(grants.values())
    return quotas
