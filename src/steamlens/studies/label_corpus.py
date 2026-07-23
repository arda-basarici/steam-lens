"""The C1 corpus-labeling driver — the census dispatch, narrated and resumable.

The first M1 labels land through this entry shell: frozen corpus → usable pool
→ selection → N-review batches → the classify prompt/parse pair → the LLM door
→ the label pool. The driver owns orchestration only; every hard guarantee it
leans on lives in a seam it composes — bought responses in the content-keyed
cache, spend in the ledger, resume in the selection query (an interrupted run
relaunches and pays only for what never completed). Design record: DESIGN.md's
C1 labeling driver entry (2026-07-19); the dispatch config itself was frozen at
the C0.5 certification ruling.

Two ``Store`` instances open the one database file on purpose: the client's
cache/ledger writes happen on worker threads over the first connection, all
label-pool writes happen on the main thread over the second. Transactions are
connection-scoped, so this split is what makes a worker's mid-call cache write
unable to land inside (and be rolled back with) an envelope transaction — the
store's WAL + busy-timeout provisioning carries the two-writer coordination.

The run aborts loud — never warn-and-continue — on: a supply count that
contradicts the ruled census, a mid-run change in the provider-reported model
version (the pool's "one annotator" claim), provider trouble outliving the
client's retries, and the budget cap. Every abort is resume-clean.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import traceback
import uuid
from collections.abc import Callable, Iterator, Mapping
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, TextIO

from steamlens.contracts import (
    AspectOntology,
    ClassifierVersions,
    LlmRequest,
    LlmStage,
    Origin,
    Provenance,
    Review,
    ReviewClassification,
    SinkEvent,
    StageEvent,
    StageKind,
    TokenUsage,
)
from steamlens.core.classify import (
    PROMPT_VERSION,
    BatchParseResult,
    IdxFailure,
    build_classify_prompt,
    parse_classify_response,
)
from steamlens.core.normalize import build_surface_index
from steamlens.llm_client import (
    AtCapacityError,
    GenerationIncompleteError,
    LlmClient,
    LlmClientConfig,
    LlmUnavailableError,
    ModelSpec,
    ProviderEntry,
    ProviderPermanentError,
    Route,
    openai_compat_entry,
)
from steamlens.llm_client.openai_compat import DEEPSEEK_BASE_URL
from steamlens.ontology import load_ontology, load_ontology_version
from steamlens.store import Store
from steamlens.studies.local_corpus import (
    EXCLUDED_APP_IDS,
    corpus_review_files,
    read_reviews_file,
)

RULED_CENSUS_SUPPLY: Final = 135_260
"""The census-slice ruling's usable-pool size — the default ingest assertion."""

MODEL_ID: Final = "deepseek-v4-flash"
"""The requested model id — the label key's ``model_version`` (keys are
contracts; the provider-reported version is journaled per call instead)."""

_PROVIDER: Final = "deepseek"
_KEY_ENV: Final = "DEEPSEEK_API_KEY"
# The bake-off's measured output sizing: the base holds one worst-case dense
# review, the per-review term covers dense batches, the cap is DeepSeek's.
_OUTPUT_BASE: Final = 2_048
_OUTPUT_PER_REVIEW: Final = 200
_OUTPUT_CAP: Final = 8_192
# Politeness backstop only — DeepSeek's envelope is concurrency-based (no rpm);
# high enough that the worker pool, not pacing, is the real throttle.
_RPM: Final = 600
_INPUT_USD_PER_1M: Final = 0.14
_OUTPUT_USD_PER_1M: Final = 0.28
# The refusal circuit breaker: per-batch provider refusals feed the failure
# sweep (a content-filter rejection is a property of one batch's text), but a
# systemic 4xx — a revoked key, a broken payload — must abort loud, never
# become thousands of silent failure marks. Census evidence: refusals ran
# ~1 per 10K requests (the Tiananmen-line review, 2026-07-20).
_REFUSED_BATCH_LIMIT: Final = 20

_EPOCH: Final = datetime.fromtimestamp(0, tz=UTC)


class RunAbort(Exception):
    """A condition the design says stops the run loudly; always resume-clean."""


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


