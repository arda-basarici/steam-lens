"""View models for the ops page — journal aggregates shaped for the template.

The observability step's rendering half (DESIGN: monitoring — "the richer
observability … is the in-app ops dashboard reading the same store, a product
page rather than infrastructure"): pure builders, loaded aggregates in,
display records out, same discipline as the report page's ``view``. The page
is public read-only by ruling (2026-08-09): a portfolio app's ops surface is
itself on display, so it renders aggregates a visitor may see — and the input
rows are aggregate by construction (``contracts.ops``), so there is no raw
IP here to leak.

The vocabulary is deliberate LLMOps: cost per call and per report, token
splits by stage and model, the day's allowance against the spend breaker.
These are the platform concepts (traces, spans, cost, failure rates) told
natively over the app's own journals; failure rates and latency join when
the job journal lands (the designed 3b increment) — the page states that gap
honestly rather than rendering an empty section.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from steamlens.contracts import (
    DailyAdmissionRow,
    DailyLedgerRow,
    DailyRefusalRow,
    JobRow,
    StageLatencyRow,
    StageModelRow,
)


@dataclass(frozen=True, slots=True)
class OpsData:
    """The raw ops facts the composition root loads — the builder's input.

    ``now`` rides along so the header's generated-at stamp shares the instant
    the "today" reads were computed against (one clock, one story);
    ``admissions_today``/``spend_today_usd`` are the gate's own reads reused,
    and the limits are the serving config's dials so the page always shows
    the numbers actually enforcing.
    """

    now: datetime
    admissions_today: int
    daily_job_limit: int
    per_ip_daily_job_limit: int
    spend_today_usd: float
    daily_spend_backstop_usd: float
    daily_ledger: tuple[DailyLedgerRow, ...]
    daily_admissions: tuple[DailyAdmissionRow, ...]
    stage_model: tuple[StageModelRow, ...]
    report_count: int
    daily_refusals: tuple[DailyRefusalRow, ...] = ()
    jobs: tuple[JobRow, ...] = ()
    stage_latencies: tuple[StageLatencyRow, ...] = ()


@dataclass(frozen=True, slots=True)
class OpsStat:
    """One headline number: label, formatted value, and its honest qualifier."""

    label: str
    value: str
    note: str


@dataclass(frozen=True, slots=True)
class OpsTable:
    """One rendered table: headers and pre-formatted string rows.

    Generic cells rather than a dataclass per table because these tables ARE
    tabular numbers — the meaning lives in the header row, and the template
    stays one loop.
    """

    title: str
    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    note: str | None = None
    text_columns: int = 1
    """How many leading columns hold text — the template left-aligns these
    and right-aligns the numeric rest (the tabular-comparison convention)."""


@dataclass(frozen=True, slots=True)
class OpsView:
    """Everything ``ops.html`` renders, in page order.

    ``notes`` are the page-level honesty lines (the pre-fix pricing
    disclosure, for one) — rendered under the header, before any table.
    """

    generated_at: str
    today: tuple[OpsStat, ...]
    tables: tuple[OpsTable, ...]
    notes: tuple[str, ...] = ()


def build_ops_view(data: OpsData) -> OpsView:
    """Shape the loaded aggregates into the page: headline stats, then tables."""
    total_cost = sum(row.cost for row in data.stage_model)
    per_report = (
        _usd(total_cost / data.report_count) if data.report_count else "—"
    )
    return OpsView(
        generated_at=(
            f"generated {data.now.strftime('%Y-%m-%d %H:%M')} UTC · "
            "all days are UTC days"
        ),
        today=(
            OpsStat(
                label="public fresh analyses today",
                value=f"{data.admissions_today}",
                note=(
                    "resets midnight UTC — the operator's unlocked runs are "
                    "not counted"
                ),
            ),
            OpsStat(
                label="settled LLM spend today",
                value=_usd(data.spend_today_usd),
                note=f"runaway-day backstop at {_usd(data.daily_spend_backstop_usd)}",
            ),
            OpsStat(
                label="reports published",
                value=f"{data.report_count:,}",
                note="all time, this store",
            ),
            OpsStat(
                label="LLM spend per report",
                value=per_report,
                note="all-time spend ÷ published reports — failed jobs included",
            ),
        ),
        tables=(
            _jobs_table(data.jobs),
            _daily_table(data.daily_ledger, data.daily_admissions, data.daily_refusals),
            _stage_model_table(data.stage_model),
            _latency_table(data.stage_latencies),
        ),
        notes=(
            f"fresh analyses are capped at {data.per_ip_daily_job_limit} per "
            f"visitor IP a day, inside one pooled allowance of "
            f"{data.daily_job_limit} per UTC day",
            "ledger rows from before 2026-08-09 are priced without the provider's "
            "prefix-cache discount — overstated roughly 4-5x against the real bill, "
            "left as written (forward-only ruling); the provider dashboard is "
            "billing truth",
        ),
    )


def _jobs_table(jobs: tuple[JobRow, ...]) -> OpsTable:
    """The job history — every analysis run, its outcome, and what it cost.

    The LLMOps trace table: one row per job with duration, the banked classify
    counts, and the ledger-joined attributed cost. A never-settled row renders
    ``running`` (or is the honest trace of a process death). Error *text*
    deliberately never renders — this page is public, and raw exception
    strings can leak internals; the outcome column says failed, the operator
    reads the journal for why.
    """
    return OpsTable(
        title="jobs (newest 20)",
        headers=(
            "started (UTC)", "game", "outcome", "duration",
            "labeled", "reused", "cost",
        ),
        rows=tuple(
            (
                job.started_at[:16].replace("T", " "),
                job.requested_name,
                job.outcome if job.outcome is not None else "running",
                _elapsed(job.started_at, job.finished_at),
                "—" if job.labeled is None else f"{job.labeled:,}",
                "—" if job.reused is None else f"{job.reused:,}",
                _usd(job.cost),
            )
            for job in jobs
        ),
        note=(
            "reused counts verdicts served from the label pool instead of "
            "re-bought — the app-side cache economics; cost joins the ledger "
            "by the job's run id"
        ),
        text_columns=4,
    )


def _daily_table(
    ledger: tuple[DailyLedgerRow, ...],
    admissions: tuple[DailyAdmissionRow, ...],
    refusals: tuple[DailyRefusalRow, ...],
) -> OpsTable:
    """The last days' activity, newest first — the three journals merged by day.

    The union of the journals' days: a day with admissions but no settled
    calls yet (or the reverse — the operator's exempt jobs mint no admission)
    still renders, zeros worn openly.
    """
    admitted = {row.day: row.admissions for row in admissions}
    refused = {row.day: row.refusals for row in refusals}
    spent = {row.day: row for row in ledger}
    days = sorted(set(admitted) | set(refused) | set(spent), reverse=True)
    rows: list[tuple[str, ...]] = []
    for day in days:
        row = spent.get(day)
        rows.append((
            day,
            f"{admitted.get(day, 0):,}",
            f"{refused.get(day, 0):,}",
            f"{row.calls:,}" if row else "0",
            f"{row.prompt_tokens:,}" if row else "0",
            _hit_rate(row.cached_prompt_tokens, row.measured_prompt_tokens)
            if row else "—",
            f"{row.output_tokens:,}" if row else "0",
            f"{row.thinking_tokens:,}" if row else "0",
            _usd(row.cost) if row else _usd(0.0),
        ))
    return OpsTable(
        title="by day (last 14)",
        headers=(
            "day", "jobs admitted", "refusals", "LLM calls",
            "prompt tokens", "cache hit", "output tokens", "thinking tokens", "cost",
        ),
        rows=tuple(rows),
        note=(
            "admitted counts the gate's public admissions — the operator's "
            "unlocked jobs spend but are not admissions; refusals count the "
            "spend breaker's and the search limiter's firings; cache hit is "
            "the provider-side prefix-cache share of prompt tokens (— where "
            "no row recorded it)"
        ),
    )


def _stage_model_table(stage_model: tuple[StageModelRow, ...]) -> OpsTable:
    """All-time totals per (stage, model), costliest first — the unit-economics split."""
    return OpsTable(
        title="by stage and model (all time)",
        headers=(
            "stage", "model", "calls",
            "prompt tokens", "cache hit", "output tokens", "thinking tokens", "cost",
        ),
        rows=tuple(
            (
                row.stage,
                row.model,
                f"{row.calls:,}",
                f"{row.prompt_tokens:,}",
                _hit_rate(row.cached_prompt_tokens, row.measured_prompt_tokens),
                f"{row.output_tokens:,}",
                f"{row.thinking_tokens:,}",
                _usd(row.cost),
            )
            for row in stage_model
        ),
        note=(
            "cache hit computes over rows that recorded the split "
            "(post-2026-08-09) — earlier rows never measured it"
        ),
        text_columns=2,
    )


def _latency_table(latencies: tuple[StageLatencyRow, ...]) -> OpsTable:
    """Per-stage call latency percentiles over the measured ledger rows."""
    return OpsTable(
        title="call latency by stage",
        headers=("stage", "measured calls", "p50", "p95"),
        rows=tuple(
            (
                row.stage,
                f"{row.calls:,}",
                f"{row.p50_s:.1f}s",
                f"{row.p95_s:.1f}s",
            )
            for row in latencies
        ),
        note="dispatch-to-response wall clock per LLM call, retries included",
    )


def _hit_rate(cached: int, measured_prompt: int) -> str:
    """The prefix-cache share over the *measured* prompt volume.

    "—" when no row in the group recorded the split (pre-step-6 rows carry
    no measurement) — an unrecorded split must never render as 0% hit.
    """
    return f"{cached / measured_prompt:.0%}" if measured_prompt else "—"


def _elapsed(started_at: str, finished_at: str | None) -> str:
    """A finished job's wall-clock span as "3m 12s" — "—" while unfinished."""
    if finished_at is None:
        return "—"
    seconds = int(
        (
            datetime.fromisoformat(finished_at) - datetime.fromisoformat(started_at)
        ).total_seconds()
    )
    return f"{seconds // 60}m {seconds % 60:02d}s"


def _usd(amount: float) -> str:
    """Dollars at four decimals — the runner narrates job cost the same way,
    and a single classify call is fractions of a cent.

    >>> _usd(0.1101)
    '$0.1101'
    """
    return f"${amount:,.4f}"
