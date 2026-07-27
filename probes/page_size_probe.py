"""One-shot probe (E1): does the review endpoint honor num_per_page above 100?

The docs say 100 is the maximum, but fetcher programs are reported running 200
(Arda's observation, 2026-07-27). If a 200-request comes back with 200 reviews,
every window costs half the requests — a config edit, nothing else, since page
size is deliberately a non-load-bearing knob (no batch size is universally
safe; FIXLOG 2026-07-07). One paced request against TF2's plain recent feed,
which always has well over 200 reviews to serve; the raw response lands in
captures/page_size_200.json.

Probe-grade script: single request, stdout-narrated. Run:
uv run python probes/page_size_probe.py
"""

import json
from pathlib import Path

import httpx

CAPTURES = Path(__file__).parent / "captures"
URL = "https://store.steampowered.com/appreviews/440"
PARAMS = {
    "json": 1,
    "filter": "recent",
    "language": "all",
    "purchase_type": "all",
    "review_type": "all",
    "filter_offtopic_activity": 0,
    "num_per_page": 200,
    "cursor": "*",
}


def main() -> None:
    resp = httpx.get(
        URL,
        params=PARAMS,
        headers={"User-Agent": "steam-lens/0.1 (+https://github.com/arda-basarici)"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    reviews = data.get("reviews", [])
    CAPTURES.mkdir(exist_ok=True)
    (CAPTURES / "page_size_200.json").write_text(json.dumps(data, indent=2), encoding="utf-8")

    print(f"asked num_per_page=200 -> got {len(reviews)} reviews "
          f"(success={data.get('success')}, capture saved)")
    if len(reviews) > 100:
        print("HONORED above 100 — halving per-window request cost is a config edit away")
    else:
        print("CLAMPED at or below 100 — the documented cap stands; default 100 stays")


if __name__ == "__main__":
    main()
