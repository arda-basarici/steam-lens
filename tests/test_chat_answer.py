"""The answer shell's ladder — every rung, driven through the real client.

The claims: a valid answer is used after one call; a faulty answer gets
exactly one corrective retry that names its faults; a fault that survives
the retry costs the reply the faulty statement and never the rest; a retry
that fails falls back to what the first answer could give; an answer with no
statement left after the retry, a cut-off generation, the spend cap and
provider trouble each end the turn with an outcome and never with an
exception; and a reply that offers more games than a reply may is cut and
counted without a retry.

The check rides the same round. Its objection is named in the one retry
beside the parse's faults, and ends as corrected when the retry's answer no
longer draws it, as withdrawn when the retry takes the offer back, and as
removed when it still stands and code takes the statement. A reply the
check leaves nothing of is withheld, which is its own outcome. A rule that
costs nothing is recorded and asks for no retry, and is named in one that
runs for another reason. A reply that offers none of its candidates and an
offer with no review cited are counted.
Calls flow through the real ``LlmClient`` over a scripted provider, so the
route and archive-key mechanics are the production ones.
"""

from __future__ import annotations

import json

from fakes import AnswerScript, CollectingSink

from steamlens.chat.answer import ANSWER_STAGE, answer, answer_route
from steamlens.contracts import (
    Answer,
    AnswerOutcome,
    AspectTarget,
    CandidatesMaterial,
    ChatMessage,
    ChatMessageKind,
    ChatRole,
    CheckRule,
    CitedExcerpt,
    Excerpt,
    FinishReason,
    Firmness,
    GameMaterial,
    LlmStage,
    MetricEvent,
    MustStanding,
    ObjectionRung,
    PlayerRequest,
    ReadState,
    Reply,
    ReplyStatement,
    RequestIntent,
    SentimentGroup,
    Stance,
    Want,
    WantFinding,
    WantMaterial,
    WantStatus,
)
from steamlens.dispatch.census_arm import MODEL_ID, PROVIDER
from steamlens.llm_client import (
    InMemoryResponseArchive,
    InMemorySpendLedger,
    LlmClient,
    LlmClientConfig,
    ModelSpec,
)


def _candidate(number: int) -> GameMaterial:
    story = WantMaterial(
        WantStatus.MATCHES, WantFinding.ASPECT_GROUP, ReadState.READ,
        group=SentimentGroup.STRONGLY_POSITIVE,
        excerpts=(
            CitedExcerpt(f"e{number}", Excerpt(7000 + number, f"r{number}", "a fine story")),
        ),
    )
    return GameMaterial(7000 + number, f"Title {number}", "", MustStanding.MEETS, (story,))


_MATERIAL = CandidatesMaterial(tuple(_candidate(number) for number in range(1, 6)))
_TITLES = {game.app_id: game.title for game in _MATERIAL.games}
_REQUEST = PlayerRequest(
    intent=RequestIntent.RECOMMEND,
    wants=(Want("a good story", Firmness.WANT, Stance.WANTS, AspectTarget("story")),),
)
_CONVERSATION = (ChatMessage(ChatRole.PLAYER, "something with a good story"),)


def _text(game: str) -> str:
    return f"Players who talk about the story of Title {game[1:]} mostly praise it."


def _offer(game: str, cite: str, text: str | None = None) -> dict[str, object]:
    return {
        "game": game, "offers": True, "wants": ["w1"], "cites": [cite],
        "text": text or _text(game),
    }


def _reply(*statements: dict[str, object]) -> str:
    return json.dumps({"statements": list(statements)})


_CLEAN = _reply(_offer("g2", "e2"), _offer("g1", "e1"))
_FAULTY = _reply(_offer("g2", "e2"), _offer("g99", "e1"))
_NOTHING_LEFT = _reply(_offer("g99", "e1"))
_BROKEN = "I would suggest the second game."
_KEPT = Reply(
    ChatMessageKind.ANSWER,
    (ReplyStatement(_text("g2"), game=7002, offers=True, wants=(0,), cites=("e2",)),),
)
# A count of reviews, which no reply may hold; and a reviewer's wording
# relayed, which is recorded and costs nothing.
_COUNTED = _reply(
    _offer("g2", "e2", "Title 2 has 40 reviews that praise its story."), _offer("g1", "e1")
)
_RELAYED = _reply(_offer("g2", "e2", "Players keep calling the story of Title 2 moving."))


