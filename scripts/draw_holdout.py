"""Draw the fresh human holdout and render its blind labeling sheet — step 8e.

The census reference is machine-labeled, so the sampling study measures
sampling error with the classifier's own error riding silently on top. This
holdout is the measured bound on that silence (DESIGN, "The fresh-buy session
(step 8)"): 150 reviews — 60 census-corpus / 45 marked-window / 45 long-tail,
the fresh strata deliberately oversampled because out-of-distribution against
gold's popular-game 250 is exactly where the reference is newly trusted —
labeled by Arda under frozen codebook v2, scored later as review-level
agreement against the production labels.

The draw is seeded uniform within each stratum (the corpus stratum over the
census pool's review ids in sorted order, the fresh strata over the fetch
run's usable English reviews through the corpus reader — the same filters the
label buy saw). The sheet shuffles all 150 together and renders id + text
only — no machine labels, no game names, no stratum hints — mirroring the
gold workbook's blindness discipline and its mention-line format, which the
compile/score step will parse the same way. Stratum and game live only in
``sample.jsonl``, the scorer's key.

Artifacts land in ``eval/holdout/``: ``sample.jsonl`` (the machine record,
full text pinned), ``SHEET.md`` (Arda's editing surface), ``manifest.json``
(seed, strata, pools, provenance). The sheet refuses to overwrite: once
edited it is the single copy of the human pass.

Run from the repo root:
  uv run python scripts/draw_holdout.py
"""

from __future__ import annotations

import argparse
import json
import random
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from steamlens.corpus import read_reviews_file
from steamlens.dispatch.stamp import code_version, config_hash

DEFAULT_SEED: Final = 20260804
STRATA_TARGETS: Final = {"corpus": 60, "marked-window": 45, "long-tail": 45}

# The fetch run's role map (DESIGN's step-8 picks): which fresh files feed
# which stratum. The corpus stratum draws from the census pool instead.
MARKED_APP_IDS: Final = frozenset({49520, 449960, 292030})
LONGTAIL_APP_IDS: Final = frozenset({1918680, 1863430, 247000})


@dataclass(frozen=True, slots=True)
class HoldoutRow:
    """One drawn review: the scorer's key plus the text the sheet renders."""

    review_id: str
    app_id: int
    stratum: str
    text: str


def draw_corpus_stratum(db_path: Path, k: int, rng: random.Random) -> list[HoldoutRow]:
    """``k`` census-pool reviews, seeded uniform over sorted review ids.

    The pool is the ingested usable census (the supply the label buy priced);
    sorting before sampling makes the draw a pure function of the seed and
    the pool contents.
    """
    db = sqlite3.connect(db_path)
    try:
        rows = db.execute(
            "SELECT review_id, app_id, text FROM reviews ORDER BY review_id"
        ).fetchall()
    finally:
        db.close()
    picks = rng.sample(rows, k)
    return [HoldoutRow(r[0], int(r[1]), "corpus", r[2]) for r in picks]


def draw_fresh_stratum(
    run_dir: Path, app_ids: frozenset[int], stratum: str, k: int, rng: random.Random
) -> list[HoldoutRow]:
    """``k`` reviews seeded uniform over the stratum's pooled usable English.

    Reading through ``read_reviews_file`` applies exactly the filters the
    label buy saw, so every drawable review has a production label to agree
    or disagree with.
    """
    pool: list[HoldoutRow] = []
    for app_id in sorted(app_ids):
        result = read_reviews_file(run_dir / f"{app_id}_reviews.jsonl")
        pool.extend(
            HoldoutRow(r.review_id, app_id, stratum, r.text) for r in result.reviews
        )
    return rng.sample(pool, k)


def fence_for(text: str) -> str:
    """A backtick fence longer than any run inside ``text`` (the workbook rule)."""
    longest = 0
    run = 0
    for ch in text:
        run = run + 1 if ch == "`" else 0
        longest = max(longest, run)
    return "`" * max(3, longest + 1)


