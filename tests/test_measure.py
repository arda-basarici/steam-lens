"""Draw-measurement tests — the per-draw scoring layer's behavioral claims.

Each test builds a small pool, an aspect index, and reference shares directly,
and asserts one property of ``measure_draw`` or ``mention_shares``: the
intersection-computed mention share, the error atom, coverage judged per
candidate, the stratified reading's presence rule and its agreement with the
directly-computed formula, the undrawn-aspect measurement, deterministic
ordering, and the loud wiring guards.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from steamlens.contracts import (
    AspectAggregate,
    AspectSlot,
    ClassifierVersions,
    Review,
    SamplingPolicy,
    SamplingPolicyKind,
    SentimentCounts,
)
from steamlens.core.intervals import Stratum, stratified_interval, wilson_interval
from steamlens.core.sampling import compile_plan
from steamlens.studies.measure import measure_draw, mention_shares
from steamlens.studies.sample_corpus import corpus_histogram, execute_plan

_VERSIONS = ClassifierVersions(
    model_version="deepseek-v4-flash", prompt_version="classify-v1", ontology_version="v2"
)


def _review(review_id: str, month: int, day: int = 15) -> Review:
    return Review(
        review_id=review_id,
        app_id=10,
        created_at=datetime(2026, month, day, 12, 0, tzinfo=UTC),
        language="english",
        text="good game",
        voted_up=True,
    )


def _aggregate(
    aspect: str,
    reviews_with_aspect: int,
    sample_size: int,
    *,
    app_id: int = 10,
    slot: AspectSlot = AspectSlot.PINNED,
) -> AspectAggregate:
    return AspectAggregate(
        app_id=app_id,
        aspect=aspect,
        slot=slot,
        reviews_with_aspect=reviews_with_aspect,
        counts=SentimentCounts(reviews_with_aspect, 0, 0, 0),
        sample_size=sample_size,
        versions=_VERSIONS,
        manifest_id="census-test",
    )


def test_mention_shares_are_review_denominated() -> None:
    """The reference share is distinct reviews over the game denominator."""
    shares = mention_shares([_aggregate("combat", 27, 100), _aggregate("story", 3, 100)])
    assert shares == {"combat": 0.27, "story": 0.03}


def test_mention_shares_guard_mixed_games_and_slot_collisions() -> None:
    """One game per reference; a pinned/candidate name clash must be resolved first."""
    with pytest.raises(ValueError, match="one game"):
        mention_shares([_aggregate("combat", 1, 10), _aggregate("story", 1, 10, app_id=20)])
    with pytest.raises(ValueError, match="more than one slot"):
        mention_shares(
            [
                _aggregate("combat", 1, 10),
                _aggregate("combat", 2, 10, slot=AspectSlot.CANDIDATE),
            ]
        )


def test_sample_share_and_error_come_from_the_id_intersection() -> None:
    """Two of four sampled reviews mention the aspect: share .5, error vs .27."""
    sample = [_review(str(i), 1) for i in range(4)]
    measured = measure_draw(
        sample, {"combat": frozenset({"0", "1", "9"})}, {"combat": 0.27}
    )
    (combat,) = measured
    assert combat.sample_share == 0.5
    assert combat.error == pytest.approx(0.23)


def test_coverage_is_judged_against_the_reference_share() -> None:
    """A truth inside the quoted interval reads covered; a distant one does not."""
    sample = [_review(str(i), 1) for i in range(20)]
    index = {"near": frozenset({"0", "1", "2", "3", "4"}), "far": frozenset({"0"})}
    far, near = measure_draw(sample, index, {"far": 0.9, "near": 0.3})
    assert near.wilson.covered and near.bootstrap.covered
    assert not far.wilson.covered and not far.bootstrap.covered


def test_wilson_reading_matches_the_direct_formula() -> None:
    """The reading is the core formula verbatim, not a re-derivation."""
    sample = [_review(str(i), 1) for i in range(10)]
    (measured,) = measure_draw(sample, {"combat": frozenset({"0", "1"})}, {"combat": 0.2})
    assert measured.wilson.interval == wilson_interval(2, 10)


def test_stratified_reading_requires_windows_and_matches_the_formula() -> None:
    """A windowed draw gets the design-aware reading, built from plan strata."""
    pool = [_review(str(i), 1 + i // 4, 1 + i % 4) for i in range(8)]
    histogram = corpus_histogram(pool)
    plan = compile_plan(
        histogram, SamplingPolicy(kind=SamplingPolicyKind.TIME_PROPORTIONAL, target_size=4)
    )
    sample = execute_plan(pool, plan)
    index = {"combat": frozenset({review.review_id for review in sample[:2]})}
    (measured,) = measure_draw(
        sample, index, {"combat": 0.4}, plan=plan, histogram=histogram
    )
    assert measured.stratified is not None
    per_window = [
        Stratum(
            successes=len(
                {r.review_id for r in sample if window.start <= r.created_at < window.end}
                & index["combat"]
            ),
            sample_size=window.quota,
            population=4,
        )
        for window in plan.windows
    ]
    assert measured.stratified.interval == stratified_interval(tuple(per_window))


def test_windowless_draws_have_no_stratified_reading() -> None:
    """Cursor and uniform draws have no strata — the field is honestly absent."""
    pool = [_review(str(i), 1) for i in range(6)]
    cursor_plan = compile_plan(
        corpus_histogram(pool), SamplingPolicy(kind=SamplingPolicyKind.CURSOR_PREFIX, target_size=3)
    )
    sample = execute_plan(pool, cursor_plan)
    index = {"combat": frozenset({"0"})}
    (with_plan,) = measure_draw(sample, index, {"combat": 0.1}, plan=cursor_plan)
    (without_plan,) = measure_draw(sample, index, {"combat": 0.1})
    assert with_plan.stratified is None
    assert without_plan.stratified is None


def test_undrawn_aspect_scores_zero_share_and_full_reference_error() -> None:
    """An aspect the sample missed is a measurement, not a hole."""
    sample = [_review("1", 1)]
    (measured,) = measure_draw(sample, {}, {"combat": 0.27})
    assert measured.sample_share == 0.0
    assert measured.error == pytest.approx(0.27)


def test_output_is_sorted_by_aspect() -> None:
    """Deterministic ordering regardless of the reference mapping's order."""
    sample = [_review("1", 1)]
    measured = measure_draw(sample, {}, {"story": 0.1, "combat": 0.2})
    assert [m.aspect for m in measured] == ["combat", "story"]


def test_wiring_bugs_fail_loud() -> None:
    """Empty sample, empty reference, duplicate ids, missing histogram: all fatal."""
    sample = [_review("1", 1)]
    with pytest.raises(ValueError, match="empty sample"):
        measure_draw([], {}, {"combat": 0.1})
    with pytest.raises(ValueError, match="nothing to measure"):
        measure_draw(sample, {}, {})
    with pytest.raises(ValueError, match="duplicate review ids"):
        measure_draw([_review("1", 1), _review("1", 2)], {}, {"combat": 0.1})
    pool = [_review(str(i), 1) for i in range(4)]
    plan = compile_plan(
        corpus_histogram(pool),
        SamplingPolicy(kind=SamplingPolicyKind.TIME_PROPORTIONAL, target_size=2),
    )
    with pytest.raises(ValueError, match="needs its histogram"):
        measure_draw(execute_plan(pool, plan), {}, {"combat": 0.1}, plan=plan)
