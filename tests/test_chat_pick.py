"""The pick shell's ladder — every rung, driven through the real client.

The claims: a valid answer is used after one call; a faulty answer gets
exactly one corrective retry that names its faults; a fault that survives
the retry costs the decision the faulty candidate and never the rest; a
retry that fails falls back to what the first answer could give; an answer
with no decision in it after the retry, a cut-off generation, the spend cap
and provider trouble each end the turn with an outcome and never with an
exception; an answer over a cap is cut and counted without a retry; and the
seed sets the order of the games that read alike and nothing else.
Calls flow through the real ``LlmClient`` over a scripted provider, so the
route and archive-key mechanics are the production ones.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fakes import AnswerScript, CollectingSink

from steamlens.chat.pick import PICK_STAGE, pick, pick_route
from steamlens.contracts import (
    AspectTarget,
    CandidatesDecision,
    FinishReason,
    Firmness,
    LibraryGame,
    LlmStage,
    MetricEvent,
    Pick,
    PickCandidate,
    PickOutcome,
    PlayerRequest,
    RequestIntent,
    Stance,
    Want,
)
from steamlens.core.sheet import read_sheet
from steamlens.dispatch.census_arm import MODEL_ID, PROVIDER
from steamlens.llm_client import (
    InMemoryResponseArchive,
    InMemorySpendLedger,
    LlmClient,
    LlmClientConfig,
    ModelSpec,
)

_READ = datetime(2026, 11, 14, tzinfo=UTC)


def _game(app_id: int) -> LibraryGame:
    return LibraryGame(
        app_id=app_id, name=f"Game {app_id}", run_id=f"serve-{app_id}", reported_at=_READ,
        sample_size=600, complete_count=False, labeler="m", cells=(), storefront=None, tags=None,
    )


# Eight games, so an answer can name more than the six a decision holds.
_LIBRARY = tuple(_game(7001 + offset) for offset in range(8))
_REQUEST = PlayerRequest(
    intent=RequestIntent.RECOMMEND,
    wants=(Want("a good story", Firmness.WANT, Stance.WANTS, AspectTarget("story")),),
)
_SHEET = read_sheet(_REQUEST, _LIBRARY, {})


def _answer(*games: str) -> str:
    return json.dumps(
        {"outcome": "candidates", "candidates": [{"game": game, "read": ["w1"]} for game in games]}
    )


_CLEAN = _answer("g2", "g1")
_FAULTY = _answer("g2", "g99")
_NOTHING_LEFT = _answer("g99")
_BROKEN = "I would go with the second game."
_KEPT = CandidatesDecision((PickCandidate(7002, (0,)),))


def _run(
    script: AnswerScript, *, budget_usd: float | None = None, seed: str = "conversation-1"
) -> tuple[Pick, CollectingSink]:
    config = LlmClientConfig(
        routes={LlmStage.PICK: pick_route()},
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
    return pick(client, _REQUEST, _SHEET, sink, seed=seed), sink


def _metrics(sink: CollectingSink) -> dict[str, float]:
    return {
        event.name: event.value
        for event in sink.events
        if isinstance(event, MetricEvent) and event.stage == PICK_STAGE
    }


def test_a_valid_answer_is_used_after_one_call() -> None:
    script = AnswerScript([_CLEAN])
    picked, sink = _run(script)
    assert picked.outcome is PickOutcome.DECIDED
    assert picked.decision == CandidatesDecision(
        (PickCandidate(7002, (0,)), PickCandidate(7001, (0,)))
    )
    assert len(script.prompts) == 1
    assert _metrics(sink) == {}


def test_a_faulty_answer_gets_one_corrective_retry_naming_its_faults() -> None:
    script = AnswerScript([_FAULTY, _CLEAN])
    picked, sink = _run(script)
    assert picked.outcome is PickOutcome.RETRIED
    assert picked.faults == ()
    assert len(script.prompts) == 2
    assert script.prompts[1].startswith(script.prompts[0])
    assert 'names the game "g99", which is not an identifier on the sheet' in script.prompts[1]
    assert _metrics(sink) == {"pick_faults": 1.0}


def test_a_fault_still_standing_after_the_retry_costs_the_faulty_candidate_only() -> None:
    script = AnswerScript([_FAULTY, _FAULTY])
    picked, sink = _run(script)
    assert picked.outcome is PickOutcome.SALVAGED
    assert picked.decision == _KEPT
    assert len(picked.faults) == 1
    assert len(script.prompts) == 2
    assert _metrics(sink)["pick_salvaged"] == 1.0


def test_a_retry_that_reads_worse_falls_back_to_the_first_answer() -> None:
    """The retry can lose the structure, lose every candidate, be cut off,
    or meet provider trouble. What the first answer could give is still the
    better turn."""
    for second in (
        AnswerScript([_FAULTY, _BROKEN]),
        AnswerScript([_FAULTY, _NOTHING_LEFT]),
        AnswerScript([_FAULTY, _CLEAN], finishes={1: FinishReason.LENGTH}),
        AnswerScript([_FAULTY, _CLEAN], down=frozenset({1})),
    ):
        picked, _ = _run(second)
        assert picked.outcome is PickOutcome.SALVAGED
        assert picked.decision == _KEPT


def test_an_answer_with_no_decision_after_the_retry_ends_the_turn() -> None:
    for script in (AnswerScript([_BROKEN, "[]"]), AnswerScript([_NOTHING_LEFT, _BROKEN])):
        picked, sink = _run(script)
        assert picked.outcome is PickOutcome.UNREADABLE
        assert picked.decision is None
        assert picked.faults
        assert len(script.prompts) == 2
        assert _metrics(sink)["pick_unreadable"] == 1.0


def test_a_cut_off_generation_is_not_retried() -> None:
    """At temperature 0 the same call would be cut off the same way."""
    script = AnswerScript([_CLEAN], finishes={0: FinishReason.LENGTH})
    picked, _ = _run(script)
    assert picked.outcome is PickOutcome.UNREADABLE
    assert len(script.prompts) == 1


def test_the_spend_cap_and_provider_trouble_end_the_turn_as_unavailable() -> None:
    capped, _ = _run(AnswerScript([_CLEAN]), budget_usd=0.0000001)
    down, sink = _run(AnswerScript([_CLEAN], down=frozenset({0})))
    for picked in (capped, down):
        assert picked.outcome is PickOutcome.UNAVAILABLE
        assert picked.decision is None
    assert _metrics(sink)["pick_unavailable"] == 1.0


def test_an_answer_over_the_candidate_cap_is_cut_and_counted_without_a_retry() -> None:
    script = AnswerScript([_answer("g8", "g7", "g6", "g5", "g4", "g3", "g2", "g1")])
    picked, sink = _run(script)
    assert picked.outcome is PickOutcome.DECIDED
    assert isinstance(picked.decision, CandidatesDecision)
    assert [candidate.app_id for candidate in picked.decision.candidates] == [
        7008, 7007, 7006, 7005, 7004, 7003,
    ]
    assert len(script.prompts) == 1
    assert _metrics(sink) == {"pick_cut": 2.0}


def test_the_seed_orders_the_games_that_read_alike_and_changes_nothing_else() -> None:
    """All eight games read alike here, so the seed decides the order they
    stand in. The same seed gives the same prompt, another seed the same
    lines in another order."""
    first, again, other = AnswerScript([_CLEAN]), AnswerScript([_CLEAN]), AnswerScript([_CLEAN])
    _run(first, seed="conversation-1")
    _run(again, seed="conversation-1")
    _run(other, seed="conversation-2")
    assert first.prompts == again.prompts
    assert first.prompts != other.prompts
    assert sorted(first.prompts[0].splitlines()) == sorted(other.prompts[0].splitlines())
