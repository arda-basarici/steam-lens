"""Behavioral claims on the turn's rules — the way a reading goes, and the fixed texts.

The claims: a reading with no request, one out of scope and a question
about the numbers end the turn, each on its own ending; a request for games
goes on whatever games it names; a request about one game goes on only
when the game it asks about resolved to a library title, and the first
such game is the one read; every ending but a written reply has exactly
one text; where the understand step already answers a reading with a fixed
text, the turn sends the same one; a written reply becomes a message by its
statements in order; and what a page links under a message makes true what
the answer prompt tells the model the page shows: the report of each game
a reply offers or is about, the two kept apart, and the link for adding a
game under a reply that found nothing and under the text for an unmeasured
game, never under a question.
"""

from __future__ import annotations

import pytest

from steamlens.contracts import (
    Answer,
    AnswerBasis,
    AnswerOutcome,
    AskDecision,
    CandidatesMaterial,
    ChatMessageKind,
    ChatRole,
    Feeling,
    NamedGame,
    NamedGameRole,
    NameMatch,
    NothingFitsMaterial,
    OneGameMaterial,
    PickOutcome,
    PlayerRequest,
    Reply,
    ReplyStatement,
    RequestIntent,
    Subject,
    Turn,
    TurnEnding,
    Understanding,
    UnderstandOutcome,
)
from steamlens.core.turn import (
    FIXED_TEXTS,
    OneGameTurn,
    RecommendTurn,
    TurnLinks,
    ending_of_answer,
    ending_without_decision,
    fixed_message,
    games_asked_about,
    plan_turn,
    reply_message,
    turn_links,
)
from steamlens.core.understand import fixed_reply

_HADES = 1145360


def _named(
    role: NamedGameRole,
    match: NameMatch = NameMatch.EXACT,
    *,
    app_id: int | None = _HADES,
    candidates: tuple[int, ...] = (),
) -> NamedGame:
    return NamedGame("it", app_id, match, role, Feeling.UNKNOWN, candidates=candidates)


def _about(*games: NamedGame) -> Understanding:
    request = PlayerRequest(
        RequestIntent.ABOUT_GAME, named_games=games, subjects=(Subject("is it hard", None),)
    )
    return Understanding(UnderstandOutcome.UNDERSTOOD, request)


def _read(intent: RequestIntent) -> Understanding:
    return Understanding(UnderstandOutcome.UNDERSTOOD, PlayerRequest(intent))


@pytest.mark.parametrize(
    ("understanding", "ending"),
    [
        (Understanding(UnderstandOutcome.UNAVAILABLE, None), TurnEnding.UNAVAILABLE),
        (Understanding(UnderstandOutcome.UNREADABLE, None), TurnEnding.NOT_UNDERSTOOD),
        (_read(RequestIntent.OUT_OF_SCOPE), TurnEnding.OUT_OF_SCOPE),
        (_read(RequestIntent.ABOUT_NUMBERS), TurnEnding.NUMBERS_UNEXPLAINED),
    ],
)
def test_a_reading_the_turn_cannot_take_further_ends_it(
    understanding: Understanding, ending: TurnEnding
) -> None:
    assert plan_turn(understanding) is ending


def test_a_request_for_games_goes_on_whatever_games_it_names() -> None:
    """An unmeasured liked game and a played name several titles share do
    not stop a recommendation: the sheet reads them, and the pick decides."""
    request = PlayerRequest(
        RequestIntent.RECOMMEND,
        named_games=(
            _named(NamedGameRole.LIKE_THIS, NameMatch.NOT_IN_LIBRARY, app_id=None),
            _named(NamedGameRole.NOT_THIS, NameMatch.SEVERAL, app_id=None, candidates=(1, 2)),
        ),
    )
    salvaged = Understanding(UnderstandOutcome.SALVAGED, request, ("a fault",))
    assert plan_turn(salvaged) == RecommendTurn(request)


@pytest.mark.parametrize("match", [NameMatch.EXACT, NameMatch.PARTIAL])
def test_a_turn_about_a_game_that_resolved_reads_that_game(match: NameMatch) -> None:
    understanding = _about(_named(NamedGameRole.ASK_ABOUT, match))
    assert understanding.request is not None
    assert plan_turn(understanding) == OneGameTurn(understanding.request, _HADES)


@pytest.mark.parametrize(
    ("games", "ending"),
    [
        (
            (_named(NamedGameRole.ASK_ABOUT, NameMatch.NOT_IN_LIBRARY, app_id=None),),
            TurnEnding.GAME_NOT_MEASURED,
        ),
        (
            (_named(NamedGameRole.ASK_ABOUT, NameMatch.SEVERAL, app_id=None, candidates=(1, 2)),),
            TurnEnding.GAME_UNCLEAR,
        ),
        (
            (_named(NamedGameRole.ASK_ABOUT, NameMatch.UNCLEAR, app_id=None),),
            TurnEnding.GAME_UNCLEAR,
        ),
        ((), TurnEnding.GAME_UNCLEAR),
    ],
)
def test_a_turn_about_a_game_that_did_not_resolve_ends_on_its_stand_in(
    games: tuple[NamedGame, ...], ending: TurnEnding
) -> None:
    assert plan_turn(_about(*games)) is ending


