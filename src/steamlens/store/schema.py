"""The schema as ordered migration steps, and the runner that applies them.

The whole schema lives here as one reviewable artifact: ``MIGRATION_STEPS`` is
an ordered tuple of steps, a step is a tuple of DDL statements, and a step's
version is its position (step N sits at index N-1) — so a version number can
never disagree with the order. ``PRAGMA user_version`` stamps how far a file
has been brought; the runner applies exactly the missing steps in one
transaction, or fails loud when the file claims a version this code has never
heard of.

The freeze rule (DESIGN: `store` scope and schema lifecycle): until the first
file holds paid data — the first corpus-labeling run — this step list may be
rewritten freely; files are disposable. After that, steps freeze append-only:
a schema change is a *new* step, never an edit to an old one, and steps stay
additive by default (``ADD COLUMN`` with a default, ``CREATE TABLE``) — a
data-rewriting step is a design smell that needs a stated reason.
"""

from __future__ import annotations

import sqlite3

from steamlens.store.errors import SchemaVersionError

# Step 1 — the full initial schema. Value vocabularies (origin, slot, sentiment,
# stage) are deliberately NOT CHECK-constrained: the read boundary re-validates
# through the enum constructors, and a CHECK would turn every enum addition into
# a migration. Structural constraints (NOT NULL, FK, UNIQUE) are the schema's job.
_STEP_1: tuple[str, ...] = (
    # The response archive (durable provenance, not a disposable cache): raw
    # provider bodies keyed by the client's content hash of (request payload +
    # model). Table name kept as classify_cache for continuity with the bought
    # census DB; the code-level type is ResponseArchive. Values replace on re-put.
    """
    CREATE TABLE classify_cache (
        key          TEXT PRIMARY KEY,
        raw_response TEXT NOT NULL
    ) WITHOUT ROWID
    """,
    # The append-only spend journal. Timestamps are ISO-8601 normalized to UTC
    # (+00:00, microsecond precision) so string order is chronological order and
    # the `since` queries stay index-range scans.
    """
    CREATE TABLE spend_ledger (
        id              INTEGER PRIMARY KEY,
        created_at      TEXT    NOT NULL,
        stage           TEXT    NOT NULL,
        model           TEXT    NOT NULL,
        model_version   TEXT    NOT NULL,
        prompt_tokens   INTEGER NOT NULL,
        output_tokens   INTEGER NOT NULL,
        thinking_tokens INTEGER NOT NULL,
        cost            REAL    NOT NULL
    )
    """,
    "CREATE INDEX idx_spend_model_created ON spend_ledger (model, created_at)",
    "CREATE INDEX idx_spend_created ON spend_ledger (created_at)",
    # One cleaned review; voted_up stores the bool as 0/1.
    """
    CREATE TABLE reviews (
        review_id  TEXT    PRIMARY KEY,
        app_id     INTEGER NOT NULL,
        created_at TEXT    NOT NULL,
        language   TEXT    NOT NULL,
        text       TEXT    NOT NULL,
        voted_up   INTEGER NOT NULL CHECK (voted_up IN (0, 1))
    ) WITHOUT ROWID
    """,
    # Provenance normalized: one run stamps thousands of envelopes with the same
    # four values, and run_id determines the rest.
    """
    CREATE TABLE runs (
        run_id       TEXT PRIMARY KEY,
        code_version TEXT NOT NULL,
        created_at   TEXT NOT NULL,
        config_hash  TEXT NOT NULL
    ) WITHOUT ROWID
    """,
    # The label pool's envelope: UNIQUE on (review, versions-triple) is the
    # never-re-paid key; origin is deliberately outside it — the same review
    # under the same versions is the same answer regardless of track.
    """
    CREATE TABLE classifications (
        id               INTEGER PRIMARY KEY,
        review_id        TEXT NOT NULL REFERENCES reviews (review_id),
        origin           TEXT NOT NULL,
        model_version    TEXT NOT NULL,
        prompt_version   TEXT NOT NULL,
        ontology_version TEXT NOT NULL,
        run_id           TEXT NOT NULL REFERENCES runs (run_id),
        UNIQUE (review_id, model_version, prompt_version, ontology_version)
    )
    """,
    """
    CREATE TABLE mentions (
        id                INTEGER PRIMARY KEY,
        classification_id INTEGER NOT NULL REFERENCES classifications (id),
        aspect            TEXT    NOT NULL,
        slot              TEXT    NOT NULL,
        sentiment         TEXT    NOT NULL,
        evidence          TEXT
    )
    """,
    "CREATE INDEX idx_mentions_classification ON mentions (classification_id)",
    # Unclassifiable-under-this-version marks — precisely not envelopes (an
    # empty-mentions envelope means "processed, found nothing"). Keyed by the
    # same versions triple, so a prompt bump correctly reopens failed reviews.
    """
    CREATE TABLE classification_failures (
        id               INTEGER PRIMARY KEY,
        review_id        TEXT NOT NULL REFERENCES reviews (review_id),
        model_version    TEXT NOT NULL,
        prompt_version   TEXT NOT NULL,
        ontology_version TEXT NOT NULL,
        run_id           TEXT NOT NULL REFERENCES runs (run_id),
        reason           TEXT NOT NULL,
        UNIQUE (review_id, model_version, prompt_version, ontology_version)
    )
    """,
)

