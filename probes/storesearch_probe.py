"""Frontend (M3 step 6) search gate: what does the storefront search actually return?

The search page's spine is "type a game name, get the report" — a typed name
must resolve to an app id (plus a capsule image and a display name) before a
POST can mean anything. The candidate endpoint is the storefront's own
``/api/storesearch`` — undocumented like all of Steam's store API, so before
a client surface exists, this probe pins the wire truth. Per question:

- shape: what fields does an item carry (id, name, image URL?) and are they
  stable across items — the parse contract gets written against these bytes.
- resolution: do canonical names surface the expected app id at or near the
  top ("team fortress" → 440, "witcher 3" → 292030)?
- noise: does a franchise term return non-game rows (DLC, soundtracks,
  demos) and does any field distinguish them?
- edges: unicode terms (encoding survives?), a garbage term (what does an
  empty result look like — [] or a missing key?).

Probe-grade: sequential, stdout-narrated, raw requests at the politeness
floor. Capture: ``captures/storesearch_summary.json`` (full bodies embedded —
the parse tests will eat these exact bytes).

Run: python probes/storesearch_probe.py
"""

import json
import time
from pathlib import Path

import httpx

CAPTURES = Path(__file__).parent / "captures"
SLEEP_S = 1.5

URL = "https://store.steampowered.com/api/storesearch/"

# (term, expected app id or None, why this term)
TERMS = (
    ("team fortress", 440, "canonical name, ancient big game"),
    ("witcher 3", 292030, "franchise + numeral, editions exist"),
    ("hollow knight", 367520, "two games share the prefix (Silksong)"),
    ("elden ring", 1245620, "recent big game, DLC exists"),
    ("ōkami", 587620, "unicode in the term — a listed game with a macron name"),
    ("qzxqzxqzx no such game", None, "garbage — the empty-result shape"),
)


def search(term: str) -> dict:
    resp = httpx.get(
        URL, params={"term": term, "l": "english", "cc": "US"}, timeout=30
    )
    resp.raise_for_status()
    time.sleep(SLEEP_S)
    return resp.json()


def probe_term(term: str, expected_id: int | None, why: str) -> dict:
    print(f"\n=== {term!r} ({why}) ===")
    body = search(term)
    items = body.get("items", [])
    total = body.get("total")
    print(f"  total: {total} · items returned: {len(items)}")

    key_sets = {frozenset(item.keys()) for item in items}
    print(f"  item key sets ({len(key_sets)} distinct):")
    for keys in key_sets:
        print(f"    {sorted(keys)}")

    for rank, item in enumerate(items[:5]):
        marker = " <-- expected" if expected_id is not None and item.get("id") == expected_id else ""
        print(f"  #{rank}: id={item.get('id')} type={item.get('type')!r} "
              f"name={item.get('name')!r}{marker}")

    found_rank = next(
        (rank for rank, item in enumerate(items) if item.get("id") == expected_id), None
    ) if expected_id is not None else None
    if expected_id is not None:
        print(f"  expected {expected_id}: "
              f"{'rank ' + str(found_rank) if found_rank is not None else 'NOT IN RESULTS'}")

    return {
        "term": term, "why": why, "expected_id": expected_id,
        "found_rank": found_rank, "total": total, "item_count": len(items),
        "distinct_key_sets": [sorted(keys) for keys in key_sets],
        "body": body,
    }


def main() -> None:
    CAPTURES.mkdir(exist_ok=True)
    reports = [probe_term(*case) for case in TERMS]
    (CAPTURES / "storesearch_summary.json").write_text(
        json.dumps(reports, indent=1, ensure_ascii=False), encoding="utf-8")

    print("\n=== search-gate summary ===")
    for r in reports:
        if r["expected_id"] is None:
            note = f"{r['item_count']} items"
        elif r["found_rank"] is None:
            note = f"expected {r['expected_id']} MISSING"
        else:
            note = f"expected {r['expected_id']} at rank {r['found_rank']}"
        print(f"{r['term']:<28} {note}")
    print("capture: captures/storesearch_summary.json")


if __name__ == "__main__":
    main()
