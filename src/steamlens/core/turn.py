"""The turn's rules — which way a reading goes, and what the chat says when no reply was written.

A chat turn is a fixed order of steps, and the order is decided here: from
the understand step's result, whether the turn recommends games, answers
about one game, or ends on a text written in advance. The decision is pure.
The steps themselves, and the store and the model they need, are composed
in ``chat.turn``.

Every way a turn can end has a name (``TurnEnding``) and every ending but a
written reply has one text (``FIXED_TEXTS``). The texts are of three
origins. Three are the understand step's own and are reused as they stand:
the refusal, the request that could not be read, and the chat that cannot
be served. One covers a turn whose request was read and whose reply did not
come: the pick held no decision, the answer could not be read, or the check
left nothing of it. Those three are told apart by the steps' outcomes and
their counts, and the player is told one thing, since there is nothing
different to do about each.

Three are stand-ins. The first stage of the chat does not write the
question that lists the titles a name could mean, the answer for a game the
library has not measured, or the explanation of what the numbers mean. A
turn that needs one of them ends on a short text that says so, with no
model call. Each stand-in is replaced by the reply it stands for when that
reply is built, and the ending's name stays.

A recommendation turn never ends here on a name. A named game that did not
resolve is read through the sheet's own finding for it, and the pick
decides what the request can still give.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from steamlens.contracts import (
    Answer,
    AnswerOutcome,
    ChatMessage,
    ChatMessageKind,
    ChatRole,
    NamedGame,
    NamedGameRole,
    NameMatch,
    PickOutcome,
    PlayerRequest,
    Reply,
    RequestIntent,
    TurnEnding,
    Understanding,
    UnderstandOutcome,
)
from steamlens.core.understand import OUT_OF_SCOPE_REPLY, UNAVAILABLE_REPLY, UNREADABLE_REPLY

# The request was read, so the understand step's "I could not make sense of
# that" would put the fault on the player's message.
NO_ANSWER_REPLY: Final = (
    "I could not put together an answer I can stand behind for that. Could you ask it"
    " another way?"
)
GAME_UNCLEAR_REPLY: Final = (
    "I could not tell which game you mean. Could you give me its full title?"
)
GAME_NOT_MEASURED_REPLY: Final = (
    "That game is not in the SteamLens library, so I have nothing measured to go on for it."
)
NUMBERS_UNEXPLAINED_REPLY: Final = (
    "I cannot explain the numbers yet. That part of the chat is not built."
)

FIXED_TEXTS: Final[Mapping[TurnEnding, str]] = {
    TurnEnding.OUT_OF_SCOPE: OUT_OF_SCOPE_REPLY,
    TurnEnding.NOT_UNDERSTOOD: UNREADABLE_REPLY,
    TurnEnding.UNAVAILABLE: UNAVAILABLE_REPLY,
    TurnEnding.NO_ANSWER: NO_ANSWER_REPLY,
    TurnEnding.GAME_UNCLEAR: GAME_UNCLEAR_REPLY,
    TurnEnding.GAME_NOT_MEASURED: GAME_NOT_MEASURED_REPLY,
    TurnEnding.NUMBERS_UNEXPLAINED: NUMBERS_UNEXPLAINED_REPLY,
}
"""The text of every ending that is not a written reply."""


@dataclass(frozen=True, slots=True)
class RecommendTurn:
    """A turn that goes to the sheet and the pick, with the request it reads."""

    request: PlayerRequest


@dataclass(frozen=True, slots=True)
class OneGameTurn:
    """A turn about one library game: the request, and the app id of the game."""

    request: PlayerRequest
    app_id: int


type TurnPlan = RecommendTurn | OneGameTurn | TurnEnding
"""Where a turn goes after the understand step: on, or to a fixed ending."""


def plan_turn(understanding: Understanding) -> TurnPlan:
    """Decide a turn's way from the understand step's result.

    A step that produced no request, a request out of scope and a question
    about the numbers each end the turn. A request for games goes on. A
    request about one game goes on when the game it asks about resolved to
    a library title, and ends otherwise: on ``GAME_NOT_MEASURED`` for a
    game the library does not hold, on ``GAME_UNCLEAR`` for a name several
    titles share, a reference that could not be tied to a game, and a
    request that marks no game as the one asked about.

    >>> plan_turn(Understanding(UnderstandOutcome.UNAVAILABLE, None))
    <TurnEnding.UNAVAILABLE: 'unavailable'>
    >>> request = PlayerRequest(RequestIntent.RECOMMEND)
    >>> plan_turn(Understanding(UnderstandOutcome.UNDERSTOOD, request)) == RecommendTurn(request)
    True
    """
    if understanding.outcome is UnderstandOutcome.UNAVAILABLE:
        return TurnEnding.UNAVAILABLE
    request = understanding.request
    if request is None:
        return TurnEnding.NOT_UNDERSTOOD
    match request.intent:
        case RequestIntent.OUT_OF_SCOPE:
            return TurnEnding.OUT_OF_SCOPE
        case RequestIntent.ABOUT_NUMBERS:
            return TurnEnding.NUMBERS_UNEXPLAINED
        case RequestIntent.RECOMMEND:
            return RecommendTurn(request)
        case RequestIntent.ABOUT_GAME:
            return _one_game_plan(request)


def games_asked_about(request: PlayerRequest) -> tuple[NamedGame, ...]:
    """The named games the request marks as the ones the latest message asks about.

    In the player's order. The understand step is asked for one. The turn
    reads the first and counts the rest.
    """
    return tuple(
        game for game in request.named_games if game.role is NamedGameRole.ASK_ABOUT
    )


def ending_without_decision(outcome: PickOutcome) -> TurnEnding:
    """The fixed ending of a turn whose pick step ended on ``outcome`` with no decision.

    ``UNAVAILABLE`` for a call that could not be served, and ``NO_ANSWER``
    for an answer that could not be read or had nothing left after its
    faults were removed.

    >>> ending_without_decision(PickOutcome.UNREADABLE)
    <TurnEnding.NO_ANSWER: 'no-answer'>
    """
    if outcome is PickOutcome.UNAVAILABLE:
        return TurnEnding.UNAVAILABLE
    return TurnEnding.NO_ANSWER


def ending_of_answer(answer: Answer) -> TurnEnding:
    """How a turn that reached the answer step ended.

    ``REPLIED`` when the step holds a reply. Otherwise ``UNAVAILABLE`` for a
    call that could not be served and ``NO_ANSWER`` for an unreadable or a
    withheld answer.

    >>> ending_of_answer(Answer(AnswerOutcome.WITHHELD, None))
    <TurnEnding.NO_ANSWER: 'no-answer'>
    """
    if answer.reply is not None:
        return TurnEnding.REPLIED
    if answer.outcome is AnswerOutcome.UNAVAILABLE:
        return TurnEnding.UNAVAILABLE
    return TurnEnding.NO_ANSWER


def reply_message(reply: Reply) -> ChatMessage:
    """The chat message a written reply becomes.

    Its text is the statements' text in order, joined by one space: the
    answer call writes them to be read as one message. Its offered games
    and its kind are the reply's. This text is what later turns read as the
    conversation.

    >>> from steamlens.contracts import ReplyStatement
    >>> message = reply_message(Reply(ChatMessageKind.ANSWER, (
    ...     ReplyStatement("One game fits."),
    ...     ReplyStatement("It is slow and quiet.", game=620, offers=True),
    ... )))
    >>> message.text, message.offered, message.kind.value
    ('One game fits. It is slow and quiet.', (620,), 'answer')
    """
    text = " ".join(statement.text for statement in reply.statements)
    return ChatMessage(ChatRole.CHAT, text, reply.offered, reply.kind)


def fixed_message(ending: TurnEnding) -> ChatMessage:
    """The chat message of a turn that ended on a fixed text.

    Raises ``ValueError`` for ``REPLIED``, which has no fixed text: its
    message is the reply's (``reply_message``).

    >>> fixed_message(TurnEnding.GAME_UNCLEAR).kind.value
    'fixed'
    """
    if ending not in FIXED_TEXTS:
        raise ValueError(
            f"the ending {ending.value!r} has no fixed text — a turn that ended on a"
            " written reply takes its message from the reply"
        )
    return ChatMessage(ChatRole.CHAT, FIXED_TEXTS[ending], kind=ChatMessageKind.FIXED)


def _one_game_plan(request: PlayerRequest) -> OneGameTurn | TurnEnding:
    asked = games_asked_about(request)
    if not asked:
        return TurnEnding.GAME_UNCLEAR
    game = asked[0]
    if game.app_id is not None:
        return OneGameTurn(request, game.app_id)
    if game.match is NameMatch.NOT_IN_LIBRARY:
        return TurnEnding.GAME_NOT_MEASURED
    return TurnEnding.GAME_UNCLEAR
