"""One chat turn end to end — a real store, the real client, a scripted model.

Two games are seeded in a store file, each with a published report, its
sample and labels. The model's answers are scripted in the order the turn
asks: the understand step's, the pick's, the answer's.

The claims: a recommendation runs every step once and its reply becomes
the message, with the games it offered and its kind; the pick reads the
sheet under the caller's seed; a pick that asks and a pick that finds
nothing each reach the answer step with what that decision calls for; a
turn about one game makes no pick and reads the game the player asked
about; a step that ends with no result ends the turn on a fixed text, with
the record of every step that ran and no call after it; a reading the
first stage has no reply for ends on its stand-in after the one call; the
games already offered are left off the sheet when the player asks for
others; and a conversation that offered a game the library does not hold
is refused.

The reports are seeded with a direct insert, as the fetch's tests do, since
a turn uses only a report's identity, versions and aggregate rows.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fakes import AnswerScript, CollectingSink

from steamlens.chat.turn import TURN_STAGE, chat_routes, turn
from steamlens.contracts import (
    AnswerOutcome,
    AskDecision,
    AspectDef,
    AspectMention,
    AspectOntology,
    AspectSlot,
    CandidatesMaterial,
    ChatMessage,
    ChatMessageKind,
    ChatRole,
    ClassifierVersions,
    MetricEvent,
    NothingFitsMaterial,
    OneGameMaterial,
    Origin,
    PickOutcome,
    Provenance,
    Review,
    ReviewClassification,
    Sentiment,
    Turn,
    TurnEnding,
    UnderstandOutcome,
)
from steamlens.core.conversation import OfferedGameNotInLibrary
from steamlens.core.pick import build_pick_prompt, shuffled_order
from steamlens.core.turn import FIXED_TEXTS
from steamlens.dispatch.census_arm import MODEL_ID, PROVIDER
from steamlens.llm_client import (
    InMemoryResponseArchive,
    InMemorySpendLedger,
    LlmClient,
    LlmClientConfig,
    ModelSpec,
)
from steamlens.store import Store, utc_isoformat

_NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
_VERSIONS = ClassifierVersions(model_version="labeler-b", prompt_version="p", ontology_version="v2")
_FIRST, _SECOND = 7001, 7002
_ONTOLOGY = AspectOntology(
    version="test",
    aspects=(AspectDef("story", "The plot and how it is told.", (), "narrative", "", "", ()),),
    global_rules=(),
)

# A review: its id, its text, and the evidence span of its positive story mention.
type Seeded = tuple[str, str, str]

_FIRST_REVIEWS: tuple[Seeded, ...] = (
    ("a1", "The story is superb.", "story is superb"),
    ("a2", "great story, though the late game is a grind", "great story"),
    ("a3", "loved the story", "loved the story"),
    ("a4", "the story kept me up all night", "story kept me up"),
    ("a5", "a story worth the price", "story worth the price"),
)
_SECOND_REVIEWS: tuple[Seeded, ...] = (
    ("b1", "a story I will remember", "story I will remember"),
    ("b2", "the story carries it", "story carries it"),
    ("b3", "what a story", "what a story"),
    ("b4", "came for the story and stayed", "came for the story"),
    ("b5", "the story is the reason to play", "story is the reason"),
)


def _seed_game(path: Path, app_id: int, name: str, reviews: Sequence[Seeded]) -> None:
    """One published report for ``app_id`` whose sample holds ``reviews``."""
    run_id = f"serve-{app_id}"
    conn = sqlite3.connect(path)
    with conn:
        conn.execute(
            "INSERT INTO runs (run_id, code_version, created_at, config_hash)"
            " VALUES (?, 'abc1234', ?, 'cfg')",
            (run_id, utc_isoformat(_NOW)),
        )
        conn.execute(
            "INSERT INTO reports (run_id, app_id, game_name, created_at, model_version,"
            " prompt_version, ontology_version, sample_size, take_all, windowed_windows,"
            " fallback_windows, skipped_windows, narrative_outcome, narrative_json,"
            " histogram_json, episodes_json, language_mix_json, marked_windows_json,"
            " fetch_windows_json) VALUES (?, ?, ?, ?, 'labeler-b', 'p', 'v2', ?, 1, 1, 0,"
            " 0, 'withheld', '{}', '{}', '[]', '[]', '[]', '[]')",
            (run_id, app_id, name, utc_isoformat(_NOW), len(reviews)),
        )
        conn.execute(
            "INSERT INTO aggregate_snapshots (run_id, aspect, slot, reviews_with_aspect,"
            " positive, negative, mixed, neutral, sample_size)"
            " VALUES (?, 'story', 'pinned', ?, ?, 0, 0, 0, ?)",
            (run_id, len(reviews), len(reviews), len(reviews)),
        )
    conn.close()
    stamp = Provenance(run_id=run_id, code_version="abc1234", created_at=_NOW, config_hash="cfg")
    with Store(path) as store:
        store.reviews.put_many(
            Review(review_id, app_id, _NOW, "english", text, True) for review_id, text, _ in reviews
        )
        store.sample_members.add_members(run_id, [review_id for review_id, _, _ in reviews])
        for review_id, _, span in reviews:
            store.labels.put(
                ReviewClassification(
                    review_id=review_id, origin=Origin.SURVEY, versions=_VERSIONS, run=stamp,
                    mentions=(AspectMention("story", AspectSlot.PINNED, Sentiment.POSITIVE, span),),
                )
            )


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    path = tmp_path / "steamlens.sqlite3"
    with Store(path):
        pass
    _seed_game(path, _FIRST, "The First Game", _FIRST_REVIEWS)
    _seed_game(path, _SECOND, "The Second Game", _SECOND_REVIEWS)
    return path


_ASKED = (ChatMessage(ChatRole.PLAYER, "something with a good story"),)
_STORY = {"words": "a good story", "firmness": "want", "stance": "wants",
          "target": {"kind": "aspect", "aspect": "story"}}

_WANTS_GAMES = json.dumps({"intent": "recommend", "wants": [_STORY]})
_WANTS_OTHER_GAMES = json.dumps({"intent": "recommend", "wants": [_STORY], "other_games": True})
_OUT_OF_SCOPE = json.dumps({"intent": "out-of-scope"})
_BROKEN = "Here is what I think."


def _question_about(title: str) -> tuple[ChatMessage, ...]:
    """A conversation whose one message asks whether the game called ``title`` is grindy."""
    return (ChatMessage(ChatRole.PLAYER, f"{title.lower()}: is it grindy?"),)


def _asks_about(title: str) -> str:
    """The understand step's reading of ``_question_about(title)``, in the player's words."""
    return json.dumps({
        "intent": "about-game",
        "named_games": [{
            "words": title.lower(), "title": title, "role": "ask-about", "feeling": "unknown",
            "liked_parts": [],
        }],
        "subjects": [
            {"words": "is it grindy", "target": {"kind": "term", "phrases": ["grind", "grindy"]}}
        ],
    })


_PICKS_FIRST = json.dumps({"outcome": "candidates", "candidates": [{"game": "g1", "read": ["w1"]}]})
_PICK_ASKS = json.dumps({"outcome": "ask", "needs": ["what kind of game"]})
_PICK_FINDS_NOTHING = json.dumps({"outcome": "nothing-fits", "unmet": ["w1"]})


def _statement(text: str, **fields: object) -> dict[str, object]:
    return {"game": None, "offers": False, "wants": [], "cites": [], "text": text, **fields}


_OFFERS_FIRST = json.dumps({"statements": [
    _statement("One game here stands out for its story."),
    _statement(
        "Players who talk about the story of The First Game mostly praise it.",
        game="g1", offers=True, wants=["w1"], cites=["e1"],
    ),
]})
_QUESTION = json.dumps({"statements": [_statement("What kind of game are you after?")]})
_NOTHING = json.dumps({"statements": [
    _statement("The library holds nothing with a story like that.", wants=["w1"]),
]})
_ABOUT_FIRST = json.dumps({"kind": "answer", "statements": [
    _statement("One reviewer of The First Game says the late game drags.", game="g1", cites=["e1"]),
]})


def _run(
    store_path: Path,
    script: AnswerScript,
    conversation: Sequence[ChatMessage] = _ASKED,
    *,
    seed: str = "conversation-1",
) -> tuple[Turn, dict[str, float]]:
    """One turn over the seeded store; the turn's own metrics by name."""
    config = LlmClientConfig(
        routes=chat_routes(),
        models={
            MODEL_ID: ModelSpec(rpm=6_000, rpd=None, input_usd_per_1m=1.0, output_usd_per_1m=2.0)
        },
        budget_usd=None,
    )
    client = LlmClient(
        config,
        InMemoryResponseArchive(),
        InMemorySpendLedger(),
        CollectingSink(),
        registry={PROVIDER: script.entry()},
        sleep=lambda _: None,
    )
    sink = CollectingSink()
    with Store(store_path) as store:
        result = turn(client, store, conversation, _ONTOLOGY, sink, seed=seed, year=2026)
    metrics = {
        event.name: event.value
        for event in sink.events
        if isinstance(event, MetricEvent) and event.stage == TURN_STAGE
    }
    return result, metrics


