"""The sheet records — how the library reads against one request.

A report's aggregate is certified inside that report. Read across games it
needs a second layer: the samples differ in size, a sentiment share on seven
mentions means nothing, and a five-point gap between two games is noise. A
``SheetCell`` is that layer for one game and one pinned aspect: the stored
counts, unchanged, plus the group the game falls in.

The cell carries no number the report does not already hold. Its two shares
are read off the same counts, and they answer different questions, so they
stay apart: how much the game's reviews talk about the aspect, and how
positive that talk is.

The rest is the sheet itself. A ``LibraryGame`` is everything stored about
one game that a request can be read against. A ``WantReading`` is one want
read on one game, with a ``SideFinding`` for each game of a comparison when
the want is relative to a named game. A ``SheetRow`` is a game with a
reading per want, and a ``Sheet`` is every library game as a row. The sheet
is a reading handed to the chat's judge, not a selection: no game is left
off it on evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from steamlens.contracts.aggregate import SentimentCounts
from steamlens.contracts.enums import MustStanding, SentimentGroup, WantFinding, WantStatus
from steamlens.contracts.storefront import StorefrontMetadata, StorefrontTagCapture


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


@dataclass(frozen=True, slots=True)
class LibraryGame:
    """One library game as a request is read against it.

    The game is represented by its newest report: ``run_id`` names it,
    ``reported_at`` dates it, ``sample_size`` is the number of reviews it
    counted, ``complete_count`` says whether that was every review the game
    had, and ``labeler`` is the model version that labelled them. Every
    reading describes that stored sample and says nothing about reviews
    written since.

    ``cells`` hold one entry per pinned aspect at least one sampled review
    mentions; an aspect missing from them was mentioned by none.
    ``storefront`` and ``tags`` are the latest captures of the store's facts
    and the community tag block, each ``None`` when never captured, which is
    different from a game without genres or without tags.
    """

    app_id: int
    name: str
    run_id: str
    reported_at: datetime
    sample_size: int
    complete_count: bool
    labeler: str
    cells: tuple[SheetCell, ...]
    storefront: StorefrontMetadata | None
    tags: StorefrontTagCapture | None


@dataclass(frozen=True, slots=True)
class SideFinding:
    """What a want's target shows on one of the two games of a comparison.

    The finding the target would get on that game if the want were not
    relative, and the group when the target is an aspect. It holds no status
    and no match count: code gives a relative want no verdict, and two
    counts are never set side by side.
    """

    finding: WantFinding
    group: SentimentGroup | None = None


@dataclass(frozen=True, slots=True)
class WantReading:
    """One want read on one game: the status, and what was looked at.

    ``group`` is set for a want on an aspect, so the wording can tell "mostly
    criticised" from "opinions are divided" under the same status. ``hits``
    is set for a want on a search term: how many of the game's counted
    reviews match, which is also how many the judge could read.

    A want relative to a named game always reads "cannot tell" and carries
    neither of those. ``on_game`` is what its target shows on this game and
    ``on_named_game`` what it shows on the named one, which is absent when
    the library has not measured that game or the name did not resolve to
    one. The comparison is made in words by the step that reads reviews of
    both.

    >>> reading = WantReading(
    ...     WantStatus.CANNOT_TELL, WantFinding.RELATIVE_TO_NAMED_GAME,
    ...     on_game=SideFinding(WantFinding.TERM_BELOW_CLUSTER),
    ...     on_named_game=SideFinding(WantFinding.NOT_WRITTEN_ABOUT),
    ... )
    >>> reading.hits is None
    True
    """

    status: WantStatus
    finding: WantFinding
    group: SentimentGroup | None = None
    hits: int | None = None
    on_game: SideFinding | None = None
    on_named_game: SideFinding | None = None


@dataclass(frozen=True, slots=True)
class SheetRow:
    """One library game read against a request.

    ``readings`` are in the order of the request's wants, one each.
    ``standing`` sums up the readings on the wants that are musts.
    ``like_this`` marks a game the player named as the kind of thing they
    want ("something like Hades"). It stays on the sheet, since a comparison
    reads it, and it is never offered back to the player.
    """

    game: LibraryGame
    readings: tuple[WantReading, ...]
    standing: MustStanding
    like_this: bool = False


@dataclass(frozen=True, slots=True)
class WantTally:
    """How the sheet's games divide on one want."""

    matches: int
    fails: int
    cannot_tell: int


@dataclass(frozen=True, slots=True)
class Sheet:
    """The library read against one request.

    ``rows`` hold every library game except two kinds, both left off on the
    player's say and never on evidence: the ones the player said they had
    already played, whose app ids are in ``already_played``, and, when the
    player asked for other games, the ones the chat already offered, in
    ``earlier_offers`` in the order they were first offered. The rows are
    grouped by standing (meets the musts, open on a must, conflicts with
    one) and ordered by app id inside a group, an order that carries no
    reading. That is the record's order: the pick call's render lays the
    rows out again, by pattern and by a seeded shuffle inside one.
    ``tallies`` are in the order of the request's wants and count over the
    rows.
    """

    rows: tuple[SheetRow, ...]
    tallies: tuple[WantTally, ...]
    already_played: tuple[int, ...]
    earlier_offers: tuple[int, ...] = ()
