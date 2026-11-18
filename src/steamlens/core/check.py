"""The check — what a readable reply is held to before it is shown.

The answer call's output is first read as a record over the turn's material
(``core.answer.parse_answer_response``). That reading already guarantees
that a statement's game is one the turn named, that only a candidate is
offered, that every cite was issued this turn and that every want number is
the request's. This module asks the next question: does the record keep the
chat's rules. It is pure. The call, the one corrective retry the objections
share with the parse's faults, and the journal live in ``chat.answer``.

The rules are of two kinds. Rules over the record are certain, because they
read fields: where a cited excerpt was fetched from, which wants a statement
says it speaks to, which games are offered. Rules over the text see a
pattern and not a meaning: a numeral, a passage in quotation marks, a title.
Neither kind says whether a sentence is true to the reviews behind it. That
is read by hand, and the record this module keeps is what the hand reading
and the measurements count.

One bound holds every rule: a reply that follows the answer prompt as
committed draws no objection. A rule stricter than the prompt would send
the model back to correct what it was told to write.

What a rule costs. Each objection names what the reply loses if it still
stands after the retry: a cite, a statement, every statement about a game,
or nothing. Removal is by the smallest unit the fault is in, and then the
rules run again on what is left, because a removal can leave a game without
what an offer needs: the statement that named it, or the one that named its
conflict with a must. A reply that offered games and offers none after
that, or has no statement left, is withheld. Three rules cost nothing, since
there is nothing to remove or the pattern is too loose to act on (relayed
wording, a working word, length). They are recorded, named in a retry when
one runs, and do not ask for one by themselves; ``_ASKS_ANYWAY`` is where
that would change.

An offer against a failed must is the rule the design leans on. The sheet
removes no game on evidence, so a game that fails a must can reach a reply,
and it stands there only with reviews: a statement about the game lists the
want and cites an excerpt fetched for that game and that want. Code checks
the label and where the cite came from. Whether the excerpt shows the
reading is wrong is the hand reading's.

The compose stage's grounding gate is the older sibling and is not called
here. It certifies each numeral against a minted value at the numeral's own
precision and refuses every quotation outside its evidence. A chat reply
has no minted value to match and keeps no certificate: its numeral is
either the digits of a title, a year or the player's own number, or it is
not allowed.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import Enum
from typing import Final

from steamlens.contracts import (
    AnswerBasis,
    CandidatesMaterial,
    ChatMessage,
    ChatMessageKind,
    ChatRole,
    CheckRule,
    CitedExcerpt,
    Firmness,
    GameMaterial,
    NothingFitsMaterial,
    Objection,
    ObjectionRung,
    OneGameMaterial,
    PlayerRequest,
    ReleaseYearsTarget,
    Reply,
    ReplyStatement,
    SettledObjection,
    Want,
    WantMaterial,
    WantStatus,
)
from steamlens.core.answer import answer_identifiers
from steamlens.core.game_names import holds_run, names_title, title_words
from steamlens.core.grounding import normalize_quotes
from steamlens.core.pick import GROUP_WORDS
from steamlens.core.sheet import offered_games

# The prompt asks for "under about 150 words" on a reply that offers three
# games. Counted over the statements' text.
MAX_REPLY_WORDS: Final = 150

# One word in quotation marks is an ordinary word set off ("cozy"). From two
# words on, a passage that is also in an excerpt is a reviewer's sentence.
MIN_QUOTE_WORDS: Final = 2

# Rules whose fault removes nothing and still asks for the retry. The three
# recorded rules are not here: with thinking off a form of "call" is in most
# replies, so a retry on it alone would be a second answer call on most
# turns. Adding a rule here is the whole switch.
_ASKS_ANYWAY: Final = frozenset({CheckRule.WANT_NOT_SPOKEN_TO})

_DIGITS: Final = re.compile(r"\d+")
_QUOTED: Final = re.compile(r'"([^"]+)"')
_QUOTE_EDGE: Final = re.compile(r"^[\s.,!?;:…]+|[\s.,!?;:…]+$")
_SPACE: Final = re.compile(r"\s+")
_TRADEMARKS: Final = re.compile("[™®©]")
_RELAYED: Final = re.compile(r"\b(?:call|calls|called|calling)\b", re.IGNORECASE)

# The material's labels as the answer call reads them, and the words of the
# steps that made the reply. A player should meet neither.
_WORKING_WORDS: Final = (
    *GROUP_WORDS.values(),
    "cannot tell", "could not be decided", "cluster", "candidate", "put forward",
    "this turn", "the material", "excerpt",
)
_WORKING_PATTERN: Final = re.compile(r"\byour \w+ want\b|\b[gwe]\d+\b", re.IGNORECASE)


class Cost(Enum):
    """What an objection costs a reply when it still stands after the retry."""

    CITE = "cite"
    STATEMENT = "statement"
    GAME = "game"
    NOTHING = "nothing"


@dataclass(frozen=True, slots=True)
class Raised:
    """One objection as it was raised on one reply, with what it would cost.

    ``statement`` is the position, in that reply, of the statement a
    ``CITE`` or a ``STATEMENT`` cost falls on, and ``cite`` the identifier a
    ``CITE`` cost removes. A ``GAME`` cost falls on every statement about
    the objection's game.
    """

    objection: Objection
    cost: Cost
    statement: int | None = None
    cite: str | None = None

    @property
    def asks_for_retry(self) -> bool:
        """Whether this objection alone is reason for the corrective retry."""
        return self.cost is not Cost.NOTHING or self.objection.rule in _ASKS_ANYWAY


@dataclass(frozen=True, slots=True)
class CiteOrigin:
    """Where one excerpt of a turn was fetched from.

    ``game`` is the app id of the game whose reviews it is. ``want`` is the
    position of the want it was read for, absent for an excerpt read for a
    subject of a turn about one game. ``named_side`` marks an excerpt of the
    game the player named for a comparison, read for the relative want
    ``want``.
    """

    game: int
    want: int | None = None
    named_side: bool = False


@dataclass(frozen=True, slots=True)
class _OutsideTitle:
    """A library game the turn is not about, as it would be found in a sentence."""

    title: str
    words: tuple[str, ...]
    # Set for a one-word title, which is looked for as the store writes it.
    as_written: re.Pattern[str] | None = None


@dataclass(frozen=True, slots=True)
class TurnEvidence:
    """What one turn put in front of the answer call, as the rules read it.

    Built once for a turn (``turn_evidence``) and used for every reply
    checked against it: the first answer, the retry's, and each pass of a
    removal.
    """

    request: PlayerRequest
    basis: AnswerBasis
    identifiers: Mapping[int, str]
    origins: Mapping[str, CiteOrigin]
    material_titles: Mapping[int, str]
    numerals: frozenset[str]
    review_passages: tuple[str, ...]
    own_passages: tuple[str, ...]
    outside: tuple[_OutsideTitle, ...]


@dataclass(frozen=True, slots=True)
class Enforced:
    """A reply after what still stood was removed from it.

    ``reply`` is ``None`` when the reply is withheld: the removals took
    every game it offered, or every statement. ``removed`` are the
    objections whose cost was taken, over every pass. ``standing`` are the
    ones still true of ``reply``, which cost nothing.
    """

    reply: Reply | None
    removed: tuple[Objection, ...]
    standing: tuple[Objection, ...]


def turn_evidence(
    request: PlayerRequest,
    basis: AnswerBasis,
    conversation: Sequence[ChatMessage],
    titles: Mapping[int, str],
) -> TurnEvidence:
    """Read one turn into what the rules need.

    ``request`` and ``basis`` are the ones the answer was written from,
    ``conversation`` everything said so far, and ``titles`` every library
    game's title by app id.

    The turn's games are the games of the material, the games left off the
    sheet, the games the request names and the games earlier replies
    offered. A reply may name any of them. Their titles' digits, the
    release years in the material, the years of a want about release years
    and the digits the player typed are the numerals a reply may hold.
    Every other library game is outside the turn.

    Where an excerpt was fetched from is read off its place in the
    material: under a game's want line, under a subject of a turn about one
    game, or on the named game's side of a comparison. An "ask" and a turn
    where nothing fits hold no excerpt.
    """
    material_titles = _material_titles(basis)
    known_ids = {*material_titles, *offered_games(conversation)}
    named: list[str] = []
    for game in request.named_games:
        known_ids.update(game.candidates)
        if game.app_id is not None:
            known_ids.add(game.app_id)
        named.extend(spelling for spelling in (game.words, game.title) if spelling)
    known_titles = [
        *(titles[app_id] for app_id in known_ids if app_id in titles),
        *material_titles.values(),
        *_left_out_titles(basis),
        *named,
    ]
    said = [message.text for message in conversation if message.role is ChatRole.PLAYER]

    excerpts = list(_excerpts_with_origin(basis))
    known_words = [title_words(title) for title in known_titles]
    return TurnEvidence(
        request=request,
        basis=basis,
        identifiers=answer_identifiers(basis),
        origins={cited.identifier: origin for cited, origin in excerpts},
        material_titles=material_titles,
        numerals=frozenset(
            run
            for text in (*known_titles, *said, *_years(request, basis))
            for run in _DIGITS.findall(text)
        ),
        review_passages=tuple(_plain(cited.excerpt.text) for cited, _ in excerpts),
        own_passages=tuple(_plain(text) for text in (*said, *known_titles)),
        outside=tuple(
            _outside_title(title)
            for app_id, title in sorted(titles.items())
            if app_id not in known_ids
            and title_words(title)
            and not any(holds_run(known, title_words(title)) for known in known_words)
        ),
    )


def check_reply(reply: Reply, turn: TurnEvidence) -> tuple[Raised, ...]:
    """Every rule ``reply`` breaks, as objections with what each would cost.

    ``reply`` is a record already read against the turn's material, so its
    games, cites and want numbers resolve. The rules, in the order they are
    reported:

    - a cite is in place: fetched for the statement's game, or, for an
      excerpt of the named game's side, cited beside the statement's own
      game's excerpt on the same relative want, which the statement lists.
      A statement about no game may cite any excerpt;
    - an offered game that fails a must has a statement about it that lists
      the want and cites an excerpt fetched for that game and want;
    - every other want an offered game fails, and every must it could not
      be decided on, is listed by a statement about that game or about no
      game. On a turn about one game that asks whether it would suit the
      player, the same holds for the musts;
    - the first statement about an offered game names it;
    - no numeral outside the turn's titles, years and the player's own
      numbers; no passage of a review in quotation marks; no library game
      the turn is not about;
    - recorded only: reviewers' wording relayed with a form of "call", a
      working word, and a reply over ``MAX_REPLY_WORDS``.

    Raises ``KeyError`` for a cite the turn's material does not hold, and
    ``ValueError`` when a game's lines are not one per want of the request:
    the reply was then read against another turn.
    """
    return (
        *_cites_out_of_place(reply, turn),
        *_conflicts_not_cited(reply, turn),
        *_wants_not_spoken_to(reply, turn),
        *_games_not_named(reply, turn),
        *_text_faults(reply, turn),
        *_recorded_only(reply),
    )


def enforce(reply: Reply, turn: TurnEvidence) -> Enforced:
    """``reply`` without what the check still objects to.

    Every costly objection of a pass is taken together, then the rules run
    again on what is left, until a pass finds none. A statement about no
    game that holds the whole title of a game removed on that pass goes
    with it. Each pass removes at least a cite, so this ends.

    The reply is withheld when it offered games and none is left, or when
    no statement is left.
    """
    removed: list[Objection] = []
    current: Reply | None = reply
    while current is not None:
        costly = [
            raised for raised in check_reply(current, turn) if raised.cost is not Cost.NOTHING
        ]
        if not costly:
            break
        removed.extend(raised.objection for raised in costly)
        current = _without(current, costly, turn)
    if current is not None and reply.offered and not current.offered:
        current = None
    standing = (
        tuple(raised.objection for raised in check_reply(current, turn))
        if current is not None else ()
    )
    return Enforced(current, tuple(removed), standing)


def settle(
    enforced: Enforced,
    *,
    retried: Sequence[Objection] = (),
    offered_before: Sequence[int] = (),
    offered_after: Sequence[int] = (),
) -> tuple[SettledObjection, ...]:
    """Each objection of a turn once, with how it ended.

    ``enforced`` is the answer that was kept, or the last one tried when
    none was. ``retried`` are the objections raised on the answer the
    retry was asked to correct, with the games that answer offered in
    ``offered_before`` and the games the retry's answer offered in
    ``offered_after``. They are left empty when the kept answer is the one
    the objections were raised on.

    An objection is the same one when its rule, game and want are. One of
    ``retried`` that the kept answer no longer draws was ``WITHDRAWN`` when
    its game was offered before and is not after, and ``CORRECTED``
    otherwise. The kept answer's own objections are ``REMOVED`` or
    ``STANDING``.

    >>> enforced = Enforced(None, (), ())
    >>> gone = Objection(CheckRule.CONFLICT_NOT_CITED, 620, 1, "...")
    >>> [done.rung.value for done in settle(enforced, retried=[gone], offered_before=[620])]
    ['withdrawn']
    """
    removed = {_key(objection): objection for objection in enforced.removed}
    standing = {
        _key(objection): objection
        for objection in enforced.standing
        if _key(objection) not in removed
    }
    settled: dict[tuple[CheckRule, int | None, int | None], SettledObjection] = {}
    for objection in retried:
        key = _key(objection)
        if key in removed or key in standing or key in settled:
            continue
        withdrawn = objection.game in offered_before and objection.game not in offered_after
        settled[key] = SettledObjection(
            objection, ObjectionRung.WITHDRAWN if withdrawn else ObjectionRung.CORRECTED
        )
    return (
        *settled.values(),
        *(SettledObjection(objection, ObjectionRung.REMOVED) for objection in removed.values()),
        *(SettledObjection(objection, ObjectionRung.STANDING) for objection in standing.values()),
    )


def _key(objection: Objection) -> tuple[CheckRule, int | None, int | None]:
    return (objection.rule, objection.game, objection.want)


def _quoted(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def _want_number(position: int) -> str:
    return _quoted(f"w{position + 1}")


def _plain(text: str) -> str:
    """A passage as it is compared: straight quotes, one case, single spaces, bare edges."""
    folded = _SPACE.sub(" ", normalize_quotes(text)).casefold()
    return _QUOTE_EDGE.sub("", folded)


def _material_titles(basis: AnswerBasis) -> dict[int, str]:
    """The games a statement of this turn may be about, by app id, with their titles."""
    match basis:
        case CandidatesMaterial(games=games, named_sides=sides):
            listed = [(game.app_id, game.title) for game in games]
        case OneGameMaterial(app_id=app_id, title=title, named_sides=sides):
            listed = [(app_id, title)]
        case _:
            return {}
    return dict([*listed, *((side.app_id, side.title) for side in sides)])


def _left_out_titles(basis: AnswerBasis) -> tuple[str, ...]:
    if isinstance(basis, CandidatesMaterial | NothingFitsMaterial):
        return (*basis.left_out.already_played, *basis.left_out.earlier_offers)
    return ()


def _years(request: PlayerRequest, basis: AnswerBasis) -> Iterator[str]:
    """The release years a reply may state: the material's, and a want's range."""
    match basis:
        case CandidatesMaterial(games=games):
            years = [game.release_year for game in games]
        case OneGameMaterial(release_year=release_year):
            years = [release_year]
        case _:
            years = []
    for want in request.wants:
        if isinstance(want.target, ReleaseYearsTarget):
            years.extend((want.target.first, want.target.last))
    return (str(year) for year in years if year is not None)


def _outside_title(title: str) -> _OutsideTitle:
    words = title_words(title)
    if len(words) > 1:
        return _OutsideTitle(title, words)
    # Rust, Dispatch and Satisfactory are also words, so a one-word title is
    # matched as the store writes it and never as plain words.
    written = re.escape(_TRADEMARKS.sub("", title).strip())
    return _OutsideTitle(title, words, re.compile(rf"(?<!\w){written}(?!\w)"))


def _excerpts_with_origin(basis: AnswerBasis) -> Iterator[tuple[CitedExcerpt, CiteOrigin]]:
    match basis:
        case CandidatesMaterial(games=games, named_sides=sides):
            for game in games:
                yield from _game_excerpts(game)
        case OneGameMaterial(app_id=app_id, subjects=subjects, standing_wants=standing,
                             named_sides=sides):
            for subject in subjects:
                for cited in subject.excerpts:
                    yield cited, CiteOrigin(app_id)
            if standing is not None:
                yield from _game_excerpts(standing)
        case _:
            return
    for side in sides:
        for cited in side.excerpts:
            yield cited, CiteOrigin(side.app_id, side.want, named_side=True)


def _game_excerpts(game: GameMaterial) -> Iterator[tuple[CitedExcerpt, CiteOrigin]]:
    for position, line in enumerate(game.wants):
        for cited in line.excerpts:
            yield cited, CiteOrigin(game.app_id, position)


def _cites_out_of_place(reply: Reply, turn: TurnEvidence) -> Iterator[Raised]:
    for index, statement in enumerate(reply.statements):
        if statement.game is None:
            continue
        for cite in statement.cites:
            reason = _out_of_place(statement.game, statement, turn.origins[cite], turn)
            if reason is None:
                continue
            words = f"statement {index + 1} cites {_quoted(cite)}, {reason}; the cite is dropped"
            yield Raised(
                Objection(CheckRule.CITE_OUT_OF_PLACE, statement.game, None, words),
                Cost.CITE, statement=index, cite=cite,
            )


def _out_of_place(
    game: int, statement: ReplyStatement, origin: CiteOrigin, turn: TurnEvidence
) -> str | None:
    """Why a cite does not belong on a statement about ``game``, or ``None`` when it does."""
    if origin.game == game:
        return None
    about = _quoted(turn.identifiers[game])
    if not origin.named_side or origin.want is None:
        other = _quoted(turn.identifiers[origin.game])
        return (
            f"an excerpt of {other}, and is about {about}; a statement cites excerpts of"
            " the game it is about"
        )
    # A comparison: the named game's side beside this game's own side of the
    # same relative want.
    own_side = CiteOrigin(game, origin.want)
    if origin.want in statement.wants and any(
        turn.origins[cite] == own_side for cite in statement.cites
    ):
        return None
    want = _want_number(origin.want)
    return (
        f"an excerpt of the game named for the comparison on {want}; a statement about"
        f" {about} cites it only when it lists {want} and also cites one of its own"
        f" game's excerpts on {want}"
    )


def _conflicts_not_cited(reply: Reply, turn: TurnEvidence) -> Iterator[Raised]:
    for game, about in _offered_games(reply, turn):
        game_id = _quoted(turn.identifiers[game.app_id])
        for position, (want, line) in enumerate(_lines(turn.request, game)):
            if want.firmness is not Firmness.MUST or line.status is not WantStatus.FAILS:
                continue
            fetched = [cited.identifier for cited in line.excerpts]
            if any(
                position in statement.wants and set(fetched).intersection(statement.cites)
                for statement in about
            ):
                continue
            number = _want_number(position)
            words = f"{game_id} is offered and fails {number} ({_quoted(want.words)}), a must"
            if fetched:
                words += (
                    f"; the offer stands only when a statement about {game_id} lists {number}"
                    f" and cites the excerpts read on it ({', '.join(fetched)}) that show the"
                    f" reading is wrong; name the conflict and cite them, or do not offer"
                    f" {game_id}"
                )
            else:
                words += (
                    f", and no review of it was read on {number}, so nothing can be cited"
                    f" against the reading; do not offer {game_id}"
                )
            yield Raised(
                Objection(CheckRule.CONFLICT_NOT_CITED, game.app_id, position, words), Cost.GAME
            )


def _wants_not_spoken_to(reply: Reply, turn: TurnEvidence) -> Iterator[Raised]:
    for game, _ in _offered_games(reply, turn):
        listed = _wants_listed(reply, game.app_id)
        game_id = _quoted(turn.identifiers[game.app_id])
        for position, (want, line) in enumerate(_lines(turn.request, game)):
            must = want.firmness is Firmness.MUST
            # A failed must is the conflict rule's: it needs a cite as well.
            owed = (
                line.status is WantStatus.CANNOT_TELL if must
                else line.status is WantStatus.FAILS
            )
            if not owed or position in listed:
                continue
            number = _want_number(position)
            state = "could not be decided on" if must else "fails"
            words = (
                f"{game_id} is offered and {state} {number} ({_quoted(want.words)})"
                f"{', a must' if must else ''}, and no statement about it lists {number};"
                f" say it in a statement about {game_id}, or once in a statement about no"
                f" game when it holds for every game offered, and list {number} there"
            )
            yield Raised(
                Objection(CheckRule.WANT_NOT_SPOKEN_TO, game.app_id, position, words), Cost.GAME
            )

    basis = turn.basis
    if (
        not isinstance(basis, OneGameMaterial)
        or basis.standing_wants is None
        or reply.kind is not ChatMessageKind.ANSWER
    ):
        return
    listed = _wants_listed(reply, basis.app_id)
    for position, (want, line) in enumerate(_lines(turn.request, basis.standing_wants)):
        if want.firmness is not Firmness.MUST or line.status is WantStatus.MATCHES:
            continue
        if position in listed:
            continue
        number = _want_number(position)
        state = "fails" if line.status is WantStatus.FAILS else "could not be decided on"
        words = (
            f"the game {state} {number} ({_quoted(want.words)}), a must, and no statement"
            f" lists {number}; say it, and list {number} in that statement"
        )
        yield Raised(
            Objection(CheckRule.WANT_NOT_SPOKEN_TO, basis.app_id, position, words), Cost.NOTHING
        )


def _games_not_named(reply: Reply, turn: TurnEvidence) -> Iterator[Raised]:
    for game, about in _offered_games(reply, turn):
        first = about[0]
        if names_title(first.text, game.title):
            continue
        index = reply.statements.index(first)
        game_id = _quoted(turn.identifiers[game.app_id])
        words = (
            f"statement {index + 1} is the first about {game_id}, which is offered, and does"
            f" not name it; name the game by its title ({_quoted(game.title)}) in that"
            " statement"
        )
        yield Raised(Objection(CheckRule.GAME_NOT_NAMED, game.app_id, None, words), Cost.GAME)


def _text_faults(reply: Reply, turn: TurnEvidence) -> Iterator[Raised]:
    for index, statement in enumerate(reply.statements):
        where = f"statement {index + 1}"
        text = statement.text

        numerals = [
            run for run in dict.fromkeys(_DIGITS.findall(text)) if run not in turn.numerals
        ]
        if numerals:
            words = (
                f"{where} holds the numeral {', '.join(_quoted(run) for run in numerals)};"
                " a reply holds no number but one in a game's title, a release year, or one"
                " the player wrote"
            )
            yield Raised(
                Objection(CheckRule.NUMERAL, statement.game, None, words),
                Cost.STATEMENT, statement=index,
            )

        quote = _review_quote(text, turn)
        if quote is not None:
            words = (
                f"{where} quotes a review ({_quoted(quote)}); a reply holds no quote, so say"
                " what the reviewer means in your own words"
            )
            yield Raised(
                Objection(CheckRule.QUOTE, statement.game, None, words),
                Cost.STATEMENT, statement=index,
            )

        text_words = title_words(text)
        for outside in turn.outside:
            if outside.as_written is not None:
                found, cost = outside.as_written.search(text) is not None, Cost.NOTHING
            else:
                found, cost = holds_run(text_words, outside.words), Cost.STATEMENT
            if not found:
                continue
            words = (
                f"{where} names {_quoted(outside.title)}, a library game that is not one of"
                " this turn's games; a reply speaks only about the games in front of it"
            )
            yield Raised(
                Objection(CheckRule.OUTSIDE_GAME_NAMED, statement.game, None, words),
                cost, statement=index,
            )


def _review_quote(text: str, turn: TurnEvidence) -> str | None:
    """The first passage in quotation marks that is a review's, as written."""
    for passage in _QUOTED.findall(normalize_quotes(text)):
        plain = _plain(passage)
        if len(plain.split()) < MIN_QUOTE_WORDS:
            continue
        # "no timer" in quotation marks is the player's want, and a title
        # reviewers repeat is still a title.
        if any(plain in own for own in turn.own_passages):
            continue
        if any(plain in review for review in turn.review_passages):
            return passage
    return None


