"""The eval-run journal surface — certification results, minted once, cited forever.

``EvalRunLog`` owns the two step-2 tables. A record lands atomically — the
shared ``runs`` stamp, the eval row, and every metric in one transaction — so
a half-written certification can never be observed; a duplicate ``run_id``
fails loud (run ids name one execution, and an eval run that overwrote another
would be a provenance bug wearing a convenience suit). Reads rebuild the full
``EvalRun`` contract, re-proving on the way out the CI invariant the write
path promised: interval bounds present together or absent together.
"""

from __future__ import annotations

import sqlite3

from steamlens.contracts import ClassifierVersions, EvalMetric, EvalRun, Provenance
from steamlens.store.convert import parse_utc_isoformat, utc_isoformat
from steamlens.store.errors import StoreDataError, StoreError


class EvalRunLog:
    """The eval-run tables' one door; constructed by ``Store`` with its connection."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def record(self, eval_run: EvalRun) -> None:
        """Journal one certification run — stamp, row, and metrics, atomically.

        Writes the shared ``runs`` stamp itself (an eval run is a run like any
        other; the journal is one table regardless of who mints into it).
        Raises ``StoreError`` when the ``run_id`` is already recorded, and
        ``ValueError`` on a metric whose interval bounds are not present or
        absent together — a half-interval is a scorer bug, stopped at the door.
        """
        for m in eval_run.metrics:
            if (m.ci_low is None) != (m.ci_high is None):
                raise ValueError(
                    f"metric {m.metric!r} carries half an interval "
                    f"(ci_low={m.ci_low!r}, ci_high={m.ci_high!r})"
                )
        run = eval_run.run
        cursor = self._conn.cursor()
        cursor.execute("BEGIN")
        try:
            cursor.execute(
                "INSERT INTO runs (run_id, code_version, created_at, config_hash)"
                " VALUES (?, ?, ?, ?)",
                (run.run_id, run.code_version, utc_isoformat(run.created_at), run.config_hash),
            )
            cursor.execute(
                "INSERT INTO eval_runs (run_id, model_version, prompt_version,"
                " ontology_version, ontology_content_hash, gold_path, gold_sha256,"
                " n_gold_reviews, n_scored_reviews, seed, n_resamples, scorer)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run.run_id,
                    eval_run.versions.model_version,
                    eval_run.versions.prompt_version,
                    eval_run.versions.ontology_version,
                    eval_run.ontology_content_hash,
                    eval_run.gold_path,
                    eval_run.gold_sha256,
                    eval_run.n_gold_reviews,
                    eval_run.n_scored_reviews,
                    eval_run.seed,
                    eval_run.n_resamples,
                    eval_run.scorer,
                ),
            )
            cursor.executemany(
                "INSERT INTO eval_metrics (run_id, metric, value, ci_low, ci_high)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    (run.run_id, m.metric, m.value, m.ci_low, m.ci_high)
                    for m in eval_run.metrics
                ),
            )
            cursor.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            cursor.execute("ROLLBACK")
            raise StoreError(
                f"eval run {run.run_id!r} rejected — duplicate run id or duplicate "
                f"metric name: {exc}"
            ) from exc
        except BaseException:
            cursor.execute("ROLLBACK")
            raise

    def get(self, run_id: str) -> EvalRun | None:
        """The recorded certification under ``run_id``, or None.

        Metrics come back in the order they were written. Raises
        ``StoreDataError`` on a stored half-interval — the write path forbids
        it, so its presence means the file was edited behind the boundary.
        """
        row = self._conn.execute(
            "SELECT e.model_version, e.prompt_version, e.ontology_version,"
            " e.ontology_content_hash, e.gold_path, e.gold_sha256, e.n_gold_reviews,"
            " e.n_scored_reviews, e.seed, e.n_resamples, e.scorer,"
            " r.code_version, r.created_at, r.config_hash"
            " FROM eval_runs e JOIN runs r ON r.run_id = e.run_id"
            " WHERE e.run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        metric_rows = self._conn.execute(
            "SELECT metric, value, ci_low, ci_high FROM eval_metrics"
            " WHERE run_id = ? ORDER BY id",
            (run_id,),
        ).fetchall()
        metrics: list[EvalMetric] = []
        for m in metric_rows:
            if (m[2] is None) != (m[3] is None):
                raise StoreDataError(
                    f"eval_metrics[{run_id}].{m[0]}: stored half-interval "
                    f"(ci_low={m[2]!r}, ci_high={m[3]!r})"
                )
            metrics.append(
                EvalMetric(
                    metric=str(m[0]),
                    value=float(m[1]),
                    ci_low=None if m[2] is None else float(m[2]),
                    ci_high=None if m[3] is None else float(m[3]),
                )
            )
        return EvalRun(
            run=Provenance(
                run_id=run_id,
                code_version=str(row[11]),
                created_at=parse_utc_isoformat(
                    str(row[12]), context=f"runs[{run_id}].created_at"
                ),
                config_hash=str(row[13]),
            ),
            versions=ClassifierVersions(
                model_version=str(row[0]),
                prompt_version=str(row[1]),
                ontology_version=str(row[2]),
            ),
            ontology_content_hash=str(row[3]),
            gold_path=str(row[4]),
            gold_sha256=str(row[5]),
            n_gold_reviews=int(row[6]),
            n_scored_reviews=int(row[7]),
            seed=int(row[8]),
            n_resamples=int(row[9]),
            scorer=str(row[10]),
            metrics=tuple(metrics),
        )
