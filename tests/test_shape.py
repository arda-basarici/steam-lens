"""Shape-metric tests — the long-tail stage-1 axes hold their definitions.

Each test asserts one behavioral claim: the peak window share is the busiest
bucket's claim over the total with both vote directions counted, zero-claim
buckets diluting nothing, and an empty claim refused; the headline count is
inclusive at the ruled floor, honors a sensitivity floor, and refuses an
empty reference.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from steamlens.contracts import HistogramBucket, HistogramSnapshot, RollupUnit
from steamlens.studies.shape import headline_aspect_count, peak_window_share


def _histogram(claims: list[tuple[int, int]]) -> HistogramSnapshot:
    return HistogramSnapshot(
        app_id=10,
        rollup_unit=RollupUnit.MONTH,
        rollups=tuple(
            HistogramBucket(
                start=datetime(2026, month, 1, tzinfo=UTC),
                recommendations_up=up,
                recommendations_down=down,
            )
            for month, (up, down) in enumerate(claims, start=1)
        ),
        recent_daily=(),
        past_events=(),
        fetched_at=datetime(2026, 7, 1, tzinfo=UTC),
    )


def test_peak_window_share_is_the_busiest_buckets_claim() -> None:
    """The spike month's claim over the total, both vote directions counted."""
    histogram = _histogram([(10, 0), (50, 10), (20, 10)])
    assert peak_window_share(histogram) == 60 / 100


def test_peak_window_share_ignores_zero_claim_buckets() -> None:
    """Quiet months in the contiguous series dilute nothing."""
    spiky = _histogram([(30, 0), (0, 0), (0, 0), (10, 0)])
    assert peak_window_share(spiky) == 30 / 40


def test_peak_window_share_uniform_pool_is_one_over_buckets() -> None:
    """An evenly spread pool bottoms out at 1/k — the flat-shape baseline."""
    histogram = _histogram([(25, 0), (25, 0), (25, 0), (25, 0)])
    assert peak_window_share(histogram) == 0.25


def test_peak_window_share_refuses_an_empty_claim() -> None:
    """A histogram claiming no reviews has no shape — a caller bug, not a zero."""
    with pytest.raises(ValueError, match="claims no reviews"):
        peak_window_share(_histogram([(0, 0), (0, 0)]))


def test_headline_aspect_count_is_inclusive_at_the_floor() -> None:
    """A share exactly at the floor is headline — the band ruling is 'at or above'."""
    shares = {"combat": 0.30, "performance": 0.15, "audio": 0.149, "story": 0.02}
    assert headline_aspect_count(shares) == 2


def test_headline_aspect_count_honors_a_sensitivity_floor() -> None:
    """The floor parameter moves the cut without touching the default band."""
    shares = {"combat": 0.30, "performance": 0.15, "story": 0.02}
    assert headline_aspect_count(shares, floor=0.25) == 1
    assert headline_aspect_count(shares, floor=0.01) == 3


def test_headline_aspect_count_refuses_an_empty_reference() -> None:
    """No reference shares means broken wiring upstream, never a count of zero."""
    with pytest.raises(ValueError, match="no reference shares"):
        headline_aspect_count({})
