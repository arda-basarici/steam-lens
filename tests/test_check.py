"""Behavioral claims on the check — what a readable reply is held to, and what a fault costs.

The bound. A reply written the way the answer prompt asks draws no
objection: a conflict named and cited, a comparison citing both games, a
shared limit said once, the player's number repeated, a title's numeral.

Rules over the record. A cite belongs to the statement's game; the named
game's side may be cited beside the statement's own side of the same
relative want, by a statement about the named game, or by a statement about
no game. A game offered against a must it fails needs a statement that
lists the want and cites a review read on it, and cannot stand when none
was read. A softer want a game fails and a must it could not be decided on
are spoken to, by a statement about the game or about no game; a want the
game matches may go unmentioned. On a turn about one game only the musts
are owed, only for an answer, and the fault costs nothing.

Rules over the text. A numeral outside the turn's titles, years and the
player's own; a review's passage in quotation marks, where the player's own
words and a title are not a review's; an offered game its first statement
does not name; a library game the turn is not about, a one-word title only
recorded. Relayed wording, a working word and length are recorded, cost
nothing and do not ask for a retry.

What a fault costs. The smallest unit it is in, then the rules again: a
game whose naming statement went goes whole, a statement about no game that
names a removed game goes with it, and a reply left with no offer or no
statement is withheld. Each objection is settled once: corrected,
withdrawn, removed or standing.
"""

from __future__ import annotations

import pytest

from steamlens.contracts import (
    AskDecision,
    AspectTarget,
    CandidatesMaterial,
    ChatMessage,
    ChatMessageKind,
    ChatRole,
    CheckRule,
    CitedExcerpt,
    Excerpt,
    Feeling,
    Firmness,
    GameMaterial,
    LeftOut,
    MustStanding,
    NamedGame,
    NamedGameRole,
    NamedSideMaterial,
    NameMatch,
    Objection,
    ObjectionRung,
    OneGameMaterial,
    PlayerRequest,
    ReadState,
    ReleaseYearsTarget,
    Reply,
    ReplyStatement,
    RequestIntent,
    SentimentGroup,
    Stance,
    SubjectMaterial,
    TermTarget,
    Want,
    WantFinding,
    WantMaterial,
    WantStatus,
)
from steamlens.core.check import (
    MAX_REPLY_WORDS,
    Cost,
    Enforced,
    Raised,
    TurnEvidence,
    check_reply,
    enforce,
    settle,
    turn_evidence,
)

HARBOR, GARDEN, HADES = 7001, 7002, 7009
_TIMER, _MUSIC, _PACE, _LAPTOP = range(4)

_EXCERPT_TEXT = {
    "e1": "there is no timer at all, take as long as you like",
    "e2": "the timer on the last level is brutal",
    "e3": "the music gets repetitive fast",
    "e4": "a slow and gentle pace throughout",
    "e5": "the soundtrack is lovely",
    "e6": "frantic from the first room to the last",
}


def _line(
    status: WantStatus, finding: WantFinding, app_id: int, *cites: str,
    group: SentimentGroup | None = None,
) -> WantMaterial:
    excerpts = tuple(
        CitedExcerpt(cite, Excerpt(app_id, f"r-{cite}", _EXCERPT_TEXT[cite])) for cite in cites
    )
    read = ReadState.READ if excerpts else ReadState.NOTHING_TO_READ
    return WantMaterial(status, finding, read, group=group, excerpts=excerpts)


