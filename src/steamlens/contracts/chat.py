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
it was made from; the reply is written afterwards by another call. ``Pick``
is the pick step's result, the decision with the rung that produced it.

``Excerpt`` is the unit of review evidence that reply is written from: a
stretch of one review, with the review it came from. ``CandidatesMaterial``
is what code fetches between the two calls: for each candidate its title,
its reading on every want in words, and the excerpts read, each under an
identifier the reply cites. ``OneGameMaterial`` is the same for a turn that
asks about one game: a line per thing asked, and the game read against the
standing wants when the player asked whether it would suit them.
"""

from __future__ import annotations

from dataclasses import dataclass

from steamlens.contracts.enums import (
    ChatMessageKind,
    ChatRole,
    MustStanding,
    PickOutcome,
    ReadState,
    Sentiment,
    SentimentGroup,
    UnderstandOutcome,
    WantFinding,
    WantStatus,
)
from steamlens.contracts.request import PlayerRequest
from steamlens.contracts.sheet import SideFinding


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
    readings follow. They are the wants the pick call listed as mattering
    most to its decision, most important first, and may be empty. The list
    sets an order and nothing more: code reads the musts before it and the
    remaining wants after it, so a want left off is still read while there
    is room.
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


@dataclass(frozen=True, slots=True)
class Pick:
    """One recommendation turn's pick, with the rung of the ladder that produced it.

    ``decision`` is present for ``DECIDED``, ``RETRIED`` and ``SALVAGED`` and
    absent for ``UNREADABLE`` and ``UNAVAILABLE``. ``faults`` are the faults
    still standing when the step ended, in words: for a salvaged decision
    what was removed from it, for an unreadable one what was wrong with the
    answer.

    >>> Pick(PickOutcome.UNAVAILABLE, None).faults
    ()
    """

    outcome: PickOutcome
    decision: PickDecision | None
    faults: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CitedExcerpt:
    """An excerpt as the answer call reads it, under the identifier it is cited by.

    The identifier (``e1``, ``e2`` and on) is issued for one turn's material
    and means nothing outside it. A reply cites it, and it leads back to the
    review and the game through ``excerpt``.
    """

    identifier: str
    excerpt: Excerpt


@dataclass(frozen=True, slots=True)
class WantMaterial:
    """What the answer call is given on one want for one game.

    The reading in words: ``status``, ``finding``, and ``group`` for a want
    on an aspect; for a want relative to a named game, what its target
    shows on each side. There is no count here by construction. The reply
    is written from groups and excerpts, and a match count or a mention
    count that never reaches the call cannot be stated or compared.

    ``read`` says whether reviews were read on the want, and ``excerpts``
    holds them when they were.
    """

    status: WantStatus
    finding: WantFinding
    read: ReadState
    group: SentimentGroup | None = None
    on_game: SideFinding | None = None
    on_named_game: SideFinding | None = None
    excerpts: tuple[CitedExcerpt, ...] = ()


@dataclass(frozen=True, slots=True)
class GameMaterial:
    """One candidate as the answer call reads it.

    The title appears here for the first time in a turn: the pick call chose
    the game without it. ``description`` is the store's short description,
    empty when none is held. ``wants`` are in the order of the request's
    wants, one each.
    """

    app_id: int
    title: str
    description: str
    standing: MustStanding
    wants: tuple[WantMaterial, ...]


@dataclass(frozen=True, slots=True)
class NamedSideMaterial:
    """The named game's side of one comparison, read once for the turn.

    ``want`` is the position of the want that is relative to the game. A
    comparison is made in words from reviews of both games, and this is the
    half that is the same for every candidate.
    """

    want: int
    app_id: int
    title: str
    excerpts: tuple[CitedExcerpt, ...]


@dataclass(frozen=True, slots=True)
class CandidatesMaterial:
    """Everything fetched for a recommendation turn's candidates.

    ``games`` are in the pick's order. ``named_sides`` holds one entry for
    each relative want that was read for some candidate and whose named game
    the library holds.
    """

    games: tuple[GameMaterial, ...]
    named_sides: tuple[NamedSideMaterial, ...] = ()


@dataclass(frozen=True, slots=True)
class SubjectMaterial:
    """What the answer call is given on one thing the player asked about a game.

    ``words`` are the player's. ``finding`` is what the subject's target
    shows on the game, and ``group`` where reviewers stand when the target
    is an aspect. A question has no stance, so there is no status: "does it
    have co-op" is answered by the finding, not by a match. ``read`` and
    ``excerpts`` are as on a want's line; a subject past the number a turn
    reads is ``CUT_BY_CAP``.
    """

    words: str
    finding: WantFinding
    read: ReadState
    group: SentimentGroup | None = None
    excerpts: tuple[CitedExcerpt, ...] = ()


@dataclass(frozen=True, slots=True)
class AspectStanding:
    """Where a game's reviewers stand on one aspect, as a group and nothing finer."""

    aspect: str
    group: SentimentGroup


@dataclass(frozen=True, slots=True)
class OneGameMaterial:
    """Everything fetched for a turn that asks about one game.

    ``subjects`` are in the player's order, one for each thing asked.
    ``release_year`` is the store's, absent when no date is held.

    ``standing_wants`` is present when the player asked whether the game
    would suit them: the game read against the wants that still stand, the
    way a candidate is. ``named_sides`` belong to it, for a standing want
    that is relative to another game.

    ``overview`` is present when the player asked about the game in general
    and has stated no wants: the aspects its reviewers praise strongly, then
    the ones they criticise or are divided on, each list most mentioned
    first.
    """

    app_id: int
    title: str
    description: str
    release_year: int | None
    subjects: tuple[SubjectMaterial, ...]
    standing_wants: GameMaterial | None = None
    named_sides: tuple[NamedSideMaterial, ...] = ()
    overview: tuple[AspectStanding, ...] = ()
