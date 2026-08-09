"""The refusal journal — how often the spend breaker actually fires.

One row per gate refusal: the instant and which guard fired (``in_flight`` ·
``day_cap`` · ``backstop`` — the gate owns the vocabulary; this table just
records it). Deliberately no IP column, same shape-enforced rule as the
admissions journal: the ops surface renders counts, and a column that does
not exist cannot leak. Append-and-ask like the ledger; timestamps
UTC-normalized at write so day grouping stays an index-range scan.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from steamlens.store.convert import utc_isoformat


class RefusalLog:
    """Table-backed refusal journal, constructed by ``Store`` with its connection.

    >>> from datetime import UTC, datetime
    >>> from steamlens.store import Store
    >>> store = Store(":memory:")
    >>> store.refusals.record("day_cap", at=datetime(2026, 8, 9, tzinfo=UTC))
    >>> store.close()
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def record(self, kind: str, *, at: datetime) -> None:
        """Journal one refusal. Append-only — a refusal is never revised."""
        self._conn.execute(
            "INSERT INTO refusals (created_at, kind) VALUES (?, ?)",
            (utc_isoformat(at), kind),
        )
