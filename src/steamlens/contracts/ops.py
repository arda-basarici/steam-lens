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
    """One UTC day's paid-call totals off the spend ledger.

    ``cached_prompt_tokens`` is the prefix-cache-hit subset of
    ``prompt_tokens`` — the provider-side cache economics the ops page shows
    as a hit rate. ``measured_prompt_tokens`` is the prompt volume from rows
    that carry the step-6 accounting (a recorded duration marks them): the
    hit rate's honest denominator, because a pre-step-6 row never recorded
    its split and must read "—", not 0% (the 2026-08-09 display lesson — the
    designer read the unrecorded zero as a broken number).
    """

    day: str
    calls: int
    prompt_tokens: int
    cached_prompt_tokens: int
    measured_prompt_tokens: int
    output_tokens: int
    thinking_tokens: int
    cost: float


@dataclass(frozen=True, slots=True)
class StageModelRow:
    """All-time paid-call totals for one (stage, model) pair.

    ``measured_prompt_tokens`` plays the same honest-denominator role as on
    the daily row.
    """

    stage: str
    model: str
    calls: int
    prompt_tokens: int
    cached_prompt_tokens: int
    measured_prompt_tokens: int
    output_tokens: int
    thinking_tokens: int
    cost: float


@dataclass(frozen=True, slots=True)
class DailyAdmissionRow:
    """One UTC day's gated fresh-job admissions — a count, never the IPs."""

    day: str
    admissions: int


@dataclass(frozen=True, slots=True)
class DailyRefusalRow:
    """One UTC day's gate refusals — a count per day, never the IPs."""

    day: str
    refusals: int


@dataclass(frozen=True, slots=True)
class JobRow:
    """One journaled job shaped for the ops history table.

    ``outcome`` is ``"done"``/``"failed"`` once settled and ``None`` while
    running — or forever, for a job a process death interrupted, which is
    exactly what the row should say. ``cost`` joins the ledger by the shared
    run id (0.0 for a job whose calls all landed before attribution or that
    spent nothing). The banked counts are ``None`` on unsettled rows.
    """

    run_id: str
    app_id: int
    requested_name: str
    started_at: str
    finished_at: str | None
    outcome: str | None
    error: str | None
    labeled: int | None
    reused: int | None
    failed_durable: int | None
    refused_batches: int | None
    cost: float


@dataclass(frozen=True, slots=True)
class StageLatencyRow:
    """One stage's call-latency summary over the measured ledger rows."""

    stage: str
    calls: int
    p50_s: float
    p95_s: float
