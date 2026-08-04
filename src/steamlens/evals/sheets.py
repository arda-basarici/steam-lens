"""The blind labeling sheet's grammar — parse and verify a hand-edited pass.

One markdown grammar serves every human labeling artifact (the gold workbook,
the fresh holdout sheet): review blocks under ``## <n> · review <id>``
headers, a ``- [ ] reviewed`` checkbox, and exactly one of mention lines /
``Zero mentions.`` / ``SKIP: <cause>``. The sheets are rendered by machine
and edited by hand, so the parser is deliberately forgiving about whitespace
(hand-editing leaves stray indentation; the grammar is line-shaped) and loud
about everything else: a line it cannot classify is a violation naming its
file and line, never a silent skip — a dropped mention would silently move a
certified number.

This is the read half only. Renderers own their layouts; minting decisions
(what a parsed sheet becomes) stay with the callers. ``compile_gold`` grew
the grammar first and still carries its own copy wired to the workbook's
assist-diff machinery; re-pointing it here is parked, not forgotten
(FIXLOG 2026-08-04).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

SENTIMENT_WORDS: Final = frozenset({"positive", "negative", "mixed", "neutral"})
"""The sentiment vocabulary a sheet may use — the codebook's four, as words.
Validated here (not at enum conversion) so a typo surfaces as a sheet
violation with a line to fix, never a stack trace mid-scoring."""

_HEADER_RE = re.compile(r"^## \d+ · review (\S+)$")
_CHECKBOX_RE = re.compile(r"^- \[( |x)\] reviewed$")
_FENCE_OPEN_RE = re.compile(r"^(`{3,})text$")
_SKIP_RE = re.compile(r"^SKIP: (non_english|empty_text)\.?$")


@dataclass(frozen=True, slots=True)
class SheetMention:
    """One hand-written mention line: aspect / sentiment / evidence.

    ``sentiment`` stays the sheet's raw word — conversion to the ``Sentiment``
    enum is the scorer's step, after ``verify_reviews`` has vouched the word
    is in the vocabulary. ``evidence`` is ``None`` for an explicit
    ``(no span)``, mirroring the machine side's honest no-clean-span state.
    """

    aspect: str
    sentiment: str
    evidence: str | None


@dataclass(frozen=True, slots=True)
class SheetReview:
    """One review block as parsed — the human pass's record for one review."""

    review_id: str
    reviewed: bool
    zero: bool
    skip: str | None
    mentions: tuple[SheetMention, ...]


def _unescape_evidence(shown: str) -> str:
    return shown.replace("\\n", "\n").replace("\\r", "\r")


def _parse_mention_line(line: str) -> SheetMention | None:
    """``- aspect / sentiment / "evidence"`` → mention, or ``None`` if malformed."""
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
    return SheetMention(aspect=aspect, sentiment=sentiment, evidence=evidence)


@dataclass
class _Block:
    """Mutable accumulator for one review block while the line walk runs."""

    review_id: str
    reviewed: bool = False
    zero: bool = False
    skip: str | None = None
    mentions: list[SheetMention] | None = None

    def freeze(self) -> SheetReview:
        return SheetReview(
            review_id=self.review_id,
            reviewed=self.reviewed,
            zero=self.zero,
            skip=self.skip,
            mentions=tuple(self.mentions or ()),
        )


def parse_sheet(path: Path) -> tuple[tuple[SheetReview, ...], tuple[str, ...]]:
    """Parse one sheet into review blocks plus grammar violations.

    Text inside a review's fenced block is untouched (only the fence
    delimiters strip); blank lines and ``>`` blockquotes (assist notes) are
    ignored; everything else must classify as header / checkbox / mention /
    ``Zero mentions.`` / SKIP or it lands in the violation list with its
    ``file:line``. Parsing never raises on content — the caller decides
    whether violations stop the run.
    """
    violations: list[str] = []
    blocks: list[_Block] = []
    current: _Block | None = None
    fence: str | None = None
    in_preamble = True

    for lineno, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        where = f"{path.name}:{lineno}"
        line = raw_line.strip()
        if fence is not None:  # inside a review's text block
            if line == fence:
                fence = None
            continue
        header = _HEADER_RE.match(line)
        if header:
            in_preamble = False
            current = _Block(review_id=header.group(1))
            blocks.append(current)
            continue
        if in_preamble or current is None:
            continue
        if not line or line.startswith(">") or line == "---":
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
                current.mentions = [*(current.mentions or []), mention]
            continue
        violations.append(f"{where}: unparseable line: {line!r}")

    if fence is not None:
        violations.append(f"{path.name}: unterminated text fence")
    return tuple(b.freeze() for b in blocks), tuple(violations)


def verify_reviews(
    reviews: Sequence[SheetReview], texts: Mapping[str, str], sheet: str
) -> tuple[str, ...]:
    """Structural and verbatim checks over parsed blocks — the pass's gate.

    Every review must be known to ``texts`` (the machine record the sheet was
    rendered from), carry exactly one of mentions / zero / skip, use only the
    sentiment vocabulary, and quote evidence verbatim from its review's text —
    human transfer is where spans drift, so the check runs on the edited
    sheet, not the render. Returns violations; empty means the sheet is
    scoreable.
    """
    violations: list[str] = []
    for r in reviews:
        where = f"{sheet} review {r.review_id}"
        text = texts.get(r.review_id)
        if text is None:
            violations.append(f"{where}: unknown review id")
            continue
        states = [bool(r.mentions), r.zero, r.skip is not None]
        if sum(states) != 1:
            violations.append(
                f"{where}: needs exactly one of mentions / 'Zero mentions.' / SKIP "
                f"(has mentions={bool(r.mentions)}, zero={r.zero}, skip={r.skip})"
            )
        for m in r.mentions:
            if m.sentiment not in SENTIMENT_WORDS:
                violations.append(f"{where}: bad sentiment {m.sentiment!r}")
            if not m.aspect:
                violations.append(f"{where}: empty aspect")
            if m.evidence is not None and m.evidence not in text:
                violations.append(
                    f"{where} [{m.aspect}]: evidence not a verbatim substring: {m.evidence!r}"
                )
    return tuple(violations)
