"""The cold-analysis runner — one job's pipeline over the certified seams.

The serving skeleton's spine: resolve → size the English pool → plan → fetch
and classify overlapped → labels persisted, narrated end to end over the
job's sink. Everything statistical is a certified seam composed, never
reimplemented — the plan comes from ``core/sampling``'s compiler (the study's
certification target), the fetch runs the validated windowed path with the
plan contract's quota stop, and the classify leg is the census instrument
verbatim (same worker, same model identity, same three-pass retry ladder).
Mint, detect, and compose land with their own build steps; the spine ends at
the label pool today.

The overlap seam is the runner's one piece of concurrency: a fetch producer
thread pushes each *completed window* into a bounded queue while the job
thread batches arriving members to the classify pool and consumes outcomes
as they finish. Windows — not pages — are the streaming unit, deliberately:
a windowed walk that goes dirty discards its pages and re-walks via the
cursor fallback, so a page's sample membership is not final until its whole
window's path outcome is known; the design prose said "pages," and the
fallback semantics narrowed it here.

The size rule branches on the ENGLISH pool ("English-only stands everywhere"
— the study certified English-only draws), read pre-fetch via the wire-
validated English totals query. A sampled plan compiles at the certified
target against the all-language histogram, so windows under-deliver English
members at any share below 100% — accepted and disclosed (the realized n is
honest, Wilson at the actual n errs conservative) rather than inflated by an
uncertified share correction. The page-budget guard prices every plan before
fetching: an over-budget take-all degrades to the sampling branch with
disclosure, an over-budget sampled plan refuses the job loudly.
"""

from __future__ import annotations

import threading
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from queue import Empty, Full, Queue
from typing import Final

from steamlens.contracts import (
    ClassifierVersions,
    HistogramSnapshot,
    IdentityVerdict,
    Origin,
    PathOutcome,
    Provenance,
    Review,
    ReviewClassification,
    SamplingPolicy,
    SamplingPolicyKind,
    Sink,
    StageKind,
    WindowFetchResult,
)
from steamlens.core.classify import PROMPT_VERSION
from steamlens.core.normalize import build_surface_index
from steamlens.core.sampling import compile_plan
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
    run_pass,
)
from steamlens.dispatch.census_arm import MODEL_ID, build_client
from steamlens.llm_client import LlmClient, ProviderEntry
from steamlens.ontology import load_ontology, load_ontology_version
from steamlens.serve.config import ServeConfig
from steamlens.steam_client import SteamClient
from steamlens.store import Store

# Whole-life window framing for the take-all branch: the start margin only
# needs to clear one rollup bucket (buckets stamp at period start), the end
# margin absorbs reviews landing mid-job. Steam honors the window server-side,
# so generosity costs nothing.
_WHOLE_LIFE_START_MARGIN: Final = timedelta(days=45)
_END_MARGIN: Final = timedelta(days=1)

# The serving refusal circuit breaker — same reasoning as the census driver's
# (a content filter hits single texts; a systemic 4xx must abort loud), sized
# to a job's scale: a 2,000-review job is ~200 batches, so five refusals is
# already far beyond the census's observed ~1-per-10K-requests rate.
_REFUSED_BATCH_LIMIT: Final = 5

# The job thread's poll tick while fetch and classify are both live — narration
# arrives at seconds scale, so a 100 ms tick is invisible to a viewer and cheap
# to the CPU.
_POLL_S: Final = 0.1


@dataclass(frozen=True, slots=True)
class _WindowSpec:
    """One window the producer will fetch: bounds plus the plan's quota.

    ``quota`` of ``None`` is the take-all branch — walk the window whole.
    """

    start: datetime
    end: datetime
    quota: int | None


