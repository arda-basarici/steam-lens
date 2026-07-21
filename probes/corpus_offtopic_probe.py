"""Extraction+eval (M1) entry probe: is the 298k corpus bomb-blanked?

The corpus the extraction milestone builds on was fetched by the prior steam-reviews
pipeline as a plain default cursor walk — no `filter_offtopic_activity`, no date
params (verified in that repo's fetcher). The smoke tests later showed the default
*windowed* listing blanks entire Valve-marked off-topic windows, legitimate reviews
included. Unknown: whether the plain default walk blanks the same windows — i.e.
whether the corpus has holes exactly where events live.

Method: refetch `appreviewhistogram` (and its `past_events`) for all 50 corpus
games; for every marked window, compare three counts that agree only if nothing was
blanked: corpus reviews inside the window, corpus reviews in equal-length flanking
windows, and the histogram's own in-window volume (histogram buckets include bomb
reviews unconditionally, per the smoke tests; bucket granularity makes that count an
over-estimate at the window edges). Windows outside a game's corpus coverage — the
capped recent-first walk reaches back only so far — are reported but can't testify.

Reads the frozen corpus from the sibling steam-reviews repo (per-game review JSONL +
fetch_manifest.json). Full raw histograms are captured only for games carrying
past_events; a distilled per-game summary covers all 50. Probe-grade: sequential,
stdout-narrated.

Run: python probes/corpus_offtopic_probe.py
"""

import json
import time
from bisect import bisect_left, bisect_right
from datetime import UTC, datetime
from pathlib import Path

import requests

CAPTURES = Path(__file__).parent / "captures"
CORPUS_DATA = Path(__file__).resolve().parents[2] / "steam-reviews" / "data"
SLEEP_S = 1.5


def ts(v) -> str:
    return datetime.fromtimestamp(int(v), tz=UTC).strftime("%Y-%m-%d")


def load_corpus_timestamps(app_id: str) -> list[int]:
    """All of one game's corpus review creation times, sorted ascending."""
    path = CORPUS_DATA / "raw" / "reviews" / f"{app_id}_reviews.jsonl"
    with path.open(encoding="utf-8") as f:
        return sorted(int(json.loads(line)["timestamp_created"]) for line in f)


