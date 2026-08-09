"""The ops surface's read model — aggregate answers over the journals others write.

The observability step's store tenant (DESIGN: monitoring — "the richer
observability … is the in-app ops dashboard reading the same store"): a
read-only surface whose whole responsibility is shaping the append-only
journals (`spend_ledger`, `admissions`, `reports`) into the aggregate rows
the ops page displays — spend and volume by day, by stage and model, and the
published-report count. It lives beside the writing tenants rather than on
them because grouping-for-display is a different responsibility than
insert-and-ask; the writers keep their two-method discipline. The rows are
contract types (``contracts.ops``) because the web renderer is the consumer,
and that seam speaks contracts only.

Aggregates only, by rule: the security audit's hard constraint is that raw
client IPs never reach a rendered page, so no query here ever selects the
admissions journal's `client_ip` column — the shape of the surface enforces
what the page must not show. Day keys are the UTC date prefix of the stored
ISO-8601 timestamps (writes normalize to UTC, so the string prefix IS the
UTC day, and the grouping stays an index-range scan plus a group-by).
"""

from __future__ import annotations

import math
import sqlite3
from collections import defaultdict
from datetime import datetime

from steamlens.contracts import (
    DailyAdmissionRow,
    DailyLedgerRow,
    DailyRefusalRow,
    JobRow,
    StageLatencyRow,
    StageModelRow,
)
from steamlens.store.convert import utc_isoformat

# The step-6 accounting marker: a recorded duration exists exactly on rows
# written since the observability step, which also recorded the cache split —
# so "measured" prompt volume is the cache-hit rate's honest denominator
# (pre-step-6 rows never recorded their split and must not read as 0% hit).
_MEASURED_PROMPT = "SUM(CASE WHEN duration_s IS NOT NULL THEN prompt_tokens ELSE 0 END)"