# Step 2 — the eval-run journal (D2a, the first consumer B5 deferred the schema
# to). One row per certification run keyed into the shared `runs` journal; the
# metric values live in name-keyed child rows so the harness's growing metric
# family (fabricated-quote, per-category judge agreement) lands as new rows,
# never as a migration on already-minted runs.
_STEP_2: tuple[str, ...] = (
    """
    CREATE TABLE eval_runs (
        run_id                TEXT    PRIMARY KEY REFERENCES runs (run_id),
        model_version         TEXT    NOT NULL,
        prompt_version        TEXT    NOT NULL,
        ontology_version      TEXT    NOT NULL,
        ontology_content_hash TEXT    NOT NULL,
        gold_path             TEXT    NOT NULL,
        gold_sha256           TEXT    NOT NULL,
        n_gold_reviews        INTEGER NOT NULL,
        n_scored_reviews      INTEGER NOT NULL,
        seed                  INTEGER NOT NULL,
        n_resamples           INTEGER NOT NULL,
        scorer                TEXT    NOT NULL
    ) WITHOUT ROWID
    """,
    # ci_low/ci_high are NULL together for point-only diagnostics ("not
    # bootstrapped", never "zero-width interval") — the read boundary enforces
    # the pairing; SQLite's job is just the per-run metric-name uniqueness.
    """
    CREATE TABLE eval_metrics (
        id      INTEGER PRIMARY KEY,
        run_id  TEXT NOT NULL REFERENCES eval_runs (run_id),
        metric  TEXT NOT NULL,
        value   REAL NOT NULL,
        ci_low  REAL,
        ci_high REAL,
        UNIQUE (run_id, metric)
    )
    """,
    "CREATE INDEX idx_eval_metrics_metric ON eval_metrics (metric)",
)

# Step 3 — the reference generalization (the D2c census-sample fit). The journal's
# measuring stick was born gold-shaped (a file path + byte hash); agreement runs
# score against another annotator's stored labels, so the pin generalizes: renamed
# reference columns plus a kind tag telling a reader how to dereference the pin
# (the closed vocabulary and each kind's pin mechanics live on the contract enum,
# ReferenceKind). Additive per the freeze rule — the renames rewrite no data, and
# the ADD COLUMN default doubles as the honest backfill (every pre-step-3 row was
# scored against a gold file); the write path always supplies the kind explicitly.
_STEP_3: tuple[str, ...] = (
    "ALTER TABLE eval_runs RENAME COLUMN gold_path TO reference_id",
    "ALTER TABLE eval_runs RENAME COLUMN gold_sha256 TO reference_sha256",
    "ALTER TABLE eval_runs RENAME COLUMN n_gold_reviews TO n_reference_reviews",
    "ALTER TABLE eval_runs ADD COLUMN reference_kind TEXT NOT NULL DEFAULT 'gold-file'",
)

MIGRATION_STEPS: tuple[tuple[str, ...], ...] = (_STEP_1, _STEP_2, _STEP_3)

SCHEMA_VERSION = len(MIGRATION_STEPS)


def apply_migrations(conn: sqlite3.Connection) -> None:
    """Bring the connected file to ``SCHEMA_VERSION``, applying missing steps in order.

    All missing steps run in one transaction with the version stamp, so a file
    is only ever observed fully at a version, never between two. A file already
    current is a no-op; a file stamped *ahead* of this code raises
    ``SchemaVersionError`` before any statement runs. Expects a connection in
    autocommit mode (``Store``'s) — the runner manages its own transaction with
    explicit BEGIN/COMMIT.
    """
    row = conn.execute("PRAGMA user_version").fetchone()
    current = int(row[0])
    if current > SCHEMA_VERSION:
        raise SchemaVersionError(
            f"file schema is v{current}, but this code understands up to v{SCHEMA_VERSION} — "
            "the file was written by newer code"
        )
    if current == SCHEMA_VERSION:
        return
    conn.execute("BEGIN")
    try:
        for version in range(current + 1, SCHEMA_VERSION + 1):
            for statement in MIGRATION_STEPS[version - 1]:
                conn.execute(statement)
        # PRAGMA user_version cannot be parameterized; SCHEMA_VERSION is a
        # module constant, never user input.
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
