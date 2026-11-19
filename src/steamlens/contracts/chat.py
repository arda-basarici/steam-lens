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
``NothingFitsMaterial`` is what a reply that offers nothing is written from:
how the library divides on each want, in words.

``Reply`` is what the answer call writes, as data: ordered statements, each
with the game it is about, whether it offers that game, the wants it speaks
to and the excerpts it cites.
The reply stays a record until it is shown, so the games a message offered
and the reviews behind a sentence are read from fields and never back out of
prose. ``Answer`` is the answer step's result, the reply with the rung that
produced it. ``Objection`` is one thing the check found wrong in a readable
reply, and ``SettledObjection`` the same with how it ended.

``Turn`` is one whole turn: the message the chat appends to the
conversation, how the turn ended, and what each step made on the way.
"""

from __future__ import annotations

from dataclasses import dataclass

from steamlens.contracts.enums import (
    AnswerOutcome,
    ChatMessageKind,
    ChatRole,
    CheckRule,
    MustStanding,
    ObjectionRung,
    PickOutcome,
    ReadState,
    Sentiment,
    SentimentGroup,
    TurnEnding,
    UnderstandOutcome,
    WantFinding,
    WantStatus,
)
from steamlens.contracts.request import PlayerRequest
from steamlens.contracts.sheet import Sheet, SideFinding


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
    wants, one each. ``release_year`` is the store's, absent when no date is
    held; a reply may state it, and it is the one figure here.
    """

    app_id: int
    title: str
    description: str
    standing: MustStanding
    wants: tuple[WantMaterial, ...]
    release_year: int | None = None


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
class LeftOut:
    """The games left off the sheet on the player's say, by title.

    ``already_played`` are the games the player said they had played, and
    ``earlier_offers`` the ones the chat had offered before the player asked
    for other games, in the order first offered. Neither was left out on
    evidence, and a reply says that it left them out, so it needs their
    titles.
    """

    already_played: tuple[str, ...] = ()
    earlier_offers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CandidatesMaterial:
    """Everything fetched for a recommendation turn's candidates.

    ``games`` are in the pick's order. ``named_sides`` holds one entry for
    each relative want that was read for some candidate and whose named game
    the library holds. ``left_out`` names the games that were never on the
    sheet.
    """

    games: tuple[GameMaterial, ...]
    named_sides: tuple[NamedSideMaterial, ...] = ()
    left_out: LeftOut = LeftOut()


@dataclass(frozen=True, slots=True)
class WantAcrossLibrary:
    """How the library's games divide on one want, with no count.

    ``matched``, ``failed`` and ``undecided`` each say whether at least one
    game that could be offered has that status on the want. "None" and
    "some" are the only amounts: a reply that offers nothing names no game
    and no figure, so a count would have nowhere to go but into a sentence
    it should not be in. A game the player named as "like this" is not among
    the games counted, since it is never offered.

    ``findings`` are the distinct findings the want has across those games.
    Some hold for the whole library (hardly any review anywhere uses the
    words; the game the want is relative to was never measured), and the
    reply's wording depends on them.
    """

    matched: bool
    failed: bool
    undecided: bool
    findings: tuple[WantFinding, ...] = ()


@dataclass(frozen=True, slots=True)
class NothingFitsMaterial:
    """What a "nothing fits" reply is written from.

    ``wants`` are in the order of the request's wants, one each. ``unmet``
    are the positions the pick call named as the wants the library could not
    meet. ``met_only_apart`` is set when every unmet want is matched by some
    game and no game matches them all, which is a different thing to tell a
    player than "the library holds no such game". The difference between a
    want the stored data goes against and one nothing could decide is in
    each want's line.
    """

    wants: tuple[WantAcrossLibrary, ...]
    unmet: tuple[int, ...]
    met_only_apart: bool = False
    left_out: LeftOut = LeftOut()


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


type AnswerBasis = CandidatesMaterial | NothingFitsMaterial | AskDecision | OneGameMaterial
"""What one reply is written from: the candidates' material, the library's
standing on the wants when nothing fits, the pick call's decision to ask, or
one game's material. An "ask" needs nothing fetched, so the decision itself
is the basis."""