def test_a_recommendation_runs_every_step_and_its_reply_becomes_the_message(
    store_path: Path,
) -> None:
    script = AnswerScript([_WANTS_GAMES, _PICKS_FIRST, _OFFERS_FIRST])
    result, metrics = _run(store_path, script)

    assert len(script.prompts) == 3
    assert result.ending is TurnEnding.REPLIED
    assert result.message == ChatMessage(
        ChatRole.CHAT,
        "One game here stands out for its story. Players who talk about the story of"
        " The First Game mostly praise it.",
        offered=(_FIRST,),
        kind=ChatMessageKind.ANSWER,
    )
    assert result.understanding.outcome is UnderstandOutcome.UNDERSTOOD
    assert result.sheet is not None
    assert {row.game.app_id for row in result.sheet.rows} == {_FIRST, _SECOND}
    assert result.pick is not None and result.pick.outcome is PickOutcome.DECIDED
    assert isinstance(result.basis, CandidatesMaterial)
    assert [game.app_id for game in result.basis.games] == [_FIRST]
    assert result.answer is not None and result.answer.outcome is AnswerOutcome.ANSWERED
    assert metrics == {"turn_replied": 1.0}


def test_the_pick_reads_the_sheet_under_the_callers_seed(store_path: Path) -> None:
    """The seed is the caller's and is kept on the record, so the pick's
    prompt can be made again from the request, the sheet and the seed."""
    script = AnswerScript([_WANTS_GAMES, _PICKS_FIRST, _OFFERS_FIRST])
    result, _ = _run(store_path, script, seed="conversation-9")

    assert result.seed == "conversation-9"
    assert result.understanding.request is not None and result.sheet is not None
    assert script.prompts[1] == build_pick_prompt(
        result.understanding.request, result.sheet, inner_order=shuffled_order("conversation-9")
    )


