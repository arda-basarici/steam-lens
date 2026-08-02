"""Simulated-draw tests — the corpus executor's behavioral claims.

Every test builds ``Review`` records directly and asserts one property of the
simulation trio: the corpus histogram's live-shaped series (contiguous months,
zeros included, data-derived fetch time, vote split), the executor's
implementation of the contract's newest-first quota rule, the compile→execute
round trip that recovers the whole pool (the take-all case the micro-window
design rides on), the loud wiring guards, and the reference draw's seeded
determinism.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from steamlens.contracts import (
    FetchPlan,
    PlannedWindow,
    Review,
    SamplingPolicy,
    SamplingPolicyKind,
)
from steamlens.core.sampling import compile_plan
from steamlens.studies.sample_corpus import (
    corpus_histogram,
    execute_plan,
    uniform_reference_draw,
)


def _review(
    review_id: str,
    month: int,
    day: int = 15,
    *,
    app_id: int = 10,
    voted_up: bool = True,
) -> Review:
    return Review(
        review_id=review_id,
        app_id=app_id,
        created_at=datetime(2026, month, day, 12, 0, tzinfo=UTC),
        language="english",
        text="good game",
        voted_up=voted_up,
    )


def _policy(kind: SamplingPolicyKind, n: int) -> SamplingPolicy:
    return SamplingPolicy(kind=kind, target_size=n)


def _ids(reviews: tuple[Review, ...]) -> list[str]:
    return [review.review_id for review in reviews]


def test_corpus_histogram_buckets_by_month_with_vote_split() -> None:
    """Counts land in their calendar month, split by the overall vote."""
    pool = [_review("1", 1), _review("2", 1, voted_up=False), _review("3", 2)]
    histogram = corpus_histogram(pool)
    assert histogram.app_id == 10
    assert [(b.recommendations_up, b.recommendations_down) for b in histogram.rollups] == [
        (1, 1),
        (1, 0),
    ]


def test_corpus_histogram_series_is_contiguous_with_zero_months() -> None:
    """A silent month appears as a zero bucket — the shape Steam serves."""
    histogram = corpus_histogram([_review("1", 1), _review("2", 3)])
    starts = [bucket.start.month for bucket in histogram.rollups]
    volumes = [b.recommendations_up + b.recommendations_down for b in histogram.rollups]
    assert starts == [1, 2, 3]
    assert volumes == [1, 0, 1]


def test_corpus_histogram_fetched_at_is_the_month_after_the_newest_review() -> None:
    """Fetch time comes from the data, never a clock — determinism's anchor."""
    histogram = corpus_histogram([_review("1", 1), _review("2", 3)])
    assert histogram.fetched_at == datetime(2026, 4, 1, tzinfo=UTC)


def test_corpus_histogram_rejects_empty_and_mixed_pools() -> None:
    """An empty or multi-game pool is a wiring bug, not a histogram."""
    with pytest.raises(ValueError, match="empty review pool"):
        corpus_histogram([])
    with pytest.raises(ValueError, match="exactly one game"):
        corpus_histogram([_review("1", 1), _review("2", 1, app_id=20)])


def test_compile_then_execute_take_all_recovers_the_whole_pool() -> None:
    """The round trip at full budget returns every review exactly once."""
    pool = [_review(str(i), month, day) for i, (month, day) in enumerate(
        [(1, 3), (1, 20), (2, 5), (4, 1), (4, 28), (4, 28)]
    )]
    plan = compile_plan(
        corpus_histogram(pool), _policy(SamplingPolicyKind.TIME_PROPORTIONAL, len(pool))
    )
    drawn = execute_plan(pool, plan)
    assert sorted(_ids(drawn)) == sorted(_ids(tuple(pool)))