def _recorded_only(reply: Reply) -> Iterator[Raised]:
    for index, statement in enumerate(reply.statements):
        where = f"statement {index + 1}"
        relayed = _RELAYED.search(statement.text)
        if relayed is not None:
            words = (
                f"{where} relays reviewers' wording with {_quoted(relayed.group())}; say what"
                " they mean in your own words"
            )
            yield Raised(
                Objection(CheckRule.RELAYED_WORDING, statement.game, None, words), Cost.NOTHING
            )
        folded = statement.text.casefold()
        working = [word for word in _WORKING_WORDS if word in folded]
        working.extend(match.group() for match in _WORKING_PATTERN.finditer(statement.text))
        if working:
            words = (
                f"{where} uses {', '.join(_quoted(word) for word in working)}, the words of"
                " the material and not of talk; say it in ordinary words"
            )
            yield Raised(
                Objection(CheckRule.WORKING_WORD, statement.game, None, words), Cost.NOTHING
            )
    length = sum(len(statement.text.split()) for statement in reply.statements)
    if length > MAX_REPLY_WORDS:
        words = f"the reply is {length} words; a reply stays under about {MAX_REPLY_WORDS}"
        yield Raised(Objection(CheckRule.TOO_LONG, None, None, words), Cost.NOTHING)


