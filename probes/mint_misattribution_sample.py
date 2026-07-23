"""Mint the misattribution audit sample — the human half of D2b's evidence story.

Usage:
    uv run python probes/mint_misattribution_sample.py

The mechanical audit verified every stored quote is verbatim; what it cannot
see is a real quote read upside-down — attached to the wrong aspect, or to a
sentiment the quote doesn't carry. That read is human work, and this probe
mints the sample it runs on: 100 primary claims (+10 ordered reserves) drawn
from the census's evidence-carrying mentions.

The draw is a seeded systematic pass over the frame sorted by (game, aspect,
sentiment, review, mention): every k-th row from a random start. Sorting
first makes the systematic step an implicit proportional stratification
across all three dimensions at once — self-weighting, so the audited rate
estimates the population rate with no reweighting. A seeded shuffle of the
110 drawn rows assigns the primary/reserve split, so reserves aren't biased
toward the tail of the sort order.

Artifacts land in ``eval/audits/misattribution/``:

- ``sample.jsonl`` — the machine record, one claim per line, full review text.
- ``SHEET.md`` — the audit sheet Arda fills: quote highlighted in its review,
  two verdicts per claim (aspect supported? sentiment supported?) plus a note.
- ``manifest.json`` — seed, rule, pool triple, frame size, stratum counts.

The verdict scorer (rate + CI, journaled as an eval run) is a later, separate
step — this probe only mints.
"""

from __future__ import annotations

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
_OUT_DIR = _REPO / "eval" / "audits" / "misattribution"
_SEED = 20260723
_N_PRIMARY = 100
_N_RESERVE = 10
_VERSIONS = ClassifierVersions(
    model_version=MODEL_ID, prompt_version=PROMPT_VERSION, ontology_version="v2"
)
_RULE = (
    "systematic draw of 110 over the frame of evidence-carrying census mentions sorted by "
    "(app_id, aspect, sentiment, review_id, mention_id) — every k-th row from a seeded "
    "random start (implicit proportional stratification, self-weighting); a seeded shuffle "
    "of the 110 assigns 100 primary + 10 ordered reserve; a skip consumes the next unused "
    "reserve and is logged here"
)


@dataclass(frozen=True)
class Claim:
    """One auditable claim: an (aspect, sentiment, quote) triple in its review."""

    mention_id: int
    review_id: str
    app_id: int
    game: str
    aspect: str
    slot: str
    sentiment: str
    evidence: str
    text: str


def load_frame(conn: sqlite3.Connection, names: dict[str, str]) -> list[Claim]:
    """The full sampling frame, in the sort order the systematic draw walks."""
    cursor = conn.execute(
        "SELECT m.id, c.review_id, r.app_id, m.aspect, m.slot, m.sentiment, m.evidence, r.text"
        " FROM mentions m"
        " JOIN classifications c ON c.id = m.classification_id"
        " JOIN reviews r ON r.review_id = c.review_id"
        " WHERE m.evidence IS NOT NULL"
        " AND c.origin = 'survey' AND c.model_version = ? AND c.prompt_version = ?"
        " AND c.ontology_version = ?"
        " ORDER BY r.app_id, m.aspect, m.sentiment, c.review_id, m.id",
        (_VERSIONS.model_version, _VERSIONS.prompt_version, _VERSIONS.ontology_version),
    )
    return [
        Claim(
            mention_id=int(row[0]),
            review_id=str(row[1]),
            app_id=int(row[2]),
            game=names.get(str(row[2]), str(row[2])),
            aspect=str(row[3]),
            slot=str(row[4]),
            sentiment=str(row[5]),
            evidence=str(row[6]),
            text=str(row[7]),
        )
        for row in cursor
    ]


def systematic_draw(frame: list[Claim], n: int, rng: random.Random) -> list[Claim]:
    """Every k-th row from a random start — equal-probability over the sorted frame."""
    step = len(frame) / n
    start = rng.uniform(0, step)
    return [frame[int(start + i * step)] for i in range(n)]


def highlight(text: str, evidence: str) -> str:
    """Mark the quote's first occurrence in its review with visible brackets."""
    at = text.find(evidence)
    return text[:at] + "⟦" + evidence + "⟧" + text[at + len(evidence) :]


