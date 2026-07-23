"""Score production against the judge over the census sample — the D2c agreement read.

Certification measures the pool against human truth; this read measures it
against the calibrated judge out where gold doesn't reach. Both annotators'
labels already sit in the pool as envelope sets under their own versions
triples (the judge's minted by ``judge_sample``), so scoring is the frozen
core pointed at a new pair: the judge's mentions take the reference role,
production's take the prediction role. Direction matters and is fixed here —
precision is the share of production's mentions the judge corroborates,
recall the share of the judge's mentions production found.

The result journals through the same eval-run record as a certification,
distinguished honestly twice: ``reference_kind = pool-labels`` and the
``judge-vs-production/1`` scorer identity. Its reference pin is computed, not
read from a file — ``reference_sha256`` digests the judge's
canonically-serialized labels for the scored reviews — so the tamper-evidence
property of ``gold_sha256`` survives the reference moving into the store.

Accounting follows the design's refusal ruling: a review the judge declined
or failed to read drops from the scoring intersection — an instrument that
didn't read didn't read wrong — and the narrowing is the run row's
``n_reference_reviews`` (the drawn sample) vs ``n_scored_reviews`` (the
mutually-labeled intersection). A production-side failure mark *does* score,
as a parse failure, same as certification. A sampled review with no judge
verdict at all is a loud error: the sample hasn't been fully dispatched, and
scoring a partial dispatch would silently shrink the read.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from steamlens.contracts import (
    ClassifierVersions,
    EvalRun,
    Provenance,
    ReferenceKind,
    ReviewClassification,
)
from steamlens.core.classify import PROMPT_VERSION
from steamlens.core.normalize import build_surface_index
from steamlens.evals.certify import certification_metrics, render_eval_run
from steamlens.evals.judge_dispatch import JUDGE_MODEL_ID
from steamlens.evals.judge_sample import SampledReview, load_sample
from steamlens.evals.scoring import ReviewTally, tally_review
from steamlens.ontology import load_ontology, load_ontology_version
from steamlens.store.store import Store
from steamlens.studies.label_corpus import MODEL_ID, code_version

AGREEMENT_SCORER: Final = "judge-vs-production/1"
"""The agreement procedure's identity: certify's pairing semantics with the
judge's labels in the reference role, no scope exclusion (the sample was
drawn from the census, so every review is in scope by construction), and
judge-unread reviews dropped from the intersection with the drop disclosed."""


def agreement_tallies(
    store: Store,
    sample: tuple[SampledReview, ...],
    index: Mapping[str, str],
    production: ClassifierVersions,
    judge: ClassifierVersions,
) -> tuple[tuple[ReviewTally, ...], tuple[str, ...], tuple[ReviewClassification, ...]]:
    """Pair each sampled review's two envelopes; returns (tallies, dropped, reference).

    ``dropped`` names the reviews the judge declined or failed to read —
    excluded from scoring, disclosed by the caller. ``reference`` is the judge
    envelope per scored review, in scoring order — the exact label set the
    digest pins. Raises ``ValueError`` naming every sampled review with
    neither a judge envelope nor a judge failure mark (a partially-dispatched
    sample must not quietly score), and likewise for a missing production
    side (the frame was drawn from production envelopes, so absence means the
    store and the sample disagree).
    """
    tallies: list[ReviewTally] = []
    dropped: list[str] = []
    reference: list[ReviewClassification] = []
    unjudged: list[str] = []
    unaccounted: list[str] = []
    for record in sample:
        judge_envelope = store.labels.get(record.review_id, judge)
        if judge_envelope is None:
            if store.labels.get_failure(record.review_id, judge) is not None:
                dropped.append(record.review_id)
            else:
                unjudged.append(record.review_id)
            continue
        judge_pairs = [(m.aspect, m.sentiment) for m in judge_envelope.mentions]
        production_envelope = store.labels.get(record.review_id, production)
        if production_envelope is not None:
            pred_pairs = [(m.aspect, m.sentiment) for m in production_envelope.mentions]
            tallies.append(tally_review(judge_pairs, pred_pairs, index))
            reference.append(judge_envelope)
        elif store.labels.get_failure(record.review_id, production) is not None:
            tallies.append(tally_review(judge_pairs, [], index, parse_failed=True))
            reference.append(judge_envelope)
        else:
            unaccounted.append(record.review_id)
    if unjudged:
        raise ValueError(
            f"{len(unjudged)} sampled reviews have neither a judge envelope nor a "
            f"failure mark under {judge!r}: {unjudged} — dispatch the sample fully "
            f"before scoring"
        )
    if unaccounted:
        raise ValueError(
            f"{len(unaccounted)} sampled reviews have no production envelope or "
            f"failure mark under {production!r}: {unaccounted} — the sample was drawn "
            f"from production envelopes, so the store and the sample disagree"
        )
    return tuple(tallies), tuple(dropped), tuple(reference)


def reference_digest(reference: tuple[ReviewClassification, ...]) -> str:
    """The judge's scored label set, pinned by content — ``reference_sha256``'s value.

    Serializes exactly what the scorer consumed: per scored review (sorted by
    id), every judge mention as ``[aspect, slot, sentiment]`` sorted — no
    evidence spans (unscored decoration) and no run stamps (the pin is on the
    labels, not on which run produced them, so a re-dispatch that lands
    identical labels verifies identical). Canonical JSON, sha256 over UTF-8.
    """
    canonical = json.dumps(
        [
            {
                "review_id": envelope.review_id,
                "mentions": sorted(
                    [m.aspect, m.slot.value, m.sentiment.value] for m in envelope.mentions
                ),
            }
            for envelope in sorted(reference, key=lambda e: e.review_id)
        ],
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def agreement_pool(
    store: Store,
    *,
    sample_path: Path,
    ontology_path: Path | None,
    model_version: str,
    prompt_version: str,
    seed: int,
    n_resamples: int,
    started: datetime | None = None,
) -> EvalRun:
    """Score production against the judge over the sample and build the run record.

    Pure assembly over its inputs (no writes), same contract as
    ``certify_pool``: recording the returned ``EvalRun`` is the caller's
    explicit step. The production triple under judgment is
    (``model_version``, ``prompt_version``, the loaded ontology's version);
    the judge triple is fixed by the instrument (``JUDGE_MODEL_ID``, the
    classify prompt, the same ontology).
    """
    started = started if started is not None else datetime.now(UTC)
    stamp = load_ontology_version(ontology_path)
    production = ClassifierVersions(
        model_version=model_version,
        prompt_version=prompt_version,
        ontology_version=stamp.version,
    )
    judge = ClassifierVersions(
        model_version=JUDGE_MODEL_ID,
        prompt_version=PROMPT_VERSION,
        ontology_version=stamp.version,
    )
    sample = load_sample(sample_path)
    sample_sha256 = hashlib.sha256(sample_path.read_bytes()).hexdigest()
    index = build_surface_index(load_ontology(ontology_path))
    tallies, dropped, reference = agreement_tallies(store, sample, index, production, judge)
    metrics = certification_metrics(tallies, seed=seed, n_resamples=n_resamples)
    reference_id = (
        f"{judge.model_version}/{judge.prompt_version}/{judge.ontology_version}"
        f" @ {sample_path.as_posix()}"
    )
    config = {
        "model_version": production.model_version,
        "prompt_version": production.prompt_version,
        "ontology_version": production.ontology_version,
        "ontology_content_hash": stamp.content_hash,
        "judge_model_version": judge.model_version,
        "judge_prompt_version": judge.prompt_version,
        "sample_path": sample_path.as_posix(),
        "sample_sha256": sample_sha256,
        "dropped_judge_unread": sorted(dropped),
        "seed": seed,
        "n_resamples": n_resamples,
        "scorer": AGREEMENT_SCORER,
    }
    canonical = json.dumps(config, sort_keys=True, separators=(",", ":"))
    return EvalRun(
        run=Provenance(
            run_id=f"agree-{started:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}",
            code_version=code_version(),
            created_at=started,
            config_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        ),
        versions=production,
        ontology_content_hash=stamp.content_hash,
        reference_kind=ReferenceKind.POOL_LABELS,
        reference_id=reference_id,
        reference_sha256=reference_digest(reference),
        n_reference_reviews=len(sample),
        n_scored_reviews=len(tallies),
        seed=seed,
        n_resamples=n_resamples,
        scorer=AGREEMENT_SCORER,
        metrics=metrics,
    )


def main() -> None:
    """Score, mint the journal row, verify the round-trip — the agreement front door."""
    parser = argparse.ArgumentParser(
        description="Score production's census labels against the judge's over the "
                    "minted agreement sample, and journal the run."
    )
    parser.add_argument("--db", type=Path, default=Path("data/steamlens.sqlite3"),
                        help="the label-pool database (default: data/steamlens.sqlite3)")
    parser.add_argument("--sample", type=Path, default=Path("eval/agreement/sample.jsonl"),
                        help="the minted sample JSONL (default: eval/agreement/sample.jsonl)")
    parser.add_argument("--ontology", type=Path, required=True,
                        help="ontology artifact path — explicit on purpose; both triples "
                             "pin v2 by path like every consumer of the census pool")
    parser.add_argument("--model", default=MODEL_ID,
                        help=f"production model_version under judgment (default: {MODEL_ID})")
    parser.add_argument("--prompt", default=PROMPT_VERSION,
                        help=f"production prompt_version (default: {PROMPT_VERSION})")
    parser.add_argument("--seed", type=int, default=20260718,
                        help="bootstrap seed (default: 20260718, the certify seed)")
    parser.add_argument("--resamples", type=int, default=10_000,
                        help="bootstrap resamples (default: 10,000)")
    args = parser.parse_args()

    with Store(args.db) as store:
        eval_run = agreement_pool(
            store,
            sample_path=args.sample,
            ontology_path=args.ontology,
            model_version=args.model,
            prompt_version=args.prompt,
            seed=args.seed,
            n_resamples=args.resamples,
        )
        store.eval_runs.record(eval_run)
        recorded = store.eval_runs.get(eval_run.run.run_id)
        if recorded != eval_run:
            raise SystemExit(
                f"journal round-trip mismatch for {eval_run.run.run_id} — "
                "the stored record does not equal the minted one"
            )
    print(render_eval_run(eval_run))


if __name__ == "__main__":
    main()