@dataclass(slots=True)
class RunTotals:
    """The run's accumulating counters — one place, narrated and manifested."""

    batches: int = 0
    labeled: int = 0
    empty_envelopes: int = 0
    salvaged: int = 0
    repairs: int = 0
    unattributable: int = 0
    rebatched: int = 0
    isolated: int = 0
    failed_durable: int = 0
    refused_batches: int = 0
    prompt_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    model_versions_seen: set[str] = field(default_factory=set[str])


@dataclass(frozen=True, slots=True)
class BatchOutcome:
    """One dispatched batch's full account, carried from worker to writer.

    ``refusal`` is set when the provider rejected the whole request (a content
    filter, typically) — the parse then carries every idx as failed with the
    refusal as reason, no tokens were reported, and ``model_version`` is the
    empty string (nothing served the call, so the drift watch skips it).
    """

    batch: tuple[Review, ...]
    parse: BatchParseResult
    model_version: str
    finish: str
    usage: TokenUsage
    refusal: str | None = None


class TeeSink:
    """Narration to the console and a tail-able run log; metrics to the log only.

    Stage events are the human story — both surfaces get them. Metric events
    (six per model call) would drown a console at census scale, so they land
    only in the log file, greppable after the fact. The file is line-buffered
    so a second-pane ``tail`` follows the run live.
    """

    def __init__(self, log: TextIO) -> None:
        self._log = log

    def emit(self, event: SinkEvent) -> None:
        stamp = datetime.now(UTC).strftime("%H:%M:%S")
        if isinstance(event, StageEvent):
            line = f"[{stamp}] {event.stage} {event.kind.value}: {event.message}"
            print(line)
            self._log.write(line + "\n")
        else:
            self._log.write(
                f"[{stamp}] metric {event.stage} {event.name}={event.value} {event.unit}\n"
            )


def code_version() -> str:
    """The repo's short commit sha, ``+dirty`` when the tree has changes.

    Provenance is a design pillar — a run that cannot state what code produced
    it refuses to start, so a failed ``git`` call raises rather than stamping
    ``unknown``.
    """
    repo = Path(__file__).resolve().parents[3]
    sha = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=repo, capture_output=True, text=True, check=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo, capture_output=True, text=True, check=True,
    ).stdout.strip()
    return f"{sha}+dirty" if status else sha


