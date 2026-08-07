"""Rate-budget recheck (M3 entry): does the ~200-req/5-min budget hold from this host?

M0's datacenter pass proved Steam *answers* from cloud IPs but never stressed the
community-known store-API budget of roughly 200 requests per 5 minutes — and the M3
host gets its own recheck before anything is built on it. Two phases:

    A — at-budget: 200 requests paced evenly over 5 minutes (one per 1.5 s), the
        sustained rate the app will actually live under. The gate passes iff every
        response is 200.
    B — over-budget burst: a short unpaced run to see whether the edge is near and
        what refusal looks like from here. Aborts on the first non-200 — one data
        point, not a fight. A live 429 here is the recorded evidence that reopens
        the settled 429-on-the-5xx-ladder ruling (declined 2026-07-28, no 429 ever
        observed); absence keeps that ruling closed.

Requests round-robin over a small appid set so a response cache can't quietly absorb
the load, and stay cheap (`num_per_page=1`). Probe-grade like its reachability
sibling: sequential, no retries — a transient failure is itself data. The JSON
capture carries the egress IP so the run proves where it ran from.

    python3 probe.py > rate_budget_netcup.json
"""

import json
import time

import requests

# The corpus five plus the two reachability-probe regulars — enough variety to
# defeat per-URL caching, all high-traffic apps whose page 1 always exists.
APPIDS = [440, 49520, 227300, 236850, 252950, 750920, 1091500]

BUDGET_REQUESTS = 200
BUDGET_SPACING_S = 1.5  # 200 requests x 1.5 s = the 5-minute budget window
BURST_REQUESTS = 60


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


def one_request(seq: int, phase_start: float) -> dict:
    """One cheap appreviews hit, reported as a flat record: when, status, latency."""
    appid = APPIDS[seq % len(APPIDS)]
    resp, elapsed_ms, err = timed_get(
        f"https://store.steampowered.com/appreviews/{appid}",
        {"json": 1, "filter": "recent", "language": "all", "num_per_page": 1},
    )
    record = {
        "seq": seq,
        "appid": appid,
        "t_offset_s": round(time.perf_counter() - phase_start, 2),
        "elapsed_ms": round(elapsed_ms),
    }
    if resp is None:
        return {**record, "status": None, "error": err}
    record["status"] = resp.status_code
    try:
        record["success_flag"] = resp.json().get("success")
    except ValueError:
        record["error"] = "non-JSON body: " + resp.text[:200]
    return record


def run_paced_phase() -> list[dict]:
    """Phase A: the budget rate held for the full window, pacing by wall clock so
    request duration doesn't compress the schedule."""
    records = []
    phase_start = time.perf_counter()
    for seq in range(BUDGET_REQUESTS):
        target = seq * BUDGET_SPACING_S
        lag = target - (time.perf_counter() - phase_start)
        if lag > 0:
            time.sleep(lag)
        records.append(one_request(seq, phase_start))
    return records


def run_burst_phase() -> list[dict]:
    """Phase B: unpaced requests until the first refusal or the cap — whichever
    comes first. Stopping at one non-200 is the politeness contract."""
    records = []
    phase_start = time.perf_counter()
    for seq in range(BURST_REQUESTS):
        record = one_request(seq, phase_start)
        records.append(record)
        if record.get("status") != 200:
            break
    return records


def percentile(sorted_ms: list[int], fraction: float) -> int:
    """Nearest-rank percentile; fine at these sample sizes."""
    index = min(len(sorted_ms) - 1, round(fraction * (len(sorted_ms) - 1)))
    return sorted_ms[index]


def summarize(records: list[dict]) -> dict:
    statuses = [r.get("status") for r in records]
    latencies = sorted(r["elapsed_ms"] for r in records)
    non_200 = [r for r in records if r.get("status") != 200]
    return {
        "sent": len(records),
        "ok": statuses.count(200),
        "status_counts": {str(s): statuses.count(s) for s in set(statuses)},
        "latency_ms": {
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "max": latencies[-1],
        },
        "first_non_200": non_200[0] if non_200 else None,
    }


def run_probe() -> dict:
    paced = run_paced_phase()
    time.sleep(5)
    burst = run_burst_phase()
    paced_summary = summarize(paced)
    burst_summary = summarize(burst)
    return {
        "egress_ip": egress_ip(),
        "paced": {"summary": paced_summary, "records": paced},
        "burst": {"summary": burst_summary, "records": burst},
        "verdict": {
            "budget_ok": paced_summary["ok"] == BUDGET_REQUESTS,
            "burst_first_refusal": burst_summary["first_non_200"],
            "saw_429": any(r.get("status") == 429 for r in paced + burst),
        },
    }


if __name__ == "__main__":
    print(json.dumps(run_probe(), indent=2))
