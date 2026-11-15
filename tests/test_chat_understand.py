"""The understand shell's ladder — every rung, driven through the real client.

The claims: a valid answer is used after one call; a faulty answer gets
exactly one corrective retry that names its faults; faults that survive the
retry cost a want its target and never the want; a retry that fails falls
back to what the first answer could give; an unreadable structure, a cut-off
generation, the spend cap and provider trouble each end the turn with the
outcome its fixed reply is chosen by, and never with an exception. Calls
flow through the real ``LlmClient`` over a scripted provider, so the route
and archive-key mechanics are the production ones.
"""

from __future__ import annotations

import json
import threading

from fakes import CollectingSink

from steamlens.chat.understand import UNDERSTAND_STAGE, understand, understand_route
from steamlens.contracts import (
    AspectDef,
    AspectOntology,
    AspectTarget,
    ChatMessage,
    ChatRole,
    FinishReason,
    LlmResponse,
    LlmStage,
    MetricEvent,
    RequestIntent,
    TokenUsage,
    Understanding,
    UnderstandOutcome,
)
from steamlens.core.understand import UNAVAILABLE_REPLY, UNREADABLE_REPLY, fixed_reply
from steamlens.dispatch.census_arm import MODEL_ID, PROVIDER
from steamlens.llm_client import (
    InMemoryResponseArchive,
    InMemorySpendLedger,
    LlmClient,
    LlmClientConfig,
    ModelSpec,
    ProviderEntry,
    ProviderPayload,
    ProviderTransientError,
)

_ONTOLOGY = AspectOntology(
    version="test",
    aspects=(AspectDef("story", "The plot and how it is told.", (), "narrative", "", "", ()),),
    global_rules=(),
)
_LIBRARY = {1145360: "Hades"}
_CONVERSATION = (ChatMessage(ChatRole.PLAYER, "a game with a good story and no grind"),)

_STORY = {"words": "a good story", "firmness": "want", "stance": "wants",
          "target": {"kind": "aspect", "aspect": "story"}}
_GRIND_FAULTY = {"words": "no grind", "firmness": "must", "stance": "avoids",
                 "target": {"kind": "aspect", "aspect": "grind"}}
_GRIND_FIXED = {"words": "no grind", "firmness": "must", "stance": "avoids",
                "target": {"kind": "term", "phrases": ["grind", "grindy"]}}

_CLEAN = json.dumps({"intent": "recommend", "wants": [_STORY, _GRIND_FIXED]})
_FAULTY = json.dumps({"intent": "recommend", "wants": [_STORY, _GRIND_FAULTY]})
_BROKEN = "I think the player wants a story game."


class AnswerScript:
    """A scripted provider: answers each call with the next text in order.

    ``finishes`` overrides the finish reason per call, and a call whose
    index is in ``down`` fails the way provider trouble does.
    """

    def __init__(
        self,
        texts: list[str],
        *,
        finishes: dict[int, FinishReason] | None = None,
        down: frozenset[int] = frozenset(),
    ) -> None:
        self.prompts: list[str] = []
        self._texts = texts
        self._finishes = finishes or {}
        self._down = down
        self._lock = threading.Lock()
        self._attempts = 0

    def entry(self) -> ProviderEntry:
        return ProviderEntry(build_payload=self._build, send=self._send, parse=self._parse)

    def _build(
        self, *, model: str, prompt: str, max_output_tokens: int, params: dict[str, object]
    ) -> ProviderPayload:
        return {"model": model, "prompt": prompt}

    def _send(self, *, model: str, payload: ProviderPayload) -> str:
        with self._lock:
            prompt = str(payload["prompt"])
            if prompt not in self.prompts:
                self.prompts.append(prompt)
            index = self.prompts.index(prompt)
        if index in self._down:
            raise ProviderTransientError("scripted 503")
        finish = self._finishes.get(index, FinishReason.STOP)
        return json.dumps({"text": self._texts[index], "finish": finish})

    @staticmethod
    def _parse(raw: str) -> LlmResponse:
        body = json.loads(raw)
        return LlmResponse(
            text=str(body["text"]),
            model_version="deepseek-flash",
            finish_reason=FinishReason(str(body["finish"])),
            usage=TokenUsage(prompt_tokens=100, output_tokens=50, thinking_tokens=0),
        )


