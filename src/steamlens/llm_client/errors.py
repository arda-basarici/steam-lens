"""Typed failures of the LLM door — what went wrong, said precisely.

The taxonomy lives here rather than in ``contracts`` because contracts is a data
spine and errors are the client's public *behavior*. The load-bearing split:
``AtCapacityError`` is **us keeping a promise** (our own reserve refusing before
any money moves) while ``LlmUnavailableError`` is **the world failing** (provider
trouble that outlived every retry). Only the former becomes the system's honest
at-capacity state; conflating them would let a provider outage masquerade as a
budget decision. ``GenerationIncompleteError`` is the third kind — the provider
answered, money was spent and recorded, but the result isn't cleanly usable.
"""

from __future__ import annotations

from steamlens.contracts import FinishReason, LlmResponse


class LlmError(Exception):
    """The family root — every failure the LLM door raises is catchable as this."""


class LlmConfigError(LlmError):
    """The dial is wrong — an unknown provider, a dangling model reference, an
    unrouted stage. Raised at construction wherever possible so a misconfiguration
    is a startup failure, never a surprise at request four hundred."""


class AtCapacityError(LlmError):
    """Our own reserve refusing: the budget cap or a model's daily headroom is
    exhausted. Never retried — retrying a promise we made to ourselves is just
    breaking it slowly. This is the error the serving layer turns into the honest
    degraded state."""


class LlmUnavailableError(LlmError):
    """The world failing: transient provider trouble (429s, 5xx, timeouts)
    survived the bounded retry loop. Raised only at exhaustion — a transient that
    a retry absorbed never surfaces."""


class ProviderTransientError(LlmError):
    """An adapter's signal that one attempt failed for a retry-worthy reason.

    Adapters raise this for 429/5xx/timeout-class failures; the client's retry
    loop catches exactly this type and nothing else, so an adapter bug or a
    permanent 4xx propagates immediately instead of being retried into a quota
    hole. Callers never see this type — exhaustion surfaces as
    ``LlmUnavailableError``.
    """


class GenerationIncompleteError(LlmError):
    """The provider answered but did not finish cleanly — truncation, refusal,
    or an unmappable reason.

    Deliberately not retried: classification runs at temperature 0, so the same
    call re-truncates identically and a retry is a paid no-op. The spend was
    real and is already in the ledger and cache by the time this raises; the
    error carries the normalized ``reason`` and the full ``response`` so the
    caller decides what the partial result is worth.
    """

    reason: FinishReason
    response: LlmResponse

    def __init__(self, reason: FinishReason, response: LlmResponse) -> None:
        super().__init__(f"generation finished with {reason!r}, not a clean stop")
        self.reason = reason
        self.response = response
