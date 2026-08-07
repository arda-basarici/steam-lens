"""The compose stage shell — one model call fenced by the grounding ladder.

The composer rides the survey labeler's model (``census_arm``'s instrument
block), deliberately **cross-family from the Gemini judge**: the chat milestone
plans groundedness evals on the judge machinery whose object is composed
prose, and a same-family composer would import exactly the self-preference the
no-gold-entangled-instrument rule exists to block. Temperature 0 under
prose-shaped params — no JSON response format; the deterministic fences are
the gates, not the decoding.

The ladder is the design's honest degradation, orchestrated here over the pure
gate: one corrective retry naming the violations (legitimate where classify
rejected corrective prompting — naming violations *changes the request*, so a
temperature-0 retry is a different question, not a paid no-op), then offending
sentences drop and the survivors re-ground for a fresh certificate, then the
narrative is withheld outright. Prose is garnish — the numbers and evidence
are the product — so provider trouble at this stage (capacity, transients
outliving retries, an unclean finish) warns and withholds rather than aborting
a job whose labels are already banked; ``ProviderPermanentError`` still
propagates, being a configuration bug, not a prose problem. Violation and
withholding counts journal through the sink as metrics beside the narration.
"""

from __future__ import annotations

from typing import Final

from steamlens.contracts import (
    ComposedNarrative,
    LlmRequest,
    LlmStage,
    MetricEvent,
    NarrativeOutcome,
    Sink,
    StageKind,
)
from steamlens.core.compose import ComposeFacts, build_compose_prompt
from steamlens.core.grounding import (
    GroundingReport,
    drop_violating_sentences,
    ground,
    normalize_quotes,
)
from steamlens.dispatch import narrate
from steamlens.dispatch.census_arm import MODEL_ID, PROVIDER
from steamlens.llm_client import (
    AtCapacityError,
    GenerationIncompleteError,
    LlmClient,
    LlmUnavailableError,
    Route,
)

COMPOSE_STAGE: Final = "serve.compose"

# The narrative asks for at most 220 words (~300 tokens); 1,024 is headroom,
# not license — a LENGTH finish is an unclean generation and withholds.
_OUTPUT_CAP: Final = 1_024


def compose_route() -> Route:
    """The compose dial: the labeler's model under prose params, temperature 0.

    Handed to ``census_arm.build_client`` as an extra route so both stages
    share one client — one budget, one quota pool, one pacer. Promotion to
    another model is exactly this route edit, on evidence.
    """
    return Route(
        provider=PROVIDER,
        model=MODEL_ID,
        max_output_tokens=_OUTPUT_CAP,
        params={"temperature": 0, "thinking": {"type": "disabled"}},
    )


def compose_narrative(
    client: LlmClient,
    facts: ComposeFacts,
    whitelist: frozenset[float],
    sink: Sink,
) -> ComposedNarrative:
    """Run the compose call and walk the grounding ladder to a narrative.

    The gate's verification pool is exactly the quotes the prompt offered —
    the strictest honest check: the model was told to quote only from the
    evidence block, so a quotation verifying against some unseen stored span
    would be luck, not grounding. Every rung narrates; a ``WITHHELD`` return
    carries empty prose and the caller renders numbers-and-quotes with a
    disclosed line.
    """
    pool = tuple(quote for brief in facts.aspects for quote in brief.quotes)
    prompt = build_compose_prompt(facts)
    first = _attempt(client, prompt, whitelist, facts, sink)
    if first is None:
        return _withheld(sink, "the compose call failed")
    prose, report = first
    if not prose:
        return _withheld(sink, "the model returned an empty completion")
    if report.passed:
        narrate(
            sink, COMPOSE_STAGE, StageKind.DONE,
            f"narrative grounded clean: {len(report.certified)} certified spans",
        )
        return ComposedNarrative(prose, report.certified, NarrativeOutcome.COMPOSED)

    _journal_violations(sink, report)
    narrate(
        sink, COMPOSE_STAGE, StageKind.WARN,
        f"grounding gate: {len(report.violations)} violations — corrective retry",
    )
    second = _attempt(client, _corrective_prompt(prompt, report), whitelist, facts, sink)
    if second is None:
        return _withheld(sink, "the corrective retry failed")
    prose, report = second
    if not prose:
        return _withheld(sink, "the corrective retry returned an empty completion")
    if report.passed:
        narrate(
            sink, COMPOSE_STAGE, StageKind.DONE,
            f"narrative grounded on the corrective retry: "
            f"{len(report.certified)} certified spans",
        )
        return ComposedNarrative(prose, report.certified, NarrativeOutcome.RETRIED)

    _journal_violations(sink, report)
    survivors = drop_violating_sentences(prose, report)
    if survivors:
        final = ground(survivors, whitelist, pool)
        if final.passed:
            narrate(
                sink, COMPOSE_STAGE, StageKind.WARN,
                f"grounding gate: violating sentences dropped — "
                f"{len(final.certified)} certified spans survive",
            )
            return ComposedNarrative(survivors, final.certified, NarrativeOutcome.TRIMMED)
    return _withheld(sink, "no sentence survived the gate")


def _attempt(
    client: LlmClient,
    prompt: str,
    whitelist: frozenset[float],
    facts: ComposeFacts,
    sink: Sink,
) -> tuple[str, GroundingReport] | None:
    """One compose call, normalized and grounded; ``None`` on a degradable failure.

    Catches exactly the failures the ladder absorbs — our own capacity
    refusal, provider transients that outlived the client's retries, an
    unclean finish. A permanent rejection or a config error propagates: those
    are bugs to fix, not prose to withhold.
    """
    pool = tuple(quote for brief in facts.aspects for quote in brief.quotes)
    try:
        response = client.complete(LlmRequest(stage=LlmStage.COMPOSE, prompt=prompt))
    except (AtCapacityError, GenerationIncompleteError, LlmUnavailableError) as error:
        narrate(sink, COMPOSE_STAGE, StageKind.WARN, f"compose call failed: {error}")
        return None
    prose = normalize_quotes(response.text.strip())
    return prose, ground(prose, whitelist, pool)


def _corrective_prompt(prompt: str, report: GroundingReport) -> str:
    """The retry request: the same task plus the violations, named verbatim.

    Appending the violations changes the request — which is what makes a
    retry legitimate here at temperature 0 — and the new prompt hashes to a
    new archive key by construction, so the retry is a real second purchase,
    never a cache echo of the failure.
    """
    named = "\n".join(
        f"- {violation.kind.value} {violation.text!r}: {violation.reason}"
        for violation in report.violations
    )
    return (
        prompt
        + "\nYour previous draft broke the grounding rules:\n"
        + named
        + "\n\nWrite the narrative again, obeying every rule. Remove or replace the"
        " violating numbers and quotations; do not repeat them.\n"
    )


def _journal_violations(sink: Sink, report: GroundingReport) -> None:
    sink.emit(
        MetricEvent(
            stage=COMPOSE_STAGE,
            name="grounding_violations",
            value=float(len(report.violations)),
            unit="count",
        )
    )


def _withheld(sink: Sink, why: str) -> ComposedNarrative:
    """The ladder's floor: no prose, disclosed — the numbers still render."""
    narrate(
        sink, COMPOSE_STAGE, StageKind.WARN,
        f"narrative withheld ({why}) — the report renders aggregates and quotes"
        " with a disclosed line",
    )
    sink.emit(
        MetricEvent(stage=COMPOSE_STAGE, name="narrative_withheld", value=1.0, unit="count")
    )
    return ComposedNarrative(prose="", spans=(), outcome=NarrativeOutcome.WITHHELD)
