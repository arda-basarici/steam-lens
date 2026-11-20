"""Behavioral claims on the conversation book — what the server keeps between turns.

The claims: a new conversation holds nothing until its first turn is
settled, so a refused first message creates nothing; a settled conversation
comes back whole, in order, under the same seed; the seed is not the
identifier; one conversation takes one turn at a time, and a released turn
leaves it as it was; a conversation ends at its length, after its idle
expiry, when it is ended, and when the identifier was never the book's, all
four answered the same way but the first; and at the bound the conversation
idle longest makes room, never one whose turn is running.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from steamlens.contracts import ChatMessage, ChatMessageKind, ChatRole
from steamlens.serve.conversations import (
    REFUSAL_MESSAGES,
    ConversationBook,
    ConversationRefusal,
    TurnClaim,
    seed_of,
)

_START = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


class _Clock:
    """A clock a test moves by hand."""

    def __init__(self) -> None:
        self.moment = _START

    def __call__(self) -> datetime:
        return self.moment

    def advance(self, **delta: float) -> None:
        self.moment += timedelta(**delta)


def _book(
    clock: _Clock | None = None, *, max_turns: int = 12, max_open: int = 500
) -> ConversationBook:
    names = iter(f"conversation-{number}" for number in range(1, 100))
    return ConversationBook(
        max_turns=max_turns, max_open=max_open, idle_expiry=timedelta(hours=2),
        now=clock or _Clock(), mint=lambda: next(names),
    )


def _claimed(book: ConversationBook, identifier: str | None = None) -> TurnClaim:
    claim = book.claim(identifier)
    assert isinstance(claim, TurnClaim)
    return claim


def _turn(book: ConversationBook, identifier: str | None, text: str) -> str:
    """Take one whole turn and return the conversation's identifier."""
    claim = _claimed(book, identifier)
    book.settle(
        claim,
        ChatMessage(ChatRole.PLAYER, text),
        ChatMessage(ChatRole.CHAT, f"reply to {text}", kind=ChatMessageKind.ANSWER),
    )
    return claim.identifier


def test_a_new_conversation_holds_nothing_until_its_first_turn_is_settled() -> None:
    """A first message refused at the gate is released, and no conversation
    was created for it: the bound on open conversations cannot be filled
    for free."""
    book = _book()
    claim = _claimed(book)
    assert (claim.is_new, claim.messages) == (True, ())
    book.release(claim)
    assert book.open_count() == 0
    assert book.claim(claim.identifier) is ConversationRefusal.ENDED


def test_a_settled_conversation_comes_back_whole_and_under_the_same_seed() -> None:
    book = _book()
    first = _claimed(book)
    book.settle(
        first,
        ChatMessage(ChatRole.PLAYER, "a calm game"),
        ChatMessage(ChatRole.CHAT, "Try this one.", offered=(620,), kind=ChatMessageKind.ANSWER),
    )
    second = _claimed(book, first.identifier)
    assert [message.text for message in second.messages] == ["a calm game", "Try this one."]
    assert second.messages[1].offered == (620,)
    assert (second.seed, second.is_new) == (first.seed, False)


def test_the_seed_is_a_hash_of_the_identifier_and_never_the_identifier() -> None:
    """The identifier continues the conversation, so it is not what a
    record carries."""
    claim = _claimed(_book())
    assert claim.seed == seed_of(claim.identifier)
    assert claim.identifier not in claim.seed


def test_one_conversation_takes_one_turn_at_a_time() -> None:
    book = _book()
    identifier = _turn(book, None, "a calm game")
    running = _claimed(book, identifier)
    assert book.claim(identifier) is ConversationRefusal.BUSY
    book.release(running)
    after = _claimed(book, identifier)
    assert len(after.messages) == 2


def test_a_conversation_at_its_length_takes_no_further_turn() -> None:
    book = _book(max_turns=2)
    identifier = _turn(book, None, "first")
    _turn(book, identifier, "second")
    assert book.claim(identifier) is ConversationRefusal.AT_LENGTH


def test_an_idle_conversation_expires_and_one_in_use_does_not() -> None:
    clock = _Clock()
    book = _book(clock)
    idle = _turn(book, None, "left alone")
    used = _turn(book, None, "kept up")
    clock.advance(hours=1, minutes=30)
    _turn(book, used, "still here")
    running = _claimed(book, used)
    clock.advance(hours=3)
    assert book.claim(idle) is ConversationRefusal.ENDED
    book.settle(running, ChatMessage(ChatRole.PLAYER, "slow"), ChatMessage(ChatRole.CHAT, "done"))
    assert len(_claimed(book, used).messages) == 6


def test_an_ended_conversation_stays_ended_even_when_its_turn_settles_after() -> None:
    """The route ends a conversation whose turn found a game gone from the
    library. A settle that arrives for it afterwards does not bring it
    back."""
    book = _book()
    identifier = _turn(book, None, "a calm game")
    running = _claimed(book, identifier)
    book.end(running)
    book.settle(running, ChatMessage(ChatRole.PLAYER, "more"), ChatMessage(ChatRole.CHAT, "no"))
    assert book.claim(identifier) is ConversationRefusal.ENDED
    assert book.claim("never-minted") is ConversationRefusal.ENDED


def test_at_the_bound_the_conversation_idle_longest_makes_room() -> None:
    clock = _Clock()
    book = _book(clock, max_open=2)
    oldest = _turn(book, None, "first in")
    clock.advance(minutes=1)
    newer = _turn(book, None, "second in")
    clock.advance(minutes=1)
    _turn(book, oldest, "touched again")
    clock.advance(minutes=1)
    newest = _turn(book, None, "third in")
    assert book.open_count() == 2
    assert book.claim(newer) is ConversationRefusal.ENDED
    assert isinstance(book.claim(oldest), TurnClaim)
    assert isinstance(book.claim(newest), TurnClaim)


def test_a_conversation_whose_turn_is_running_is_never_dropped_for_room() -> None:
    book = _book(max_open=1)
    identifier = _turn(book, None, "first in")
    running = _claimed(book, identifier)
    _turn(book, None, "second in")
    book.release(running)
    assert isinstance(book.claim(identifier), TurnClaim)


def test_every_refusal_has_a_line_a_visitor_can_read() -> None:
    assert set(REFUSAL_MESSAGES) == set(ConversationRefusal)
    assert all(text.endswith(".") for text in REFUSAL_MESSAGES.values())
