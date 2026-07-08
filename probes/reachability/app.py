"""Smoke-test probe (M0): does Steam answer normally from a datacenter IP?

The one fatal unknown of the smoke-test milestone: the app's live-compute premise
assumes Steam's store endpoints answer from cloud hosts. This probe makes the same
calls the local baseline made — one histogram fetch plus a sequential cursor walk
over `appreviews` — and reports per-request status, latency, and payload sanity,
plus the egress IP so the run proves where it ran from.

Dual-mode so local and datacenter runs are the same code:
    python app.py            -> run once, print the probe JSON (baseline mode)
    python app.py --serve    -> HTTP server on :7860 (HF Spaces Docker mode);
                                GET /probe?pages=N runs it on demand

Probe-grade: sequential, no retries — a transient failure is itself data here.
"""

import json
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import requests

APPID = 440  # Team Fortress 2 — the local baseline's old_large profile
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


def run_probe(pages: int = DEFAULT_PAGES) -> dict:
    pages = max(1, min(pages, MAX_PAGES))
    walk = probe_cursor_walk(pages)
    statuses = [p.get("status") for p in walk]
    return {
        "egress_ip": egress_ip(),
        "appid": APPID,
        "histogram": probe_histogram(),
        "cursor_walk": walk,
        "verdict": {
            "pages_attempted": pages,
            "pages_ok": statuses.count(200),
            "all_ok": statuses == [200] * pages,
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