class OpsReads:
    """Table-backed ops aggregates, constructed by ``Store`` with its connection.

    >>> from datetime import UTC, datetime
    >>> from steamlens.store import Store
    >>> store = Store(":memory:")
    >>> store.admissions.record("203.0.113.7", 440, at=datetime(2026, 8, 8, tzinfo=UTC))
    >>> store.ops.daily_admissions(datetime(2026, 8, 1, tzinfo=UTC))
    (DailyAdmissionRow(day='2026-08-08', admissions=1),)
    >>> store.close()
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def daily_ledger(self, since: datetime) -> tuple[DailyLedgerRow, ...]:
        """Per-UTC-day call/token/cost totals at or after ``since``, newest day first."""
        rows = self._conn.execute(
            "SELECT substr(created_at, 1, 10) AS day, COUNT(*),"
            " SUM(prompt_tokens), SUM(cached_prompt_tokens), " + _MEASURED_PROMPT + ","
            " SUM(output_tokens), SUM(thinking_tokens), SUM(cost)"
            " FROM spend_ledger WHERE created_at >= ?"
            " GROUP BY day ORDER BY day DESC",
            (utc_isoformat(since),),
        ).fetchall()
        return tuple(
            DailyLedgerRow(
                day=day,
                calls=int(calls),
                prompt_tokens=int(prompt),
                cached_prompt_tokens=int(cached),
                measured_prompt_tokens=int(measured),
                output_tokens=int(output),
                thinking_tokens=int(thinking),
                cost=float(cost),
            )
            for day, calls, prompt, cached, measured, output, thinking, cost in rows
        )

    def stage_model_totals(self) -> tuple[StageModelRow, ...]:
        """All-time call/token/cost totals per (stage, model), costliest first."""
        rows = self._conn.execute(
            "SELECT stage, model, COUNT(*),"
            " SUM(prompt_tokens), SUM(cached_prompt_tokens), " + _MEASURED_PROMPT + ","
            " SUM(output_tokens), SUM(thinking_tokens), SUM(cost)"
            " FROM spend_ledger GROUP BY stage, model ORDER BY SUM(cost) DESC",
        ).fetchall()
        return tuple(
            StageModelRow(
                stage=stage,
                model=model,
                calls=int(calls),
                prompt_tokens=int(prompt),
                cached_prompt_tokens=int(cached),
                measured_prompt_tokens=int(measured),
                output_tokens=int(output),
                thinking_tokens=int(thinking),
                cost=float(cost),
            )
            for stage, model, calls, prompt, cached, measured, output, thinking, cost in rows
        )

    def daily_admissions(self, since: datetime) -> tuple[DailyAdmissionRow, ...]:
        """Per-UTC-day gated admission counts at or after ``since``, newest day first."""
        rows = self._conn.execute(
            "SELECT substr(created_at, 1, 10) AS day, COUNT(*)"
            " FROM admissions WHERE created_at >= ?"
            " GROUP BY day ORDER BY day DESC",
            (utc_isoformat(since),),
        ).fetchall()
        return tuple(
            DailyAdmissionRow(day=day, admissions=int(count)) for day, count in rows
        )

    def daily_refusals(self, since: datetime) -> tuple[DailyRefusalRow, ...]:
        """Per-UTC-day gate refusal counts at or after ``since``, newest day first."""
        rows = self._conn.execute(
            "SELECT substr(created_at, 1, 10) AS day, COUNT(*)"
            " FROM refusals WHERE created_at >= ?"
            " GROUP BY day ORDER BY day DESC",
            (utc_isoformat(since),),
        ).fetchall()
        return tuple(
            DailyRefusalRow(day=day, refusals=int(count)) for day, count in rows
        )

    def recent_jobs(self, limit: int) -> tuple[JobRow, ...]:
        """The newest ``limit`` journaled jobs with their ledger-joined cost.

        The cost subquery scans the ledger per job — fine at a history-table
        limit over this store's row counts; an index on the ledger's run_id
        is the known escalation if a bigger read ever wants this join.
        """
        rows = self._conn.execute(
            "SELECT j.run_id, j.app_id, j.requested_name, j.started_at,"
            " j.finished_at, j.outcome, j.error, j.labeled, j.reused,"
            " j.failed_durable, j.refused_batches,"
            " COALESCE((SELECT SUM(cost) FROM spend_ledger l"
            "           WHERE l.run_id = j.run_id), 0.0)"
            " FROM jobs j ORDER BY j.started_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return tuple(
            JobRow(
                run_id=run_id,
                app_id=int(app_id),
                requested_name=requested_name,
                started_at=started_at,
                finished_at=finished_at,
                outcome=outcome,
                error=error,
                labeled=None if labeled is None else int(labeled),
                reused=None if reused is None else int(reused),
                failed_durable=None if failed_durable is None else int(failed_durable),
                refused_batches=None if refused is None else int(refused),
                cost=float(cost),
            )
            for (
                run_id, app_id, requested_name, started_at, finished_at,
                outcome, error, labeled, reused, failed_durable, refused, cost,
            ) in rows
        )

    def stage_latencies(self) -> tuple[StageLatencyRow, ...]:
        """Per-stage latency percentiles over the measured ledger rows, slowest p95 first.

        Percentiles compute in Python by nearest rank — SQLite has no
        percentile builtin, and the measured-row volume here is a fetch a
        page load cannot feel. Pre-step-6 rows carry no duration and simply
        do not participate.
        """
        durations: defaultdict[str, list[float]] = defaultdict(list)
        for stage, duration in self._conn.execute(
            "SELECT stage, duration_s FROM spend_ledger WHERE duration_s IS NOT NULL"
        ):
            durations[stage].append(float(duration))
        summaries = tuple(
            StageLatencyRow(
                stage=stage,
                calls=len(values),
                p50_s=_nearest_rank(sorted(values), 0.50),
                p95_s=_nearest_rank(sorted(values), 0.95),
            )
            for stage, values in durations.items()
        )
        return tuple(sorted(summaries, key=lambda row: -row.p95_s))

    def report_count(self) -> int:
        """How many analyses have ever published a report — the unit-economics denominator."""
        row = self._conn.execute("SELECT COUNT(*) FROM reports").fetchone()
        return int(row[0])


def _nearest_rank(ordered: list[float], quantile: float) -> float:
    """The nearest-rank percentile over an already-sorted, non-empty list.

    >>> _nearest_rank([1.0, 2.0, 3.0, 4.0], 0.5)
    2.0
    """
    rank = max(1, math.ceil(quantile * len(ordered)))
    return ordered[rank - 1]
