"""The episode detector's offline calibration pass — pick k by looking, not guessing.

The detector's threshold is the one number in it that cannot be derived, so
the deployment design ruled it picked from data and shipped as config carrying
its provenance. This module is that pass: it sweeps ``k`` over every histogram
the project already holds and reports what each value would actually mark, so
the choice is made against real games rather than a plausible-sounding number.

**What the evidence base is, and what it is not.** The pass reads two offline
sources and rules on only one of them, which is the finding it exists to
report.

The **corpus histograms are excluded**, and the exclusion is permanent. The
frozen corpus was built by fetching each game's *recent* reviews — a
newest-first prefix per game, filled to a per-game cap — so a rebuilt
histogram is a recency window, not a lifetime history: a median of five
monthly buckets, 29 of 49 games at six or fewer, and every game's series
ending in the fetch month. That is fewer buckets than the trailing window a
baseline needs, and the bias runs the wrong way besides — span is inversely
related to review velocity, so the only corpus games long enough to flag are
the slow ones the volume floor should be suppressing. A threshold picked
there would describe the corpus's fetch shape, not how games behave. The pass
still loads them, because reporting *why* a planned input was dropped is
worth more than silently narrowing the base.

The ruling therefore rests on the **live snapshots** the long-tail discovery
and fresh-buy runs captured: all-language volume at whatever rollup unit
Steam served, which is the production instrument's own shape. The design's
phrasing also assumed labeled "known events" to separate from noise; on disk
there are three Valve-marked windows, one a degenerate multi-year span and
two sub-bucket fortnights inside monthly series. Three is not a calibration
set, and at that granularity it cannot be one — so this pass reports the
*marking rate* (what share of games and buckets each k would mark) and treats
the marked windows as an observation, never as validation.

Run: ``python -m steamlens.studies.detect_corpus --corpus-dir <path>``
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, cast

from steamlens.contracts import (
    HistogramBucket,
    HistogramSnapshot,
    ReviewEvent,
    RollupUnit,
)
from steamlens.core.detect import (
    DEFAULT_MIN_VOLUME,
    DEFAULT_WINDOW,
    detect_episodes,
    overlaps_marked_window,
)
from steamlens.corpus import corpus_review_files, read_reviews_file
from steamlens.studies.sample_corpus import corpus_histogram

K_GRID: Final = (2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0)
"""The sweep's thresholds — dense where the decision lives (2–4), thinner past
it, since anything above ~6 marks so little that the feature stops existing."""

# The snapshot directories the discovery and fresh-buy runs wrote. Both raw
# shapes are read: the discovery run stored Steam's wire payload under a
# ``payload`` key, the fresh-buy run stored an already-parsed record.
SNAPSHOT_DIRS: Final = (
    ("longtail", Path("data/longtail/longtail-20260802T232206Z-9bf61718/histograms")),
    (
        "live-corpus",
        Path("data/longtail/longtail-20260802T232206Z-9bf61718/histograms_corpus"),
    ),
    ("freshbuy", Path("data/freshbuy/freshbuy-20260803T110347Z-bccdb631/histograms")),
)
"""Each snapshot directory with the population it sampled, kept separate on
purpose: long-tail games are small and young, the corpus-check and fresh-buy
picks are established games, and blending them would average away exactly the
game-shape dependence the calibration exists to see."""


@dataclass(frozen=True, slots=True)
class SourceHistogram:
    """One histogram to calibrate against, tagged with where it came from.

    ``source`` separates the corpus-built sample from live snapshots in every
    report line, because their approximations differ and a blended number
    would hide that.
    """

    source: str
    histogram: HistogramSnapshot


@dataclass(frozen=True, slots=True)
class ThresholdReading:
    """What one ``k`` would mark across one source's histograms.

    ``games_marked`` over ``games`` is the rate that decides the feature's
    character — a k marking nearly every game says "spike" means nothing,
    while one marking almost none makes the timeline's markers vanish.
    ``bucket_share`` is the same question at bucket grain, and
    ``marked_windows_caught`` counts the Valve-flagged windows an episode
    overlapped (out of ``marked_windows_available``).
    """

    k: float
    source: str
    games: int
    games_marked: int
    episodes: int
    bucket_share: float
    median_peak_multiple: float
    marked_windows_available: int
    marked_windows_caught: int


def load_corpus_histograms(corpus_dir: Path) -> tuple[SourceHistogram, ...]:
    """Rebuild each corpus game's histogram from its frozen reviews.

    Uses the study's own ``corpus_histogram`` builder — the same one the
    sampling study planned windows against — so the calibration reads the
    histograms the rest of the project already reasons about, not a second
    construction of them.
    """
    built: list[SourceHistogram] = []
    for path in corpus_review_files(corpus_dir):
        result = read_reviews_file(path)
        if not result.reviews:
            continue
        built.append(
            SourceHistogram(source="corpus", histogram=corpus_histogram(result.reviews))
        )
    return tuple(built)


def load_snapshots(
    dirs: Sequence[tuple[str, Path]] = SNAPSHOT_DIRS,
) -> tuple[SourceHistogram, ...]:
    """Read every persisted live histogram snapshot, both stored shapes.

    Missing directories are skipped rather than raised on: the snapshots are
    run artifacts, and a calibration on a clone without them should still run
    over the corpus and say so.
    """
    snapshots: list[SourceHistogram] = []
    for source, directory in dirs:
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.json")):
            snapshots.append(
                SourceHistogram(
                    source=source,
                    histogram=_snapshot_from_json(
                        json.loads(path.read_text(encoding="utf-8"))
                    ),
                )
            )
    return tuple(snapshots)


def _snapshot_from_json(body: dict[str, object]) -> HistogramSnapshot:
    """One stored snapshot as a typed record, tolerating both persisted shapes."""
    app_id = int(str(body["app_id"]))
    fetched_at = datetime.fromisoformat(str(body["fetched_at"]))
    if "payload" in body:
        payload: dict[str, object] = _as_dict(body["payload"])
        results = _as_dict(payload["results"])
        unit = (
            RollupUnit.WEEK
            if str(results.get("rollup_type")) == "week"
            else RollupUnit.MONTH
        )
        rollups = _wire_buckets(results.get("rollups"))
        events = _wire_events(results.get("past_events"))
    else:
        unit = RollupUnit(str(body["rollup_unit"]))
        rollups = _record_buckets(body.get("rollups"))
        events = _record_events(body.get("past_events"))
    return HistogramSnapshot(
        app_id=app_id,
        rollup_unit=unit,
        rollups=rollups,
        recent_daily=(),
        past_events=events,
        fetched_at=fetched_at,
    )


def _as_dict(value: object) -> dict[str, object]:
    """One decoded JSON value as an object, or a loud failure naming what it was."""
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object, got {type(value).__name__}")
    return cast(dict[str, object], value)


def _rows(value: object) -> list[dict[str, object]]:
    """A JSON array of objects as typed rows; anything else reads as empty.

    An absent series is legitimate (a snapshot with no marked windows omits
    the key), so absence is empty rather than an error — while a present but
    non-object row still fails loud through ``_as_dict``.
    """
    if not isinstance(value, list):
        return []
    items = cast(list[object], value)
    return [_as_dict(item) for item in items]


def _wire_buckets(value: object) -> tuple[HistogramBucket, ...]:
    return tuple(
        HistogramBucket(
            start=datetime.fromtimestamp(int(str(row["date"])), tz=UTC),
            recommendations_up=int(str(row["recommendations_up"])),
            recommendations_down=int(str(row["recommendations_down"])),
        )
        for row in _rows(value)
    )


def _wire_events(value: object) -> tuple[ReviewEvent, ...]:
    return tuple(
        ReviewEvent(
            event_type=int(str(row.get("event_type", 0))),
            start=datetime.fromtimestamp(int(str(row["start_date"])), tz=UTC),
            end=datetime.fromtimestamp(int(str(row["end_date"])), tz=UTC),
        )
        for row in _rows(value)
    )


def _record_buckets(value: object) -> tuple[HistogramBucket, ...]:
    """The fresh-buy run's compact field names (``up``/``down``), read as written."""
    return tuple(
        HistogramBucket(
            start=datetime.fromisoformat(str(row["start"])),
            recommendations_up=int(str(row["up"])),
            recommendations_down=int(str(row["down"])),
        )
        for row in _rows(value)
    )