def test_a_pick_that_asks_reaches_the_answer_step_as_it_is(store_path: Path) -> None:
    script = AnswerScript([_WANTS_GAMES, _PICK_ASKS, _QUESTION])
    result, _ = _run(store_path, script)

    assert result.basis == AskDecision(("what kind of game",))
    assert result.ending is TurnEnding.REPLIED
    assert result.message.text == "What kind of game are you after?"
    assert (result.message.kind, result.message.offered) == (ChatMessageKind.QUESTION, ())


def test_a_pick_that_finds_nothing_hands_over_how_the_library_stands(store_path: Path) -> None:
    script = AnswerScript([_WANTS_GAMES, _PICK_FINDS_NOTHING, _NOTHING])
    result, _ = _run(store_path, script)

    assert isinstance(result.basis, NothingFitsMaterial)
    assert result.basis.unmet == (0,)
    assert result.ending is TurnEnding.REPLIED
    assert (result.message.kind, result.message.offered) == (ChatMessageKind.ANSWER, ())


def test_a_turn_about_one_game_makes_no_pick_and_reads_the_game_asked_about(
    store_path: Path,
) -> None:
    script = AnswerScript([_asks_about("The First Game"), _ABOUT_FIRST])
    result, metrics = _run(store_path, script, _question_about("The First Game"))

    assert len(script.prompts) == 2
    assert (result.sheet, result.pick) == (None, None)
    assert isinstance(result.basis, OneGameMaterial)
    assert result.basis.app_id == _FIRST
    (subject,) = result.basis.subjects
    assert [cited.excerpt.review_id for cited in subject.excerpts] == ["a2"]
    assert result.ending is TurnEnding.REPLIED
    assert result.message.text == "One reviewer of The First Game says the late game drags."
    assert (result.message.kind, result.message.offered) == (ChatMessageKind.ANSWER, ())
    assert metrics == {"turn_replied": 1.0}


