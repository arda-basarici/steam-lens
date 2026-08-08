"""The allowance mint arithmetic — how the shipped constants re-derive from the run.

The shipped rule itself — bands, regimes, the ruled constants, the composed
interval — lives in ``core.allowance`` (relocated 2026-08-08: the report page
became the rule's first production consumer, and the study shells are
import-forbidden to everything). What stays here is the arithmetic only a
re-mint runs, DESIGN's "re-derived from the run, never hand-carried" promise
made executable — ``scripts/mint_allowances.py`` composes these over the run
of record and must land exactly on the constants ``core.allowance`` ships:

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

Reproduction was verified before the original graduation: over the run of
record ``m2sweep-20260802T132010Z-2969bcab`` these definitions re-derive
exactly the checkpoint's flat constants, tail 0.000 / mid 0.005 / headline
0.073 (superseded by the regime-conditioned constants at the stage-1 splits).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence


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
