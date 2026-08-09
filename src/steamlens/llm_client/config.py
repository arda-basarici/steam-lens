"""What the door is dialed to — routes, model envelopes, prices, the budget cap.

Everything the milestone-exit tier decision would touch is *data* here: moving a
stage to a paid model is a route edit plus a limits-table row, zero code. Two
tables on purpose — routes are per-stage (which model serves this job), model
specs are per-model (pacing, daily quota, prices), because two stages routed to
the same model share one real-world quota pool and must not each believe they
own it.

Reference integrity is checked at construction: a route naming an absent model
spec raises here; provider names are checked against the registry by the client
(the registry is a constructor argument there, not visible here).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from steamlens.contracts import LlmStage
from steamlens.llm_client.errors import LlmConfigError


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """One model's operating envelope: pacing, daily quota, prices.

    ``rpm`` paces dispatch (requests per minute); ``rpd`` is the provider's
    daily request quota, ``None`` meaning uncapped. Prices are USD per million
    tokens; thinking tokens bill at the **output** rate — the probe's
    sticker-price lesson, encoded where cost is computed from. Free-tier models
    carry honest zeros. ``cached_input_usd_per_1m`` is the provider's
    prefix-cache-hit input rate — ``None`` means no discount is priced and
    every prompt token bills at the full input rate (conservative), which was
    the ledger's ~5x overstatement against the real bill until the 2026-08-09
    reconciliation priced the split.
    """

    rpm: int
    rpd: int | None
    input_usd_per_1m: float
    output_usd_per_1m: float
    cached_input_usd_per_1m: float | None = None

    def __post_init__(self) -> None:
        # A misconfiguration is a startup failure, never a surprise mid-run:
        # rpm=0 would divide pacing by zero after a reservation is booked,
        # and a negative value silently disables pacing.
        if self.rpm <= 0:
            raise LlmConfigError(f"rpm must be positive, got {self.rpm}")
        if self.rpd is not None and self.rpd <= 0:
            raise LlmConfigError(f"rpd must be positive when set, got {self.rpd}")
        if self.input_usd_per_1m < 0 or self.output_usd_per_1m < 0:
            raise LlmConfigError("token prices must be non-negative")
        if self.cached_input_usd_per_1m is not None and not (
            0 <= self.cached_input_usd_per_1m <= self.input_usd_per_1m
        ):
            raise LlmConfigError(
                "cached input price must sit between 0 and the full input price — "
                f"got {self.cached_input_usd_per_1m} against {self.input_usd_per_1m}"
            )


@dataclass(frozen=True, slots=True)
class Route:
    """Where one stage's calls go, and under what generation ceiling.

    ``provider`` names a registry entry; ``model`` names a ``ModelSpec`` row.
    ``max_output_tokens`` is the route's *total* generation ceiling — output
    plus thinking — kept as a typed field (not inside ``params``) because the
    client prices it for the worst-case budget reservation; the adapter maps it
    into the vendor's own syntax. ``params`` is the opaque provider-params
    block, passed to the adapter untranslated so vendor-specific knobs
    (thinking config, safety settings) never widen the seam.
    """

    provider: str
    model: str
    max_output_tokens: int
    params: dict[str, object] = field(default_factory=dict[str, object])


@dataclass(frozen=True, slots=True)
class LlmClientConfig:
    """The whole dial the client is constructed with.

    ``routes`` maps each served stage to its route; ``models`` is the per-model
    limits/price table routes reference. ``budget_usd`` caps spend over the
    client's lifetime (one run), ``None`` meaning uncapped — free-tier runs cap
    by quota instead. ``daily_reset_utc_hour`` is the UTC hour the provider's
    daily quota window rolls over (Gemini resets at midnight Pacific; the
    adapter's config picks the conservative fixed offset).
    """

    routes: dict[LlmStage, Route]
    models: dict[str, ModelSpec]
    budget_usd: float | None = None
    daily_reset_utc_hour: int = 0

    def __post_init__(self) -> None:
        for stage, route in self.routes.items():
            if route.model not in self.models:
                raise LlmConfigError(
                    f"stage {stage!r} routes to model {route.model!r}, which has no "
                    f"ModelSpec; known models: {sorted(self.models)}"
                )
        if not 0 <= self.daily_reset_utc_hour <= 23:
            raise LlmConfigError(
                f"daily_reset_utc_hour must be 0..23, got {self.daily_reset_utc_hour}"
            )
