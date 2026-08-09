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

import sqlite3
from datetime import datetime

from steamlens.contracts import DailyAdmissionRow, DailyLedgerRow, StageModelRow
from steamlens.store.convert import utc_isoformat


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
            " SUM(prompt_tokens), SUM(cached_prompt_tokens),"
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
                output_tokens=int(output),
                thinking_tokens=int(thinking),
                cost=float(cost),
            )
            for day, calls, prompt, cached, output, thinking, cost in rows
        )

    def stage_model_totals(self) -> tuple[StageModelRow, ...]:
        """All-time call/token/cost totals per (stage, model), costliest first."""
        rows = self._conn.execute(
            "SELECT stage, model, COUNT(*),"
            " SUM(prompt_tokens), SUM(cached_prompt_tokens),"
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
                output_tokens=int(output),
                thinking_tokens=int(thinking),
                cost=float(cost),
            )
            for stage, model, calls, prompt, cached, output, thinking, cost in rows
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

    def report_count(self) -> int:
        """How many analyses have ever published a report — the unit-economics denominator."""
        row = self._conn.execute("SELECT COUNT(*) FROM reports").fetchone()
        return int(row[0])
