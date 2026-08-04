"""Allowance-arithmetic tests — the mint's definitions hold their rulings.

Each test asserts one behavioral claim: band edges inclusive on the upper
side with non-shares refused, needed inflation as the centered
error-minus-half-width reading floored at zero with negative inputs refused,
the flat allowance as the minimal inflation actually reaching the register
(a ceiling order statistic, never an interpolation), and the smoothing
maxing over exactly the shipped tier and its nearest present neighbors.
"""

from __future__ import annotations

import pytest

from steamlens.studies.allowance import (
    ShareBand,
    flat_allowance,
    is_spiky_regime,
    needed_inflation,
    primary_band_tolerance,
    primary_shipped_allowance,
    share_band,
    smoothed_allowance,
)


def test_primary_tolerances_hold_the_ruled_table() -> None:
    """Tail ±1pt everywhere; calm mid ±2.5pts; spiky mid and headline are
    interval-governed — the checkpoint table with the stage-1 refinement."""
    assert primary_band_tolerance(ShareBand.TAIL, spiky=False) == 0.010
    assert primary_band_tolerance(ShareBand.TAIL, spiky=True) == 0.010
    assert primary_band_tolerance(ShareBand.MID, spiky=False) == 0.025
    assert primary_band_tolerance(ShareBand.MID, spiky=True) is None
    assert primary_band_tolerance(ShareBand.HEADLINE, spiky=False) is None
    assert primary_band_tolerance(ShareBand.HEADLINE, spiky=True) is None


def test_primary_allowances_hold_the_ruled_constants() -> None:
    """Calm 0/0/0, spiky 0/0.017/0.127 — the stage-1 splits' shipped values."""
    for band in ShareBand:
        assert primary_shipped_allowance(band, spiky=False) == 0.0
    assert primary_shipped_allowance(ShareBand.TAIL, spiky=True) == 0.0
    assert primary_shipped_allowance(ShareBand.MID, spiky=True) == 0.017
    assert primary_shipped_allowance(ShareBand.HEADLINE, spiky=True) == 0.127


def test_share_band_edges_are_inclusive_above() -> None:
    """Exactly 5% is mid and exactly 15% is headline — 'at or above' per the ruling."""
    assert share_band(0.0) is ShareBand.TAIL
    assert share_band(0.049) is ShareBand.TAIL
    assert share_band(0.05) is ShareBand.MID
    assert share_band(0.149) is ShareBand.MID
    assert share_band(0.15) is ShareBand.HEADLINE
    assert share_band(1.0) is ShareBand.HEADLINE


def test_share_band_refuses_non_shares() -> None:
    """A value outside [0, 1] is a wiring bug, never a band."""
    with pytest.raises(ValueError, match="outside"):
        share_band(-0.01)
    with pytest.raises(ValueError, match="outside"):
        share_band(1.01)


def test_needed_inflation_is_zero_under_coverage() -> None:
    """An error inside the half-width needs no inflation — floored at zero."""
    assert needed_inflation(0.02, 0.08) == 0.0
    assert needed_inflation(0.04, 0.08) == 0.0


def test_needed_inflation_is_the_centered_gap_past_the_half_width() -> None:
    """Past the half-width, the inflation is exactly error minus width over two."""
    assert needed_inflation(0.10, 0.08) == pytest.approx(0.06)


def test_needed_inflation_refuses_negative_inputs() -> None:
    """Neither an error nor a width can be negative — a wiring bug, not a draw."""
    with pytest.raises(ValueError, match="non-negative"):
        needed_inflation(-0.01, 0.08)
    with pytest.raises(ValueError, match="non-negative"):
        needed_inflation(0.02, -0.08)


def test_flat_allowance_is_the_minimal_inflation_reaching_the_register() -> None:
    """The ceiling order statistic — the step function's actual crossing point.

    Nineteen covered draws of twenty are already 95%, so the allowance is
    zero; drop one more and the allowance must climb to the next order
    statistic to reach the register — no interpolated in-between value
    covers a single additional draw.
    """
    assert flat_allowance([0.0] * 19 + [1.0]) == 0.0
    assert flat_allowance([0.0] * 18 + [0.5, 1.0]) == 0.5
    assert flat_allowance([0.0, 0.0, 0.0]) == 0.0


def test_flat_allowance_refuses_an_empty_pool() -> None:
    """No draws means a missing band, not a zero allowance."""
    with pytest.raises(ValueError, match="empty pool"):
        flat_allowance([])


def test_smoothed_allowance_maxes_over_shipped_and_nearest_neighbors() -> None:
    """Only the shipped tier and its adjacent present tiers enter the max."""
    calibrations = {100: 9.9, 750: 0.02, 1000: 0.01, 1500: 0.005, 5000: 8.0}
    assert smoothed_allowance(calibrations, shipped=1000) == 0.02


def test_smoothed_allowance_handles_a_boundary_tier() -> None:
    """A shipped tier at the ladder's edge smooths over the one side that exists."""
    assert smoothed_allowance({750: 0.02, 1000: 0.01}, shipped=1000) == 0.02
    assert smoothed_allowance({1000: 0.03}, shipped=1000) == 0.03


def test_smoothed_allowance_refuses_a_missing_shipped_tier() -> None:
    """Smoothing around a hole would pin the constant to the wrong n — refused."""
    with pytest.raises(ValueError, match="no calibration"):
        smoothed_allowance({750: 0.02, 1500: 0.005}, shipped=1000)


def test_spiky_regime_boundary_is_inclusive_at_two_thirds() -> None:
    """Exactly two-thirds of the pool in one window is spiky — the ruled edge."""
    assert is_spiky_regime(2 / 3)
    assert is_spiky_regime(0.9)
    assert not is_spiky_regime(0.66)
    assert not is_spiky_regime(0.05)


def test_spiky_regime_refuses_non_shares() -> None:
    """A peak share outside [0, 1] is a wiring bug, never a regime."""
    with pytest.raises(ValueError, match="outside"):
        is_spiky_regime(1.5)
