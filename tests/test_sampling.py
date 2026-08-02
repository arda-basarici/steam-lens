"""Plan-compiler tests — the sampling core's behavioral claims.

Every test builds a ``HistogramSnapshot`` directly (pure core: data in → data
out) and asserts one property of ``compile_plan``: the cursor plan's windowless
shape, proportional and equal allocation, exact budget sums under rounding,
the claimed-volume cap with re-flow, the take-all case (which is how the
micro-window design stays expressible), contiguous window tiling with claimed-
empty spans left unplanned, chronological determinism, and the loud guards.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from steamlens.contracts import (
    FetchPlan,
    HistogramBucket,
    HistogramSnapshot,
    RollupUnit,
    SamplingPolicy,
    SamplingPolicyKind,
)
from steamlens.core.sampling import compile_plan

_FETCHED_AT = datetime(2026, 8, 1, tzinfo=UTC)


def _bucket(month: int, up: int, down: int = 0) -> HistogramBucket:
    return HistogramBucket(
        start=datetime(2026, month, 1, tzinfo=UTC),
        recommendations_up=up,
        recommendations_down=down,
    )


def _histogram(*buckets: HistogramBucket, app_id: int = 10) -> HistogramSnapshot:
    return HistogramSnapshot(
        app_id=app_id,
        rollup_unit=RollupUnit.MONTH,
        rollups=buckets,
        recent_daily=(),
        past_events=(),
        fetched_at=_FETCHED_AT,
    )


def _plan(histogram: HistogramSnapshot, kind: SamplingPolicyKind, n: int) -> FetchPlan:
    return compile_plan(histogram, SamplingPolicy(kind=kind, target_size=n))


def _quotas(plan: FetchPlan) -> list[int]:
    return [window.quota for window in plan.windows]


def test_cursor_prefix_plans_no_windows() -> None:
    """The cursor draw is fully specified by its budget — no windows to plan."""
    plan = _plan(_histogram(_bucket(1, 50)), SamplingPolicyKind.CURSOR_PREFIX, 500)
    assert plan.windows == ()
    assert plan.planned_total == 500
    assert plan.app_id == 10
    assert plan.histogram_fetched_at == _FETCHED_AT


def test_time_proportional_quotas_follow_claimed_volume() -> None:
    """Budget lands on each window in proportion to the histogram's claim."""
    histogram = _histogram(_bucket(1, 60), _bucket(2, 20, 10), _bucket(3, 10))
    plan = _plan(histogram, SamplingPolicyKind.TIME_PROPORTIONAL, 10)
    assert _quotas(plan) == [6, 3, 1]


def test_quotas_sum_exactly_to_target_under_rounding() -> None:
    """Largest-remainder rounding never gains or loses a review; ties go earliest."""
    histogram = _histogram(_bucket(1, 5), _bucket(2, 5), _bucket(3, 5))
    plan = _plan(histogram, SamplingPolicyKind.TIME_PROPORTIONAL, 10)
    assert _quotas(plan) == [4, 3, 3]
    assert plan.planned_total == 10


def test_equal_per_window_ignores_volume() -> None:
    """The equal policy gives every populated window the same share by design."""
    histogram = _histogram(_bucket(1, 100), _bucket(2, 50), _bucket(3, 10))
    plan = _plan(histogram, SamplingPolicyKind.EQUAL_PER_WINDOW, 9)
    assert _quotas(plan) == [3, 3, 3]


def test_quota_capped_at_claimed_volume_reflows_to_roomier_windows() -> None:
    """A window never owes more than it claims to hold; the excess re-flows."""
    histogram = _histogram(_bucket(1, 2), _bucket(2, 100), _bucket(3, 100))
    plan = _plan(histogram, SamplingPolicyKind.EQUAL_PER_WINDOW, 30)
    assert _quotas(plan) == [2, 14, 14]
    assert plan.planned_total == 30


def test_target_beyond_claimed_supply_plans_take_all() -> None:
    """Asking past the claim takes everything — the micro-window design's shape."""
    histogram = _histogram(_bucket(1, 5), _bucket(2, 3))
    plan = _plan(histogram, SamplingPolicyKind.TIME_PROPORTIONAL, 100)
    assert _quotas(plan) == [5, 3]
    assert plan.planned_total == 8


def test_claimed_empty_bucket_gets_no_window_and_its_span_stays_unplanned() -> None:
    """A zero-claim bucket costs no requests; its span is a deliberate gap."""
    histogram = _histogram(_bucket(1, 40), _bucket(2, 0), _bucket(3, 40))
    plan = _plan(histogram, SamplingPolicyKind.TIME_PROPORTIONAL, 10)
    assert len(plan.windows) == 2
    assert plan.windows[0].end == datetime(2026, 2, 1, tzinfo=UTC)
    assert plan.windows[1].start == datetime(2026, 3, 1, tzinfo=UTC)


def test_windows_tile_to_the_snapshot_time() -> None:
    """Each window ends where the next bucket starts; the last runs to fetch time."""
    histogram = _histogram(_bucket(1, 10), _bucket(2, 10))
    plan = _plan(histogram, SamplingPolicyKind.TIME_PROPORTIONAL, 4)
    assert plan.windows[0].end == plan.windows[1].start
    assert plan.windows[1].end == _FETCHED_AT


def test_shuffled_rollups_compile_the_same_chronological_plan() -> None:
    """Bucket order in the snapshot is presentation; the plan is always time-ordered."""
    ordered = _histogram(_bucket(1, 60), _bucket(2, 30), _bucket(3, 10))
    shuffled = _histogram(_bucket(3, 10), _bucket(1, 60), _bucket(2, 30))
    policy = SamplingPolicy(kind=SamplingPolicyKind.TIME_PROPORTIONAL, target_size=10)
    assert compile_plan(ordered, policy) == compile_plan(shuffled, policy)


def test_same_inputs_compile_identical_plans() -> None:
    """Determinism is the reproducibility contract: no hidden state, no drift."""
    histogram = _histogram(_bucket(1, 7), _bucket(2, 13), _bucket(3, 29))
    policy = SamplingPolicy(kind=SamplingPolicyKind.EQUAL_PER_WINDOW, target_size=17)
    assert compile_plan(histogram, policy) == compile_plan(histogram, policy)


def test_windowed_plan_over_empty_claim_fails_loud() -> None:
    """A histogram claiming nothing anywhere cannot seed a windowed draw."""
    histogram = _histogram(_bucket(1, 0), _bucket(2, 0))
    with pytest.raises(ValueError, match="claims no reviews"):
        _plan(histogram, SamplingPolicyKind.TIME_PROPORTIONAL, 10)


def test_non_positive_target_fails_loud() -> None:
    """A policy asking for zero reviews is a caller bug, not an empty plan."""
    with pytest.raises(ValueError, match="at least one review"):
        _plan(_histogram(_bucket(1, 50)), SamplingPolicyKind.TIME_PROPORTIONAL, 0)
