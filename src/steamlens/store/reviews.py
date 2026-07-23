"""The reviews surface — the corpus snapshot, and the selection query C1 loops on.

``ReviewStore`` owns the ``reviews`` table and everything that answers in
``Review`` records — including ``unlabeled_under``, the driver's selection
query, which anti-joins the label pool's tables (which reviews still need
labeling is a question *about reviews*; the pool's own surface is
``LabelPool``). Ingest is idempotent by ``review_id``: re-ingesting the same
frozen corpus inserts nothing and is safe to repeat on every driver start.
Content drift under an existing id is deliberately not detected here — the
M1 corpus is frozen files; the live door revisits that question when reviews
can actually change between fetches.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Collection, Iterable
from typing import Any

from steamlens.contracts import ClassifierVersions, Review
from steamlens.store.convert import parse_utc_isoformat, utc_isoformat

_REVIEW_COLUMNS = "review_id, app_id, created_at, language, text, voted_up"


def _exclusion_clause(
    column: str, app_ids: Collection[int], *, prefix: str = " WHERE"
) -> tuple[str, tuple[int, ...]]:
    """A ``NOT IN`` fragment plus its parameters, or nothing when the set is empty.

    Sorted so an identical exclusion set always renders identical SQL.
    """
    if not app_ids:
        return "", ()
    ordered = tuple(sorted(app_ids))
    placeholders = ", ".join("?" for _ in ordered)
    return f"{prefix} {column} NOT IN ({placeholders})", ordered


def _review_from_row(row: Any) -> Review:
    """One ``reviews`` row (in ``_REVIEW_COLUMNS`` order) back as its contract.

    The datetime parse is the read boundary — a naive or mangled timestamp
    raises ``StoreDataError`` naming the review.
    """
    review_id = str(row[0])
    return Review(
        review_id=review_id,
        app_id=int(row[1]),
        created_at=parse_utc_isoformat(str(row[2]), context=f"reviews[{review_id}].created_at"),
        language=str(row[3]),
        text=str(row[4]),
        voted_up=bool(row[5]),
    )


class ReviewStore:
    """The corpus snapshot behind C1: idempotent ingest, reads, the selection query.

    Constructed by ``Store`` with the store's connection; never opens or owns
    one itself.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def put_many(self, reviews: Iterable[Review]) -> int:
        """Ingest ``reviews``, skipping ids already present; returns how many were new.

        The count is the driver's narration hook ("ingested N new, rest already
        present"). One transaction: a crashed ingest leaves nothing half-visible,
        and the re-run inserts whatever is missing.
        """
        cursor = self._conn.cursor()
        cursor.execute("BEGIN")
        try:
            cursor.executemany(
                f"INSERT OR IGNORE INTO reviews ({_REVIEW_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    (
                        review.review_id,
                        review.app_id,
                        utc_isoformat(review.created_at),
                        review.language,
                        review.text,
                        int(review.voted_up),
                    )
                    for review in reviews
                ),
            )
            inserted = cursor.rowcount
            cursor.execute("COMMIT")
        except BaseException:
            cursor.execute("ROLLBACK")
            raise
        return inserted

    def get(self, review_id: str) -> Review | None:
        """The stored review under ``review_id``, or None if it was never ingested."""
        row = self._conn.execute(
            f"SELECT {_REVIEW_COLUMNS} FROM reviews WHERE review_id = ?", (review_id,)
        ).fetchone()
        return None if row is None else _review_from_row(row)

    def count(self, *, excluding_app_ids: Collection[int] = ()) -> int:
        """How many reviews the snapshot holds — the driver's denominator.

        ``excluding_app_ids`` narrows the count to a labeling run's scope: the
        table may hold reviews outside the census's usable pool (eval dispatches
        backfill their out-of-scope gold reviews — the judge's CS2 rows — so
        their envelopes can satisfy the label pool's review foreign key), and a
        supply assertion priced on the usable pool must not count them.
        """
        clause, params = _exclusion_clause("app_id", excluding_app_ids)
        row = self._conn.execute(f"SELECT COUNT(*) FROM reviews{clause}", params).fetchone()
        return int(row[0])

    def app_id_by_review(self) -> dict[str, int]:
        """Every review's game as a skinny ``review_id -> app_id`` map.

        Two columns, no review text: the aggregate fold attaches each mention's
        game through this in-memory map instead of joining every mention row to
        the fat ``reviews`` table, which measured ~3-4x faster on the census (a
        per-row join drags text pages off disk for a lookup that needs one int).
        """
        return {
            str(row[0]): int(row[1])
            for row in self._conn.execute("SELECT review_id, app_id FROM reviews")
        }

    def unlabeled_under(
        self,
        versions: ClassifierVersions,
        *,
        excluding_app_ids: Collection[int] = (),
    ) -> tuple[Review, ...]:
        """The reviews still owed a verdict under ``versions`` — the driver's selection loop.

        Excludes reviews with an envelope (labeled, possibly with zero mentions)
        *and* reviews with a failure mark (unclassifiable-under-this-version)
        for exactly this versions triple; bumping any version reopens both.
        ``excluding_app_ids`` keeps out-of-scope backfilled reviews (see
        ``count``) from being selected — which reviews a labeling run may buy
        is part of the selection question, so the scope lives in the query.
        Ordered by ``review_id`` so a re-run selects deterministically —
        batch composition varies with the remaining *set*, never with row order
        luck.
        """
        clause, scope_params = _exclusion_clause("r.app_id", excluding_app_ids, prefix=" AND")
        rows = self._conn.execute(
            f"""
            SELECT {_REVIEW_COLUMNS} FROM reviews r
            WHERE NOT EXISTS (
                    SELECT 1 FROM classifications c
                    WHERE c.review_id = r.review_id
                      AND c.model_version = ? AND c.prompt_version = ? AND c.ontology_version = ?
                  )
              AND NOT EXISTS (
                    SELECT 1 FROM classification_failures f
                    WHERE f.review_id = r.review_id
                      AND f.model_version = ? AND f.prompt_version = ? AND f.ontology_version = ?
                  ){clause}
            ORDER BY r.review_id
            """,
            (
                versions.model_version,
                versions.prompt_version,
                versions.ontology_version,
            )
            * 2
            + scope_params,
        ).fetchall()
        return tuple(_review_from_row(row) for row in rows)
