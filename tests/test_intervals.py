"""Interval-formula tests — the three raced candidates' behavioral claims.

Each candidate is pinned to hand-checked reference values and to the
properties the race relies on: Wilson's non-degenerate boundaries, the exact
bootstrap matching the binomial quantiles it claims to be, the stratified
formula's finite-population honesty (a take-all draw has zero sampling
error), the openly-carried degeneracies, and the loud input guards shared by
all three.
"""

from __future__ import annotations

import pytest

from steamlens.core.intervals import (
    Stratum,
    exact_bootstrap_interval,
    stratified_interval,
    wilson_interval,
)


def test_wilson_matches_the_hand_checked_value() -> None:
    """27 of 100 at 95%: the textbook Wilson bounds, not a lookalike."""
    interval = wilson_interval(27, 100)
    assert interval.low == pytest.approx(0.1927, abs=1e-3)
    assert interval.high == pytest.approx(0.3643, abs=1e-3)


def test_wilson_boundaries_do_not_collapse() -> None:
    """At 0% and 100% the interval keeps width — the reason Wilson beat Wald."""
    at_zero = wilson_interval(0, 50)
    at_full = wilson_interval(50, 50)
    assert at_zero.low == pytest.approx(0.0, abs=1e-12)
    assert at_zero.high > 0.05
    assert at_full.high == pytest.approx(1.0, abs=1e-12)
    assert at_full.low < 0.95


def test_wilson_narrows_with_sample_size() -> None:
    """More draws, tighter interval — the basic sanity of any error bar."""
    wide = wilson_interval(27, 100)
    narrow = wilson_interval(270, 1000)
    assert (narrow.high - narrow.low) < (wide.high - wide.low)


def test_exact_bootstrap_matches_binomial_quantiles() -> None:
    """50 of 100 brackets at the known Binomial(100, .5) tail points, 40 and 60."""
    interval = exact_bootstrap_interval(50, 100)
    assert interval.low == pytest.approx(0.40)
    assert interval.high == pytest.approx(0.60)


def test_exact_bootstrap_boundary_degeneracy_is_visible() -> None:
    """A 0% or 100% share yields zero width — the percentile bootstrap's own flaw."""
    assert exact_bootstrap_interval(0, 200).high == 0.0
    assert exact_bootstrap_interval(200, 200).low == 1.0


def test_exact_bootstrap_covers_the_sample_share() -> None:
    """The percentile interval always brackets the share it was built from."""
    interval = exact_bootstrap_interval(27, 1000)
    assert interval.covers(0.027)


def test_stratified_matches_the_hand_checked_value() -> None:
    """Two equal strata, shares .2 and .8: estimate .5, half-width .1753."""
    interval = stratified_interval(
        (Stratum(2, 10, 100), Stratum(8, 10, 100))
    )
    assert interval.low == pytest.approx(0.3247, abs=1e-3)
    assert interval.high == pytest.approx(0.6753, abs=1e-3)


def test_stratified_take_all_stratum_contributes_zero_variance() -> None:
    """Sampling a whole window leaves no sampling error — the FPC's honesty."""
    interval = stratified_interval((Stratum(3, 10, 10),))
    assert interval.low == pytest.approx(0.3)
    assert interval.high == pytest.approx(0.3)


def test_stratified_single_review_stratum_is_the_documented_degeneracy() -> None:
    """A one-review window estimates zero variance — carried openly, not patched."""
    interval = stratified_interval((Stratum(1, 1, 50),))
    assert interval.low == pytest.approx(1.0)
    assert interval.high == pytest.approx(1.0)


def test_stratified_weights_by_claimed_population() -> None:
    """A big window moves the estimate more than a small one, share for share."""
    interval = stratified_interval(
        (Stratum(9, 10, 900), Stratum(0, 10, 100))
    )
    assert (interval.low + interval.high) / 2 == pytest.approx(0.81)


def test_bounds_are_clipped_to_the_unit_interval() -> None:
    """No formula quotes a share below 0% or above 100%."""
    near_one = stratified_interval((Stratum(9, 10, 1000), Stratum(10, 10, 1000)))
    assert near_one.high <= 1.0
    assert wilson_interval(1, 2).high <= 1.0
    assert wilson_interval(1, 2).low >= 0.0


def test_incoherent_counts_fail_loud() -> None:
    """Zero draws, negative or overflowing successes, oversampled strata: caller bugs."""
    with pytest.raises(ValueError, match="at least one draw"):
        wilson_interval(0, 0)
    with pytest.raises(ValueError, match="incoherent"):
        exact_bootstrap_interval(5, 4)
    with pytest.raises(ValueError, match="incoherent"):
        wilson_interval(-1, 10)
    with pytest.raises(ValueError, match="zero strata"):
        stratified_interval(())
    with pytest.raises(ValueError, match="more reviews than the window holds"):
        stratified_interval((Stratum(1, 5, 4),))
