"""One chat turn — the steps composed, from a conversation to the message that answers it.

The steps are built one by one in this package: understand, the sheet, the
pick, the fetch, the answer with its check. ``turn`` runs them in their
fixed order for one conversation and returns a ``Turn``: the message the
chat appends, how the turn ended, and what each step made on the way. The
serving route and an evaluation run both call it, so a reply read by hand
went the same way a reply shown on the page did.

Which way a reading goes, and the text of every ending that is not a
written reply, are rules and live in ``core.turn``. This module reads the
library, calls the steps and journals how the turn ended.

A recommendation turn builds the sheet, asks the pick, and then follows
the pick's decision: reviews are fetched for candidates, the library's
standing on the wants is put together when nothing fits, and a decision to
ask goes on as it is. A turn about one game has no sheet and no pick: the
reviews are fetched for what the player asked about that game. Either way
the answer step writes the reply. A step that ends with no result ends the
turn on a fixed text, and so does a reading the first stage has no reply
for.

The library is read once and handed to the steps that need it, so the
titles the understand step resolved a name against are the titles of the
games the sheet and the fetch read.

Nothing is stored here. The conversation is the caller's, and so are the
seed and the clock: the caller appends ``Turn.message``, keeps the seed
with the conversation, and decides what of the record it keeps.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from steamlens.chat.answer import answer, answer_route
from steamlens.chat.fetch import fetch_about_game, fetch_candidates
from steamlens.chat.pick import pick, pick_route
from steamlens.chat.sheet import load_library, term_hit_counts
from steamlens.chat.understand import understand, understand_route
from steamlens.contracts import (
    Answer,
    AnswerBasis,
    AskDecision,
    AspectOntology,
    CandidatesDecision,
    ChatMessage,
    LibraryGame,
    LlmStage,
    MetricEvent,
    NothingFitsDecision,
    Pick,
    PlayerRequest,
    RequestIntent,
    Sheet,
    Sink,
    StageKind,
    Turn,
    TurnEnding,
    Understanding,
)
from steamlens.core.material import left_out_games, nothing_fits_material
from steamlens.core.sheet import offered_games, read_sheet
from steamlens.core.turn import (
    OneGameTurn,
    RecommendTurn,
    ending_of_answer,
    ending_without_decision,
    fixed_message,
    games_asked_about,
    plan_turn,
    reply_message,
)
from steamlens.dispatch import narrate
from steamlens.llm_client import LlmClient, Route
from steamlens.store import Store

TURN_STAGE: Final = "chat.turn"


def chat_routes() -> dict[LlmStage, Route]:
    """The routes a turn's three model calls ride, by stage.

    A caller hands them to the client it builds, so the page and an
    evaluation run put the same dials under a turn.
    """
    return {
        LlmStage.UNDERSTAND: understand_route(),
        LlmStage.PICK: pick_route(),
        LlmStage.ANSWER: answer_route(),
    }


def turn(
    client: LlmClient,
    store: Store,
    conversation: Sequence[ChatMessage],
    ontology: AspectOntology,
    sink: Sink,
    *,
    seed: str,
    year: int,
) -> Turn:
    """Answer the latest message of ``conversation``.

    ``conversation`` ends with the player's latest message. ``client``
    carries the routes of ``chat_routes``. ``seed`` is the conversation's
    seed, which fixes the order of the games inside one pattern of the
    sheet the pick reads; it has no default, since any fixed order would
    hand every player the same games. ``year`` is the current year; the
    caller reads the clock.

    The result always holds a message to append, and says how the turn
    ended. A step's failure is an ending and never an exception: every step
    narrates and journals its own rungs, and the turn journals one count
    for its ending.

    Raises ``ValueError`` when an earlier chat message of ``conversation``
    offered a game the library does not hold. The chat offers library games
    only, so that is a conversation it did not write, and the caller decides
    which conversations it accepts.
    """
    library = load_library(store)
    titles = {game.app_id: game.name for game in library}
    understanding = understand(client, conversation, ontology, titles, sink, year=year)
    if understanding.request is not None:
        _count_readings(sink, understanding.request)

    plan = plan_turn(understanding)
    match plan:
        case TurnEnding():
            return _ended(sink, plan, seed, understanding)
        case RecommendTurn(request=request):
            return _recommend(
                client, store, conversation, request, library, titles, sink,
                seed=seed, understanding=understanding,
            )
        case OneGameTurn(request=request, app_id=app_id):
            # The understand step resolved the name against this turn's
            # titles, so the game is one of ``library``.
            game = next(game for game in library if game.app_id == app_id)
            basis = fetch_about_game(store, request, game, library, sink)
            answered = answer(client, conversation, request, basis, titles, sink)
            return _ended(
                sink, ending_of_answer(answered), seed, understanding,
                basis=basis, answer=answered,
            )


def _recommend(
    client: LlmClient,
    store: Store,
    conversation: Sequence[ChatMessage],
    request: PlayerRequest,
    library: Sequence[LibraryGame],
    titles: dict[int, str],
    sink: Sink,
    *,
    seed: str,
    understanding: Understanding,
) -> Turn:
    """A recommendation turn: the sheet, the pick, what its decision calls for, the answer."""
    sheet = read_sheet(
        request, library, term_hit_counts(store, request), offered_games(conversation)
    )
    picked = pick(client, request, sheet, sink, seed=seed)
    basis: AnswerBasis
    match picked.decision:
        case None:
            return _ended(
                sink, ending_without_decision(picked.outcome), seed, understanding,
                sheet=sheet, pick=picked,
            )
        case CandidatesDecision():
            basis = fetch_candidates(store, request, sheet, picked.decision, library, sink)
        case NothingFitsDecision():
            basis = nothing_fits_material(picked.decision, sheet, left_out_games(sheet, titles))
        case AskDecision():
            basis = picked.decision
    answered = answer(client, conversation, request, basis, titles, sink)
    return _ended(
        sink, ending_of_answer(answered), seed, understanding,
        sheet=sheet, pick=picked, basis=basis, answer=answered,
    )


def _ended(
    sink: Sink,
    ending: TurnEnding,
    seed: str,
    understanding: Understanding,
    *,
    sheet: Sheet | None = None,
    pick: Pick | None = None,
    basis: AnswerBasis | None = None,
    answer: Answer | None = None,
) -> Turn:
    """The turn's record, with its ending narrated and journalled as one count."""
    _count(sink, f"turn_{ending.value}".replace("-", "_"), 1)
    narrate(sink, TURN_STAGE, StageKind.DONE, f"the turn ended: {ending.value}")
    reply = answer.reply if answer is not None else None
    return Turn(
        message=reply_message(reply) if reply is not None else fixed_message(ending),
        ending=ending, seed=seed, understanding=understanding,
        sheet=sheet, pick=pick, basis=basis, answer=answer,
    )


def _count_readings(sink: Sink, request: PlayerRequest) -> None:
    """Count three readings of a turn about one game the understand step is asked not to give.

    No game marked as the one asked about, more than one, and nothing asked
    about it. The parse lets all three through, so how often they come is
    read off these counts.
    """
    if request.intent is not RequestIntent.ABOUT_GAME:
        return
    asked = games_asked_about(request)
    if not asked:
        _count(sink, "turn_no_game_asked_about", 1)
    if len(asked) > 1:
        _count(sink, "turn_more_games_asked_about", len(asked) - 1)
    if not request.subjects:
        _count(sink, "turn_nothing_asked", 1)


def _count(sink: Sink, name: str, value: int) -> None:
    sink.emit(MetricEvent(stage=TURN_STAGE, name=name, value=float(value), unit="count"))
