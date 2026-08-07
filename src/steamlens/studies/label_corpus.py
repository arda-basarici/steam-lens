"""The C1 corpus-labeling driver — the census dispatch, narrated and resumable.

The first M1 labels land through this entry shell: frozen corpus → usable pool
→ selection → N-review batches → the classify prompt/parse pair → the LLM door
→ the label pool. The driver owns orchestration only; every hard guarantee it
leans on lives in a seam it composes — bought responses in the content-keyed
cache, spend in the ledger, resume in the selection query (an interrupted run
relaunches and pays only for what never completed). Design record: the
census-dispatch decisions in DESIGN's labeling-engine section (settled
2026-07-19); the dispatch config itself was frozen at the v2 codebook
certification ruling.

The run's shell — the tee'd log and the deliberate two-``Store`` split — is
``dispatch.run_shell``'s contract; the two-writer reasoning lives there once.

The run aborts loud — never warn-and-continue — on: a supply count that
contradicts the ruled census, a mid-run change in the provider-reported model
version (the pool's "one annotator" claim), provider trouble outliving the
client's retries, and the budget cap. Every abort is resume-clean.
"""

from __future__ import annotations

import argparse
import os
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from steamlens.contracts import (
    ClassifierVersions,
    OntologyVersion,
    Origin,
    Provenance,
    Review,
    ReviewClassification,
    Sink,
    StageKind,
)
from steamlens.core.classify import PROMPT_VERSION
from steamlens.core.normalize import build_surface_index
from steamlens.corpus import EXCLUDED_APP_IDS, corpus_review_files, read_reviews_file
from steamlens.dispatch import (
    BatchOutcome,
    DriftWatch,
    RunAbort,
    RunTotals,
    chunk,
    classify_batch,
    code_version,
    config_hash,
    mint_run_id,
    narrate,
    run_context,
    run_pass,
    write_manifest,
)
from steamlens.dispatch.census_arm import KEY_ENV, MODEL_ID, build_client
from steamlens.llm_client import (
    AtCapacityError,
    LlmUnavailableError,
    ProviderEntry,
    openai_compat_entry,
)
from steamlens.llm_client.openai_compat import DEEPSEEK_BASE_URL
from steamlens.ontology import load_ontology, load_ontology_version
from steamlens.store import Store

RULED_CENSUS_SUPPLY: Final = 135_260
"""The census-slice ruling's usable-pool size — the default ingest assertion."""

# The refusal circuit breaker: per-batch provider refusals feed the failure
# sweep (a content-filter rejection is a property of one batch's text), but a
# systemic 4xx — a revoked key, a broken payload — must abort loud, never
# become thousands of silent failure marks. Census evidence: refusals ran
# ~1 per 10K requests (the Tiananmen-line review, 2026-07-20).
_REFUSED_BATCH_LIMIT: Final = 20

_EPOCH: Final = datetime.fromtimestamp(0, tz=UTC)

_STAGE: Final = "c1.driver"


@dataclass(frozen=True, slots=True)
class RunConfig:
    """One invocation's resolved dial — everything the manifest reproduces.

    ``ontology_path`` of ``None`` means the packaged artifact (v1, gold's
    identity pin); the census passes v2 explicitly per the frozen dispatch
    config. ``expected_supply`` is the ingest assertion — the ruled census by
    default, overridden only by tests and deliberate re-rulings. ``limit``
    caps the *selection* (the pilot's dial); ingest always covers the corpus.
    """

    corpus_dir: Path
    db_path: Path
    runs_dir: Path
    ontology_path: Path | None
    n: int
    max_workers: int
    budget_usd: float
    limit: int | None
    expected_supply: int


def _config_hash(cfg: RunConfig, ontology_version: str, ontology_content_hash: str) -> str:
    """A fingerprint of the decision-relevant config — checkable, never trusted."""
    return config_hash({
        "model": MODEL_ID,
        "prompt_version": PROMPT_VERSION,
        "ontology_version": ontology_version,
        "ontology_content_hash": ontology_content_hash,
        "n": cfg.n,
        "max_workers": cfg.max_workers,
        "budget_usd": cfg.budget_usd,
        "limit": cfg.limit,
        "expected_supply": cfg.expected_supply,
    })


