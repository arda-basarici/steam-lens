"""Draw a dry-run slice for the gold-instructions acceptance test.

The gold labeling instructions (``eval/gold/INSTRUCTIONS.md``) gate on dry
runs: Arda labels a few real reviews using only that document, and friction
found there is fixed before the real gold pass. The six B4 dev-slice reviews
were the originally planned material, but they became the doc's own worked
examples — labeling them would be reading the answer key — so dry runs draw
fresh reviews instead.

**Rounds and the convergence stopping rule.** The acceptance test repeats
until it stops producing rulings: a round that settles zero new rulings means
the doc has converged (proceed to the real draw); several mean another round.
Each round targets codebook regions earlier rounds left untested, carries its
own seed, and writes its own manifest to ``eval/gold/dry_run/round<N>/``; the
exclusion set grows monotonically — the dev slice plus every earlier round's
ids. ALL round manifests are gold-excluded (INSTRUCTIONS section 8): the
instructions get iterated — possibly revised — against every dry-run review.

Draw design, per round: one review per game, 200-2,000 chars — long enough to
carry aspect talk (a natural draw is ~half bare verdicts, which test nothing
the worked examples haven't), capped so the dry run isn't essay-grading. The
bound is a dry-run convenience only; the real gold draw takes the natural mix.

Usage: ``uv run python scripts/draw_gold_dry_run.py --round 2``. Refuses to
overwrite a round's existing manifest — each round is a one-shot record;
delete its directory deliberately to redraw.
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple

_REPO = Path(__file__).resolve().parents[1]
_CORPUS_DATA = _REPO.parent / "steam-reviews" / "data"
_DEV_SLICE = _REPO / "probes" / "captures" / "classify_pilot" / "dev_slice.json"
_OUT_DIR = _REPO / "eval" / "gold" / "dry_run"

_MIN_CHARS, _MAX_CHARS = 200, 2_000


class RoundSpec(NamedTuple):
    """One dry-run round: an arbitrary distinct seed and its target games (app_id -> name)."""

    seed: int
    games: dict[str, str]


# Games per round are chosen to exercise codebook regions earlier rounds (and
# the doc's worked examples) don't cover. Round 1: live-service netcode /
# narrative / vehicle sim. Round 2: competitive-F2P monetization+matchmaking /
# challenging indie difficulty+learning_curve / early-access-collapse
# developer_conduct. Round 3: MTX-saturated annual release (monetization /
# price_value) / challenging indie (difficulty / learning_curve — the region
# round 2's non-English skip vacated) / redemption arc (updates and
# developer_conduct in their positive register). Round 4: beloved indie
# (music / emotional_impact / story) / complex F2P (learning_curve /
# monetization) / survival multiplayer (community / cheating).
_ROUNDS: dict[int, RoundSpec] = {
    1: RoundSpec(
        seed=20260716,
        games={
            "553850": "Helldivers 2",
            "632470": "Disco Elysium",
            "227300": "Euro Truck Simulator 2",
        },
    ),
    2: RoundSpec(
        seed=20260717,
        games={
            "2357570": "Overwatch 2",
            "367520": "Hollow Knight",
            "1372880": "The Day Before",
        },
    ),
    3: RoundSpec(
        seed=20260718,
        games={
            "1919590": "NBA 2K23",
            "262060": "Darkest Dungeon",
            "275850": "No Man's Sky",
        },
    ),
    4: RoundSpec(
        seed=20260719,
        games={
            "391540": "Undertale",
            "238960": "Path of Exile",
            "252490": "Rust",
        },
    ),
}

_SHEET_HEADER = """\
# Gold instructions — dry-run acceptance test (round {round})

**Rules of the run.** Label the reviews below using `eval/gold/INSTRUCTIONS.md`
and nothing else — no pilot captures, no chat, no codebook TOML. Work top to
bottom; note the rough time per review. The friction notes are the point of
this exercise: every place you had to reread, guess, or wish the doc said
more is a finding, even if you resolved it yourself.

**Recording a mention** — one bullet per mention, in this shape:

    - `aspect_label` / sentiment / "verbatim evidence" (or: no usable span)

Evidence is **copy-pasted, never retyped** (a round-1 finding). A zero-mention
review gets the single line `Zero mentions.` instead.
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


def gold_excluded_ids() -> frozenset[str]:
    """Every review id disqualified from gold candidacy so far.

    The dev slice (prompt-iteration exposure) plus every existing dry-run
    round's manifest (instructions-iteration exposure). The gold draw script
    uses this same function as its exclusion source.
    """
    ids = set(json.loads(_DEV_SLICE.read_text(encoding="utf-8")))
    for manifest in sorted(_OUT_DIR.glob("round*/manifest.json")):
        ids.update(r["id"] for r in json.loads(manifest.read_text(encoding="utf-8"))["reviews"])
    return frozenset(ids)


def draw_one(
    app_id: str, game: str, rng: random.Random, excluded: frozenset[str]
) -> dict[str, str]:
    """Pick one eligible review from a game's corpus file, seeded-random.

    Eligible = English, text length within the dry-run window, id not already
    excluded. Returns ``{"id", "app_id", "game", "text"}``.
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
                    {"id": r["recommendationid"], "app_id": app_id, "game": game, "text": text}
                )
    if not pool:
        raise SystemExit(f"{path}: no eligible reviews (window {_MIN_CHARS}-{_MAX_CHARS} chars)")
    return rng.choice(pool)


def render_sheet(round_no: int, reviews: list[dict[str, str]]) -> str:
    """The labeling sheet Arda fills — verbatim texts, empty label + friction slots."""
    blocks = [_SHEET_HEADER.format(round=round_no)]
    for n, r in enumerate(reviews, start=1):
        blocks.append(_REVIEW_TEMPLATE.format(n=n, game=r["game"], rid=r["id"], text=r["text"]))
    blocks.append(
        "---\n\n## Overall\n\n(doc verdict: converged / needs fixes — and the fix list)\n"
    )
    return "\n".join(blocks)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--round", type=int, required=True, choices=sorted(_ROUNDS), help="round number to draw"
    )
    args = parser.parse_args()
    spec = _ROUNDS[args.round]

    out_dir = _OUT_DIR / f"round{args.round}"
    manifest_path = out_dir / "manifest.json"
    if manifest_path.exists():
        raise SystemExit(
            f"{manifest_path} exists — round {args.round} already drawn; delete its dir to redraw"
        )
    excluded = gold_excluded_ids()
    rng = random.Random(spec.seed)
    reviews = [draw_one(app_id, game, rng, excluded) for app_id, game in spec.games.items()]

    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "purpose": "dry-run slice for the gold-instructions acceptance test; ids are gold-excluded",
        "round": args.round,
        "drawn_at": datetime.now(UTC).isoformat(),
        "seed": spec.seed,
        "rule": (
            f"per game: one english review, {_MIN_CHARS}-{_MAX_CHARS} chars, "
            "dev-slice and earlier-round ids excluded"
        ),
        "corpus": str(_CORPUS_DATA),
        "instructions_version": "gold-instructions-v1",
        "reviews": [{k: r[k] for k in ("id", "app_id", "game")} for r in reviews],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "SHEET.md").write_text(render_sheet(args.round, reviews), encoding="utf-8")
    for r in reviews:
        print(f"drew {r['id']} ({r['game']}, {len(r['text'])} chars)")
    print(f"round {args.round} sheet + manifest written to {out_dir}")


if __name__ == "__main__":
    main()
