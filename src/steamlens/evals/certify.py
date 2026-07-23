"""Certify the pool's production labels against gold — the D2a mechanical core.

The bake-off certified a *configuration* on lab-composed batches; this shell
certifies the *bought labels themselves* — the envelopes every displayed
number is folded from — by scoring the pool's stored mentions for gold's
reviews through the same frozen scoring core. The result is minted into the
store's eval-run journal with its full regenerability set (gold hash, seed,
scorer identity), because a certification number that cannot be regenerated
to the digit is an anecdote, not a certification.

Scope rule: gold reviews from games outside the pool's scope (gold predates
the usable-pool ruling; the CS2 case) are excluded from scoring, never
counted as failures — a model must not be penalized for reviews it was never
sent. The narrowing is recorded on the run row (``n_scored_reviews`` vs
``n_reference_reviews``), visible forever.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from collections.abc import Callable, Collection, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from steamlens.contracts import (
    ClassifierVersions,
    EvalMetric,
    EvalRun,
    Provenance,
    ReferenceKind,
)
from steamlens.core.classify import PROMPT_VERSION
from steamlens.core.normalize import build_surface_index
from steamlens.evals.gold import GoldRecord, load_gold
from steamlens.evals.judge_dispatch import JUDGE_MODEL_ID
from steamlens.evals.scoring import ReviewTally, bootstrap_ci, score, tally_review
from steamlens.ontology import load_ontology, load_ontology_version
from steamlens.store.store import Store
from steamlens.studies.label_corpus import MODEL_ID, code_version
from steamlens.studies.local_corpus import EXCLUDED_APP_IDS

SCORER: Final = "census-vs-gold/1"
"""The scoring procedure's identity, stamped on every run this shell mints.