def render_sheet(rows: list[HoldoutRow], seed: int, drawn_on: str) -> str:
    """The blind labeling sheet — id + text only, workbook mention-line format."""
    head = (
        "# Fresh human holdout — labeling sheet\n\n"
        f"{len(rows)} reviews, drawn {drawn_on} (seed {seed}; strata and provenance in "
        "`manifest.json` — deliberately not shown per review: the pass is blind).\n"
        "Label each review under frozen codebook v2, the gold workbook rules:\n\n"
        "- Flip `- [ ] reviewed` to `- [x] reviewed` on every review you finish.\n"
        '- Mention line: `- aspect / sentiment / "verbatim evidence"` — evidence\n'
        "  COPY-PASTED from the text block (`\\n` for an in-span newline), or\n"
        "  `(no span)` when no usable span exists.\n"
        "- Zero mentions: the single line `Zero mentions.`\n"
        "- Skip: replace the mention lines with `SKIP: non_english` (should be\n"
        "  rare — the pool is English-filtered).\n\n"
        "---\n"
    )
    blocks: list[str] = [head]
    for position, row in enumerate(rows, start=1):
        fence = fence_for(row.text)
        blocks.append(
            f"\n## {position} · review {row.review_id}\n\n"
            f"- [ ] reviewed\n\n"
            f"{fence}text\n{row.text}\n{fence}\n"
        )
    return "".join(blocks)


def main() -> int:
    """Draw the strata, shuffle blind, persist the three artifacts."""
    parser = argparse.ArgumentParser(
        description="Draw the fresh human holdout (step 8e) and render its blind sheet."
    )
    parser.add_argument("--db", type=Path, default=Path("data/steamlens.sqlite3"),
                        help="the census pool database (the corpus stratum's frame)")
    parser.add_argument("--freshbuy-run", type=Path,
                        default=Path("data/freshbuy/freshbuy-20260803T110347Z-bccdb631"),
                        help="the fetch run whose JSONLs feed the fresh strata")
    parser.add_argument("--out", type=Path, default=Path("eval/holdout"))
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()

    sheet_path = args.out / "SHEET.md"
    if sheet_path.exists():
        raise SystemExit(
            f"{sheet_path} already exists — the edited sheet is the single copy "
            "of the human pass; delete it deliberately to re-draw"
        )

    rng = random.Random(args.seed)
    rows = [
        *draw_corpus_stratum(args.db, STRATA_TARGETS["corpus"], rng),
        *draw_fresh_stratum(args.freshbuy_run, MARKED_APP_IDS, "marked-window",
                            STRATA_TARGETS["marked-window"], rng),
        *draw_fresh_stratum(args.freshbuy_run, LONGTAIL_APP_IDS, "long-tail",
                            STRATA_TARGETS["long-tail"], rng),
    ]
    rng.shuffle(rows)

    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "sample.jsonl").open("w", encoding="utf-8") as out:
        for position, row in enumerate(rows, start=1):
            out.write(json.dumps({
                "position": position,
                "review_id": row.review_id,
                "app_id": row.app_id,
                "stratum": row.stratum,
                "text": row.text,
            }, ensure_ascii=False) + "\n")
    drawn_on = datetime.now(UTC).date().isoformat()
    sheet_path.write_text(render_sheet(rows, args.seed, drawn_on), encoding="utf-8")

    counts = {s: sum(1 for r in rows if r.stratum == s) for s in STRATA_TARGETS}
    manifest = {
        "drawn_at": drawn_on,
        "seed": args.seed,
        "code_version": code_version(),
        "config_hash": config_hash({
            "seed": args.seed,
            "targets": dict(STRATA_TARGETS),
            "db": str(args.db),
            "freshbuy_run": str(args.freshbuy_run),
        }),
        "strata": counts,
        "corpus_db": str(args.db),
        "freshbuy_run": args.freshbuy_run.name,
        "marked_app_ids": sorted(MARKED_APP_IDS),
        "longtail_app_ids": sorted(LONGTAIL_APP_IDS),
    }
    (args.out / "manifest.json").write_text(
        json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"drawn: {counts} -> {args.out} (sheet {len(rows)} reviews)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