# "Nothing with a timer" (must), "nice music" (nice-to-have), "less frantic
# than Hades" (want), "runs on my laptop" (must, nothing stored decides it).
# Quiet Harbor 2 fails the timer must on clustering words and its music is
# criticised. Stone Garden could not be decided on the timer.
_REQUEST = PlayerRequest(
    intent=RequestIntent.RECOMMEND,
    named_games=(
        NamedGame("hades", HADES, NameMatch.EXACT, NamedGameRole.LIKE_THIS, Feeling.LIKED),
    ),
    wants=(
        Want("nothing with a timer", Firmness.MUST, Stance.AVOIDS, TermTarget(("timer",))),
        Want("nice music", Firmness.NICE_TO_HAVE, Stance.WANTS, AspectTarget("music")),
        Want("less frantic", Firmness.WANT, Stance.WANTS, TermTarget(("frantic",)),
             compared_to="hades"),
        Want("runs on my laptop at 60 fps", Firmness.MUST, Stance.WANTS, None),
    ),
)
_HARBOR = GameMaterial(
    HARBOR, "Quiet Harbor 2", "", MustStanding.CONFLICTS,
    (
        _line(WantStatus.FAILS, WantFinding.TERM_CLUSTERS, HARBOR, "e1", "e2"),
        _line(WantStatus.FAILS, WantFinding.ASPECT_GROUP, HARBOR, "e3",
              group=SentimentGroup.CLEARLY_NEGATIVE),
        _line(WantStatus.CANNOT_TELL, WantFinding.RELATIVE_TO_NAMED_GAME, HARBOR, "e4"),
        _line(WantStatus.CANNOT_TELL, WantFinding.NO_DATA, HARBOR),
    ),
    release_year=2019,
)
_GARDEN = GameMaterial(
    GARDEN, "Return of the Stone Garden", "", MustStanding.OPEN,
    (
        _line(WantStatus.CANNOT_TELL, WantFinding.WRITTEN_ABOUT_ELSEWHERE, GARDEN),
        _line(WantStatus.MATCHES, WantFinding.ASPECT_GROUP, GARDEN, "e5",
              group=SentimentGroup.STRONGLY_POSITIVE),
        _line(WantStatus.CANNOT_TELL, WantFinding.RELATIVE_TO_NAMED_GAME, GARDEN),
        _line(WantStatus.CANNOT_TELL, WantFinding.NO_DATA, GARDEN),
    ),
)
_HADES_SIDE = NamedSideMaterial(
    _PACE, HADES, "Hades",
    (CitedExcerpt("e6", Excerpt(HADES, "r-e6", _EXCERPT_TEXT["e6"])),),
)
_MATERIAL = CandidatesMaterial(
    (_HARBOR, _GARDEN), (_HADES_SIDE,), LeftOut(already_played=("Stardew Valley",)),
)
_LIBRARY = {
    HARBOR: "Quiet Harbor 2", GARDEN: "Return of the Stone Garden", HADES: "Hades",
    7010: "Baldur's Gate 3", 7011: "Rust", 7012: "Stardew Valley", 7013: "Lethal Company",
}
_CONVERSATION = (
    ChatMessage(ChatRole.PLAYER, "something with no timer"),
    ChatMessage(ChatRole.CHAT, "How about this one.", offered=(7013,),
                kind=ChatMessageKind.ANSWER),
    ChatMessage(
        ChatRole.PLAYER,
        "nice music too, less frantic than hades, and it should run on my laptop at 60 fps",
    ),
)
_TURN = turn_evidence(_REQUEST, _MATERIAL, _CONVERSATION, _LIBRARY)

_LIMIT = ReplyStatement(
    "Nothing here says how a game runs on your laptop, so 60 fps is not something I can"
    " confirm for either.",
    wants=(_LAPTOP,),
)
_HARBOR_CONFLICT = ReplyStatement(
    "Quiet Harbor 2 has timers come up in its reviews, though one reviewer writes that there"
    " is none to worry about, so treat that as open.",
    game=HARBOR, offers=True, wants=(_TIMER,), cites=("e1",),
)
_HARBOR_REST = ReplyStatement(
    "Its music is criticised, and its reviewers describe a slower pace than Hades players"
    " describe.",
    game=HARBOR, offers=True, wants=(_MUSIC, _PACE), cites=("e3", "e4", "e6"),
)
_GARDEN_OFFER = ReplyStatement(
    "Return of the Stone Garden gets warm words for its soundtrack, and none of the reviews"
    " held for it mention a timer, which does not mean it has none.",
    game=GARDEN, offers=True, wants=(_TIMER, _MUSIC), cites=("e5",),
)
_HADES_NOTE = ReplyStatement(
    "For reference, Hades players describe it as frantic throughout.",
    game=HADES, wants=(_PACE,), cites=("e6",),
)
_GOOD = Reply(
    ChatMessageKind.ANSWER,
    (_LIMIT, _HARBOR_CONFLICT, _HARBOR_REST, _GARDEN_OFFER, _HADES_NOTE),
)


