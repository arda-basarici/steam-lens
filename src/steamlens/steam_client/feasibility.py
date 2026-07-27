"""The fallback feasibility estimate — is the plain walk affordable, said before paying.

The plain-cursor fallback walks newest-first and must burn a page request per
``num_per_page`` reviews *above* the window before collecting anything, so a
deep window on a large game can cost thousands of paced requests. This
estimate prices that approach from the histogram — data already in hand — so
an unaffordable window becomes a disclosed ``SKIPPED_INFEASIBLE``, never a
silent multi-hour walk or a silent hole.

Private to ``steam_client`` by design: when the sampling plan compiler lands
in ``core/sampling``, this helper migrates there — the sampling study will
want to certify exactly this estimate.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from math import ceil
from typing import Final

from steamlens.contracts import HistogramSnapshot, RollupUnit

# A rollup bucket's nominal span: it holds reviews newer than the window's end
# whenever its span crosses that end, so the straddling bucket counts whole —
# a deliberate over-count in the skip direction, because the price of
# under-estimating is an unbounded walk and the price of over-estimating is a
# disclosed skip.
_ROLLUP_SPANS: Final = {
    RollupUnit.MONTH: timedelta(days=31),
    RollupUnit.WEEK: timedelta(days=7),
}


def estimate_skip_pages(
    histogram: HistogramSnapshot, window_end: datetime, page_size: int
) -> int:
    """Pages the plain newest-first walk burns before reaching the window's end.

    Sums every rollup bucket that could hold reviews newer than ``window_end``
    (recommend-up plus recommend-down is the bucket's review count — every
    review carries one or the other) and divides by the page size, rounding
    up. Pure: histogram in, page count out.
    """
    span = _ROLLUP_SPANS[histogram.rollup_unit]
    above_window_end = sum(
        bucket.recommendations_up + bucket.recommendations_down
        for bucket in histogram.rollups
        if bucket.start + span > window_end
    )
    return ceil(above_window_end / page_size)
