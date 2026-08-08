"""The submit gate's admission journal — the daily count that survives restarts.

One row per gated fresh-job admission (the spend-breaker design): the gate
counts jobs at the moment of admission, not dollars at settle time, so the
day's allowance cannot be burst past while costs are still in flight. The
rows exist for exactly two readers — the gate's daily-count refusal and the
ops "did anything happen today" surface — which is why the table is not a
general access log: attaches never land here (no new spend), and the
operator's own unlocked admissions stay outside the public day's count.

Same discipline as the spend ledger: append-and-ask only, timestamps
UTC-normalized at write so the ``since`` filter runs as an index-range scan,
and no locking of its own (the serving gate's writes arrive one per admitted
job, serialized by the store's WAL + busy timeout).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from steamlens.store.convert import utc_isoformat


class AdmissionLog:
    """Table-backed admission journal, constructed by ``Store`` with its connection.

    >>> from steamlens.store import Store
    >>> from datetime import UTC, datetime
    >>> store = Store(":memory:")
    >>> day = datetime(2026, 8, 8, tzinfo=UTC)
    >>> store.admissions.record("203.0.113.7", 440, at=day)
    >>> store.admissions.count_since(day)
    1
    >>> store.close()
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def record(self, client_ip: str, app_id: int, *, at: datetime) -> None:
        """Journal one admitted fresh job. Append-only — an admission is never revised."""
        self._conn.execute(
            "INSERT INTO admissions (created_at, client_ip, app_id) VALUES (?, ?, ?)",
            (utc_isoformat(at), client_ip, app_id),
        )

    def count_since(self, since: datetime) -> int:
        """Admissions at or after ``since`` — the gate's daily-allowance read."""
        row = self._conn.execute(
            "SELECT COUNT(*) FROM admissions WHERE created_at >= ?",
            (utc_isoformat(since),),
        ).fetchone()
        return int(row[0])