def _reply(*statements: ReplyStatement) -> Reply:
    return Reply(ChatMessageKind.ANSWER, statements)


def _with(statement: ReplyStatement, **changes: object) -> ReplyStatement:
    fields = {
        "text": statement.text, "game": statement.game, "offers": statement.offers,
        "wants": statement.wants, "cites": statement.cites,
    }
    return ReplyStatement(**{**fields, **changes})  # type: ignore[arg-type]


def _swap(reply: Reply, old: ReplyStatement, new: ReplyStatement) -> Reply:
    return Reply(reply.kind, tuple(new if item is old else item for item in reply.statements))


def _rules(raised: tuple[Raised, ...]) -> list[CheckRule]:
    return [found.objection.rule for found in raised]


def _check(reply: Reply, turn: TurnEvidence = _TURN) -> tuple[Raised, ...]:
    return check_reply(reply, turn)


# --- the bound -------------------------------------------------------------------


def test_a_reply_written_as_the_prompt_asks_draws_no_objection() -> None:
    """A conflict named and cited, a comparison citing both games, a limit
    said once, the player's 60, a title's 2, and the named game spoken
    about from its own reviews."""
    assert _check(_GOOD) == ()
    assert enforce(_GOOD, _TURN) == Enforced(_GOOD, (), ())


# --- rules over the record -------------------------------------------------------


def test_a_cite_fetched_for_another_game_is_out_of_place_and_costs_only_the_cite() -> None:
    borrowed = _with(_GARDEN_OFFER, cites=("e5", "e3"))
    (found,) = _check(_swap(_GOOD, _GARDEN_OFFER, borrowed))
    assert found.objection.rule is CheckRule.CITE_OUT_OF_PLACE
    assert (found.cost, found.cite, found.objection.game) == (Cost.CITE, "e3", GARDEN)
    assert '"e3", an excerpt of "g1", and is about "g2"' in found.objection.words

    kept = enforce(_swap(_GOOD, _GARDEN_OFFER, borrowed), _TURN).reply
    assert kept == _GOOD


def test_the_named_side_is_cited_only_beside_the_games_own_side_of_that_want() -> None:
    """Three ways a comparison can be short: the relative want not listed,
    this game's own side not cited, and another want's excerpt standing in
    for it."""
    for short in (
        _with(_HARBOR_REST, wants=(_MUSIC,)),
        _with(_HARBOR_REST, cites=("e3", "e6")),
        _with(_HARBOR_REST, wants=(_PACE,), cites=("e1", "e6")),
    ):
        raised = _check(_swap(_GOOD, _HARBOR_REST, short))
        out_of_place = [
            found for found in raised if found.objection.rule is CheckRule.CITE_OUT_OF_PLACE
        ]
        assert [found.cite for found in out_of_place] == ["e6"]
        assert "named for the comparison" in out_of_place[0].objection.words


def test_a_statement_about_no_game_may_cite_any_excerpt() -> None:
    shared = _with(_LIMIT, cites=("e1", "e5", "e6"))
    assert _check(_swap(_GOOD, _LIMIT, shared)) == ()


