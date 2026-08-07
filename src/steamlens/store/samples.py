"""The sample-manifest surface — which exact reviews a serving run's sample holds.

``SampleManifest`` owns the ``sample_members`` table: one row per (run,
member review), written as each fetched window's members are filed. The
manifest is what makes a run's sample a stored fact rather than an inference
from who bought which label — the mint folds membership ∩ label pool, the
classify selection asks which *members* still lack a verdict, and a resumed
job re-uses labels bought by any prior run because membership, not run-scoped
envelope ownership, scopes both questions. Those two cross-table reads live
with their own nouns (``ReviewStore.members_unlabeled_under``, the
``LabelPool`` member-scoped folds); this surface owns the membership facts
themselves.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable

from steamlens.store.errors import StoreError


class SampleManifest:
    """The stored membership of each serving run's sample.

    Constructed by ``Store`` with the store's connection; never opens or owns
    one itself.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def add_members(self, run_id: str, review_ids: Iterable[str]) -> None:
        """File ``review_ids`` as members of ``run_id``'s sample, atomically.

        One call per fetched window, riding the same moment the reviews
        themselves are filed. Duplicates fail loud with ``StoreError``: plan
        windows are disjoint, so the same review arriving twice under one run
        means the plan or the producer is broken — exactly the class of bug
        silent absorption would hide. Unrecorded runs and reviews are rejected
        the same way (foreign keys).
        """
        cursor = self._conn.cursor()
        cursor.execute("BEGIN")
        try:
            cursor.executemany(
                "INSERT INTO sample_members (run_id, review_id) VALUES (?, ?)",
                ((run_id, review_id) for review_id in review_ids),
            )
            cursor.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            cursor.execute("ROLLBACK")
            raise StoreError(
                f"membership write rejected for run {run_id!r} — duplicate member, "
                f"or the run/a review is not recorded: {exc}"
            ) from exc
        except BaseException:
            cursor.execute("ROLLBACK")
            raise

    def member_ids(self, run_id: str) -> tuple[str, ...]:
        """Every member review id of ``run_id``'s sample, ordered by review id."""
        rows = self._conn.execute(
            "SELECT review_id FROM sample_members WHERE run_id = ? ORDER BY review_id",
            (run_id,),
        ).fetchall()
        return tuple(str(row[0]) for row in rows)

    def count(self, run_id: str) -> int:
        """How many reviews ``run_id``'s sample holds — the fetched-members total.

        Distinct from the mint denominator (``LabelPool.count_member_envelopes``):
        this counts what was fetched and filed, that counts what was actually
        classified under the folded versions.
        """
        row = self._conn.execute(
            "SELECT COUNT(*) FROM sample_members WHERE run_id = ?", (run_id,)
        ).fetchone()
        return int(row[0])
