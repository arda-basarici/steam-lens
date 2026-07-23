"""The label pool surface — envelopes, mentions, runs, and failure marks.

``LabelPool`` owns the four label-pool tables. Its write discipline is the
driver's safety net, stated once: a run is recorded exactly once before its
envelopes; envelope and failure writes fail loud on a duplicate under their
version key (a duplicate means the driver's unlabeled-selection is broken —
replacing would hide exactly that bug) and on references to runs or reviews
never recorded (foreign keys, surfaced as ``StoreError``). Reads reconstruct
full contracts through the read boundary's parsers — a stored label re-proves
its vocabulary membership on the way out.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from typing import Any

from steamlens.contracts import (
    AspectMention,
    AspectSlot,
    ClassifierVersions,
    Origin,
    Provenance,
    ReviewClassification,
    Sentiment,
)
from steamlens.store.convert import parse_enum, parse_utc_isoformat, utc_isoformat
from steamlens.store.errors import StoreError


def _mention_from_row(row: Any, *, context: str) -> AspectMention:
    return AspectMention(
        aspect=str(row[0]),
        slot=parse_enum(AspectSlot, str(row[1]), context=f"{context}.slot"),
        sentiment=parse_enum(Sentiment, str(row[2]), context=f"{context}.sentiment"),
        evidence=None if row[3] is None else str(row[3]),
    )


class LabelPool:
    """The bought labels, keyed to never re-pay: one envelope per (review, versions).

    Constructed by ``Store`` with the store's connection; never opens or owns
    one itself.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def record_run(self, run: Provenance) -> None:
        """Journal one run's stamp, exactly once, before any of its envelopes.

        A duplicate ``run_id`` raises ``StoreError``: run ids name one
        execution, so a collision means two executions claim the same identity
        — a provenance bug worth crashing on, never merging silently.
        """
        try:
            self._conn.execute(
                "INSERT INTO runs (run_id, code_version, created_at, config_hash)"
                " VALUES (?, ?, ?, ?)",
                (run.run_id, run.code_version, utc_isoformat(run.created_at), run.config_hash),
            )
        except sqlite3.IntegrityError as exc:
            raise StoreError(f"run {run.run_id!r} is already recorded: {exc}") from exc

    def put(self, classification: ReviewClassification) -> None:
        """Store one envelope and its mentions atomically; duplicates fail loud.

        Raises ``StoreError`` when the envelope already exists under its
        (review, versions) key — the driver selected a review it shouldn't
        have — or when its review or run was never recorded (foreign keys).
        """
        c = classification
        cursor = self._conn.cursor()
        cursor.execute("BEGIN")
        try:
            cursor.execute(
                "INSERT INTO classifications (review_id, origin, model_version,"
                " prompt_version, ontology_version, run_id) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    c.review_id,
                    c.origin,
                    c.versions.model_version,
                    c.versions.prompt_version,
                    c.versions.ontology_version,
                    c.run.run_id,
                ),
            )
            envelope_id = cursor.lastrowid
            cursor.executemany(
                "INSERT INTO mentions (classification_id, aspect, slot, sentiment, evidence)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    (envelope_id, m.aspect, m.slot, m.sentiment, m.evidence)
                    for m in c.mentions
                ),
            )
            cursor.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            cursor.execute("ROLLBACK")
            raise StoreError(
                f"envelope write rejected for review {c.review_id!r} under "
                f"{c.versions!r} — duplicate under its version key, or its "
                f"review/run is not recorded: {exc}"
            ) from exc
        except BaseException:
            cursor.execute("ROLLBACK")
            raise

    def get(self, review_id: str, versions: ClassifierVersions) -> ReviewClassification | None:
        """The stored envelope for ``review_id`` under ``versions``, or None.

        Reconstructs the full contract — origin, the versions triple, the run
        stamp via the ``runs`` join, mentions in the order they were written.
        """
        context = f"classifications[{review_id}]"
        row = self._conn.execute(
            "SELECT c.id, c.origin, c.model_version, c.prompt_version, c.ontology_version,"
            " r.run_id, r.code_version, r.created_at, r.config_hash"
            " FROM classifications c JOIN runs r ON r.run_id = c.run_id"
            " WHERE c.review_id = ? AND c.model_version = ? AND c.prompt_version = ?"
            " AND c.ontology_version = ?",
            (review_id, versions.model_version, versions.prompt_version,
             versions.ontology_version),
        ).fetchone()
        if row is None:
            return None
        mention_rows = self._conn.execute(
            "SELECT aspect, slot, sentiment, evidence FROM mentions"
            " WHERE classification_id = ? ORDER BY id",
            (row[0],),
        ).fetchall()
        return ReviewClassification(
            review_id=review_id,
            origin=parse_enum(Origin, str(row[1]), context=f"{context}.origin"),
            versions=ClassifierVersions(
                model_version=str(row[2]),
                prompt_version=str(row[3]),
                ontology_version=str(row[4]),
            ),
            run=Provenance(
                run_id=str(row[5]),
                code_version=str(row[6]),
                created_at=parse_utc_isoformat(str(row[7]), context=f"runs[{row[5]}].created_at"),
                config_hash=str(row[8]),
            ),
            mentions=tuple(
                _mention_from_row(m, context=f"{context}.mentions[{i}]")
                for i, m in enumerate(mention_rows)
            ),
        )

    def record_failure(
        self, review_id: str, versions: ClassifierVersions, run_id: str, reason: str
    ) -> None:
        """Mark ``review_id`` unclassifiable under ``versions`` — durably, so the
        selection loop never re-buys the same failure.

        ``reason`` is the classify failure's own wording, stringified. No
        contract record crosses here on purpose: a failure is precisely
        not-an-envelope, and the classification contracts have no failure state
        (an empty-mentions envelope means "processed, found nothing"). Raises
        ``StoreError`` on a duplicate mark (a failed review is excluded from
        selection, so failing twice under one key means the selection is
        broken) and on an unrecorded review or run.
        """
        try:
            self._conn.execute(
                "INSERT INTO classification_failures (review_id, model_version,"
                " prompt_version, ontology_version, run_id, reason) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    review_id,
                    versions.model_version,
                    versions.prompt_version,
                    versions.ontology_version,
                    run_id,
                    reason,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise StoreError(
                f"failure mark rejected for review {review_id!r} under {versions!r} — "
                f"duplicate under its version key, or its review/run is not recorded: {exc}"
            ) from exc

    def get_failure(self, review_id: str, versions: ClassifierVersions) -> str | None:
        """The durable failure mark's reason for ``review_id`` under ``versions``, or None.

        The read that lets a consumer tell "classified as unclassifiable" from
        "never attempted": a certification must score the former as a failure
        and treat the latter as the loud error it is (a review inside the
        pool's scope with neither an envelope nor a mark means the selection
        or the scope reasoning is broken).
        """
        row = self._conn.execute(
            "SELECT reason FROM classification_failures"
            " WHERE review_id = ? AND model_version = ? AND prompt_version = ?"
            " AND ontology_version = ?",
            (review_id, versions.model_version, versions.prompt_version,
             versions.ontology_version),
        ).fetchone()
        return None if row is None else str(row[0])

    def iter_survey_mentions(
        self, versions: ClassifierVersions
    ) -> Iterator[tuple[str, str, AspectSlot, Sentiment]]:
        """Stream survey mentions as ``(review_id, aspect, slot, sentiment)`` for the fold.

        The aggregate fold's mention input, kept lean on purpose: only the four
        fields the count needs — no evidence span, and no join to ``reviews`` (the
        caller attaches ``app_id`` from the skinny map). Origin and the versions
        triple are filtered here, so a number can only ever be folded from labels
        that belong in it: investigation-track and off-version mentions never
        cross this boundary. Enums re-validate on the way out, same as ``get``.
        """
        cursor = self._conn.execute(
            "SELECT c.review_id, m.aspect, m.slot, m.sentiment"
            " FROM mentions m JOIN classifications c ON c.id = m.classification_id"
            " WHERE c.origin = ? AND c.model_version = ? AND c.prompt_version = ?"
            " AND c.ontology_version = ?",
            (
                Origin.SURVEY,
                versions.model_version,
                versions.prompt_version,
                versions.ontology_version,
            ),
        )
        for row in cursor:
            yield (
                str(row[0]),
                str(row[1]),
                parse_enum(AspectSlot, str(row[2]), context="mentions.slot"),
                parse_enum(Sentiment, str(row[3]), context="mentions.sentiment"),
            )

    def iter_survey_envelope_review_ids(self, versions: ClassifierVersions) -> Iterator[str]:
        """Stream each survey, version-matched envelope's review id — empties included.

        The denominator source: one row per classified survey review under
        ``versions`` whether or not it yielded a mention — the ~46% empty
        envelopes are exactly what keeps a game's ``sample_size`` from being the
        inflated "reviews that said something" instead of "reviews we looked at."
        """
        cursor = self._conn.execute(
            "SELECT review_id FROM classifications"
            " WHERE origin = ? AND model_version = ?"
            " AND prompt_version = ? AND ontology_version = ?",
            (
                Origin.SURVEY,
                versions.model_version,
                versions.prompt_version,
                versions.ontology_version,
            ),
        )
        for row in cursor:
            yield str(row[0])
