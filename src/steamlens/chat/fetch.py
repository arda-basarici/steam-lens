"""The fetch — reading reviews for a turn, between understanding it and answering it.

A recommendation turn's pick call names candidates without having read a
review. ``fetch_candidates`` reads them: for each pair of a game and a want
in the read plan, the game's reviews on that want, and once per comparison
the named game's side.

A turn about one game has no pick. ``fetch_about_game`` reads that game on
each thing the player asked, and, when they asked whether it would suit
them, against the wants that still stand.

Either way what comes back is put together into the material the answer
call reads. No rule lives here. Which pairs are read, and in what order
under the cap, is ``core.pick.read_plan``; how a target is read, which
subjects are read and how the material is laid out is ``core.material``;
the two reads are ``chat.evidence``. This module runs them against the
store and journals what was left unread, so a cut is on record and never
silent.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Final

from steamlens.chat.evidence import aspect_excerpts, term_excerpts
from steamlens.chat.sheet import term_hit_counts
from steamlens.contracts import (
    CandidatesDecision,
    CandidatesMaterial,
    Excerpt,
    LibraryGame,
    MetricEvent,
    OneGameMaterial,
    PickCandidate,
    PlayerRequest,
    Sheet,
    Sink,
    StageKind,
    TermTarget,
)
from steamlens.core.material import (
    MAX_SUBJECTS,
    AspectRead,
    NamedSideRead,
    ReviewRead,
    StandingWantsRead,
    asks_whether_it_suits,
    candidates_material,
    named_sides_to_read,
    one_game_material,
    review_read,
    subject_reading,
    subjects_to_read,
)
from steamlens.core.pick import ReadPlan, read_plan
from steamlens.core.sheet import read_sheet
from steamlens.dispatch import narrate
from steamlens.store import Store

FETCH_STAGE: Final = "chat.fetch"


def fetch_candidates(
    store: Store,
    request: PlayerRequest,
    sheet: Sheet,
    decision: CandidatesDecision,
    library: Iterable[LibraryGame],
    sink: Sink,
) -> CandidatesMaterial:
    """Read the reviews a recommendation turn's reply is written from.

    ``sheet`` is the one ``decision`` was made from. ``library`` is every
    library game, the ones left off the sheet included: a game the player
    has already played is not a candidate and can still be the named side
    of a comparison.

    Journals how many pairs were read, how many excerpts they gave, and how
    many pairs the cap cut; a cut also narrates.

    Raises ``ValueError`` for a candidate that is not on the sheet, for a
    planned pair whose target has no way to be read, and for a named game
    the library does not hold: each means the pieces handed in do not
    belong together.
    """
    games = {game.app_id: game for game in library}
    plan = read_plan(decision, request, sheet)
    excerpts = _read_pairs(store, request, plan, games)
    named_sides = _read_named_sides(store, request, plan, games)
    _journal(sink, plan, [*excerpts.values(), *(side.excerpts for side in named_sides)])
    return candidates_material(request, sheet, decision, plan, excerpts, named_sides)


def fetch_about_game(
    store: Store,
    request: PlayerRequest,
    game: LibraryGame,
    library: Iterable[LibraryGame],
    sink: Sink,
) -> OneGameMaterial:
    """Read the reviews a reply about one game is written from.

    ``game`` is the library game the turn asks about, which the caller has
    resolved from the request's named games, and ``library`` every library
    game. Each of the first few subjects is read by its target. When the
    player asked whether the game would suit them, it is also read against
    the standing wants, as a candidate is. That read is skipped for a game
    that is not on the sheet, which is one the player said they had already
    played.

    Journals what ``fetch_candidates`` does, and how many subjects came
    after the number a turn reads.
    """
    games = {library_game.app_id: library_game for library_game in library}
    terms = {
        subject.target for subject in request.subjects if isinstance(subject.target, TermTarget)
    }
    term_hits = {term: store.review_search.game_hit_counts(term.phrases) for term in terms}
    readings = [subject_reading(subject, game, term_hits) for subject in request.subjects]

    excerpts: dict[int, tuple[Excerpt, ...]] = {}
    for position in subjects_to_read(request):
        read = review_read(request.subjects[position].target)
        if read is not None:
            excerpts[position] = _read(store, game, read)

    standing: StandingWantsRead | None = None
    plan = ReadPlan(pairs=())
    if asks_whether_it_suits(request):
        sheet = read_sheet(request, games.values(), term_hit_counts(store, request))
        row = next((row for row in sheet.rows if row.game.app_id == game.app_id), None)
        if row is not None:
            plan = read_plan(CandidatesDecision((PickCandidate(game.app_id),)), request, sheet)
            standing = StandingWantsRead(
                row=row,
                plan=plan,
                excerpts=_read_pairs(store, request, plan, games),
                named_sides=_read_named_sides(store, request, plan, games),
            )

    read_excerpts: list[Sequence[Excerpt]] = list(excerpts.values())
    if standing is not None:
        read_excerpts += [*standing.excerpts.values()]
        read_excerpts += [side.excerpts for side in standing.named_sides]
    _journal(sink, plan, read_excerpts, subjects_read=len(excerpts))
    unread = len(request.subjects) - MAX_SUBJECTS
    if unread > 0:
        _count(sink, "fetch_subjects_unread", unread)
        narrate(
            sink, FETCH_STAGE, StageKind.WARN,
            f"{unread} subjects came after the {MAX_SUBJECTS} a turn reads — the reply is"
            " told which",
        )
    return one_game_material(request, game, readings, excerpts, standing)


def _read_pairs(
    store: Store, request: PlayerRequest, plan: ReadPlan, games: Mapping[int, LibraryGame]
) -> dict[tuple[int, int], tuple[Excerpt, ...]]:
    """What each pair of the plan gives, by app id and want position."""
    excerpts: dict[tuple[int, int], tuple[Excerpt, ...]] = {}
    for app_id, position in plan.pairs:
        want = request.wants[position]
        read = review_read(want.target)
        if read is None:
            raise ValueError(
                f"the read plan holds want {want.words!r} for game {app_id}, and its target has"
                " no reviews to read — the plan and the reads disagree on what is readable"
            )
        excerpts[(app_id, position)] = _read(store, _game(games, app_id), read)
    return excerpts


def _read_named_sides(
    store: Store, request: PlayerRequest, plan: ReadPlan, games: Mapping[int, LibraryGame]
) -> list[NamedSideRead]:
    """The named game's side of each comparison the plan reads, once each."""
    sides: list[NamedSideRead] = []
    for position, app_id in named_sides_to_read(request, plan):
        read = review_read(request.wants[position].target)
        if read is not None:
            game = _game(games, app_id)
            sides.append(NamedSideRead(position, game, _read(store, game, read)))
    return sides


