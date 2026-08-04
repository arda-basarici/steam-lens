"""Closing-verdict tests — the register arithmetic over closing rows.

The load-bearing claims: the sampled read is cell-weighted with the tolerance
gate pooling only tolerance-carrying cells, the register pass needs both
gates, a take-all-only game's verdict is exactness alone (and a nonzero
persisted error poisons it), and the band slices exclude the take-all side.
"""

from __future__ import annotations

import pytest

from steamlens.studies.allowance import ShareBand
from steamlens.studies.closing import (
    ClosingRow,
    band_reads,
    game_verdicts,
)


def _row(
    *,
    app_id: int = 1,
    quantile: float = 1.0,
    take_all: bool = False,
    band: ShareBand = ShareBand.MID,
    error: float = 0.0,
    within: bool | None = True,
    covered: bool | None = True,
) -> ClosingRow:
    return ClosingRow(
        app_id=app_id,
        anchor_quantile=quantile,
        take_all=take_all,
        band=band,
        error=error,
        within_tolerance=within,
        shipped_covered=covered,
    )


def _take_all(*, app_id: int = 1, error: float = 0.0) -> ClosingRow:
    return _row(app_id=app_id, take_all=True, error=error, within=None, covered=None)


def test_sampled_read_is_cell_weighted_and_pools_tolerance_separately() -> None:
    """Coverage pools every sampled cell; tolerance only the tolerance-carrying
    ones — interval-governed cells contribute to coverage alone."""
    rows = [
        _row(within=True, covered=True),
        _row(within=False, covered=True),
        _row(band=ShareBand.HEADLINE, within=None, covered=False),
        _row(within=True, covered=True),
    ]
    read = game_verdicts(rows)[1].sampled
    assert read is not None
    assert read.coverage_cells == 4
    assert read.coverage_rate == 0.75
    assert read.tolerance_cells == 3
    assert read.tolerance_rate == pytest.approx(2 / 3)


def test_register_pass_needs_both_gates() -> None:
    """One gate at the register does not carry the other."""
    passing = game_verdicts([_row() for _ in range(20)])[1]
    assert passing.passes()
    coverage_broken = game_verdicts(
        [_row(covered=False)] + [_row() for _ in range(9)]
    )[1]
    assert not coverage_broken.passes()  # coverage 0.9 under the 0.95 register
    tolerance_broken = game_verdicts(
        [_row(within=False)] + [_row() for _ in range(9)]
    )[1]
    assert not tolerance_broken.passes()


def test_take_all_only_game_verdict_is_exactness_alone() -> None:
    """A game the size rule never samples has no sampled read; exactness passes it."""
    verdict = game_verdicts([_take_all(), _take_all()])[1]
    assert verdict.sampled is None
    assert verdict.exact
    assert verdict.take_all_cells_exact == 2
    assert verdict.passes()


def test_nonzero_take_all_error_poisons_the_verdict() -> None:
    """The verdict stands on the file: a persisted take-all drift fails the game."""
    verdict = game_verdicts([_take_all(), _take_all(error=0.01)])[1]
    assert not verdict.exact
    assert verdict.take_all_cells_exact == 1
    assert not verdict.passes()


def test_all_tolerance_free_cells_read_coverage_alone() -> None:
    """A slice of purely interval-governed cells holds an absent tolerance gate."""
    rows = [_row(band=ShareBand.HEADLINE, within=None, covered=True) for _ in range(4)]
    read = game_verdicts(rows)[1].sampled
    assert read is not None
    assert read.tolerance_rate is None
    assert read.passes()


def test_band_reads_slice_sampled_cells_only() -> None:
    """Take-all rows carry no gates and stay out of the band diagnosis."""
    rows = [
        _row(band=ShareBand.TAIL, covered=True),
        _row(band=ShareBand.TAIL, covered=False),
        _row(band=ShareBand.MID, covered=True),
        _take_all(),
    ]
    reads = band_reads(rows)
    assert set(reads) == {ShareBand.TAIL, ShareBand.MID}
    assert reads[ShareBand.TAIL].coverage_rate == 0.5
    assert reads[ShareBand.MID].coverage_rate == 1.0


def test_verdicts_group_per_game() -> None:
    """Rows reduce per app_id — one game's failure never leaks into another's."""
    verdicts = game_verdicts([_take_all(app_id=1), _take_all(app_id=2, error=0.5)])
    assert verdicts[1].passes()
    assert not verdicts[2].passes()


def test_empty_input_fails_loud() -> None:
    """A verdict over nothing is a caller bug, never a pass."""
    with pytest.raises(ValueError, match="no closing rows"):
        game_verdicts([])
