"""The persistence shell — one SQLite file behind small typed surfaces.

The public surface: ``Store`` owns the file (connection, pragmas, the
one-step migration runner in ``schema``) and exposes the tenant surfaces as
attributes — the durable ``SqliteResponseArchive``/``SqliteSpendLedger`` pair
that binds into the LLM client's constructor slots where the in-memory pair
binds for tests, ``ReviewStore`` (the corpus snapshot and the labeling
driver's selection query), ``LabelPool`` (envelopes, mentions, runs,
failure marks), ``EvalRunLog`` (the certification journal —
``eval_runs``/``eval_metrics``, the runs of record the CI gate regenerates),
``SampleManifest`` (the serving runs' stored sample memberships),
``ReportLog`` (published analyses: report rows plus their frozen aggregate
snapshots), and ``OpsReads`` (the ops page's read-only aggregates — its row
dataclasses live in ``contracts.ops``, the renderer's seam). Typed failures
in ``errors``. Design record: the store decisions
in DESIGN's labeling-engine section (settled 2026-07-14) and the serving-
persistence section (the report layer, designed 2026-08-08).
"""

from steamlens.store.archive import SqliteResponseArchive
from steamlens.store.convert import parse_utc_isoformat, utc_isoformat
from steamlens.store.errors import SchemaVersionError, StoreDataError, StoreError
from steamlens.store.eval_runs import EvalRunLog
from steamlens.store.labels import LabelPool
from steamlens.store.ledger import SqliteSpendLedger
from steamlens.store.ops import OpsReads
from steamlens.store.reports import ReportLog
from steamlens.store.reviews import ReviewStore
from steamlens.store.samples import SampleManifest
from steamlens.store.store import Store

__all__ = [
    # the owner
    "Store",
    # the durable protocol pair
    "SqliteResponseArchive",
    "SqliteSpendLedger",
    # the record surfaces
    "ReviewStore",
    "LabelPool",
    "EvalRunLog",
    "SampleManifest",
    "ReportLog",
    # the ops read model (row dataclasses live in contracts.ops)
    "OpsReads",
    # the canonical timestamp codec (the CI fixture exporter's handshake)
    "utc_isoformat",
    "parse_utc_isoformat",
    # errors
    "StoreError",
    "SchemaVersionError",
    "StoreDataError",
]
