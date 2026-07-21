"""Extraction+eval (M1) entry probe, part two: does a plain default cursor walk
blank Valve-marked off-topic windows?

The corpus off-topic probe found zero corpus reviews inside marked windows — but
only because no marked window overlaps any game's corpus coverage, so the corpus
can't testify about the mechanism. The smoke tests proved the default *windowed*
listing blanks marked windows; the prior pipeline's *plain* default walk (no date
params, no `filter_offtopic_activity` — the shape the corpus was fetched in) was
never tested against one.

Method: Europa Universalis IV carries the most recent marked window among the five
flagged corpus games (Feb–Mar 2025), close enough to reach by walking the plain
default listing newest→oldest until safely past the window's start. Count the
walked reviews landing inside the window, then compare against the same window's
windowed-default and windowed-unfiltered totals (`query_summary.total_reviews`).
Blanking would read: plain-walk in-window ≈ windowed default ≈ 0 while the
unfiltered total holds the truth; no blanking reads: plain-walk ≈ unfiltered.

Budget: ≤120 walk pages at ~1.2 s spacing stays inside the ~200-req/5-min budget.
Probe-grade: sequential, stdout-narrated.

Run: python probes/default_walk_blanking_probe.py
"""

import json
import time
from datetime import UTC, datetime
from pathlib import Path

import requests

CAPTURES = Path(__file__).parent / "captures"
APPID = 236850  # Europa Universalis IV
MAX_PAGES = 120
SLEEP_S = 1.2


def ts(v) -> str:
    return datetime.fromtimestamp(int(v), tz=UTC).strftime("%Y-%m-%d")


def marked_window() -> tuple[int, int]:
    resp = requests.get(
        f"https://store.steampowered.com/appreviewhistogram/{APPID}",
        params={"l": "english"}, timeout=30)
    resp.raise_for_status()
    events = resp.json().get("past_events", [])
    if not events:
        raise SystemExit("no past_events on the histogram — nothing to probe")
    return int(events[0]["start_date"]), int(events[0]["end_date"])


def windowed_fetch(name: str, ws: int, we: int, extra_params: dict) -> dict:
    resp = requests.get(
        f"https://store.steampowered.com/appreviews/{APPID}",
        params={
            "json": 1, "filter": "recent", "language": "all",
            "purchase_type": "all", "num_per_page": 100,
            "start_date": ws, "end_date": we, "date_range_type": "include",
            **extra_params,
        }, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    (CAPTURES / f"defaultwalk_windowed_{name}_{APPID}.json").write_text(
        json.dumps(data, indent=2), encoding="utf-8")
    return data


def plain_default_walk(ws: int, we: int) -> dict:
    """Walk the plain default listing (the prior pipeline's exact request shape,
    at 100/page) newest→oldest until a page reaches past the window start;
    short pages do NOT stop the walk — that was the prior fetcher's quirk."""
    cursor = "*"
    walked = {"pages": 0, "reviews_seen": 0, "in_window": 0,
              "short_pages": 0, "oldest_reached": None, "reached_window_start": False}
    for page in range(1, MAX_PAGES + 1):
        resp = requests.get(
            f"https://store.steampowered.com/appreviews/{APPID}",
            params={
                "json": 1, "filter": "recent", "language": "all",
                "purchase_type": "all", "num_per_page": 100, "cursor": cursor,
            }, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        reviews = data.get("reviews", [])
        cursor = data.get("cursor", "")
        stamps = [int(r["timestamp_created"]) for r in reviews]
        walked["pages"] = page
        walked["reviews_seen"] += len(reviews)
        walked["in_window"] += sum(ws <= t <= we for t in stamps)
        walked["short_pages"] += len(reviews) < 100
        if stamps:
            walked["oldest_reached"] = min(stamps)
        if page % 10 == 0 or (stamps and min(stamps) < ws):
            print(f"  page {page:>3}: seen {walked['reviews_seen']}, "
                  f"in-window {walked['in_window']}, oldest "
                  f"{ts(walked['oldest_reached']) if walked['oldest_reached'] else '?'}")
        if not reviews or not cursor:
            print(f"  walk ended by Steam at page {page} "
                  f"({'empty page' if not reviews else 'no cursor'})")
            break
        if min(stamps) < ws:
            walked["reached_window_start"] = True
            break
        time.sleep(SLEEP_S)
    return walked


def main() -> None:
    CAPTURES.mkdir(exist_ok=True)
    ws, we = marked_window()
    print(f"EUIV ({APPID}) marked window: {ts(ws)}..{ts(we)}")
    time.sleep(SLEEP_S)

    windowed_default = windowed_fetch("default", ws, we, {})
    time.sleep(SLEEP_S)
    windowed_unfiltered = windowed_fetch(
        "unfiltered", ws, we, {"filter_offtopic_activity": 0})
    default_summary = windowed_default.get("query_summary", {})
    unfiltered_summary = windowed_unfiltered.get("query_summary", {})
    default_total = default_summary.get("total_reviews")
    unfiltered_total = unfiltered_summary.get("total_reviews")
    print(f"windowed totals (query_summary.total_reviews): "
          f"default {default_total}, unfiltered {unfiltered_total} "
          f"({unfiltered_summary.get('total_positive')} up / "
          f"{unfiltered_summary.get('total_negative')} down)")
    time.sleep(SLEEP_S)

    print(f"\nplain default walk (no date params, no off-topic flag), "
          f"max {MAX_PAGES} pages:")
    walked = plain_default_walk(ws, we)

    print("\n--- verdict material ---")
    print(f"plain-walk reviews inside the marked window: {walked['in_window']}")
    print(f"windowed default total: {default_total} · "
          f"windowed unfiltered total: {unfiltered_total}")
    print(f"walk reached past window start: {walked['reached_window_start']} "
          f"(oldest reached {ts(walked['oldest_reached'])}, "
          f"{walked['pages']} pages, {walked['short_pages']} short)")

    out = CAPTURES / f"defaultwalk_summary_{APPID}.json"
    out.write_text(json.dumps({
        "probe_date": datetime.now(tz=UTC).strftime("%Y-%m-%d"),
        "appid": APPID,
        "window": {"start": ws, "end": we},
        "windowed_default_query_summary": default_summary,
        "windowed_unfiltered_query_summary": unfiltered_summary,
        "plain_default_walk": walked,
    }, indent=2), encoding="utf-8")
    print(f"\nSummary capture: {out}")


if __name__ == "__main__":
    main()
