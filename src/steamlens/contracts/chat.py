"""A chat conversation, and what the understand step made of it.

A conversation is the only state the recommender chat carries: every turn
the understand step reads all of it and fills a fresh ``PlayerRequest``.
``Understanding`` is that step's result, with the rung of its ladder that
produced it, so a caller can tell a request read cleanly from one that was
salvaged, and both from a turn that ends in a fixed reply.
"""

from __future__ import annotations

from dataclasses import dataclass

from steamlens.contracts.enums import ChatRole, UnderstandOutcome
from steamlens.contracts.request import PlayerRequest


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """One message of a conversation, in the order it was written."""

    role: ChatRole
    text: str


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
