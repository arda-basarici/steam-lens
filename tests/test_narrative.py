"""The compose shell's ladder — every rung, driven through the real client.

The claims: a clean draft lands COMPOSED with its certificate; a dirty draft
gets exactly one corrective retry that names the violations verbatim; a
still-dirty retry renders its surviving sentences (TRIMMED, with a fresh
certificate over the cut text); and nothing-survives, unclean finishes, and
empty completions all withhold with the disclosed narration — never an
exception out of the stage. Calls flow through the real ``LlmClient`` over a
scripted prose entry, so the archive-key and route mechanics are the
production ones.
"""

from __future__ import annotations

import json
import threading

from fakes import CollectingSink

from steamlens.contracts import (
    EvidenceQuote,
    FinishReason,
    LlmResponse,
    LlmStage,
    MetricEvent,
    NarrativeOutcome,
    Sentiment,
    SentimentCounts,
    SpanKind,
    StageEvent,
    StageKind,
    TokenUsage,
)
from steamlens.core.compose import AspectBrief, ComposeFacts
from steamlens.dispatch.census_arm import MODEL_ID, PROVIDER
from steamlens.llm_client import (
    InMemoryResponseArchive,
    InMemorySpendLedger,
    LlmClient,
    LlmClientConfig,
    ModelSpec,
    ProviderEntry,
    ProviderPayload,
)
from steamlens.serve.narrative import compose_narrative, compose_route


class ProseScript:
    """A scripted compose provider: answers each call with the next text in order."""

    def __init__(
        self, texts: list[str], finishes: list[FinishReason] | None = None
    ) -> None:
        self.prompts: list[str] = []
        self._texts = texts
        self._finishes = finishes or []
        self._lock = threading.Lock()

    def entry(self) -> ProviderEntry:
        return ProviderEntry(build_payload=self._build, send=self._send, parse=self._parse)

    def _build(
        self, *, model: str, prompt: str, max_output_tokens: int, params: dict[str, object]
    ) -> ProviderPayload:
        return {"model": model, "prompt": prompt}

    def _send(self, *, model: str, payload: ProviderPayload) -> str:
        with self._lock:
            index = len(self.prompts)
            self.prompts.append(str(payload["prompt"]))
        finish = (
            self._finishes[index] if index < len(self._finishes) else FinishReason.STOP
        )
        return json.dumps({"text": self._texts[index], "finish": finish})

    @staticmethod
    def _parse(raw: str) -> LlmResponse:
        body = json.loads(raw)
        return LlmResponse(
            text=str(body["text"]),
            model_version="deepseek-v4-flash-0902",
            finish_reason=FinishReason(str(body["finish"])),
            usage=TokenUsage(prompt_tokens=100, output_tokens=50, thinking_tokens=0),
        )


def _client(script: ProseScript) -> LlmClient:
    config = LlmClientConfig(
        routes={LlmStage.COMPOSE: compose_route()},
        models={
            MODEL_ID: ModelSpec(
                rpm=6_000, rpd=None, input_usd_per_1m=0.0, output_usd_per_1m=0.0
            )
        },
    )
    return LlmClient(
        config,
        InMemoryResponseArchive(),
        InMemorySpendLedger(),
        CollectingSink(),
        registry={PROVIDER: script.entry()},
        sleep=lambda _: None,
    )


_QUOTE = EvidenceQuote(
    review_id="r7",
    aspect="performance",
    sentiment=Sentiment.NEGATIVE,
    text="frame drops every time the swarm shows up",
)

_FACTS = ComposeFacts(
    game_name="Dome Keeper",
    sample_size=1_000,
    take_all=False,
    aspects=(
        AspectBrief(
            aspect="performance",
            reviews_with_aspect=273,
            share_pct=27.3,
            counts=SentimentCounts(positive=41, negative=210, mixed=15, neutral=7),
            quotes=(_QUOTE,),
        ),
    ),
    themes=(),
)

_WHITELIST = frozenset({1_000.0, 273.0, 27.3, 210.0, 41.0, 15.0, 7.0, 21.0})


def _warns(sink: CollectingSink) -> list[str]:
    return [
        event.message
        for event in sink.events
        if isinstance(event, StageEvent) and event.kind is StageKind.WARN
    ]


