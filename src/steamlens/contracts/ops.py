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

    ``measured_prompt_tokens`` is the prompt volume from rows that carry the
    step-6 accounting (a recorded duration marks a row the live client
    measured at write time), and ``cached_prompt_tokens`` is the
    prefix-cache-hit subset of *that* volume — numerator and denominator of
    the hit rate the ops page shows, deliberately over the same rows. Rows
    outside the marker read "—", not 0% (the 2026-08-09 display lesson — the
    designer read the unrecorded zero as a broken number); the 2026-08-10
    repricing backfilled true splits onto old rows, which the rate still
    excludes rather than lean on a migration-shaped invariant
    (``store.ops`` states the reasoning).
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

    ``cached_prompt_tokens`` and ``measured_prompt_tokens`` pair the same way
    as on the daily row: the hit rate's numerator and denominator, both over
    the live-measured rows only.
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
class UnattributedTotals:
    """What the job journal cannot account for — the trace table's blind spot.

    ``unjournaled_reports`` counts published reports with no job row, and
    ``unattributed_cost`` is the ledger spend whose rows carry no run id (the
    step-6 "not attributed" marker — priced exactly since the 2026-08-10
    repricing, joinable to no job). Both are structural markers, not a date:
    today they are exactly the reports and calls from before the journal
    existed (2026-08-09), and the ops page states the count as the
    measurement and the journal's birth as its explanation, so the number
    stays true if a report ever lacks a job row for another reason. The
    live-app sweep's skeptic derived both by hand (tier 3 #11, 2026-08-14);
    the page now says them.
    """

    unjournaled_reports: int
    unattributed_cost: float


@dataclass(frozen=True, slots=True)
class JobRow:
    """One journaled job shaped for the ops history table.

    ``outcome`` is ``"done"``/``"failed"`` once settled and ``None`` while
    running — or forever, for a job a process death interrupted, which is
    exactly what the row should say. ``cost`` joins the ledger by the shared
    run id (0.0 for a job whose calls all landed before attribution or that
    spent nothing), and ``views`` joins the report-view journal the same way —
    how many times this job's published report has answered a page load (0
    for a job that never published). ``narrative_outcome`` joins the report
    row by run id too: the grounding ladder's rung as the report records it
    (``"composed"`` … ``"withheld"``), ``None`` for a job that never
    published — so the page can say a report shipped with its narrative
    trimmed or withheld instead of a plain ``done``. The banked counts are
    ``None`` on unsettled rows.
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
    views: int
    narrative_outcome: str | None


@dataclass(frozen=True, slots=True)
class StageLatencyRow:
    """One stage's call-latency summary over the measured ledger rows."""

    stage: str
    calls: int
    p50_s: float
    p95_s: float