def _journal(
    sink: Sink,
    plan: ReadPlan,
    excerpts: Iterable[Sequence[Excerpt]],
    *,
    subjects_read: int = 0,
) -> None:
    _count(sink, "fetch_pairs_read", len(plan.pairs) + subjects_read)
    _count(sink, "fetch_excerpts", sum(len(found) for found in excerpts))
    if plan.cut:
        _count(sink, "fetch_pairs_cut", len(plan.cut))
        narrate(
            sink, FETCH_STAGE, StageKind.WARN,
            f"the read cap left {len(plan.cut)} pairs unread — the reply is told which",
        )


def _game(games: Mapping[int, LibraryGame], app_id: int) -> LibraryGame:
    game = games.get(app_id)
    if game is None:
        raise ValueError(
            f"game {app_id} is to be read and is not in the library handed to the fetch"
        )
    return game


def _read(store: Store, game: LibraryGame, read: ReviewRead) -> tuple[Excerpt, ...]:
    if isinstance(read, AspectRead):
        return aspect_excerpts(store, game, read.aspect)
    return term_excerpts(store, game, read.phrases)


def _count(sink: Sink, name: str, value: int) -> None:
    sink.emit(MetricEvent(stage=FETCH_STAGE, name=name, value=float(value), unit="count"))