def render_sheet(primary: list[Claim]) -> str:
    """The audit sheet: one section per claim, verdict lines left blank to fill."""
    lines = [
        "# Misattribution audit sheet",
        "",
        f"100 claims, drawn {datetime.now(UTC).date().isoformat()} (seed {_SEED}; draw rule "
        "in `manifest.json`). Per claim, judge the ⟦bracketed⟧ quote **in its review's "
        "context** and fill the two verdicts with `yes` / `no` / `unclear`:",
        "",
        "- **aspect_supported** — does the quote actually talk about the claimed aspect?",
        "- **sentiment_supported** — does the quote carry the claimed sentiment toward it "
        "(sarcasm and context count)?",
        "",
        "The two are independent: a quote can name the right aspect with the wrong "
        "sentiment, and vice versa. `note:` is free text, optional.",
        "",
    ]
    for i, claim in enumerate(primary, start=1):
        lines += [
            "---",
            "",
            f"## {i:03d} · {claim.game} — **{claim.aspect}** ({claim.slot}), "
            f"sentiment **{claim.sentiment}**",
            "",
            f"review `{claim.review_id}` · mention `{claim.mention_id}`",
            "",
        ]
        lines += ["> " + line for line in highlight(claim.text, claim.evidence).splitlines()]
        lines += [
            "",
            "- aspect_supported:",
            "- sentiment_supported:",
            "- note:",
            "",
        ]
    return "\n".join(lines) + "\n"


def stratum_counts(claims: list[Claim]) -> dict[str, dict[str, int]]:
    sentiments: dict[str, int] = {}
    slots: dict[str, int] = {}
    for claim in claims:
        sentiments[claim.sentiment] = sentiments.get(claim.sentiment, 0) + 1
        slots[claim.slot] = slots.get(claim.slot, 0) + 1
    return {"sentiment": sentiments, "slot": slots}


def main() -> None:
    names = (
        {str(k): str(v) for k, v in json.loads(_APP_NAMES.read_text(encoding="utf-8")).items()}
        if _APP_NAMES.exists()
        else {}
    )
    conn = sqlite3.connect(f"file:{_DB.as_posix()}?mode=ro", uri=True)
    try:
        frame = load_frame(conn, names)
    finally:
        conn.close()

    rng = random.Random(_SEED)
    drawn = systematic_draw(frame, _N_PRIMARY + _N_RESERVE, rng)
    shuffled = list(drawn)
    rng.shuffle(shuffled)
    primary, reserve = shuffled[:_N_PRIMARY], shuffled[_N_PRIMARY:]

    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (_OUT_DIR / "sample.jsonl").open("w", encoding="utf-8") as f:
        for role, claims in (("primary", primary), ("reserve", reserve)):
            for i, claim in enumerate(claims, start=1):
                f.write(json.dumps({"item": i, "role": role} | asdict(claim)) + "\n")
    (_OUT_DIR / "SHEET.md").write_text(render_sheet(primary), encoding="utf-8")

    manifest = {
        "purpose": (
            "the misattribution audit sample: 100 primary claims for the human read the "
            "mechanical evidence audit cannot make — a verbatim quote attached to the wrong "
            "aspect or sentiment; a skip consumes the next unused reserve and is logged here"
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
        "totals": {"primary": _N_PRIMARY, "reserve": _N_RESERVE},
        "sample_strata": stratum_counts(primary),
        "skips": [],
        "primary_mention_ids": [c.mention_id for c in primary],
        "reserve_mention_ids": [c.mention_id for c in reserve],
    }
    (_OUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )

    counts = stratum_counts(primary)
    games = len({c.app_id for c in primary})
    aspects = len({c.aspect for c in primary})
    print(f"frame: {len(frame):,} evidence-carrying census mentions")
    print(f"drawn: {_N_PRIMARY} primary + {_N_RESERVE} reserve (seed {_SEED})")
    print(f"primary spread: {games} games, {aspects} distinct aspects")
    print(f"  sentiment: {counts['sentiment']}")
    print(f"  slot:      {counts['slot']}")
    print(f"written -> {_OUT_DIR.relative_to(_REPO)}\\")


if __name__ == "__main__":
    main()