def _run(script: AnswerScript, *, budget_usd: float | None = None) -> tuple[Answer, CollectingSink]:
    config = LlmClientConfig(
        routes={LlmStage.ANSWER: answer_route()},
        models={
            MODEL_ID: ModelSpec(rpm=6_000, rpd=None, input_usd_per_1m=1.0, output_usd_per_1m=2.0)
        },
        budget_usd=budget_usd,
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
    return answer(client, _CONVERSATION, _REQUEST, _MATERIAL, _TITLES, sink), sink


def _metrics(sink: CollectingSink) -> dict[str, float]:
    return {
        event.name: event.value
        for event in sink.events
        if isinstance(event, MetricEvent) and event.stage == ANSWER_STAGE
    }


def test_a_valid_answer_is_used_after_one_call() -> None:
    script = AnswerScript([_CLEAN])
    answered, sink = _run(script)
    assert answered.outcome is AnswerOutcome.ANSWERED
    assert answered.reply is not None
    assert answered.reply.offered == (7002, 7001)
    assert len(script.prompts) == 1
    assert _metrics(sink) == {}


def test_a_faulty_answer_gets_one_corrective_retry_naming_its_faults() -> None:
    script = AnswerScript([_FAULTY, _CLEAN])
    answered, sink = _run(script)
    assert answered.outcome is AnswerOutcome.RETRIED
    assert answered.faults == ()
    assert len(script.prompts) == 2
    assert script.prompts[1].startswith(script.prompts[0])
    assert 'statement 2 has "game": "g99"' in script.prompts[1]
    assert _metrics(sink) == {"answer_faults": 1.0}


def test_a_fault_still_standing_after_the_retry_costs_the_faulty_statement_only() -> None:
    script = AnswerScript([_FAULTY, _FAULTY])
    answered, sink = _run(script)
    assert answered.outcome is AnswerOutcome.SALVAGED
    assert answered.reply == _KEPT
    assert len(answered.faults) == 1
    assert len(script.prompts) == 2
    assert _metrics(sink)["answer_salvaged"] == 1.0


def test_a_retry_that_reads_worse_falls_back_to_the_first_answer() -> None:
    """The retry can lose the structure, lose every statement, be cut off,
    or meet provider trouble. What the first answer could give is still the
    better turn."""
    for second in (
        AnswerScript([_FAULTY, _BROKEN]),
        AnswerScript([_FAULTY, _NOTHING_LEFT]),
        AnswerScript([_FAULTY, _CLEAN], finishes={1: FinishReason.LENGTH}),
        AnswerScript([_FAULTY, _CLEAN], down=frozenset({1})),
    ):
        answered, _ = _run(second)
        assert answered.outcome is AnswerOutcome.SALVAGED
        assert answered.reply == _KEPT


def test_an_answer_with_no_reply_after_the_retry_ends_the_turn() -> None:
    for script in (AnswerScript([_BROKEN, "[]"]), AnswerScript([_NOTHING_LEFT, _BROKEN])):
        answered, sink = _run(script)
        assert answered.outcome is AnswerOutcome.UNREADABLE
        assert answered.reply is None
        assert answered.faults
        assert len(script.prompts) == 2
        assert _metrics(sink)["answer_unreadable"] == 1.0


def test_a_cut_off_generation_is_not_retried() -> None:
    """At temperature 0 the same call would be cut off the same way."""
    script = AnswerScript([_CLEAN], finishes={0: FinishReason.LENGTH})
    answered, _ = _run(script)
    assert answered.outcome is AnswerOutcome.UNREADABLE
    assert len(script.prompts) == 1


def test_the_spend_cap_and_provider_trouble_end_the_turn_as_unavailable() -> None:
    capped, _ = _run(AnswerScript([_CLEAN]), budget_usd=0.0000001)
    down, sink = _run(AnswerScript([_CLEAN], down=frozenset({0})))
    for answered in (capped, down):
        assert answered.outcome is AnswerOutcome.UNAVAILABLE
        assert answered.reply is None
    assert _metrics(sink)["answer_unavailable"] == 1.0


def test_a_reply_that_offers_too_many_games_is_cut_and_counted_without_a_retry() -> None:
    script = AnswerScript(
        [_reply(*(_offer(f"g{number}", f"e{number}") for number in (5, 4, 3, 2, 1)))]
    )
    answered, sink = _run(script)
    assert answered.outcome is AnswerOutcome.ANSWERED
    assert answered.reply is not None
    assert answered.reply.offered == (7005, 7004, 7003)
    assert len(script.prompts) == 1
    assert _metrics(sink) == {"answer_cut": 2.0}


def _endings(answered: Answer) -> list[tuple[CheckRule, ObjectionRung]]:
    return [(settled.objection.rule, settled.rung) for settled in answered.objections]


def test_an_objection_of_the_check_is_named_in_the_one_retry_and_ends_as_corrected() -> None:
    script = AnswerScript([_COUNTED, _CLEAN])
    answered, sink = _run(script)
    assert answered.outcome is AnswerOutcome.RETRIED
    assert answered.faults == ()
    assert len(script.prompts) == 2
    assert 'statement 1 holds the numeral "40"' in script.prompts[1]
    assert _endings(answered) == [(CheckRule.NUMERAL, ObjectionRung.CORRECTED)]
    assert _metrics(sink) == {"answer_faults": 1.0, "check_numeral_corrected": 1.0}


def test_an_objection_still_standing_after_the_retry_costs_its_statement() -> None:
    script = AnswerScript([_COUNTED, _COUNTED])
    answered, sink = _run(script)
    assert answered.outcome is AnswerOutcome.SALVAGED
    assert answered.reply is not None
    assert answered.reply.offered == (7001,)
    assert len(answered.faults) == 1
    assert _endings(answered) == [(CheckRule.NUMERAL, ObjectionRung.REMOVED)]
    assert _metrics(sink)["answer_salvaged"] == 1.0
    assert _metrics(sink)["check_numeral_removed"] == 1.0


def test_a_retry_that_takes_the_offer_back_ends_the_objection_as_withdrawn() -> None:
    script = AnswerScript([_COUNTED, _reply(_offer("g1", "e1"))])
    answered, _ = _run(script)
    assert answered.outcome is AnswerOutcome.RETRIED
    assert answered.reply is not None
    assert answered.reply.offered == (7001,)
    assert _endings(answered) == [(CheckRule.NUMERAL, ObjectionRung.WITHDRAWN)]


def test_a_reply_the_check_leaves_nothing_of_is_withheld() -> None:
    only = _reply(_offer("g2", "e2", "Title 2 has 40 reviews that praise its story."))
    script = AnswerScript([only, only])
    answered, sink = _run(script)
    assert answered.outcome is AnswerOutcome.WITHHELD
    assert answered.reply is None
    assert len(answered.faults) == 1
    assert _endings(answered) == [(CheckRule.NUMERAL, ObjectionRung.REMOVED)]
    assert len(script.prompts) == 2
    assert _metrics(sink)["answer_withheld"] == 1.0


def test_a_rule_that_costs_nothing_asks_for_no_retry_and_rides_one_that_runs() -> None:
    script = AnswerScript([_RELAYED])
    answered, sink = _run(script)
    assert answered.outcome is AnswerOutcome.ANSWERED
    assert len(script.prompts) == 1
    assert _endings(answered) == [(CheckRule.RELAYED_WORDING, ObjectionRung.STANDING)]
    assert _metrics(sink) == {"check_relayed_wording_standing": 1.0}

    both = _reply(_offer("g2", "e2", "Players keep calling Title 2 one of the 40 best."))
    script = AnswerScript([both, _CLEAN])
    answered, _ = _run(script)
    assert "relays reviewers' wording" in script.prompts[1]
    assert _endings(answered) == [
        (CheckRule.NUMERAL, ObjectionRung.CORRECTED),
        (CheckRule.RELAYED_WORDING, ObjectionRung.CORRECTED),
    ]


def test_a_reply_that_offers_no_candidate_and_an_offer_with_no_cite_are_counted() -> None:
    set_aside = _reply({
        "game": "g2", "offers": False, "wants": ["w1"], "cites": ["e2"],
        "text": "Title 2 has a praised story, though it is not the kind of game you asked for.",
    })
    answered, sink = _run(AnswerScript([set_aside]))
    assert answered.outcome is AnswerOutcome.ANSWERED
    assert _metrics(sink) == {"answer_no_offer": 1.0}

    uncited = _reply({**_offer("g2", "e2"), "cites": []})
    answered, sink = _run(AnswerScript([uncited]))
    assert answered.outcome is AnswerOutcome.ANSWERED
    assert _metrics(sink) == {"answer_uncited_offers": 1.0}
