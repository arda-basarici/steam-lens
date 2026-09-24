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

MODEL_ID: Final = "deepseek-flash"
"""The requested model id — the label key's ``model_version`` (keys are
contracts; the provider-reported version is journaled per call instead).
Pinned to the provider's canonical id on 2026-09-24, after the alias it
replaced (``deepseek-v4-flash``) was re-pointed under us; the pool
namespace moved with it, so labels bought under the old key stay under
the old key, certified for the model that bought them."""

EXPECTED_MODEL_VERSION: Final = "deepseek-flash"
"""The version string the provider must report for the requested id — the
drift watch's cross-run anchor. The requested id is an alias the provider
can re-point: on 2026-09-10 DeepSeek retired V4 Flash and routed
``deepseek-v4-flash`` to V4.1 Flash, reported as ``deepseek-flash``, and
the within-run watch saw nothing for eight days. Declaring the version
here makes the next such swap fail on its first call. Part of the
instrument identity with ``MODEL_ID`` and the readings: a re-certification
updates all three together (done once, 2026-09-24 — the id, this
declaration, and the F1 reading moved in one commit)."""

PUBLISHED_READINGS: Final[dict[str, str]] = {
    "classifier F1 vs gold": "0.801 [0.752–0.844]",
    "quote misattribution rate": "11.6% [6.6–19.6]",
    "judge–production agreement F1": "0.791 [0.772–0.810]",
}
"""The instrument's published evaluation readings, display-ready — the trust
panel's disclosure block. Part of the instrument identity exactly like
``MODEL_ID``: each number was measured *on this model under this config*,
so a model or prompt change invalidates them together and the
re-measurement updates them here, in one place. The F1 is the 2026-09-24
re-certification of V4.1 Flash with prompt-only JSON (run
``certify-20260924T222850Z-b7092393``, scorer ``census-vs-gold/2``, the
recomposed gold scope under fillers seed 20260924); the two other rows
were measured on the retired V4 Flash (outcome blocks in DESIGN's
evaluation section) and ``PRIOR_MODEL_READINGS`` says so on the panel
until their re-measurement lands."""

PRIOR_MODEL_READINGS: Final[dict[str, str]] = {
    "quote misattribution rate": "2026-08-05",
    "judge–production agreement F1": "2026-07-25",
}
"""Readings carried over from the retired model, keyed like
``PUBLISHED_READINGS`` with the date they were measured. The panel appends
the caveat to each; a re-measurement removes the row here and updates the
value there, in the same commit. Empty once every reading is the current
instrument's own."""

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
# The provider's full price table, verified against api-docs.deepseek.com and
# reconciled to the dashboard's billed total 2026-08-09 (the day priced flat
# read ~5x over the bill). The cache-hit rate is DeepSeek's 50x prefix-cache
# discount; ~90% of a classify prompt is the shared ontology prefix, so the
# discount dominates real cost. Prices are config, not identity: a table
# update changes accounting, never the instrument.
_INPUT_USD_PER_1M: Final = 0.14
_CACHED_INPUT_USD_PER_1M: Final = 0.0028
_OUTPUT_USD_PER_1M: Final = 0.28


def classify_params(*, json_mode: bool) -> dict[str, object]:
    """The classify route's request parameters — deterministic, thinking off,
    and json mode by the caller's choice.

    The instrument was certified with json mode on and an *array* contract in
    the prompt: contradictory by the OpenAI-compatible convention (json mode
    means an object root), tolerated by V4 Flash, which answered arrays
    anyway. V4.1 Flash (served under the same id since 2026-09-10) resolves
    it the provider's way on ~45% of calls — the array wrapped in an object,
    or the directive echoed back as the whole answer — and every such row
    fails the parser. Measured 2026-09-24 on the recomposed gold scope: json
    mode F1 0.700 [0.624–0.766] with 24.9% of gold reviews lost to shape
    failures; prompt-only JSON F1 0.801 [0.752–0.844] with none. Production
    sends prompt-only JSON since; the bake-off's json cell keeps the old
    shape reproducible.
    """
    params: dict[str, object] = {"temperature": 0, "thinking": {"type": "disabled"}}
    if json_mode:
        params["response_format"] = {"type": "json_object"}
    return params


def build_client(
    entry: ProviderEntry,
    budget_usd: float,
    n: int,
    client_store: Store,
    sink: Sink,
    *,
    extra_routes: Mapping[LlmStage, Route] | None = None,
    run_id: str | None = None,
    json_mode: bool = False,
) -> LlmClient:
    """The dispatch-config client over the *client's* store connection.

    ``extra_routes`` lets a composing shell ride further stages on this same
    client — the serving runner adds its compose route so classify and compose
    share one budget and one real-world quota pool by construction (the config
    module's own two-tables rationale). An extra route must name a model this
    instrument block declares; anything else fails the config's reference
    check at construction, never mid-run. ``run_id`` is the ledger attribution
    the client stamps on every journaled call — the shells that mint a run
    pass theirs, so spend joins to jobs and reports without inference.
    ``json_mode`` is the one request-parameter knob, and only the bake-off
    turns it: production sends prompt-only JSON, the shape the instrument
    was re-certified with on 2026-09-24 (``classify_params`` has the numbers).
    """
    routes: dict[LlmStage, Route] = {
        LlmStage.CLASSIFY: Route(
            provider=PROVIDER,
            model=MODEL_ID,
            max_output_tokens=min(_OUTPUT_CAP, _OUTPUT_BASE + _OUTPUT_PER_REVIEW * n),
            params=classify_params(json_mode=json_mode),
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
                cached_input_usd_per_1m=_CACHED_INPUT_USD_PER_1M,
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
        run_id=run_id,
    )
