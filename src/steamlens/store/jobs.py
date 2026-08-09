"""The job journal — job outcomes that survive the queue's memory.

The observability step's load-bearing gap (DESIGN: the job journal): jobs
lived only in queue memory, so a failure vanished on restart and the store
could not answer "how many jobs failed this week and why." One row per job,
keyed by the run id minted before the pipeline starts — the same key the
report row and the ledger's attribution carry, so cost-per-job is a join,
never an inference.

Deliberately the store's first settle-by-UPDATE tenant: a job row is a
lifecycle record, not a ledger entry — ``start`` inserts it, ``settle``
completes it, and a row started but never settled is the honest trace of a
process death mid-job (never backfilled, never cleaned up). Settling a row
that was never started is a caller bug and fails loud.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from steamlens.store.convert import utc_isoformat
from steamlens.store.errors import StoreError


class JobLog:
    """Table-backed job journal, constructed by ``Store`` with its connection.

    >>> from datetime import UTC, datetime
    >>> from steamlens.store import Store
    >>> store = Store(":memory:")
    >>> at = datetime(2026, 8, 9, tzinfo=UTC)
    >>> store.jobs.start("serve-1", 440, "Team Fortress 2", at=at)
    >>> store.jobs.settle(
    ...     "serve-1", at=at, outcome="done", error=None,
    ...     labeled=120, reused=30, failed_durable=1, refused_batches=0,
    ...     stage_timings_json=None,
    ... )
    >>> store.close()
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def start(
        self, run_id: str, app_id: int, requested_name: str, *, at: datetime
    ) -> None:
        """Journal a job the moment it starts running — before any money moves."""
        try:
            self._conn.execute(
                "INSERT INTO jobs (run_id, app_id, requested_name, started_at)"
                " VALUES (?, ?, ?, ?)",
                (run_id, app_id, requested_name, utc_isoformat(at)),
            )
        except sqlite3.IntegrityError as exc:
            raise StoreError(f"job {run_id!r} already journaled") from exc

    def settle(
        self,
        run_id: str,
        *,
        at: datetime,
        outcome: str,
        error: str | None,
        labeled: int | None,
        reused: int | None,
        failed_durable: int | None,
        refused_batches: int | None,
        stage_timings_json: str | None,
    ) -> None:
        """Complete the row: outcome, error, the banked counts, the derived timings.

        The counts are ``None`` when the pipeline aborted before producing
        them — an honest "unknown", not a zero. Raises ``StoreError`` on a
        run id never started: settlement without a start is a wiring bug,
        and updating zero rows silently would bury it.
        """
        cursor = self._conn.execute(
            "UPDATE jobs SET finished_at = ?, outcome = ?, error = ?,"
            " labeled = ?, reused = ?, failed_durable = ?, refused_batches = ?,"
            " stage_timings_json = ?"
            " WHERE run_id = ?",
            (
                utc_isoformat(at),
                outcome,
                error,
                labeled,
                reused,
                failed_durable,
                refused_batches,
                stage_timings_json,
                run_id,
            ),
        )
        if cursor.rowcount == 0:
            raise StoreError(f"job {run_id!r} was never started — cannot settle")