def test_a_game_named_under_another_role_is_not_taken_as_the_one_asked_about() -> None:
    """A played game that resolved is in the request, and the turn still
    asks which game is meant: code does not guess the subject of a question
    from the games that happen to be standing."""
    assert plan_turn(_about(_named(NamedGameRole.NOT_THIS))) is TurnEnding.GAME_UNCLEAR


def test_the_first_game_asked_about_decides_when_there_are_several() -> None:
    unresolved = _named(NamedGameRole.ASK_ABOUT, NameMatch.UNCLEAR, app_id=None)
    resolved = _named(NamedGameRole.ASK_ABOUT)
    liked = _named(NamedGameRole.LIKE_THIS, app_id=620)

    first_resolved = _about(liked, resolved, unresolved)
    assert first_resolved.request is not None
    assert games_asked_about(first_resolved.request) == (resolved, unresolved)
    assert plan_turn(first_resolved) == OneGameTurn(first_resolved.request, _HADES)
    assert plan_turn(_about(unresolved, resolved)) is TurnEnding.GAME_UNCLEAR


def test_every_ending_but_a_written_reply_has_one_text_of_its_own() -> None:
    assert set(FIXED_TEXTS) == set(TurnEnding) - {TurnEnding.REPLIED}
    assert len(set(FIXED_TEXTS.values())) == len(FIXED_TEXTS)
    for ending in FIXED_TEXTS:
        message = fixed_message(ending)
        assert (message.role, message.kind) == (ChatRole.CHAT, ChatMessageKind.FIXED)
        assert message.text == FIXED_TEXTS[ending]
        assert message.offered == ()
    with pytest.raises(ValueError, match="no fixed text"):
        fixed_message(TurnEnding.REPLIED)


def test_no_fixed_text_holds_a_numeral() -> None:
    """The chat's replies hold no number, and a text written in advance is
    not an exception to what the player reads."""
    assert not any(character.isdigit() for text in FIXED_TEXTS.values() for character in text)


@pytest.mark.parametrize(
    "understanding",
    [
        Understanding(UnderstandOutcome.UNAVAILABLE, None),
        Understanding(UnderstandOutcome.UNREADABLE, None),
        _read(RequestIntent.OUT_OF_SCOPE),
    ],
)
def test_the_turn_sends_the_understand_steps_own_fixed_text(understanding: Understanding) -> None:
    """Two functions decide these three endings, the understand step's and
    the turn's, and they may not come apart."""
    ending = plan_turn(understanding)
    assert isinstance(ending, TurnEnding)
    assert FIXED_TEXTS[ending] == fixed_reply(understanding)


def test_a_reading_the_understand_step_lets_go_on_has_no_fixed_text_there() -> None:
    assert fixed_reply(_read(RequestIntent.RECOMMEND)) is None
    assert fixed_reply(_read(RequestIntent.ABOUT_NUMBERS)) is None


@pytest.mark.parametrize(
    ("outcome", "ending"),
    [
        (PickOutcome.UNAVAILABLE, TurnEnding.UNAVAILABLE),
        (PickOutcome.UNREADABLE, TurnEnding.NO_ANSWER),
    ],
)
def test_a_pick_with_no_decision_ends_the_turn(outcome: PickOutcome, ending: TurnEnding) -> None:
    assert ending_without_decision(outcome) is ending


@pytest.mark.parametrize(
    ("outcome", "ending"),
    [
        (AnswerOutcome.UNAVAILABLE, TurnEnding.UNAVAILABLE),
        (AnswerOutcome.UNREADABLE, TurnEnding.NO_ANSWER),
        (AnswerOutcome.WITHHELD, TurnEnding.NO_ANSWER),
    ],
)
def test_an_answer_with_no_reply_ends_the_turn_on_a_fixed_text(
    outcome: AnswerOutcome, ending: TurnEnding
) -> None:
    assert ending_of_answer(Answer(outcome, None)) is ending


@pytest.mark.parametrize(
    "outcome", [AnswerOutcome.ANSWERED, AnswerOutcome.RETRIED, AnswerOutcome.SALVAGED]
)
def test_an_answer_that_holds_a_reply_is_the_turns_reply(outcome: AnswerOutcome) -> None:
    reply = Reply(ChatMessageKind.ANSWER, (ReplyStatement("One game fits."),))
    assert ending_of_answer(Answer(outcome, reply)) is TurnEnding.REPLIED


def test_a_reply_becomes_a_message_by_its_statements_in_order() -> None:
    reply = Reply(
        ChatMessageKind.ANSWER,
        (
            ReplyStatement("Two of these are close."),
            ReplyStatement("The first is slow and quiet.", game=620, offers=True),
            ReplyStatement("A third has timed dialogue.", game=730),
            ReplyStatement("The second is shorter.", game=400, offers=True),
        ),
    )
    message = reply_message(reply)
    assert message.text == (
        "Two of these are close. The first is slow and quiet. A third has timed dialogue."
        " The second is shorter."
    )
    assert message.offered == (620, 400)
    assert (message.role, message.kind) == (ChatRole.CHAT, ChatMessageKind.ANSWER)


