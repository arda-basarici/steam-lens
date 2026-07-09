"""Smoke-test probe (M0): does Steam answer normally from a datacenter IP?

The one fatal unknown of the smoke-test milestone: the app's live-compute premise
assumes Steam's store endpoints answer from cloud hosts. This probe makes the same
calls the local baseline made — one histogram fetch plus a sequential cursor walk
over `appreviews` — and reports per-request status, latency, and payload sanity,
plus the egress IP so the run proves where it ran from.

Extended at extraction+eval (M1) entry with the production primary path, which the
smoke tests never exercised from a datacenter: a date-windowed cursor walk using the
undocumented `start_date`/`end_date` params plus `filter_offtopic_activity=0`, and a
marked-window check on Borderlands 2 (default listing blanks Valve's marked window;
the unfiltered flag must restore it — the local behavior `offtopic_probe.py` found).

Dual-mode so local and datacenter runs are the same code:
    python app.py            -> run once, print the probe JSON (baseline mode)
    python app.py --serve    -> HTTP server on :7860 (HF Spaces Docker mode);
                                GET /probe?pages=N runs it on demand

Probe-grade: sequential, no retries — a transient failure is itself data here.
"""

import json
import sys
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import requests

APPID = 440  # Team Fortress 2 — the local baseline's old_large profile
MARKED_APPID = 49520  # Borderlands 2 — carries the first Valve-marked off-topic window
# Plain-window walk target: one arbitrary full TF2 month (TF2's histogram carries no
# past_events), far enough back that its contents no longer change under us.
WINDOW_START = int(datetime(2023, 6, 1, tzinfo=timezone.utc).timestamp())
WINDOW_END = int(datetime(2023, 6, 30, 23, 59, 59, tzinfo=timezone.utc).timestamp())
WINDOWED_PAGES = 2
PORT = 7860
DEFAULT_PAGES = 5
MAX_PAGES = 10


def timed_get(url: str, params: dict) -> tuple[requests.Response | None, float, str]:
    """One GET with wall-clock ms and an error string instead of an exception."""
    start = time.perf_counter()
    try:
        resp = requests.get(url, params=params, timeout=30)
        return resp, (time.perf_counter() - start) * 1000, ""
    except requests.RequestException as exc:
        return None, (time.perf_counter() - start) * 1000, repr(exc)


def egress_ip() -> str:
    resp, _, err = timed_get("https://api.ipify.org", {"format": "json"})
    if resp is None:
        return f"unavailable ({err})"
    return resp.json().get("ip", "unavailable")


def probe_histogram() -> dict:
    resp, elapsed_ms, err = timed_get(
        f"https://store.steampowered.com/appreviewhistogram/{APPID}",
        {"l": "english"},
    )
    report = {"endpoint": "appreviewhistogram", "elapsed_ms": round(elapsed_ms)}
    if resp is None:
        return {**report, "error": err}
    report["status"] = resp.status_code
    try:
        results = resp.json().get("results", {})
        report["rollup_type"] = results.get("rollup_type")
        report["rollup_buckets"] = len(results.get("rollups", []))
        report["recent_buckets"] = len(results.get("recent", []))
    except ValueError:
        report["error"] = "non-JSON body: " + resp.text[:200]
    return report


def probe_cursor_walk(pages: int) -> list[dict]:
    """Walk sequential appreviews cursor pages; each page's health is one report."""
    walk = []
    cursor = "*"
    for page in range(1, pages + 1):
        resp, elapsed_ms, err = timed_get(
            f"https://store.steampowered.com/appreviews/{APPID}",
            {
                "json": 1, "filter": "recent", "language": "all",
                "purchase_type": "all", "num_per_page": 100, "cursor": cursor,
            },
        )
        report = {"page": page, "elapsed_ms": round(elapsed_ms)}
        if resp is None:
            walk.append({**report, "error": err})
            break
        report["status"] = resp.status_code
        try:
            data = resp.json()
            report["reviews_returned"] = len(data.get("reviews", []))
            report["success_flag"] = data.get("success")
            cursor = data.get("cursor", "")
        except ValueError:
            report["error"] = "non-JSON body: " + resp.text[:200]
        walk.append(report)
        if report.get("status") != 200 or not cursor:
            break
        time.sleep(1)
    return walk


