"""Score the misattribution audit sheet — the human read behind the verbatim caveat.

The fabricated-quote metric certifies that every stored evidence span is a
verbatim substring; the standing spine caveat is that verbatim passes a quote
read upside-down. This scorer turns Arda's audit pass over the minted claim
sample (100 primaries, a seeded systematic draw — self-weighting, so the
audited rate estimates the population rate with no reweighting) into that
caveat's measured size: the share of evidence-carrying mentions whose
verbatim-true quote is attached to the wrong aspect or an uncarried
sentiment.

Verdicts are ``yes`` / ``no`` / ``unclear`` per side, and rates read over
definite verdicts only with the unclear counts disclosed beside them (ruled
2026-08-04) — an "unclear" is not measured badness, the same honesty as the
bootstrap-undefined convention. The combined rate's denominator is the
decidable claims: any ``no`` decides a claim misattributed, a double ``yes``
decides it supported, anything else is undecided and disclosed. Intervals
are Wilson at 95%.

An unauditable primary (a non-English review that slipped the language
filter) is SKIPped on the sheet and replaced from the draw's ordered
reserves — the gold-workbook pattern. A replacement renders as item
``100 + reserve_number`` and must be consumed strictly in reserve order, so
the audited set stays a deterministic function of the draw and the skip
causes, never a choice.

An audit has no measuring stick, so per the eval-harness ruling it stays out
of ``eval_runs`` and renders as a regenerable report — a table on the
console and ``report.json`` beside the sheet, both carrying the sheet and
sample pins so the numbers are regenerable to the digit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from steamlens.core.intervals import Interval, wilson_interval
from steamlens.dispatch import code_version

VERDICT_WORDS: Final = frozenset({"yes", "no", "unclear"})

RESERVE_ITEM_BASE: Final = 100
"""Sheet item numbers above this map to reserves (sheet 101 = reserve 1), so
replacement blocks join the sample without renumbering the draw."""

_HEADER_RE = re.compile(r"^## (\d+) ·")
_IDS_RE = re.compile(r"^review `(\S+)` · mention `(\d+)`$")
_FIELD_RE = re.compile(r"^- (aspect_supported|sentiment_supported|note):\s*(.*)$")
_SKIP_RE = re.compile(r"^SKIP: (non_english|empty_text)\.?$")


@dataclass(frozen=True, slots=True)
class ClaimVerdict:
    """One audited claim: the sheet's two verdicts joined to the sample's identity."""

    item: int
    review_id: str
    mention_id: int
    aspect_supported: str
    sentiment_supported: str
    note: str | None


@dataclass(frozen=True, slots=True)
class FieldReading:
    """One verdict field's rate: ``no`` over the definite verdicts, unclear beside it.

    ``rate``/``interval`` are ``None`` when no definite verdict exists —
    undefined, never 0.0.
    """

    n_yes: int
    n_no: int
    n_unclear: int
    rate: float | None
    interval: Interval | None


@dataclass(frozen=True, slots=True)
class AuditReading:
    """The audit's verdict arithmetic — everything the report renders.

    ``combined`` is the headline misattribution read: misattributed (any
    ``no``) over decidable (misattributed + double-``yes``), with the
    undecided remainder disclosed. ``misattributed`` lists the failing claims
    by identity with which side failed — the report narrative's raw material,
    not a metric.
    """

    n_claims: int
    aspect: FieldReading
    sentiment: FieldReading
    combined: FieldReading
    n_undecided: int
    misattributed: tuple[ClaimVerdict, ...]


def _field_reading(n_yes: int, n_no: int, n_unclear: int) -> FieldReading:
    definite = n_yes + n_no
    interval = wilson_interval(n_no, definite) if definite else None
    return FieldReading(
        n_yes=n_yes,
        n_no=n_no,
        n_unclear=n_unclear,
        rate=n_no / definite if definite else None,
        interval=interval,
    )


def compute_reading(verdicts: Sequence[ClaimVerdict]) -> AuditReading:
    """Fold the joined verdicts into the audit's rates — pure arithmetic.

    Per-side rates read ``no`` over that side's definite verdicts. A claim is
    misattributed on any ``no`` (one wrong side is enough — the quote fails
    its claim), supported only on a double ``yes``, undecided otherwise.
    """
    if not verdicts:
        raise ValueError("cannot read an empty audit — no verdicts to fold")
    aspect = _field_reading(
        sum(v.aspect_supported == "yes" for v in verdicts),
        sum(v.aspect_supported == "no" for v in verdicts),
        sum(v.aspect_supported == "unclear" for v in verdicts),
    )
    sentiment = _field_reading(
        sum(v.sentiment_supported == "yes" for v in verdicts),
        sum(v.sentiment_supported == "no" for v in verdicts),
        sum(v.sentiment_supported == "unclear" for v in verdicts),
    )
    misattributed = tuple(
        v for v in verdicts if v.aspect_supported == "no" or v.sentiment_supported == "no"
    )
    supported = sum(
        v.aspect_supported == "yes" and v.sentiment_supported == "yes" for v in verdicts
    )
    combined = _field_reading(supported, len(misattributed), 0)
    return AuditReading(
        n_claims=len(verdicts),
        aspect=aspect,
        sentiment=sentiment,
        combined=combined,
        n_undecided=len(verdicts) - supported - len(misattributed),
        misattributed=misattributed,
    )


def parse_audit_sheet(
    path: Path,
) -> tuple[tuple[ClaimVerdict, ...], tuple[tuple[int, str], ...], tuple[str, ...]]:
    """Parse the edited audit sheet into (claim verdicts, skips, violations).

    Line-shaped like the labeling-sheet grammar: claim headers, an id line,
    ``- <field>: <value>`` verdict lines; blockquotes (the claim's context),
    ``---`` separators, and blanks are ignored. A ``SKIP: <cause>`` line
    marks the claim unauditable — it lands in ``skips`` as ``(item, cause)``
    and must carry no verdicts (both is a violation: a skipped claim was not
    judged). Verdict words are matched case-insensitively after stripping (a
    hand-filled ``Yes`` is a verdict, not a violation) but an empty or
    foreign value is a violation naming its line — the pass is incomplete or
    drifted, and either must be fixed at the sheet, never patched at the
    parser.
    """
    violations: list[str] = []
    claims: list[ClaimVerdict] = []
    skips: list[tuple[int, str]] = []
    item: int | None = None
    ids: tuple[str, int] | None = None
    fields: dict[str, str | None] = {}
    skip_cause: str | None = None

    def close_block(where: str) -> None:
        nonlocal item, ids, fields, skip_cause
        if item is None:
            return
        if skip_cause is not None:
            if any(v for v in (fields.get("aspect_supported"), fields.get("sentiment_supported"))):
                violations.append(
                    f"{where}: claim {item:03d} is SKIPped but carries verdicts"
                )
            else:
                skips.append((item, skip_cause))
            item, ids, fields, skip_cause = None, None, {}, None
            return
        if ids is None:
            violations.append(f"{where}: claim {item:03d} has no id line")
        else:
            aspect = fields.get("aspect_supported")
            sentiment = fields.get("sentiment_supported")
            for name, value in (("aspect_supported", aspect), ("sentiment_supported", sentiment)):
                if value is None or value == "":
                    violations.append(f"{where}: claim {item:03d} unfilled verdict {name}")
                elif value not in VERDICT_WORDS:
                    violations.append(
                        f"{where}: claim {item:03d} bad verdict {name}: {value!r}"
                    )
            if (
                aspect is not None
                and sentiment is not None
                and aspect in VERDICT_WORDS
                and sentiment in VERDICT_WORDS
            ):
                claims.append(
                    ClaimVerdict(
                        item=item,
                        review_id=ids[0],
                        mention_id=ids[1],
                        aspect_supported=aspect,
                        sentiment_supported=sentiment,
                        note=fields.get("note") or None,
                    )
                )
        item, ids, fields, skip_cause = None, None, {}, None

    for lineno, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        where = f"{path.name}:{lineno}"
        line = raw_line.strip()
        header = _HEADER_RE.match(line)
        if header:
            close_block(where)
            item = int(header.group(1))
            continue
        if item is None or not line or line.startswith(">") or line == "---":
            continue
        id_match = _IDS_RE.match(line)
        if id_match:
            ids = (id_match.group(1), int(id_match.group(2)))
            continue
        skip = _SKIP_RE.match(line)
        if skip:
            skip_cause = skip.group(1)
            continue
        field = _FIELD_RE.match(line)
        if field:
            name, value = field.group(1), field.group(2).strip()
            fields[name] = value.lower() if name != "note" else value
            continue
        violations.append(f"{where}: unparseable line: {line!r}")
    close_block(f"{path.name}:EOF")
    return tuple(claims), tuple(skips), tuple(violations)


def verify_against_sample(
    verdicts: Sequence[ClaimVerdict],
    skips: Sequence[tuple[int, str]],
    sample_path: Path,
) -> tuple[str, ...]:
    """Check coverage and identity: primaries filled-or-skipped, reserves in order.

    The sheet renders the 100 primary claims; a skipped primary consumes the
    next ordered reserve, rendered as item ``RESERVE_ITEM_BASE + n``. Exactly
    the first ``len(skips)`` reserves must be filled — consuming them out of
    order (or over- or under-consuming) would make the audited set a choice
    instead of a rule. Coverage or identity drift means the sheet was edited
    structurally, not just filled — a scoring stop, not a warning.
    """
    primaries: dict[int, dict[str, object]] = {}
    reserves: dict[int, dict[str, object]] = {}
    with sample_path.open(encoding="utf-8") as f:
        for line in f:
            record = json.loads(line)
            (primaries if record["role"] == "primary" else reserves)[record["item"]] = record
    violations: list[str] = []
    skipped = {item for item, _ in skips}
    if not skipped <= set(primaries):
        violations.append(f"skipped items are not primaries: {sorted(skipped - set(primaries))}")
    filled_primary = {v.item for v in verdicts if v.item <= RESERVE_ITEM_BASE}
    expected_primary = set(primaries) - skipped
    if filled_primary != expected_primary:
        missing = sorted(expected_primary - filled_primary)
        extra = sorted(filled_primary - expected_primary)
        violations.append(
            f"claim coverage mismatch vs the sample's primaries "
            f"(missing {missing[:5]}, extra {extra[:5]})"
        )
    filled_reserve = {v.item - RESERVE_ITEM_BASE for v in verdicts if v.item > RESERVE_ITEM_BASE}
    expected_reserve = set(range(1, len(skips) + 1))
    if filled_reserve != expected_reserve:
        violations.append(
            f"replacement mismatch: {len(skips)} skip(s) must consume reserves "
            f"{sorted(expected_reserve)} in order, sheet has {sorted(filled_reserve)}"
        )
    for v in verdicts:
        record = (
            primaries.get(v.item)
            if v.item <= RESERVE_ITEM_BASE
            else reserves.get(v.item - RESERVE_ITEM_BASE)
        )
        if record is None:
            continue
        if record["review_id"] != v.review_id or record["mention_id"] != v.mention_id:
            violations.append(
                f"claim {v.item:03d} identity drift: sheet has review {v.review_id} / "
                f"mention {v.mention_id}, sample has {record['review_id']} / "
                f"{record['mention_id']}"
            )
    return tuple(violations)


def _field_json(reading: FieldReading) -> dict[str, object]:
    return {
        "n_yes": reading.n_yes,
        "n_no": reading.n_no,
        "n_unclear": reading.n_unclear,
        "rate": reading.rate,
        "ci_low": reading.interval.low if reading.interval else None,
        "ci_high": reading.interval.high if reading.interval else None,
    }


def render_report(
    reading: AuditReading,
    *,
    sheet_path: Path,
    sample_path: Path,
    created_at: datetime,
    skips: Sequence[tuple[int, str]] = (),
) -> str:
    """The audit as regenerable JSON — pins, rates, skips, and the failing claims."""
    return json.dumps(
        {
            "purpose": "misattribution audit: the share of evidence-carrying mentions "
            "whose verbatim-true quote is attached to the wrong aspect or an "
            "uncarried sentiment",
            "created_at": created_at.isoformat(),
            "code_version": code_version(),
            "sheet_path": sheet_path.as_posix(),
            "sheet_sha256": hashlib.sha256(sheet_path.read_bytes()).hexdigest(),
            "sample_path": sample_path.as_posix(),
            "sample_sha256": hashlib.sha256(sample_path.read_bytes()).hexdigest(),
            "skips": [
                {"item": item, "cause": cause, "replacement_reserve": n + 1}
                for n, (item, cause) in enumerate(skips)
            ],
            "n_claims": reading.n_claims,
            "misattribution": _field_json(reading.combined),
            "n_undecided": reading.n_undecided,
            "aspect_supported": _field_json(reading.aspect),
            "sentiment_supported": _field_json(reading.sentiment),
            "misattributed_claims": [
                {
                    "item": v.item,
                    "review_id": v.review_id,
                    "mention_id": v.mention_id,
                    "aspect_supported": v.aspect_supported,
                    "sentiment_supported": v.sentiment_supported,
                    "note": v.note,
                }
                for v in reading.misattributed
            ],
        },
        indent=2,
        ensure_ascii=False,
    )


def _rate_line(name: str, reading: FieldReading) -> str:
    if reading.rate is None or reading.interval is None:
        return f"  {name}: undefined (no definite verdicts)"
    return (
        f"  {name}: {reading.rate:.3f} "
        f"[{reading.interval.low:.3f}–{reading.interval.high:.3f}] "
        f"(no {reading.n_no} / yes {reading.n_yes}, unclear {reading.n_unclear})"
    )


def render_table(reading: AuditReading) -> str:
    """The console read — every number the JSON carries, human-shaped."""
    lines = [
        f"misattribution audit · {reading.n_claims} claims",
        _rate_line("misattribution (any no / decidable)", reading.combined),
        f"    undecided (unclear, no 'no'): {reading.n_undecided}",
        _rate_line("aspect_supported = no", reading.aspect),
        _rate_line("sentiment_supported = no", reading.sentiment),
    ]
    if reading.misattributed:
        lines.append("  misattributed claims:")
        lines.extend(
            f"    {v.item:03d} · review {v.review_id} · mention {v.mention_id} · "
            f"aspect {v.aspect_supported} / sentiment {v.sentiment_supported}"
            + (f" · {v.note}" if v.note else "")
            for v in reading.misattributed
        )
    return "\n".join(lines)


def main() -> None:
    """Parse, verify, fold, render — the audit's front door (no journal, by ruling)."""
    parser = argparse.ArgumentParser(
        description="Score the filled misattribution audit sheet and write the report."
    )
    parser.add_argument("--audit-dir", type=Path, default=Path("eval/audits/misattribution"),
                        help="the audit's directory: SHEET.md, sample.jsonl (default: "
                             "eval/audits/misattribution)")
    parser.add_argument("--dry-run", action="store_true",
                        help="score and print without writing report.json")
    args = parser.parse_args()

    sheet_path = args.audit_dir / "SHEET.md"
    sample_path = args.audit_dir / "sample.jsonl"
    verdicts, skips, violations = parse_audit_sheet(sheet_path)
    problems = list(violations) + list(verify_against_sample(verdicts, skips, sample_path))
    if problems:
        print(f"{len(problems)} FINDING(S):")
        for p in problems:
            print(f"  !! {p}")
        raise SystemExit(1)

    reading = compute_reading(verdicts)
    print(render_table(reading))
    for item, cause in skips:
        print(f"  skipped {item:03d} ({cause}), replaced from the ordered reserve")
    if args.dry_run:
        print("dry run — report.json not written")
        return
    report_path = args.audit_dir / "report.json"
    report_path.write_text(
        render_report(
            reading,
            sheet_path=sheet_path,
            sample_path=sample_path,
            created_at=datetime.now(UTC),
            skips=skips,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"report -> {report_path.as_posix()}")


if __name__ == "__main__":
    main()
