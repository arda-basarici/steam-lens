"""Draw the gold-set survey slice: the reviews Arda will hand-label.

The gold set (eval/gold/INSTRUCTIONS.md, status GOLD-READY) needs its ~250
reviews. This script performs the draw once, seeded, and writes a
self-contained record: the texts ride along (gold must run in CI, which never
sees the corpus), and the manifest carries full provenance.

Design, and the rulings it honors:

- **Uniform per game, 5 per corpus game** (ruled 2026-07-16): the product
  mints *per-game* aspect aggregates, so the eval samples every game's
  vocabulary evenly. Corpus-proportional was rejected because per-game corpus
  counts are fetcher artifacts (the frozen fetcher stopped on short pages),
  not popularity.
- **The natural mix, never distorted** (INSTRUCTIONS section 10): within a
  game's draw there is NO length or content filter — bare verdicts and walls
  of whitespace arrive at their honest base rate. (Empty-text rows are
  excluded: with nothing to read there is nothing to label; the zero-mention
  base rate the ruling protects is a property of reviews *with text*.)
- **Ordered draw with reserves** (the round-2 dry-run finding): each game's
  eligible pool is shuffled once, seeded; the first five are the draw, the
  next five the ordered reserve. A labeling-time skip (non-English text — the
  corpus `language` field is reviewer-selected and proven unreliable)
  consumes the game's next unused reserve and is logged in the manifest's
  `skips` list. Reserves exhausted → rerun with a larger ``_RESERVE`` (same
  seed, same order — the prefix is stable).
- **Exclusions** via ``gold_excluded_ids()`` (the dev slice + every dry-run
  round; the single exclusion source, INSTRUCTIONS section 8).

Writes ``eval/gold/draw/manifest.json`` and ``eval/gold/draw/reviews.jsonl``
(one line per review, ``slot`` = primary | reserve). Refuses to overwrite an
existing manifest — the draw is a one-shot record; delete the directory
deliberately to redraw.
"""

from __future__ import annotations

import json
import random
from datetime import UTC, datetime
from pathlib import Path

from draw_gold_dry_run import gold_excluded_ids

from steamlens.ontology import load_ontology_version

_REPO = Path(__file__).resolve().parents[1]
_CORPUS_REVIEWS = _REPO.parent / "steam-reviews" / "data" / "raw" / "reviews"
_GAME_LIST = _REPO.parent / "steam-reviews" / "data" / "game_list.json"
_OUT_DIR = _REPO / "eval" / "gold" / "draw"

_SEED = 20260720
_PER_GAME = 5
_RESERVE = 5


def load_games() -> dict[str, str]:
    """The corpus game list as app_id -> name, from the corpus's own manifest."""
    data = json.loads(_GAME_LIST.read_text(encoding="utf-8"))
    return {str(g["app_id"]): g["name"] for g in data["games"]}


def eligible_pool(app_id: str, excluded: frozenset[str]) -> list[dict[str, str]]:
    """A game's draw pool: english-tagged, non-empty text, not gold-excluded.

    No other filter — the natural mix is the point. Returns rows as
    ``{"id", "app_id", "text"}`` in corpus file order (the shuffle seeds order
    later, in one place).
    """
    path = _CORPUS_REVIEWS / f"{app_id}_reviews.jsonl"
    pool: list[dict[str, str]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            text = (r.get("review") or "").strip()
            if text and r.get("language") == "english" and r["recommendationid"] not in excluded:
                pool.append({"id": r["recommendationid"], "app_id": app_id, "text": text})
    return pool


def main() -> None:
    manifest_path = _OUT_DIR / "manifest.json"
    if manifest_path.exists():
        raise SystemExit(
            f"{manifest_path} exists — the gold draw is one-shot; delete deliberately to redraw"
        )

    games = load_games()
    excluded = gold_excluded_ids()
    pin = load_ontology_version()
    rng = random.Random(_SEED)

    drawn: list[dict[str, str]] = []
    per_game: dict[str, dict[str, object]] = {}
    for app_id, name in games.items():
        pool = eligible_pool(app_id, excluded)
        rng.shuffle(pool)
        primary = pool[:_PER_GAME]
        reserve = pool[_PER_GAME : _PER_GAME + _RESERVE]
        for rank, row in enumerate(primary):
            drawn.append({**row, "game": name, "slot": "primary", "rank": str(rank)})
        for rank, row in enumerate(reserve):
            drawn.append({**row, "game": name, "slot": "reserve", "rank": str(rank)})
        per_game[app_id] = {
            "game": name,
            "pool_size": len(pool),
            "primary": [r["id"] for r in primary],
            "reserve": [r["id"] for r in reserve],
        }
        if len(primary) < _PER_GAME:
            print(f"!! shortfall: {name} has only {len(primary)} eligible reviews")

    primaries = [r for r in drawn if r["slot"] == "primary"]
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {
        "purpose": (
            "the gold-set survey slice: primary rows are the labeling set; a labeling-time "
            "skip consumes the game's next unused reserve and is logged in `skips`"
        ),
        "drawn_at": datetime.now(UTC).isoformat(),
        "seed": _SEED,
        "rule": (
            f"uniform per game: first {_PER_GAME} of the seeded shuffle of each game's "
            f"eligible pool (english-tagged, non-empty text, gold-exclusions removed), "
            f"next {_RESERVE} held as ordered reserve; no length or content filter"
        ),
        "corpus": str(_CORPUS_REVIEWS),
        "instructions_version": "gold-instructions-v1",
        "ontology_version": pin.version,
        "ontology_content_hash": pin.content_hash,
        "excluded_ids": sorted(excluded),
        "totals": {"games": len(games), "primary": len(primaries)},
        "skips": [],
        "per_game": per_game,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    with (_OUT_DIR / "reviews.jsonl").open("w", encoding="utf-8") as f:
        for row in drawn:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    lengths = sorted(len(r["text"]) for r in primaries)
    n_reserve = len(drawn) - len(primaries)
    median = lengths[len(lengths) // 2]
    print(f"\ndrawn: {len(primaries)} primary + {n_reserve} reserve across {len(games)} games")
    print(f"text length (primary): min {lengths[0]}, median {median}, max {lengths[-1]}")
    print(f"written to {_OUT_DIR}")


if __name__ == "__main__":
    main()
