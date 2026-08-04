"""Behavioral claims on the shared blind-sheet grammar — parse and verify.

The load-bearing claims: a well-formed sheet round-trips into review states
(mentions with spans, ``(no span)``, zero, skip); text inside a fence can
never leak into the grammar; anything unclassifiable is a violation naming
its file and line, never a silent drop; and verification catches exactly the
hand-editing failure modes — unknown ids, contradictory states, foreign
sentiments, evidence that stopped being verbatim.
"""

from __future__ import annotations

from pathlib import Path

from steamlens.evals.sheets import SheetMention, parse_sheet, verify_reviews

_SHEET = """# Some sheet — preamble

Instructions mention `- aspect / sentiment / "evidence"` lines; ignored.

---

## 1 · review r1

- [x] reviewed

```text
Great gunplay, awful
netcode today.
```

- gameplay / positive / "Great gunplay"
- performance / negative / "awful\\nnetcode"

## 2 · review r2

- [x] reviewed

```text
ok
```

Zero mentions.

## 3 · review r3

  - [ ] reviewed

```text
non-english text
```

SKIP: non_english
"""


def _write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "SHEET.md"
    path.write_text(content, encoding="utf-8")
    return path


_TEXTS = {
    "r1": "Great gunplay, awful\nnetcode today.",
    "r2": "ok",
    "r3": "non-english text",
}


def test_well_formed_sheet_round_trips(tmp_path: Path) -> None:
    reviews, violations = parse_sheet(_write(tmp_path, _SHEET))
    assert violations == ()
    assert [r.review_id for r in reviews] == ["r1", "r2", "r3"]
    r1, r2, r3 = reviews
    assert r1.reviewed and r1.mentions == (
        SheetMention("gameplay", "positive", "Great gunplay"),
        SheetMention("performance", "negative", "awful\nnetcode"),
    )
    assert r2.reviewed and r2.zero and not r2.mentions
    # stray indentation on the checkbox is hand-editing, not a violation
    assert not r3.reviewed and r3.skip == "non_english"
    assert verify_reviews(reviews, _TEXTS, "SHEET.md") == ()


def test_no_span_parses_to_none_evidence(tmp_path: Path) -> None:
    sheet = _SHEET.replace('- gameplay / positive / "Great gunplay"',
                           "- gameplay / positive / (no span)")
    reviews, violations = parse_sheet(_write(tmp_path, sheet))
    assert violations == ()
    assert reviews[0].mentions[0].evidence is None
    assert verify_reviews(reviews, _TEXTS, "SHEET.md") == ()


def test_fence_interior_never_reaches_the_grammar(tmp_path: Path) -> None:
    sheet = _SHEET.replace("Great gunplay, awful", "- [x] reviewed\nZero mentions.\n## fake")
    reviews, violations = parse_sheet(_write(tmp_path, sheet))
    assert violations == ()
    assert [r.review_id for r in reviews] == ["r1", "r2", "r3"]
    assert not reviews[0].zero


def test_malformed_and_unparseable_lines_are_named_violations(tmp_path: Path) -> None:
    sheet = _SHEET + "\n- gameplay positive no slashes\nstray prose line\n"
    _, violations = parse_sheet(_write(tmp_path, sheet))
    assert len(violations) == 2
    assert "malformed mention line" in violations[0]
    assert "unparseable line" in violations[1]
    assert all("SHEET.md:" in v for v in violations)


def test_unterminated_fence_is_a_violation(tmp_path: Path) -> None:
    sheet = _SHEET + "\n## 4 · review r4\n\n```text\nnever closed\n"
    _, violations = parse_sheet(_write(tmp_path, sheet))
    assert violations == ("SHEET.md: unterminated text fence",)


def test_verify_catches_hand_editing_failure_modes(tmp_path: Path) -> None:
    sheet = _SHEET.replace("Zero mentions.", 'Zero mentions.\n- graphics / great / "ok"')
    sheet = sheet.replace('"Great gunplay"', '"Great gunplays"')  # drifted span
    reviews, _ = parse_sheet(_write(tmp_path, sheet))
    violations = verify_reviews(reviews, _TEXTS, "SHEET.md")
    assert any("not a verbatim substring" in v for v in violations)
    assert any("bad sentiment 'great'" in v for v in violations)
    assert any("exactly one of" in v for v in violations)  # r2 is zero AND mentioned


def test_verify_rejects_unknown_review_id(tmp_path: Path) -> None:
    reviews, _ = parse_sheet(_write(tmp_path, _SHEET))
    violations = verify_reviews(reviews, {"r1": _TEXTS["r1"], "r2": "ok"}, "SHEET.md")
    assert violations == ("SHEET.md review r3: unknown review id",)