def _record_events(value: object) -> tuple[ReviewEvent, ...]:
    return tuple(
        ReviewEvent(
            event_type=int(str(row.get("type", 0))),
            start=datetime.fromisoformat(str(row["start"])),
            end=datetime.fromisoformat(str(row["end"])),
        )
        for row in _rows(value)
    )


def read_threshold(
    histograms: Sequence[SourceHistogram],
    k: float,
    *,
    source: str,
    window: int = DEFAULT_WINDOW,
    min_volume: int = DEFAULT_MIN_VOLUME,
) -> ThresholdReading:
    """What ``k`` marks across one source's histograms — the sweep's unit of evidence."""
    subset = [item for item in histograms if item.source == source]
    episodes_total = 0
    games_marked = 0
    flagged_buckets = 0
    total_buckets = 0
    peaks: list[float] = []
    marked_available = 0
    marked_caught = 0
    for item in subset:
        episodes = detect_episodes(
            item.histogram, k=k, window=window, min_volume=min_volume
        )
        total_buckets += len(item.histogram.rollups)
        flagged_buckets += sum(episode.buckets for episode in episodes)
        episodes_total += len(episodes)
        peaks.extend(episode.peak_multiple for episode in episodes)
        if episodes:
            games_marked += 1
        for event in item.histogram.past_events:
            marked_available += 1
            if any(
                overlaps_marked_window(episode, item.histogram)
                and episode.start < event.end
                and episode.end > event.start
                for episode in episodes
            ):
                marked_caught += 1
    peaks.sort()
    median_peak = peaks[len(peaks) // 2] if peaks else 0.0
    return ThresholdReading(
        k=k,
        source=source,
        games=len(subset),
        games_marked=games_marked,
        episodes=episodes_total,
        bucket_share=flagged_buckets / total_buckets if total_buckets else 0.0,
        median_peak_multiple=median_peak,
        marked_windows_available=marked_available,
        marked_windows_caught=marked_caught,
    )


def render_table(readings: Sequence[ThresholdReading]) -> str:
    """The sweep as the table a person reads to pick k."""
    header = (
        f"{'k':>5} {'source':<7} {'games':>6} {'marked':>7} {'rate':>6} "
        f"{'episodes':>9} {'bucket%':>8} {'med×':>6} {'valve':>7}"
    )
    lines = [header, "-" * len(header)]
    for reading in readings:
        rate = reading.games_marked / reading.games if reading.games else 0.0
        valve = (
            f"{reading.marked_windows_caught}/{reading.marked_windows_available}"
            if reading.marked_windows_available
            else "—"
        )
        lines.append(
            f"{reading.k:>5.1f} {reading.source:<7} {reading.games:>6} "
            f"{reading.games_marked:>7} {rate:>6.0%} {reading.episodes:>9} "
            f"{reading.bucket_share:>7.1%} {reading.median_peak_multiple:>6.1f} "
            f"{valve:>7}"
        )
    return "\n".join(lines)


def main() -> None:
    """CLI: sweep the grid over both sources, print the table, write the capture."""
    parser = argparse.ArgumentParser(description="Calibrate the episode detector's k.")
    parser.add_argument("--corpus-dir", type=Path, default=None)
    parser.add_argument("--window", type=int, default=DEFAULT_WINDOW)
    parser.add_argument("--min-volume", type=int, default=DEFAULT_MIN_VOLUME)
    parser.add_argument(
        "--out", type=Path, default=Path("probes/captures/detect_calibration.json")
    )
    args = parser.parse_args()

    histograms: list[SourceHistogram] = list(load_snapshots())
    if args.corpus_dir is not None:
        histograms.extend(load_corpus_histograms(args.corpus_dir))
    sources = sorted({item.source for item in histograms})
    print(
        f"histograms: {len(histograms)} "
        + ", ".join(
            f"{source} {sum(1 for i in histograms if i.source == source)}"
            for source in sources
        )
        + f"   (window={args.window}, min_volume={args.min_volume})"
    )
    readings = [
        read_threshold(
            histograms, k, source=source, window=args.window, min_volume=args.min_volume
        )
        for k in K_GRID
        for source in sources
    ]
    print(render_table(readings))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(
            {
                "window": args.window,
                "min_volume": args.min_volume,
                "k_grid": list(K_GRID),
                "readings": [
                    {
                        "k": r.k,
                        "source": r.source,
                        "games": r.games,
                        "games_marked": r.games_marked,
                        "episodes": r.episodes,
                        "bucket_share": r.bucket_share,
                        "median_peak_multiple": r.median_peak_multiple,
                        "marked_windows_available": r.marked_windows_available,
                        "marked_windows_caught": r.marked_windows_caught,
                    }
                    for r in readings
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\ncapture: {args.out}")


if __name__ == "__main__":
    main()
