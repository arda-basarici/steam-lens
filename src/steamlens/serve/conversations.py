"""The conversation book — the chat's open conversations, kept between turns.

A chat turn stores nothing: it takes a whole conversation and returns the
message to append. Something has to hand the conversation back for the next
turn, and it is the server. The browser sends an identifier and the new
message and nothing else, so everything the chat said earlier, with the
games it offered, is the server's own record and never text a visitor wrote.

The book keeps conversations in process memory. A restart ends every open
one, the way a restarted job queue is empty, and a conversation the book no
longer knows is answered as ended. This is the first stage's arrangement.
The stored conversation, with its retention period, is designed later and
replaces what sits behind these four methods.

A turn is taken in three moves, so that two requests for one conversation
cannot both read it and both append. ``claim`` hands out the conversation
and marks it busy, or says why it cannot be continued. ``settle`` appends
the turn and frees it. ``release`` frees it with nothing appended, for a
turn that was refused admission or failed. A new conversation is claimed
without an identifier and exists from the first turn that is settled, so a
first message that is refused creates nothing.

The identifier lets its holder continue the conversation, so it goes to the
browser and nowhere else. What records and logs carry is the seed, a hash
of the identifier, which is also what orders the games inside one pattern
of the sheet the pick reads.
"""

from __future__ import annotations

import hashlib
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Final

from steamlens.contracts import ChatMessage

ENDED_MESSAGE: Final = "This conversation has ended. Start a new one to keep going."
AT_LENGTH_MESSAGE: Final = (
    "This conversation has reached its length. Start a new one to keep going."
)
BUSY_MESSAGE: Final = (
    "One message at a time: the reply to your last one is still being written."
)


class ConversationRefusal(Enum):
    """Why a conversation cannot take another turn right now.

    ``ENDED`` covers an identifier the book does not know, whatever the
    cause: expired, lost at a restart, or made up. One answer for the three
    means a reply never confirms that an identifier once existed.
    """

    ENDED = "ended"
    AT_LENGTH = "at-length"
    BUSY = "busy"


REFUSAL_MESSAGES: Final[dict[ConversationRefusal, str]] = {
    ConversationRefusal.ENDED: ENDED_MESSAGE,
    ConversationRefusal.AT_LENGTH: AT_LENGTH_MESSAGE,
    ConversationRefusal.BUSY: BUSY_MESSAGE,
}
"""The line a visitor reads for each refusal."""


def seed_of(identifier: str) -> str:
    """The conversation's seed: a hash of its identifier, safe to record.

    >>> seed_of("a") == seed_of("a") != seed_of("b")
    True
    >>> len(seed_of("a"))
    16
    """
    return hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class TurnClaim:
    """One conversation, handed out for one turn.

    ``messages`` is the conversation before the new message. ``is_new`` is
    set for a conversation the book does not hold yet: its identifier and
    seed are minted, and it is stored when the turn is settled.
    """

    identifier: str
    seed: str
    messages: tuple[ChatMessage, ...]
    is_new: bool


@dataclass(slots=True)
class _Open:
    """A conversation as the book holds it."""

    messages: list[ChatMessage] = field(default_factory=list[ChatMessage])
    turns: int = 0
    busy: bool = False
    last_used: datetime = datetime.min.replace(tzinfo=UTC)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _mint_identifier() -> str:
    return secrets.token_urlsafe(24)


class ConversationBook:
    """Open conversations in process memory, bounded three ways.

    ``max_turns`` is how many turns one conversation takes before it is at
    its length. ``idle_expiry`` drops a conversation nobody continued for
    that long. ``max_open`` bounds how many are held: when a new one would
    pass it, the one idle longest is dropped. The bounds are there for a
    script and not for capacity, since a conversation at its length is a
    few tens of kilobytes.

    The lock keeps a claim atomic under the route's thread pool. ``now``
    and ``mint`` are injected so a test steers the clock and knows the
    identifiers.
    """

    def __init__(
        self,
        *,
        max_turns: int,
        max_open: int,
        idle_expiry: timedelta,
        now: Callable[[], datetime] = _utc_now,
        mint: Callable[[], str] = _mint_identifier,
    ) -> None:
        self._max_turns = max_turns
        self._max_open = max_open
        self._idle_expiry = idle_expiry
        self._now = now
        self._mint = mint
        self._lock = threading.Lock()
        self._open: dict[str, _Open] = {}

    def claim(self, identifier: str | None) -> TurnClaim | ConversationRefusal:
        """Hand out the conversation for one turn, or say why it cannot go on.

        ``None`` claims a new conversation, which is never refused and
        holds nothing in the book until it is settled. A known conversation
        is marked busy until ``settle`` or ``release``.
        """
        if identifier is None:
            minted = self._mint()
            return TurnClaim(minted, seed_of(minted), (), is_new=True)
        with self._lock:
            self._drop_expired()
            held = self._open.get(identifier)
            if held is None:
                return ConversationRefusal.ENDED
            if held.busy:
                return ConversationRefusal.BUSY
            if held.turns >= self._max_turns:
                return ConversationRefusal.AT_LENGTH
            held.busy = True
            return TurnClaim(identifier, seed_of(identifier), tuple(held.messages), is_new=False)

    def settle(self, claim: TurnClaim, player: ChatMessage, chat: ChatMessage) -> None:
        """Append one turn, the player's message and the chat's, and free the conversation.

        A new conversation is stored here, on its first turn. A known one
        that was dropped while its turn ran (ended by ``end``) stays
        dropped.
        """
        with self._lock:
            if claim.is_new:
                self._make_room()
                held = self._open.setdefault(claim.identifier, _Open())
            else:
                found = self._open.get(claim.identifier)
                if found is None:
                    return
                held = found
            held.messages.extend((player, chat))
            held.turns += 1
            held.busy = False
            held.last_used = self._now()

    def release(self, claim: TurnClaim) -> None:
        """Free the conversation with nothing appended."""
        with self._lock:
            held = self._open.get(claim.identifier)
            if held is not None:
                held.busy = False

    def end(self, claim: TurnClaim) -> None:
        """Drop the conversation: it cannot be continued, and is answered as ended from now on."""
        with self._lock:
            self._open.pop(claim.identifier, None)

    def open_count(self) -> int:
        """How many conversations the book holds."""
        with self._lock:
            return len(self._open)

    def _drop_expired(self) -> None:
        horizon = self._now() - self._idle_expiry
        expired = [
            identifier for identifier, held in self._open.items()
            if not held.busy and held.last_used < horizon
        ]
        for identifier in expired:
            del self._open[identifier]

    def _make_room(self) -> None:
        """Before a new conversation is stored: at the bound, drop the one idle longest.

        A conversation whose turn is running is never dropped, so the book
        can pass the bound by the few turns in flight.
        """
        self._drop_expired()
        while len(self._open) >= self._max_open:
            idle = [
                (held.last_used, identifier) for identifier, held in self._open.items()
                if not held.busy
            ]
            if not idle:
                return
            del self._open[min(idle)[1]]
