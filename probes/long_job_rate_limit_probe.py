"""Long-job rate-limit probe (2026-11-14): does a 150+ window job still draw an
HTTP 429 on the WebAPI review method, and what does Steam say when it does?

Six jobs died on 429 between 2026-10-01 and 2026-10-19, all on the retired
store endpoint, each about 234 s into its requests. Since the 2026-10-22 move
to ``IUserReviewsService/GetAppReviews`` no job longer than 86 windows has
run, so the new endpoint's limit is untested. This probe replays the Steam
side of one long job and nothing else: the runner's own pre-fetch reads
(appdetails, totals, English totals, histogram), the production plan compiler
at the serving target, then every planned window through the real
``SteamClient`` over the real ``SteamTransport`` (1.5 s floor, six attempts).
No LLM call, no store write.

What it measures that production cannot: an httpx transport wrapper records
every response's status and headers (the production transport keeps neither),
so a 429 arrives with its ``Retry-After`` and any limit headers on record. If
the job phase dies on the transport's exhausted retries, a recovery phase
polls one cheap read until the first 200 and records how long the block
lasted (honoring ``Retry-After`` when Steam sends one, otherwise every 30 s,
bounded at 30 minutes).

Two limits on what a run proves. It runs from the machine it is started on,
and a per-address budget says nothing certain about another address. And it
fetches windows back to back, where the live job's fetch can stall behind
the classify queue, so this is the fastest request rate a job can reach.

Result (2026-11-14, from a laptop): Portal 2 ran 172 windows in 176 requests
over 263 s and Rust 156 windows in 160 requests over 258 s, every answer HTTP
200, no retry, so the 429 was not reproduced and the recovery phase never ran.
Neither host sends a rate-limit header on a 200. A side finding: the review
method answers a repeated request from a cache for ten minutes (same
``expires``, 20 ms against 360 ms), so a second run of the same game inside
that time is not a fresh test.

Run: python probes/long_job_rate_limit_probe.py [app_id]   (default 620, Portal 2)
Writes: probes/captures/long_job_rate_limit_<app_id>_<utc>.jsonl, one row per request.
"""

import json
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import httpx

from steamlens.contracts import SamplingPolicy, SamplingPolicyKind
from steamlens.core.sampling import compile_plan
from steamlens.serve.config import ServeConfig
from steamlens.steam_client import (
    SteamClient,
    SteamClientConfig,
    SteamTransport,
    SteamUnavailableError,
)
from steamlens.steam_client.client import review_request

CAPTURES = Path(__file__).parent / "captures"
PORTAL_2 = 620
MIN_WINDOWS = 150
REVIEWS_URL = "https://api.steampowered.com/IUserReviewsService/GetAppReviews/v1/"
# The client's one-review totals read, the cheapest request on the limited host.
RECOVERY_QUERY = {
    "languages": ["all"],
    "purchase_type": 1,
    "review_type": 0,
    "filter_offtopic_activity": False,
    "num_per_page": 1,
}
RECOVERY_POLL_S = 30.0
RECOVERY_BOUND_S = 30 * 60.0
ROLLING_WINDOW_S = 300.0
LIMIT_HEADER_HINTS = ("retry", "rate", "limit", "eresult", "quota")


class RecordingTransport(httpx.BaseTransport):
    """The real network transport, with one JSONL row written per response."""

    def __init__(self, log_path: Path) -> None:
        self._inner = httpx.HTTPTransport()
        self._log = log_path.open("w", encoding="utf-8")
        self._started = time.monotonic()
        self.rows: list[dict] = []
        self.phase = "job"

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        sent = time.monotonic()
        row: dict = {
            "seq": len(self.rows) + 1,
            "phase": self.phase,
            "t_s": round(sent - self._started, 3),
            "utc": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "host": request.url.host,
            "path": request.url.path,
        }
        try:
            response = self._inner.handle_request(request)
        except httpx.TransportError as exc:
            row["error"] = repr(exc)
            self._record(row)
            raise
        row["elapsed_ms"] = round((time.monotonic() - sent) * 1000)
        row["status"] = response.status_code
        row["headers"] = {
            name: value for name, value in response.headers.items()
            if name.lower() != "set-cookie"
        }
        if response.status_code != 200:
            response.read()
            row["body"] = response.text[:400]
        self._record(row)
        return response

    def _record(self, row: dict) -> None:
        self.rows.append(row)
        self._log.write(json.dumps(row) + "\n")
        self._log.flush()

    def close(self) -> None:
        self._inner.close()
        self._log.close()


class PrintSink:
    """The transport's and client's narration, straight to stdout."""

    def emit(self, event: object) -> None:
        print(f"    {event}", flush=True)


