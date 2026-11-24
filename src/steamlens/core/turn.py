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

Four are stand-ins. The first stage of the chat does not write the
question that lists the titles a name could mean, the answer for a game the
library has not measured, the explanation of what the numbers mean, or an
answer about several games at once. A turn that needs one of them ends on a
short text that says so, with no model call. Each stand-in is replaced by
the reply it stands for when that reply is built, and the ending's name
stays.

A recommendation turn never ends here on a name. A named game that did not
resolve is read through the sheet's own finding for it, and the pick
decides what the request can still give.

What a page links under a turn's message is a rule too (``turn_links``),
since the answer prompt tells the model what the page shows: a link to the
report of each game a reply offers or is about, and a link for adding a
game under a reply that found nothing. A page that showed less would make
the reply's own sentences untrue.

How a page lays the message out is the last rule here (``reply_blocks``):
the same text cut where the reply moves to another game, with a card over
each game it offers.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from steamlens.contracts import (
    Answer,
    AnswerOutcome,
    CandidatesMaterial,
    ChatMessage,
    ChatMessageKind,
    ChatRole,
    NamedGame,
    NamedGameRole,
    NameMatch,
    NothingFitsMaterial,
    OneGameMaterial,
    PickOutcome,
    PlayerRequest,
    Reply,
    RequestIntent,
    Turn,
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
# Reading the first game and saying nothing of the rest gave a reply about
# one game of three that read as if it covered all of them.
SEVERAL_GAMES_REPLY: Final = (
    "I can go into one game at a time for now. Which one would you like to hear about?"
)

FIXED_TEXTS: Final[Mapping[TurnEnding, str]] = {
    TurnEnding.OUT_OF_SCOPE: OUT_OF_SCOPE_REPLY,
    TurnEnding.NOT_UNDERSTOOD: UNREADABLE_REPLY,
    TurnEnding.UNAVAILABLE: UNAVAILABLE_REPLY,
    TurnEnding.NO_ANSWER: NO_ANSWER_REPLY,
    TurnEnding.GAME_UNCLEAR: GAME_UNCLEAR_REPLY,
    TurnEnding.GAME_NOT_MEASURED: GAME_NOT_MEASURED_REPLY,
    TurnEnding.NUMBERS_UNEXPLAINED: NUMBERS_UNEXPLAINED_REPLY,
    TurnEnding.SEVERAL_GAMES: SEVERAL_GAMES_REPLY,
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
    request that marks no game as the one asked about. A request that asks
    about more than one game ends on ``SEVERAL_GAMES``, whether or not each
    of them resolved.

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

    In the player's order. A turn goes on with one. With more it ends on
    the text that asks which, until a turn can answer about several.
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


@dataclass(frozen=True, slots=True)
class TurnLinks:
    """What a page links under a turn's message: games by app id, and one flag.

    ``offered`` are the games the reply offers, in its order. ``about`` are
    the games the reply is about and does not offer, in the order it first
    speaks of them: a candidate it set aside, the game named for a
    comparison, the one game a turn asks about. The two are kept apart so a
    page can label them apart, and a game set aside is not read as a
    suggestion. Every game in either is a library game with a report.
    ``add_game`` says whether the link for adding a game to the library is
    shown.
    """

    offered: tuple[int, ...] = ()
    about: tuple[int, ...] = ()
    add_game: bool = False


def turn_links(turn: Turn) -> TurnLinks:
    """The links a page shows under ``turn.message``.

    A turn that ended on a fixed text links no report. The text that says a
    game is not measured carries the link for adding one, since that is
    what the player can do about it.

    A written reply links the report of each game it offers and of each
    game one of its statements is about. On a turn about one game that game
    is linked whether or not a statement names it, since the whole reply is
    about it. The link for adding a game is shown under a reply written
    from the "nothing fits" material, which the answer prompt promises, and
    under an answer written from candidates that offers none of them, which
    can tell the player the same thing. A reply that only asks carries no
    such link: nothing was looked for yet.

    >>> understanding = Understanding(
    ...     UnderstandOutcome.UNDERSTOOD, PlayerRequest(RequestIntent.ABOUT_GAME)
    ... )
    >>> ended = TurnEnding.GAME_NOT_MEASURED
    >>> turn_links(Turn(fixed_message(ended), ended, "seed", understanding))
    TurnLinks(offered=(), about=(), add_game=True)
    """
    if turn.ending is TurnEnding.GAME_NOT_MEASURED:
        return TurnLinks(add_game=True)
    reply = turn.answer.reply if turn.answer is not None else None
    if turn.ending is not TurnEnding.REPLIED or reply is None:
        return TurnLinks()
    offered = reply.offered
    spoken_of = [statement.game for statement in reply.statements if statement.game is not None]
    if isinstance(turn.basis, OneGameMaterial):
        spoken_of.insert(0, turn.basis.app_id)
    about = tuple(dict.fromkeys(game for game in spoken_of if game not in offered))
    found_nothing = isinstance(turn.basis, NothingFitsMaterial) or (
        isinstance(turn.basis, CandidatesMaterial)
        and reply.kind is ChatMessageKind.ANSWER
        and not offered
    )
    return TurnLinks(offered=offered, about=about, add_game=found_nothing)


@dataclass(frozen=True, slots=True)
class ReplyBlock:
    """One block of a turn's message as a page lays it out.

    ``text`` is a run of the reply that stays on one game, or on none.
    ``card`` is the app id of the game whose card heads the block, present
    on the first block about a game the reply offers and on the block that
    opens a reply about one game. A block about a game the reply only
    speaks of has no card: a card reads as a suggestion.
    """

    text: str
    card: int | None = None


def reply_blocks(turn: Turn) -> tuple[ReplyBlock, ...]:
    """The turn's message cut into blocks, a new one wherever the reply changes game.

    The stored message is the statements joined into one text, which later
    turns read as the conversation; a reply about three games is hard to
    read that way on a page. This is the same text, in the same order, cut
    where a statement is about a different game from the one before it. The
    blocks joined by one space are the message again, so nothing is said on
    the page that the conversation does not hold.

    A turn that ended on a fixed text is one block.

    >>> understanding = Understanding(
    ...     UnderstandOutcome.UNDERSTOOD, PlayerRequest(RequestIntent.ABOUT_GAME)
    ... )
    >>> ended = TurnEnding.GAME_UNCLEAR
    >>> blocks = reply_blocks(Turn(fixed_message(ended), ended, "seed", understanding))
    >>> [(block.text == GAME_UNCLEAR_REPLY, block.card) for block in blocks]
    [(True, None)]
    """
    reply = turn.answer.reply if turn.answer is not None else None
    if turn.ending is not TurnEnding.REPLIED or reply is None:
        return (ReplyBlock(turn.message.text),)

    runs: list[tuple[int | None, list[str]]] = []
    for statement in reply.statements:
        if runs and runs[-1][0] == statement.game:
            runs[-1][1].append(statement.text)
        else:
            runs.append((statement.game, [statement.text]))

    carded = set(reply.offered)
    asked_about = turn.basis.app_id if isinstance(turn.basis, OneGameMaterial) else None
    if asked_about is not None:
        carded.add(asked_about)
    blocks: list[ReplyBlock] = []
    for game, texts in runs:
        heads = game is not None and game in carded
        blocks.append(ReplyBlock(" ".join(texts), game if heads else None))
        carded.discard(game)
    # A reply about one game need not name it in any statement. Its card
    # then heads the reply, unless the reply opens on another game.
    if asked_about in carded and blocks and runs[0][0] is None:
        blocks[0] = ReplyBlock(blocks[0].text, asked_about)
    return tuple(blocks)


def _one_game_plan(request: PlayerRequest) -> OneGameTurn | TurnEnding:
    match games_asked_about(request):
        case ():
            return TurnEnding.GAME_UNCLEAR
        case (game,):
            if game.app_id is not None:
                return OneGameTurn(request, game.app_id)
            if game.match is NameMatch.NOT_IN_LIBRARY:
                return TurnEnding.GAME_NOT_MEASURED
            return TurnEnding.GAME_UNCLEAR
        case _:
            return TurnEnding.SEVERAL_GAMES
