"""Mint the census agreement sample — the reviews the judge re-labels for D2c's read.

Usage:
    uv run python probes/mint_census_sample.py

Calibration proved the judge reference-grade on gold's 250; this probe mints
the sample that carries that instrument out where gold doesn't reach: 1,000
census reviews whose production labels will be scored against the judge's
fresh labels (the judge-vs-production agreement read, DESIGN's D2c entries).

The frame is the census itself — every review holding a survey envelope under
production's versions triple — so the draw estimates census-level agreement.
It is a *review* frame on purpose: the judge's unit of work is a review and
the scorer's tallies are per-review; a mention frame would overweight
multi-mention reviews with no clean review-level interpretation. Zero-mention
reviews stay in — "both instruments say no aspects" is agreement worth
measuring, and the zero-mention slice needs them.

The draw is the misattribution sample's method on this frame: a seeded
systematic pass over the frame sorted by (app_id, review_id) — every k-th row
from a random start — making the step an implicit proportional-by-game
stratification, self-weighting, so the sampled agreement estimates the census
rate with no reweighting. No reserves: a judge refusal is a disclosed drop in
the scoring intersection, never a replacement (the design's refusal ruling).

Artifacts land in ``eval/agreement/``:

- ``sample.jsonl`` — one drawn review per line: identity, game, and the
  stored text's sha256. The text itself stays in the store (the judge
  dispatch reads it there); the hash pins exactly what was drawn, so the
  dispatch can refuse a store whose text has drifted from the minted frame.
- ``manifest.json`` — seed, rule, pool triple, frame size, per-game counts,
  the drawn zero-mention share.

The judge dispatch and the agreement scorer are later, separate steps — this
probe only mints.
"""

from __future__ import annotations

import hashlib
import json
import random
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "src"))

import sqlite3  # noqa: E402

from steamlens.contracts import ClassifierVersions  # noqa: E402
from steamlens.core.classify import PROMPT_VERSION  # noqa: E402
from steamlens.studies.label_corpus import MODEL_ID  # noqa: E402

_DB = _REPO / "data" / "steamlens.sqlite3"
_APP_NAMES = _REPO / "data" / "app_names.json"
_OUT_DIR = _REPO / "eval" / "agreement"
_SEED = 20260723
_N = 1_000
_VERSIONS = ClassifierVersions(
    model_version=MODEL_ID, prompt_version=PROMPT_VERSION, ontology_version="v2"
)
_RULE = (
    "systematic draw of 1,000 over the frame of census survey envelopes under the "
    "production versions triple, sorted by (app_id, review_id) — every k-th row from a "
    "seeded random start (implicit proportional-by-game stratification, self-weighting); "
    "no reserves — a judge refusal is a disclosed drop from the scoring intersection, "
    "never a replacement"
)


@dataclass(frozen=True)
class SampledReview:
    """One drawn review: identity plus the pins the dispatch re-verifies."""

    review_id: str
    app_id: int
    game: str
    empty_envelope: bool
    text_sha256: str


def load_frame(conn: sqlite3.Connection) -> list[tuple[str, int, bool]]:
    """The full frame as ``(review_id, app_id, empty_envelope)``, in draw order."""
    cursor = conn.execute(
        "SELECT c.review_id, r.app_id,"
        " NOT EXISTS (SELECT 1 FROM mentions m WHERE m.classification_id = c.id)"
        " FROM classifications c JOIN reviews r ON r.review_id = c.review_id"
        " WHERE c.origin = 'survey' AND c.model_version = ? AND c.prompt_version = ?"
        " AND c.ontology_version = ?"
        " ORDER BY r.app_id, c.review_id",
        (_VERSIONS.model_version, _VERSIONS.prompt_version, _VERSIONS.ontology_version),
    )
    return [(str(row[0]), int(row[1]), bool(row[2])) for row in cursor]


def systematic_draw[T](frame: list[T], n: int, rng: random.Random) -> list[T]:
    """Every k-th row from a random start — equal-probability over the sorted frame."""
    step = len(frame) / n
    start = rng.uniform(0, step)
    return [frame[int(start + i * step)] for i in range(n)]


def text_hashes(conn: sqlite3.Connection, review_ids: list[str]) -> dict[str, str]:
    """Each drawn review's stored text, pinned as sha256 over its UTF-8 bytes."""
    hashes: dict[str, str] = {}
    for review_id in review_ids:
        row = conn.execute(
            "SELECT text FROM reviews WHERE review_id = ?", (review_id,)
        ).fetchone()
        if row is None:
            raise SystemExit(f"drawn review {review_id} vanished from the store")
        hashes[review_id] = hashlib.sha256(str(row[0]).encode("utf-8")).hexdigest()
    return hashes


def per_game_counts(sample: list[SampledReview]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for review in sample:
        counts[review.game] = counts.get(review.game, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def main() -> None:
    names = (
        {str(k): str(v) for k, v in json.loads(_APP_NAMES.read_text(encoding="utf-8")).items()}
        if _APP_NAMES.exists()
        else {}
    )
    conn = sqlite3.connect(f"file:{_DB.as_posix()}?mode=ro", uri=True)
    try:
        frame = load_frame(conn)
        drawn = systematic_draw(frame, _N, random.Random(_SEED))
        hashes = text_hashes(conn, [review_id for review_id, _, _ in drawn])
    finally:
        conn.close()

    sample = [
        SampledReview(
            review_id=review_id,
            app_id=app_id,
            game=names.get(str(app_id), str(app_id)),
            empty_envelope=empty,
            text_sha256=hashes[review_id],
        )
        for review_id, app_id, empty in drawn
    ]

    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (_OUT_DIR / "sample.jsonl").open("w", encoding="utf-8") as f:
        for i, review in enumerate(sample, start=1):
            f.write(json.dumps({"item": i} | asdict(review)) + "\n")

    zero_share = sum(r.empty_envelope for r in sample) / len(sample)
    manifest = {
        "purpose": (
            "the census agreement sample: 1,000 reviews whose production labels the "
            "calibrated judge re-labels fresh; scored judge-vs-production, journaled "
            "as a pool-labels-reference eval run"
        ),
        "drawn_at": datetime.now(UTC).isoformat(),
        "seed": _SEED,
        "rule": _RULE,
        "db": str(_DB),
        "pool": {
            "origin": "survey",
            "model_version": _VERSIONS.model_version,
            "prompt_version": _VERSIONS.prompt_version,
            "ontology_version": _VERSIONS.ontology_version,
        },
        "frame_size": len(frame),
        "n": _N,
        "drawn_empty_envelope_share": zero_share,
        "per_game_counts": per_game_counts(sample),
    }
    (_OUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"frame: {len(frame):,} census envelopes under {_VERSIONS.model_version}")
    print(f"drawn: {_N} reviews (seed {_SEED})")
    print(f"games covered: {len(per_game_counts(sample))}")
    print(f"drawn empty-envelope share: {zero_share:.3f}")
    print(f"written -> {_OUT_DIR.relative_to(_REPO)}")


if __name__ == "__main__":
    main()