@dataclass(frozen=True, slots=True)
class ReplyStatement:
    """One statement of a reply: a sentence or a few, resting on the same evidence.

    ``game`` is the app id of the game the statement is about, or ``None``
    for a statement about none: an opening line, a question. ``offers`` says
    whether the statement puts that game to the player as a suggestion. The
    two are kept apart because a reply also speaks about games it does not
    suggest: a candidate it set aside and says why, the game the player
    named for a comparison, the one game a turn is about. Each of those has
    reviews behind it, and a statement that names its game can be held to
    citing that game's reviews.

    ``wants`` are the positions, in the request's wants, of the wants the
    statement speaks to. A want with no review behind it cannot be reached
    through a cite, and this is what lets code see that a mismatch or an
    undecided must was said and not passed over.

    ``cites`` are identifiers of the turn's excerpts, the reviews the
    statement rests on. The text holds no quote and no figure; what is shown
    of the evidence is supplied by code from these.
    """

    text: str
    game: int | None = None
    offers: bool = False
    wants: tuple[int, ...] = ()
    cites: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Reply:
    """What the chat says in one turn, before it is shown.

    ``kind`` is ``QUESTION`` for a reply that only asks and ``ANSWER``
    otherwise. ``statements`` are in the order they are read.

    >>> reply = Reply(ChatMessageKind.ANSWER, (
    ...     ReplyStatement("Two of these are close to what you asked for."),
    ...     ReplyStatement("The first is slow and quiet.", game=620, offers=True, cites=("e3",)),
    ...     ReplyStatement("The second is shorter.", game=400, offers=True, wants=(2,)),
    ...     ReplyStatement("Its music is praised too.", game=620, offers=True, cites=("e9",)),
    ...     ReplyStatement("A third has timed dialogue.", game=730, cites=("e12",)),
    ... ))
    >>> reply.offered
    (620, 400)
    """

    kind: ChatMessageKind
    statements: tuple[ReplyStatement, ...]

    @property
    def offered(self) -> tuple[int, ...]:
        """The games the reply offers, each once, in the order first offered.

        Derived from the statements that offer a game, so the list a later
        turn reads "the second one" against cannot disagree with what the
        reply said, and a game the reply only spoke about is not on it.
        """
        games = (statement.game for statement in self.statements if statement.offers)
        return tuple(dict.fromkeys(game for game in games if game is not None))


@dataclass(frozen=True, slots=True)
class Objection:
    """One thing the check found wrong in a readable reply.

    ``rule`` is the rule broken. ``game`` is the app id of the game the
    objection is about, or ``None`` for one about a statement on no game or
    about the reply as a whole. ``want`` is the position of the want it is
    about, for the rules that are about one. The three together identify an
    objection, so the one raised on a first answer can be found again in
    the retry's. ``words`` is the sentence the corrective retry names, in
    the identifiers the answer call was given.
    """

    rule: CheckRule
    game: int | None
    want: int | None
    words: str


@dataclass(frozen=True, slots=True)
class SettledObjection:
    """An objection with how it ended, for the record a measurement counts."""

    objection: Objection
    rung: ObjectionRung


@dataclass(frozen=True, slots=True)
class Answer:
    """One turn's reply, with the rung of the ladder that produced it.

    ``reply`` is present for ``ANSWERED``, ``RETRIED`` and ``SALVAGED`` and
    absent for ``WITHHELD``, ``UNREADABLE`` and ``UNAVAILABLE``. ``faults``
    are the faults still standing when the step ended, in words: for a
    salvaged reply what was removed from it, for an unreadable one what was
    wrong with the answer.

    ``objections`` are what the check raised over the turn, each once, with
    how it ended. An objection left standing is true of ``reply`` as it is
    returned; the others are not.

    >>> Answer(AnswerOutcome.UNAVAILABLE, None).faults
    ()
    """

    outcome: AnswerOutcome
    reply: Reply | None
    faults: tuple[str, ...] = ()
    objections: tuple[SettledObjection, ...] = ()


@dataclass(frozen=True, slots=True)
class Turn:
    """One chat turn: the message to append, and what each step made on the way.

    ``message`` is what the chat says, with the games it offered and its
    kind, ready to be appended to the conversation. ``ending`` says whether
    it is the answer call's reply or which fixed text. ``seed`` is the
    conversation's seed the turn ran under, kept so the pick can be
    regenerated from the request, the sheet and the seed.

    The rest is each step's result as it ran, absent for a step the turn did
    not reach: the understanding, the sheet the pick was made from, the
    pick, the material the reply was written from, and the answer. A turn
    about one game has no sheet and no pick. A turn that ended on a fixed
    text after the understand step has neither material nor answer.

    A page reads its links off the record: the report of each game in
    ``message.offered``, the game of a ``OneGameMaterial``, and the link for
    adding a game under a reply written from a ``NothingFitsMaterial``.

    >>> fixed = ChatMessage(ChatRole.CHAT, "Try again later.", kind=ChatMessageKind.FIXED)
    >>> turn = Turn(
    ...     fixed, TurnEnding.UNAVAILABLE, "conversation-a",
    ...     Understanding(UnderstandOutcome.UNAVAILABLE, None),
    ... )
    >>> turn.pick is None and turn.answer is None
    True
    """

    message: ChatMessage
    ending: TurnEnding
    seed: str
    understanding: Understanding
    sheet: Sheet | None = None
    pick: Pick | None = None
    basis: AnswerBasis | None = None
    answer: Answer | None = None
