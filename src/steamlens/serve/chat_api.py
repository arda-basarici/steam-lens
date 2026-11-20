"""The chat's HTTP surface — one route that takes a message and answers with a turn.

``POST /chat/turns`` is the whole of it. The browser sends the new message
and, after the first, the conversation's identifier. It sends nothing else
of the conversation: what the chat said earlier is the server's own record
(``conversations``), so a visitor cannot write the chat's lines, the games
it offered or the number of turns taken. The route answers when the turn
has ended, with the message, how the page lays it out and what it links
under it. A stream of
the steps was declined for a turn that takes a few seconds, and the reply
cannot be streamed as it is written, since it is checked whole before
anything is shown.

The order of the checks is the visitor's own situation first: the message,
then the conversation, then the turn gate (``chat_gate``). Counting happens
inside the gate, after every check, so a refusal counts against nobody.
Everything that is not a turn's result answers with a status and a
``detail`` line the page shows by the input, the way the search box shows
a refusal: 400 for a message that cannot be taken, 410 for a conversation
that cannot go on (ended, or at its length), 409 for one whose turn is
still running, 429 for the gate, 503 for a turn that failed. The page reads
410 as the end of what is on screen and asks for a new conversation.

A turn's failures are endings and come back as an ordinary reply. What a
turn does not expect propagates out of it (a provider error no retry
mends, a broken invariant), and the route is where it stops: the cause is
narrated and its trace printed to the server's journal, the visitor reads
that the chat is unavailable, and the message is not appended, so the
conversation is as it was. One error has an answer of its own: a
conversation that offered a game the library no longer holds cannot be
continued, and is ended.

The route talks to injected callables and the two small objects that hold
its state, so this module knows nothing of the model door or the store, and
it never imports the renderer: the page that calls it lives in
``serve.web``.
"""

from __future__ import annotations

import traceback
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from fastapi import FastAPI, HTTPException, Request

from steamlens.contracts import (
    ChatMessage,
    ChatMessageKind,
    ChatRole,
    MetricEvent,
    Sink,
    StageKind,
    Turn,
    TurnEnding,
)
from steamlens.core.conversation import OfferedGameNotInLibrary
from steamlens.core.turn import reply_blocks, turn_links
from steamlens.core.understand import UNAVAILABLE_REPLY
from steamlens.dispatch import narrate
from steamlens.serve.chat_gate import TurnGate, message_refusal
from steamlens.serve.config import ServeConfig
from steamlens.serve.conversations import (
    ENDED_MESSAGE,
    REFUSAL_MESSAGES,
    ConversationBook,
    ConversationRefusal,
)
from steamlens.serve.gate import UNLOCK_COOKIE, client_ip

CHAT_STAGE: Final = "serve.chat"
ADD_GAME_URL: Final = "/"
"""Where a game is added to the library: the search page, which starts an analysis."""

_REFUSAL_STATUS: Final[dict[ConversationRefusal, int]] = {
    ConversationRefusal.ENDED: 410,
    ConversationRefusal.AT_LENGTH: 410,
    ConversationRefusal.BUSY: 409,
}


@dataclass(frozen=True, slots=True)
class ChatTurnRequest:
    """What the browser sends: the new message, and which conversation it continues.

    ``conversation`` is absent for a first message, which opens one. Any
    other field a caller adds is ignored: nothing of the conversation is
    taken from the request.
    """

    message: str
    conversation: str | None = None


@dataclass(frozen=True, slots=True)
class GameLink:
    """One game a reply links: its title, its report's address and its header art.

    The art's address is minted by the renderer's own rule, so the
    composition root builds these and this module only passes them on.
    """

    title: str
    url: str
    image_url: str


@dataclass(frozen=True, slots=True)
class ReplyBlockView:
    """One block of the message as the page lays it out: text under an optional card.

    ``card`` is present on the block that opens what the reply says about a
    game it offers, and on the block that opens a reply about one game.
    """

    text: str
    card: GameLink | None


@dataclass(frozen=True, slots=True)
class ChatTurnReply:
    """One turn's answer, as the page shows it.

    ``conversation`` is the identifier the next message sends back.
    ``text`` is the chat's message as the conversation holds it, plain text
    and never markup, and ``blocks`` are the same text cut where the reply
    moves to another game, each offered game's first block under its card.
    ``ending`` names how the turn ended, so a page can tell a written reply
    from each fixed text. ``offered`` are the games the reply offers.
    ``about`` are the games it speaks of that no card shows, which a page
    lists as plain links so a game set aside is not read as a suggestion.
    ``add_game_url`` is present when the page shows the link for adding a
    game.
    """

    conversation: str
    text: str
    blocks: tuple[ReplyBlockView, ...]
    kind: ChatMessageKind
    ending: TurnEnding
    offered: tuple[GameLink, ...]
    about: tuple[GameLink, ...]
    add_game_url: str | None


