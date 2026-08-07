"""Episode markers — spike detection over review volume, kept deliberately dumb.

Histogram in, episode list out: a pure transform with no model in it. A bucket
flags when its volume exceeds ``k`` times the trailing median of the buckets
before it, and adjacent flags merge into one episode span. The median (not the
mean) is the whole trick — a spike cannot drag its own baseline, so the bucket
that matters stays measured against the quiet months preceding it.

Everything here computes on the **native rollup unit** Steam served, never a
hardcoded month: Steam sizes buckets by a game's age, and a detector assuming
months would silently mis-span every weekly-served game.

Two guards keep the output honest rather than merely plentiful. A bucket needs
a full trailing window before it can flag, so a game's launch spike — the
first bucket, with nothing before it — is never an "episode": it is the game
starting, which the timeline already shows. And a bucket must clear an
absolute volume floor, because a ratio over a near-zero baseline is arithmetic
noise: three reviews after a month of one is a 3× spike and means nothing.

What the caller may say about a flagged span is ruled elsewhere and matters
more than this code: markers render observations only — span, magnitude,
review count, and overlap with a Valve-marked window stated as fact — with no
causal noun anywhere. "Review activity spike," never "backlash." The
detection is statistical, the cause is unknown, and the chat milestone is
where "what happened here?" gets asked with receipts.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from steamlens.contracts import HistogramSnapshot, RollupUnit

DEFAULT_K: Final = 4.0
"""The spike multiple a bucket must clear against its trailing median.

Set by the offline calibration pass over the corpus and long-tail histograms
(``studies/detect_corpus``), not guessed — the provenance rides in that
module's capture, and moving this number means re-running it."""

DEFAULT_WINDOW: Final = 6
"""How many preceding buckets the trailing median is taken over.

Long enough that a single quiet stretch cannot halve the baseline, short
enough that a years-old lull does not make an ordinary month look explosive."""

DEFAULT_MIN_VOLUME: Final = 30
"""The absolute floor a bucket must clear to flag at all.

A ratio over a near-zero baseline is noise wearing a large number: without
this, every thinly-reviewed game's ordinary week reads as an episode."""


@dataclass(frozen=True, slots=True)
class Episode:
    """One detected span of unusual review volume — an observation, not a story.

    ``start`` is the opening instant of the first flagged bucket and ``end``
    the opening instant of the bucket *after* the last flagged one, so the
    span is half-open and covers the flagged buckets exactly. ``buckets`` is
    how many merged, ``reviews`` their total volume, and ``peak_multiple`` the
    largest ratio-to-baseline inside the span — the magnitude a marker
    displays. No cause, no label, no adjective: naming why this happened is
    precisely what the detector cannot know.
    """

    start: datetime
    end: datetime
    buckets: int
    reviews: int
    peak_multiple: float


def detect_episodes(
    histogram: HistogramSnapshot,
    *,
    k: float = DEFAULT_K,
    window: int = DEFAULT_WINDOW,
    min_volume: int = DEFAULT_MIN_VOLUME,
) -> tuple[Episode, ...]:
    """Flag volume spikes in ``histogram``'s rollup series and merge adjacent ones.

    A bucket at index ``i`` flags when it has a full ``window`` of preceding
    buckets, its volume is at least ``min_volume``, and its volume exceeds
    ``k`` times the median of those preceding buckets. Consecutive flagged
    buckets merge into one episode. Returns episodes in chronological order;
    an empty tuple is the common and correct answer for a game with no unusual
    activity.

    Raises ``ValueError`` on a non-positive ``k`` or ``window`` — both would
    turn the detector into a flag-everything machine rather than failing
    visibly.

    >>> from steamlens.contracts import HistogramBucket, RollupUnit
    >>> from datetime import UTC, datetime
    >>> quiet = [
    ...     HistogramBucket(datetime(2025, m, 1, tzinfo=UTC), 50, 10) for m in range(1, 7)
    ... ]
    >>> spike = HistogramBucket(datetime(2025, 7, 1, tzinfo=UTC), 900, 300)
    >>> snapshot = HistogramSnapshot(
    ...     app_id=1, rollup_unit=RollupUnit.MONTH,
    ...     rollups=tuple([*quiet, spike]), recent_daily=(), past_events=(),
    ...     fetched_at=datetime(2025, 8, 1, tzinfo=UTC),
    ... )
    >>> episode = detect_episodes(snapshot)[0]
    >>> episode.buckets, episode.reviews, round(episode.peak_multiple, 1)
    (1, 1200, 20.0)
    """
    if k <= 0:
        raise ValueError(f"k must be positive, got {k}")
    if window <= 0:
        raise ValueError(f"window must be positive, got {window}")

    volumes = [
        bucket.recommendations_up + bucket.recommendations_down
        for bucket in histogram.rollups
    ]
    multiples: dict[int, float] = {}
    for index in range(window, len(volumes)):
        volume = volumes[index]
        if volume < min_volume:
            continue
        baseline = statistics.median(volumes[index - window : index])
        if baseline <= 0 or volume <= k * baseline:
            continue
        multiples[index] = volume / baseline

    return tuple(
        _episode(histogram, run, volumes, multiples)
        for run in _consecutive_runs(sorted(multiples))
    )


def _consecutive_runs(indices: list[int]) -> list[list[int]]:
    """Group sorted indices into maximal consecutive runs — the merge step.

    >>> _consecutive_runs([2, 3, 7])
    [[2, 3], [7]]
    """
    runs: list[list[int]] = []
    for index in indices:
        if runs and index == runs[-1][-1] + 1:
            runs[-1].append(index)
        else:
            runs.append([index])
    return runs


def _episode(
    histogram: HistogramSnapshot,
    run: list[int],
    volumes: list[int],
    multiples: dict[int, float],
) -> Episode:
    """One merged run of flagged buckets as an episode span."""
    first, last = run[0], run[-1]
    return Episode(
        start=histogram.rollups[first].start,
        end=_bucket_end(histogram, last),
        buckets=len(run),
        reviews=sum(volumes[index] for index in run),
        peak_multiple=max(multiples[index] for index in run),
    )


def _bucket_end(histogram: HistogramSnapshot, index: int) -> datetime:
    """The half-open end of the bucket at ``index`` — the next bucket's start.

    The final bucket has no successor, so its width is taken from the series
    itself (the previous gap) rather than assumed from the rollup unit; a
    one-bucket series falls back to the unit's nominal width, the only place
    that assumption is unavoidable.
    """
    rollups = histogram.rollups
    if index + 1 < len(rollups):
        return rollups[index + 1].start
    if len(rollups) >= 2:
        return rollups[index].start + (rollups[-1].start - rollups[-2].start)
    nominal = 7 if histogram.rollup_unit is RollupUnit.WEEK else 30
    return rollups[index].start + timedelta(days=nominal)


def overlaps_marked_window(episode: Episode, histogram: HistogramSnapshot) -> bool:
    """Whether ``episode`` overlaps any Valve-marked anomalous window.

    Steam marks windows of off-topic review activity itself; an overlap is a
    *fact about Steam's own flagging* that a marker may state plainly, and it
    is the closest thing to external corroboration this detector has. Absence
    of overlap says nothing — most real events are never Valve-marked.
    """
    return any(
        episode.start < event.end and episode.end > event.start
        for event in histogram.past_events
    )