def fetch_histogram(app_id: str) -> dict:
    resp = requests.get(
        f"https://store.steampowered.com/appreviewhistogram/{app_id}",
        params={"l": "english"}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def bucket_spans(rollups: list[dict]) -> list[tuple[int, int, dict]]:
    """(start, end, bucket) per rollup bucket; a bucket ends where the next begins,
    the last one reuses the previous span (there is no next to read it from)."""
    dates = [int(b["date"]) for b in rollups]
    spans = []
    for i, bucket in enumerate(rollups):
        if i + 1 < len(dates):
            end = dates[i + 1]
        else:
            end = dates[i] + (dates[i] - dates[i - 1] if i else 31 * 86400)
        spans.append((dates[i], end, bucket))
    return spans


def count_between(stamps: list[int], start: int, end: int) -> int:
    return bisect_right(stamps, end) - bisect_left(stamps, start)


def window_report(stamps: list[int], rollups: list[dict],
                  ws: int, we: int) -> dict:
    """The three counts that agree only if the window wasn't blanked, plus the
    coverage flags needed to read them (a flank before corpus coverage is
    legitimately zero — coverage, not blanking)."""
    length = we - ws
    cov_min, cov_max = stamps[0], stamps[-1]
    hist = [b for s, e, b in bucket_spans(rollups) if s < we and e > ws]
    return {
        "window": {"start": ws, "end": we},
        "in_coverage": we >= cov_min and ws <= cov_max,
        "partially_before_coverage": ws < cov_min <= we,
        "corpus_in_window": count_between(stamps, ws, we),
        "corpus_flank_before": count_between(stamps, ws - length, ws - 1),
        "corpus_flank_after": count_between(stamps, we + 1, we + length),
        "histogram_in_window_up": sum(b["recommendations_up"] for b in hist),
        "histogram_in_window_down": sum(b["recommendations_down"] for b in hist),
        "histogram_buckets_overlapping": len(hist),
    }


def main() -> None:
    CAPTURES.mkdir(exist_ok=True)
    manifest = json.loads(
        (CORPUS_DATA / "raw" / "fetch_manifest.json").read_text(encoding="utf-8"))
    games = sorted(manifest.items(), key=lambda kv: int(kv[0]))
    print(f"{len(games)} corpus games from the frozen steam-reviews fetch manifest\n")

    summary = []
    total_reviews = 0
    total_in_marked = 0
    for app_id, record in games:
        stamps = load_corpus_timestamps(app_id)
        total_reviews += len(stamps)
        hist = fetch_histogram(app_id)
        time.sleep(SLEEP_S)
        events = hist.get("past_events", [])
        results = hist.get("results", {})
        entry = {
            "app_id": int(app_id),
            "name": record.get("name"),
            "corpus_reviews": len(stamps),
            "corpus_range": {"oldest": stamps[0], "newest": stamps[-1]},
            "rollup_type": results.get("rollup_type"),
            "past_events": events,
            "windows": [],
        }
        line = (f"{app_id:>8}  {(record.get('name') or '?')[:36]:<36} "
                f"{len(stamps):>6} reviews  {ts(stamps[0])}..{ts(stamps[-1])}")
        if not events:
            print(f"{line}  -")
        else:
            (CAPTURES / f"corpus_hist_{app_id}.json").write_text(
                json.dumps(hist, indent=2), encoding="utf-8")
            print(f"{line}  {len(events)} marked window(s)")
            for event in events:
                report = window_report(stamps, results.get("rollups", []),
                                       int(event["start_date"]), int(event["end_date"]))
                report["event_type"] = event.get("type")
                entry["windows"].append(report)
                total_in_marked += report["corpus_in_window"]
                w = report["window"]
                coverage = ("in coverage" if report["in_coverage"]
                            else "OUTSIDE corpus coverage")
                print(f"          window {ts(w['start'])}..{ts(w['end'])} ({coverage}): "
                      f"corpus in-window {report['corpus_in_window']}, "
                      f"flanks {report['corpus_flank_before']}/"
                      f"{report['corpus_flank_after']}, "
                      f"histogram {report['histogram_in_window_up']}+"
                      f"{report['histogram_in_window_down']} over "
                      f"{report['histogram_buckets_overlapping']} bucket(s)")
        summary.append(entry)

    flagged = [e for e in summary if e["past_events"]]
    covered = [w for e in flagged for w in e["windows"] if w["in_coverage"]]
    print("\n--- aggregate ---")
    print(f"corpus reviews counted: {total_reviews}")
    print(f"games with past_events: {len(flagged)}/{len(games)} "
          f"({', '.join(str(e['app_id']) for e in flagged) or 'none'})")
    print(f"marked windows: {sum(len(e['windows']) for e in flagged)} total, "
          f"{len(covered)} overlapping corpus coverage")
    print(f"corpus reviews inside marked windows: {total_in_marked} "
          f"({100 * total_in_marked / total_reviews:.3f}% of corpus)")

    out = CAPTURES / "corpus_offtopic_summary.json"
    out.write_text(json.dumps({
        "probe_date": datetime.now(tz=UTC).strftime("%Y-%m-%d"),
        "corpus_source": "steam-reviews (frozen sibling repo), "
                         "full fetch of 2026-06-12, per its fetch_manifest.json",
        "corpus_reviews_counted": total_reviews,
        "games": summary,
    }, indent=2), encoding="utf-8")
    print(f"\nSummary capture: {out}")
    print("Raw histograms for flagged games: captures/corpus_hist_<appid>.json")


if __name__ == "__main__":
    main()