def attach_chat(
    app: FastAPI,
    run_turn: Callable[[Sequence[ChatMessage], str], Turn],
    book: ConversationBook,
    gate: TurnGate,
    config: ServeConfig,
    report_links: Callable[[], Mapping[int, GameLink]],
    sink: Sink,
    *,
    is_exempt: Callable[[str | None], bool] | None = None,
) -> None:
    """Register the chat's route on ``app`` — the composition root's call.

    ``run_turn`` answers a conversation that ends with the player's new
    message, under the conversation's seed; the root builds it over the
    store and the model door. ``book`` keeps the conversations and ``gate``
    admits the turns. ``config`` carries the message's length.
    ``report_links`` gives every published report's link by app id (title,
    address, header art), consulted once a turn for the cards and the links.
    ``sink`` takes the route's own narration and its one count, a
    conversation opened. ``is_exempt`` is the submit gate's unlock-cookie
    check; ``None`` composes a route with no exemption.
    """

    # The route function is "unused" to a type checker — the decorator
    # registers it with the app; the suppression states that, nothing more.
    @app.post("/chat/turns")
    def chat_turn(  # pyright: ignore[reportUnusedFunction]
        request: ChatTurnRequest, http_request: Request
    ) -> ChatTurnReply:
        """Answer one message: a turn's reply, or a line saying why there is none."""
        refused = message_refusal(request.message, config.chat_message_max_chars)
        if refused is not None:
            raise HTTPException(status_code=400, detail=refused)
        claim = book.claim(request.conversation or None)
        if isinstance(claim, ConversationRefusal):
            raise HTTPException(
                status_code=_REFUSAL_STATUS[claim], detail=REFUSAL_MESSAGES[claim]
            )
        peer = http_request.client.host if http_request.client else ""
        ip = client_ip(http_request.headers.get("x-forwarded-for"), peer)
        exempt = is_exempt is not None and is_exempt(http_request.cookies.get(UNLOCK_COOKIE))
        admitted = gate.admit(ip, exempt=exempt)
        if isinstance(admitted, str):
            book.release(claim)
            raise HTTPException(status_code=429, detail=admitted)

        player = ChatMessage(ChatRole.PLAYER, request.message.strip())
        try:
            turn = run_turn((*claim.messages, player), claim.seed)
        except OfferedGameNotInLibrary as gone:
            book.end(claim)
            narrate(
                sink, CHAT_STAGE, StageKind.WARN,
                f"a conversation was ended: it offered the games {list(gone.app_ids)},"
                " which the library no longer holds",
            )
            raise HTTPException(status_code=410, detail=ENDED_MESSAGE) from gone
        except Exception as error:
            # The one place a turn's unexpected failure stops. It is not
            # swallowed: the cause is narrated, the trace goes to the
            # server's journal, and the visitor is told the chat is
            # unavailable instead of being handed an error page.
            book.release(claim)
            narrate(
                sink, CHAT_STAGE, StageKind.WARN,
                f"a turn failed outside its steps: {type(error).__name__}: {error}",
            )
            traceback.print_exc()
            raise HTTPException(status_code=503, detail=UNAVAILABLE_REPLY) from error
        finally:
            gate.finish(admitted)

        book.settle(claim, player, turn.message)
        if claim.is_new:
            sink.emit(
                MetricEvent(stage=CHAT_STAGE, name="conversation_opened", value=1.0, unit="count")
            )
        return _reply(claim.identifier, turn, report_links())


def _reply(identifier: str, turn: Turn, reports: Mapping[int, GameLink]) -> ChatTurnReply:
    """The turn as the page shows it: its blocks under their cards, and its links."""
    kind = turn.message.kind
    if kind is None:
        raise ValueError(
            "a turn's message has no kind — a chat message always says what it was,"
            " so the turn that made this one is wrong"
        )
    links = turn_links(turn)
    laid_out = reply_blocks(turn)
    blocks = tuple(
        ReplyBlockView(block.text, reports.get(block.card) if block.card is not None else None)
        for block in laid_out
    )
    # A game whose card the page shows needs no second link among the rest.
    shown_as_cards = {block.card for block in laid_out if block.card in reports}
    return ChatTurnReply(
        conversation=identifier,
        text=turn.message.text,
        blocks=blocks,
        kind=kind,
        ending=turn.ending,
        offered=_game_links(links.offered, reports),
        about=_game_links(
            [game for game in links.about if game not in shown_as_cards], reports
        ),
        add_game_url=ADD_GAME_URL if links.add_game else None,
    )


def _game_links(app_ids: Sequence[int], reports: Mapping[int, GameLink]) -> tuple[GameLink, ...]:
    """The link of each game that has a published report, in the order given.

    Every game a reply speaks of is a library game, so a missing link means
    its report was unpublished between the turn and this read. That game
    gets no link.
    """
    return tuple(reports[app_id] for app_id in app_ids if app_id in reports)