def build_manifest(
    cfg: RunConfig,
    run: Provenance,
    stamp: OntologyVersion,
    totals: RunTotals,
    *,
    supply: int,
    already_settled: int,
    selected: int,
    finished: datetime,
    run_cost: float,
    ledger_lifetime: float,
    aborted: str | None,
) -> dict[str, object]:
    """The run's manifest as pure data assembly — its honesty claims unit-assertable.

    The claims: an aborted run still stamps its true counts, tokens, and
    spend (``aborted`` discloses, never suppresses), and ``started_at`` is
    ``run.created_at`` — one clock, the same instant the run id was minted
    from and the ledger's run-cost window opened at.
    """
    return {
        "run_id": run.run_id,
        "code_version": run.code_version,
        "config_hash": run.config_hash,
        "model": MODEL_ID,
        "model_versions_seen": sorted(totals.model_versions_seen),
        "prompt_version": PROMPT_VERSION,
        "ontology_version": stamp.version,
        "ontology_content_hash": stamp.content_hash,
        "ontology_override": None if cfg.ontology_path is None else str(cfg.ontology_path),
        "n": cfg.n,
        "max_workers": cfg.max_workers,
        "budget_usd": cfg.budget_usd,
        "limit": cfg.limit,
        "started_at": run.created_at.isoformat(),
        "finished_at": finished.isoformat(),
        "reviews": {
            "supply": supply,
            "already_settled": already_settled,
            "selected": selected,
            "labeled": totals.labeled,
            "empty_envelopes": totals.empty_envelopes,
            "salvaged_from_partial_batches": totals.salvaged,
            "evidence_repairs": totals.repairs,
            "unattributable_rows": totals.unattributable,
            "rebatched": totals.rebatched,
            "isolated": totals.isolated,
            "failed_durable": totals.failed_durable,
            "refused_batches": totals.refused_batches,
        },
        "requests": totals.batches,
        "tokens": {
            "prompt": totals.prompt_tokens,
            "output": totals.output_tokens,
            "thinking": totals.thinking_tokens,
        },
        "cost_usd_run": run_cost,
        "cost_usd_ledger_lifetime": ledger_lifetime,
        "aborted": aborted,
    }


def ingest_corpus(cfg: RunConfig, store: Store, sink: Sink) -> None:
    """Walk the usable games into the reviews table, then assert the ruled supply.

    Idempotent on every start (ingest skips ids already present). The supply
    assertion runs against the *table* — the set selection draws from — and a
    mismatch aborts before any money moves: the census was priced on exactly
    ``expected_supply`` reviews, so a differing count means the corpus files
    or the usable filter drifted from what the ruling saw. Both the assertion
    and the selection count only usable-scope rows: eval dispatches backfill
    out-of-scope gold reviews (the judge's CS2 rows) into the table for the
    label pool's foreign key, and those are never this driver's to price or buy.
    """
    files = corpus_review_files(cfg.corpus_dir)
    total = non_english = empty = usable = inserted = 0
    for path in files:
        result = read_reviews_file(path)
        inserted += store.reviews.put_many(result.reviews)
        total += result.total
        non_english += result.non_english
        empty += result.empty
        usable += result.usable
    narrate(
        sink, "c1.ingest", StageKind.DONE,
        f"ingest: {len(files)} games · {total:,} on disk → {non_english:,} non-English "
        f"+ {empty:,} empty dropped → {usable:,} usable ({inserted:,} newly inserted)",
    )
    count = store.reviews.count(excluding_app_ids=EXCLUDED_APP_IDS)
    if count != cfg.expected_supply:
        raise RunAbort(
            f"supply assertion failed: reviews table holds {count:,}, the ruling "
            f"expects {cfg.expected_supply:,} — corpus or filter drifted; refusing to dispatch"
        )


