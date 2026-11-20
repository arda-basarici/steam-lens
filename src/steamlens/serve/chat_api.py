"""The chat's HTTP surface — one route that takes a message and answers with a turn.

``POST /chat/turns`` is the whole of it. The browser sends the new message
and, after the first, the conversation's identifier. It sends nothing else
of the conversation: what the chat said earlier is the server's own record
(``conversations``), so a visitor cannot write the chat's lines, the games
it offered or the number of turns taken. The route answers when the turn
has ended, with the message and what the page links under it. A stream of
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
from steamlens.core.turn import turn_links
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
from steamlens.serve.links import report_path

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
    """One report link under a reply: the game's title and its report's address."""

    title: str
    url: str


@dataclass(frozen=True, slots=True)
class ChatTurnReply:
    """One turn's answer, as the page shows it.

    ``conversation`` is the identifier the next message sends back.
    ``text`` is the chat's message, plain text and never markup. ``ending``
    names how the turn ended, so a page can tell a written reply from each
    fixed text. ``offered`` are the reports of the games the reply offers
    and ``about`` those of the games it speaks of without offering, kept
    apart so the page can label them apart. ``add_game_url`` is present
    when the page shows the link for adding a game.
    """

    conversation: str
    text: str
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
    report_names: Callable[[], Mapping[int, str]],
    sink: Sink,
    *,
    is_exempt: Callable[[str | None], bool] | None = None,
) -> None:
    """Register the chat's route on ``app`` — the composition root's call.

    ``run_turn`` answers a conversation that ends with the player's new
    message, under the conversation's seed; the root builds it over the
    store and the model door. ``book`` keeps the conversations and ``gate``
    admits the turns. ``config`` carries the message's length.
    ``report_names`` is the persistence layer's app-id → name read of every
    published report, consulted once a turn to title and address the links.
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
        return _reply(claim.identifier, turn, report_names())


def _reply(identifier: str, turn: Turn, names: Mapping[int, str]) -> ChatTurnReply:
    """The turn as the page shows it, with its links titled and addressed."""
    kind = turn.message.kind
    if kind is None:
        raise ValueError(
            "a turn's message has no kind — a chat message always says what it was,"
            " so the turn that made this one is wrong"
        )
    links = turn_links(turn)
    return ChatTurnReply(
        conversation=identifier,
        text=turn.message.text,
        kind=kind,
        ending=turn.ending,
        offered=_game_links(links.offered, names),
        about=_game_links(links.about, names),
        add_game_url=ADD_GAME_URL if links.add_game else None,
    )


def _game_links(app_ids: Sequence[int], names: Mapping[int, str]) -> tuple[GameLink, ...]:
    """A link for each game that has a published report, in the order given.

    Every game a reply speaks of is a library game, so a missing name means
    its report was unpublished between the turn and this read. That game
    gets no link.
    """
    return tuple(
        GameLink(names[app_id], report_path(app_id, names[app_id]))
        for app_id in app_ids
        if app_id in names
    )
