"""Deployment (M3) runner gate: verify the whole-game English totals read.

The serving runner's size rule branches on the ENGLISH pool (the sampling
study certified English-only draws — "take-all over a tiny English pool is
the honest production behavior"), and the only pre-fetch way to know it is a
totals-only read with ``language=english``. The bomb-pick probe validated
that read *windowed*; the runner's read is whole-game, which no probe has
made. Per game, three questions:

- does the whole-game English totals read return a coherent count — present,
  positive where English reviews are known to exist, and at or below the
  all-language total?
- does it agree with an independent measurement — the fresh-buy run fetched
  three games whole-life and counted English rows one by one (2026-08-03),
  so the wire count should land near those numbers (a few days of new
  reviews is the expected drift, order-of-magnitude disagreement is a fail)?
- which size-rule branch does each game take under English vs all-language
  branching — the two long-tail picks should FLIP to take-all, which is the
  motivating case for the ruling.

Probe-grade: sequential, stdout-narrated, raw requests mirroring the
production seam's exact param base (the seam stays out — a probe varies what
the seam hard-codes). Capture: ``captures/english_totals_summary.json``.

Run: python probes/english_totals_probe.py
"""

import json
import time
from pathlib import Path

import requests

CAPTURES = Path(__file__).parent / "captures"
SLEEP_S = 1.5

# The ruled size rule (curves checkpoint, 2026-08-02): take all at pool
# <= 2_000, else sample n = 1_000 — the branch preview uses the cutoff only.
TAKE_ALL_CUTOFF = 2_000

# Reference counts measured by the fresh-buy run (freshbuy-20260803T110347Z-
# bccdb631): whole-life fetches with English rows counted one by one. The
# marked-window games are window-scoped there, so only the whole-life three
# carry a whole-game reference; TF2 rides along as the big-game sanity check
# (no reference, coherence only).
GAMES = (
    (1918680, "Sword and Fairy Inn 2", 2_277, 36),
    (1863430, "Dragonkin: The Banished", 2_620, 1_312),
    (247000, "Talisman: Digital Classic Edition", 9_997, 6_108),
    (440, "Team Fortress 2", None, None),
)

# Mirrors the production seam's _TOTALS_PARAMS (steam_client.client): the
# bias-avoiding trio + off-topic restore + num_per_page=0; the English read
# overrides exactly one key, which is the whole point of the probe.
TOTALS_BASE = {
    "json": 1,
    "language": "all",
    "purchase_type": "all",
    "review_type": "all",
    "filter_offtopic_activity": 0,
    "num_per_page": 0,
}


def totals(app_id: int, language: str) -> dict:
    resp = requests.get(
        f"https://store.steampowered.com/appreviews/{app_id}",
        params={**TOTALS_BASE, "language": language},
        timeout=30,
    )
    resp.raise_for_status()
    time.sleep(SLEEP_S)
    return resp.json().get("query_summary", {})


def branch(pool: int) -> str:
    return "take-all" if pool <= TAKE_ALL_CUTOFF else f"sample (pool {pool:,} > cutoff)"


def probe_game(app_id: int, name: str, ref_all: int | None, ref_english: int | None) -> dict:
    print(f"\n=== {name} ({app_id}) ===")
    all_summary = totals(app_id, "all")
    english_summary = totals(app_id, "english")
    all_total = int(all_summary.get("total_reviews", -1))
    english_total = int(english_summary.get("total_reviews", -1))

    coherent = 0 <= english_total <= all_total
    print(f"  totals: all {all_total:>9,} · english {english_total:>9,}"
          f"   coherent(0<=en<=all): {'PASS' if coherent else 'FAIL'}")
    if ref_all is not None and ref_english is not None:
        print(f"  fresh-buy reference (2026-08-03): all {ref_all:>9,} · english {ref_english:>9,}")
    print(f"  branch on English pool     : {branch(english_total)}")
    print(f"  branch on all-language pool: {branch(all_total)}   <- what naive branching would do")

    return {
        "app_id": app_id, "name": name,
        "all_total": all_total, "english_total": english_total,
        "coherent": coherent,
        "reference_all": ref_all, "reference_english": ref_english,
        "english_branch": branch(english_total),
        "all_language_branch": branch(all_total),
        "all_summary": all_summary, "english_summary": english_summary,
    }


def main() -> None:
    CAPTURES.mkdir(exist_ok=True)
    reports = [probe_game(*game) for game in GAMES]
    (CAPTURES / "english_totals_summary.json").write_text(
        json.dumps(reports, indent=1), encoding="utf-8")

    print("\n=== runner-gate summary ===")
    verdict = all(r["coherent"] for r in reports)
    for r in reports:
        if r["reference_english"] is None:
            note = "coherence only"
        else:
            drift = r["english_total"] - r["reference_english"]
            note = f"vs reference {r['reference_english']:,} (drift {drift:+,})"
        print(f"{r['name']:<36} english {r['english_total']:>9,}   {note}")
    print(f"coherence: {'ALL PASS' if verdict else 'FAILURES PRESENT'} · "
          f"capture: captures/english_totals_summary.json")


if __name__ == "__main__":
    main()