Names the whole procedure — set-intersection pairing via ``core/normalize``,
candidate mentions unscored, the out-of-scope exclusion rule — so a future
semantics change bumps this string and old rows stay attributable to old
semantics.
"""

JUDGE_SCORER: Final = "judge-vs-gold/1"
"""The judge-calibration variant's identity: same pairing and metrics, but NO
out-of-scope exclusion — the judge labels all of gold (pool scope was the
labeler's constraint, not the judge's), so its runs must not wear a scorer
name whose semantics include the exclusion rule."""

_BOOTSTRAPPED: Final[dict[str, Callable[[Sequence[ReviewTally]], float]]] = {
    "precision": lambda t: score(t).precision,
    "recall": lambda t: score(t).recall,
    "f1": lambda t: score(t).f1,
    "sentiment_accuracy": lambda t: score(t).sentiment_accuracy,
}
_DIAGNOSTICS: Final[dict[str, Callable[[Sequence[ReviewTally]], float]]] = {
    "zero_share_pred": lambda t: score(t).zero_share_pred,
    "candidate_emission_rate": lambda t: score(t).candidate_emission_rate,
    "parse_failure_rate": lambda t: score(t).parse_failure_rate,
}


def pool_tallies(
    store: Store,
    gold_records: Sequence[GoldRecord],
    index: Mapping[str, str],
    versions: ClassifierVersions,
    *,
    excluded_app_ids: Collection[int] = EXCLUDED_APP_IDS,
) -> tuple[ReviewTally, ...]:
    """One tally per in-scope gold review, from the pool's stored envelopes.

    A gold review outside the pool's scope (its game in ``excluded_app_ids``)
    is skipped — never scored, never a failure. In scope, an envelope's
    mentions are paired against gold; a durable failure mark scores as a
    parse failure per the protocol; a review with *neither* raises
    ``ValueError`` naming every such id, because inside the scope that means
    the pool or the scope reasoning is broken, and a silent skip would
    quietly shrink the denominator of a certification.
    """
    excluded = {str(app_id) for app_id in excluded_app_ids}
    tallies: list[ReviewTally] = []
    unaccounted: list[str] = []
    for record in gold_records:
        if record.app_id in excluded:
            continue
        gold_pairs = [(m.aspect, m.sentiment) for m in record.mentions]
        envelope = store.labels.get(record.review_id, versions)
        if envelope is not None:
            pred_pairs = [(m.aspect, m.sentiment) for m in envelope.mentions]
            tallies.append(tally_review(gold_pairs, pred_pairs, index))
        elif store.labels.get_failure(record.review_id, versions) is not None:
            tallies.append(tally_review(gold_pairs, [], index, parse_failed=True))
        else:
            unaccounted.append(record.review_id)
    if unaccounted:
        raise ValueError(
            f"{len(unaccounted)} in-scope gold reviews have neither an envelope nor "
            f"a failure mark under {versions!r}: {unaccounted}"
        )
    return tuple(tallies)


def certification_metrics(
    tallies: Sequence[ReviewTally], *, seed: int, n_resamples: int
) -> tuple[EvalMetric, ...]:
    """The certification's metric rows: the headline four, diagnostics, and slices.

    The headline four (precision, recall, F1, sentiment accuracy) carry 95%
    bootstrap intervals; the diagnostics (zero-share, candidate emission,
    parse-failure rate) are point values — they contextualize, they are not
    certified claims, and an interval would dress them as one. The item-type
    slices (the D2c calibration protocol's remainder) land as extra name-keyed
    rows via ``slice_metrics`` — new rows, never a schema or scorer change.
    """
    metrics: list[EvalMetric] = []
    for name, statistic in _BOOTSTRAPPED.items():
        ci = bootstrap_ci(tallies, statistic, n_resamples=n_resamples, seed=seed)
        metrics.append(
            EvalMetric(metric=name, value=statistic(tallies), ci_low=ci.low, ci_high=ci.high)
        )
    for name, statistic in _DIAGNOSTICS.items():
        metrics.append(EvalMetric(metric=name, value=statistic(tallies)))
    metrics.extend(slice_metrics(tallies, seed=seed, n_resamples=n_resamples))
    return tuple(metrics)


def _pinned_quiet_share(tallies: Sequence[ReviewTally]) -> float:
    """The share of reviews where the annotator predicted no pinned aspect at all."""
    return sum(t.fp == 0 and t.tp == 0 for t in tallies) / len(tallies)


_SLICE_ROWS: Final[
    tuple[tuple[str, Callable[[ReviewTally], bool], str,
                Callable[[Sequence[ReviewTally]], float]], ...]
] = (
    ("zero_mention", lambda t: t.gold_zero,
     "zero_mention_agreement", _pinned_quiet_share),
    ("multi_mention", lambda t: t.tp + t.fn >= 2,
     "f1_multi_mention", lambda t: score(t).f1),
    ("candidate_emitting", lambda t: bool(t.gold_candidates),
     "f1_candidate_emitting", lambda t: score(t).f1),
)
"""Each slice: (slice name, membership by tally, stat row name, statistic).

Membership reads the *reference* side (gold in a certification, the judge in
the agreement read) — the slices describe item types of the measuring stick,
per the calibration protocol. The zero-mention slice's statistic is
quiet-agreement (the annotator also found no pinned aspect — F1 is undefined
where the reference is empty); the mention-carrying slices reuse F1.
"""


def slice_metrics(
    tallies: Sequence[ReviewTally], *, seed: int, n_resamples: int
) -> tuple[EvalMetric, ...]:
    """The per-item-type rows: each slice's n, and its statistic where n > 0.

    Every slice journals its ``n_<slice>`` denominator even at zero — a
    missing statistic row must be readable as "slice was empty", never
    "slice wasn't computed". Statistics bootstrap within the slice under the
    run's seed.
    """
    rows: list[EvalMetric] = []
    for slice_name, member, stat_name, statistic in _SLICE_ROWS:
        members = [t for t in tallies if member(t)]
        rows.append(EvalMetric(metric=f"n_{slice_name}", value=float(len(members))))
        if members:
            ci = bootstrap_ci(members, statistic, n_resamples=n_resamples, seed=seed)
            rows.append(
                EvalMetric(
                    metric=stat_name, value=statistic(members), ci_low=ci.low, ci_high=ci.high
                )
            )
    return tuple(rows)


def certify_pool(
    store: Store,
    *,
    gold_path: Path,
    ontology_path: Path | None,
    model_version: str,
    prompt_version: str,
    seed: int,
    n_resamples: int,
    started: datetime | None = None,
    excluded_app_ids: Collection[int] = EXCLUDED_APP_IDS,
    scorer: str = SCORER,
) -> EvalRun:
    """Score the pool's labels for gold's reviews and build the full run record.

    Composes the pieces — gold loader, ontology surface index, the pool reads,
    the scoring core — and stamps the result with everything a regeneration
    needs. Pure assembly over its inputs (no writes): recording the returned
    ``EvalRun`` is the caller's explicit step, so tests and dry reads can
    certify without minting. ``excluded_app_ids`` and ``scorer`` travel
    together on purpose: the exclusion rule is part of the procedure a scorer
    string names, so the judge-calibration caller passes the no-exclusion
    scope WITH ``JUDGE_SCORER`` — never one without the other.
    """
    started = started if started is not None else datetime.now(UTC)
    stamp = load_ontology_version(ontology_path)
    versions = ClassifierVersions(
        model_version=model_version,
        prompt_version=prompt_version,
        ontology_version=stamp.version,
    )
    gold_records = load_gold(gold_path)
    gold_sha256 = hashlib.sha256(gold_path.read_bytes()).hexdigest()
    index = build_surface_index(load_ontology(ontology_path))
    tallies = pool_tallies(store, gold_records, index, versions, excluded_app_ids=excluded_app_ids)
    metrics = certification_metrics(tallies, seed=seed, n_resamples=n_resamples)
    config = {
        "model_version": versions.model_version,
        "prompt_version": versions.prompt_version,
        "ontology_version": versions.ontology_version,
        "ontology_content_hash": stamp.content_hash,
        "gold_path": gold_path.as_posix(),
        "gold_sha256": gold_sha256,
        "excluded_app_ids": sorted(excluded_app_ids),
        "seed": seed,
        "n_resamples": n_resamples,
        "scorer": scorer,
    }
    canonical = json.dumps(config, sort_keys=True, separators=(",", ":"))
    return EvalRun(
        run=Provenance(
            run_id=f"certify-{started:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}",
            code_version=code_version(),
            created_at=started,
            config_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        ),
        versions=versions,
        ontology_content_hash=stamp.content_hash,
        reference_kind=ReferenceKind.GOLD_FILE,
        reference_id=gold_path.as_posix(),
        reference_sha256=gold_sha256,
        n_reference_reviews=len(gold_records),
        n_scored_reviews=len(tallies),
        seed=seed,
        n_resamples=n_resamples,
        scorer=scorer,
        metrics=metrics,
    )


def render_eval_run(eval_run: EvalRun) -> str:
    """The run as a human-readable block — what the console shows and cites.

    Public because every journal-minting front door (certify's, the agreement
    read's) renders the same record the same way.
    """
    lines = [
        f"eval run {eval_run.run.run_id} · scorer {eval_run.scorer} · "
        f"code {eval_run.run.code_version}",
        f"pool: {eval_run.versions.model_version} / {eval_run.versions.prompt_version} / "
        f"{eval_run.versions.ontology_version} ({eval_run.ontology_content_hash[:12]}…)",
        f"reference ({eval_run.reference_kind}): {eval_run.reference_id} "
        f"({eval_run.reference_sha256[:12]}…) · "
        f"scored {eval_run.n_scored_reviews}/{eval_run.n_reference_reviews} reviews · "
        f"seed {eval_run.seed} · {eval_run.n_resamples:,} resamples",
    ]
    for m in eval_run.metrics:
        interval = ""
        if m.ci_low is not None and m.ci_high is not None:
            interval = f" [{m.ci_low:.3f}–{m.ci_high:.3f}]"
        lines.append(f"  {m.metric}: {m.value:.3f}{interval}")
    return "\n".join(lines)


def main() -> None:
    """Certify, mint the journal row, verify the round-trip — the D2a front door.

    ``--judge`` is a preset, not a free dial: judge calibration changes the
    model, the scope, and the scorer identity *together* (a no-exclusion run
    under the census scorer's name would misdescribe its own procedure), so
    the three are one flag.
    """
    parser = argparse.ArgumentParser(
        description="Score the pool's labels against gold and journal the certification."
    )
    parser.add_argument("--db", type=Path, default=Path("data/steamlens.sqlite3"),
                        help="the label-pool database (default: data/steamlens.sqlite3)")
    parser.add_argument("--gold", type=Path, default=Path("eval/gold/gold.jsonl"),
                        help="the gold JSONL artifact (default: eval/gold/gold.jsonl)")
    parser.add_argument("--ontology", type=Path, default=None,
                        help="ontology artifact path (default: packaged v1; census pins v2)")
    parser.add_argument("--model", default=None,
                        help="the pool triple's model_version "
                             "(default: the census's; with --judge, the judge's)")
    parser.add_argument("--prompt", default=PROMPT_VERSION,
                        help="the pool triple's prompt_version (default: the census's)")
    parser.add_argument("--judge", action="store_true",
                        help="score the judge's envelope set: judge model, all gold "
                             "games in scope, scorer judge-vs-gold/1")
    parser.add_argument("--seed", type=int, default=20260718)
    parser.add_argument("--resamples", type=int, default=10_000)
    parser.add_argument("--dry-run", action="store_true",
                        help="score and print without journaling the run")
    args = parser.parse_args()

    default_model = JUDGE_MODEL_ID if args.judge else MODEL_ID
    with Store(args.db) as store:
        eval_run = certify_pool(
            store,
            gold_path=args.gold,
            ontology_path=args.ontology,
            model_version=args.model if args.model is not None else default_model,
            prompt_version=args.prompt,
            seed=args.seed,
            n_resamples=args.resamples,
            excluded_app_ids=() if args.judge else EXCLUDED_APP_IDS,
            scorer=JUDGE_SCORER if args.judge else SCORER,
        )
        print(render_eval_run(eval_run))
        if args.dry_run:
            print("dry run — nothing journaled")
            return
        store.eval_runs.record(eval_run)
        if store.eval_runs.get(eval_run.run.run_id) != eval_run:
            raise SystemExit("round-trip verification failed — journaled row differs")
        print(f"journaled + verified -> eval_runs[{eval_run.run.run_id}]")


if __name__ == "__main__":
    main()
