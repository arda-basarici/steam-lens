"""The sheet records — one game's reading on one aspect, as the recommender chat compares games.

A report's aggregate is certified inside that report. Read across games it
needs a second layer: the samples differ in size, a sentiment share on seven
mentions means nothing, and a five-point gap between two games is noise. A
``SheetCell`` is that layer for one game and one pinned aspect: the stored
counts, unchanged, plus the group the game falls in.

The cell carries no number the report does not already hold. Its two shares
are read off the same counts, and they answer different questions, so they
stay apart: how much the game's reviews talk about the aspect, and how
positive that talk is.
"""

from __future__ import annotations

from dataclasses import dataclass

from steamlens.contracts.aggregate import SentimentCounts
from steamlens.contracts.enums import SentimentGroup


@dataclass(frozen=True, slots=True)
class SheetCell:
    """One game's reading on one pinned aspect.

    ``mentions`` is the number of sampled reviews that mention the aspect and
    ``sample_size`` the number of sampled reviews, both from the game's
    report. ``counts`` is the sentiment breakdown of those mentions.
    ``group`` is where the game stands on this aspect among the library's
    games.

    >>> cell = SheetCell(
    ...     aspect="combat", mentions=45, sample_size=602,
    ...     counts=SentimentCounts(positive=41, negative=4, mixed=0, neutral=0),
    ...     group=SentimentGroup.STRONGLY_POSITIVE,
    ... )
    >>> round(cell.mention_share, 3), round(cell.positive_share, 3)
    (0.075, 0.911)
    """

    aspect: str
    mentions: int
    sample_size: int
    counts: SentimentCounts
    group: SentimentGroup

    @property
    def mention_share(self) -> float:
        """The share of sampled reviews that mention the aspect: how much the game is about it."""
        return self.mentions / self.sample_size

    @property
    def positive_share(self) -> float:
        """The share of those mentions that are positive. Mixed and neutral count against it."""
        return self.counts.positive / self.mentions