def test_a_reply_that_only_asks_is_a_question_message() -> None:
    reply = Reply(ChatMessageKind.QUESTION, (ReplyStatement("What kind of game are you after?"),))
    message = reply_message(reply)
    assert (message.kind, message.offered) == (ChatMessageKind.QUESTION, ())


def _replied(reply: Reply, basis: AnswerBasis) -> Turn:
    """A turn that ended on ``reply``, written from ``basis``."""
    return Turn(
        reply_message(reply), TurnEnding.REPLIED, "seed",
        _read(RequestIntent.RECOMMEND), basis=basis,
        answer=Answer(AnswerOutcome.ANSWERED, reply),
    )


_NO_CANDIDATES_READ = CandidatesMaterial(games=())
_ONE_GAME = OneGameMaterial(
    app_id=_HADES, title="Hades", description="", release_year=None, subjects=()
)


def test_a_reply_links_the_games_it_offers_apart_from_the_games_it_only_speaks_of() -> None:
    """The prompt tells the model the page links every game a reply offers
    or is about. A game set aside is linked too, and on its own list, so it
    is not read as a suggestion. Each game is linked once, in the order the
    reply first reaches it."""
    reply = Reply(
        ChatMessageKind.ANSWER,
        (
            ReplyStatement("Two of these are close."),
            ReplyStatement("A third has timed dialogue.", game=730),
            ReplyStatement("The first is slow and quiet.", game=620, offers=True),
            ReplyStatement("It is unlike the one you named.", game=400),
            ReplyStatement("The second is shorter.", game=440, offers=True),
            ReplyStatement("That timer is strict.", game=730),
            ReplyStatement("Its music is praised too.", game=620, offers=True),
        ),
    )
    assert turn_links(_replied(reply, _NO_CANDIDATES_READ)) == TurnLinks(
        offered=(620, 440), about=(730, 400)
    )


def test_a_turn_about_one_game_links_that_game_whatever_the_statements_name() -> None:
    """The whole reply is about the game, so its report is linked even when
    no statement carries it, and once when several do."""
    unnamed = Reply(ChatMessageKind.ANSWER, (ReplyStatement("Reviewers call it hard."),))
    named = Reply(
        ChatMessageKind.ANSWER,
        (
            ReplyStatement("Reviewers call it hard.", game=_HADES),
            ReplyStatement("Unlike the one you played.", game=400),
        ),
    )
    assert turn_links(_replied(unnamed, _ONE_GAME)) == TurnLinks(about=(_HADES,))
    assert turn_links(_replied(named, _ONE_GAME)) == TurnLinks(about=(_HADES, 400))


def test_a_reply_that_found_nothing_carries_the_link_for_adding_a_game() -> None:
    """Promised by the prompt under a "nothing fits" reply. An answer that
    read candidates and offered none can say the same thing to the player
    (the first end-to-end run's third example did), so it carries the link
    as well, beside the reports of the games it set aside."""
    nothing_fits = Reply(ChatMessageKind.ANSWER, (ReplyStatement("The library has no such game."),))
    none_offered = Reply(
        ChatMessageKind.ANSWER, (ReplyStatement("This one is not about curling.", game=730),)
    )
    assert turn_links(_replied(nothing_fits, NothingFitsMaterial(wants=(), unmet=()))) == (
        TurnLinks(add_game=True)
    )
    assert turn_links(_replied(none_offered, _NO_CANDIDATES_READ)) == TurnLinks(
        about=(730,), add_game=True
    )


def test_a_reply_that_offers_or_only_asks_carries_no_link_for_adding_a_game() -> None:
    """A question has looked for nothing yet, whether the pick decided to
    ask or the answer call asked after reading candidates."""
    offers = Reply(ChatMessageKind.ANSWER, (ReplyStatement("Try this.", game=620, offers=True),))
    asks = Reply(ChatMessageKind.QUESTION, (ReplyStatement("What kind of game are you after?"),))
    assert not turn_links(_replied(offers, _NO_CANDIDATES_READ)).add_game
    assert turn_links(_replied(asks, AskDecision(needs=("the kind of game",)))) == TurnLinks()
    assert turn_links(_replied(asks, _NO_CANDIDATES_READ)) == TurnLinks()
    assert not turn_links(_replied(asks, _ONE_GAME)).add_game


@pytest.mark.parametrize("ending", list(FIXED_TEXTS))
def test_a_fixed_text_links_no_report_and_only_the_unmeasured_game_can_be_added(
    ending: TurnEnding,
) -> None:
    turn = Turn(fixed_message(ending), ending, "seed", _read(RequestIntent.ABOUT_GAME))
    assert turn_links(turn) == TurnLinks(add_game=ending is TurnEnding.GAME_NOT_MEASURED)
