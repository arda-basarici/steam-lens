"""The numeric-grounding gate — whitelist derivation, the scan, and the cut.

The claims that matter: honest rounding passes and laundering dies (the gate's
reason to exist), candidate values never reach the whitelist (the two-stratum
ruling enforced structurally), quotations verify verbatim with numerals inside
them exempt, and the sentence cut removes exactly the condemned sentences while
survivors keep their text.
"""

import pytest

from steamlens.contracts import (
    AspectAggregate,
    AspectSlot,
    ClassifierVersions,
    EvidenceQuote,
    Sentiment,
    SentimentCounts,
    SpanKind,
)
from steamlens.core.grounding import (
    derive_whitelist,
    drop_violating_sentences,
    ground,
    normalize_quotes,
)

_VERSIONS = ClassifierVersions(
    model_version="m", prompt_version="p", ontology_version="o"
)


def _aggregate(
    aspect: str,
    slot: AspectSlot,
    reviews: int,
    *,
    positive: int = 0,
    negative: int = 0,
    sample_size: int = 1_000,
) -> AspectAggregate:
    return AspectAggregate(
        app_id=10,
        aspect=aspect,
        slot=slot,
        reviews_with_aspect=reviews,
        counts=SentimentCounts(positive=positive, negative=negative, mixed=0, neutral=0),
        sample_size=sample_size,
        versions=_VERSIONS,
        manifest_id="manifest",
    )


def _evidence(review_id: str, text: str) -> EvidenceQuote:
    return EvidenceQuote(
        review_id=review_id, aspect="combat", sentiment=Sentiment.NEGATIVE, text=text
    )


# --- the whitelist ---


def test_whitelist_derives_counts_and_shares_from_pinned_aggregates() -> None:
    """A pinned aggregate contributes its count, its share, sentiment counts and
    their shares of both denominators — the honest derivations, nothing else."""
    values = derive_whitelist(
        [_aggregate("combat", AspectSlot.PINNED, 273, negative=210, positive=63)],
        sample_size=1_000,
    )
    for expected in (1_000.0, 273.0, 27.3, 210.0, 21.0, 63.0):
        assert expected in values
    assert 210 / 273 * 100 in values  # sentiment share of the mention count


def test_whitelist_excludes_candidate_aggregates_by_ruling() -> None:
    """Themes enter prose as names, never numbers — a candidate count has no match."""
    values = derive_whitelist(
        [_aggregate("grind", AspectSlot.CANDIDATE, 300, negative=300)],
        sample_size=1_000,
    )
    assert 300.0 not in values
    assert 30.0 not in values


def test_whitelist_admits_shell_supplied_job_values() -> None:
    """extra_values is the door for claimed totals and histogram volumes."""
    values = derive_whitelist([], sample_size=1_000, extra_values=[45_210.0, 2024.0])
    assert 45_210.0 in values
    assert 2024.0 in values


# --- the numeric scan ---


def test_exact_and_honestly_rounded_numerals_certify() -> None:
    """273 exact, 27% from a 27.3 share, and a comma-grouped 1,000 all ground."""
    whitelist = frozenset({273.0, 27.3, 1_000.0})
    report = ground(
        "Of 1,000 reviews, 273 (27%) raise performance; 27.3% is the precise share.",
        whitelist,
        (),
    )
    assert report.passed
    assert [span.text for span in report.certified] == ["1,000", "273", "27", "27.3"]
    assert report.certified[2].value == pytest.approx(27.3)


def test_the_laundering_numeral_dies_at_its_own_precision() -> None:
    """'roughly 40%' over a 27.3 share has no match — the case the gate exists for."""
    report = ground("Roughly 40% complain about performance.", frozenset({27.3}), ())
    assert not report.passed
    assert report.violations[0].text == "40"
    assert report.violations[0].kind is SpanKind.NUMERAL


def test_precision_is_the_numerals_own_not_the_whitelists() -> None:
    """27 passes against 27.3, but 27.0 does not — one decimal place claims tenths."""
    whitelist = frozenset({27.3})
    assert ground("27% mention it.", whitelist, ()).passed
    assert not ground("27.0% mention it.", whitelist, ()).passed


# --- quotations ---


def test_verbatim_quotes_certify_with_their_source_and_shield_their_numerals() -> None:
    """A quoted sub-span verifies against evidence, carries the review id, and the
    '60' inside it needs no whitelist entry."""
    evidence = [_evidence("r7", "barely holds 60 fps on a 4090, embarrassing")]
    report = ground('One player wrote "barely holds 60 fps" and refunded.', frozenset(), evidence)
    assert report.passed
    quote = report.certified[0]
    assert (quote.kind, quote.review_id) == (SpanKind.QUOTE, "r7")
    assert quote.text == '"barely holds 60 fps"'


def test_a_fabricated_quote_is_a_violation() -> None:
    """A quotation that is no evidence substring fails — the compose-side mirror
    of the write-time verbatim check."""
    evidence = [_evidence("r7", "barely holds 60 fps on a 4090")]
    report = ground('They said "runs perfectly everywhere".', frozenset(), evidence)
    assert [violation.kind for violation in report.violations] == [SpanKind.QUOTE]


def test_curly_typography_normalizes_before_the_scan() -> None:
    """A model emitting curly quotes still grounds — normalize first, then judge."""
    evidence = [_evidence("r7", "barely holds 60 fps on a 4090")]
    prose = normalize_quotes("One wrote “barely holds 60 fps” and left.")
    assert ground(prose, frozenset(), evidence).passed


def test_empty_and_unpaired_quotation_marks_are_violations() -> None:
    """An empty pair and an odd trailing mark each surface — never silently passed."""
    empty = ground('An "" quote.', frozenset(), ())
    assert empty.violations[0].reason == "empty quotation"
    unpaired = ground('A dangling " mark.', frozenset(), ())
    assert unpaired.violations[0].reason == "unpaired quotation mark"


# --- the cut ---


def test_drop_removes_exactly_the_condemned_sentences() -> None:
    """The violating middle sentence goes; both neighbors keep their text."""
    prose = "Combat lands well. Roughly 40% complain. Audio holds up."
    report = ground(prose, frozenset(), ())
    assert drop_violating_sentences(prose, report) == "Combat lands well. Audio holds up."


def test_drop_never_splits_inside_a_quotation() -> None:
    """Terminal punctuation inside a verified quote is not a sentence boundary."""
    evidence = [_evidence("r7", "It stutters. Constantly. Everywhere I go")]
    prose = 'One wrote "It stutters. Constantly." and 99 agreed. The rest moved on.'
    report = ground(prose, frozenset(), evidence)
    assert [violation.text for violation in report.violations] == ["99"]
    assert drop_violating_sentences(prose, report) == "The rest moved on."


def test_drop_can_leave_nothing() -> None:
    """Every sentence condemned returns empty — the ladder's withholding rung decides next."""
    prose = "Roughly 40% complain."
    report = ground(prose, frozenset(), ())
    assert drop_violating_sentences(prose, report) == ""
