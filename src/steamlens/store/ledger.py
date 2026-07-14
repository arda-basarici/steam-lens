"""The durable ``SpendLedger`` binding — the journal whose rows ARE the counters.

Daily-quota and budget reads are derived by querying these rows, never trusted
to an in-memory tally, so they survive restarts by construction (DESIGN:
`llm_client` concurrency, persistence, errors). The surface is insert-and-ask
only — no update, no delete — because a ledger entry is never revised.
Timestamps are normalized to UTC text at write (see ``convert``), which is
what lets the ``since`` filters run as plain string comparisons over the
``created_at`` indexes. Not thread-safe on its own by the same discipline as
the cache: the client's lock serializes every touch.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from steamlens.contracts import SpendRecord
from steamlens.store.convert import utc_isoformat


class SqliteSpendLedger:
    """Table-backed ``SpendLedger`` — satisfies the protocol structurally.

    Constructed by ``Store`` with the store's connection; never opens or owns
    one itself.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def append(self, entry: SpendRecord) -> None:
        """Journal one paid call. Append-only — a ledger entry is never revised."""
        self._conn.execute(
            "INSERT INTO spend_ledger (created_at, stage, model, model_version,"
            " prompt_tokens, output_tokens, thinking_tokens, cost)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                utc_isoformat(entry.created_at),
                entry.stage,
                entry.model,
                entry.model_version,
                entry.usage.prompt_tokens,
                entry.usage.output_tokens,
                entry.usage.thinking_tokens,
                entry.cost,
            ),
        )

    def request_count_since(self, model: str, since: datetime) -> int:
        """Calls made to ``model`` (the requested name) at or after ``since`` — the quota read."""
        row = self._conn.execute(
            "SELECT COUNT(*) FROM spend_ledger WHERE model = ? AND created_at >= ?",
            (model, utc_isoformat(since)),
        ).fetchone()
        return int(row[0])

    def cost_since(self, since: datetime) -> float:
        """Total USD spent across all models at or after ``since`` — the budget read."""
        row = self._conn.execute(
            "SELECT COALESCE(SUM(cost), 0.0) FROM spend_ledger WHERE created_at >= ?",
            (utc_isoformat(since),),
        ).fetchone()
        return float(row[0])
