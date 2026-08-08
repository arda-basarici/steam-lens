"""The ops surface's aggregate rows — journal totals shaped for display.

The observability step's data language: the store's ops read model produces
these, the web renderer consumes them, and the seam between the two stays
plain data like every other (the rendering-boundary ruling — the renderer
imports contracts, never store internals). Each row is an *aggregate* by
construction: the admissions row carries a day and a count and structurally
cannot carry a client IP, which is how the security audit's no-raw-IPs rule
is enforced by shape rather than renderer discipline. Day keys are UTC dates
in ISO text — the stored timestamps are UTC-normalized at write, so a day
string compares and groups honestly.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DailyLedgerRow:
    """One UTC day's paid-call totals off the spend ledger."""

    day: str
    calls: int
    prompt_tokens: int
    output_tokens: int
    thinking_tokens: int
    cost: float


@dataclass(frozen=True, slots=True)
class StageModelRow:
    """All-time paid-call totals for one (stage, model) pair."""

    stage: str
    model: str
    calls: int
    prompt_tokens: int
    output_tokens: int
    thinking_tokens: int
    cost: float


@dataclass(frozen=True, slots=True)
class DailyAdmissionRow:
    """One UTC day's gated fresh-job admissions — a count, never the IPs."""

    day: str
    admissions: int