def test_an_offer_against_a_failed_must_needs_the_want_listed_and_its_reviews_cited() -> None:
    """Listing the want with another want's excerpt, and citing the right
    excerpt without listing the want, both leave the conflict unnamed to
    code."""
    for unnamed in (
        _with(_HARBOR_CONFLICT, cites=("e3",)),
        _with(_HARBOR_CONFLICT, wants=()),
        _with(_HARBOR_CONFLICT, cites=()),
    ):
        raised = _check(_swap(_GOOD, _HARBOR_CONFLICT, unnamed))
        conflicts = [
            found for found in raised if found.objection.rule is CheckRule.CONFLICT_NOT_CITED
        ]
        assert len(conflicts) == 1
        objection = conflicts[0].objection
        assert (objection.game, objection.want, conflicts[0].cost) == (HARBOR, _TIMER, Cost.GAME)
        assert '"g1" is offered and fails "w1" ("nothing with a timer"), a must' in objection.words
        assert "(e1, e2)" in objection.words


def test_a_failed_must_with_no_review_read_cannot_be_offered_against() -> None:
    """The cap can cut a must and a read can come back empty. Whatever the
    statement cites, nothing was read on the want."""
    unread = GameMaterial(
        HARBOR, "Quiet Harbor 2", "", MustStanding.CONFLICTS,
        (
            _line(WantStatus.FAILS, WantFinding.NOT_LISTED, HARBOR),
            *_HARBOR.wants[1:],
        ),
        release_year=2019,
    )
    turn = turn_evidence(
        _REQUEST, CandidatesMaterial((unread, _GARDEN), (_HADES_SIDE,)), _CONVERSATION, _LIBRARY
    )
    claimed = _with(_HARBOR_CONFLICT, cites=("e3",))
    (found,) = _check(_swap(_GOOD, _HARBOR_CONFLICT, claimed), turn)
    assert found.objection.rule is CheckRule.CONFLICT_NOT_CITED
    assert 'no review of it was read on "w1"' in found.objection.words


def test_a_miss_and_an_undecided_must_are_spoken_to_and_a_match_need_not_be() -> None:
    """Quiet Harbor 2's criticised music is a softer want it fails. Stone
    Garden's praised music is a match and may go unmentioned. The laptop
    must is undecided for both and is said once, about no game."""
    silent_on_music = _with(_HARBOR_REST, wants=(_PACE,), cites=("e4", "e6"))
    (found,) = _check(_swap(_GOOD, _HARBOR_REST, silent_on_music))
    assert found.objection.rule is CheckRule.WANT_NOT_SPOKEN_TO
    assert (found.objection.game, found.objection.want, found.cost) == (HARBOR, _MUSIC, Cost.GAME)

    match_unmentioned = _with(_GARDEN_OFFER, wants=(_TIMER,))
    assert _check(_swap(_GOOD, _GARDEN_OFFER, match_unmentioned)) == ()

    without_limit = _reply(_HARBOR_CONFLICT, _HARBOR_REST, _GARDEN_OFFER, _HADES_NOTE)
    owed = [
        (found.objection.game, found.objection.want) for found in _check(without_limit)
    ]
    assert owed == [(HARBOR, _LAPTOP), (GARDEN, _LAPTOP)]

    timer_unsaid = _with(_GARDEN_OFFER, wants=(_MUSIC,))
    (found,) = _check(_swap(_GOOD, _GARDEN_OFFER, timer_unsaid))
    assert (found.objection.game, found.objection.want) == (GARDEN, _TIMER)
    assert "could not be decided on" in found.objection.words


_SUITS = OneGameMaterial(
    HARBOR, "Quiet Harbor 2", "", 2019,
    (SubjectMaterial("would it suit me", WantFinding.NO_DATA, ReadState.NOTHING_TO_READ),),
    standing_wants=_HARBOR,
)
_ONE_GAME_TURN = turn_evidence(
    PlayerRequest(
        intent=RequestIntent.ABOUT_GAME, wants=_REQUEST.wants,
        named_games=(
            NamedGame("quiet harbor 2", HARBOR, NameMatch.EXACT, NamedGameRole.ASK_ABOUT,
                      Feeling.UNKNOWN),
        ),
    ),
    _SUITS, (ChatMessage(ChatRole.PLAYER, "would quiet harbor 2 suit me"),), _LIBRARY,
)


