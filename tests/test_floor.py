"""Floor-arithmetic tests — the register pooling and the prefix rule's claims.

The load-bearing claims: draw-weighted pooling with interval-governed rows
entering coverage only, the at-the-register edge passing, the prefix rule
(one failing low share caps the floor against later recoveries), the failing
baseline yielding no floor, censoring at the grid top, and the missing
baseline refused.
"""

from __future__ import annotations

import pytest

from steamlens.studies.allowance import ShareBand
from steamlens.studies.floor import (
    FloorRead,
    GateRow,
    RegisterRead,
    floor_from_reads,
    register_reads,
)


def _row(
    share: float,
    *,
    band: ShareBand = ShareBand.TAIL,
    repeats: int = 10,
    tolerance: float | None = 1.0,
    coverage: float = 1.0,
    source: int = 99,
) -> GateRow:
    return GateRow(
        source_app_id=source,
        share=share,
        band=band,
        repeats=repeats,
        within_tolerance_rate=tolerance,
        shipped_coverage_rate=coverage,
    )


def _read(tolerance: float | None, coverage: float) -> RegisterRead:
    return RegisterRead(
        tolerance_rate=tolerance,
        coverage_rate=coverage,
        tolerance_draws=10,
        coverage_draws=10,
    )


def test_register_reads_pool_draw_weighted() -> None:
    """Rates weight by draw count; tolerance-free rows enter coverage only."""
    reads = register_reads(
        [
            _row(0.1, repeats=10, tolerance=1.0, coverage=0.9),
            _row(0.1, repeats=190, tolerance=None, coverage=1.0, band=ShareBand.HEADLINE),
        ]
    )
    read = reads[(99, 0.1)]
    assert read.coverage_rate == pytest.approx((0.9 * 10 + 1.0 * 190) / 200)
    assert read.coverage_draws == 200
    assert read.tolerance_rate == pytest.approx(1.0)
    assert read.tolerance_draws == 10


def test_register_reads_split_by_source_and_share() -> None:
    """The pooling key is (source, share) — nothing leaks across curves."""
    reads = register_reads([_row(0.1, source=1), _row(0.1, source=2), _row(0.2, source=1)])
    assert set(reads) == {(1, 0.1), (2, 0.1), (1, 0.2)}


def test_passes_is_inclusive_at_the_register() -> None:
    """Exactly 95% satisfies a 95% register; an absent tolerance gate holds."""
    assert _read(0.95, 0.95).passes()
    assert not _read(0.949, 0.95).passes()
    assert not _read(0.95, 0.949).passes()
    assert _read(None, 0.95).passes()


def test_floor_is_the_last_share_of_the_passing_prefix() -> None:
    """A failure caps the floor even when a later share recovers."""
    reads = {
        0.0: _read(1.0, 1.0),
        0.02: _read(1.0, 0.98),
        0.05: _read(1.0, 0.90),  # the break
        0.10: _read(1.0, 0.97),  # noise recovering — never re-opens
    }
    result = floor_from_reads(reads)
    assert result.floor == 0.02
    assert not result.censored
    assert result.verdicts == ((0.0, True), (0.02, True), (0.05, False), (0.10, True))


def test_failing_baseline_yields_no_floor() -> None:
    """Share 0 restates the certified promise; its failure is a wiring question."""
    result = floor_from_reads({0.0: _read(1.0, 0.90), 0.02: _read(1.0, 1.0)})
    assert result.floor is None
    assert not result.censored


def test_all_passing_grid_is_censored() -> None:
    """A promise that never breaks quotes the top share as a lower bound."""
    result = floor_from_reads({0.0: _read(1.0, 1.0), 0.5: _read(1.0, 0.96)})
    assert result == FloorRead(
        floor=0.5, censored=True, verdicts=((0.0, True), (0.5, True))
    )


def test_missing_baseline_fails_loud() -> None:
    """A grid without its share-0 control cannot claim a floor."""
    with pytest.raises(ValueError, match="baseline control is missing"):
        floor_from_reads({0.02: _read(1.0, 1.0)})
    with pytest.raises(ValueError, match="no register reads"):
        floor_from_reads({})


def test_register_reads_refuse_emptiness() -> None:
    """Reading a register over nothing is a caller bug."""
    with pytest.raises(ValueError, match="no gate rows"):
        register_reads([])
