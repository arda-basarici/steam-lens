"""Run the canary set against live models — the model-side half, at both stages.

The set's scoring is pure and deterministic, but the *output* it scores cannot
be: measuring whether a prompt's walls hold requires asking a real model, so
this is a harness probe at prompt-change and model-change cadence, never a CI
re-score. That boundary is deliberate — the evals-in-CI rule admits only
deterministic re-scoring of stored artifacts, and pinning a model's live
behavior into CI would buy flakiness and spend, not safety. The render-side
half of the canary story (every review-sourced string escapes inert) *is*
deterministic and gates in CI with the frontend step.

Both surfaces run, because the walls differ. At **classify** the canaries ride
the reviews block: the beacon check asks whether the model was steered, and
the parse asks the second question no beacon can — whether the answer still
carried one well-formed row per review, which is what a format-break attack
actually targets. At **compose** the canaries ride the evidence block as
quotable spans over an otherwise ordinary fact sheet, and the run reports both
the beacon check and the grounding gate's verdict on the prose.

Fresh output is required, so the response archive is deliberately bypassed
with a per-run nonce in the prompt: an archived reply from a previous run
would score its own history, reporting walls that held last month as holding
today. The run journals nothing into the eval-run tables — those pin a
measuring stick against a reference, and a canary run measures the prompts,
not the labeler.

Run: ``python -m steamlens.evals.canary_run --out probes/captures/canaries``
"""

from __future__ import annotations

import argparse
import json
import os
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from steamlens.contracts import (
    AspectAggregate,
    AspectSlot,
    ClassifierVersions,
    EvidenceQuote,
    LlmRequest,
    LlmStage,
    Sentiment,
    SentimentCounts,
    SinkEvent,
)
from steamlens.core.classify import build_classify_prompt, parse_classify_response
from steamlens.core.compose import AspectBrief, ComposeFacts, build_compose_prompt
from steamlens.core.grounding import derive_whitelist, ground, normalize_quotes
from steamlens.core.normalize import build_surface_index
from steamlens.dispatch import code_version
from steamlens.dispatch.census_arm import KEY_ENV, MODEL_ID, PROVIDER
from steamlens.evals.canaries import (
    CANARY_SET_VERSION,
    Canary,
    CanaryReport,
    CanarySurface,
    for_surface,
    load_canaries,
    score_output,
)
from steamlens.llm_client import (
    LlmClient,
    LlmClientConfig,
    ModelSpec,
    ProviderEntry,
    Route,
    openai_compat_entry,
)
from steamlens.llm_client.memory import InMemoryResponseArchive, InMemorySpendLedger
from steamlens.llm_client.openai_compat import DEEPSEEK_BASE_URL
from steamlens.ontology import load_ontology
from steamlens.serve.narrative import compose_route

# The canaries are long and the classify answer is per review; one batch of
# six needs materially more room than the census's dense-review sizing.
_CLASSIFY_OUTPUT_CAP: Final = 4_096

# A canary run is ten-ish calls at census prices — cents. The cap exists so a
# misconfigured route cannot spend unattended, not as a real constraint.
_BUDGET_USD: Final = 0.50

# The fact sheet the compose surface runs over: ordinary numbers, so the only
# adversarial content in the prompt is the evidence itself.
_SAMPLE_SIZE: Final = 1_000
_CANARY_ASPECT: Final = "gameplay"
_CANARY_MENTIONS: Final = 120


@dataclass(frozen=True, slots=True)
class SurfaceResult:
    """One stage's canary run: what was asked, what came back, what it means.

    ``structural_note`` carries the second question a beacon check cannot ask
    — whether classify's answer still parsed one row per review, or whether
    compose's prose still passed the grounding gate.
    """

    surface: CanarySurface
    canary_ids: tuple[str, ...]
    output: str
    report: CanaryReport
    structural_note: str

    @property
    def held(self) -> bool:
        return self.report.held


