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

from steamlens.store.errors import StoreError


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
        """Archive ``raw_response`` under ``key`` — the first write wins, forever.

        This binding is the provenance record of unreproducible provider
        output, so a *differing* second write raises ``StoreError`` instead
        of silently destroying the archived body — the same fail-loud rule
        every other durable conflict in the store follows. An identical
        re-put is a no-op, so a caller re-offering the same body (a crash
        between put and journal) stays safe.
        """
        existing = self.get(key)
        if existing is not None:
            if existing != raw_response:
                raise StoreError(
                    f"archive key {key!r} already holds a different body — "
                    "refusing to overwrite the provenance record"
                )
            return
        self._conn.execute(
            "INSERT INTO classify_cache (key, raw_response) VALUES (?, ?)",
            (key, raw_response),
        )