def run_job_phase(client: SteamClient, app_id: int) -> None:
    """The Steam side of one sampled job, in the runner's order."""
    ref = client.resolve_game(app_id, "probe")
    english = client.fetch_totals(app_id, language="english")
    histogram = client.fetch_histogram(app_id)
    plan = compile_plan(
        histogram,
        SamplingPolicy(
            kind=SamplingPolicyKind.TIME_PROPORTIONAL,
            target_size=ServeConfig().sample_target,
        ),
    )
    print(f"{ref.store_name} (app {app_id}): {ref.total_reviews:,} reviews claimed, "
          f"{english.total_reviews if english else 0:,} English; "
          f"plan: n={plan.planned_total:,} over {len(plan.windows)} windows", flush=True)
    if len(plan.windows) < MIN_WINDOWS:
        raise SystemExit(
            f"plan has {len(plan.windows)} windows, the probe wants {MIN_WINDOWS}+ "
            "(the failing jobs' size) — pick an older game"
        )
    started = time.monotonic()
    for index, window in enumerate(plan.windows, start=1):
        result = client.fetch_window(app_id, window.start, window.end, quota=window.quota)
        print(f"[{index:>3}/{len(plan.windows)}] {window.start:%Y-%m-%d} quota={window.quota:<3} "
              f"got={len(result.reviews):<3} pages={result.pages_fetched} "
              f"retries={result.retries} {result.outcome.value} "
              f"t={time.monotonic() - started:6.1f}s", flush=True)


def run_recovery_phase(recorder: RecordingTransport, app_id: int) -> None:
    """After a block: poll one cheap read until the first 200, timing the block."""
    recorder.phase = "recovery"
    last = recorder.rows[-1]
    retry_after = last.get("headers", {}).get("retry-after")
    print(f"\nblocked — last response: status={last.get('status')} "
          f"retry-after={retry_after!r} body={last.get('body', '')[:160]!r}", flush=True)
    blocked_at = time.monotonic()
    first_wait = float(retry_after) + 1.0 if retry_after and retry_after.isdigit() else None
    with httpx.Client(transport=recorder, timeout=30,
                      headers={"User-Agent": SteamClientConfig().user_agent}) as http:
        while time.monotonic() - blocked_at < RECOVERY_BOUND_S:
            wait = first_wait if first_wait is not None else RECOVERY_POLL_S
            first_wait = None
            time.sleep(wait)
            response = http.get(REVIEWS_URL, params=review_request(app_id, RECOVERY_QUERY))
            since = time.monotonic() - blocked_at
            print(f"  recovery poll at +{since:6.1f}s: HTTP {response.status_code} "
                  f"retry-after={response.headers.get('retry-after')!r}", flush=True)
            if response.status_code == 200:
                print(f"recovered {since:.0f}s after the transport gave up "
                      f"(resolution {RECOVERY_POLL_S:.0f}s)", flush=True)
                return
    print(f"still blocked after {RECOVERY_BOUND_S:.0f}s — bound reached", flush=True)


def summarize(rows: list[dict]) -> None:
    """Request counts, the densest five minutes, and every limit-shaped header seen."""
    print("\n=== summary ===")
    by_key = Counter((r["phase"], r["host"], r.get("status", "error")) for r in rows)
    for (phase, host, status), count in sorted(by_key.items(), key=str):
        print(f"  {phase:<9} {host:<28} {status!s:<6} {count:>4}")
    job = [r for r in rows if r["phase"] == "job"]
    if job:
        times = [r["t_s"] for r in job]
        densest = max(
            sum(1 for t in times if start <= t < start + ROLLING_WINDOW_S) for start in times
        )
        print(f"  job phase: {len(job)} requests over {times[-1] - times[0]:.0f}s; "
              f"densest {ROLLING_WINDOW_S:.0f}s held {densest} requests")
    for host in sorted({r["host"] for r in rows}):
        names: set[str] = set()
        for r in rows:
            if r["host"] == host:
                names.update(name.lower() for name in r.get("headers", {}))
        hinted = sorted(n for n in names if any(h in n for h in LIMIT_HEADER_HINTS))
        print(f"  {host}: {len(names)} distinct header names; limit-shaped: {hinted or 'none'}")
    first_bad = next((r for r in rows if r.get("status") not in (200, None)), None)
    if first_bad:
        print(f"  first non-200: seq {first_bad['seq']} at t={first_bad['t_s']}s "
              f"status={first_bad['status']} headers={json.dumps(first_bad['headers'])}")


if __name__ == "__main__":
    probe_app_id = int(sys.argv[1]) if len(sys.argv) > 1 else PORTAL_2
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    capture_path = CAPTURES / f"long_job_rate_limit_{probe_app_id}_{stamp}.jsonl"
    recording = RecordingTransport(capture_path)
    print(f"capture: {capture_path}", flush=True)
    try:
        with SteamTransport(SteamClientConfig(), PrintSink(), transport=recording) as steam:
            try:
                run_job_phase(SteamClient(steam), probe_app_id)
                print("\njob phase completed — no block", flush=True)
            except SteamUnavailableError as exc:
                print(f"\njob phase failed as production would: {exc}", flush=True)
                run_recovery_phase(recording, probe_app_id)
    finally:
        summarize(recording.rows)
        recording.close()
