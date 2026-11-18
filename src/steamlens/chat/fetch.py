"""The fetch — reading reviews for a turn's candidates, between the two model calls.

The pick call names candidates without having read a review. This module
reads them: for each pair of a game and a want in the read plan, the game's
reviews on that want, and once per comparison the named game's side. What
comes back is put together into the material the answer call reads.

No rule lives here. Which pairs are read, and in what order under the cap,
is ``core.pick.read_plan``; how a target is read and how the material is
laid out is ``core.material``; the two reads are ``chat.evidence``. This
module runs them against the store and journals what the cap left unread,
so a cut is on record and never silent.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final

from steamlens.chat.evidence import aspect_excerpts, term_excerpts
from steamlens.contracts import (
    CandidatesDecision,
    CandidatesMaterial,
    Excerpt,
    LibraryGame,
    MetricEvent,
    PlayerRequest,
    Sheet,
    Sink,
    StageKind,
)
from steamlens.core.material import (
    AspectRead,
    NamedSideRead,
    ReviewRead,
    candidates_material,
    named_sides_to_read,
    review_read,
)
from steamlens.core.pick import read_plan
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
    plan = read_plan(decision, request, sheet)
    games = {game.app_id: game for game in library}
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

    named_sides: list[NamedSideRead] = []
    for position, app_id in named_sides_to_read(request, plan):
        read = review_read(request.wants[position].target)
        if read is not None:
            game = _game(games, app_id)
            named_sides.append(NamedSideRead(position, game, _read(store, game, read)))

    _count(sink, "fetch_pairs_read", len(plan.pairs))
    _count(
        sink, "fetch_excerpts",
        sum(len(found) for found in excerpts.values())
        + sum(len(side.excerpts) for side in named_sides),
    )
    if plan.cut:
        _count(sink, "fetch_pairs_cut", len(plan.cut))
        narrate(
            sink, FETCH_STAGE, StageKind.WARN,
            f"the read cap left {len(plan.cut)} pairs unread — the reply is told which",
        )
    return candidates_material(request, sheet, decision, plan, excerpts, named_sides)


def _game(games: dict[int, LibraryGame], app_id: int) -> LibraryGame:
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