def test_a_turn_about_one_game_owes_no_want_even_with_the_standing_wants_read() -> None:
    # The standing-wants read comes with every question no stored field fits,
    # so a reply that answers the question and leaves an undecided must unsaid
    # has followed the prompt.
    unsaid = ReplyStatement("Its pace is described as slow.", game=HARBOR, cites=("e4",))
    assert _check(Reply(ChatMessageKind.ANSWER, (unsaid,)), _ONE_GAME_TURN) == ()


# --- rules over the text ---------------------------------------------------------


def test_a_numeral_is_allowed_only_from_a_title_a_year_or_the_player() -> None:
    def numerals(text: str, turn: TurnEvidence = _TURN) -> list[str]:
        raised = _check(_swap(_GOOD, _HADES_NOTE, _with(_HADES_NOTE, text=text)), turn)
        return [
            found.objection.words for found in raised
            if found.objection.rule is CheckRule.NUMERAL
        ]

    assert numerals("Hades came up beside Quiet Harbor 2, from 2019, for your 60 fps.") == []
    (words,) = numerals("Hades has 40 reviews on this, and 3 of them agree.")
    assert 'holds the numeral "40", "3"' in words

    # The request block shows the model the range a want was read as
    # ("2021 to now"), though the player never typed the year.
    asks = Reply(
        ChatMessageKind.QUESTION, (ReplyStatement("Anything from 2021 on, or older too?"),)
    )
    conversation = (ChatMessage(ChatRole.PLAYER, "something from the last few years"),)
    for target, allowed in ((ReleaseYearsTarget(2021, None), True), (None, False)):
        request = PlayerRequest(
            intent=RequestIntent.RECOMMEND,
            wants=(Want("from the last few years", Firmness.WANT, Stance.WANTS, target),),
        )
        turn = turn_evidence(request, AskDecision(("how old",)), conversation, _LIBRARY)
        assert (_check(asks, turn) == ()) is allowed


def test_a_review_in_quotation_marks_is_a_quote_and_the_players_words_are_not() -> None:
    def quotes(text: str) -> list[Raised]:
        raised = _check(_swap(_GOOD, _HADES_NOTE, _with(_HADES_NOTE, text=text)))
        return [found for found in raised if found.objection.rule is CheckRule.QUOTE]

    (found,) = quotes("Hades players say it is “frantic from the first room,” and mean it.")
    assert (found.cost, found.statement) == (Cost.STATEMENT, 4)
    assert quotes('Hades is the "less frantic than hades" comparison you asked for.') == []
    assert quotes('Hades is often described as "frantic" by its players.') == []
    assert quotes('Hades is not "Quiet Harbor 2", of course.') == []
    assert quotes('Hades players call it "a wild ride" all the way.') == []


def test_the_first_statement_about_an_offered_game_names_it_whole_or_shortened() -> None:
    shortened = _with(
        _GARDEN_OFFER,
        text="Stone Garden gets warm words for its soundtrack, with no word on a timer.",
    )
    assert _check(_swap(_GOOD, _GARDEN_OFFER, shortened)) == ()

    unnamed = _with(_GARDEN_OFFER, text="The second gets warm words for its soundtrack.")
    (found,) = _check(_swap(_GOOD, _GARDEN_OFFER, unnamed))
    assert found.objection.rule is CheckRule.GAME_NOT_NAMED
    assert (found.objection.game, found.cost) == (GARDEN, Cost.GAME)
    assert '("Return of the Stone Garden")' in found.objection.words

    aside = _with(_HADES_NOTE, text="The game you named is frantic throughout.")
    assert _check(_swap(_GOOD, _HADES_NOTE, aside)) == ()


