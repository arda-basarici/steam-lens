"""The shipped interval rule — bands, regimes, and the ruled constants a report quotes.

The sampling study's shipped promise (the curves checkpoint 2026-08-02, the
long-tail stage-1 splits 2026-08-03): a sampled share displays Wilson plus a
per-band constant allowance, because the windowed draw's newest-first prefix
carries a bias Wilson's width does not price. This module is that rule's
production home — relocated from the study package (2026-08-08, the frontend
build) because the report page is its first real consumer and the study shells
are import-forbidden to everything; the *mint arithmetic* that re-derives
these constants from the run of record stays in ``studies.allowance``, which
imports nothing back.

- ``share_band`` — the ruled display bands over a share: tail below 5%, mid
  from 5% to below 15%, headline at 15% and above.
- ``peak_window_share`` / ``is_spiky_regime`` — the regime axis: a pool whose
  busiest histogram bucket claims two-thirds or more of its reviews is
  spiky, and the constants condition on that regime (the splits located the
  entire windowed penalty in spiky pools).
- ``primary_shipped_allowance`` — the ruled constants per band and regime,
  re-derivable via ``scripts/mint_allowances.py`` over the run of record
  ``m2sweep-20260802T132010Z-2969bcab``.
- ``shipped_interval`` — the composed whisker: Wilson plus the allowance,
  clamped to ``[0, 1]``.

Take-all pools quote the exact number and no interval; nothing here ever
applies to them — the allowance prices sampled draws only.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from steamlens.contracts import HistogramSnapshot
from steamlens.core.intervals import Interval, wilson_interval

TAIL_SHARE_CEILING: Final = 0.05
"""The tail band's upper edge — a share below this is tail material."""

HEADLINE_SHARE_FLOOR: Final = 0.15
"""The headline band's lower edge — a share at or above this displays as a
headline aspect (the curves checkpoint's band ruling, 2026-08-02)."""

SHIPPED_SAMPLE_SIZE: Final = 1000
"""The size rule's sampled n (the curves checkpoint, 2026-08-02) — the tier
the shipped constants pin to."""

SPIKY_PEAK_SHARE_FLOOR: Final = 2 / 3
"""The regime boundary (the stage-1 splits ruling, 2026-08-03): a pool whose
busiest window claims two-thirds or more of its reviews is spiky, and the
allowance constants condition on the regime. Runtime-computable before any
draw — the live histogram arrives ahead of window planning."""


def peak_window_share(histogram: HistogramSnapshot) -> float:
    """The pool share of the busiest rollup bucket — the spikiness axis.

    A review-bombed month, a launch spike, or simply a young game's short
    span all land here as one large window claiming a big slice of the draw;
    the metric deliberately does not distinguish the causes, because the
    windowed draw doesn't either — what matters to transfer is how much of
    the quota one window swallows. Claims count both vote directions;
    zero-claim buckets dilute nothing. Raises on a histogram claiming no
    reviews at all — there is no pool to have a shape.
    """
    claims = [
        bucket.recommendations_up + bucket.recommendations_down
        for bucket in histogram.rollups
    ]
    total = sum(claims)
    if total == 0:
        raise ValueError(
            f"app_id {histogram.app_id}: histogram claims no reviews — "
            "an empty pool has no shape to measure"
        )
    return max(claims) / total


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
    """Assign a share to its ruled band, edges inclusive on the upper side.

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
    is covered by the shipped interval exactly when its needed inflation
    (``studies.allowance.needed_inflation``) is at or under this constant —
    the same centered reading the constants were minted from.
    """
    return _PRIMARY_ALLOWANCES[spiky][band]


def shipped_interval(successes: int, sample_size: int, *, spiky: bool) -> Interval:
    """The shipped whisker: Wilson plus the regime-and-band allowance, clamped to ``[0, 1]``.

    The interval a report page draws for one sampled aspect share. The band
    assigns from the sample share — the only share production knows; the
    study calibrated bands on census truth, and the sample share is its
    estimate. Calm-regime allowances are all zero, so there this *is* the
    Wilson interval. Never called for take-all pools (an exact count has no
    sampling error to price — the caller renders "complete count" instead).

    >>> shipped_interval(270, 1000, spiky=False) == wilson_interval(270, 1000)
    True
    >>> calm = shipped_interval(270, 1000, spiky=False)
    >>> spiky = shipped_interval(270, 1000, spiky=True)
    >>> round(calm.low - spiky.low, 3), round(spiky.high - calm.high, 3)
    (0.127, 0.127)
    """
    base = wilson_interval(successes, sample_size)
    allowance = primary_shipped_allowance(
        share_band(successes / sample_size), spiky=spiky
    )
    return Interval(
        low=max(0.0, base.low - allowance), high=min(1.0, base.high + allowance)
    )
