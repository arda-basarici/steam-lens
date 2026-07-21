"""The durable ``ResponseArchive`` binding — bought responses that survive restarts.

Same contract as the in-memory binding, one difference in kind: lifetime is
the file, not the process, which is what "bought responses never re-paid" means
across runs — and, more importantly, what makes this the durable provenance
record of unreproducible provider output. Deliberately not thread-safe on its
own — the client serializes every archive touch under its one lock (the
discipline the in-memory pair documents), so this stays a dumb table.
"""

from __future__ import annotations

import sqlite3


class SqliteResponseArchive:
    """Table-backed ``ResponseArchive`` — satisfies the protocol structurally.

    Constructed by ``Store`` with the store's connection; never opens or owns
    one itself. The physical table is named ``classify_cache`` for schema
    continuity with the bought census DB; the code-level concept is the
    response archive.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get(self, key: str) -> str | None:
        """The archived raw response body under ``key``, or None on a miss."""
        row = self._conn.execute(
            "SELECT raw_response FROM classify_cache WHERE key = ?", (key,)
        ).fetchone()
        return None if row is None else str(row[0])

    def put(self, key: str, raw_response: str) -> None:
        """Store ``raw_response`` under ``key``, replacing any previous value."""
        self._conn.execute(
            "INSERT INTO classify_cache (key, raw_response) VALUES (?, ?) "
            "ON CONFLICT (key) DO UPDATE SET raw_response = excluded.raw_response",
            (key, raw_response),
        )