def test_a_pick_with_no_decision_ends_the_turn_before_the_answer(store_path: Path) -> None:
    """The pick's one retry is spent and nothing can be read, so no review
    is fetched and no answer is asked for."""
    script = AnswerScript([_WANTS_GAMES, _BROKEN, _BROKEN])
    result, metrics = _run(store_path, script)

    assert len(script.prompts) == 3
    assert result.ending is TurnEnding.NO_ANSWER
    assert result.message == ChatMessage(
        ChatRole.CHAT, FIXED_TEXTS[TurnEnding.NO_ANSWER], kind=ChatMessageKind.FIXED
    )
    assert result.pick is not None and result.pick.outcome is PickOutcome.UNREADABLE
    assert result.sheet is not None
    assert (result.basis, result.answer) == (None, None)
    assert metrics == {"turn_no_answer": 1.0}


def test_an_answer_with_no_reply_ends_the_turn_with_every_steps_record_kept(
    store_path: Path,
) -> None:
    script = AnswerScript([_WANTS_GAMES, _PICKS_FIRST, _BROKEN, _BROKEN])
    result, _ = _run(store_path, script)

    assert result.ending is TurnEnding.NO_ANSWER
    assert result.message.kind is ChatMessageKind.FIXED
    assert result.answer is not None and result.answer.outcome is AnswerOutcome.UNREADABLE
    assert isinstance(result.basis, CandidatesMaterial)
    assert result.pick is not None and result.pick.decision is not None


@pytest.mark.parametrize(
    ("down", "steps_reached"),
    [(0, (False, False)), (1, (True, False)), (2, (True, True))],
)
def test_a_step_that_cannot_be_served_ends_the_turn_as_unavailable(
    store_path: Path, down: int, steps_reached: tuple[bool, bool]
) -> None:
    """Whichever of the three calls fails, the player reads the same text;
    the record says how far the turn got."""
    script = AnswerScript(
        [_WANTS_GAMES, _PICKS_FIRST, _OFFERS_FIRST], down=frozenset({down})
    )
    result, metrics = _run(store_path, script)

    assert result.ending is TurnEnding.UNAVAILABLE
    assert result.message.text == FIXED_TEXTS[TurnEnding.UNAVAILABLE]
    assert (result.pick is not None, result.answer is not None) == steps_reached
    assert metrics == {"turn_unavailable": 1.0}


def test_a_request_out_of_scope_ends_the_turn_after_the_one_call(store_path: Path) -> None:
    script = AnswerScript([_OUT_OF_SCOPE])
    result, metrics = _run(store_path, script)

    assert len(script.prompts) == 1
    assert result.ending is TurnEnding.OUT_OF_SCOPE
    assert result.message.text == FIXED_TEXTS[TurnEnding.OUT_OF_SCOPE]
    assert (result.sheet, result.pick, result.basis, result.answer) == (None, None, None, None)
    assert metrics == {"turn_out_of_scope": 1.0}


