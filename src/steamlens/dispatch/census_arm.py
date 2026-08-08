"""The census annotator's identity — the production model as a citable instrument.

The label pool's production envelopes all carry one annotator: this model,
under this generation config, at these prices. That identity is not the
labeling driver's private constant — certification and the agreement read
judge *the production model*, and the D2d cells re-dispatch it under
controlled conditions — so it lives here as an instrument block, the exact
mirror of the judge block ``evals/judge_dispatch`` owns. A consumer citing
``census_arm.MODEL_ID`` is naming the annotator under judgment, not reaching
into a driver's interior.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from steamlens.contracts import LlmStage, Sink
from steamlens.llm_client import LlmClient, LlmClientConfig, ModelSpec, ProviderEntry, Route
from steamlens.store import Store

MODEL_ID: Final = "deepseek-v4-flash"
"""The requested model id — the label key's ``model_version`` (keys are
contracts; the provider-reported version is journaled per call instead)."""

PUBLISHED_READINGS: Final[dict[str, str]] = {
    "classifier F1 vs gold": "0.766 [0.713–0.811]",
    "quote misattribution rate": "11.6% [6.6–19.6]",
    "judge–production agreement F1": "0.791 [0.772–0.810]",
}
"""The instrument's published evaluation readings, display-ready — the trust
panel's disclosure block. Part of the instrument identity exactly like
``MODEL_ID``: each number was measured *on this model under this config*
(certification run ``certify-20260728T184100Z-5f3f4652`` over census labels
vs gold; the misattribution audit 2026-08-05; the judge agreement read
2026-07-25 — outcome blocks in DESIGN's evaluation section), so a model or
prompt change invalidates them together and the re-measurement updates them
here, in one place."""

KEY_ENV: Final = "DEEPSEEK_API_KEY"

PROVIDER: Final = "deepseek"
"""The registry name this instrument's entry binds under — public because a
rider route (the serving composer) must name the same provider to share the
same client."""
# The bake-off's measured output sizing: the base holds one worst-case dense
# review, the per-review term covers dense batches, the cap is DeepSeek's.
_OUTPUT_BASE: Final = 2_048
_OUTPUT_PER_REVIEW: Final = 200
_OUTPUT_CAP: Final = 8_192
# Politeness backstop only — DeepSeek's envelope is concurrency-based (no rpm);
# high enough that the worker pool, not pacing, is the real throttle.
_RPM: Final = 600
_INPUT_USD_PER_1M: Final = 0.14
_OUTPUT_USD_PER_1M: Final = 0.28


def build_client(
    entry: ProviderEntry,
    budget_usd: float,
    n: int,
    client_store: Store,
    sink: Sink,
    *,
    extra_routes: Mapping[LlmStage, Route] | None = None,
) -> LlmClient:
    """The dispatch-config client over the *client's* store connection.

    ``extra_routes`` lets a composing shell ride further stages on this same
    client — the serving runner adds its compose route so classify and compose
    share one budget and one real-world quota pool by construction (the config
    module's own two-tables rationale). An extra route must name a model this
    instrument block declares; anything else fails the config's reference
    check at construction, never mid-run.
    """
    routes: dict[LlmStage, Route] = {
        LlmStage.CLASSIFY: Route(
            provider=PROVIDER,
            model=MODEL_ID,
            max_output_tokens=min(_OUTPUT_CAP, _OUTPUT_BASE + _OUTPUT_PER_REVIEW * n),
            params={
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "thinking": {"type": "disabled"},
            },
        )
    }
    routes.update(extra_routes or {})
    config = LlmClientConfig(
        routes=routes,
        models={
            MODEL_ID: ModelSpec(
                rpm=_RPM,
                rpd=None,
                input_usd_per_1m=_INPUT_USD_PER_1M,
                output_usd_per_1m=_OUTPUT_USD_PER_1M,
            )
        },
        budget_usd=budget_usd,
    )
    return LlmClient(
        config,
        client_store.responses,
        client_store.spend_ledger,
        sink,
        registry={PROVIDER: entry},
    )
