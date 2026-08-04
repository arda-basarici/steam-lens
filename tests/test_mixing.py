"""Mixing-blend tests — the contamination transform's behavioral claims.

The load-bearing claims: the swap arithmetic (count, composition, the
zero-share identity, half-away-from-zero rounding), seeded determinism that
survives caller iteration order, and the fail-loud boundary (duplicate ids,
self-contamination, out-of-range shares, whole-sample swaps, short supply).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from steamlens.contracts import Review
from steamlens.studies.mixing import contaminate

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


def _base(n: int) -> tuple[Review, ...]:
    return tuple(_review(f"b{i}", i) for i in range(n))


def _marked(n: int) -> tuple[Review, ...]:
    return tuple(_review(f"m{i}", 500 + i, app_id=99) for i in range(n))


def test_zero_share_returns_the_sample_in_canonical_order() -> None:
    """No swap at share 0 — the identity blend, canonically ordered."""
    sample = _base(10)
    mixed = contaminate(sample, _marked(5), 0.0, seed=7)
    assert {r.review_id for r in mixed} == {r.review_id for r in sample}
    assert [r.created_at for r in mixed] == sorted(
        (r.created_at for r in sample), reverse=True
    )


def test_swap_count_and_composition() -> None:
    """Share 0.2 of 10 swaps exactly 2: 8 base survivors, 2 marked entrants."""
    mixed = contaminate(_base(10), _marked(5), 0.2, seed=7)
    assert len(mixed) == 10
    entrants = {r.review_id for r in mixed if r.review_id.startswith("m")}
    survivors = {r.review_id for r in mixed if r.review_id.startswith("b")}
    assert len(entrants) == 2
    assert len(survivors) == 8


def test_rounding_is_half_away_from_zero() -> None:
    """Share 0.05 of 10 swaps 1, not banker's-rounded 0 — small shares stay real."""
    mixed = contaminate(_base(10), _marked(5), 0.05, seed=7)
    assert sum(1 for r in mixed if r.review_id.startswith("m")) == 1


def test_same_inputs_same_seed_reproduce_exactly() -> None:
    """The blend is a pure function of (sample, marked, share, seed)."""
    first = contaminate(_base(50), _marked(100), 0.2, seed=42)
    second = contaminate(_base(50), _marked(100), 0.2, seed=42)
    assert [r.review_id for r in first] == [r.review_id for r in second]


def test_caller_iteration_order_never_matters() -> None:
    """Reversed input orders produce the identical blend — canonical-order teeth."""
    sample, marked = _base(50), _marked(100)
    forward = contaminate(sample, marked, 0.2, seed=42)
    backward = contaminate(tuple(reversed(sample)), tuple(reversed(marked)), 0.2, seed=42)
    assert [r.review_id for r in forward] == [r.review_id for r in backward]


def test_different_seeds_vary_the_blend() -> None:
    """Seeds are the repeat-variance dial: distinct seeds, distinct swaps."""
    first = contaminate(_base(50), _marked(100), 0.2, seed=1)
    second = contaminate(_base(50), _marked(100), 0.2, seed=2)
    assert [r.review_id for r in first] != [r.review_id for r in second]


def test_output_holds_no_duplicate_ids() -> None:
    """A blend is a sample — no review appears twice."""
    mixed = contaminate(_base(20), _marked(20), 0.45, seed=3)
    ids = [r.review_id for r in mixed]
    assert len(ids) == len(set(ids))


def test_empty_inputs_fail_loud() -> None:
    """Blending nothing is a caller bug, never a draw."""
    with pytest.raises(ValueError, match="empty sample"):
        contaminate((), _marked(5), 0.2, seed=7)
    with pytest.raises(ValueError, match="empty marked pool"):
        contaminate(_base(5), (), 0.2, seed=7)


def test_duplicate_ids_fail_loud() -> None:
    """Duplicate ids inside either input refute the it's-a-sample premise."""
    with pytest.raises(ValueError, match="sample contains duplicate"):
        contaminate(_base(5) + (_review("b0", 0),), _marked(5), 0.2, seed=7)
    with pytest.raises(ValueError, match="marked pool contains duplicate"):
        contaminate(_base(5), _marked(5) + (_review("m0", 500),), 0.2, seed=7)


def test_self_contamination_fails_loud() -> None:
    """An id in both pools means the wiring blended a game into itself."""
    overlapping = _marked(5) + (_review("b1", 1),)
    with pytest.raises(ValueError, match="cannot contaminate itself"):
        contaminate(_base(5), overlapping, 0.2, seed=7)


def test_share_bounds_fail_loud() -> None:
    """Shares live in [0, 1): negatives and 1.0 are contract violations."""
    with pytest.raises(ValueError, match=r"\[0.0, 1.0\)"):
        contaminate(_base(5), _marked(5), -0.1, seed=7)
    with pytest.raises(ValueError, match=r"\[0.0, 1.0\)"):
        contaminate(_base(5), _marked(5), 1.0, seed=7)


def test_whole_sample_swap_fails_loud() -> None:
    """A share that rounds to n would leave no base game to measure."""
    with pytest.raises(ValueError, match="whole sample"):
        contaminate(_base(10), _marked(20), 0.99, seed=7)


def test_short_marked_supply_fails_loud() -> None:
    """A pool smaller than the swap count cannot supply the blend."""
    with pytest.raises(ValueError, match="needs 5 marked reviews but the pool holds 3"):
        contaminate(_base(10), _marked(3), 0.5, seed=7)