def _offered_games(
    reply: Reply, turn: TurnEvidence
) -> Iterator[tuple[GameMaterial, list[ReplyStatement]]]:
    """Each game the reply offers, with the statements about it in order."""
    if not isinstance(turn.basis, CandidatesMaterial):
        return
    offered = set(reply.offered)
    for game in turn.basis.games:
        if game.app_id in offered:
            yield game, [
                statement for statement in reply.statements if statement.game == game.app_id
            ]


def _lines(request: PlayerRequest, game: GameMaterial) -> Iterator[tuple[Want, WantMaterial]]:
    return zip(request.wants, game.wants, strict=True)


def _wants_listed(reply: Reply, app_id: int) -> set[int]:
    """The wants listed by the statements about one game or about no game."""
    return {
        position
        for statement in reply.statements
        if statement.game in (app_id, None)
        for position in statement.wants
    }


def _without(reply: Reply, costly: Sequence[Raised], turn: TurnEvidence) -> Reply | None:
    """``reply`` less the cost of each objection in ``costly``; ``None`` when nothing is left."""
    games = {
        raised.objection.game
        for raised in costly
        if raised.cost is Cost.GAME and raised.objection.game is not None
    }
    statements = {raised.statement for raised in costly if raised.cost is Cost.STATEMENT}
    cites = {(raised.statement, raised.cite) for raised in costly if raised.cost is Cost.CITE}
    gone = [
        title_words(turn.material_titles[app_id])
        for app_id in games
        if app_id in turn.material_titles
    ]
    kept: list[ReplyStatement] = []
    for index, statement in enumerate(reply.statements):
        if index in statements or statement.game in games:
            continue
        if statement.game is None and gone:
            text_words = title_words(statement.text)
            if any(holds_run(text_words, title) for title in gone):
                continue
        left = tuple(cite for cite in statement.cites if (index, cite) not in cites)
        kept.append(statement if left == statement.cites else replace(statement, cites=left))
    return Reply(reply.kind, tuple(kept)) if kept else None