class AnalysisRunner:
    """One process's runner: composed once, executing one cold job at a time.

    Construction binds the seams the composition root owns — the shared-pacer
    ``SteamClient``, the provider entry (a test injects a fake, production
    passes DeepSeek), the database path, and the ontology artifact (pinned
    explicitly: the packaged default is v1, gold's identity pin, so the
    production composition passes v2 by path per the M1 carry). ``run`` is
    what the job queue's ``run_job`` seam binds to; it opens its own store
    connections per job (the two-writer split: the LLM client's cache writes
    ride worker threads, the driver's label writes stay on the job thread —
    ``dispatch.run_shell`` states the reasoning once).
    """

    def __init__(
        self,
        config: ServeConfig,
        steam: SteamClient,
        entry: ProviderEntry,
        db_path: Path,
        ontology_path: Path | None,
    ) -> None:
        self._config = config
        self._steam = steam
        self._entry = entry
        self._db_path = db_path
        self._stamp = load_ontology_version(ontology_path)
        self._ontology = load_ontology(ontology_path)
        self._surface_index = build_surface_index(self._ontology)
        self._versions = ClassifierVersions(
            model_version=MODEL_ID,
            prompt_version=PROMPT_VERSION,
            ontology_version=self._stamp.version,
        )

    def run(self, app_id: int, requested_name: str, sink: Sink) -> None:
        """One cold analysis end to end, narrated over ``sink``.

        Fetch → classify today; the mint, detect, and compose stages slot in
        after the classify account when their build steps land. Raises on the
        honest aborts — an over-budget sampled plan, the refusal breaker,
        provider trouble outliving retries, annotator drift mid-job — and the
        job queue records the failure; labels bought before an abort are
        already banked and make the re-run nearly free.
        """
        started = datetime.now(UTC)
        run = Provenance(
            run_id=mint_run_id("serve", started),
            code_version=code_version(),
            created_at=started,
            config_hash=self._config_hash(),
        )
        with Store(self._db_path) as client_store, Store(self._db_path) as driver_store:
            ref = self._steam.resolve_game(app_id, requested_name)
            if ref.verdict is not IdentityVerdict.OK:
                narrate(
                    sink, "serve.resolve", StageKind.WARN,
                    f"identity guard: requested {requested_name!r} but the store says "
                    f"{ref.store_name!r} ({ref.verdict.value}) — analyzing app {app_id} as asked",
                )
            english_summary = self._steam.fetch_totals(app_id, language="english")
            english_claim = (
                english_summary.total_reviews if english_summary is not None else 0
            )
            all_claim = ref.total_reviews if ref.total_reviews is not None else 0
            narrate(
                sink, "serve.resolve", StageKind.DONE,
                f"{ref.store_name or requested_name} (app {app_id}): "
                f"{all_claim:,} reviews claimed, {english_claim:,} English",
            )
            histogram = self._steam.fetch_histogram(app_id)
            specs = self._plan(english_claim, all_claim, histogram, sink)

            driver_store.labels.record_run(run)
            client = build_client(
                self._entry, self._config.job_budget_usd, self._config.batch_n,
                client_store, sink,
            )
            self._fetch_and_classify(
                app_id, specs, client, driver_store, run, sink, started
            )

    def _config_hash(self) -> str:
        """The decision-relevant serving dial, fingerprinted for provenance."""
        cfg = self._config
        return config_hash({
            "model": MODEL_ID,
            "prompt_version": PROMPT_VERSION,
            "ontology_version": self._stamp.version,
            "ontology_content_hash": self._stamp.content_hash,
            "take_all_cutoff": cfg.take_all_cutoff,
            "sample_target": cfg.sample_target,
            "batch_n": cfg.batch_n,
            "classify_workers": cfg.classify_workers,
            "job_budget_usd": cfg.job_budget_usd,
            "fetch_page_budget": cfg.fetch_page_budget,
            "num_per_page": self._steam.config.num_per_page,
        })

    def _plan(
        self,
        english_claim: int,
        all_claim: int,
        histogram: HistogramSnapshot,
        sink: Sink,
    ) -> list[_WindowSpec]:
        """The size rule plus the page-budget guard, as window specs to fetch.

        Take-all at English pool ≤ cutoff (one whole-life window, no quota) —
        unless its page cost busts the budget, in which case it degrades to
        the sampling branch with disclosure. A sampled plan compiles at the
        certified target; if even that busts the budget, the job refuses
        loudly rather than becoming an hour-long fetch on a public box.
        """
        per_page = self._steam.config.num_per_page
        budget = self._config.fetch_page_budget
        if english_claim <= self._config.take_all_cutoff:
            take_all_pages = -(-all_claim // per_page) if all_claim else 1
            if take_all_pages <= budget:
                narrate(
                    sink, "serve.plan", StageKind.DONE,
                    f"size rule: take-all (English pool {english_claim:,} ≤ "
                    f"{self._config.take_all_cutoff:,}) — one whole-life window, "
                    f"~{take_all_pages} pages",
                )
                return [self._whole_life_spec(histogram)]
            narrate(
                sink, "serve.plan", StageKind.WARN,
                f"take-all would cost ~{take_all_pages:,} pages against the "
                f"{budget}-page budget (English pool {english_claim:,} inside a "
                f"{all_claim:,}-review game) — degrading to the sampled draw, disclosed",
            )
        plan = compile_plan(
            histogram,
            SamplingPolicy(
                kind=SamplingPolicyKind.TIME_PROPORTIONAL,
                target_size=self._config.sample_target,
            ),
        )
        sampled_pages = sum(-(-window.quota // per_page) for window in plan.windows)
        if sampled_pages > budget:
            raise RunAbort(
                f"sampled plan needs ~{sampled_pages:,} pages against the "
                f"{budget}-page budget ({len(plan.windows)} windows) — refusing the "
                "job rather than running an unbounded fetch"
            )
        narrate(
            sink, "serve.plan", StageKind.DONE,
            f"size rule: sample n={plan.planned_total:,} time-proportional over "
            f"{len(plan.windows)} windows (~{sampled_pages} pages)",
        )
        return [
            _WindowSpec(start=window.start, end=window.end, quota=window.quota)
            for window in plan.windows
        ]

    def _whole_life_spec(self, histogram: HistogramSnapshot) -> _WindowSpec:
        populated = [
            bucket.start
            for bucket in histogram.rollups
            if bucket.recommendations_up + bucket.recommendations_down > 0
        ]
        start = (
            min(populated) - _WHOLE_LIFE_START_MARGIN
            if populated
            else datetime.fromtimestamp(0, tz=UTC)
        )
        return _WindowSpec(
            start=start, end=datetime.now(UTC) + _END_MARGIN, quota=None
        )

    def _fetch_and_classify(
        self,
        app_id: int,
        specs: list[_WindowSpec],
        client: LlmClient,
        driver_store: Store,
        run: Provenance,
        sink: Sink,
        started: datetime,
    ) -> None:
        """The overlap seam: windows stream from the producer, batches classify as they land.

        The producer thread fetches window by window into a bounded queue (the
        bound stalls fetching rather than racing unboundedly ahead); the job
        thread files each completed window's English-usable members into the
        reviews table, batches them to the classify pool, and consumes
        outcomes as futures finish. After production ends, the census's
        rebatch → isolate ladder runs on the same pool. A producer failure
        surfaces on the job thread before the ladder — no retrying into a
        dead fetch; a job-thread abort releases the producer via the cancel
        event so neither side can deadlock on the bounded queue.
        """
        window_queue: Queue[tuple[_WindowSpec, WindowFetchResult] | None] = Queue(
            maxsize=self._config.window_buffer
        )
        cancel = threading.Event()
        fetch_error: list[BaseException] = []
        planned = sum(spec.quota for spec in specs if spec.quota is not None) or None

        def produce() -> None:
            try:
                for spec in specs:
                    if cancel.is_set():
                        return
                    result = self._steam.fetch_window(
                        app_id, spec.start, spec.end, quota=spec.quota
                    )
                    if not _put_unless_cancelled(window_queue, (spec, result), cancel):
                        return
            except BaseException as exc:  # noqa: BLE001 — carried to the job thread
                fetch_error.append(exc)
            finally:
                _put_unless_cancelled(window_queue, None, cancel)

        producer = threading.Thread(target=produce, name="steamlens-fetch", daemon=True)
        totals = RunTotals()
        drift = DriftWatch()
        languages: Counter[str] = Counter()
        buffer: list[Review] = []
        failed: list[Review] = []
        members_total = 0
        windows_done = 0
        pending: set[Future[BatchOutcome]] = set()

        def worker(batch: tuple[Review, ...]) -> BatchOutcome:
            return classify_batch(client, self._ontology, self._surface_index, batch)

        def consume(outcome: BatchOutcome, attempt: str) -> list[Review]:
            return self._consume(outcome, driver_store, run, attempt, totals, drift, sink)

        with ThreadPoolExecutor(max_workers=self._config.classify_workers) as pool:
            producer.start()
            producing = True
            try:
                while producing or pending or buffer:
                    if producing:
                        try:
                            item = window_queue.get(timeout=_POLL_S)
                        except Empty:
                            pass
                        else:
                            if item is None:
                                producing = False
                            else:
                                spec, result = item
                                windows_done += 1
                                members = _usable_english(result.reviews)
                                languages.update(r.language for r in result.reviews)
                                members_total += len(members)
                                self._narrate_window(
                                    sink, spec, result, members, windows_done, len(specs)
                                )
                                driver_store.reviews.put_many(members)
                                buffer.extend(members)
                                while len(buffer) >= self._config.batch_n:
                                    batch = tuple(buffer[: self._config.batch_n])
                                    del buffer[: self._config.batch_n]
                                    pending.add(pool.submit(worker, batch))
                    if not producing and buffer:
                        pending.add(pool.submit(worker, tuple(buffer)))
                        buffer.clear()
                    if pending:
                        done, pending = wait(
                            pending,
                            timeout=0 if producing else None,
                            return_when=FIRST_COMPLETED,
                        )
                        for future in done:
                            failed.extend(consume(future.result(), "initial"))
                if fetch_error:
                    raise fetch_error[0]
                if failed:
                    narrate(
                        sink, "serve.classify", StageKind.PROGRESS,
                        f"rebatch: {len(failed)} failed rows retried at "
                        f"N={self._config.batch_n}",
                    )
                    totals.rebatched = len(failed)
                    failed = run_pass(
                        chunk(failed, self._config.batch_n), "rebatch", worker,
                        lambda o: consume(o, "rebatch"), pool, sink,
                        stage="serve.classify", warmup=False,
                    )
                if failed:
                    narrate(
                        sink, "serve.classify", StageKind.PROGRESS,
                        f"isolate: {len(failed)} rows alone at N=1",
                    )
                    totals.isolated = len(failed)
                    run_pass(
                        chunk(failed, 1), "isolate", worker,
                        lambda o: consume(o, "isolate"), pool, sink,
                        stage="serve.classify", warmup=False,
                    )
            except BaseException:
                for future in pending:
                    future.cancel()
                raise
            finally:
                cancel.set()
                producer.join()

        run_cost = driver_store.spend_ledger.cost_since(started)
        english_note = (
            f"sample {members_total:,}/{planned:,} planned"
            if planned is not None
            else f"take-all sample {members_total:,}"
        )
        mix = ", ".join(
            f"{language} {count:,}"
            for language, count in languages.most_common(3)
        )
        narrate(
            sink, "serve.runner", StageKind.DONE,
            f"labels banked: {totals.labeled:,} labeled (empty {totals.empty_envelopes:,}, "
            f"failed durable {totals.failed_durable}) · {english_note} · "
            f"language mix: {mix or 'none fetched'} · ${run_cost:.4f} this job · "
            f"run {run.run_id}",
        )

    def _narrate_window(
        self,
        sink: Sink,
        spec: _WindowSpec,
        result: WindowFetchResult,
        members: list[Review],
        done: int,
        total: int,
    ) -> None:
        """One window's account: path, volume, and the English yield against quota."""
        if result.outcome is PathOutcome.SKIPPED_INFEASIBLE:
            narrate(
                sink, "serve.fetch", StageKind.WARN,
                f"window {done}/{total} ({spec.start.date()} → {spec.end.date()}): "
                "skipped as infeasible — a disclosed hole in the sample",
            )
            return
        quota_note = f"/{spec.quota} quota" if spec.quota is not None else ""
        narrate(
            sink, "serve.fetch", StageKind.PROGRESS,
            f"window {done}/{total} ({spec.start.date()} → {spec.end.date()}): "
            f"{len(result.reviews)} fetched{quota_note} via {result.outcome.value}, "
            f"{len(members)} English-usable",
        )

    def _consume(
        self,
        outcome: BatchOutcome,
        store: Store,
        run: Provenance,
        attempt: str,
        totals: RunTotals,
        drift: DriftWatch,
        sink: Sink,
    ) -> list[Review]:
        """Consume one outcome on the job thread: envelopes in, failures forward.

        The serving mirror of the census consume — same envelope writes, same
        drift discipline, same durable-mark closure on the isolate attempt —
        with the refusal breaker sized to a job (attempt semantics stay with
        the driver; ``dispatch.run_shell`` states why this is not a shared
        framework).
        """
        if outcome.refusal is not None:
            totals.refused_batches += 1
            narrate(
                sink, "serve.classify", StageKind.WARN,
                f"provider refused a batch ({attempt}, {len(outcome.batch)} reviews): "
                f"{outcome.refusal}",
            )
            if totals.refused_batches > _REFUSED_BATCH_LIMIT:
                raise RunAbort(
                    f"{totals.refused_batches} provider-refused batches exceeds the "
                    f"{_REFUSED_BATCH_LIMIT}-batch circuit breaker — suspect a systemic "
                    "request problem, not content"
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
                    versions=self._versions,
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
                    review.review_id, self._versions, run.run_id, failure.reason
                )
                totals.failed_durable += 1
                narrate(
                    sink, "serve.classify", StageKind.WARN,
                    f"review {review.review_id} unclassifiable even alone: {failure.reason}",
                )
            else:
                retry.append(review)
        return retry


def _put_unless_cancelled(
    queue: Queue[tuple[_WindowSpec, WindowFetchResult] | None],
    item: tuple[_WindowSpec, WindowFetchResult] | None,
    cancel: threading.Event,
) -> bool:
    """Put with a cancellation escape — a bounded queue must never deadlock an abort.

    A ``None`` item is the production-over sentinel. Returns ``False`` when
    the job thread cancelled while the queue was full; the producer treats
    that as "stop fetching," not an error.
    """
    while not cancel.is_set():
        try:
            queue.put(item, timeout=_POLL_S)
        except Full:
            continue
        return True
    return False


def _usable_english(reviews: tuple[Review, ...]) -> list[Review]:
    """The sample members: English with non-empty text — the labelable pool's
    usable filter, applied after selection so the draw stays the certified
    newest-first prefix."""
    return [
        review
        for review in reviews
        if review.language == "english" and review.text.strip()
    ]
