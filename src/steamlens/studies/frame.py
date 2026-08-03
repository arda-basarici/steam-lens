"""Label-free frame checks for long-tail stage 2 — measuring off-corpus shape.

Stage 2 of the long-tail evidence (DESIGN, the study-design section) asks what
the stage-1 ruling made load-bearing: do genuinely long-tail games land in the
spiky allowance regime (peak window share at or above the ruled 2/3), and do
their temporal structures and pool sizes fall inside the range the corpus
spans? Both questions answer from a game's live review histogram alone — no
review fetch, no LLM spend — because the histogram *is* the production
instrument: the windowed compiler plans one window per populated rollup
bucket, and the regime ruling conditions on a share computable from the live
histogram before any draw.

Everything here is the pure middle of that check. The list-band definition
says which games a discovery probe may admit (edges aligned to the ruled
take-all cutoff, so each band asks a distinct question of the size rule); the
anchor grid mirrors the sweep's query-anchor semantics at bucket granularity,
so fresh (game, anchor) units land on the same replication grain the run of
record certified; truncation and month-rolling produce the histogram views
those units are measured on. The shape metric itself stays in
``studies.shape`` and the regime boundary in ``studies.allowance`` — this
module feeds them, never redefines them.

One honesty note carried into every consumer: bucket granularity is coarser
than the sweep's review-level grid. A histogram anchor's cutoff includes the
whole bucket it lands in, and pool sizes are Steam's all-language claim
totals rather than counted reviews. Both approximations are the finest
instrument a label-free check has, and the all-language basis matches what
production planning itself sees.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

from steamlens.contracts import HistogramBucket, HistogramSnapshot, RollupUnit
from steamlens.studies.sweep_corpus import Anchor, AnchorGrid

TAKE_ALL_POOL_CEILING: Final = 2_000
"""The ruled size rule's take-all edge (the curves checkpoint, 2026-08-02): a
pool at or below this is fetched and classified whole, so sampling — and with
it the size rule — only engages above it."""


class ListBand(StrEnum):
    """The discovery list's review-count bands — one distinct question each.

    Bands are defined on Steam's whole-game, all-language ``total_reviews``
    claim (the one-request totals read), the same population basis the live
    histogram reports. ``TRUE_TAIL`` sits at or below the take-all ceiling,
    where production samples nothing — those games document that take-all
    covers the actual tail, and their regime is measured for the report's
    regime-distribution statement. ``ENGAGING`` is where the ruled size rule
    actually draws, so it carries the transfer question and the heaviest
    weight in the list. ``BRIDGE`` spans the gap toward corpus-scale games so
    the in-range comparison is continuous rather than a two-cluster contrast.
    """

    TRUE_TAIL = "true-tail"
    ENGAGING = "engaging"
    BRIDGE = "bridge"


LIST_BAND_FLOOR: Final = 200
"""Below this total a histogram is too sparse to carry a measurable shape —
excluded from the list by construction, and disclosed as such: production
take-all covers those games trivially."""

ENGAGING_CEILING: Final = 20_000
BRIDGE_CEILING: Final = 60_000


def list_band(total_reviews: int) -> ListBand | None:
    """The discovery band ``total_reviews`` lands in, or ``None`` outside all.

    Edges follow the take-all ruling, not round numbers: ``TRUE_TAIL`` runs
    from the floor through the take-all ceiling *inclusive* (a 2,000-review
    pool is still fetched whole), ``ENGAGING`` opens strictly above it, and
    ``BRIDGE`` ends below the ceiling that would start overlapping corpus
    scale. Negative totals are a caller bug and raise.
    """
    if total_reviews < 0:
        raise ValueError(f"total_reviews is {total_reviews}, expected non-negative")
    if total_reviews < LIST_BAND_FLOOR:
        return None
    if total_reviews <= TAKE_ALL_POOL_CEILING:
        return ListBand.TRUE_TAIL
    if total_reviews <= ENGAGING_CEILING:
        return ListBand.ENGAGING
    if total_reviews < BRIDGE_CEILING:
        return ListBand.BRIDGE
    return None


def histogram_anchor_grid(
    histogram: HistogramSnapshot, quantiles: tuple[float, ...]
) -> AnchorGrid:
    """The sweep's query anchors, placed from a histogram instead of reviews.

    Mirrors ``sweep_corpus.anchor_grid`` semantics at bucket granularity:
    each quantile cuts at ``oldest + q * (newest - oldest)`` of the span
    between the first and last *populated* rollup buckets, an anchor's pool
    is the claim total of populated buckets starting at or before the cutoff,
    and equal pool sizes mean the identical pool (truncation is monotone), so
    the later quantile is recorded as a duplicate and dropped. Raises on a
    histogram claiming no reviews or an unsorted/out-of-range grid — both
    caller bugs, same contract as the review-level grid.
    """
    if not quantiles or list(quantiles) != sorted(quantiles):
        raise ValueError(f"anchor quantiles must be ascending, got {quantiles!r}")
    if quantiles[0] <= 0.0 or quantiles[-1] > 1.0:
        raise ValueError(f"anchor quantiles must lie in (0, 1], got {quantiles!r}")
    populated = _populated_rollups(histogram)
    oldest, newest = populated[0].start, populated[-1].start
    anchors: list[Anchor] = []
    duplicates: list[float] = []
    for quantile in quantiles:
        cutoff = oldest + (newest - oldest) * quantile
        pool_size = sum(_claims(b) for b in populated if b.start <= cutoff)
        if anchors and anchors[-1].pool_size == pool_size:
            duplicates.append(quantile)
            continue
        anchors.append(Anchor(quantile=quantile, cutoff=cutoff, pool_size=pool_size))
    return AnchorGrid(anchors=tuple(anchors), duplicates=tuple(duplicates))


def truncate_rollups(histogram: HistogramSnapshot, cutoff: datetime) -> HistogramSnapshot:
    """The histogram a query at ``cutoff`` would have planned from.

    Keeps every rollup bucket starting at or before the cutoff; the other
    series ride along unchanged — windowed planning and the shape metric read
    only ``rollups``. Raises if no populated bucket survives: a cutoff before
    the first review is a caller bug, and an empty plan downstream would blame
    the wrong layer.
    """
    kept = tuple(b for b in histogram.rollups if b.start <= cutoff)
    if not any(_claims(b) > 0 for b in kept):
        raise ValueError(
            f"app_id {histogram.app_id}: cutoff {cutoff.isoformat()} precedes every "
            "populated rollup bucket — nothing to plan from"
        )
    return replace(histogram, rollups=kept)


def month_rolled(histogram: HistogramSnapshot) -> HistogramSnapshot:
    """The rollup series re-bucketed to calendar months — the corpus-comparable view.

    Steam serves weekly rollups for young games and monthly for old ones, and
    the regime metric moves with the bucket width; the corpus's stage-1
    spikiness values were minted over monthly buckets. Rolling by the UTC
    calendar month of each bucket's start gives fresh games a reading on the
    corpus's instrument next to their native one. Idempotent on a monthly
    series — Steam's month buckets already start on month boundaries.
    """
    claims_by_month: dict[datetime, tuple[int, int]] = defaultdict(lambda: (0, 0))
    for bucket in histogram.rollups:
        month = datetime(bucket.start.year, bucket.start.month, 1, tzinfo=UTC)
        up, down = claims_by_month[month]
        claims_by_month[month] = (
            up + bucket.recommendations_up,
            down + bucket.recommendations_down,
        )
    rolled = tuple(
        HistogramBucket(start=month, recommendations_up=up, recommendations_down=down)
        for month, (up, down) in sorted(claims_by_month.items())
    )
    return replace(histogram, rollup_unit=RollupUnit.MONTH, rollups=rolled)


def _populated_rollups(histogram: HistogramSnapshot) -> tuple[HistogramBucket, ...]:
    """The rollup buckets with any claim, chronological; raises on an empty pool."""
    populated = sorted(
        (b for b in histogram.rollups if _claims(b) > 0), key=lambda b: b.start
    )
    if not populated:
        raise ValueError(
            f"app_id {histogram.app_id}: histogram claims no reviews — "
            "an empty pool has no anchors"
        )
    return tuple(populated)


def _claims(bucket: HistogramBucket) -> int:
    """A bucket's review claim, both vote directions."""
    return bucket.recommendations_up + bucket.recommendations_down