def test_a_library_game_the_turn_is_not_about_costs_its_statement() -> None:
    """A game left off the sheet, a game the player named and a game an
    earlier reply offered are the turn's. Another library title is not,
    and a one-word title is only recorded, since Rust is also a word."""

    def outside(text: str) -> list[Raised]:
        raised = _check(_swap(_GOOD, _HADES_NOTE, _with(_HADES_NOTE, text=text)))
        return [
            found for found in raised if found.objection.rule is CheckRule.OUTSIDE_GAME_NAMED
        ]

    assert outside("Hades aside, Stardew Valley and Lethal Company were left out.") == []
    (found,) = outside("Hades fans often move on to Baldur's Gate 3.")
    assert (found.cost, found.statement) == (Cost.STATEMENT, 4)
    (found,) = outside("Hades fans often move on to Rust.")
    assert (found.cost, found.asks_for_retry) == (Cost.NOTHING, False)
    assert outside("Hades never lets its combat rust.") == []


def test_relayed_wording_a_working_word_and_length_are_recorded_and_cost_nothing() -> None:
    relayed = _with(
        _HADES_NOTE,
        text="Hades players keep calling it frantic, which is strongly positive for some.",
    )
    long = _with(_LIMIT, text=" ".join(["word"] * (MAX_REPLY_WORDS + 1)))
    reply = _swap(_swap(_GOOD, _HADES_NOTE, relayed), _LIMIT, long)
    raised = _check(reply)
    assert _rules(raised) == [
        CheckRule.RELAYED_WORDING, CheckRule.WORKING_WORD, CheckRule.TOO_LONG,
    ]
    assert not any(found.asks_for_retry for found in raised)
    assert all(found.cost is Cost.NOTHING for found in raised)
    enforced = enforce(reply, _TURN)
    assert enforced.reply == reply
    assert enforced.removed == ()
    assert len(enforced.standing) == 3


@pytest.mark.parametrize(
    ("text", "relays"),
    [
        ("Hades players call it frantic.", True),
        ("Hades players call its combat frantic.", True),
        ("One Hades reviewer calls the pace relentless.", True),
        ("Hades gets called a frantic game by its players.", True),
        ("Its players keep calling Hades one of the best.", True),
        ("Its players call Hades frantic.", True),
        ("Hades players describe hard calls that stay with them.", False),
        ("Hades players say every call is theirs to make.", False),
        ("Hades players say the last area calls for patience.", False),
        ("In Hades, players say, death is a close call.", False),
    ],
)
def test_relayed_wording_is_call_as_a_verb_and_not_the_word_alone(
    text: str, relays: bool
) -> None:
    """The rule is recorded to be counted, so a decision a player has to
    make ("a hard call") must not be counted as a reviewer's wording."""
    raised = _check(_swap(_GOOD, _HADES_NOTE, _with(_HADES_NOTE, text=text)))
    assert (CheckRule.RELAYED_WORDING in _rules(raised)) is relays


def test_a_turn_that_names_no_game_is_held_to_the_text_rules_only() -> None:
    turn = turn_evidence(
        PlayerRequest(intent=RequestIntent.RECOMMEND), AskDecision(("what kind of game",)),
        (ChatMessage(ChatRole.PLAYER, "what should i play"),), _LIBRARY,
    )
    asks = Reply(ChatMessageKind.QUESTION, (ReplyStatement("What kind of game are you after?"),))
    assert _check(asks, turn) == ()
    names = Reply(ChatMessageKind.QUESTION, (ReplyStatement("Something like Lethal Company?"),))
    assert _rules(_check(names, turn)) == [CheckRule.OUTSIDE_GAME_NAMED]
    assert enforce(names, turn).reply is None


# --- what a fault costs ----------------------------------------------------------


