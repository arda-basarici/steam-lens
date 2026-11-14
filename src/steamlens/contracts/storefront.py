"""The storefront records — what the store says a game is, apart from its reviews.

An aspect profile says how reviewers feel about parts of a game. It does not
say what kind of game it is, and the recommender chat's hard filters (a racing
game, co-op, runs on Mac) need exactly that. These records carry the store's
own answer: ``StorefrontMetadata`` is the part of one appdetails read the
filters use, and ``StorefrontTagCapture`` is the community tag block of one
store page.

Both describe the game on the day they were read, which is why each carries
its ``captured_at``. The store revises these facts: a game gains a platform,
and its release date moves to the full release when it leaves early access.
A report is a frozen sample and must not be rewritten when that happens, so
the records are kept per game, beside the reports and not inside them.

The tags are held apart from the metadata because they come from a different
page, can fail on their own, and have a different job: they are recorded as an
outside reference for grading review search and are not given to the chat.

Like every contract these hold already-parsed data. The wire's oddities (genre
ids as strings, a release date as display text) are the ``steam_client``
shell's work.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Final

EARLY_ACCESS_GENRE_ID: Final = 70
"""The genre row the store adds to a game in early access (probed 2026-11-14
on two such games; a game that has left early access no longer carries it)."""


@dataclass(frozen=True, slots=True)
class StorefrontLabel:
    """One genre or category row as the store lists it.

    ``id`` is the stable key. ``description`` is display text and is not
    unique: two category ids can share one description (the store lists
    "DualSense Controller Support" under both 57 and 58), so a filter that
    means one specific thing compares ids.
    """

    id: int
    description: str


@dataclass(frozen=True, slots=True)
class StorefrontMetadata:
    """The filterable part of one appdetails read for one game.

    ``genres`` and ``categories`` keep the store's own order. The platform
    flags are the store's ``platforms`` object. ``release_date_text`` is the
    store's display string, verbatim (``"Sep 17, 2020"`` at the door's
    parameters), and ``release_date`` is that string as a date, ``None`` when
    the store gave none or gave something that is not a full date (an
    unreleased game can say ``"Coming soon"`` or a bare year). For a game in
    early access the date is its early access launch; once the game leaves
    early access the store replaces it with the full release date.
    ``short_description`` is the store's one-paragraph blurb, empty when the
    store has none. Price is deliberately absent: it changes, varies by
    region, and adds nothing to review evidence.

    >>> from datetime import UTC
    >>> hades = StorefrontMetadata(
    ...     app_id=1145360,
    ...     genres=(StorefrontLabel(1, "Action"), StorefrontLabel(3, "RPG")),
    ...     categories=(StorefrontLabel(2, "Single-player"),),
    ...     windows=True, mac=True, linux=False,
    ...     release_date_text="Sep 17, 2020", release_date=date(2020, 9, 17),
    ...     coming_soon=False, short_description="Defy the god of the dead.",
    ...     captured_at=datetime(2026, 11, 14, tzinfo=UTC),
    ... )
    >>> hades.in_early_access
    False
    """

    app_id: int
    genres: tuple[StorefrontLabel, ...]
    categories: tuple[StorefrontLabel, ...]
    windows: bool
    mac: bool
    linux: bool
    release_date_text: str | None
    release_date: date | None
    coming_soon: bool
    short_description: str
    captured_at: datetime

    @property
    def in_early_access(self) -> bool:
        """Whether the store listed the game as early access when this was read."""
        return any(genre.id == EARLY_ACCESS_GENRE_ID for genre in self.genres)


@dataclass(frozen=True, slots=True)
class StorefrontTag:
    """One community tag on a store page.

    ``count`` is the number the store attaches to the tag. It orders the tags
    on one page and is not comparable across games: a game with 72 stored
    reviews showed counts above 400 (probed 2026-11-14).
    """

    tag_id: int
    name: str
    count: int


@dataclass(frozen=True, slots=True)
class StorefrontTagCapture:
    """The tag block of one store page, in the store's order, with its read date.

    The page carries at most the top twenty tags, so a tag missing here is not
    evidence that the game lacks the trait. An empty ``tags`` is a real
    answer (a page with no tags yet) and differs from a game never captured.
    """

    app_id: int
    tags: tuple[StorefrontTag, ...]
    captured_at: datetime
