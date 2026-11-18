"""What the answer call is given to read — the fetch's pure half.

Between the pick call and the answer call, code reads reviews for the pick's
candidates. Which pairs of a game and a want are read is ``core.pick``'s
``ReadPlan``. This module says how each is read and puts the result
together; the reading itself is the shell's (``chat.fetch``).

A want is read one of two ways, by its target. An aspect is read by label:
the reviews the classifier marked with it. Everything else that has reviews
is read by words: a search term's phrases, and for a store fact the search
words its vocabulary entry carries, since a store fact names no review.

The assembled material is one entry per candidate in the pick's order, with
a line per want. A want's line carries the reading in words and no count,
whether its reviews were read, and the excerpts. The three ways a want can
have no excerpts are kept apart, because a reply has to say different
things for them: nothing could be read, the read budget did not reach it,
or it was read. A planned read that comes back empty counts as nothing to
read: an aspect too few reviews mention, or matches that all contain
"spoiler".

Every excerpt gets an identifier, ``e1`` and on, in the order the material
is laid out. Like a game's identifier in the pick call it is made for one
turn and means nothing outside it; a reply cites it, and the check leads it
back to the review and the game.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass

from steamlens.contracts import (
    AspectTarget,
    CandidatesDecision,
    CandidatesMaterial,
    CitedExcerpt,
    Excerpt,
    GameMaterial,
    LibraryGame,
    NamedSideMaterial,
    PlayerRequest,
    ReadState,
    Sheet,
    StoreFactTarget,
    TermTarget,
    WantMaterial,
    WantTarget,
)
from steamlens.core.game_names import referenced_game
from steamlens.core.pick import ReadPlan
from steamlens.core.store_facts import store_fact


@dataclass(frozen=True, slots=True)
class AspectRead:
    """Read the reviews labelled with one pinned aspect."""

    aspect: str


@dataclass(frozen=True, slots=True)
class WordsRead:
    """Read the reviews that match any of these phrases, best match first."""

    phrases: tuple[str, ...]


type ReviewRead = AspectRead | WordsRead
"""How a game's reviews are read for one target."""


@dataclass(frozen=True, slots=True)
class NamedSideRead:
    """The named game's side of one comparison, as read.

    ``want`` is the position of the relative want, ``game`` the library
    game the player named, and ``excerpts`` what its reviews gave.
    """

    want: int
    game: LibraryGame
    excerpts: tuple[Excerpt, ...]


def review_read(target: WantTarget | None) -> ReviewRead | None:
    """How reviews are read for ``target``, or ``None`` when it has no reviews behind it.

    A release year and a want with no target have none. A store fact is
    read through the search words of its vocabulary entry.

    >>> review_read(AspectTarget("story"))
    AspectRead(aspect='story')
    >>> review_read(StoreFactTarget("online-co-op")).phrases[0]
    'online co-op'
    >>> review_read(None) is None
    True
    """
    match target:
        case AspectTarget(aspect=aspect):
            return AspectRead(aspect)
        case TermTarget(phrases=phrases):
            return WordsRead(phrases)
        case StoreFactTarget(key=key):
            words = store_fact(key).search_words
            return WordsRead(words) if words else None
        case _:
            return None


def named_sides_to_read(request: PlayerRequest, plan: ReadPlan) -> tuple[tuple[int, int], ...]:
    """The comparisons whose named game is read: each as a want position and that game's app id.

    One entry for each want that is relative to a named game, is read for
    at least one candidate under ``plan``, and whose named game resolved to
    a library game. A comparison no candidate is read on needs no other
    side, and a game the library has not measured has no reviews to read.
    """
    read_wants = {position for _, position in plan.pairs}
    sides: list[tuple[int, int]] = []
    for position, want in enumerate(request.wants):
        if want.compared_to is None or position not in read_wants:
            continue
        named = referenced_game(want.compared_to, request.named_games)
        if named is not None and named.app_id is not None:
            sides.append((position, named.app_id))
    return tuple(sides)


def candidates_material(
    request: PlayerRequest,
    sheet: Sheet,
    decision: CandidatesDecision,
    plan: ReadPlan,
    excerpts: Mapping[tuple[int, int], Sequence[Excerpt]],
    named_sides: Sequence[NamedSideRead] = (),
) -> CandidatesMaterial:
    """Put a recommendation turn's fetched material together for the answer call.

    ``plan`` is the read plan of ``decision`` (``core.pick.read_plan``) and
    ``excerpts`` what each of its pairs gave, keyed by app id and want
    position. ``named_sides`` are the named games' sides, read once each.

    A want's ``read`` is ``READ`` when its pair gave excerpts,
    ``CUT_BY_CAP`` when the plan cut the pair, and ``NOTHING_TO_READ``
    otherwise, which covers a pair that was read and came back empty.
    Identifiers run ``e1`` and on through the games in the pick's order,
    each game's wants in the request's order, then the named sides.

    Raises ``ValueError`` for a candidate that is not a row of ``sheet``.
    """
    rows = {row.game.app_id: row for row in sheet.rows}
    cut = set(plan.cut)
    identifiers = _identifiers()
    games: list[GameMaterial] = []
    for candidate in decision.candidates:
        row = rows.get(candidate.app_id)
        if row is None:
            raise ValueError(
                f"candidate {candidate.app_id} is not a row of the sheet — material is put"
                " together against the sheet the decision was made from"
            )
        wants: list[WantMaterial] = []
        for position, reading in enumerate(row.readings):
            pair = (candidate.app_id, position)
            cited = _cited(excerpts.get(pair, ()), identifiers)
            if cited:
                state = ReadState.READ
            elif pair in cut:
                state = ReadState.CUT_BY_CAP
            else:
                state = ReadState.NOTHING_TO_READ
            wants.append(
                WantMaterial(
                    status=reading.status,
                    finding=reading.finding,
                    read=state,
                    group=reading.group,
                    on_game=reading.on_game,
                    on_named_game=reading.on_named_game,
                    excerpts=cited,
                )
            )
        storefront = row.game.storefront
        games.append(
            GameMaterial(
                app_id=row.game.app_id,
                title=row.game.name,
                description=storefront.short_description if storefront is not None else "",
                standing=row.standing,
                wants=tuple(wants),
            )
        )
    return CandidatesMaterial(
        games=tuple(games),
        named_sides=tuple(
            NamedSideMaterial(
                want=side.want,
                app_id=side.game.app_id,
                title=side.game.name,
                excerpts=_cited(side.excerpts, identifiers),
            )
            for side in named_sides
        ),
    )


def _identifiers() -> Iterator[str]:
    number = 0
    while True:
        number += 1
        yield f"e{number}"


def _cited(excerpts: Sequence[Excerpt], identifiers: Iterator[str]) -> tuple[CitedExcerpt, ...]:
    return tuple(CitedExcerpt(next(identifiers), excerpt) for excerpt in excerpts)