def _write_outcome(
    outcome: BatchOutcome,
    store: Store,
    versions: ClassifierVersions,
    run: Provenance,
    attempt: str,
    totals: RunTotals,
    drift: DriftWatch,
    sink: Sink,
) -> list[Review]:
    """Consume one outcome on the main thread: envelopes in, failures forward.

    Returns the batch members owed another attempt. On the final (``isolate``)
    attempt nothing is returned — a review failing alone gets its durable
    failure mark instead, closing its selection under these versions. A
    provider-refused outcome skips the drift watch (nothing served the call)
    and counts toward the refusal circuit breaker.
    """
    if outcome.refusal is not None:
        totals.refused_batches += 1
        narrate(
            sink, _STAGE, StageKind.WARN,
            f"provider refused a batch ({attempt}, {len(outcome.batch)} reviews): "
            f"{outcome.refusal}",
        )
        if totals.refused_batches > _REFUSED_BATCH_LIMIT:
            raise RunAbort(
                f"{totals.refused_batches} provider-refused batches exceeds the "
                f"{_REFUSED_BATCH_LIMIT}-batch circuit breaker — a content filter hits "
                f"single texts, not this many; suspect a systemic request problem"
            )
    else:
        drift.check(outcome.model_version)
        totals.model_versions_seen.add(outcome.model_version)
    totals.batches += 1
    totals.prompt_tokens += outcome.usage.prompt_tokens
    totals.output_tokens += outcome.usage.output_tokens
    totals.thinking_tokens += outcome.usage.thinking_tokens
    totals.repairs += len(outcome.parse.repairs)
    had_failures = bool(outcome.parse.failures)
    for parsed in outcome.parse.parsed:
        review = outcome.batch[parsed.idx]
        store.labels.put(
            ReviewClassification(
                review_id=review.review_id,
                origin=Origin.SURVEY,
                versions=versions,
                run=run,
                mentions=parsed.mentions,
            )
        )
        totals.labeled += 1
        if not parsed.mentions:
            totals.empty_envelopes += 1
        if had_failures:
            totals.salvaged += 1
    retry: list[Review] = []
    for failure in outcome.parse.failures:
        if failure.idx is None or not 0 <= failure.idx < len(outcome.batch):
            totals.unattributable += 1
            continue
        review = outcome.batch[failure.idx]
        if attempt == "isolate":
            store.labels.record_failure(
                review.review_id, versions, run.run_id, failure.reason
            )
            totals.failed_durable += 1
            narrate(
                sink, _STAGE, StageKind.WARN,
                f"review {review.review_id} unclassifiable even alone: {failure.reason}",
            )
        else:
            retry.append(review)
    return retry


def execute_run(cfg: RunConfig, entry: ProviderEntry, started: datetime | None = None) -> int:
    """One driver invocation end to end; returns the process exit code.

    The composition root for a run: identity, stores (two connections — see
    the module docstring), client, ontology, sinks — then ingest, select,
    label in the three-pass shape, and write the manifest whether the run
    finished or aborted. ``entry`` is injected so tests drive the whole path
    with a fake provider; production passes the DeepSeek entry.
    """
    started = started if started is not None else datetime.now(UTC)
    run_id = mint_run_id("c1", started)
    run_dir = cfg.runs_dir / run_id

    stamp = load_ontology_version(cfg.ontology_path)
    ontology = load_ontology(cfg.ontology_path)
    surface_index = build_surface_index(ontology)
    versions = ClassifierVersions(
        model_version=MODEL_ID,
        prompt_version=PROMPT_VERSION,
        ontology_version=stamp.version,
    )
    run = Provenance(
        run_id=run_id,
        code_version=code_version(),
        created_at=started,
        config_hash=_config_hash(cfg, stamp.version, stamp.content_hash),
    )

    totals = RunTotals()
    drift = DriftWatch()
    aborted: str | None = None
    selected = already_labeled = supply = 0

    with run_context(cfg.runs_dir, run_id, cfg.db_path) as (sink, client_store, driver_store):
        client = build_client(entry, cfg.budget_usd, cfg.n, client_store, sink)
        lifetime = driver_store.spend_ledger.cost_since(_EPOCH)
        narrate(
            sink, _STAGE, StageKind.STARTED,
            f"run {run_id} · code {run.code_version} · {MODEL_ID} · N={cfg.n} · "
            f"workers {cfg.max_workers} · ontology {stamp.version} · "
            f"budget ${cfg.budget_usd:.2f} this run · ledger holds ${lifetime:.4f} to date",
        )
        try:
            ingest_corpus(cfg, driver_store, sink)
            supply = driver_store.reviews.count(excluding_app_ids=EXCLUDED_APP_IDS)
            pending = driver_store.reviews.unlabeled_under(
                versions, excluding_app_ids=EXCLUDED_APP_IDS
            )
            already_labeled = supply - len(pending)
            if cfg.limit is not None:
                pending = pending[: cfg.limit]
            selected = len(pending)
            narrate(
                sink, _STAGE, StageKind.PROGRESS,
                f"selection: {selected:,} to label under {versions.model_version}/"
                f"{versions.prompt_version}/{versions.ontology_version} "
                f"({already_labeled:,} of {supply:,} already settled)",
            )
            if pending:
                driver_store.labels.record_run(run)

                def worker(batch: tuple[Review, ...]) -> BatchOutcome:
                    return classify_batch(client, ontology, surface_index, batch)

                def consume(outcome: BatchOutcome, attempt: str) -> list[Review]:
                    return _write_outcome(
                        outcome, driver_store, versions, run, attempt, totals, drift, sink
                    )

                with ThreadPoolExecutor(max_workers=cfg.max_workers) as pool:
                    failed = run_pass(
                        chunk(pending, cfg.n), "initial", worker,
                        lambda o: consume(o, "initial"), pool, sink,
                        stage=_STAGE, warmup=True,
                    )
                    if failed:
                        narrate(
                            sink, _STAGE, StageKind.PROGRESS,
                            f"rebatch: {len(failed)} failed rows retried at N={cfg.n}",
                        )
                        totals.rebatched = len(failed)
                        failed = run_pass(
                            chunk(failed, cfg.n), "rebatch", worker,
                            lambda o: consume(o, "rebatch"), pool, sink,
                            stage=_STAGE, warmup=False,
                        )
                    if failed:
                        narrate(
                            sink, _STAGE, StageKind.PROGRESS,
                            f"isolate: {len(failed)} rows alone at N=1",
                        )
                        totals.isolated = len(failed)
                        run_pass(
                            chunk(failed, 1), "isolate", worker,
                            lambda o: consume(o, "isolate"), pool, sink,
                            stage=_STAGE, warmup=False,
                        )
        except KeyboardInterrupt:
            aborted = "keyboard interrupt"
        except (RunAbort, LlmUnavailableError, AtCapacityError) as exc:
            aborted = str(exc)
        except Exception as exc:  # manifest still written even when dying loud
            aborted = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()

        run_cost = driver_store.spend_ledger.cost_since(started)
        manifest = build_manifest(
            cfg, run, stamp, totals,
            supply=supply,
            already_settled=already_labeled,
            selected=selected,
            finished=datetime.now(UTC),
            run_cost=run_cost,
            ledger_lifetime=driver_store.spend_ledger.cost_since(_EPOCH),
            aborted=aborted,
        )
        manifest_path = write_manifest(run_dir, manifest)
        outcome_kind = StageKind.WARN if aborted else StageKind.DONE
        narrate(
            sink, _STAGE, outcome_kind,
            (f"ABORTED: {aborted}" if aborted else "run complete")
            + f" · labeled {totals.labeled:,}/{selected:,} (empty {totals.empty_envelopes:,}, "
            f"failed durable {totals.failed_durable}) · ${run_cost:.4f} this run · "
            f"manifest {manifest_path}",
        )
    return 1 if aborted else 0