def test_windowed_execution_takes_the_newest_of_each_window() -> None:
    """Inside a window the quota prefix is newest-first — the contract's rule."""
    pool = [_review("old", 1, 2), _review("mid", 1, 10), _review("new", 1, 25)]
    plan = compile_plan(
        corpus_histogram(pool), _policy(SamplingPolicyKind.TIME_PROPORTIONAL, 2)
    )
    assert _ids(execute_plan(pool, plan)) == ["new", "mid"]


def test_cursor_prefix_takes_the_newest_across_the_pool() -> None:
    """The fallback draw is a most-recent prefix; beyond the pool it takes all."""
    pool = [_review("a", 1), _review("b", 3), _review("c", 2)]
    plan = compile_plan(corpus_histogram(pool), _policy(SamplingPolicyKind.CURSOR_PREFIX, 2))
    assert _ids(execute_plan(pool, plan)) == ["b", "c"]
    everything = compile_plan(
        corpus_histogram(pool), _policy(SamplingPolicyKind.CURSOR_PREFIX, 99)
    )
    assert len(execute_plan(pool, everything)) == 3


def test_same_timestamp_ties_break_by_review_id_descending() -> None:
    """Equal seconds still order deterministically — the fixed tie-break."""
    pool = [_review("7", 1, 10), _review("9", 1, 10), _review("8", 1, 10)]
    plan = compile_plan(corpus_histogram(pool), _policy(SamplingPolicyKind.CURSOR_PREFIX, 3))
    assert _ids(execute_plan(pool, plan)) == ["9", "8", "7"]


def test_windowed_shortfall_fails_loud() -> None:
    """A quota the pool cannot fill means histogram and pool disagree — a bug."""
    pool = [_review("1", 1)]
    plan = FetchPlan(
        app_id=10,
        policy=_policy(SamplingPolicyKind.TIME_PROPORTIONAL, 5),
        windows=(
            PlannedWindow(
                start=datetime(2026, 1, 1, tzinfo=UTC),
                end=datetime(2026, 2, 1, tzinfo=UTC),
                quota=5,
            ),
        ),
        histogram_fetched_at=datetime(2026, 2, 1, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match="disagrees with this pool"):
        execute_plan(pool, plan)


def test_wrong_game_pool_fails_loud() -> None:
    """A plan executed against another game's reviews is a wiring bug."""
    pool = [_review("1", 1, app_id=20)]
    plan = compile_plan(
        corpus_histogram([_review("1", 1)]), _policy(SamplingPolicyKind.CURSOR_PREFIX, 1)
    )
    with pytest.raises(ValueError, match="app_id 10"):
        execute_plan(pool, plan)


def test_uniform_reference_draw_is_seed_deterministic() -> None:
    """Same seed, same draw; a different seed draws differently on this pool."""
    pool = [_review(str(i), 1 + i % 6, 1 + i % 27) for i in range(40)]
    first = uniform_reference_draw(pool, 10, seed=7)
    again = uniform_reference_draw(pool, 10, seed=7)
    other = uniform_reference_draw(pool, 10, seed=8)
    assert _ids(first) == _ids(again)
    assert _ids(first) != _ids(other)
    assert len(first) == 10


def test_uniform_reference_draw_ignores_caller_ordering() -> None:
    """The draw depends on the pool's content, never its iteration order."""
    pool = [_review(str(i), 1 + i % 3) for i in range(12)]
    assert _ids(uniform_reference_draw(pool, 4, seed=3)) == _ids(
        uniform_reference_draw(list(reversed(pool)), 4, seed=3)
    )


def test_uniform_reference_draw_take_all_and_guards() -> None:
    """At or past the pool size the draw is the pool; bad inputs fail loud."""
    pool = [_review("1", 1), _review("2", 2)]
    assert len(uniform_reference_draw(pool, 2, seed=1)) == 2
    assert len(uniform_reference_draw(pool, 99, seed=1)) == 2
    with pytest.raises(ValueError, match="empty review pool"):
        uniform_reference_draw([], 5, seed=1)
    with pytest.raises(ValueError, match="at least one review"):
        uniform_reference_draw(pool, 0, seed=1)