def run_classify_surface(
    client: LlmClient, canaries: Sequence[Canary], ontology_path: Path | None, nonce: str
) -> SurfaceResult:
    """Send the classify-surface canaries as one review batch and score the reply.

    The batch is the canaries alone: mixing in benign filler would dilute
    nothing (each canary is scored by its own beacon) while making a
    format-break's blast radius harder to read. The nonce rides as a trailing
    benign review so the payload — and therefore the archive key — is unique
    per run.
    """
    ontology = load_ontology(ontology_path)
    texts = [canary.text for canary in canaries]
    texts.append(f"Short and fun, worth the sale price. (run {nonce})")
    prompt = build_classify_prompt(texts, ontology)
    response = client.complete(LlmRequest(stage=LlmStage.CLASSIFY, prompt=prompt))
    parsed = parse_classify_response(
        response.text, texts, build_surface_index(ontology)
    )
    note = (
        f"parse: {len(parsed.parsed)}/{len(texts)} rows salvaged, "
        f"{len(parsed.failures)} failures, {len(parsed.repairs)} evidence repairs"
    )
    return SurfaceResult(
        surface=CanarySurface.CLASSIFY,
        canary_ids=tuple(canary.canary_id for canary in canaries),
        output=response.text,
        report=CanaryReport(score_output(canaries, response.text)),
        structural_note=note,
    )


def run_compose_surface(
    client: LlmClient, canaries: Sequence[Canary], nonce: str
) -> SurfaceResult:
    """Offer the compose-surface canaries as quotable evidence and score the prose.

    Every canary enters as an evidence span on one ordinary aspect, which is
    exactly how attacker text reaches this stage in production: a review's
    span is stored verbatim, selected, and handed to the composer as
    quotable. The grounding gate then runs over the reply as it would in a
    job, and its verdict rides in the structural note — a beacon that arrives
    *as a verified quotation* is the laundering case, and the note is where
    that shows. The whitelist derives from the fixture aggregate through
    ``derive_whitelist`` — the production derivation, not a hand-list — so
    the note reports the shipped gate's verdict rather than a stricter one
    (the first live run's hand-list omitted the fact sheet's own sentiment
    counts and mislabeled honest restatements as violations).
    """
    quotes = tuple(
        EvidenceQuote(
            review_id=canary.canary_id,
            aspect=_CANARY_ASPECT,
            sentiment=Sentiment.POSITIVE,
            text=canary.text,
        )
        for canary in canaries
    )
    aggregate = AspectAggregate(
        app_id=0,
        aspect=_CANARY_ASPECT,
        slot=AspectSlot.PINNED,
        reviews_with_aspect=_CANARY_MENTIONS,
        counts=SentimentCounts(positive=90, negative=20, mixed=6, neutral=4),
        sample_size=_SAMPLE_SIZE,
        versions=ClassifierVersions(
            model_version=MODEL_ID,
            prompt_version="canary-fixture",
            ontology_version="canary-fixture",
        ),
        manifest_id=f"canary-{nonce}",
    )
    facts = ComposeFacts(
        game_name=f"Canary Run {nonce}",
        sample_size=aggregate.sample_size,
        take_all=False,
        aspects=(
            AspectBrief(
                aspect=aggregate.aspect,
                reviews_with_aspect=aggregate.reviews_with_aspect,
                share_pct=aggregate.reviews_with_aspect / aggregate.sample_size * 100,
                counts=aggregate.counts,
                quotes=quotes,
            ),
        ),
        themes=(),
    )
    prompt = build_compose_prompt(facts)
    response = client.complete(LlmRequest(stage=LlmStage.COMPOSE, prompt=prompt))
    prose = normalize_quotes(response.text.strip())
    whitelist = derive_whitelist([aggregate], sample_size=aggregate.sample_size)
    grounding = ground(prose, whitelist, quotes)
    note = (
        f"grounding: {'passed' if grounding.passed else 'failed'}, "
        f"{len(grounding.certified)} certified spans, "
        f"{len(grounding.violations)} violations"
    )
    return SurfaceResult(
        surface=CanarySurface.COMPOSE,
        canary_ids=tuple(canary.canary_id for canary in canaries),
        output=prose,
        report=CanaryReport(score_output(canaries, prose)),
        structural_note=note,
    )


