"""A chat conversation, and what the chat's steps make of it.

A conversation is the only state the recommender chat carries: every turn
the understand step reads all of it and fills a fresh ``PlayerRequest``.
What a later turn needs to know about an earlier reply is therefore recorded
on the message itself, as data: the games it offered and what kind of
message it was. Nothing is read back out of the reply's prose.

``Understanding`` is the understand step's result, with the rung of its
ladder that produced it, so a caller can tell a request read cleanly from
one that was salvaged, and both from a turn that ends in a fixed reply.

``PickDecision`` is what the pick call returns for a recommendation turn:
candidates to read reviews on, a question, or the finding that nothing fits.
It is a decision and holds no wording, so it can be scored against the sheet
it was made from; the reply is written afterwards by another call.

``Excerpt`` is the unit of review evidence that reply is written from: a
stretch of one review, with the review it came from.
"""

from __future__ import annotations

from dataclasses import dataclass

from steamlens.contracts.enums import ChatMessageKind, ChatRole, Sentiment, UnderstandOutcome
from steamlens.contracts.request import PlayerRequest


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """One message of a conversation, in the order it was written.

    ``offered`` holds the app ids of the games a chat message offered, in
    the order it offered them, so "the second one" has a list to be read
    against and a request for other games has offers to leave out. ``kind``
    says what a chat message was. A player message offers nothing and has no
    kind.

    >>> message = ChatMessage(ChatRole.PLAYER, "something like Hades")
    >>> message.offered, message.kind
    ((), None)
    """

    role: ChatRole
    text: str
    offered: tuple[int, ...] = ()
    kind: ChatMessageKind | None = None


@dataclass(frozen=True, slots=True)
class Understanding:
    """One turn's reading of the conversation.

    ``request`` is present for ``UNDERSTOOD``, ``RETRIED`` and ``SALVAGED``
    and absent for ``UNREADABLE`` and ``UNAVAILABLE``. ``faults`` are the
    faults still standing when the step ended, in words: for a salvaged
    request the wants that lost their target and the words that are not the
    player's, for an unreadable one what was wrong with the structure. A
    request with the intent ``OUT_OF_SCOPE`` is a valid reading; the fixed
    refusal is the caller's reply to it.

    >>> Understanding(UnderstandOutcome.UNAVAILABLE, None).faults
    ()
    """

    outcome: UnderstandOutcome
    request: PlayerRequest | None
    faults: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Excerpt:
    """A stretch of one review, cut for a model to read.

    ``text`` is the sentence around what made the review worth reading: the
    stored evidence span for a review labelled with an aspect, the matched
    words for one found by search. ``review_id`` and ``app_id`` say where it
    came from, so a statement built on it can be checked against the review
    and the game it is used for. ``sentiment`` is the label's, present only
    for a review read by its label; a search match does not say which way it
    points.
    """

    app_id: int
    review_id: str
    text: str
    sentiment: Sentiment | None = None


@dataclass(frozen=True, slots=True)
class PickCandidate:
    """One game the pick call put forward, and the wants to read its reviews on.

    ``wants`` are positions in the request's wants, the order a sheet row's
    readings follow. They are the wants the pick call was in doubt about and
    asked to see reviews for, and may be empty: a game that meets everything
    on store facts alone needs none read.
    """

    app_id: int
    wants: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class CandidatesDecision:
    """The pick call put games forward, in its own order of preference.

    More candidates are picked than a reply offers, since the call that
    writes the reply may drop some after reading their reviews. The order is
    the pick call's, and it is the order a cap cuts in.
    """

    candidates: tuple[PickCandidate, ...]


@dataclass(frozen=True, slots=True)
class AskDecision:
    """The pick call found the request too open to pick from, and what it needs to know.

    ``needs`` names each missing thing in a few words. They are not the
    question's wording, which the call that writes the reply chooses with
    the conversation in front of it.
    """

    needs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NothingFitsDecision:
    """The pick call found no library game worth offering.

    ``unmet`` are the positions, in the request's wants, of the wants no
    game could meet, so the reply can say what the library does not hold.
    """

    unmet: tuple[int, ...]


type PickDecision = CandidatesDecision | AskDecision | NothingFitsDecision
"""What the pick call decided for one recommendation turn: exactly one of the
three outcomes."""
