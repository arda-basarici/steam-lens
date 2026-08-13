"""View models for the ops page — journal aggregates shaped for the template.

The observability step's rendering half (DESIGN: monitoring — "the richer
observability … is the in-app ops dashboard reading the same store, a product
page rather than infrastructure"): pure builders, loaded aggregates in,
display records out, same discipline as the report page's ``view``. The page
is public read-only by ruling (2026-08-09): a portfolio app's ops surface is
itself on display, so it renders aggregates a visitor may see — and the input
rows are aggregate by construction (``contracts.ops``), so there is no raw
IP here to leak.

The vocabulary is deliberate LLMOps: cost per call and per report, cache
leverage, per-stage latency, the day's allowance against the spend breaker —
the platform concepts told natively over the app's own journals. The layout
is progressive disclosure (the 2026-08-14 simplification pass, off external
reader feedback that the page read as a diagnostics dump): the default view
leads with the headline stats and three lean tables, and the accounting
methodology folds into one collapsed about block instead of captioning every
table. Token-level splits stay in the ledger journal; the page renders the
rates and unit costs they produce.
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
    text_columns: int = 1
    """How many leading columns hold text — the template left-aligns these
    and right-aligns the numeric rest (the tabular-comparison convention)."""


@dataclass(frozen=True, slots=True)
class OpsView:
    """Everything ``ops.html`` renders, in page order.

    ``limits`` is the one always-visible policy line under the stat plate —
    the caps a visitor is actually subject to. ``about`` is the methodology
    fine print (the repricing disclosure, cache-hit semantics, what "reused"
    counts), rendered collapsed so the page leads with numbers and keeps its
    provenance one click away.
    """

    generated_at: str
    today: tuple[OpsStat, ...]
    limits: str
    tables: tuple[OpsTable, ...]
    about: tuple[str, ...]


def build_ops_view(data: OpsData) -> OpsView:
    """Shape the loaded aggregates into the page: stats, tables, fine print."""
    total_cost = sum(row.cost for row in data.stage_model)
    per_report = (
        _usd(total_cost / data.report_count) if data.report_count else "—"
    )
    return OpsView(
        generated_at=f"generated {data.now.strftime('%Y-%m-%d %H:%M')} UTC",
        today=(
            OpsStat(
                label="public fresh analyses today",
                value=f"{data.admissions_today}",
                note="resets midnight UTC",
            ),
            OpsStat(
                label="settled LLM spend today",
                value=_usd(data.spend_today_usd),
                note=f"backstop at {_usd(data.daily_spend_backstop_usd)}",
            ),
            OpsStat(
                label="reports published",
                value=f"{data.report_count:,}",
                note="all time, this store",
            ),
            OpsStat(
                label="LLM spend per report",
                value=per_report,
                note="all-time spend ÷ reports",
            ),
        ),
        limits=(
            f"fresh analyses are capped at {data.per_ip_daily_job_limit} per "
            f"visitor IP a day, inside one pooled allowance of "
            f"{data.daily_job_limit} per UTC day"
        ),
        tables=(
            _jobs_table(data.jobs),
            _daily_table(data.daily_ledger, data.daily_admissions, data.daily_refusals),
            _stages_table(data.stage_model, data.stage_latencies),
        ),
        about=(
            "all days are UTC days; the operator's unlocked runs spend but "
            "are never counted as public admissions",
            "reused counts verdicts served from the app's own label pool "
            "instead of re-bought — the app-side cache economics; a job's "
            "cost joins the spend ledger by its run id, failed runs included",
            "cache hit is the provider-side prefix-cache share of prompt "
            "tokens, computed over calls measured live at write "
            "(post-2026-08-09) — a group with none reads a dash, never 0%",
            "refusals count the spend breaker's and the search limiter's "
            "firings",
            "p50/p95 are dispatch-to-response wall clock per LLM call over "
            "the live-measured calls, retries included",
            "ledger rows from before 2026-08-09 were flat-priced at write "
            "and repriced 2026-08-10 from the archive's recorded cache "
            "splits; the provider dashboard is billing truth",
            "token-level splits (prompt, cached, output, thinking) stay in "
            "the ledger journal — this page renders the rates and unit "
            "costs they produce",
        ),
    )


def _jobs_table(jobs: tuple[JobRow, ...]) -> OpsTable:
    """The job history — every analysis run, its outcome, and what it cost.

    The LLMOps trace table: one row per job with duration, the pool-reuse
    count, and the ledger-joined attributed cost. A never-settled row renders
    ``running`` (or is the honest trace of a process death). Error *text*
    deliberately never renders — this page is public, and raw exception
    strings can leak internals; the outcome column says failed, the operator
    reads the journal for why. The bought-verdict count stays journal-only
    since the simplification pass: at a glance the reuse number carries the
    cache story alone, and cost already prices the buying.
    """
    return OpsTable(
        title="recent analyses (newest 20)",
        headers=("started (UTC)", "game", "outcome", "duration", "reused", "cost"),
        rows=tuple(
            (
                job.started_at[:16].replace("T", " "),
                job.requested_name,
                job.outcome if job.outcome is not None else "running",
                _elapsed(job.started_at, job.finished_at),
                "—" if job.reused is None else f"{job.reused:,}",
                _usd(job.cost),
            )
            for job in jobs
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
            _hit_rate(row.cached_prompt_tokens, row.measured_prompt_tokens)
            if row else "—",
            _usd(row.cost) if row else _usd(0.0),
        ))
    return OpsTable(
        title="by day (last 14)",
        headers=("day", "admitted", "refused", "LLM calls", "cache hit", "cost"),
        rows=tuple(rows),
    )


def _stages_table(
    stage_model: tuple[StageModelRow, ...],
    latencies: tuple[StageLatencyRow, ...],
) -> OpsTable:
    """All-time unit economics and latency per (stage, model), costliest first.

    One row tells a stage's whole operational story — volume, cache leverage,
    cost, and how long a call takes — merging what used to be two tables over
    the same two rows. Latency summaries key by stage alone (the ledger
    measures the call, not the model split), so a stage split across models
    would repeat its percentiles per row — honest, if redundant, and not the
    current shape. A stage with no live-measured calls reads a dash.
    """
    latency_by_stage = {row.stage: row for row in latencies}
    rows: list[tuple[str, ...]] = []
    for row in stage_model:
        latency = latency_by_stage.get(row.stage)
        rows.append((
            row.stage,
            row.model,
            f"{row.calls:,}",
            _hit_rate(row.cached_prompt_tokens, row.measured_prompt_tokens),
            _usd(row.cost),
            f"{latency.p50_s:.1f}s" if latency else "—",
            f"{latency.p95_s:.1f}s" if latency else "—",
        ))
    return OpsTable(
        title="LLM stages (all time)",
        headers=("stage", "model", "calls", "cache hit", "cost", "p50", "p95"),
        rows=tuple(rows),
        text_columns=2,
    )


def _hit_rate(cached: int, measured_prompt: int) -> str:
    """The prefix-cache share over the *measured* prompt volume.

    Both inputs aggregate the live-measured rows only (``store.ops`` draws
    that line); "—" when the group has none — an unmeasured split must
    never render as 0% hit.
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
