"""Sampling-study (M2) step-8 gate: verify the bomb picks at wire level.

The blank/restore mechanism is settled (findings 3–5: default listings blank
Valve-marked windows, `filter_offtopic_activity=0` restores them, verified
locally and from a datacenter). What no probe has checked is the *picks*: web
research nominated Borderlands 2, Book of Demons, and The Witcher 3 as carriers
of off-topic marks, and nomination is not evidence. Per pick, four questions:

- does `past_events` exist on the wire, and what window dates does it carry?
- does the default windowed listing blank this game's window while the
  unfiltered flag restores volume consistent with the histogram's in-window
  buckets (the mechanism confirmed on *this* game, not a stand-in)?
- how large is the in-window **English** pool — the only labelable material,
  sizing the mixing experiment's ~1–2k-review appetite? Read as a windowed
  totals-only query (`num_per_page=0` returns `query_summary` alone); the
  histogram cross-check guards against the undocumented window params being
  ignored by the summary, which would surface as a whole-game-sized count.
- does a sample page's every timestamp fall inside the window?

Probe-grade: sequential, stdout-narrated, raw requests mirroring the production
seam's exact param base (the seam itself stays out — a probe must be able to
vary the params the seam deliberately hard-codes). Captures: raw histogram and
sample page per game.

Run: python probes/bomb_pick_probe.py
"""

import json
import time
from datetime import UTC, datetime
from pathlib import Path

import requests

CAPTURES = Path(__file__).parent / "captures"
SLEEP_S = 1.5

# The step-8 bomb picks (DESIGN, "The fresh-buy session (step 8)", 2026-08-03).
PICKS = {
    49520: "Borderlands 2",
    449960: "Book of Demons",
    292030: "The Witcher 3: Wild Hunt",
}

# Mirrors the production seam's _UNFILTERED_BASE (steam_client.client) — the
# bias-avoiding trio plus the off-topic restore flag.
UNFILTERED_BASE = {
    "json": 1,
    "language": "all",
    "purchase_type": "all",
    "review_type": "all",
    "filter_offtopic_activity": 0,
}


def ts(epoch: int) -> str:
    return datetime.fromtimestamp(int(epoch), tz=UTC).strftime("%Y-%m-%d")


def get_json(url: str, params: dict) -> dict:
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    time.sleep(SLEEP_S)
    return resp.json()


def fetch_histogram(app_id: int) -> dict:
    return get_json(
        f"https://store.steampowered.com/appreviewhistogram/{app_id}",
        {"l": "english"},
    )


def windowed_totals(app_id: int, start: int, end: int,
                    language: str, unfiltered: bool) -> dict:
    """One totals-only windowed query; `unfiltered=False` drops the off-topic
    flag entirely — the default behavior whose blanking is under test."""
    params = {**UNFILTERED_BASE, "language": language, "num_per_page": 0,
              "filter": "recent", "start_date": start, "end_date": end,
              "date_range_type": "include"}
    if not unfiltered:
        del params["filter_offtopic_activity"]
    payload = get_json(f"https://store.steampowered.com/appreviews/{app_id}", params)
    return payload.get("query_summary", {})


def windowed_page(app_id: int, start: int, end: int) -> dict:
    params = {**UNFILTERED_BASE, "num_per_page": 100, "filter": "recent",
              "start_date": start, "end_date": end, "date_range_type": "include"}
    return get_json(f"https://store.steampowered.com/appreviews/{app_id}", params)


def in_window_bucket_volume(rollups: list[dict], start: int, end: int) -> int:
    """All-language in-window volume from histogram buckets (mark-agnostic per
    finding 3); bucket granularity makes this an edge-overestimate."""
    return sum(
        int(b["recommendations_up"]) + int(b["recommendations_down"])
        for b in rollups
        if start <= int(b["date"]) <= end
    )


def probe_game(app_id: int, name: str) -> dict:
    print(f"\n=== {name} ({app_id}) ===")
    hist = fetch_histogram(app_id)
    (CAPTURES / f"bombpick_hist_{app_id}.json").write_text(
        json.dumps(hist, indent=1), encoding="utf-8")
    events = hist.get("past_events", [])
    if not events:
        print("no past_events on the wire — the nominated mark DOES NOT EXIST")
        return {"app_id": app_id, "name": name, "mark_exists": False}

    rollups = hist.get("results", {}).get("rollups", [])
    event_rows = []
    for event in events:
        start, end = int(event["start_date"]), int(event["end_date"])
        ongoing = end == 0
        if ongoing:
            end = int(time.time())
        hist_volume = in_window_bucket_volume(rollups, start, end)
        default_total = int(
            windowed_totals(app_id, start, end, "all", unfiltered=False)
            .get("total_reviews", -1))
        all_total = int(
            windowed_totals(app_id, start, end, "all", unfiltered=True)
            .get("total_reviews", -1))
        english_total = int(
            windowed_totals(app_id, start, end, "english", unfiltered=True)
            .get("total_reviews", -1))
        print(f"window {ts(start)} -> {ts(end)}{' (ongoing)' if ongoing else ''}"
              f"  type={event.get('type')}")
        print(f"  histogram in-window volume : {hist_volume:>8,}")
        print(f"  windowed totals, default   : {default_total:>8,}"
              "   (blanked => ~0)")
        print(f"  windowed totals, unfiltered: {all_total:>8,}")
        print(f"  windowed totals, English   : {english_total:>8,}"
              "   (the labelable pool)")
        event_rows.append({
            "start": start, "end": end, "ongoing": ongoing,
            "histogram_volume": hist_volume, "default_total": default_total,
            "unfiltered_total": all_total, "english_total": english_total,
        })

    largest = max(event_rows, key=lambda r: r["unfiltered_total"])
    page = windowed_page(app_id, largest["start"], largest["end"])
    (CAPTURES / f"bombpick_page_{app_id}.json").write_text(
        json.dumps(page, indent=1), encoding="utf-8")
    stamps = [int(r["timestamp_created"]) for r in page.get("reviews", [])]
    inside = sum(largest["start"] <= s <= largest["end"] for s in stamps)
    english = sum(r.get("language") == "english" for r in page.get("reviews", []))
    print(f"sample page (largest window): {len(stamps)} reviews, "
          f"{inside} in-window, {english} English")

    return {"app_id": app_id, "name": name, "mark_exists": True,
            "events": event_rows,
            "sample_page": {"reviews": len(stamps), "in_window": inside,
                            "english": english}}


def main() -> None:
    CAPTURES.mkdir(exist_ok=True)
    reports = [probe_game(app_id, name) for app_id, name in PICKS.items()]
    (CAPTURES / "bombpick_summary.json").write_text(
        json.dumps(reports, indent=1), encoding="utf-8")

    print("\n=== step-8 gate summary ===")
    combined_english = 0
    for report in reports:
        if not report["mark_exists"]:
            print(f"{report['name']:<28} NO MARK — replace from alternates")
            continue
        pool = sum(e["english_total"] for e in report["events"]
                   if e["english_total"] > 0)
        combined_english += pool
        windows = ", ".join(
            f"{ts(e['start'])}->{ts(e['end'])}" for e in report["events"])
        print(f"{report['name']:<28} English pool {pool:>7,}   [{windows}]")
    print(f"{'combined labelable pool':<28} {combined_english:>7,} "
          "(mixing appetite: ~1–2k)")


if __name__ == "__main__":
    main()
