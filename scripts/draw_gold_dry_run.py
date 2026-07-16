"""Draw the dry-run slice for the gold-instructions acceptance test.

The gold labeling instructions (``eval/gold/INSTRUCTIONS.md``) gate on a dry
run: Arda labels a few real reviews using only that document, and friction
found there is fixed before the real gold pass. The six B4 dev-slice reviews
were the planned material, but they became the doc's own worked examples —
labeling them would be reading the answer key — so the dry run draws fresh
reviews instead.

Draw design, and why:

- **Three games outside the worked-example pair** (Stardew Valley, Cyberpunk
  2077 teach in the doc), chosen to exercise codebook regions the examples do
  not cover: a live-service shooter (servers/matchmaking/monetization talk), a
  narrative RPG (story/writing/characters), and a vehicle sim
  (realism/relaxation/dlc).
- **One review per game, 200-2,000 chars** — long enough to carry aspect talk
  (a natural draw is ~half bare verdicts, which test nothing the worked
  examples haven't), capped so the dry run isn't essay-grading. The bound is a
  dry-run convenience only; the real gold draw takes the natural mix.
- **Seeded and manifest-recorded** — the drawn ids are excluded from future
  gold candidacy for the same reason the dev slice is: the instructions get
  iterated (possibly revised) against them. The gold draw script reads this
  manifest alongside ``dev_slice.json``.

Writes ``eval/gold/dry_run/manifest.json`` and ``eval/gold/dry_run/SHEET.md``
(the sheet Arda fills). Refuses to overwrite an existing manifest — the dry
run is a one-shot record; delete the directory deliberately to redraw.
"""

from __future__ import annotations

import json
import random
from datetime import UTC, datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_CORPUS_DATA = _REPO.parent / "steam-reviews" / "data"
_DEV_SLICE = _REPO / "probes" / "captures" / "classify_pilot" / "dev_slice.json"
_OUT_DIR = _REPO / "eval" / "gold" / "dry_run"

_SEED = 20260716
_MIN_CHARS, _MAX_CHARS = 200, 2_000
# Codebook regions the doc's worked examples don't cover (see module docstring).
_GAMES = {
    "553850": "Helldivers 2",
    "632470": "Disco Elysium",
    "227300": "Euro Truck Simulator 2",
}

_SHEET_HEADER = """\
# Gold instructions — dry-run acceptance test

**Rules of the run.** Label the reviews below using `eval/gold/INSTRUCTIONS.md`
and nothing else — no pilot captures, no chat, no codebook TOML. Work top to
bottom; note the rough time per review. The friction notes are the point of
this exercise: every place you had to reread, guess, or wish the doc said
more is a finding, even if you resolved it yourself.

**Recording a mention** — one bullet per mention, in this shape:

    - `aspect_label` / sentiment / "verbatim evidence" (or: no usable span)

A zero-mention review gets the single line `Zero mentions.` instead.
"""

_REVIEW_TEMPLATE = """\
---

## Review {n} — {game} (review id `{rid}`)

```text
{text}
```

### Labels

(your mention bullets here)

### Friction notes

(rereads, guesses, doc gaps — or "none")
"""


def draw_one(app_id: str, rng: random.Random, excluded: frozenset[str]) -> dict[str, str]:
    """Pick one eligible review from a game's corpus file, seeded-random.

    Eligible = English, text length within the dry-run window, id not already
    excluded (dev slice). Returns ``{"id", "app_id", "game", "text"}``.
    """
    path = _CORPUS_DATA / "raw" / "reviews" / f"{app_id}_reviews.jsonl"
    pool: list[dict[str, str]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            text = (r.get("review") or "").strip()
            if (
                r.get("language") == "english"
                and _MIN_CHARS <= len(text) <= _MAX_CHARS
                and r["recommendationid"] not in excluded
            ):
                pool.append(
                    {
                        "id": r["recommendationid"],
                        "app_id": app_id,
                        "game": _GAMES[app_id],
                        "text": text,
                    }
                )
    if not pool:
        raise SystemExit(f"{path}: no eligible reviews (window {_MIN_CHARS}-{_MAX_CHARS} chars)")
    return rng.choice(pool)


def render_sheet(reviews: list[dict[str, str]]) -> str:
    """The labeling sheet Arda fills — verbatim texts, empty label + friction slots."""
    blocks = [_SHEET_HEADER]
    for n, r in enumerate(reviews, start=1):
        blocks.append(_REVIEW_TEMPLATE.format(n=n, game=r["game"], rid=r["id"], text=r["text"]))
    blocks.append("---\n\n## Overall\n\n(doc verdict: ready / needs fixes — and the fix list)\n")
    return "\n".join(blocks)


def main() -> None:
    manifest_path = _OUT_DIR / "manifest.json"
    if manifest_path.exists():
        raise SystemExit(
            f"{manifest_path} exists — the dry run is already drawn; delete deliberately to redraw"
        )
    excluded = frozenset(json.loads(_DEV_SLICE.read_text(encoding="utf-8")))
    rng = random.Random(_SEED)
    reviews = [draw_one(app_id, rng, excluded) for app_id in _GAMES]

    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {
        "purpose": "dry-run slice for the gold-instructions acceptance test; ids are gold-excluded",
        "drawn_at": datetime.now(UTC).isoformat(),
        "seed": _SEED,
        "rule": (
            f"per game: one english review, {_MIN_CHARS}-{_MAX_CHARS} chars, dev-slice ids excluded"
        ),
        "corpus": str(_CORPUS_DATA),
        "instructions_version": "gold-instructions-v1",
        "reviews": [{k: r[k] for k in ("id", "app_id", "game")} for r in reviews],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    (_OUT_DIR / "SHEET.md").write_text(render_sheet(reviews), encoding="utf-8")
    for r in reviews:
        print(f"drew {r['id']} ({r['game']}, {len(r['text'])} chars)")
    print(f"sheet + manifest written to {_OUT_DIR}")


if __name__ == "__main__":
    main()
