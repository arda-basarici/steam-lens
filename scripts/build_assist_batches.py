"""Build the game-stripped input batches for the gold assist pre-annotation run.

The assist stage (eval/gold/INSTRUCTIONS.md section 8) has a strong model
pre-annotate every primary gold review; Arda adjudicates. The assist annotator
is bound by the same evidence horizon as every other annotator (section 3,
round-3 ruling): labels are a function of (review text, codebook) only. This
script is where that horizon becomes structural rather than behavioral:

- **Game-stripped rows**: each batch line carries ``id`` and ``text`` and
  nothing else — no ``game``, no ``app_id``. The assist cannot leak what it
  is never shown.
- **Seeded cross-game shuffle**: the draw file groups each game's five
  primaries together; five same-game neighbors invite game inference from
  cross-review clues. One seeded shuffle of all 250 breaks the grouping
  while staying reproducible.
- **Primaries only**: reserves are pre-annotated on demand if a labeling-time
  skip consumes one — most never will be, and the assist run should not spend
  double for rows that never get labeled.

Writes ``eval/gold/assist/input/batch_NN.jsonl`` and
``eval/gold/assist/manifest.json`` (provenance: source draw, seed, batching,
model, contract versions — copied from the draw manifest so the two records
cannot drift apart). Refuses to overwrite an existing manifest: batch
composition is part of the assist run's provenance; delete the directory
deliberately to rebuild.
"""

from __future__ import annotations

import json
import random
from datetime import UTC, datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_DRAW_DIR = _REPO / "eval" / "gold" / "draw"
_OUT_DIR = _REPO / "eval" / "gold" / "assist"

_SEED = 20260721
_BATCH_SIZE = 10
_ASSIST_MODEL = "claude-sonnet-5"


def load_primaries() -> list[dict[str, str]]:
    """The draw's primary rows, game-stripped to ``{"id", "text"}``.

    The strip happens here, at the single point where draw data crosses into
    assist territory — everything downstream is clean by construction.
    """
    rows: list[dict[str, str]] = []
    with (_DRAW_DIR / "reviews.jsonl").open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r["slot"] == "primary":
                rows.append({"id": r["id"], "text": r["text"]})
    return rows


def main() -> None:
    manifest_path = _OUT_DIR / "manifest.json"
    if manifest_path.exists():
        raise SystemExit(
            f"{manifest_path} exists — batch composition is provenance; "
            "delete the assist directory deliberately to rebuild"
        )

    draw_manifest = json.loads((_DRAW_DIR / "manifest.json").read_text(encoding="utf-8"))
    rows = load_primaries()
    random.Random(_SEED).shuffle(rows)
    batches = [rows[i : i + _BATCH_SIZE] for i in range(0, len(rows), _BATCH_SIZE)]

    input_dir = _OUT_DIR / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    (_OUT_DIR / "raw").mkdir(exist_ok=True)
    for n, batch in enumerate(batches, start=1):
        with (input_dir / f"batch_{n:02d}.jsonl").open("w", encoding="utf-8") as f:
            for row in batch:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    manifest = {
        "purpose": (
            "game-stripped input batches for the assist pre-annotation run; "
            "raw model outputs land in raw/, one file per batch, never edited"
        ),
        "created_at": datetime.now(UTC).isoformat(),
        "seed": _SEED,
        "batch_size": _BATCH_SIZE,
        "batches": len(batches),
        "reviews": len(rows),
        "assist_model": _ASSIST_MODEL,
        "orchestration": (
            "one fresh (context-clean) Claude Code agent per batch; the exact "
            "delegation prompt is PROMPT.md in this directory"
        ),
        "source_draw": {
            "path": str(_DRAW_DIR),
            "drawn_at": draw_manifest["drawn_at"],
            "seed": draw_manifest["seed"],
        },
        "instructions_version": draw_manifest["instructions_version"],
        "ontology_version": draw_manifest["ontology_version"],
        "ontology_content_hash": draw_manifest["ontology_content_hash"],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {len(batches)} batches x {_BATCH_SIZE} ({len(rows)} reviews) to {input_dir}")


if __name__ == "__main__":
    main()
