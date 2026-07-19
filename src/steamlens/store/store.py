"""The one owner of the SQLite file — connection, pragmas, migrations, surfaces.

``Store`` opens the file exactly once, brings it to the current schema, and
hands its connection to small tenant surfaces exposed as attributes: the
durable ``classify_cache``/``spend_ledger`` pair binds into the LLM client's
constructor slots (the client never learns SQLite exists), ``reviews`` holds
the corpus snapshot and the driver's selection query, ``labels`` is the label
pool. One owner, dumb tenants: pragmas and migrations run once per open
instead of once per surface, and "which connection has WAL set" stays a
single fact.

The store adds no locking of its own: the client already serializes every
cache and ledger touch under its one lock, and transactions never share a
connection across threads by design — the labeling driver opens TWO ``Store``
instances over the one file (the client's cache/ledger on one connection from
worker threads, all label-pool writes on the other from its main thread),
because a transaction is connection-scoped and a shared connection would let a
worker's cache write land inside an open envelope transaction. WAL plus the
busy timeout is what coordinates the two writers (C1 driver design, DESIGN
2026-07-19); they remain the safety net for any genuinely unexpected third.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import TracebackType

from steamlens.store.cache import SqliteClassifyCache
from steamlens.store.labels import LabelPool
from steamlens.store.ledger import SqliteSpendLedger
from steamlens.store.reviews import ReviewStore
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
        # 60s, sized to bursts, not to writes: a write takes milliseconds, but
        # SQLite's busy-wait is unfair polling, and the C1 cache-banking flood
        # (~300 envelope txns/s against the client connection's writes) starved
        # a waiter past the old 5s on sheer arrival density (2026-07-20, census
        # tranche 3). Capacity has order-of-magnitude slack — the queue always
        # drains; if a lock ever recurs at 60s, the escalation is batching
        # envelope writes per outcome, not more patience.
        self._conn.execute("PRAGMA busy_timeout = 60000")
        apply_migrations(self._conn)
        self.classify_cache = SqliteClassifyCache(self._conn)
        self.spend_ledger = SqliteSpendLedger(self._conn)
        self.reviews = ReviewStore(self._conn)
        self.labels = LabelPool(self._conn)

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
