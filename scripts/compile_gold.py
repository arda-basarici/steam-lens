"""Parse the edited gold workbook, verify it, and report adjudication state.

The read half of the workbook loop (render_gold_workbook.py is the write
half). Default mode is **check**: parse every sheet, enforce the structural
grammar, re-verify evidence verbatim against the review texts (Arda's edits
included — human transfer is where spans drift), and diff the current state
against the immutable ``assist/raw/`` files to report progress and the
assist-vs-final disagreement stats that INSTRUCTIONS section 8 wants measured.

``--mint`` additionally writes the final gold set — refused until every
review is checked off, every violation cleared, and every SKIP resolved.
Minting is deliberately not built yet (it lands with the skip-replacement
flow once Arda's pass confirms which skips are real); check mode is complete
and is also the render round-trip test: a freshly rendered workbook must
parse back identical to raw (all accepted, zero violations).

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
) -> dict[str, int]:
    """Assist-vs-current mention diff: accepted / modified / added / deleted.

    Exact (aspect, sentiment, evidence) matches count accepted; a same-aspect
    survivor with edits counts modified; the rest are deletions/additions.
    Coarse by design — the free difficulty estimate, not a certified metric.
    """
    counts = {"accepted": 0, "modified": 0, "added": 0, "deleted": 0}
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
        counts["deleted"] += len(raw_mentions)
        counts["added"] += len(current)
    return counts


def main() -> None:
    if "--mint" in sys.argv:
        raise SystemExit(
            "--mint is not built yet: it lands with the skip-replacement flow "
            "after the adjudication pass confirms which skips are real"
        )

    sheets = sorted(_WORKBOOK_DIR.glob("batch_*.md"))
    if not sheets:
        raise SystemExit(f"no sheets in {_WORKBOOK_DIR} — render the workbook first")

    all_violations: list[str] = []
    totals = {"reviews": 0, "reviewed": 0, "mentions": 0, "skips": 0}
    diff_totals = {"accepted": 0, "modified": 0, "added": 0, "deleted": 0}
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
        diff = diff_against_raw(reviews, raw_annotations)

        all_violations += violations
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


if __name__ == "__main__":
    main()