def test_a_fault_in_the_statement_that_names_a_game_costs_the_game() -> None:
    """The numeral costs the statement. What is left about the game no
    longer names it, or names its conflict, so the second pass takes the
    rest."""
    counted = _with(
        _HARBOR_CONFLICT,
        text="Quiet Harbor 2 has timers in 14 of its reviews, though one says there is none.",
    )
    enforced = enforce(_swap(_GOOD, _HARBOR_CONFLICT, counted), _TURN)
    assert enforced.reply == _reply(_LIMIT, _GARDEN_OFFER, _HADES_NOTE)
    assert {objection.rule for objection in enforced.removed} == {
        CheckRule.NUMERAL, CheckRule.CONFLICT_NOT_CITED, CheckRule.GAME_NOT_NAMED,
    }


def test_a_statement_about_no_game_that_names_a_removed_game_goes_with_it() -> None:
    opener = ReplyStatement(
        "Quiet Harbor 2 and one more are worth a look, though your laptop is an open question.",
        wants=(_LAPTOP,),
    )
    unnamed_conflict = _with(_HARBOR_CONFLICT, cites=())
    reply = _reply(opener, unnamed_conflict, _HARBOR_REST, _GARDEN_OFFER)
    enforced = enforce(reply, _TURN)
    # The opener carried the laptop limit; with it gone Stone Garden's
    # undecided must is unsaid, so the last offer goes and nothing is shown.
    assert enforced.reply is None
    assert [objection.rule for objection in enforced.removed] == [
        CheckRule.CONFLICT_NOT_CITED, CheckRule.WANT_NOT_SPOKEN_TO,
    ]

    kept = enforce(_reply(opener, _LIMIT, unnamed_conflict, _HARBOR_REST, _GARDEN_OFFER), _TURN)
    assert kept.reply == _reply(_LIMIT, _GARDEN_OFFER)


def test_a_reply_left_with_no_offer_or_no_statement_is_withheld() -> None:
    only_harbor = _reply(_LIMIT, _with(_HARBOR_CONFLICT, cites=()), _HARBOR_REST, _HADES_NOTE)
    assert enforce(only_harbor, _TURN).reply is None

    counted = Reply(
        ChatMessageKind.ANSWER,
        (ReplyStatement("Quiet Harbor 2 has 14 reviews on its pace.", game=HARBOR,
                        wants=(_TIMER, _LAPTOP)),),
    )
    enforced = enforce(counted, _ONE_GAME_TURN)
    assert enforced.reply is None
    assert [objection.rule for objection in enforced.removed] == [CheckRule.NUMERAL]


def test_each_objection_is_settled_once_by_how_it_ended() -> None:
    def objection(rule: CheckRule, game: int | None, want: int | None = None) -> Objection:
        return Objection(rule, game, want, "…")

    conflict = objection(CheckRule.CONFLICT_NOT_CITED, HARBOR, _TIMER)
    numeral = objection(CheckRule.NUMERAL, GARDEN)
    unsaid = objection(CheckRule.WANT_NOT_SPOKEN_TO, GARDEN, _LAPTOP)
    relayed = objection(CheckRule.RELAYED_WORDING, None)
    kept = Enforced(_GOOD, (unsaid,), (relayed, relayed))

    settled = settle(
        kept,
        retried=(conflict, numeral, numeral, unsaid, relayed),
        offered_before=(HARBOR, GARDEN), offered_after=(GARDEN,),
    )
    assert [(done.objection, done.rung) for done in settled] == [
        (conflict, ObjectionRung.WITHDRAWN),
        (numeral, ObjectionRung.CORRECTED),
        (unsaid, ObjectionRung.REMOVED),
        (relayed, ObjectionRung.STANDING),
    ]
    # With no earlier answer to compare with, an objection is removed or standing.
    assert [done.rung for done in settle(kept)] == [
        ObjectionRung.REMOVED, ObjectionRung.STANDING,
    ]
