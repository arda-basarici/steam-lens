"""Behavioral claims on the misattribution audit scorer — parse, join, fold.

The load-bearing claims: the sheet's verdicts parse case-insensitively but an
unfilled or foreign value is a named violation (an incomplete pass must not
quietly score); the join to the sample stops on coverage or identity drift;
and the fold implements the definite-only ruling — unclear verdicts leave
the denominator with their counts disclosed, any ``no`` decides a claim
misattributed, only a double ``yes`` decides it supported, and the undecided
remainder is disclosed, never folded in.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from steamlens.core.intervals import wilson_interval
from steamlens.evals.misattribution import (
    ClaimVerdict,
    compute_reading,
    parse_audit_sheet,
    verify_against_sample,
)

_SHEET = """# Misattribution audit sheet

100 claims; fill the two verdicts with `yes` / `no` / `unclear`:

- **aspect_supported** — does the quote actually talk about the claimed aspect?
- **sentiment_supported** — does the quote carry the claimed sentiment toward it?

---

## 001 · Game A — **performance** (pinned), sentiment **negative**

review `r1` · mention `11`

> Some context with a ⟦bracketed quote⟧ inside.

- aspect_supported: yes
- sentiment_supported: Yes
- note:

---

## 002 · Game B — **music** (pinned), sentiment **positive**

review `r2` · mention `22`

> Another ⟦quote⟧.

- aspect_supported: no
- sentiment_supported: unclear
- note: quote is about sound effects, not music

---

## 003 · Game C — **combat** (pinned), sentiment **positive**

review `r3` · mention `33`

> Third ⟦quote⟧.

- aspect_supported: yes
- sentiment_supported: unclear
- note:
"""


def _write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "SHEET.md"
    path.write_text(content, encoding="utf-8")
    return path


def _sample_file(tmp_path: Path) -> Path:
    path = tmp_path / "sample.jsonl"
    rows = [
        {"item": 1, "role": "primary", "review_id": "r1", "mention_id": 11},
        {"item": 2, "role": "primary", "review_id": "r2", "mention_id": 22},
        {"item": 3, "role": "primary", "review_id": "r3", "mention_id": 33},
        {"item": 101, "role": "reserve", "review_id": "r9", "mention_id": 99},
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


def test_filled_sheet_parses_with_case_insensitive_verdicts(tmp_path: Path) -> None:
    verdicts, violations = parse_audit_sheet(_write(tmp_path, _SHEET))
    assert violations == ()
    assert [v.item for v in verdicts] == [1, 2, 3]
    assert verdicts[0].sentiment_supported == "yes"  # the hand-typed "Yes"
    assert verdicts[0].note is None  # empty note is no note
    assert verdicts[1].note == "quote is about sound effects, not music"
    assert (verdicts[1].review_id, verdicts[1].mention_id) == ("r2", 22)


def test_unfilled_and_foreign_verdicts_are_named_violations(tmp_path: Path) -> None:
    broken = _SHEET.replace("- aspect_supported: no", "- aspect_supported:")
    broken = broken.replace("- sentiment_supported: unclear", "- sentiment_supported: maybe", 1)
    verdicts, violations = parse_audit_sheet(_write(tmp_path, broken))
    assert [v.item for v in verdicts] == [1, 3]  # claim 002 does not score
    assert len(violations) == 2
    assert "claim 002 unfilled verdict aspect_supported" in violations[0]
    assert "claim 002 bad verdict sentiment_supported: 'maybe'" in violations[1]


def test_missing_id_line_is_a_violation(tmp_path: Path) -> None:
    broken = _SHEET.replace("review `r3` · mention `33`", "")
    verdicts, violations = parse_audit_sheet(_write(tmp_path, broken))
    assert [v.item for v in verdicts] == [1, 2]
    assert any("claim 003 has no id line" in v for v in violations)


def test_join_stops_on_coverage_and_identity_drift(tmp_path: Path) -> None:
    verdicts, _ = parse_audit_sheet(_write(tmp_path, _SHEET))
    sample = _sample_file(tmp_path)
    assert verify_against_sample(verdicts, sample) == ()
    # reserves are not sheet material, so their absence is not a gap
    short = [v for v in verdicts if v.item != 3]
    (coverage,) = verify_against_sample(short, sample)
    assert "missing [3]" in coverage
    drifted = [*short, ClaimVerdict(3, "r3", 44, "yes", "yes", None)]
    violations = verify_against_sample(drifted, sample)
    assert any("claim 003 identity drift" in v for v in violations)


def test_fold_implements_the_definite_only_ruling() -> None:
    verdicts = (
        ClaimVerdict(1, "r1", 11, "yes", "yes", None),      # supported
        ClaimVerdict(2, "r2", 22, "no", "unclear", None),   # misattributed (aspect decides)
        ClaimVerdict(3, "r3", 33, "yes", "unclear", None),  # undecided
        ClaimVerdict(4, "r4", 44, "yes", "no", None),       # misattributed (sentiment decides)
    )
    reading = compute_reading(verdicts)
    assert reading.n_claims == 4
    assert reading.aspect.rate == pytest.approx(1 / 4)  # no=1 over definite 4, unclear 0
    assert reading.aspect.n_unclear == 0
    assert reading.sentiment.rate == pytest.approx(1 / 2)  # no=1 over definite 2
    assert reading.sentiment.n_unclear == 2
    assert reading.combined.rate == pytest.approx(2 / 3)  # 2 misattributed / 3 decidable
    assert reading.n_undecided == 1
    assert [v.item for v in reading.misattributed] == [2, 4]
    expected = wilson_interval(2, 3)
    assert reading.combined.interval == expected


def test_fold_reports_undefined_rates_never_zero() -> None:
    verdicts = (ClaimVerdict(1, "r1", 11, "unclear", "unclear", None),)
    reading = compute_reading(verdicts)
    assert reading.aspect.rate is None and reading.aspect.interval is None
    assert reading.combined.rate is None  # nothing decidable
    assert reading.n_undecided == 1
    with pytest.raises(ValueError, match="empty audit"):
        compute_reading(())
