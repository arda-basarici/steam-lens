"""The numeric-grounding gate — deterministic verification of composed prose.

The composer is fenced on both sides by deterministic checks; this module is
the outbound fence, pure and testable as text-in / report-out. It answers one
question: does this prose state anything the job's own outputs cannot back?
Every numeral outside a quotation must match a whitelisted value at the
numeral's *own* precision — honest rounding passes ("27.3%" may appear as
"27%"), an estimate with no match ("roughly 40%" over a 27.3% share) dies,
which is the laundering case the gate exists for. Every quotation must be a
verbatim substring of the supplied evidence — the compose-side mirror of the
classify parse's write-time quote check — where "verbatim" is judged on the
quoted words: sentence punctuation the writer tucks inside the closing mark
("…too high," / "…tear up.") is typography, not content, and is stripped
before the check (ruled 2026-08-16 off a full replay of the archive: 119 of
122 gate violations across 37 drafts were exactly this, the numeric fence
never fired once, and seven public reports had true sentences cut for a
period). The known caveat rides along unchanged: verbatim passes a quote
used misleadingly out of context; that is the judge machinery's territory
(the chat milestone), never this gate's.

The whitelist derives from pinned aggregates plus the job-level values the
shell hands in. Candidate aggregates contribute nothing *by ruling* — themes
enter the narrative as names, never numbers — so the gate enforces the
two-stratum rule structurally: a candidate-derived numeral has no match and
dies like any other ungrounded number.

A pass is a certificate, not just a verdict: the report carries every
certified span (numeral with its matched value, quotation with its source
review), which is what the report row stores and the renderer styles — in
gate-passed prose every non-quote numeral IS a minted value by construction.
The failure ladder (corrective retry, sentence-drop, disclosed withholding)
is the shell's orchestration; this module only measures and cuts. Callers
normalize typography first (``normalize_quotes``) and re-ground any cut text —
offsets in a report always refer to exactly the text that was grounded.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Final

from steamlens.contracts import (
    AspectAggregate,
    AspectSlot,
    EvidenceQuote,
    GroundedSpan,
    SpanKind,
)

# One numeral token: comma-grouped or plain, optional decimal part. The regex
# deliberately reads "10/10" as two grounded-or-not numerals and never matches
# the dot of "27.3" as sentence punctuation ordering — precision comes from the
# token's own decimal digits, nothing else.
_NUMERAL: Final = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")

# Typography a prose model plausibly emits for double quotes, folded to the
# straight mark the scanner reads. Single quotes stay untouched — apostrophes
# and contractions would make them unpairable.
_CURLY_QUOTES: Final = {"“": '"', "”": '"', "„": '"', "«": '"', "»": '"'}

_SENTENCE_END: Final = re.compile(r"[.!?]+(?=\s|$)")

# Sentence punctuation a writer closes a quotation with — the American
# convention puts it inside the mark. Stripped from the quoted words before
# the verbatim check; never from the evidence side, and never mid-quote.
_QUOTE_TAIL_PUNCTUATION: Final = re.compile(r"[.,!?;:…]+$")


def normalize_quotes(prose: str) -> str:
    """Fold curly double-quote typography to straight marks, apostrophes untouched.

    Run before ``ground`` and persist what was normalized: a report's offsets
    refer to the exact text it was handed, so normalize-then-ground keeps the
    certificate honest against the stored prose.

    >>> normalize_quotes('“runs great”')
    '"runs great"'
    """
    for curly, straight in _CURLY_QUOTES.items():
        prose = prose.replace(curly, straight)
    return prose


def derive_whitelist(
    aggregates: Sequence[AspectAggregate],
    *,
    sample_size: int,
    extra_values: Sequence[float] = (),
) -> frozenset[float]:
    """Every value the prose may state, derived from the job's own outputs.

    From each *pinned* aggregate: the distinct-review count, its percentage
    share of the sample, each sentiment count, and each sentiment count's
    percentage of both the mention count and the sample — the honest
    derivations a narrative plausibly states. ``sample_size`` itself is always
    whitelisted; ``extra_values`` is the shell's door for job-level numbers
    (claimed totals, histogram volumes, episode magnitudes when detect lands).
    Candidate aggregates contribute nothing — the two-stratum ruling, enforced
    here structurally. Every widening of this set weakens the gate, so
    additions are deliberate, never convenient.

    >>> sorted(derive_whitelist([], sample_size=1000, extra_values=[45210.0]))
    [1000.0, 45210.0]
    """
    values: set[float] = {float(sample_size)}
    values.update(float(value) for value in extra_values)
    for aggregate in aggregates:
        if aggregate.slot is not AspectSlot.PINNED:
            continue
        mentions = aggregate.reviews_with_aspect
        values.add(float(mentions))
        if aggregate.sample_size > 0:
            values.add(mentions / aggregate.sample_size * 100)
        counts = aggregate.counts
        for count in (counts.positive, counts.negative, counts.mixed, counts.neutral):
            values.add(float(count))
            if mentions > 0:
                values.add(count / mentions * 100)
            if aggregate.sample_size > 0:
                values.add(count / aggregate.sample_size * 100)
    return frozenset(values)


@dataclass(frozen=True, slots=True)
class Violation:
    """One span the gate refuses, located and explained.

    ``start``/``end``/``text`` mirror the certified-span addressing; ``kind``
    says which check failed and ``reason`` is the sentence the corrective
    retry names verbatim — the violation record *is* the retry's material.
    """

    start: int
    end: int
    text: str
    kind: SpanKind
    reason: str


@dataclass(frozen=True, slots=True)
class GroundingReport:
    """The gate's full account of one prose text: certified spans and violations.

    ``certified`` is the pass's product — the spans the report row stores and
    the renderer styles; ``violations`` is the ladder's input. Both are sorted
    by position. The report never mutates the prose it judged; cutting is
    ``drop_violating_sentences``'s separate job, and the cut text gets its own
    fresh report.
    """

    certified: tuple[GroundedSpan, ...]
    violations: tuple[Violation, ...]

    @property
    def passed(self) -> bool:
        """True when nothing in the prose failed a check."""
        return not self.violations


def ground(
    prose: str,
    whitelist: AbstractSet[float],
    evidence: Sequence[EvidenceQuote],
) -> GroundingReport:
    """Judge one prose text against the whitelist and the evidence pool.

    Quotations are read as sequentially paired straight double quotes (run
    ``normalize_quotes`` first): each pair's quoted words — the text between
    the marks, less any sentence punctuation tucked inside the closing mark —
    must be a non-empty verbatim substring of some evidence text; a verified
    pair certifies with its source ``review_id`` (the lowest matching id, for
    determinism), a failed pair is one violation, and an unpaired trailing
    mark is a violation of its own. Numerals inside *any* paired quotation are
    exempt from the numeric check — a verified quote's numbers belong to the
    reviewer, and a failed quote already condemns its sentence. Every numeral
    outside quotations must round-match a whitelisted value at the numeral's
    own decimal precision (half rounds up); the certified span carries the
    lowest matching value.

    >>> report = ground('Performance comes up in 273 reviews.', frozenset({273.0}), ())
    >>> report.passed, report.certified[0].text
    (True, '273')
    >>> ground('Roughly 40% complain.', frozenset({27.3}), ()).violations[0].text
    '40'
    >>> pool = [EvidenceQuote('r1', 'price', 'negative', 'the asking price is far too high')]
    >>> ground('One wrote "asking price is far too high," and left.', frozenset(), pool).passed
    True
    """
    certified: list[GroundedSpan] = []
    violations: list[Violation] = []
    pairs, unpaired = _quote_pairs(prose)
    if unpaired is not None:
        violations.append(
            Violation(
                start=unpaired,
                end=unpaired + 1,
                text='"',
                kind=SpanKind.QUOTE,
                reason="unpaired quotation mark",
            )
        )
    for start, end in pairs:
        words = _quoted_words(prose[start + 1 : end - 1])
        if not words:
            violations.append(
                Violation(
                    start=start, end=end, text=prose[start:end],
                    kind=SpanKind.QUOTE, reason="empty quotation",
                )
            )
            continue
        sources = sorted(quote.review_id for quote in evidence if words in quote.text)
        if sources:
            certified.append(
                GroundedSpan(
                    start=start, end=end, text=prose[start:end],
                    kind=SpanKind.QUOTE, review_id=sources[0],
                )
            )
        else:
            violations.append(
                Violation(
                    start=start, end=end, text=prose[start:end],
                    kind=SpanKind.QUOTE,
                    reason="quotation is not a verbatim span of the supplied evidence",
                )
            )
    for match in _NUMERAL.finditer(prose):
        if _inside_any(match.start(), pairs):
            continue
        value = _round_match(match.group(), whitelist)
        if value is not None:
            certified.append(
                GroundedSpan(
                    start=match.start(), end=match.end(), text=match.group(),
                    kind=SpanKind.NUMERAL, value=value,
                )
            )
        else:
            violations.append(
                Violation(
                    start=match.start(), end=match.end(), text=match.group(),
                    kind=SpanKind.NUMERAL,
                    reason=(
                        f"numeral {match.group()!r} matches no whitelisted value "
                        "at its own precision"
                    ),
                )
            )
    certified.sort(key=lambda span: span.start)
    violations.sort(key=lambda violation: violation.start)
    return GroundingReport(tuple(certified), tuple(violations))


def drop_violating_sentences(prose: str, report: GroundingReport) -> str:
    """Cut every sentence a violation touches; survivors keep their own text.

    The ladder's second rung: sentence boundaries are terminal punctuation
    outside quotations (a period inside a quote never splits), each violating
    sentence is removed whole, and the surviving text — possibly empty —
    returns for the shell to re-ground, so the final certificate's offsets
    refer to exactly what renders.

    >>> report = ground('Roughly 40% complain. The rest hold up.', frozenset(), ())
    >>> drop_violating_sentences('Roughly 40% complain. The rest hold up.', report)
    'The rest hold up.'
    """
    survivors: list[str] = []
    for start, end in _sentence_spans(prose):
        hit = any(
            violation.start < end and violation.end > start
            for violation in report.violations
        )
        if not hit:
            survivors.append(prose[start:end])
    return "".join(survivors).strip()


def _quoted_words(inner: str) -> str:
    """The words a quotation asserts verbatim: its content less closing punctuation.

    A writer's period or comma inside the closing mark belongs to the
    sentence, not the reviewer (edge whitespace goes with it); a quotation
    holding nothing but punctuation
    asserts no words and returns empty (the caller's "empty quotation" case),
    which also keeps an empty string from matching every evidence text.

    >>> _quoted_words('runs great.')
    'runs great'
    >>> _quoted_words('...')
    ''
    """
    return _QUOTE_TAIL_PUNCTUATION.sub("", inner.strip()).strip()


def _quote_pairs(prose: str) -> tuple[list[tuple[int, int]], int | None]:
    """Sequentially paired straight-quote spans (end-exclusive), plus any odd mark.

    Pairing is positional — first mark opens, next closes — which is the only
    reading that needs no grammar; the returned spans include the marks
    themselves. An odd trailing mark cannot pair and returns as its index.
    """
    marks = [index for index, char in enumerate(prose) if char == '"']
    pairs = [
        (marks[at], marks[at + 1] + 1) for at in range(0, len(marks) - 1, 2)
    ]
    unpaired = marks[-1] if len(marks) % 2 else None
    return pairs, unpaired


def _inside_any(position: int, spans: Sequence[tuple[int, int]]) -> bool:
    """Whether ``position`` falls inside any end-exclusive span."""
    return any(start <= position < end for start, end in spans)


def _round_match(token: str, whitelist: AbstractSet[float]) -> float | None:
    """The lowest whitelisted value that rounds to ``token`` at its precision.

    Precision is the token's own decimal digits — an integer matches at whole
    numbers, "27.3" at one decimal place. Rounding is half-up (the honest
    reader's convention), computed in ``Decimal`` so float repr noise in a
    derived share cannot flip a match.
    """
    normalized = token.replace(",", "")
    target = Decimal(normalized)
    places = len(normalized.partition(".")[2])
    exponent = Decimal(1).scaleb(-places)
    matched = [
        value
        for value in whitelist
        if Decimal(repr(value)).quantize(exponent, rounding=ROUND_HALF_UP) == target
    ]
    return min(matched) if matched else None


def _sentence_spans(prose: str) -> list[tuple[int, int]]:
    """The prose as consecutive sentence spans, boundaries never inside quotations.

    Each span runs through its terminal punctuation and the whitespace that
    follows, so concatenating survivors preserves the original spacing
    (paragraph breaks ride the trailing whitespace of the sentence before
    them). Trailing text with no terminator is a final span of its own.
    """
    pairs, _ = _quote_pairs(prose)
    spans: list[tuple[int, int]] = []
    start = 0
    for match in _SENTENCE_END.finditer(prose):
        if _inside_any(match.start(), pairs):
            continue
        end = match.end()
        while end < len(prose) and prose[end].isspace():
            end += 1
        spans.append((start, end))
        start = end
    if start < len(prose):
        spans.append((start, len(prose)))
    return spans
