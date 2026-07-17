"""Parse the edited gold workbook, verify it, and report adjudication state.

The read half of the workbook loop (render_gold_workbook.py is the write
half). Default mode is **check**: parse every sheet, enforce the structural
grammar, re-verify evidence verbatim against the review texts (Arda's edits
included — human transfer is where spans drift), and diff the current state
against the immutable ``assist/raw/`` files to report progress and the
assist-vs-final disagreement stats that INSTRUCTIONS section 8 wants measured.

``--mint`` additionally writes the final gold set — refused until every
review is checked off, every violation cleared, and every skip's
replacement (the top-up batch) is adjudicated. Minting writes three
artifacts: ``eval/gold/gold.jsonl`` (self-contained records — text and
full provenance per row, per the section-8 storage ruling),
``eval/gold/gold_manifest.json`` (counts, the assist-disagreement profile
including the disposition-vs-intrinsic sentiment-flip contrast feeding the
v2 two-category decision, skip log), and the draw manifest's ``skips``
list (cause + replacement per skip, closing the loop the draw opened).

Per-review grammar (everything else in a block is a violation, printed loud):

- ``- [ ] reviewed`` / ``- [x] reviewed`` — exactly one per review;
- one of: mention lines / ``Zero mentions.`` / ``SKIP: non_english``;
- mention line ``- aspect / sentiment / "evidence"`` (or ``(no span)``);
  ``\\n``/``\\r`` in evidence unescape before the verbatim check;
- ``> ...`` blockquote lines are ignored (assist notes/flags).
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_ASSIST_DIR = _REPO / "eval" / "gold" / "assist"
_WORKBOOK_DIR = _REPO / "eval" / "gold" / "workbook"

_SENTIMENTS = {"positive", "negative", "mixed", "neutral"}
_HEADER_RE = re.compile(r"^## \d+ · review (\S+)$")
_CHECKBOX_RE = re.compile(r"^- \[( |x)\] reviewed$")
_FENCE_OPEN_RE = re.compile(r"^(`{3,})text$")
_SKIP_RE = re.compile(r"^SKIP: (non_english|empty_text)\.?$")


@dataclass
class ReviewState:
    """One review block as parsed from a workbook sheet."""

    review_id: str
    reviewed: bool = False
    zero: bool = False
    skip: str | None = None
    mentions: list[dict[str, str | None]] = field(default_factory=list)


def _unescape_evidence(shown: str) -> str:
    return shown.replace("\\n", "\n").replace("\\r", "\r")


def _parse_mention_line(line: str) -> dict[str, str | None] | None:
    """``- aspect / sentiment / "evidence"`` -> mention dict, or None if malformed."""
    parts = line[2:].split(" / ", 2)
    if len(parts) != 3:
        return None
    aspect, sentiment, shown = (p.strip() for p in parts)
    if shown == "(no span)":
        evidence: str | None = None
    else:
        first, last = shown.find('"'), shown.rfind('"')
        if first == -1 or last <= first:
            return None
        evidence = _unescape_evidence(shown[first + 1 : last])
    return {"aspect": aspect, "sentiment": sentiment, "evidence": evidence}


def parse_sheet(path: Path) -> tuple[list[ReviewState], list[str]]:
    """Parse one workbook sheet into review states + grammar violations."""
    violations: list[str] = []
    reviews: list[ReviewState] = []
    current: ReviewState | None = None
    fence: str | None = None
    in_preamble = True

    for lineno, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        where = f"{path.name}:{lineno}"
        # Hand-editing leaves stray indentation; the grammar is line-shaped,
        # so classification ignores leading/trailing whitespace. Text inside
        # fences is untouched — only the fence delimiters themselves strip.
        line = raw_line.strip()
        if fence is not None:  # inside a review's text block
            if line == fence:
                fence = None
            continue
        header = _HEADER_RE.match(line)
        if header:
            in_preamble = False
            current = ReviewState(review_id=header.group(1))
            reviews.append(current)
            continue
        if in_preamble or current is None:
            continue
        if not line or line.startswith(">"):
            continue
        opened = _FENCE_OPEN_RE.match(line)
        if opened:
            fence = opened.group(1)
            continue
        checkbox = _CHECKBOX_RE.match(line)
        if checkbox:
            current.reviewed = checkbox.group(1) == "x"
            continue
        if line == "Zero mentions.":
            current.zero = True
            continue
        skip = _SKIP_RE.match(line)
        if skip:
            current.skip = skip.group(1)
            continue
        if line.startswith("- "):
            mention = _parse_mention_line(line)
            if mention is None:
                violations.append(f"{where}: malformed mention line: {line!r}")
            else:
                current.mentions.append(mention)
            continue
        violations.append(f"{where}: unparseable line: {line!r}")

    if fence is not None:
        violations.append(f"{path.name}: unterminated text fence")
    return reviews, violations


def verify_reviews(
    reviews: list[ReviewState], texts: dict[str, str], sheet: str
) -> list[str]:
    """Structural + verbatim checks over parsed review states."""
    violations: list[str] = []
    for r in reviews:
        where = f"{sheet} review {r.review_id}"
        if r.review_id not in texts:
            violations.append(f"{where}: unknown review id")
            continue
        states = [bool(r.mentions), r.zero, r.skip is not None]
        if sum(states) != 1:
            violations.append(
                f"{where}: needs exactly one of mentions / 'Zero mentions.' / SKIP "
                f"(has mentions={bool(r.mentions)}, zero={r.zero}, skip={r.skip})"
            )
        for m in r.mentions:
            if m["sentiment"] not in _SENTIMENTS:
                violations.append(f"{where}: bad sentiment {m['sentiment']!r}")
            if not m["aspect"]:
                violations.append(f"{where}: empty aspect")
            evidence = m["evidence"]
            if evidence is not None and evidence not in texts[r.review_id]:
                violations.append(
                    f"{where} [{m['aspect']}]: evidence not a verbatim substring: {evidence!r}"
                )
    return violations


def diff_against_raw(
    reviews: list[ReviewState], raw_annotations: dict[str, dict[str, object]]
) -> tuple[dict[str, int], list[dict[str, str]]]:
    """Assist-vs-current mention diff: accepted / modified / added / deleted.

    Exact (aspect, sentiment, evidence) matches count accepted; a same-aspect
    survivor with edits counts modified — and when the edit flipped the
    sentiment, the flip is recorded (aspect, from, to) for the
    disposition-vs-intrinsic contrast. Coarse by design — the free
    difficulty estimate, not a certified metric.
    """
    counts = {"accepted": 0, "modified": 0, "added": 0, "deleted": 0}
    flips: list[dict[str, str]] = []
    for r in reviews:
        if r.skip:  # exclusion from gold, not a labeling disagreement
            continue
        raw = raw_annotations.get(r.review_id, {})
        raw_mentions = [dict(m) for m in raw.get("mentions", [])]  # type: ignore[union-attr]
        current = list(r.mentions)
        for m in list(current):
            if m in raw_mentions:
                raw_mentions.remove(m)
                current.remove(m)
                counts["accepted"] += 1
        for m in list(current):
            twin = next((x for x in raw_mentions if x["aspect"] == m["aspect"]), None)
            if twin is not None:
                raw_mentions.remove(twin)
                current.remove(m)
                counts["modified"] += 1
                if twin["sentiment"] != m["sentiment"]:
                    flips.append(
                        {
                            "aspect": str(m["aspect"]),
                            "from": str(twin["sentiment"]),
                            "to": str(m["sentiment"]),
                        }
                    )
        counts["deleted"] += len(raw_mentions)
        counts["added"] += len(current)
    return counts, flips


_DISPOSITION_PINS = frozenset(
    {"addictiveness", "relaxation", "emotional_impact", "difficulty", "learning_curve"}
)


def _mint(
    reviews_by_id: dict[str, ReviewState],
    texts_by_id: dict[str, str],
    diff_totals: dict[str, int],
    flips: list[dict[str, str]],
) -> None:
    """Write gold.jsonl + gold manifest and log skips into the draw manifest.

    Every record is self-contained (text + full provenance per row — the
    section-8 storage ruling: evals run in CI, which never sees the corpus).
    """
    from datetime import date

    from steamlens.ontology import load_ontology

    draw_manifest_path = _REPO / "eval" / "gold" / "draw" / "manifest.json"
    draw_manifest = json.loads(draw_manifest_path.read_text(encoding="utf-8"))
    draw_rows = {
        json.loads(line)["id"]: json.loads(line)
        for line in (_REPO / "eval" / "gold" / "draw" / "reviews.jsonl").open(encoding="utf-8")
    }
    assist_manifest = json.loads((_ASSIST_DIR / "manifest.json").read_text(encoding="utf-8"))
    replacements: dict[str, str] = assist_manifest["top_up"]["replacements"]

    unreviewed = [r.review_id for r in reviews_by_id.values() if not r.reviewed]
    if unreviewed:
        raise SystemExit(f"mint refused: {len(unreviewed)} unreviewed reviews: {unreviewed[:5]}")
    for skip_id, repl_id in replacements.items():
        repl = reviews_by_id.get(repl_id)
        if repl is None or not repl.reviewed or repl.skip:
            raise SystemExit(
                f"mint refused: replacement {repl_id} for skip {skip_id} is missing, "
                "unreviewed, or itself skipped"
            )

    constants = {
        "instructions_version": draw_manifest["instructions_version"],
        "ontology_version": draw_manifest["ontology_version"],
        "ontology_content_hash": draw_manifest["ontology_content_hash"],
        "annotator": "Arda",
        "assist_model": assist_manifest["assist_model"],
        "labeled_at": str(date.today()),
    }

    records = []
    for r in reviews_by_id.values():
        if r.skip:
            continue
        records.append(
            {
                "review_id": r.review_id,
                "app_id": draw_rows[r.review_id]["app_id"],
                "text": texts_by_id[r.review_id],
                "mentions": r.mentions,
                **constants,
            }
        )
    records.sort(key=lambda x: (x["app_id"], x["review_id"]))

    pinned = frozenset(a.label for a in load_ontology().aspects)
    n_mentions = sum(len(x["mentions"]) for x in records)
    n_zero = sum(1 for x in records if not x["mentions"])
    candidates = sorted(
        {m["aspect"] for x in records for m in x["mentions"] if m["aspect"] not in pinned}
    )
    sentiments: dict[str, int] = {}
    class_mentions = {"disposition": 0, "intrinsic": 0}
    for x in records:
        for m in x["mentions"]:
            sentiments[m["sentiment"]] = sentiments.get(m["sentiment"], 0) + 1
            cls = "disposition" if m["aspect"] in _DISPOSITION_PINS else "intrinsic"
            class_mentions[cls] += 1
    flip_contrast = {
        "disposition": [f for f in flips if f["aspect"] in _DISPOSITION_PINS],
        "intrinsic": [f for f in flips if f["aspect"] not in _DISPOSITION_PINS],
    }

    gold_path = _REPO / "eval" / "gold" / "gold.jsonl"
    with gold_path.open("w", encoding="utf-8", newline="\n") as f:
        for x in records:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")

    skip_log = [
        {
            "review_id": sid,
            "cause": next(
                r.skip for r in reviews_by_id.values() if r.review_id == sid
            ),
            "replacement_id": rid,
        }
        for sid, rid in replacements.items()
    ]
    manifest = {
        "purpose": "the certified gold set: Arda-adjudicated labels over the draw's "
        "primary slice with skip replacements from the ordered reserve",
        "minted_at": constants["labeled_at"],
        **{k: constants[k] for k in ("instructions_version", "ontology_version",
                                     "ontology_content_hash", "annotator", "assist_model")},
        "records": len(records),
        "mentions": n_mentions,
        "zero_mention": n_zero,
        "zero_share": round(n_zero / len(records), 3),
        "sentiments": sentiments,
        "candidate_labels": candidates,
        "skips": skip_log,
        "assist_disagreement": {
            **diff_totals,
            "sentiment_flips": flips,
            "flip_contrast": {
                "note": "disposition pins per the dispositional-family report note "
                "(2026-07-17); feeds the v2 two-category decision",
                "disposition_flips": len(flip_contrast["disposition"]),
                "disposition_mentions": class_mentions["disposition"],
                "intrinsic_flips": len(flip_contrast["intrinsic"]),
                "intrinsic_mentions": class_mentions["intrinsic"],
            },
        },
    }
    (_REPO / "eval" / "gold" / "gold_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8", newline="\n"
    )
    draw_manifest["skips"] = skip_log
    draw_manifest_path.write_text(
        json.dumps(draw_manifest, indent=2, ensure_ascii=False), encoding="utf-8", newline="\n"
    )

    d, i = manifest["assist_disagreement"]["flip_contrast"], None
    print(f"\nMINTED: {len(records)} records -> {gold_path}")
    print(
        f"  {n_mentions} mentions, zero-share {manifest['zero_share']:.1%}, "
        f"{len(candidates)} candidate labels, sentiments {sentiments}"
    )
    print(
        f"  flip contrast: disposition {d['disposition_flips']}/{d['disposition_mentions']} "
        f"vs intrinsic {d['intrinsic_flips']}/{d['intrinsic_mentions']}"
    )
    print(f"  skips logged to draw manifest: {[s['review_id'] for s in skip_log]}")


def main() -> None:
    sheets = sorted(_WORKBOOK_DIR.glob("batch_*.md"))
    if not sheets:
        raise SystemExit(f"no sheets in {_WORKBOOK_DIR} — render the workbook first")

    all_violations: list[str] = []
    totals = {"reviews": 0, "reviewed": 0, "mentions": 0, "skips": 0}
    diff_totals = {"accepted": 0, "modified": 0, "added": 0, "deleted": 0}
    all_flips: list[dict[str, str]] = []
    reviews_by_id: dict[str, ReviewState] = {}
    texts_by_id: dict[str, str] = {}
    print(
        f"{'sheet':>8} {'reviewed':>9} {'mentions':>9} {'skip':>5} "
        f"{'accept':>7} {'modify':>7} {'add':>4} {'del':>4}"
    )
    for sheet in sheets:
        n = int(sheet.stem.split("_")[1])
        with (_ASSIST_DIR / "input" / f"batch_{n:02d}.jsonl").open(encoding="utf-8") as f:
            texts = {r["id"]: r["text"] for r in map(json.loads, f)}
        raw = json.loads(
            (_ASSIST_DIR / "raw" / f"batch_{n:02d}.json").read_text(encoding="utf-8")
        )
        raw_annotations = {a["id"]: a for a in raw["annotations"]}

        reviews, violations = parse_sheet(sheet)
        violations += verify_reviews(reviews, texts, sheet.name)
        if {r.review_id for r in reviews} != set(texts):
            violations.append(f"{sheet.name}: review coverage mismatch vs input batch")
        diff, flips = diff_against_raw(reviews, raw_annotations)

        all_violations += violations
        all_flips += flips
        for r in reviews:
            reviews_by_id[r.review_id] = r
        texts_by_id.update(texts)
        totals["reviews"] += len(reviews)
        totals["reviewed"] += sum(r.reviewed for r in reviews)
        totals["mentions"] += sum(len(r.mentions) for r in reviews)
        totals["skips"] += sum(1 for r in reviews if r.skip)
        for k in diff_totals:
            diff_totals[k] += diff[k]
        print(
            f"{n:>8} {sum(r.reviewed for r in reviews):>6}/{len(reviews):<2} "
            f"{sum(len(r.mentions) for r in reviews):>9} "
            f"{sum(1 for r in reviews if r.skip):>5} "
            f"{diff['accepted']:>7} {diff['modified']:>7} {diff['added']:>4} {diff['deleted']:>4}"
        )

    print(
        f"\ntotal: {totals['reviewed']}/{totals['reviews']} reviewed, "
        f"{totals['mentions']} mentions, {totals['skips']} skips | "
        f"vs assist: {diff_totals['accepted']} accepted, {diff_totals['modified']} modified, "
        f"{diff_totals['added']} added, {diff_totals['deleted']} deleted"
    )
    if all_violations:
        print(f"\n{len(all_violations)} VIOLATION(S):")
        for v in all_violations:
            print(f"  !! {v}")
        raise SystemExit(1)
    print("all checks passed")
    if "--mint" in sys.argv:
        _mint(reviews_by_id, texts_by_id, diff_totals, all_flips)


if __name__ == "__main__":
    main()
