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

A turn about one game has no pick and no plan. Each thing the player asked
is read by its target the same way, up to a fixed number of subjects, and a
subject on a store fact is read whether or not the store lists it. Two
questions have no target of their own. "Would it suit me" reads the game
against the wants that still stand, as a candidate is read. A question about
the game in general, from a player who has stated no wants, gets the aspects
its reviewers praise strongly and the ones they criticise or are divided on,
as groups.

Every excerpt gets an identifier, ``e1`` and on, in the order the material
is laid out. Like a game's identifier in the pick call it is made for one
turn and means nothing outside it; a reply cites it, and the check leads it
back to the review and the game.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from steamlens.contracts import (
    AspectStanding,
    AspectTarget,
    CandidatesDecision,
    CandidatesMaterial,
    CitedExcerpt,
    Excerpt,
    Firmness,
    GameMaterial,
    LibraryGame,
    NamedSideMaterial,
    OneGameMaterial,
    PlayerRequest,
    ReadState,
    SentimentGroup,
    Sheet,
    SheetRow,
    Stance,
    StoreFactTarget,
    Subject,
    SubjectMaterial,
    TermTarget,
    Want,
    WantMaterial,
    WantReading,
    WantTarget,
)
from steamlens.core.game_names import referenced_game
from steamlens.core.pick import ReadPlan
from steamlens.core.sheet import target_reading
from steamlens.core.store_facts import store_fact

# Every subject of a turn about one game is read, up to this many, in the
# player's order. A working value.
MAX_SUBJECTS: Final = 4

_CRITICISED: Final = (SentimentGroup.CLEARLY_NEGATIVE, SentimentGroup.SPLIT)


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
    identifiers = _identifiers()
    games: list[GameMaterial] = []
    for candidate in decision.candidates:
        row = rows.get(candidate.app_id)
        if row is None:
            raise ValueError(
                f"candidate {candidate.app_id} is not a row of the sheet — material is put"
                " together against the sheet the decision was made from"
            )
        games.append(_game_material(row, plan, excerpts, identifiers))
    return CandidatesMaterial(
        games=tuple(games), named_sides=_named_side_material(named_sides, identifiers)
    )


@dataclass(frozen=True, slots=True)
class StandingWantsRead:
    """A game read against the request's standing wants, for "would it suit me".

    ``row`` is the game's row of the sheet, ``plan`` the read plan with the
    game as its one candidate, ``excerpts`` what the plan's pairs gave, and
    ``named_sides`` the other side of any standing comparison.
    """

    row: SheetRow
    plan: ReadPlan
    excerpts: Mapping[tuple[int, int], Sequence[Excerpt]]
    named_sides: Sequence[NamedSideRead] = ()


def subject_reading(
    subject: Subject, game: LibraryGame, term_hits: Mapping[TermTarget, Mapping[int, int]]
) -> WantReading:
    """What a subject's target shows on ``game``.

    A subject is read the way a wanted want on the same target is, since the
    finding and the group are the same either way. Its status is not used: a
    question has no stance to match. ``term_hits`` holds the hit counts of
    every search term among the subjects.

    Raises what ``core.sheet.target_reading`` raises, for a term with no
    supplied counts.
    """
    as_want = Want(subject.words, Firmness.WANT, Stance.WANTS, subject.target)
    return target_reading(as_want, game, term_hits)


def subjects_to_read(request: PlayerRequest) -> tuple[int, ...]:
    """The positions of the subjects whose reviews are read on a one-game turn.

    The first ``MAX_SUBJECTS`` in the player's order, those of them whose
    target has reviews behind it. A subject on a store fact is among them
    whether or not the store lists the fact: the player asked about it, and
    the reviews say more than the listing does.
    """
    return tuple(
        position
        for position, subject in enumerate(request.subjects[:MAX_SUBJECTS])
        if review_read(subject.target) is not None
    )


def asks_whether_it_suits(request: PlayerRequest) -> bool:
    """Whether the turn reads the game against the standing wants.

    A subject with no target, on a request that has wants: "would it suit
    me", where the wants say what would suit. Code cannot tell that question
    from another one no stored field fits, so every such subject gets the
    read; the call that writes the reply has the subject's own words.
    """
    return bool(request.wants) and _has_untargeted_subject(request)


def asks_for_an_overview(request: PlayerRequest) -> bool:
    """Whether the turn reads the game in general: an untargeted subject and no wants."""
    return not request.wants and _has_untargeted_subject(request)


