"""The sheet's group rule — where a game stands on an aspect when games are compared.

Pure functions from a report's stored aggregates to ``SheetCell`` records. The
rule is DESIGN's "The sheet": a mention floor below which a game has no
reading on an aspect, then groups set by where the sentiment share's interval
starts. Beside it sits the one rule for wants the aspects cannot express:
when a search term counts as clustering in a game's reviews.

The sentiment share is the positive mentions over every review that mentions
the aspect, with mixed and neutral mentions in the denominator, since a mixed
mention is not praise. Its interval is a plain Wilson interval on the
mentions. That interval is not the one the report page draws: the sampling
study calibrated the mention share and treated the sentiment mix as
descriptive, so nothing certifies this interval for the windowed draw. It
prices sampling noise on that many mentions and nothing more, and the groups
are a policy for reading across games, not a measurement.

The four constants are working values, cheap to move here and expensive to
move once measurements have been taken against them. They are to be re-read
on development cases, never tuned on reported ones.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final

from steamlens.contracts import (
    AspectAggregate,
    AspectSlot,
    SentimentCounts,
    SentimentGroup,
    SheetCell,
)
from steamlens.core.intervals import wilson_interval

MENTION_FLOOR: Final = 30
"""Fewer sampled reviews than this mention the aspect: no reading. At 30 the
widest interval is about 17 points either way; 20 would admit 20 points, and
50 leaves few aspects readable across many games."""

STRONG_LINE: Final = 0.70
"""The positive share's interval starts above this: strongly positive."""

MAJORITY_LINE: Final = 0.50
"""The positive (or negative) share's interval starts above this: a clear majority."""

SPLIT_HALF_WIDTH: Final = 0.15
"""No clear majority and an interval at most this wide either way: opinion is
split. Wider than this and the sample cannot say."""

TERM_SHARE_FLOOR: Final = 0.02
"""A search term clusters in a game when at least this share of the game's
counted reviews match it. Read against the store's tags on 2026-11-14, 2%
nominated no untagged game for "roguelike", "metroidvania", "racing" or "city
builder". It is too low for a word that names a part of many games
("puzzle"), which no single share separates."""

TERM_MIN_HITS: Final = 3
"""And at least this many matching reviews, so one or two reviews in a small
sample do not make a cluster."""


def sentiment_group(counts: SentimentCounts, mentions: int) -> SentimentGroup:
    """The group for one game on one aspect, from its stored counts.

    ``mentions`` is the number of sampled reviews mentioning the aspect, and
    ``counts`` their sentiment breakdown. The two must agree (the counts sum
    to the mentions, which the classify stage guarantees by collapsing
    repeats); a mismatch raises ``ValueError``, because the rule was set on
    shares of reviews and would mean something else on shares of mentions.

    >>> sentiment_group(SentimentCounts(41, 4, 0, 0), 45)
    <SentimentGroup.STRONGLY_POSITIVE: 'strongly-positive'>
    >>> sentiment_group(SentimentCounts(49, 25, 4, 0), 78)
    <SentimentGroup.MOSTLY_POSITIVE: 'mostly-positive'>
    >>> sentiment_group(SentimentCounts(7, 0, 0, 0), 7)
    <SentimentGroup.TOO_FEW_MENTIONS: 'too-few-mentions'>
    """
    total = counts.positive + counts.negative + counts.mixed + counts.neutral
    if total != mentions:
        raise ValueError(
            f"sentiment counts sum to {total} but {mentions} reviews mention the aspect — "
            "the group rule reads shares of reviews and needs the two to agree"
        )
    if mentions < MENTION_FLOOR:
        return SentimentGroup.TOO_FEW_MENTIONS
    praise = wilson_interval(counts.positive, mentions)
    if praise.low > STRONG_LINE:
        return SentimentGroup.STRONGLY_POSITIVE
    if praise.low > MAJORITY_LINE:
        return SentimentGroup.MOSTLY_POSITIVE
    if wilson_interval(counts.negative, mentions).low > MAJORITY_LINE:
        return SentimentGroup.CLEARLY_NEGATIVE
    if (praise.high - praise.low) / 2 <= SPLIT_HALF_WIDTH:
        return SentimentGroup.SPLIT
    return SentimentGroup.UNCLEAR


def term_clusters(hits: int, sample_size: int) -> bool:
    """Whether a search term clusters in a game: ``hits`` of ``sample_size`` reviews match.

    Only a cluster is evidence. For something the player wants, a cluster
    puts the game forward; for something the player wants to avoid, a
    cluster counts against it. The absence of a cluster says nothing in
    either case: reviewers of the game that defines a kind rarely use the
    word for it, a store feature is rarely stated in a review at all, and a
    word like "grind" turns up at a low share in most games.

    >>> term_clusters(77, 602), term_clusters(8, 549), term_clusters(2, 72)
    (True, False, False)
    """
    if sample_size < 1:
        raise ValueError(f"sample_size is {sample_size} — a share needs at least one review")
    if not 0 <= hits <= sample_size:
        raise ValueError(f"{hits} matching reviews out of {sample_size} is incoherent")
    return hits >= TERM_MIN_HITS and hits / sample_size >= TERM_SHARE_FLOOR


def sheet_cells(aggregates: Iterable[AspectAggregate]) -> tuple[SheetCell, ...]:
    """One report's aggregates as sheet cells, pinned aspects only, by aspect name.

    Candidate aspects are left out: they are the uncalibrated stratum, and
    one concept fragments across many free-form strings, so a count under any
    one of them is not comparable between games. The order is alphabetical,
    which carries no reading.
    """
    return tuple(
        SheetCell(
            aspect=aggregate.aspect,
            mentions=aggregate.reviews_with_aspect,
            sample_size=aggregate.sample_size,
            counts=aggregate.counts,
            group=sentiment_group(aggregate.counts, aggregate.reviews_with_aspect),
        )
        for aggregate in sorted(aggregates, key=lambda a: a.aspect)
        if aggregate.slot is AspectSlot.PINNED
    )
