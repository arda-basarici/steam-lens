"""Score the fresh human holdout against production — the reference-imperfection bound.

The census reference is machine-labeled, so the sampling study measures
sampling error with the classifier's own error riding silently on top. This
scorer reads Arda's blind pass over the 150-review holdout (drawn by
``scripts/draw_holdout.py``, labeled under frozen codebook v2) as the
reference and production's stored envelopes as the prediction, and mints the
measured bound on that silence — the number the M2 report's limitations
section quotes.

The frame is the judge read's: reviews, not mentions, zero-mention reviews
in ("both say no aspects" is agreement worth measuring). The headline binary
is the **strict envelope match** (ruled 2026-08-04): a review agrees only
when production's pinned aspect set equals the human's *and* every matched
sentiment agrees — the strictest honest reading, so the limitations number
cannot flatter. Softer components (aspect-set match alone, sentiment given a
matched set) journal beside it as disclosure, point values only. Intervals
are Wilson over the review flags, per the holdout ruling — no bootstrap, so
the run row's bootstrap dial reads ``seed 0 / 0 resamples``, meaning "none
ran", not "seeded at zero".

Two label stores feed the prediction side — the census pool for the corpus
stratum, the fresh-buy run's contained ``labels.sqlite3`` for the
marked-window and long-tail strata (containment by storage, the 2026-08-03
ruling) — both under the same frozen production triple. The run journals
into the census store's eval-run journal (it has a measuring stick, so it is
an eval run, not an audit) with the sheet pinned by content hash, and the
front door mirrors the record beside the sheet as ``agreement.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from steamlens.contracts import (
    ClassifierVersions,
    EvalMetric,
    EvalRun,
    Provenance,
    ReferenceKind,
    Sentiment,
)
from steamlens.core.classify import PROMPT_VERSION
from steamlens.core.intervals import wilson_interval
from steamlens.core.normalize import build_surface_index
from steamlens.dispatch import code_version
from steamlens.dispatch.census_arm import MODEL_ID
from steamlens.evals.certify import render_eval_run
from steamlens.evals.scoring import ReviewTally, tally_review
from steamlens.evals.sheets import parse_sheet, verify_reviews
from steamlens.ontology import load_ontology, load_ontology_version
from steamlens.store import Store

HOLDOUT_SCORER: Final = "holdout-vs-production/1"
"""The scoring procedure's identity: the human sheet in the reference role,
set-intersection pairing via ``core/normalize`` with candidates unscored on
both sides, SKIP reviews dropped with the drop disclosed, the strict-envelope
agreement binary, and Wilson intervals over review flags (no bootstrap)."""

CORPUS_STRATUM: Final = "corpus"
"""The stratum whose predictions live in the census pool; the fresh strata
(marked-window, long-tail) read from the fetch run's contained store."""


@dataclass(frozen=True, slots=True)
class HoldoutRow:
    """One drawn holdout review — the scorer's key, straight from ``sample.jsonl``."""

    position: int
    review_id: str
    app_id: int
    stratum: str
    text: str


@dataclass(frozen=True, slots=True)
class ScoredReview:
    """One scored review: its stratum (the slicing key) and its pairing tally."""

    review_id: str
    stratum: str
    tally: ReviewTally


def load_holdout_sample(path: Path) -> tuple[HoldoutRow, ...]:
    """Read the machine record of the draw — id, stratum, and pinned text per review."""
    rows: list[HoldoutRow] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            record = json.loads(line)
            rows.append(
                HoldoutRow(
                    position=record["position"],
                    review_id=record["review_id"],
                    app_id=record["app_id"],
                    stratum=record["stratum"],
                    text=record["text"],
                )
            )
    return tuple(rows)


def agrees(tally: ReviewTally) -> bool:
    """The strict envelope match — the holdout's headline binary.

    Production agrees with the human on a review when nothing pinned differs:
    no prediction-only aspects, no reference-only aspects, and every matched
    aspect's sentiment correct. Both sides empty is a genuine agreement (the
    zero-mention case). A parse failure never agrees even against an empty
    reference — a crashed read is not a considered zero, the same honesty
    ``pred_zero`` keeps in the scoring core.
    """
    return (
        not tally.parse_failed
        and tally.fp == 0
        and tally.fn == 0
        and tally.sentiment_correct == tally.tp
    )


