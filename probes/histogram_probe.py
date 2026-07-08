"""Smoke-test probe (M0): what granularity does the review histogram actually give?

Hits `appreviewhistogram/<appid>` for three game profiles — an old large game, a
recent release, a tiny indie — and reports the bucket structure (rollup type, bucket
count, date span) plus any recent/daily section. The answer bounds what the event
detector can be: monthly buckets mean month-level event localization unless the
recent window or another path gives finer grain.

Raw responses are saved under captures/ so the findings note cites real payloads,
not memory. Probe-grade script: sequential, stdout-narrated, no retries beyond one.

Run: python probes/histogram_probe.py
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

CAPTURES = Path(__file__).parent / "captures"
HISTOGRAM_URL = "https://store.steampowered.com/appreviewhistogram/{appid}"


def fetch_json(url: str, params: dict) -> dict:
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def front_page_appids(category: str) -> list[int]:
    """Deduped appids from a store front-page tab ('new_releases', 'top_sellers')."""
    data = fetch_json(
        "https://store.steampowered.com/api/featuredcategories",
        {"l": "english"},
    )
    items = data.get(category, {}).get("items", [])
    return list(dict.fromkeys(item["id"] for item in items))


def release_age_days(appid: int) -> float | None:
    """Days since release per appdetails, or None if unreleased/unparseable."""
    data = fetch_json(
        "https://store.steampowered.com/api/appdetails",
        {"appids": appid, "l": "english", "filters": "release_date"},
    )
    entry = data.get(str(appid), {})
    release = (entry.get("data") or {}).get("release_date", {})
    if not entry.get("success") or release.get("coming_soon"):
        return None
    for fmt in ("%d %b, %Y", "%b %d, %Y"):
        try:
            released = datetime.strptime(release.get("date", ""), fmt)
            return (datetime.now() - released).days
        except ValueError:
            continue
    return None


def total_reviews(appid: int) -> int:
    data = fetch_json(
        f"https://store.steampowered.com/appreviews/{appid}",
        {"json": 1, "num_per_page": 0, "language": "all", "purchase_type": "all"},
    )
    return data.get("query_summary", {}).get("total_reviews", -1)


def ts(v) -> str:
    try:
        return datetime.fromtimestamp(int(v), tz=timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return repr(v)


def describe_histogram(label: str, appid: int, note: str) -> None:
    print(f"\n=== {label}: appid {appid} — {note} ===")
    data = fetch_json(HISTOGRAM_URL.format(appid=appid), {"l": "english"})

    capture_path = CAPTURES / f"histogram_{label}_{appid}.json"
    capture_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    results = data.get("results", {})
    print(f"  top-level keys: {sorted(data.keys())}")
    print(f"  results keys:   {sorted(results.keys())}")

    for section in ("rollups", "recent"):
        buckets = results.get(section)
        if not buckets:
            print(f"  {section}: MISSING or empty -> {buckets!r}")
            continue
        dates = [b.get("date") for b in buckets]
        gaps = {int(b) - int(a) for a, b in zip(dates, dates[1:])}
        gap_days = sorted(g / 86400 for g in gaps)
        print(f"  {section}: {len(buckets)} buckets, "
              f"{ts(dates[0])} .. {ts(dates[-1])}, "
              f"bucket gaps (days): {gap_days[:5]}{'...' if len(gap_days) > 5 else ''}")
        print(f"    sample bucket: {buckets[len(buckets) // 2]}")

    for key in ("rollup_type", "recent_rollup_type", "start_date", "end_date",
                "weeks", "count_all_reviews", "expand_graph"):
        if key in results:
            val = results[key]
            shown = ts(val) if key.endswith("_date") else val
            print(f"  results.{key} = {shown}")


def resolve_tiny_indie() -> int | None:
    """A new release with under 100 (but >0) reviews, from the new-releases tab."""
    print("Resolving a tiny indie from the new-releases list...")
    for appid in front_page_appids("new_releases"):
        n = total_reviews(appid)
        print(f"  appid {appid}: {n} total reviews")
        if 0 < n < 100:
            return appid
        time.sleep(1)
    return None


def resolve_recent_hit() -> int | None:
    """A top seller released within ~90 days with real review volume.

    New releases are almost all tiny, so the volume-bearing recent game has to
    come from the top-sellers tab filtered by release age.
    """
    print("Resolving a recent high-volume game from the top-sellers list...")
    for appid in front_page_appids("top_sellers"):
        age = release_age_days(appid)
        if age is None or age > 90:
            print(f"  appid {appid}: age {age} days -> skip")
            time.sleep(1)
            continue
        n = total_reviews(appid)
        print(f"  appid {appid}: age {age:.0f} days, {n} total reviews")
        if n >= 500:
            return appid
        time.sleep(1)
    return None


def main() -> None:
    CAPTURES.mkdir(exist_ok=True)

    recent_appid = resolve_recent_hit()
    tiny_appid = resolve_tiny_indie()

    targets = [("old_large", 440, "Team Fortress 2 (2007, ~1M reviews)")]
    if recent_appid:
        targets.append(("recent", recent_appid, "top seller released <=90 days ago"))
    if tiny_appid:
        targets.append(("tiny_indie", tiny_appid, "new release, <100 reviews"))
    if not recent_appid or not tiny_appid:
        print("  WARNING: could not fill every profile; probing what we have — "
              "rerun with hand-picked appids if needed.")

    for label, appid, note in targets:
        describe_histogram(label, appid, note)
        time.sleep(1.5)

    print(f"\nRaw captures in {CAPTURES}/")


if __name__ == "__main__":
    main()
