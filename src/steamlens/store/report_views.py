"""The report-view journal — how often a published report answers again.

One row per report-page render, keyed by the publication's run id (the same
key the ledger and the job journal carry, so a job's view count is a join,
not an inference). This is the report-reuse economics the ops page shows:
every view after the first is an analysis delivered without a new job or a
cent of spend. Deliberately no IP and no user-agent column, same
shape-enforced rule as the admissions journal — the count is identity-blind
by construction, crawlers and the operator included. Append-and-ask like the
ledger; timestamps UTC-normalized at write so day grouping stays an
index-range scan.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from steamlens.store.convert import utc_isoformat


class ReportViewLog:
    """Table-backed view journal, constructed by ``Store`` with its connection.

    >>> from datetime import UTC, datetime
    >>> from steamlens.store import Store
    >>> store = Store(":memory:")
    >>> store.report_views.record("serve-1", at=datetime(2026, 8, 14, tzinfo=UTC))
    >>> store.close()
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def record(self, run_id: str, *, at: datetime) -> None:
        """Journal one report-page render. Append-only — a view is never revised."""
        self._conn.execute(
            "INSERT INTO report_views (created_at, run_id) VALUES (?, ?)",
            (utc_isoformat(at), run_id),
        )
