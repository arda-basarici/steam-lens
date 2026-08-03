"""Frame-check core tests — the stage-2 definitions hold at their edges.

Each test asserts one behavioral claim: the list bands cut exactly at the
ruled take-all ceiling and the disclosed floor; the histogram anchor grid
mirrors the sweep's span/cutoff/dedup semantics at bucket granularity;
truncation keeps the whole cutoff bucket and refuses an empty plan; month
rolling merges weekly buckets by UTC calendar month and leaves a monthly
series untouched.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from steamlens.contracts import HistogramBucket, HistogramSnapshot, RollupUnit
from steamlens.studies.frame import (
    ListBand,
    histogram_anchor_grid,
    list_band,
    month_rolled,
    truncate_rollups,
)


def _histogram(
    buckets: list[tuple[datetime, int, int]], unit: RollupUnit = RollupUnit.MONTH
) -> HistogramSnapshot:
    return HistogramSnapshot(
        app_id=10,
        rollup_unit=unit,
        rollups=tuple(
            HistogramBucket(start=start, recommendations_up=up, recommendations_down=down)
            for start, up, down in buckets
        ),
        recent_daily=(),
        past_events=(),
        fetched_at=datetime(2026, 8, 1, tzinfo=UTC),
    )


def _month(month: int, up: int, down: int = 0) -> tuple[datetime, int, int]:
    return datetime(2026, month, 1, tzinfo=UTC), up, down


def test_list_band_edges_follow_the_take_all_ruling() -> None:
    """2,000 is still take-all; the engaging band opens strictly above it."""
    assert list_band(2_000) is ListBand.TRUE_TAIL
    assert list_band(2_001) is ListBand.ENGAGING
    assert list_band(20_000) is ListBand.ENGAGING
    assert list_band(20_001) is ListBand.BRIDGE


def test_list_band_floor_and_ceiling_exclude() -> None:
    """Below the shape floor and at corpus scale the list admits nothing."""
    assert list_band(199) is None
    assert list_band(200) is ListBand.TRUE_TAIL
    assert list_band(59_999) is ListBand.BRIDGE
    assert list_band(60_000) is None


def test_list_band_refuses_a_negative_total() -> None:
    """A negative claim is a caller bug, never an out-of-band answer."""
    with pytest.raises(ValueError, match="non-negative"):
        list_band(-1)


def test_anchor_grid_cuts_the_populated_span_and_sums_claims() -> None:
    """Cutoffs interpolate first-to-last populated bucket; pools sum both votes."""
    histogram = _histogram([_month(1, 10, 5), _month(3, 20), _month(5, 40)])
    grid = histogram_anchor_grid(histogram, (0.5, 1.0))
    assert [a.pool_size for a in grid.anchors] == [35, 75]
    assert grid.anchors[0].cutoff == datetime(2026, 3, 2, tzinfo=UTC)
    assert grid.anchors[1].cutoff == datetime(2026, 5, 1, tzinfo=UTC)


def test_anchor_grid_drops_equal_pools_as_duplicates() -> None:
    """Equal pool sizes mean the identical pool — the later quantile is dropped."""
    histogram = _histogram([_month(1, 10), _month(6, 30)])
    grid = histogram_anchor_grid(histogram, (0.40, 0.55, 0.70, 0.85, 1.00))
    assert [a.quantile for a in grid.anchors] == [0.40, 1.00]
    assert grid.duplicates == (0.55, 0.70, 0.85)


def test_anchor_grid_zero_span_keeps_the_first_quantile() -> None:
    """One populated bucket collapses every anchor onto the same full pool."""
    histogram = _histogram([_month(4, 25, 5)])
    grid = histogram_anchor_grid(histogram, (0.40, 1.00))
    assert [a.quantile for a in grid.anchors] == [0.40]
    assert grid.anchors[0].pool_size == 30


def test_anchor_grid_refuses_an_empty_claim_and_a_bad_grid() -> None:
    """No reviews means no anchors; grid validation matches the sweep's contract."""
    with pytest.raises(ValueError, match="claims no reviews"):
        histogram_anchor_grid(_histogram([_month(1, 0)]), (1.0,))
    with pytest.raises(ValueError, match="ascending"):
        histogram_anchor_grid(_histogram([_month(1, 5)]), (0.7, 0.4))
    with pytest.raises(ValueError, match=r"lie in \(0, 1\]"):
        histogram_anchor_grid(_histogram([_month(1, 5)]), (0.4, 1.1))


def test_truncate_rollups_keeps_the_whole_cutoff_bucket() -> None:
    """A cutoff inside a bucket keeps that bucket — bucket granularity, honestly."""
    histogram = _histogram([_month(1, 10), _month(3, 20), _month(5, 40)])
    truncated = truncate_rollups(histogram, datetime(2026, 3, 15, tzinfo=UTC))
    assert [b.recommendations_up for b in truncated.rollups] == [10, 20]
    assert truncated.app_id == histogram.app_id


def test_truncate_rollups_refuses_an_empty_plan() -> None:
    """A cutoff before every populated bucket is the caller's bug, loudly."""
    histogram = _histogram([_month(3, 20)])
    with pytest.raises(ValueError, match="precedes every populated"):
        truncate_rollups(histogram, datetime(2026, 1, 1, tzinfo=UTC))


def test_month_rolled_merges_weeks_by_utc_calendar_month() -> None:
    """Weekly buckets sum into their start's calendar month, chronologically."""
    weekly = _histogram(
        [
            (datetime(2026, 1, 26, tzinfo=UTC), 5, 1),
            (datetime(2026, 2, 2, tzinfo=UTC), 7, 0),
            (datetime(2026, 2, 9, tzinfo=UTC), 3, 2),
        ],
        unit=RollupUnit.WEEK,
    )
    rolled = month_rolled(weekly)
    assert rolled.rollup_unit is RollupUnit.MONTH
    assert [(b.start, b.recommendations_up, b.recommendations_down) for b in rolled.rollups] == [
        (datetime(2026, 1, 1, tzinfo=UTC), 5, 1),
        (datetime(2026, 2, 1, tzinfo=UTC), 10, 2),
    ]


def test_month_rolled_leaves_a_monthly_series_untouched() -> None:
    """Steam's month buckets already start on month boundaries — idempotent."""
    monthly = _histogram([_month(1, 10, 5), _month(2, 20)])
    assert month_rolled(monthly).rollups == monthly.rollups