def holdout_tallies(
    stores: Mapping[str, Store],
    sample: Sequence[HoldoutRow],
    reference: Mapping[str, Sequence[tuple[str, Sentiment]]],
    index: Mapping[str, str],
    versions: ClassifierVersions,
) -> tuple[ScoredReview, ...]:
    """Pair every non-skipped sampled review's human labels against production's.

    ``stores`` maps each stratum to the store holding its production
    envelopes; ``reference`` maps review id to the human (aspect, sentiment)
    pairs — a review absent from it was SKIPped on the sheet and is not
    scored (the caller discloses the drop). A durable failure mark scores as
    a parse failure per the protocol; a review with neither an envelope nor a
    mark raises naming every such id, because the holdout was drawn from
    labeled pools and silence means the store and the draw disagree.
    """
    scored: list[ScoredReview] = []
    unaccounted: list[str] = []
    for row in sample:
        pairs = reference.get(row.review_id)
        if pairs is None:
            continue
        store = stores[row.stratum]
        envelope = store.labels.get(row.review_id, versions)
        if envelope is not None:
            pred_pairs = [(m.aspect, m.sentiment) for m in envelope.mentions]
            parse_failed = False
        elif store.labels.get_failure(row.review_id, versions) is not None:
            pred_pairs = []
            parse_failed = True
        else:
            unaccounted.append(row.review_id)
            continue
        try:
            tally = tally_review(pairs, pred_pairs, index, parse_failed=parse_failed)
        except ValueError as exc:
            # tally_review knows the collision, only this loop knows the review
            raise ValueError(f"holdout review {row.review_id}: {exc}") from exc
        scored.append(ScoredReview(review_id=row.review_id, stratum=row.stratum, tally=tally))
    if unaccounted:
        raise ValueError(
            f"{len(unaccounted)} holdout reviews have neither an envelope nor a "
            f"failure mark under {versions!r}: {unaccounted}"
        )
    return tuple(scored)


def _agreement_rows(name: str, scored: Sequence[ScoredReview]) -> tuple[EvalMetric, ...]:
    """One slice's n row and its Wilson-bounded agreement row."""
    successes = sum(agrees(s.tally) for s in scored)
    interval = wilson_interval(successes, len(scored))
    return (
        EvalMetric(metric=f"holdout_n/{name}" if name else "holdout_n", value=float(len(scored))),
        EvalMetric(
            metric=f"holdout_agreement/{name}" if name else "holdout_agreement",
            value=successes / len(scored),
            ci_low=interval.low,
            ci_high=interval.high,
        ),
    )


def holdout_metrics(scored: Sequence[ScoredReview]) -> tuple[EvalMetric, ...]:
    """The holdout's metric rows: headline agreement, strata, and disclosure components.

    The headline and per-stratum rows carry Wilson intervals (the ruling's
    interval; strata order follows first appearance in the draw). The
    components — aspect-set match alone, sentiment given a matched set, and
    the parse-failure rate — are point diagnostics: they decompose the
    headline, they are not separately certified claims. The sentiment
    component's denominator is the aspect-matched subset; when that subset is
    empty the row is omitted and ``holdout_n_aspect_set_match`` (always
    journaled) reads as the explanation — undefined, never 0.0.
    """
    if not scored:
        raise ValueError("cannot score an empty holdout — no reviews survived the sheet")
    rows = list(_agreement_rows("", scored))
    strata = list(dict.fromkeys(s.stratum for s in scored))
    for stratum in strata:
        rows.extend(_agreement_rows(stratum, [s for s in scored if s.stratum == stratum]))
    aspect_matched = [
        s for s in scored
        if not s.tally.parse_failed and s.tally.fp == 0 and s.tally.fn == 0
    ]
    rows.append(
        EvalMetric(metric="holdout_aspect_set_match", value=len(aspect_matched) / len(scored))
    )
    rows.append(
        EvalMetric(metric="holdout_n_aspect_set_match", value=float(len(aspect_matched)))
    )
    if aspect_matched:
        rows.append(
            EvalMetric(
                metric="holdout_sentiment_given_aspect_match",
                value=sum(s.tally.sentiment_correct == s.tally.tp for s in aspect_matched)
                / len(aspect_matched),
            )
        )
    rows.append(
        EvalMetric(
            metric="parse_failure_rate",
            value=sum(s.tally.parse_failed for s in scored) / len(scored),
        )
    )
    return tuple(rows)