def test_a_turn_about_a_game_the_library_does_not_hold_ends_on_its_stand_in(
    store_path: Path,
) -> None:
    script = AnswerScript([_asks_about("Some Other Game")])
    result, metrics = _run(store_path, script, _question_about("Some Other Game"))

    assert len(script.prompts) == 1
    assert result.ending is TurnEnding.GAME_NOT_MEASURED
    assert result.message == ChatMessage(
        ChatRole.CHAT, FIXED_TEXTS[TurnEnding.GAME_NOT_MEASURED], kind=ChatMessageKind.FIXED
    )
    assert metrics == {"turn_game_not_measured": 1.0}


def test_a_turn_about_one_game_that_marks_no_game_is_counted_as_that_reading(
    store_path: Path,
) -> None:
    """The parse lets the reading through. The turn asks for the title and
    counts the reading, with the question that had nothing asked in it."""
    script = AnswerScript([json.dumps({"intent": "about-game"})])
    result, metrics = _run(store_path, script)

    assert result.ending is TurnEnding.GAME_UNCLEAR
    assert metrics == {
        "turn_no_game_asked_about": 1.0, "turn_nothing_asked": 1.0, "turn_game_unclear": 1.0,
    }


def test_a_message_about_two_library_games_ends_on_asking_which_with_no_further_call(
    store_path: Path,
) -> None:
    """Both games resolve, and the turn still answers about neither: one
    model call, the fixed text, and the reading counted."""
    asked: list[dict[str, object]] = [
        {"words": title.lower(), "title": title, "role": "ask-about", "feeling": "unknown",
         "liked_parts": []}
        for title in ("The First Game", "The Second Game")
    ]
    script = AnswerScript([json.dumps({"intent": "about-game", "named_games": asked})])
    conversation = (ChatMessage(ChatRole.PLAYER, "the first game and the second game: cons?"),)
    result, metrics = _run(store_path, script, conversation)

    assert len(script.prompts) == 1
    assert result.ending is TurnEnding.SEVERAL_GAMES
    assert result.message == ChatMessage(
        ChatRole.CHAT, FIXED_TEXTS[TurnEnding.SEVERAL_GAMES], kind=ChatMessageKind.FIXED
    )
    assert metrics == {
        "turn_more_games_asked_about": 1.0, "turn_nothing_asked": 1.0, "turn_several_games": 1.0,
    }


def test_games_already_offered_are_left_off_when_the_player_asks_for_others(
    store_path: Path,
) -> None:
    """The sheet the pick reads holds the second game only, so the pick's
    first identifier is that game and the reply can offer nothing shown
    before."""
    conversation = (
        *_ASKED,
        ChatMessage(
            ChatRole.CHAT, "The First Game is praised for its story.",
            offered=(_FIRST,), kind=ChatMessageKind.ANSWER,
        ),
        ChatMessage(ChatRole.PLAYER, "anything else?"),
    )
    offers_second = json.dumps({"statements": [
        _statement(
            "Players who talk about the story of The Second Game mostly praise it.",
            game="g1", offers=True, wants=["w1"], cites=["e1"],
        ),
    ]})
    script = AnswerScript([_WANTS_OTHER_GAMES, _PICKS_FIRST, offers_second])
    result, _ = _run(store_path, script, conversation)

    assert result.sheet is not None
    assert result.sheet.earlier_offers == (_FIRST,)
    assert [row.game.app_id for row in result.sheet.rows] == [_SECOND]
    assert result.message.offered == (_SECOND,)


def test_a_conversation_that_offered_a_game_outside_the_library_is_refused(
    store_path: Path,
) -> None:
    """The chat offers library games only, so this conversation is not one
    it wrote. The turn says so loudly and answers nothing. The error has a
    type of its own and names the games, so a caller can end the
    conversation on this case without taking a step's bug for it."""
    conversation = (
        ChatMessage(ChatRole.CHAT, "Try this one.", offered=(999,), kind=ChatMessageKind.ANSWER),
        ChatMessage(ChatRole.PLAYER, "tell me more"),
    )
    script = AnswerScript([_WANTS_GAMES])
    with pytest.raises(OfferedGameNotInLibrary, match="the library does not hold") as caught:
        _run(store_path, script, conversation)
    assert caught.value.app_ids == (999,)
    assert isinstance(caught.value, ValueError)
    assert script.prompts == []
