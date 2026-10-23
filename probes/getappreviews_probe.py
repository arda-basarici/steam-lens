"""Recapture probe (2026-10-23): the review pages the parse suite pins, re-read
from the WebAPI method that replaced the store endpoint.

Valve retired ``store.steampowered.com/appreviews`` on 2026-10-22 (announced
2026-10-02); it now answers a 302 to the store front. The replacement,
``IUserReviewsService/GetAppReviews/v1``, wraps its body in ``response``,
drops the ``success`` field, takes integer enums, and names the date window
``date_range_start``/``date_range_end`` — documented now, where the old names
were not. The captures in ``captures/getappreviews_*.json`` are this method's
real answers for the same questions the old captures asked: Borderlands 2's
marked window default vs off-topic restored, one windowed-unfiltered page of
Europa Universalis IV over its own marked window, an empty window, and an id
the store has no record of. Raw bodies, saved verbatim.

Run: python probes/getappreviews_probe.py
"""

import json
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

CAPTURES = Path(__file__).parent / "captures"
URL = "https://api.steampowered.com/IUserReviewsService/GetAppReviews/v1/"
HISTOGRAM = "https://store.steampowered.com/appreviewhistogram/{app_id}"
BORDERLANDS_2 = 49520
EU4 = 236850
TF2 = 440
NO_SUCH_APP = 999_999_999

UNFILTERED = {
    "filter": 1,  # Recent
    "languages": ["all"],
    "purchase_type": 1,  # All
    "review_type": 0,  # All
    "num_per_page": 100,
    "cursor": "*",
}


def capture(name: str, query: dict) -> dict:
    response = httpx.get(URL, params={"input_json": json.dumps(query)}, timeout=30)
    response.raise_for_status()
    body = response.json()
    (CAPTURES / f"getappreviews_{name}.json").write_text(
        json.dumps(body, indent=1), encoding="utf-8"
    )
    inner = body.get("response", {})
    print(f"{name}: HTTP {response.status_code} eresult={response.headers.get('x-eresult')} "
          f"reviews={len(inner.get('reviews', []))} summary={inner.get('query_summary')} "
          f"total_matching={inner.get('total_matching')} cursor={inner.get('cursor')!r}")
    time.sleep(1.5)
    return body


def marked_window(app_id: int) -> tuple[int, int]:
    body = httpx.get(HISTOGRAM.format(app_id=app_id), params={"l": "english"}, timeout=30)
    body.raise_for_status()
    events = body.json()["past_events"]
    first = events[0]
    print(f"histogram {app_id}: marked window "
          f"{datetime.fromtimestamp(int(first['start_date']), tz=UTC):%Y-%m-%d} .. "
          f"{datetime.fromtimestamp(int(first['end_date']), tz=UTC):%Y-%m-%d}")
    time.sleep(1.5)
    return int(first["start_date"]), int(first["end_date"])


def windowed(app_id: int, start: int, end: int, **extra: object) -> dict:
    return {"appid": app_id, **UNFILTERED, "date_range_start": start, "date_range_end": end,
            "date_range_exclude": False, **extra}


if __name__ == "__main__":
    bl_start, bl_end = marked_window(BORDERLANDS_2)
    slice_end = min(bl_end, bl_start + 86_400)
    capture("offtopic_default_49520", windowed(BORDERLANDS_2, bl_start, slice_end))
    capture("offtopic_restored_49520",
            windowed(BORDERLANDS_2, bl_start, slice_end, filter_offtopic_activity=False))
    eu_start, eu_end = marked_window(EU4)
    capture("windowed_unfiltered_236850",
            windowed(EU4, eu_start, eu_end, filter_offtopic_activity=False))
    capture("empty_window_440",
            windowed(TF2, int(datetime(2008, 1, 1, tzinfo=UTC).timestamp()),
                     int(datetime(2008, 1, 2, tzinfo=UTC).timestamp()),
                     filter_offtopic_activity=False))
    capture("no_such_app", {"appid": NO_SUCH_APP, **UNFILTERED, "filter_offtopic_activity": False})