def _config_hash(cfg: RunConfig, ontology_version: str, ontology_content_hash: str) -> str:
    """A fingerprint of the decision-relevant config — checkable, never trusted."""
    resolved = {
        "model": MODEL_ID,
        "prompt_version": PROMPT_VERSION,
        "ontology_version": ontology_version,
        "ontology_content_hash": ontology_content_hash,
        "n": cfg.n,
        "max_workers": cfg.max_workers,
        "budget_usd": cfg.budget_usd,
        "limit": cfg.limit,
        "expected_supply": cfg.expected_supply,
    }
    canonical = json.dumps(resolved, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_client(
    entry: ProviderEntry, budget_usd: float, n: int, client_store: Store, sink: TeeSink
) -> LlmClient:
    """The dispatch-config client over the *client's* store connection."""
    config = LlmClientConfig(
        routes={
            LlmStage.CLASSIFY: Route(
                provider=_PROVIDER,
                model=MODEL_ID,
                max_output_tokens=min(_OUTPUT_CAP, _OUTPUT_BASE + _OUTPUT_PER_REVIEW * n),
                params={
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                    "thinking": {"type": "disabled"},
                },
            )
        },
        models={
            MODEL_ID: ModelSpec(
                rpm=_RPM,
                rpd=None,
                input_usd_per_1m=_INPUT_USD_PER_1M,
                output_usd_per_1m=_OUTPUT_USD_PER_1M,
            )
        },
        budget_usd=budget_usd,
    )
    return LlmClient(
        config,
        client_store.responses,
        client_store.spend_ledger,
        sink,
        registry={_PROVIDER: entry},
    )


def _narrate(sink: TeeSink, kind: StageKind, message: str, *, stage: str = "c1.driver") -> None:
    sink.emit(StageEvent(stage=stage, kind=kind, message=message))


def ingest_corpus(cfg: RunConfig, store: Store, sink: TeeSink) -> None:
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
    _narrate(
        sink, StageKind.DONE,
        f"ingest: {len(files)} games · {total:,} on disk → {non_english:,} non-English "
        f"+ {empty:,} empty dropped → {usable:,} usable ({inserted:,} newly inserted)",
        stage="c1.ingest",
    )
    count = store.reviews.count(excluding_app_ids=EXCLUDED_APP_IDS)
    if count != cfg.expected_supply:
        raise RunAbort(
            f"supply assertion failed: reviews table holds {count:,}, the ruling "
            f"expects {cfg.expected_supply:,} — corpus or filter drifted; refusing to dispatch"
        )


def classify_batch(
    client: LlmClient,
    ontology: AspectOntology,
    surface_index: Mapping[str, str],
    batch: tuple[Review, ...],
) -> BatchOutcome:
    """One batch through prompt → door → parse; the worker-side unit of work.

    A truncated-or-refused generation is salvaged, not lost: its spend is
    already journaled and cached, so the partial text is parsed and the finish
    reason rides the outcome. A ``ProviderPermanentError`` — the provider
    rejecting the request itself (DeepSeek's content filter, live-observed
    2026-07-20) — becomes an all-rows-failed outcome so the ordinary sweep
    isolates the offending review to its durable mark instead of the whole
    run dying on one batch forever (composition is deterministic — an abort
    here would re-form the same batch every relaunch). Provider trouble
    outliving the client's retries and budget refusals still propagate —
    those end the run, not the batch.
    """
    texts = [review.text for review in batch]
    prompt = build_classify_prompt(texts, ontology)
    try:
        response = client.complete(LlmRequest(stage=LlmStage.CLASSIFY, prompt=prompt))
        finish = response.finish_reason.value
    except GenerationIncompleteError as exc:
        response = exc.response
        finish = f"incomplete:{exc.reason.value}"
    except ProviderPermanentError as exc:
        reason = f"provider refused the request: {exc}"
        return BatchOutcome(
            batch=batch,
            parse=BatchParseResult(
                parsed=(),
                failures=tuple(IdxFailure(idx, reason) for idx in range(len(batch))),
                repairs=(),
            ),
            model_version="",
            finish="refused",
            usage=TokenUsage(prompt_tokens=0, output_tokens=0, thinking_tokens=0),
            refusal=str(exc),
        )
    return BatchOutcome(
        batch=batch,
        parse=parse_classify_response(response.text, texts, surface_index),
        model_version=response.model_version,
        finish=finish,
        usage=response.usage,
    )


class DriftWatch:
    """Holds the first provider-reported model version; a change aborts the run.

    A silent provider roll mid-census would split the pool's "one annotator"
    claim, so the change is a stop-and-rule event — resume is free, and the
    envelopes already written carry their true build in the spend ledger.
    """

    def __init__(self) -> None:
        self._first: str | None = None

    def check(self, reported: str) -> None:
        if self._first is None:
            self._first = reported
            return
        if reported != self._first:
            raise RunAbort(
                f"model version drift: run started under {self._first!r}, provider now "
                f"reports {reported!r} — stopping so the pool keeps one annotator; "
                f"per-call versions are in the spend ledger"
            )


def _write_outcome(
    outcome: BatchOutcome,
    store: Store,
    versions: ClassifierVersions,
    run: Provenance,
    attempt: str,
    totals: RunTotals,
    drift: DriftWatch,
    sink: TeeSink,
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
        _narrate(
            sink, StageKind.WARN,
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
            _narrate(
                sink, StageKind.WARN,
                f"review {review.review_id} unclassifiable even alone: {failure.reason}",
            )
        else:
            retry.append(review)
    return retry


def _chunk(reviews: tuple[Review, ...], n: int) -> Iterator[tuple[Review, ...]]:
    for start in range(0, len(reviews), n):
        yield reviews[start : start + n]


def _run_pass(
    reviews: tuple[Review, ...],
    batch_size: int,
    attempt: str,
    worker: Callable[[tuple[Review, ...]], BatchOutcome],
    consume: Callable[[BatchOutcome, str], list[Review]],
    pool: ThreadPoolExecutor,
    sink: TeeSink,
    *,
    warmup: bool,
) -> list[Review]:
    """One labeling pass: chunk, dispatch, consume as completed on this thread.

    ``warmup`` runs the first batch synchronously before the pool opens, so
    the provider's prefix cache is seeded by one completed request instead of
    ``max_workers`` concurrent cold misses — the pilot's cost-per-review then
    measures steady-state behavior. Consumption happens as futures finish;
    total ordering is not needed because every write is per-review keyed.
    """
    batches = list(_chunk(reviews, batch_size))
    total = len(batches)
    failed: list[Review] = []
    done = 0
    start_at = 0
    if warmup and batches:
        failed.extend(consume(worker(batches[0]), attempt))
        done += 1
        _narrate(sink, StageKind.PROGRESS, f"{attempt}: warmup batch 1/{total} consumed")
        start_at = 1
    pending: set[Future[BatchOutcome]] = {
        pool.submit(worker, batch) for batch in batches[start_at:]
    }
    try:
        while pending:
            completed, pending = wait(pending, return_when=FIRST_COMPLETED)
            for future in completed:
                failed.extend(consume(future.result(), attempt))
                done += 1
                if done % 10 == 0 or done == total:
                    _narrate(
                        sink, StageKind.PROGRESS, f"{attempt}: batch {done}/{total} consumed"
                    )
    except BaseException:
        # Abort means stop: queued batches must not keep dispatching (and
        # spending) behind a dying run. In-flight requests finish and cache
        # harmlessly; cancellation only stops what never started.
        for future in pending:
            future.cancel()
        raise
    return failed


def execute_run(cfg: RunConfig, entry: ProviderEntry, started: datetime | None = None) -> int:
    """One driver invocation end to end; returns the process exit code.

    The composition root for a run: identity, stores (two connections — see
    the module docstring), client, ontology, sinks — then ingest, select,
    label in the three-pass shape, and write the manifest whether the run
    finished or aborted. ``entry`` is injected so tests drive the whole path
    with a fake provider; production passes the DeepSeek entry.
    """
    started = started if started is not None else datetime.now(UTC)
    run_id = f"c1-{started:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"
    run_dir = cfg.runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

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

    with (
        (run_dir / "run.log").open("a", encoding="utf-8", buffering=1) as log,
        Store(cfg.db_path) as client_store,
        Store(cfg.db_path) as driver_store,
    ):
        sink = TeeSink(log)
        client = build_client(entry, cfg.budget_usd, cfg.n, client_store, sink)
        lifetime = driver_store.spend_ledger.cost_since(_EPOCH)
        _narrate(
            sink, StageKind.STARTED,
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
            _narrate(
                sink, StageKind.PROGRESS,
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
                    failed = _run_pass(
                        pending, cfg.n, "initial", worker, consume, pool, sink, warmup=True
                    )
                    if failed:
                        _narrate(
                            sink, StageKind.PROGRESS,
                            f"rebatch: {len(failed)} failed rows retried at N={cfg.n}",
                        )
                        totals.rebatched = len(failed)
                        failed = _run_pass(
                            tuple(failed), cfg.n, "rebatch", worker, consume, pool, sink,
                            warmup=False,
                        )
                    if failed:
                        _narrate(
                            sink, StageKind.PROGRESS,
                            f"isolate: {len(failed)} rows alone at N=1",
                        )
                        totals.isolated = len(failed)
                        _run_pass(
                            tuple(failed), 1, "isolate", worker, consume, pool, sink,
                            warmup=False,
                        )
        except KeyboardInterrupt:
            aborted = "keyboard interrupt"
        except (RunAbort, LlmUnavailableError, AtCapacityError) as exc:
            aborted = str(exc)
        except Exception as exc:  # manifest still written even when dying loud
            aborted = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()

        run_cost = driver_store.spend_ledger.cost_since(started)
        finished = datetime.now(UTC)
        manifest: dict[str, object] = {
            "run_id": run_id,
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
            "started_at": started.isoformat(),
            "finished_at": finished.isoformat(),
            "reviews": {
                "supply": supply,
                "already_settled": already_labeled,
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
            "cost_usd_ledger_lifetime": driver_store.spend_ledger.cost_since(_EPOCH),
            "aborted": aborted,
        }
        (run_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        outcome_kind = StageKind.WARN if aborted else StageKind.DONE
        _narrate(
            sink, outcome_kind,
            (f"ABORTED: {aborted}" if aborted else "run complete")
            + f" · labeled {totals.labeled:,}/{selected:,} (empty {totals.empty_envelopes:,}, "
            f"failed durable {totals.failed_durable}) · ${run_cost:.4f} this run · "
            f"manifest {run_dir / 'manifest.json'}",
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

    key = os.environ.get(_KEY_ENV)
    if not key:
        raise SystemExit(f"missing {_KEY_ENV} in the environment — set it and rerun")
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