def main() -> None:
    """Parse the dial, build the DeepSeek entry, run. The census's front door."""
    parser = argparse.ArgumentParser(
        description="Label the corpus census into the pool (C1). Pilot with --limit first."
    )
    parser.add_argument("--corpus", type=Path, required=True,
                        help="directory holding the <app_id>_reviews.jsonl corpus files")
    parser.add_argument("--db", type=Path, default=Path("data/steamlens.sqlite3"),
                        help="the label-pool database (default: data/steamlens.sqlite3)")
    parser.add_argument("--runs-dir", type=Path, default=Path("data/runs"),
                        help="where run manifests and logs land (default: data/runs)")
    parser.add_argument("--ontology", type=Path, default=None,
                        help="ontology artifact path (default: packaged v1; census passes v2)")
    parser.add_argument("--n", type=int, default=10, help="reviews per request (certified: 10)")
    parser.add_argument("--max-workers", type=int, default=1,
                        help="concurrent requests (default 1; census dispatches at 10)")
    parser.add_argument("--budget-usd", type=float, required=True,
                        help="this run's spend cap (ruled: pilot 1, census 8)")
    parser.add_argument("--limit", type=int, default=None,
                        help="label only the first K selected reviews (the pilot dial)")
    parser.add_argument("--expect-supply", type=int, default=RULED_CENSUS_SUPPLY,
                        help="ingest assertion (default: the ruled census supply)")
    args = parser.parse_args()

    key = os.environ.get(KEY_ENV)
    if not key:
        raise SystemExit(f"missing {KEY_ENV} in the environment — set it and rerun")
    cfg = RunConfig(
        corpus_dir=args.corpus,
        db_path=args.db,
        runs_dir=args.runs_dir,
        ontology_path=args.ontology,
        n=args.n,
        max_workers=args.max_workers,
        budget_usd=args.budget_usd,
        limit=args.limit,
        expected_supply=args.expect_supply,
    )
    entry = openai_compat_entry(key, base_url=DEEPSEEK_BASE_URL)
    raise SystemExit(execute_run(cfg, entry))


if __name__ == "__main__":
    main()