def one_game_material(
    request: PlayerRequest,
    game: LibraryGame,
    readings: Sequence[WantReading],
    excerpts: Mapping[int, Sequence[Excerpt]],
    standing: StandingWantsRead | None = None,
) -> OneGameMaterial:
    """Put the fetched material of a turn about one game together for the answer call.

    ``readings`` hold one reading per subject, in the subjects' order
    (``subject_reading``), and ``excerpts`` what each subject that was read
    gave, by its position. ``standing`` is the game read against the
    standing wants, handed in when the player asked whether it would suit
    them.

    A subject is ``READ`` when it gave excerpts, ``CUT_BY_CAP`` when it
    comes after the ``MAX_SUBJECTS`` a turn reads, and ``NOTHING_TO_READ``
    otherwise. The overview is filled only when ``asks_for_an_overview``
    holds. Identifiers run through the subjects, then the standing wants,
    then the named sides.

    Raises ``ValueError`` when ``readings`` are not one per subject.
    """
    if len(readings) != len(request.subjects):
        raise ValueError(
            f"{len(readings)} readings for {len(request.subjects)} subjects — a turn about"
            " one game has one reading per subject"
        )
    identifiers = _identifiers()
    subjects: list[SubjectMaterial] = []
    for position, (subject, reading) in enumerate(zip(request.subjects, readings, strict=True)):
        cited = _cited(excerpts.get(position, ()), identifiers)
        subjects.append(
            SubjectMaterial(
                words=subject.words,
                finding=reading.finding,
                read=_read_state(
                    cited,
                    was_cut=position >= MAX_SUBJECTS and review_read(subject.target) is not None,
                ),
                group=reading.group,
                excerpts=cited,
            )
        )
    released = game.storefront.release_date if game.storefront is not None else None
    return OneGameMaterial(
        app_id=game.app_id,
        title=game.name,
        description=_description(game),
        release_year=released.year if released is not None else None,
        subjects=tuple(subjects),
        standing_wants=(
            _game_material(standing.row, standing.plan, standing.excerpts, identifiers)
            if standing is not None else None
        ),
        named_sides=(
            _named_side_material(standing.named_sides, identifiers)
            if standing is not None else ()
        ),
        overview=_overview(game) if asks_for_an_overview(request) else (),
    )


def _has_untargeted_subject(request: PlayerRequest) -> bool:
    return any(subject.target is None for subject in request.subjects[:MAX_SUBJECTS])


def _overview(game: LibraryGame) -> tuple[AspectStanding, ...]:
    """The aspects a game's reviewers praise strongly, then those they criticise or split on.

    Each list most mentioned first. The mention counts order aspects inside
    one game's report and are not carried: they never order games.
    """
    by_mentions = sorted(game.cells, key=lambda cell: (-cell.mentions, cell.aspect))
    praised = [cell for cell in by_mentions if cell.group is SentimentGroup.STRONGLY_POSITIVE]
    criticised = [cell for cell in by_mentions if cell.group in _CRITICISED]
    return tuple(AspectStanding(cell.aspect, cell.group) for cell in (*praised, *criticised))


def _game_material(
    row: SheetRow,
    plan: ReadPlan,
    excerpts: Mapping[tuple[int, int], Sequence[Excerpt]],
    identifiers: Iterator[str],
) -> GameMaterial:
    """One game's row as the answer call reads it, a line per want."""
    cut = set(plan.cut)
    wants: list[WantMaterial] = []
    for position, reading in enumerate(row.readings):
        pair = (row.game.app_id, position)
        cited = _cited(excerpts.get(pair, ()), identifiers)
        wants.append(
            WantMaterial(
                status=reading.status,
                finding=reading.finding,
                read=_read_state(cited, was_cut=pair in cut),
                group=reading.group,
                on_game=reading.on_game,
                on_named_game=reading.on_named_game,
                excerpts=cited,
            )
        )
    return GameMaterial(
        app_id=row.game.app_id,
        title=row.game.name,
        description=_description(row.game),
        standing=row.standing,
        wants=tuple(wants),
    )


def _named_side_material(
    sides: Sequence[NamedSideRead], identifiers: Iterator[str]
) -> tuple[NamedSideMaterial, ...]:
    return tuple(
        NamedSideMaterial(
            want=side.want,
            app_id=side.game.app_id,
            title=side.game.name,
            excerpts=_cited(side.excerpts, identifiers),
        )
        for side in sides
    )


def _read_state(cited: Sequence[CitedExcerpt], *, was_cut: bool) -> ReadState:
    if cited:
        return ReadState.READ
    return ReadState.CUT_BY_CAP if was_cut else ReadState.NOTHING_TO_READ


def _description(game: LibraryGame) -> str:
    return game.storefront.short_description if game.storefront is not None else ""


def _identifiers() -> Iterator[str]:
    number = 0
    while True:
        number += 1
        yield f"e{number}"


def _cited(excerpts: Sequence[Excerpt], identifiers: Iterator[str]) -> tuple[CitedExcerpt, ...]:
    return tuple(CitedExcerpt(next(identifiers), excerpt) for excerpt in excerpts)
