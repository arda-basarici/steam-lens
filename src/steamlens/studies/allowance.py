"""The calibrated interval's bias allowance — band assignment and the mint arithmetic.

The curves checkpoint (ruled 2026-08-02, DESIGN's study-design section) ships
Wilson plus a per-band constant allowance: the windowed draw's newest-first
prefix carries a bias that Wilson's width does not price, so the shipped
half-width adds a constant calibrated to restore the 95% register on the run
of record. This module owns the arithmetic the constants re-derive from —
DESIGN's promise is "re-derived from the run, never hand-carried", and the
checkpoint's own numbers were minted by session scratch (the FIXLOG entry this
module closes), so the definition now lives here where the mint script and the
long-tail split views both consume it:

- ``share_band`` — the ruled display bands over an aspect's census share:
  tail below 5%, mid from 5% to below 15%, headline at 15% and above.
- ``needed_inflation`` — one draw's atom: the flat half-width addition that
  would have covered the truth, in the centered reading (error minus
  half-width) the ruled constants were minted from.
- ``flat_allowance`` — a band's calibration at one size: the *minimal* flat
  inflation under which the register's fraction of draws is covered — a
  ceiling order statistic, because coverage is a step function of the
  inflation and an interpolated quantile would quote a value that does not
  reach the register.
- ``smoothed_allowance`` — the shipped constant: the max of the calibration
  over the shipped tier and its ladder neighbors, deliberate conservatism
  against the thin headline band's order-statistic noise.

Reproduction was verified before this graduation: over the run of record
``m2sweep-20260802T132010Z-2969bcab`` these definitions re-derive exactly
the checkpoint's flat constants, tail 0.000 / mid 0.005 / headline 0.073.

The long-tail stage-1 splits (ruled 2026-08-03) superseded the flat
constants with regime-conditioned ones: the flat numbers averaged a calm
regime needing no allowance at all into a spiky regime needing roughly
double, so the shipped constants now mint per regime — ``is_spiky_regime``
over the pool's peak window share decides which set a report quotes.

Take-all pools quote the exact number and no interval, so nothing here ever
applies to them; the allowance prices sampled draws only.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Final

from steamlens.studies.shape import HEADLINE_SHARE_FLOOR

TAIL_SHARE_CEILING: Final = 0.05
"""The tail band's upper edge — a census share below this is tail material."""

SHIPPED_SAMPLE_SIZE: Final = 1000
"""The size rule's sampled n (the curves checkpoint, 2026-08-02) — the tier
the shipped constants pin to."""

SPIKY_PEAK_SHARE_FLOOR: Final = 2 / 3
"""The regime boundary (the stage-1 splits ruling, 2026-08-03): a pool whose
busiest window claims two-thirds or more of its reviews is spiky, and the
allowance constants condition on the regime. Runtime-computable before any
draw — the live histogram arrives ahead of window planning."""


def is_spiky_regime(peak_share: float) -> bool:
    """Whether a pool's peak window share puts it in the spiky allowance regime.

    The stage-1 splits located the entire windowed penalty in spiky pools:
    with spiky units set aside, no band at any pool size needs any allowance,
    so the constants mint per regime rather than averaging two very different
    games into one flat number. The boundary is inclusive — exactly
    two-thirds is spiky — and the threshold ruled over a sweep showing the
    calm regime's constants at zero for every candidate cut from 0.50 to
    0.75, so only the spiky side's calibration hinged on it.
    """
    if not 0.0 <= peak_share <= 1.0:
        raise ValueError(f"peak share {peak_share} lies outside [0, 1] — not a pool share")
    return peak_share >= SPIKY_PEAK_SHARE_FLOOR


class ShareBand(StrEnum):
    """The ruled display bands — the tolerance and the allowance condition on these."""

    TAIL = "tail"
    MID = "mid"
    HEADLINE = "headline"


def share_band(share: float) -> ShareBand:
    """Assign a census share to its ruled band, edges inclusive on the upper side.

    A share of exactly 5% is mid and exactly 15% is headline — both bands are
    "at or above" their floor, matching the checkpoint's wording. Raises on a
    share outside ``[0, 1]``: that is not a share, and banding it would file a
    wiring bug under a legitimate-looking label.
    """
    if not 0.0 <= share <= 1.0:
        raise ValueError(f"share {share} lies outside [0, 1] — not a share at all")
    if share < TAIL_SHARE_CEILING:
        return ShareBand.TAIL
    if share < HEADLINE_SHARE_FLOOR:
        return ShareBand.MID
    return ShareBand.HEADLINE