def sheet_reference(
    sheet_path: Path, sample: Sequence[HoldoutRow]
) -> tuple[dict[str, tuple[tuple[str, Sentiment], ...]], tuple[str, ...]]:
    """Parse and gate the human sheet; returns (reference pairs by id, skipped ids).

    The gate is total: grammar violations, structural/verbatim failures,
    coverage mismatches against the draw, and unreviewed blocks all collect
    into one ``ValueError`` listing every finding — the sheet is fixed once,
    not one raise at a time. A SKIP block passes the gate but stays out of
    the reference; the caller discloses the ids.
    """
    reviews, violations = parse_sheet(sheet_path)
    texts = {row.review_id: row.text for row in sample}
    problems = list(violations)
    problems += verify_reviews(reviews, texts, sheet_path.name)
    sheet_ids = {r.review_id for r in reviews}
    if sheet_ids != set(texts):
        problems.append(
            f"{sheet_path.name}: review coverage mismatch vs the draw "
            f"(missing {sorted(set(texts) - sheet_ids)[:5]}, "
            f"extra {sorted(sheet_ids - set(texts))[:5]})"
        )
    unreviewed = [r.review_id for r in reviews if not r.reviewed]
    if unreviewed:
        problems.append(
            f"{sheet_path.name}: {len(unreviewed)} unreviewed blocks: {unreviewed[:5]}"
        )
    if problems:
        raise ValueError(
            f"the holdout sheet is not scoreable — {len(problems)} finding(s):\n  "
            + "\n  ".join(problems)
        )
    reference: dict[str, tuple[tuple[str, Sentiment], ...]] = {}
    skipped: list[str] = []
    for r in reviews:
        if r.skip is not None:
            skipped.append(r.review_id)
            continue
        reference[r.review_id] = tuple(
            (m.aspect, Sentiment(m.sentiment)) for m in r.mentions
        )
    return reference, tuple(skipped)


def score_holdout(
    corpus_store: Store,
    fresh_store: Store,
    *,
    sample_path: Path,
    sheet_path: Path,
    ontology_path: Path | None,
    model_version: str,
    prompt_version: str,
    freshbuy_run: str,
    started: datetime | None = None,
) -> EvalRun:
    """Score the human holdout against production and build the full run record.

    Pure assembly over its inputs (no writes), the certify contract:
    recording the returned ``EvalRun`` is the caller's explicit step. The
    reference pin is the edited sheet's bytes — the single copy of the human
    pass — under ``reference_kind = gold-file``; ``n_reference_reviews`` is
    the draw's 150, ``n_scored_reviews`` what survived SKIPs, with the
    skipped ids disclosed in the config.
    """
    started = started if started is not None else datetime.now(UTC)
    stamp = load_ontology_version(ontology_path)
    versions = ClassifierVersions(
        model_version=model_version,
        prompt_version=prompt_version,
        ontology_version=stamp.version,
    )
    sample = load_holdout_sample(sample_path)
    reference, skipped = sheet_reference(sheet_path, sample)
    index = build_surface_index(load_ontology(ontology_path))
    stores = {
        row.stratum: (corpus_store if row.stratum == CORPUS_STRATUM else fresh_store)
        for row in sample
    }
    scored = holdout_tallies(stores, sample, reference, index, versions)
    metrics = holdout_metrics(scored)
    sheet_sha256 = hashlib.sha256(sheet_path.read_bytes()).hexdigest()
    config = {
        "model_version": versions.model_version,
        "prompt_version": versions.prompt_version,
        "ontology_version": versions.ontology_version,
        "ontology_content_hash": stamp.content_hash,
        "sample_path": sample_path.as_posix(),
        "sample_sha256": hashlib.sha256(sample_path.read_bytes()).hexdigest(),
        "sheet_path": sheet_path.as_posix(),
        "sheet_sha256": sheet_sha256,
        "freshbuy_run": freshbuy_run,
        "skipped_reviews": sorted(skipped),
        "scorer": HOLDOUT_SCORER,
    }
    canonical = json.dumps(config, sort_keys=True, separators=(",", ":"))
    return EvalRun(
        run=Provenance(
            run_id=f"holdout-{started:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}",
            code_version=code_version(),
            created_at=started,
            config_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        ),
        versions=versions,
        ontology_content_hash=stamp.content_hash,
        reference_kind=ReferenceKind.GOLD_FILE,
        reference_id=sheet_path.as_posix(),
        reference_sha256=sheet_sha256,
        n_reference_reviews=len(sample),
        n_scored_reviews=len(scored),
        seed=0,
        n_resamples=0,
        scorer=HOLDOUT_SCORER,
        metrics=metrics,
    )