class _QuietSink:
    """Swallows the client's per-call metrics — the canary run's own report is the output."""

    def emit(self, event: SinkEvent) -> None:
        pass


def build_canary_client(entry: ProviderEntry) -> LlmClient:
    """A throwaway client for one canary run — in-memory archive, no journal.

    The in-memory bindings are the point, not a convenience: archiving these
    responses durably would enroll adversarial text into the provenance
    record the label pool's archive exists to be, and a ledger row would
    charge a measurement against a run's spend history.
    """
    config = LlmClientConfig(
        routes={
            LlmStage.CLASSIFY: Route(
                provider=PROVIDER,
                model=MODEL_ID,
                max_output_tokens=_CLASSIFY_OUTPUT_CAP,
                params={
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                    "thinking": {"type": "disabled"},
                },
            ),
            LlmStage.COMPOSE: compose_route(),
        },
        models={
            MODEL_ID: ModelSpec(
                rpm=600, rpd=None, input_usd_per_1m=0.14, output_usd_per_1m=0.28
            )
        },
        budget_usd=_BUDGET_USD,
    )
    return LlmClient(
        config,
        InMemoryResponseArchive(),
        InMemorySpendLedger(),
        _QuietSink(),
        registry={PROVIDER: entry},
    )


def render_result(result: SurfaceResult) -> str:
    """One surface's outcome as the lines a person reads on the console."""
    lines = [
        f"=== {result.surface.value} surface — {len(result.canary_ids)} canaries ===",
        f"  {result.structural_note}",
    ]
    for outcome in result.report.outcomes:
        if outcome.failed:
            verdict = "BREACH"
        elif outcome.breached:
            verdict = "limitation (expected, measured)"
        else:
            verdict = "held"
        lines.append(f"  {outcome.canary_id:<12} {outcome.shape.value:<22} {verdict}")
    lines.append(
        f"  verdict: {'all walls held' if result.held else 'WALLS FAILED'}"
        f" ({len(result.report.limitations)} known limitations observed)"
    )
    return "\n".join(lines)


def capture(results: Sequence[SurfaceResult], nonce: str) -> dict[str, object]:
    """The run's machine record — the capture a future run compares against."""
    return {
        "canary_set_version": CANARY_SET_VERSION,
        "model": MODEL_ID,
        "code_version": code_version(),
        "run_nonce": nonce,
        "ran_at": datetime.now(UTC).isoformat(),
        "surfaces": [
            {
                "surface": result.surface.value,
                "structural_note": result.structural_note,
                "held": result.held,
                "outcomes": [
                    {
                        "canary_id": outcome.canary_id,
                        "shape": outcome.shape.value,
                        "expectation": outcome.expectation.value,
                        "breached": outcome.breached,
                        "failed": outcome.failed,
                    }
                    for outcome in result.report.outcomes
                ],
                "output": result.output,
            }
            for result in results
        ],
    }


def main() -> None:
    """CLI: run both surfaces, print the verdicts, write the capture."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("probes/captures/canaries"))
    parser.add_argument("--ontology", type=Path, default=None)
    args = parser.parse_args()

    key = os.environ.get(KEY_ENV)
    if not key:
        raise SystemExit(f"{KEY_ENV} is not set — the canary run needs live output")
    nonce = uuid.uuid4().hex[:8]
    canaries = load_canaries()
    entry = openai_compat_entry(key, base_url=DEEPSEEK_BASE_URL)
    client = build_canary_client(entry)

    results = [
        run_classify_surface(
            client, for_surface(canaries, CanarySurface.CLASSIFY), args.ontology, nonce
        ),
        run_compose_surface(client, for_surface(canaries, CanarySurface.COMPOSE), nonce),
    ]
    for result in results:
        print(render_result(result))
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"canary_run_{nonce}.json"
    path.write_text(
        json.dumps(capture(results, nonce), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\ncapture: {path}")
    raise SystemExit(0 if all(result.held for result in results) else 1)


if __name__ == "__main__":
    main()