_PRIMARY_ALLOWANCES: Final[dict[bool, dict[ShareBand, float]]] = {
    False: {ShareBand.TAIL: 0.000, ShareBand.MID: 0.000, ShareBand.HEADLINE: 0.000},
    True: {ShareBand.TAIL: 0.000, ShareBand.MID: 0.017, ShareBand.HEADLINE: 0.127},
}
"""The primary path's shipped constants, keyed by spikiness (the stage-1
splits ruling, 2026-08-03) — re-derivable from the run of record via
``scripts/mint_allowances.py``; these literals are the ruled values, recorded
in DESIGN's long-tail stage-1 entry."""

_PRIMARY_TOLERANCES: Final[dict[bool, dict[ShareBand, float | None]]] = {
    False: {ShareBand.TAIL: 0.010, ShareBand.MID: 0.025, ShareBand.HEADLINE: None},
    True: {ShareBand.TAIL: 0.010, ShareBand.MID: None, ShareBand.HEADLINE: None},
}
"""The ruled share-error tolerances (the curves checkpoint, 2026-08-02;
spiky mid joined the headline's tolerance-free treatment at the stage-1
splits, 2026-08-03). ``None`` means the band's promise is the calibrated
interval alone — a tolerance there would either restate the interval width
or claim a precision the windowed draw cannot deliver."""


def primary_band_tolerance(band: ShareBand, *, spiky: bool) -> float | None:
    """The ruled share-error tolerance for one band under one regime.

    ``None`` for the interval-governed cells (headline everywhere, spiky
    mid): those displayed numbers carry no separate error tolerance, so a
    gate over them reads coverage only.
    """
    return _PRIMARY_TOLERANCES[spiky][band]


def primary_shipped_allowance(band: ShareBand, *, spiky: bool) -> float:
    """The primary path's shipped half-width constant for one band and regime.

    The number added to Wilson's half-width in the shipped interval; a draw
    is covered by the shipped interval exactly when its ``needed_inflation``
    is at or under this constant — the same centered reading the constants
    were minted from.
    """
    return _PRIMARY_ALLOWANCES[spiky][band]


def needed_inflation(error: float, width: float) -> float:
    """The flat half-width addition that would have covered this draw's truth.

    The centered reading the ruled constants were minted from: the share
    error minus half the quoted width, floored at zero for a covered draw.
    Wilson's true interval is not centered on the sample share — its center
    leans toward one half — so on the far side this slightly overprices the
    gap relative to the exact edge distance; deliberate, because the
    checkpoint ratified constants from this reading and its error is in the
    conservative direction (wider shipped bars, never narrower). Negative
    inputs are refused — neither an error nor a width can be one.
    """
    if error < 0 or width < 0:
        raise ValueError(f"error {error} and width {width} must be non-negative")
    return max(0.0, error - width / 2)


def flat_allowance(needed: Sequence[float], *, register: float = 0.95) -> float:
    """One band-and-size pool's calibration: the minimal inflation reaching the register.

    The smallest value under which at least the register's fraction of the
    pool's draws would have been covered — the ceiling order statistic of
    the pool, covered draws entering as zeros. Not an interpolated quantile:
    coverage is a step function of the inflation, so a value between two
    order statistics covers no more draws than the lower one and the
    interpolation would quote an inflation that does not reach the register.
    Raises on an empty pool: a calibration over nothing is not conservatism,
    it is a missing band.
    """
    if not needed:
        raise ValueError("cannot calibrate an allowance over an empty pool")
    ordered = sorted(needed)
    return ordered[math.ceil(register * len(ordered)) - 1]


def smoothed_allowance(calibrations: Mapping[int, float], shipped: int) -> float:
    """The shipped constant: the max calibration over the shipped tier and its neighbors.

    ``calibrations`` maps ladder sizes to their ``flat_allowance`` results;
    the neighbors are the nearest present tiers on either side of ``shipped``.
    The max is deliberate conservatism (the checkpoint's smoothing ruling):
    the headline band is thin, so any single tier's 95th percentile is a
    noisy order statistic. Raises when the shipped tier itself is absent —
    smoothing around a hole would silently pin the constant to the wrong n.
    """
    if shipped not in calibrations:
        raise ValueError(f"shipped size {shipped} has no calibration to smooth around")
    below = [size for size in calibrations if size < shipped]
    above = [size for size in calibrations if size > shipped]
    tiers = [shipped] + ([max(below)] if below else []) + ([min(above)] if above else [])
    return max(calibrations[tier] for tier in tiers)
