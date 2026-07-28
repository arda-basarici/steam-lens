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

from typing import Final

from steamlens.contracts import LlmStage, Sink
from steamlens.llm_client import LlmClient, LlmClientConfig, ModelSpec, ProviderEntry, Route
from steamlens.store import Store

MODEL_ID: Final = "deepseek-v4-flash"
"""The requested model id — the label key's ``model_version`` (keys are
contracts; the provider-reported version is journaled per call instead)."""

KEY_ENV: Final = "DEEPSEEK_API_KEY"

_PROVIDER: Final = "deepseek"
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
    entry: ProviderEntry, budget_usd: float, n: int, client_store: Store, sink: Sink
) -> LlmClient:
    """The dispatch-config client over the *client's* store connection."""
    config = LlmClientConfig(
        routes={
            LlmStage.CLASSIFY: Route(
                provider=_PROVIDER,
                model=MODEL_ID,
                max_output_tokens=min(_OUTPUT_CAP, _OUTPUT_BASE + _OUTPUT_PER_REVIEW * n),
                params={
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                    "thinking": {"type": "disabled"},
                },
            )
        },
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
        registry={_PROVIDER: entry},
    )