def probe_windowed_walk(appid: int, start: int, end: int,
                        extra_params: dict, pages: int) -> list[dict]:
    """Walk cursor pages of a date-windowed `appreviews` fetch — the production
    primary path: the undocumented start/end date params composed with cursor
    pagination, plus whatever flags `extra_params` adds."""
    walk = []
    cursor = "*"
    for page in range(1, pages + 1):
        resp, elapsed_ms, err = timed_get(
            f"https://store.steampowered.com/appreviews/{appid}",
            {
                "json": 1, "filter": "recent", "language": "all",
                "purchase_type": "all", "num_per_page": 100,
                "start_date": start, "end_date": end,
                "date_range_type": "include", "cursor": cursor,
                **extra_params,
            },
        )
        report = {"page": page, "elapsed_ms": round(elapsed_ms)}
        if resp is None:
            walk.append({**report, "error": err})
            break
        report["status"] = resp.status_code
        try:
            data = resp.json()
            reviews = data.get("reviews", [])
            report["reviews_returned"] = len(reviews)
            report["success_flag"] = data.get("success")
            if reviews:
                stamps = [int(r.get("timestamp_created", 0)) for r in reviews]
                report["all_inside_window"] = start <= min(stamps) and max(stamps) <= end
            cursor = data.get("cursor", "")
        except ValueError:
            report["error"] = "non-JSON body: " + resp.text[:200]
        walk.append(report)
        if report.get("status") != 200 or not cursor or not report.get("reviews_returned"):
            break
        time.sleep(1)
    return walk


def probe_marked_window() -> dict:
    """The unfiltered flag, from wherever this runs: Borderlands 2's Valve-marked
    window should come back blanked by the default listing and restored by
    `filter_offtopic_activity=0` — the behavior the local `offtopic_probe.py` found.
    The window itself comes from the live histogram's `past_events`, not a constant,
    so this also confirms the annotation is visible from this egress."""
    resp, elapsed_ms, err = timed_get(
        f"https://store.steampowered.com/appreviewhistogram/{MARKED_APPID}",
        {"l": "english"},
    )
    report = {"appid": MARKED_APPID, "histogram_elapsed_ms": round(elapsed_ms)}
    if resp is None:
        return {**report, "error": err}
    try:
        events = resp.json().get("past_events", [])
    except ValueError:
        return {**report, "error": "non-JSON body: " + resp.text[:200]}
    report["past_events"] = events
    if not events:
        return {**report, "error": "histogram carries no past_events to probe"}
    start, end = int(events[0]["start_date"]), int(events[0]["end_date"])
    time.sleep(1)
    report["default_listing"] = probe_windowed_walk(
        MARKED_APPID, start, end, {}, pages=1)
    time.sleep(1)
    report["unfiltered_listing"] = probe_windowed_walk(
        MARKED_APPID, start, end, {"filter_offtopic_activity": 0}, pages=1)
    return report


def run_probe(pages: int = DEFAULT_PAGES) -> dict:
    pages = max(1, min(pages, MAX_PAGES))
    walk = probe_cursor_walk(pages)
    statuses = [p.get("status") for p in walk]
    time.sleep(1)
    windowed = probe_windowed_walk(
        APPID, WINDOW_START, WINDOW_END,
        {"filter_offtopic_activity": 0}, WINDOWED_PAGES)
    time.sleep(1)
    marked = probe_marked_window()
    default_first = (marked.get("default_listing") or [{}])[0]
    unfiltered_first = (marked.get("unfiltered_listing") or [{}])[0]
    return {
        "egress_ip": egress_ip(),
        "appid": APPID,
        "histogram": probe_histogram(),
        "cursor_walk": walk,
        "windowed_walk": windowed,
        "marked_window": marked,
        "verdict": {
            "pages_attempted": pages,
            "pages_ok": statuses.count(200),
            "all_ok": statuses == [200] * pages,
            "windowed_ok": bool(windowed) and all(
                p.get("status") == 200 and p.get("reviews_returned")
                and p.get("all_inside_window") for p in windowed),
            "offtopic_filter_ok": (
                default_first.get("reviews_returned") == 0
                and bool(unfiltered_first.get("reviews_returned"))
                and unfiltered_first.get("all_inside_window") is True),
        },
    }


class ProbeHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != "/probe":
            body = b'Steam reachability probe (M0). GET /probe?pages=N to run.\n'
            self._respond(200, "text/plain", body)
            return
        query = parse_qs(parsed.query)
        pages = int(query.get("pages", [DEFAULT_PAGES])[0])
        result = run_probe(pages)
        self._respond(200, "application/json",
                      json.dumps(result, indent=2).encode())

    def _respond(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    if "--serve" in sys.argv:
        print(f"Serving probe on :{PORT}", flush=True)
        HTTPServer(("0.0.0.0", PORT), ProbeHandler).serve_forever()
    else:
        print(json.dumps(run_probe(), indent=2))
