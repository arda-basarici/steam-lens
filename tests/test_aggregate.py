"""Aggregate-fold tests — the number mint's behavioral claims.

Every test builds ``MentionRow`` inputs directly (pure core: data in → data out,
no store involved) and asserts one property of the fold: per-game isolation, the
denominator/numerator split, the pinned/candidate strata, faithful raw tallies
(singletons kept, no floor), deterministic ordering, and the two loud
input-inconsistency guards.
"""

from __future__ import annotations

import pytest

from steamlens.contracts import (
    AspectAggregate,
    AspectSlot,
    ClassifierVersions,
    Sentiment,
    SentimentCounts,
)
from steamlens.core.aggregate import MentionRow, aggregate

_VERSIONS = ClassifierVersions(
    model_version="deepseek-v4-flash", prompt_version="classify-v1", ontology_version="v2"
)
_MANIFEST = "census-fold-test"


def _row(
    app_id: int,
    review_id: str,
    aspect: str,
    sentiment: Sentiment = Sentiment.POSITIVE,
    slot: AspectSlot = AspectSlot.PINNED,
) -> MentionRow:
    return MentionRow(
        app_id=app_id, review_id=review_id, aspect=aspect, slot=slot, sentiment=sentiment
    )


def _fold(rows: list[MentionRow], sizes: dict[int, int]) -> tuple[AspectAggregate, ...]:
    return aggregate(rows, sizes, versions=_VERSIONS, manifest_id=_MANIFEST)


def _find(aggregates: tuple[AspectAggregate, ...], app_id: int, aspect: str) -> AspectAggregate:
    return next(a for a in aggregates if a.app_id == app_id and a.aspect == aspect)


def _total(counts: SentimentCounts) -> int:
    return counts.positive + counts.negative + counts.mixed + counts.neutral


def test_folds_per_game_without_bleed() -> None:
    """The same aspect in two games mints two independent numbers, never a blend."""
    rows = [
        _row(10, "r1", "combat", Sentiment.POSITIVE),
        _row(10, "r2", "combat", Sentiment.NEGATIVE),
        _row(20, "r3", "combat", Sentiment.POSITIVE),
    ]
    aggregates = _fold(rows, {10: 2, 20: 1})
    assert _find(aggregates, 10, "combat").counts == SentimentCounts(1, 1, 0, 0)
    assert _find(aggregates, 20, "combat").counts == SentimentCounts(1, 0, 0, 0)


def test_pinned_and_candidate_both_fold_with_slot_preserved() -> None:
    """Candidates fold alongside pinned aspects; the slot rides onto the record."""
    rows = [
        _row(10, "r1", "combat", slot=AspectSlot.PINNED),
        _row(10, "r2", "boss design", slot=AspectSlot.CANDIDATE),
    ]
    aggregates = _fold(rows, {10: 2})
    assert _find(aggregates, 10, "combat").slot is AspectSlot.PINNED
    assert _find(aggregates, 10, "boss design").slot is AspectSlot.CANDIDATE


def test_sentiment_breakdown_is_tallied() -> None:
    """Each polarity lands in its own count; the four sum to the mention total."""
    rows = [
        _row(10, "r1", "story", Sentiment.POSITIVE),
        _row(10, "r2", "story", Sentiment.NEGATIVE),
        _row(10, "r3", "story", Sentiment.MIXED),
        _row(10, "r4", "story", Sentiment.NEUTRAL),
    ]
    assert _find(_fold(rows, {10: 4}), 10, "story").counts == SentimentCounts(1, 1, 1, 1)


def test_reviews_with_aspect_counts_distinct_reviews() -> None:
    """One review mentioning an aspect twice counts once in reviews, twice in totals.

    The contract's "differs when a review mentions an aspect twice" case: the fold
    computes reviews and mention totals independently, so it stays correct even if
    upstream collapse is ever bypassed.
    """
    rows = [
        _row(10, "r1", "grind", Sentiment.NEGATIVE, slot=AspectSlot.CANDIDATE),
        _row(10, "r1", "grind", Sentiment.POSITIVE, slot=AspectSlot.CANDIDATE),
    ]
    agg = _find(_fold(rows, {10: 1}), 10, "grind")
    assert agg.reviews_with_aspect == 1
    assert _total(agg.counts) == 2


def test_reviews_with_aspect_equals_total_without_duplicates() -> None:
    """Distinct reviews make reviews_with_aspect equal the mention sum — the census invariant.

    This is the miniature of the property the real-census smoke asserts wholesale:
    with classify's per-review collapse upstream, the two quantities coincide.
    """
    rows = [_row(10, f"r{i}", "combat") for i in range(3)]
    agg = _find(_fold(rows, {10: 3}), 10, "combat")
    assert agg.reviews_with_aspect == _total(agg.counts)


def test_singleton_candidate_mints_a_thin_row() -> None:
    """A once-seen candidate is minted, not floored — the tally stays faithful."""
    agg = _find(_fold([_row(10, "r1", "weird inventory ui", slot=AspectSlot.CANDIDATE)], {10: 5}),
                10, "weird inventory ui")
    assert agg.reviews_with_aspect == 1
    assert agg.slot is AspectSlot.CANDIDATE


def test_sample_size_is_the_denominator_including_empties() -> None:
    """sample_size comes from the map, so it exceeds the aspect's reviews as it should."""
    agg = _find(_fold([_row(10, "r1", "combat")], {10: 100}), 10, "combat")
    assert agg.sample_size == 100
    assert agg.reviews_with_aspect == 1


def test_all_empty_game_mints_no_aggregate() -> None:
    """A game present only as a denominator (every review empty) yields no rows."""
    aggregates = _fold([_row(10, "r1", "combat")], {10: 2, 20: 5})
    assert all(a.app_id != 20 for a in aggregates)
    assert any(a.app_id == 10 for a in aggregates)


def test_versions_and_manifest_stamped_on_every_row() -> None:
    """Every minted number carries the folded versions and the sample's manifest."""
    aggregates = _fold([_row(10, "r1", "combat"), _row(20, "r2", "story")], {10: 1, 20: 1})
    assert aggregates
    assert all(a.versions == _VERSIONS and a.manifest_id == _MANIFEST for a in aggregates)


def test_output_is_deterministically_ordered() -> None:
    """Order is (app_id, slot, aspect) and independent of the input row order."""
    rows = [
        _row(20, "r3", "combat"),
        _row(10, "r2", "story", slot=AspectSlot.CANDIDATE),
        _row(10, "r1", "combat", slot=AspectSlot.PINNED),
    ]
    aggregates = _fold(rows, {10: 2, 20: 1})
    keys = [(a.app_id, a.slot.value, a.aspect) for a in aggregates]
    assert keys == sorted(keys)
    assert aggregates == _fold(list(reversed(rows)), {10: 2, 20: 1})


def test_mention_without_a_sample_size_fails_loud() -> None:
    """A mention for a game absent from the denominator map is an inconsistency, not a guess."""
    with pytest.raises(ValueError, match="no sample size"):
        _fold([_row(10, "r1", "combat")], {20: 1})


def test_reviews_exceeding_sample_size_fails_loud() -> None:
    """A numerator larger than its denominator means leakage — crash, don't mint it."""
    with pytest.raises(ValueError, match="outside the counted sample"):
        _fold([_row(10, "r1", "combat"), _row(10, "r2", "combat")], {10: 1})


def test_empty_inputs_yield_empty() -> None:
    """No mentions folds to nothing, whether or not denominators are present."""
    assert _fold([], {}) == ()
    assert _fold([], {10: 5}) == ()
