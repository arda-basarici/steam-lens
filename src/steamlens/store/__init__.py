"""The persistence shell — one SQLite file behind small typed surfaces.

The public surface: ``Store`` owns the file (connection, pragmas, the
one-step migration runner in ``schema``) and exposes the tenant surfaces as
attributes — the durable ``SqliteClassifyCache``/``SqliteSpendLedger`` pair
that binds into the LLM client's constructor slots where the in-memory pair
binds for tests, ``ReviewStore`` (the corpus snapshot and the labeling
driver's selection query), and ``LabelPool`` (envelopes, mentions, runs,
failure marks). Typed failures in ``errors``. Design record: DESIGN.md's two
``store`` operational-decisions entries (2026-07-14).
"""

from steamlens.store.cache import SqliteClassifyCache
from steamlens.store.errors import SchemaVersionError, StoreDataError, StoreError
from steamlens.store.labels import LabelPool
from steamlens.store.ledger import SqliteSpendLedger
from steamlens.store.reviews import ReviewStore
from steamlens.store.store import Store

__all__ = [
    # the owner
    "Store",
    # the durable protocol pair
    "SqliteClassifyCache",
    "SqliteSpendLedger",
    # the record surfaces
    "ReviewStore",
    "LabelPool",
    # errors
    "StoreError",
    "SchemaVersionError",
    "StoreDataError",
]
