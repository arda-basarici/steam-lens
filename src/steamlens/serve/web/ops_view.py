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

from steamlens.contracts import DailyAdmissionRow, DailyLedgerRow, StageModelRow


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
    spend_today_usd: float
    daily_spend_backstop_usd: float
    daily_ledger: tuple[DailyLedgerRow, ...]
    daily_admissions: tuple[DailyAdmissionRow, ...]
    stage_model: tuple[StageModelRow, ...]
    report_count: int


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
    """Everything ``ops.html`` renders, in page order."""

    generated_at: str
    today: tuple[OpsStat, ...]
    tables: tuple[OpsTable, ...]


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
                label="fresh analyses today",
                value=f"{data.admissions_today} of {data.daily_job_limit}",
                note="the public daily allowance — resets at midnight UTC",
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
            _daily_table(data.daily_ledger, data.daily_admissions),
            _stage_model_table(data.stage_model),
        ),
    )


def _daily_table(
    ledger: tuple[DailyLedgerRow, ...], admissions: tuple[DailyAdmissionRow, ...]
) -> OpsTable:
    """The last days' activity, newest first — ledger and admissions merged by day.

    The union of both journals' days: a day with admissions but no settled
    calls yet (or the reverse — the operator's exempt jobs mint no admission)
    still renders, zeros worn openly.
    """
    admitted = {row.day: row.admissions for row in admissions}
    spent = {row.day: row for row in ledger}
    days = sorted(set(admitted) | set(spent), reverse=True)
    rows: list[tuple[str, ...]] = []
    for day in days:
        row = spent.get(day)
        rows.append((
            day,
            f"{admitted.get(day, 0):,}",
            f"{row.calls:,}" if row else "0",
            f"{row.prompt_tokens:,}" if row else "0",
            f"{row.output_tokens:,}" if row else "0",
            f"{row.thinking_tokens:,}" if row else "0",
            _usd(row.cost) if row else _usd(0.0),
        ))
    return OpsTable(
        title="by day (last 14)",
        headers=(
            "day", "jobs admitted", "LLM calls",
            "prompt tokens", "output tokens", "thinking tokens", "cost",
        ),
        rows=tuple(rows),
        note=(
            "admitted counts the gate's public admissions — the operator's "
            "unlocked jobs spend but are not admissions"
        ),
    )


def _stage_model_table(stage_model: tuple[StageModelRow, ...]) -> OpsTable:
    """All-time totals per (stage, model), costliest first — the unit-economics split."""
    return OpsTable(
        title="by stage and model (all time)",
        headers=(
            "stage", "model", "calls",
            "prompt tokens", "output tokens", "thinking tokens", "cost",
        ),
        rows=tuple(
            (
                row.stage,
                row.model,
                f"{row.calls:,}",
                f"{row.prompt_tokens:,}",
                f"{row.output_tokens:,}",
                f"{row.thinking_tokens:,}",
                _usd(row.cost),
            )
            for row in stage_model
        ),
        note="failure rates and latency join with the job journal (in design)",
        text_columns=2,
    )


def _usd(amount: float) -> str:
    """Dollars at four decimals — the runner narrates job cost the same way,
    and a single classify call is fractions of a cent.

    >>> _usd(0.1101)
    '$0.1101'
    """
    return f"${amount:,.4f}"
