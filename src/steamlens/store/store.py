"""The one owner of the SQLite file — connection, pragmas, migrations, surfaces.

``Store`` opens the file exactly once, brings it to the current schema, and
hands its connection to small tenant surfaces exposed as attributes — the
durable ``classify_cache``/``spend_ledger`` pair binds into the LLM client's
constructor slots, so the client never learns SQLite exists. One owner, dumb
tenants: pragmas and migrations run once per open instead of once per surface,
and "which connection has WAL set" stays a single fact.

The store adds no locking of its own: the client already serializes every
cache and ledger touch under its one lock, and the labeling driver is
sequential by config default. WAL plus the busy timeout is the safety net for
an unexpected second connection, not the concurrency design.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import TracebackType

from steamlens.store.cache import SqliteClassifyCache
from steamlens.store.ledger import SqliteSpendLedger
from steamlens.store.schema import apply_migrations


class Store:
    """The opened store: one connection, migrated schema, tenant surfaces.

    Construction connects, sets the pragmas (WAL journal, foreign keys on,
    a 5s busy timeout), and runs the migration runner — so holding a ``Store``
    means holding a file at the current schema version; a file written by newer
    code fails here, before any query. Usable as a context manager; ``close``
    is idempotent. ``":memory:"`` works for throwaway stores (WAL quietly
    degrades to a memory journal there).

    >>> store = Store(":memory:")
    >>> store.classify_cache.get("missing") is None
    True
    >>> store.classify_cache.put("k", '{"answer": 42}')
    >>> store.classify_cache.get("k")
    '{"answer": 42}'
    >>> store.close()
    """

    def __init__(self, db_path: str | Path) -> None:
        # autocommit=True: single statements commit themselves; multi-statement
        # atomicity (migrations, the envelope+mentions write) uses explicit
        # BEGIN/COMMIT, never the module's implicit transaction management.
        self._conn = sqlite3.connect(db_path, check_same_thread=False, autocommit=True)
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA busy_timeout = 5000")
        apply_migrations(self._conn)
        self.classify_cache = SqliteClassifyCache(self._conn)
        self.spend_ledger = SqliteSpendLedger(self._conn)

    def close(self) -> None:
        """Close the underlying connection; the instance is unusable afterwards."""
        self._conn.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
