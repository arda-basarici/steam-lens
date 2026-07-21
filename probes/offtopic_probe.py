"""Smoke-test probe (M0): what does Steam's off-topic (review-bomb) flag look like?

The store page shades "off-topic review activity" periods, but nothing in the docs
says where that data lives: per-review field? per-window structure? counts only?
The answer defines the review-bomb data contract the design would otherwise guess.

Method: hit both endpoints for Borderlands 2 (49520 — the April 2019 Epic-exclusivity
bomb, the first Valve officially marked) with `filter_offtopic_activity` off/default,
and diff: which keys appear, which counts move, and whether reviews fetched from
inside the bombed window (via the verified undocumented date params) carry any flag.

Raw responses are saved under captures/. Probe-grade: sequential, stdout-narrated.

Run: python probes/offtopic_probe.py
"""

import json
import time
from datetime import UTC, datetime
from pathlib import Path

import requests

CAPTURES = Path(__file__).parent / "captures"
APPID = 49520  # Borderlands 2

# Fallback window (Epic-exclusivity bomb, April 2019) if the histogram carries no
# past_events; when it does, the review fetches use the marked window itself so the
# with/without comparison actually straddles flagged reviews.
FALLBACK_START = int(datetime(2019, 4, 1, tzinfo=UTC).timestamp())
FALLBACK_END = int(datetime(2019, 4, 30, tzinfo=UTC).timestamp())


def fetch_json(name: str, url: str, params: dict) -> dict:
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    (CAPTURES / f"offtopic_{name}.json").write_text(
        json.dumps(data, indent=2), encoding="utf-8")
    return data


def ts(v) -> str:
    try:
        return datetime.fromtimestamp(int(v), tz=UTC).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return repr(v)


def histogram(name: str, extra_params: dict) -> dict:
    return fetch_json(
        f"hist_{name}",
        f"https://store.steampowered.com/appreviewhistogram/{APPID}",
        {"l": "english", **extra_params},
    )


def reviews_in_window(name: str, start: int, end: int, extra_params: dict) -> dict:
    return fetch_json(
        f"reviews_{name}",
        f"https://store.steampowered.com/appreviews/{APPID}",
        {
            "json": 1, "filter": "recent", "language": "all",
            "purchase_type": "all", "num_per_page": 100,
            "start_date": start, "end_date": end,
            "date_range_type": "include",
            **extra_params,
        },
    )


def diff_histograms(base: dict, variant: dict, label: str) -> None:
    print(f"\n--- histogram diff: default vs {label} ---")
    base_keys = set(base.get("results", {}).keys())
    var_keys = set(variant.get("results", {}).keys())
    if base_keys != var_keys:
        print(f"  results keys differ: only-default={base_keys - var_keys}, "
              f"only-variant={var_keys - base_keys}")
    else:
        print(f"  results keys identical: {sorted(base_keys)}")

    base_rollups = {b["date"]: b for b in base["results"].get("rollups", [])}
    var_rollups = {b["date"]: b for b in variant["results"].get("rollups", [])}
    moved = [
        (date, base_rollups[date], var_rollups[date])
        for date in sorted(base_rollups.keys() & var_rollups.keys())
        if base_rollups[date] != var_rollups[date]
    ]
    print(f"  rollup buckets: {len(base_rollups)} vs {len(var_rollups)}, "
          f"{len(moved)} buckets with different counts")
    for date, b, v in moved[:8]:
        print(f"    {ts(date)}: default up/down {b['recommendations_up']}/"
              f"{b['recommendations_down']} -> variant {v['recommendations_up']}/"
              f"{v['recommendations_down']}")
    if len(moved) > 8:
        print(f"    ... and {len(moved) - 8} more differing buckets")


def summarize_reviews(name: str, data: dict) -> None:
    summary = data.get("query_summary", {})
    reviews = data.get("reviews", [])
    print(f"\n--- reviews ({name}) ---")
    print(f"  query_summary: {summary}")
    print(f"  fetched {len(reviews)} reviews")
    if reviews:
        sample = reviews[0]
        print(f"  per-review keys: {sorted(sample.keys())}")
        dates = [r.get("timestamp_created") for r in reviews]
        print(f"  created range: {ts(min(dates))} .. {ts(max(dates))}")


def main() -> None:
    CAPTURES.mkdir(exist_ok=True)

    hist_default = histogram("default", {})
    time.sleep(1.5)
    hist_include = histogram("include_offtopic", {"filter_offtopic_activity": 0})
    time.sleep(1.5)

    print(f"histogram top-level keys: {sorted(hist_default.keys())}")
    print(f"histogram results keys:   {sorted(hist_default['results'].keys())}")

    events = hist_default.get("past_events", [])
    print(f"\npast_events: {events}")
    if events:
        start, end = events[0]["start_date"], events[0]["end_date"]
        print(f"  -> review fetches use the marked window {ts(start)}..{ts(end)}")
    else:
        start, end = FALLBACK_START, FALLBACK_END
        print(f"  -> none found; falling back to {ts(start)}..{ts(end)}")

    diff_histograms(hist_default, hist_include, "filter_offtopic_activity=0")

    reviews_default = reviews_in_window("default", start, end, {})
    time.sleep(1.5)
    reviews_include = reviews_in_window(
        "include_offtopic", start, end, {"filter_offtopic_activity": 0})

    summarize_reviews("default", reviews_default)
    summarize_reviews("filter_offtopic_activity=0", reviews_include)

    default_ids = {r["recommendationid"] for r in reviews_default.get("reviews", [])}
    include_ids = {r["recommendationid"] for r in reviews_include.get("reviews", [])}
    print(f"\nreview-id overlap: {len(default_ids & include_ids)} shared, "
          f"{len(include_ids - default_ids)} only-in-unfiltered, "
          f"{len(default_ids - include_ids)} only-in-default")

    print(f"\nRaw captures in {CAPTURES}/")


if __name__ == "__main__":
    main()