def _run(
    script: AnswerScript, *, budget_usd: float | None = None
) -> tuple[Understanding, CollectingSink]:
    config = LlmClientConfig(
        routes={LlmStage.UNDERSTAND: understand_route()},
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
    return understand(client, _CONVERSATION, _ONTOLOGY, _LIBRARY, sink, year=2026), sink


def _metrics(sink: CollectingSink) -> dict[str, float]:
    return {
        event.name: event.value
        for event in sink.events
        if isinstance(event, MetricEvent) and event.stage == UNDERSTAND_STAGE
    }


def test_a_valid_answer_is_used_after_one_call() -> None:
    script = AnswerScript([_CLEAN])
    understanding, sink = _run(script)
    assert understanding.outcome is UnderstandOutcome.UNDERSTOOD
    assert understanding.request is not None
    assert understanding.request.intent is RequestIntent.RECOMMEND
    assert len(script.prompts) == 1
    assert _metrics(sink) == {}


def test_a_faulty_answer_gets_one_corrective_retry_naming_its_faults() -> None:
    script = AnswerScript([_FAULTY, _CLEAN])
    understanding, sink = _run(script)
    assert understanding.outcome is UnderstandOutcome.RETRIED
    assert understanding.faults == ()
    assert len(script.prompts) == 2
    assert script.prompts[1].startswith(script.prompts[0])
    assert 'the want "no grind" names the aspect \'grind\'' in script.prompts[1]
    assert _metrics(sink) == {"understand_faults": 1.0}


def test_a_target_still_faulty_after_the_retry_costs_the_want_its_target_only() -> None:
    script = AnswerScript([_FAULTY, _FAULTY])
    understanding, sink = _run(script)
    assert understanding.outcome is UnderstandOutcome.SALVAGED
    assert understanding.request is not None
    story, grind = understanding.request.wants
    assert story.target == AspectTarget("story")
    assert (grind.words, grind.target) == ("no grind", None)
    assert len(understanding.faults) == 1
    assert len(script.prompts) == 2
    assert _metrics(sink)["understand_salvaged"] == 1.0
    assert fixed_reply(understanding) is None


def test_a_retry_that_reads_worse_falls_back_to_the_first_answer() -> None:
    """The retry can lose the structure, be cut off, or meet provider
    trouble. What the first answer could give is still the better turn."""
    for second in (
        AnswerScript([_FAULTY, _BROKEN]),
        AnswerScript([_FAULTY, _CLEAN], finishes={1: FinishReason.LENGTH}),
        AnswerScript([_FAULTY, _CLEAN], down=frozenset({1})),
    ):
        understanding, _ = _run(second)
        assert understanding.outcome is UnderstandOutcome.SALVAGED
        assert understanding.request is not None
        assert [want.words for want in understanding.request.wants] == ["a good story", "no grind"]


def test_a_structure_unreadable_after_the_retry_ends_the_turn() -> None:
    script = AnswerScript([_BROKEN, "[]"])
    understanding, sink = _run(script)
    assert understanding.outcome is UnderstandOutcome.UNREADABLE
    assert understanding.request is None
    assert "expected one JSON object" in understanding.faults[0]
    assert len(script.prompts) == 2
    assert _metrics(sink)["understand_unreadable"] == 1.0
    assert fixed_reply(understanding) == UNREADABLE_REPLY


def test_a_cut_off_generation_is_not_retried() -> None:
    """At temperature 0 the same call would be cut off the same way."""
    script = AnswerScript([_CLEAN], finishes={0: FinishReason.LENGTH})
    understanding, _ = _run(script)
    assert understanding.outcome is UnderstandOutcome.UNREADABLE
    assert len(script.prompts) == 1
    assert fixed_reply(understanding) == UNREADABLE_REPLY


def test_the_spend_cap_and_provider_trouble_end_the_turn_as_unavailable() -> None:
    capped, _ = _run(AnswerScript([_CLEAN]), budget_usd=0.0000001)
    down, sink = _run(AnswerScript([_CLEAN], down=frozenset({0})))
    for understanding in (capped, down):
        assert understanding.outcome is UnderstandOutcome.UNAVAILABLE
        assert understanding.request is None
        assert fixed_reply(understanding) == UNAVAILABLE_REPLY
    assert _metrics(sink)["understand_unavailable"] == 1.0

