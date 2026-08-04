"""Mixing-sweep tests — the grid's pure pieces and one game end to end.

The load-bearing claims: order-independent seed derivation over the full cell
identity, the merged vocabulary giving marked-only aspects a true zero
reference, take-all anchors skipped and counted, the cell layout (sources ×
shares, a single-draw share-0 baseline, seeded repeats elsewhere), plan-free
measurement, the contamination signal itself (an invented aspect rising to
exactly its blend share; a base aspect diluting below its baseline), and
seeded determinism (same config, identical rows; different base seed,
different blends).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from steamlens.contracts import Review
from steamlens.studies.marked_pool import MarkedPool
from steamlens.studies.mix_corpus import (
    GameMix,
    MixConfig,
    derive_mix_seed,
    merged_aspect_index,
    mix_game,
)

_START = datetime(2026, 1, 1, tzinfo=UTC)


def _review(review_id: str, day: int, *, app_id: int = 10) -> Review:
    return Review(
        review_id=review_id,
        app_id=app_id,
        created_at=_START + timedelta(days=day),
        language="english",
        text=f"review {review_id}",
        voted_up=True,
    )


def _base_pool(n: int = 60) -> tuple[Review, ...]:
    """A base game's pool spread across months — reviews b0..b{n-1}, ~2/day."""
    return tuple(_review(f"b{i}", i * 2) for i in range(n))


def _base_index(pool: tuple[Review, ...]) -> dict[str, frozenset[str]]:
    """Even-numbered reviews mention combat — a ~0.5 reference share."""
    return {
        "combat": frozenset(r.review_id for i, r in enumerate(pool) if i % 2 == 0),
    }


def _marked_source(n: int = 40) -> MarkedPool:
    """A bomb source whose every review mentions an aspect the base never has."""
    reviews = tuple(_review(f"m{i}", 500 + i, app_id=99) for i in range(n))
    return MarkedPool(
        app_id=99,
        name="Bomb Game",
        window_start=_START + timedelta(days=500),
        window_end=_START + timedelta(days=600),
        reviews=reviews,
        aspect_reviews={"bomb_aspect": frozenset(r.review_id for r in reviews)},
        dropped_unlabeled=0,
        source_run_id="freshbuy-test",
    )


def _cfg(**overrides: object) -> MixConfig:
    dials: dict[str, object] = {
        "shares": (0.0, 0.2, 0.5),
        "quantiles": (1.0,),
        "sample_size": 20,
        "take_all_cutoff": 30,
        "repeats": 5,
        "base_seed": 20260804,
    }
    dials.update(overrides)
    return MixConfig(**dials)  # type: ignore[arg-type]


def _mix(**overrides: object) -> GameMix:
    pool = _base_pool()
    return mix_game(pool, _base_index(pool), [_marked_source()], _cfg(**overrides))


def test_derive_mix_seed_is_stable_and_cell_distinct() -> None:
    """Seeds reproduce from the cell identity alone and differ across cells."""
    seed = derive_mix_seed(7, 10, 1.0, 99, 0.2, 3)
    assert seed == derive_mix_seed(7, 10, 1.0, 99, 0.2, 3)
    others = {
        derive_mix_seed(8, 10, 1.0, 99, 0.2, 3),
        derive_mix_seed(7, 11, 1.0, 99, 0.2, 3),
        derive_mix_seed(7, 10, 0.7, 99, 0.2, 3),
        derive_mix_seed(7, 10, 1.0, 98, 0.2, 3),
        derive_mix_seed(7, 10, 1.0, 99, 0.3, 3),
        derive_mix_seed(7, 10, 1.0, 99, 0.2, 4),
    }
    assert seed not in others
    assert len(others) == 6


def test_merged_index_gives_marked_only_aspects_a_home() -> None:
    """The union vocabulary: base-only kept, marked-only added, overlaps unioned."""
    merged = merged_aspect_index(
        {"combat": frozenset({"b1"}), "story": frozenset({"b2"})},
        {"combat": frozenset({"m1"}), "bomb_aspect": frozenset({"m2"})},
    )
    assert merged == {
        "combat": frozenset({"b1", "m1"}),
        "story": frozenset({"b2"}),
        "bomb_aspect": frozenset({"m2"}),
    }


def test_take_all_anchors_are_skipped_and_counted() -> None:
    """An anchor pool at or under the cutoff is production take-all — no cell."""
    result = _mix(take_all_cutoff=60)
    assert result.rows == ()
    assert result.skipped_take_all_anchors == 1


def test_cell_layout_sources_by_shares() -> None:
    """One admitted anchor yields sources × shares cells at the ruled size."""
    result = _mix()
    assert len(result.rows) == 3  # one source × three shares
    assert [row.share for row in result.rows] == [0.0, 0.2, 0.5]
    assert all(row.source_app_id == 99 for row in result.rows)
    assert all(row.size == 20 for row in result.rows)
    assert result.skipped_take_all_anchors == 0


def test_share_zero_is_a_single_deterministic_baseline() -> None:
    """The share-0 cell records one draw; contaminated cells record the repeats."""
    result = _mix()
    by_share = {row.share: row for row in result.rows}
    assert all(s.repeats == 1 for s in by_share[0.0].summaries)
    assert all(s.repeats == 5 for s in by_share[0.5].summaries)


def test_measurement_is_plan_free() -> None:
    """No stratified reading anywhere — the blend falsifies strata by design."""
    result = _mix()
    assert all(s.stratified is None for row in result.rows for s in row.summaries)


def test_invented_aspect_rises_to_exactly_its_blend_share() -> None:
    """Every marked review mentions the invented aspect, so its measured share
    is the contamination share itself — and its reference is a true zero."""
    result = _mix()
    by_share = {row.share: row for row in result.rows}
    for share in (0.0, 0.2, 0.5):
        bomb = next(s for s in by_share[share].summaries if s.aspect == "bomb_aspect")
        assert bomb.reference_share == 0.0
        assert bomb.mean_sample_share == pytest.approx(share)
        assert bomb.mean_error == pytest.approx(share)


def test_base_aspect_dilutes_under_contamination() -> None:
    """Swapping in bomb material pushes the base aspect below its baseline."""
    result = _mix()
    by_share = {row.share: row for row in result.rows}
    combat = {
        share: next(s for s in by_share[share].summaries if s.aspect == "combat")
        for share in (0.0, 0.5)
    }
    assert combat[0.5].mean_sample_share < combat[0.0].mean_sample_share


def test_same_config_reproduces_identical_rows() -> None:
    """The whole game mix is a pure function of (pool, index, sources, cfg)."""
    assert _mix() == _mix()


def test_different_base_seed_varies_the_blends() -> None:
    """The base seed is the run's repeat-variance dial."""
    assert _mix() != _mix(base_seed=1)


def test_empty_pool_fails_loud() -> None:
    """Mixing over nothing is a caller bug, never a run."""
    with pytest.raises(ValueError, match="empty review pool"):
        mix_game((), {}, [_marked_source()], _cfg())
