"""Episode detection — the flag rule, the merge, and the guards that keep it honest.

The claims: a spike over a quiet baseline flags with its true magnitude, the
median baseline resists being dragged by the spike itself (the reason it is a
median), adjacent flags merge into one span, and the two guards hold — no
flag without a full trailing window (so a launch is never an "episode") and
none below the volume floor (so a ratio over near-zero noise stays unmarked).
Spans are computed on the native rollup unit, which the weekly case pins.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from steamlens.contracts import (
    HistogramBucket,
    HistogramSnapshot,
    ReviewEvent,
    RollupUnit,
)
from steamlens.core.detect import (
    detect_episodes,
    overlaps_marked_window,
)


def _snapshot(
    volumes: list[int],
    *,
    unit: RollupUnit = RollupUnit.MONTH,
    events: tuple[ReviewEvent, ...] = (),
) -> HistogramSnapshot:
    """A histogram whose buckets carry ``volumes``, spaced by the rollup unit."""
    step = timedelta(days=7 if unit is RollupUnit.WEEK else 30)
    start = datetime(2025, 1, 6, tzinfo=UTC)
    return HistogramSnapshot(
        app_id=1,
        rollup_unit=unit,
        rollups=tuple(
            HistogramBucket(
                start=start + step * index,
                recommendations_up=volume,
                recommendations_down=0,
            )
            for index, volume in enumerate(volumes)
        ),
        recent_daily=(),
        past_events=events,
        fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_a_spike_over_a_quiet_baseline_flags_with_its_magnitude() -> None:
    """Six quiet buckets then a 10x bucket: one episode, peak multiple reported."""
    snapshot = _snapshot([100] * 6 + [1_000])
    (episode,) = detect_episodes(snapshot)
    assert (episode.buckets, episode.reviews) == (1, 1_000)
    assert episode.peak_multiple == pytest.approx(10.0)
    assert episode.start == snapshot.rollups[6].start
    assert episode.end == snapshot.rollups[6].start + timedelta(days=30)


def test_adjacent_flagged_buckets_merge_into_one_episode() -> None:
    """A two-bucket surge is one episode, not two markers on the timeline."""
    snapshot = _snapshot([100] * 6 + [900, 800, 100])
    (episode,) = detect_episodes(snapshot)
    assert (episode.buckets, episode.reviews) == (2, 1_700)
    assert (episode.start, episode.end) == (
        snapshot.rollups[6].start,
        snapshot.rollups[8].start,
    )


def test_the_median_baseline_resists_the_spike_dragging_it() -> None:
    """A huge bucket inside the trailing window barely moves the median, so the
    bucket after it is still judged against the quiet months — which a mean
    baseline would not do."""
    snapshot = _snapshot([100, 100, 100, 5_000, 100, 100, 500])
    (episode,) = detect_episodes(snapshot)
    assert episode.peak_multiple == pytest.approx(5.0)  # 500 / median(100..100) = 5


def test_no_flag_without_a_full_trailing_window() -> None:
    """A launch spike is the game starting, not an episode — nothing before it
    can serve as a baseline, so it is never marked."""
    assert detect_episodes(_snapshot([5_000, 100, 100])) == ()
    assert detect_episodes(_snapshot([100] * 5 + [5_000])) == ()


def test_the_volume_floor_blocks_ratios_over_near_zero_baselines() -> None:
    """Three reviews after months of one is a 3x spike and means nothing."""
    assert detect_episodes(_snapshot([1] * 6 + [20])) == ()
    (episode,) = detect_episodes(_snapshot([1] * 6 + [20]), min_volume=10)
    assert episode.reviews == 20


def test_spans_follow_the_native_rollup_unit() -> None:
    """A weekly-served game gets week-wide spans; the detector never assumes months."""
    snapshot = _snapshot([100] * 6 + [1_000], unit=RollupUnit.WEEK)
    (episode,) = detect_episodes(snapshot)
    assert episode.end - episode.start == timedelta(days=7)


def test_a_quiet_game_yields_no_episodes() -> None:
    """The common, correct answer — steady volume is not an event."""
    assert detect_episodes(_snapshot([100, 110, 95, 105, 100, 98, 102, 99])) == ()


def test_a_nonsense_threshold_fails_loudly() -> None:
    """k or window at zero would make a flag-everything detector, silently."""
    with pytest.raises(ValueError, match="k must be positive"):
        detect_episodes(_snapshot([100] * 8), k=0)
    with pytest.raises(ValueError, match="window must be positive"):
        detect_episodes(_snapshot([100] * 8), window=0)


def test_marked_window_overlap_is_reported_as_the_fact_it_is() -> None:
    """Overlap with a Valve-flagged window is checkable; absence claims nothing."""
    snapshot = _snapshot([100] * 6 + [1_000])
    (episode,) = detect_episodes(snapshot)
    covering = ReviewEvent(
        event_type=0, start=episode.start - timedelta(days=1), end=episode.end
    )
    elsewhere = ReviewEvent(
        event_type=0,
        start=episode.end + timedelta(days=90),
        end=episode.end + timedelta(days=120),
    )
    assert overlaps_marked_window(episode, _snapshot([1], events=(covering,)))
    assert not overlaps_marked_window(episode, _snapshot([1], events=(elsewhere,)))