def render_artifact(eval_run: EvalRun, *, skipped: Sequence[str]) -> str:
    """The journal row mirrored as JSON for ``eval/holdout/agreement.json``.

    The store row is the record of record; this artifact keeps the number
    readable beside the sheet that produced it (the M2 report cites both).
    Carries full regenerability provenance, per the artifact rule.
    """
    return json.dumps(
        {
            "run_id": eval_run.run.run_id,
            "code_version": eval_run.run.code_version,
            "created_at": eval_run.run.created_at.isoformat(),
            "scorer": eval_run.scorer,
            "reference": {
                "kind": str(eval_run.reference_kind),
                "id": eval_run.reference_id,
                "sha256": eval_run.reference_sha256,
            },
            "pool_versions": {
                "model_version": eval_run.versions.model_version,
                "prompt_version": eval_run.versions.prompt_version,
                "ontology_version": eval_run.versions.ontology_version,
            },
            "n_reference_reviews": eval_run.n_reference_reviews,
            "n_scored_reviews": eval_run.n_scored_reviews,
            "skipped_reviews": sorted(skipped),
            "metrics": [
                {
                    "metric": m.metric,
                    "value": m.value,
                    "ci_low": m.ci_low,
                    "ci_high": m.ci_high,
                }
                for m in eval_run.metrics
            ],
        },
        indent=2,
        ensure_ascii=False,
    )


def main() -> None:
    """Score, journal into the census store, mirror the artifact — the front door.

    The fresh-buy run id comes from the draw's manifest, not a flag — the
    scorer reads the same provenance chain the draw recorded, so the two can
    never quietly point at different fetch runs.
    """
    parser = argparse.ArgumentParser(
        description="Score Arda's holdout sheet against production labels and "
                    "journal the run."
    )
    parser.add_argument("--holdout-dir", type=Path, default=Path("eval/holdout"),
                        help="the draw's directory: SHEET.md, sample.jsonl, manifest.json")
    parser.add_argument("--db", type=Path, default=None,
                        help="census label-pool db (default: the draw manifest's corpus_db)")
    parser.add_argument("--freshbuy-root", type=Path, default=Path("data/freshbuy"),
                        help="parent of fetch-run directories (default: data/freshbuy)")
    parser.add_argument("--ontology", type=Path, required=True,
                        help="ontology artifact path — explicit on purpose; every consumer "
                             "of the label pool pins v2 by path")
    parser.add_argument("--model", default=MODEL_ID,
                        help=f"production model_version under judgment (default: {MODEL_ID})")
    parser.add_argument("--prompt", default=PROMPT_VERSION,
                        help=f"production prompt_version (default: {PROMPT_VERSION})")
    parser.add_argument("--dry-run", action="store_true",
                        help="score and print without journaling or writing the artifact")
    args = parser.parse_args()

    manifest = json.loads((args.holdout_dir / "manifest.json").read_text(encoding="utf-8"))
    corpus_db = args.db if args.db is not None else Path(manifest["corpus_db"])
    fresh_db = args.freshbuy_root / manifest["freshbuy_run"] / "labels.sqlite3"
    sheet_path = args.holdout_dir / "SHEET.md"

    with Store(corpus_db) as corpus_store, Store(fresh_db) as fresh_store:
        eval_run = score_holdout(
            corpus_store,
            fresh_store,
            sample_path=args.holdout_dir / "sample.jsonl",
            sheet_path=sheet_path,
            ontology_path=args.ontology,
            model_version=args.model,
            prompt_version=args.prompt,
            freshbuy_run=manifest["freshbuy_run"],
        )
        print(render_eval_run(eval_run))
        if args.dry_run:
            print("dry run — nothing journaled, no artifact written")
            return
        corpus_store.eval_runs.record(eval_run)
        if corpus_store.eval_runs.get(eval_run.run.run_id) != eval_run:
            raise SystemExit("round-trip verification failed — journaled row differs")

    _, skipped = sheet_reference(sheet_path, load_holdout_sample(args.holdout_dir / "sample.jsonl"))
    artifact_path = args.holdout_dir / "agreement.json"
    artifact_path.write_text(
        render_artifact(eval_run, skipped=skipped) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"journaled + verified -> eval_runs[{eval_run.run.run_id}]")
    print(f"artifact -> {artifact_path.as_posix()}")


if __name__ == "__main__":
    main()