def test_a_clean_draft_lands_composed_with_its_certificate() -> None:
    """Grounded numerals certify with values, the quotation with its source id —
    one call, no retry."""
    prose = (
        'Performance dominates: 273 of 1,000 reviews raise it, and one wrote '
        '"frame drops every time the swarm" before moving on.'
    )
    script = ProseScript([prose])
    sink = CollectingSink()
    narrative = compose_narrative(_client(script), _FACTS, _WHITELIST, sink)
    assert narrative.outcome is NarrativeOutcome.COMPOSED
    assert narrative.prose == prose
    kinds = [(span.kind, span.text) for span in narrative.spans]
    assert (SpanKind.NUMERAL, "273") in kinds
    assert (SpanKind.NUMERAL, "1,000") in kinds
    quote_spans = [span for span in narrative.spans if span.kind is SpanKind.QUOTE]
    assert [span.review_id for span in quote_spans] == ["r7"]
    assert len(script.prompts) == 1


def test_a_dirty_draft_gets_one_corrective_retry_naming_the_violations() -> None:
    """The retry prompt carries the violation verbatim; a clean second draft
    lands RETRIED."""
    script = ProseScript(
        [
            "Roughly 40% of players complain about performance.",
            "Performance comes up in 273 reviews.",
        ]
    )
    sink = CollectingSink()
    narrative = compose_narrative(_client(script), _FACTS, _WHITELIST, sink)
    assert narrative.outcome is NarrativeOutcome.RETRIED
    assert narrative.prose == "Performance comes up in 273 reviews."
    assert len(script.prompts) == 2
    assert "broke the grounding rules" in script.prompts[1]
    assert "numeral '40'" in script.prompts[1]


def test_a_still_dirty_retry_renders_its_surviving_sentences() -> None:
    """Past the retry the violating sentence drops; the survivor re-grounds and
    its certificate offsets refer to the cut text."""
    script = ProseScript(
        [
            "Roughly 40% complain.",
            "Roughly 40% complain. Performance comes up in 273 reviews.",
        ]
    )
    sink = CollectingSink()
    narrative = compose_narrative(_client(script), _FACTS, _WHITELIST, sink)
    assert narrative.outcome is NarrativeOutcome.TRIMMED
    assert narrative.prose == "Performance comes up in 273 reviews."
    (span,) = narrative.spans
    assert (span.text, narrative.prose[span.start : span.end]) == ("273", "273")


def test_nothing_surviving_withholds_with_the_disclosed_narration() -> None:
    """Both drafts dirty and no survivor: empty prose, WITHHELD, the warn line
    and the metric journaled."""
    script = ProseScript(
        ["Roughly 40% complain.", "Roughly 40% still complain."]
    )
    sink = CollectingSink()
    narrative = compose_narrative(_client(script), _FACTS, _WHITELIST, sink)
    assert narrative.outcome is NarrativeOutcome.WITHHELD
    assert (narrative.prose, narrative.spans) == ("", ())
    assert any("narrative withheld" in message for message in _warns(sink))
    assert any(
        isinstance(event, MetricEvent) and event.name == "narrative_withheld"
        for event in sink.events
    )


def test_an_unclean_finish_withholds_instead_of_aborting() -> None:
    """A LENGTH finish surfaces as the client's incomplete-generation error and
    degrades to withholding — the job survives, the failure narrates."""
    script = ProseScript(["cut off mid-sentence"], finishes=[FinishReason.LENGTH])
    sink = CollectingSink()
    narrative = compose_narrative(_client(script), _FACTS, _WHITELIST, sink)
    assert narrative.outcome is NarrativeOutcome.WITHHELD
    assert len(script.prompts) == 1
    assert any("compose call failed" in message for message in _warns(sink))


def test_an_empty_completion_withholds() -> None:
    """A blank reply is not a passing narrative — it withholds, disclosed."""
    script = ProseScript(["   "])
    sink = CollectingSink()
    narrative = compose_narrative(_client(script), _FACTS, _WHITELIST, sink)
    assert narrative.outcome is NarrativeOutcome.WITHHELD
    assert any("empty completion" in message for message in _warns(sink))
