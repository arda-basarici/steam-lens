"""Curves-sweep tests — the sweep's pure pieces and one game end to end.

Each test asserts one behavioral claim: anchor placement at span quantiles
with duplicate pools dropped, inclusive truncation, order-independent seed
derivation, reference shares that agree with the census fold's own
definition, summary arithmetic over repeated draws, and the game sweep's
take-all skipping plus its seeded determinism (same config, identical rows;
different base seed, different uniform draws).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from steamlens.contracts import (
    AspectAggregate,
    AspectSlot,
    ClassifierVersions,
    Review,
    SentimentCounts,
)
from steamlens.core.intervals import Interval
from steamlens.studies.measure import AspectMeasurement, IntervalReading, mention_shares
from steamlens.studies.sweep_corpus import (
    SweepConfig,
    anchor_grid,
    anchored_reference_shares,
    derive_seed,
    summarize_cell,
    sweep_game,
    truncate_pool,
)

_START = datetime(2026, 1, 1, tzinfo=UTC)


def _review(review_id: str, day: int, *, app_id: int = 10) -> Review:
    return Review(
        review_id=review_id,
        app_id=app_id,
        created_at=_START + timedelta(days=day),
        language="english",
        text="good game",
        voted_up=True,
    )


def _pool(days: list[int]) -> tuple[Review, ...]:
    return tuple(_review(f"r{i}", day) for i, day in enumerate(days))


def _measurement(
    aspect: str,
    error: float,
    *,
    covered: bool = True,
    stratified: IntervalReading | None = None,
) -> AspectMeasurement:
    reading = IntervalReading(interval=Interval(low=0.1, high=0.3), covered=covered)
    return AspectMeasurement(
        aspect=aspect,
        sample_share=0.2,
        reference_share=0.25,
        error=error,
        wilson=reading,
        bootstrap=reading,
        stratified=stratified,
    )


def test_anchor_grid_places_span_quantiles() -> None:
    """Cutoffs sit at fractions of the game's own span; pools count inclusively.

    Days 71-85 hold nothing, so the 85% anchor's pool duplicates the 70%
    anchor's and is dropped — the duplicate rule falling out of a plain grid.
    """
    pool = _pool([0, 10, 40, 55, 70, 100])
    grid = anchor_grid(pool, (0.40, 0.55, 0.70, 0.85, 1.00))
    assert [a.quantile for a in grid.anchors] == [0.40, 0.55, 0.70, 1.00]
    assert [a.pool_size for a in grid.anchors] == [3, 4, 5, 6]
    assert grid.duplicates == (0.85,)
    assert grid.anchors[-1].cutoff == _START + timedelta(days=100)
    cutoffs = [a.cutoff for a in grid.anchors]
    assert cutoffs == sorted(cutoffs)


def test_anchor_grid_drops_duplicate_pools() -> None:
    """Equal pool sizes mean the identical pool — later quantiles drop."""
    pool = _pool([0, 10, 40, 55, 70, 100])
    grid = anchor_grid(pool, (0.70, 0.85, 1.00))
    assert [a.quantile for a in grid.anchors] == [0.70, 1.00]
    assert grid.duplicates == (0.85,)


def test_anchor_grid_single_instant_pool_collapses_to_one_anchor() -> None:
    """A zero-width span puts every quantile on the same full pool."""
    pool = tuple(_review(f"r{i}", 5) for i in range(3))
    grid = anchor_grid(pool, (0.40, 0.70, 1.00))
    assert len(grid.anchors) == 1
    assert grid.anchors[0].pool_size == 3
    assert grid.duplicates == (0.70, 1.00)


def test_anchor_grid_guards() -> None:
    """Empty pools and malformed quantile grids are caller bugs, never grids."""
    pool = _pool([0, 100])
    with pytest.raises(ValueError, match="empty review pool"):
        anchor_grid((), (0.5, 1.0))
    with pytest.raises(ValueError, match="ascending"):
        anchor_grid(pool, (0.7, 0.4))
    with pytest.raises(ValueError, match=r"in \(0, 1\]"):
        anchor_grid(pool, (0.0, 0.5))
    with pytest.raises(ValueError, match=r"in \(0, 1\]"):
        anchor_grid(pool, (0.5, 1.5))


def test_truncate_pool_keeps_the_cutoff_instant() -> None:
    """Truncation is at-or-before — the review created exactly at T is seen at T."""
    pool = _pool([0, 50, 100])
    kept = truncate_pool(pool, _START + timedelta(days=50))
    assert [review.review_id for review in kept] == ["r0", "r1"]


def test_derive_seed_is_stable_and_cell_distinct() -> None:
    """Seeds reproduce from the cell identity alone and differ across cells."""
    seed = derive_seed(7, 10, 0.40, 500, 3)
    assert seed == derive_seed(7, 10, 0.40, 500, 3)
    others = {
        derive_seed(8, 10, 0.40, 500, 3),
        derive_seed(7, 11, 0.40, 500, 3),
        derive_seed(7, 10, 0.55, 500, 3),
        derive_seed(7, 10, 0.40, 501, 3),
        derive_seed(7, 10, 0.40, 500, 4),
    }
    assert seed not in others
    assert len(others) == 5


def test_anchored_reference_shares_match_the_fold_definition() -> None:
    """Id-set shares equal ``mention_shares`` over the same universe.

    The run-time wiring guard's claim, as a unit test: both sides divide the
    same integers, so the full-pool shares must be equal exactly.
    """
    pool = _pool([0, 10, 20, 30])
    aspect_reviews = {"combat": frozenset({"r0", "r2"}), "story": frozenset({"r3"})}
    versions = ClassifierVersions(
        model_version="m", prompt_version="p", ontology_version="v2"
    )
    counts = SentimentCounts(positive=0, negative=0, mixed=0, neutral=0)
    aggregates = tuple(
        AspectAggregate(
            app_id=10,
            aspect=aspect,
            slot=AspectSlot.PINNED,
            reviews_with_aspect=len(ids),
            counts=counts,
            sample_size=len(pool),
            versions=versions,
            manifest_id="census/test",
        )
        for aspect, ids in aspect_reviews.items()
    )
    assert anchored_reference_shares(pool, aspect_reviews) == mention_shares(aggregates)


def test_anchored_reference_shares_shift_with_truncation() -> None:
    """An anchor's truth is the truncated pool's truth, zero shares included."""
    pool = _pool([0, 10, 20, 30])
    aspect_reviews = {"combat": frozenset({"r0"}), "story": frozenset({"r3"})}
    truncated = truncate_pool(pool, _START + timedelta(days=20))
    assert anchored_reference_shares(truncated, aspect_reviews) == {
        "combat": 1 / 3,
        "story": 0.0,
    }
    with pytest.raises(ValueError, match="empty pool"):
        anchored_reference_shares((), aspect_reviews)


def test_summarize_cell_statistics() -> None:
    """Error stats and coverage tally over draws; a single draw is its own stats."""
    draws = [
        (_measurement("combat", 0.1, covered=True),),
        (_measurement("combat", 0.2, covered=True),),
        (_measurement("combat", 0.4, covered=False),),
    ]
    summary = summarize_cell(draws)[0]
    assert summary.repeats == 3
    assert summary.mean_error == pytest.approx((0.1 + 0.2 + 0.4) / 3)
    assert summary.p50_error == pytest.approx(0.2)
    assert summary.p90_error == pytest.approx(0.36)  # linear interp between 0.2 and 0.4
    assert summary.max_error == pytest.approx(0.4)
    assert summary.wilson.coverage == pytest.approx(2 / 3)
    assert summary.wilson.mean_width == pytest.approx(0.2)
    assert summary.stratified is None

    single = summarize_cell([(_measurement("combat", 0.3),)])[0]
    assert single.mean_error == single.p50_error == single.p90_error == single.max_error == 0.3


def test_summarize_cell_rejects_incoherent_cells() -> None:
    """Mixed aspect sets or mixed plan shapes in one cell are wiring bugs."""
    with pytest.raises(ValueError, match="no draws"):
        summarize_cell([])
    with pytest.raises(ValueError, match="different aspect sets"):
        summarize_cell([
            (_measurement("combat", 0.1),),
            (_measurement("story", 0.1),),
        ])
    stratified = IntervalReading(interval=Interval(low=0.0, high=0.5), covered=True)
    with pytest.raises(ValueError, match="one plan shape"):
        summarize_cell([
            (_measurement("combat", 0.1, stratified=stratified),),
            (_measurement("combat", 0.2),),
        ])


def _game_fixture() -> tuple[tuple[Review, ...], dict[str, frozenset[str]]]:
    """Sixty reviews over 100 days; combat in every third, story in every fifth."""
    pool = tuple(_review(f"r{i}", (i * 100) // 59) for i in range(60))
    return pool, {
        "combat": frozenset(f"r{i}" for i in range(0, 60, 3)),
        "story": frozenset(f"r{i}" for i in range(0, 60, 5)),
    }


def test_sweep_game_skips_take_all_and_covers_all_policies() -> None:
    """Viable cells carry all four policies; oversized cells are counted, not drawn."""
    pool, aspect_reviews = _game_fixture()
    cfg = SweepConfig(sizes=(10, 25, 500), quantiles=(0.40, 1.00), repeats=3, base_seed=1)
    sweep = sweep_game(pool, aspect_reviews, cfg)

    assert [a.pool_size for a in sweep.grid.anchors] == [25, 60]
    # anchor 0.40 (pool 25): sizes 10 viable, 25 and 500 take-all;
    # anchor 1.00 (pool 60): sizes 10 and 25 viable, 500 take-all.
    assert sweep.skipped_take_all == 3
    cells = {(row.anchor_quantile, row.size, row.policy) for row in sweep.rows}
    assert len(cells) == len(sweep.rows) == 3 * 4
    for row in sweep.rows:
        windowed = row.policy in ("time-proportional", "equal-per-window")
        for summary in row.summaries:
            assert (summary.stratified is not None) == windowed
            assert summary.repeats == (3 if row.policy == "uniform-random" else 1)


def test_sweep_game_is_deterministic_and_seed_sensitive() -> None:
    """Same config replays identical rows; a new base seed moves the uniform draws."""
    pool, aspect_reviews = _game_fixture()
    cfg = SweepConfig(sizes=(10,), quantiles=(1.00,), repeats=5, base_seed=1)
    first = sweep_game(pool, aspect_reviews, cfg)
    second = sweep_game(pool, aspect_reviews, cfg)
    assert first == second

    reseeded = sweep_game(
        pool, aspect_reviews,
        SweepConfig(sizes=(10,), quantiles=(1.00,), repeats=5, base_seed=2),
    )
    uniform = [row for row in first.rows if row.policy == "uniform-random"]
    uniform_reseeded = [row for row in reseeded.rows if row.policy == "uniform-random"]
    assert uniform != uniform_reseeded
    deterministic = [row for row in first.rows if row.policy != "uniform-random"]
    deterministic_reseeded = [row for row in reseeded.rows if row.policy != "uniform-random"]
    assert deterministic == deterministic_reseeded


def test_sweep_game_rejects_an_empty_pool() -> None:
    """No pool, no sweep — a wiring bug, not an empty result."""
    with pytest.raises(ValueError, match="empty review pool"):
        sweep_game((), {"combat": frozenset()}, SweepConfig((10,), (1.0,), 1, 1))
