"""The D2c judge dispatch — gold's reviews re-labeled by an independent second annotator.

The judge is not a verifier: it never sees production's answers. It reads the
same review text under the same classify prompt and codebook the labeler read,
and answers into the label pool as its own envelope set under its own versions
triple — so judge-vs-gold and judge-vs-production agreement both come out of
the existing certify scorer with no new machinery (DESIGN "D2c judge design:
a second annotator, not a verifier", 2026-07-23). Two riders are load-bearing:
**single-review dispatch** and **temperature 0** — the measured −0.033
batch-composition effect (census vs lab) must not reach the instrument, so
every request carries exactly one review and nothing stochastic.

Calibration scope is ALL gold reviews, including those outside the census
pool's usable scope (the CS2 rows — pool scope was the labeler's constraint,
not the judge's; the judge reads text). The label pool's foreign key requires
a review row per envelope, so the driver backfills out-of-scope gold reviews
into ``reviews`` from their corpus files with their true metadata — never
fabricated rows; the census driver's supply assertion and selection are
scoped to ignore them (they were never the census's to price or buy).

Single-review dispatch collapses C1's three-pass failure sweep to its last
stage: a malformed answer at N=1 is already the isolate case — at temperature
0 a retry recomposes nothing and would replay the identical cached response —
so it takes its durable failure mark on first attempt, exactly as C1's
isolate pass would rule. This module lives in ``evals`` (not ``studies``)
because it consumes the gold artifact and nothing may import ``evals``; like
the certify shell, the import law forces the arrow.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import traceback
import uuid
from collections.abc import Mapping, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from steamlens.contracts import (
    AspectOntology,
    ClassifierVersions,
    FinishReason,
    LlmRequest,
    LlmStage,
    Origin,
    Provenance,
    ReviewClassification,
    StageEvent,
    StageKind,
    TokenUsage,
)
from steamlens.core.classify import (
    CLASSIFY_RESPONSE_SCHEMA,
    PROMPT_VERSION,
    BatchParseResult,
    IdxFailure,
    build_classify_prompt,
    parse_classify_response,
)
from steamlens.core.normalize import build_surface_index
from steamlens.evals.gold import GoldRecord, load_gold
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
    gemini_entry,
)
from steamlens.ontology import load_ontology, load_ontology_version
from steamlens.store import Store
from steamlens.studies.label_corpus import (
    DriftWatch,
    RunAbort,
    TeeSink,
    code_version,
)
from steamlens.studies.local_corpus import read_reviews_file

JUDGE_MODEL_ID: Final = "gemini-3-flash-preview"
"""The requested model id — the judge triple's ``model_version`` (keys are
contracts; the provider-reported version is journaled per call instead).
Picked 2026-07-23 over the design's generic "Gemini flash": the bake-off's
best-F1 flash arm against gold (0.801 at N=20, 0.789 at N=50 — the only
candidate consistently above production's 0.766) at $0.50/$3.00 per 1M."""

_PROVIDER: Final = "gemini"
_KEY_ENV: Final = "GEMINI_API_KEY"
# One review per request: C1's measured base already holds one worst-case
# dense review's answer, and nothing batched ever grows it.
_MAX_OUTPUT_TOKENS: Final = 2_048
# Paid-tier politeness backstop; 250 single-review requests take minutes at
# this pace, so the worker pool, not pacing, is the real throttle.
_RPM: Final = 60
_INPUT_USD_PER_1M: Final = 0.50
_OUTPUT_USD_PER_1M: Final = 3.00
# Gold's text passed two human annotators and 249/250 of it labeled cleanly at
# the census (one durable content-filter refusal in 135K requests) — more than
# a handful of refusals on 250 reviews means a systemic request problem (a bad
# key, a broken payload), never this much toxic text.
_REFUSED_LIMIT: Final = 5

_GEMINI_PARAMS: Final[dict[str, object]] = {
    "temperature": 0,
    "responseMimeType": "application/json",
    "responseSchema": CLASSIFY_RESPONSE_SCHEMA,
    "thinkingConfig": {"thinkingBudget": 0},
}
"""The bake-off's exact measured generation config for this model — constrained
decoding on the classify schema, thinking off, deterministic."""


@dataclass(frozen=True, slots=True)
class JudgeRunConfig:
    """One judge invocation's resolved dial — everything the manifest reproduces.

    ``ontology_path`` is required and explicit (no packaged default): the
    judge must annotate under the same v2 artifact the census pinned by path,
    and an accidental fall-through to packaged v1 would mint a whole envelope
    set under the wrong contract. ``limit`` is the pilot dial — judge the
    first K gold reviews to smoke the path before the full dispatch.
    """

    gold_path: Path
    corpus_dir: Path
    db_path: Path
    runs_dir: Path
    ontology_path: Path
    max_workers: int
    budget_usd: float
    limit: int | None


@dataclass(slots=True)
class JudgeTotals:
    """The run's accumulating counters — one place, narrated and manifested."""

    requests: int = 0
    labeled: int = 0
    empty_envelopes: int = 0
    repairs: int = 0
    failed_durable: int = 0
    refused: int = 0
    prompt_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    model_versions_seen: set[str] = field(default_factory=set[str])


@dataclass(frozen=True, slots=True)
class JudgeOutcome:
    """One judged review's full account, carried from worker to writer.

    ``refusal`` is set when the provider rejected the request outright OR
    finished with a refusal (Gemini's safety block answers with an empty
    body rather than an error) — either way the review takes the typed
    failure path and the refusal counts toward the circuit breaker.
    """

    record: GoldRecord
    parse: BatchParseResult
    model_version: str
    finish: str
    usage: TokenUsage
    refusal: str | None = None


def build_judge_client(
    entry: ProviderEntry, budget_usd: float, client_store: Store, sink: TeeSink
) -> LlmClient:
    """The judge-route client over the *client's* store connection."""
    config = LlmClientConfig(
        routes={
            LlmStage.JUDGE: Route(
                provider=_PROVIDER,
                model=JUDGE_MODEL_ID,
                max_output_tokens=_MAX_OUTPUT_TOKENS,
                params=dict(_GEMINI_PARAMS),
            )
        },
        models={
            JUDGE_MODEL_ID: ModelSpec(
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


def _narrate(sink: TeeSink, kind: StageKind, message: str) -> None:
    sink.emit(StageEvent(stage="judge.driver", kind=kind, message=message))


def backfill_gold_reviews(
    gold_records: Sequence[GoldRecord], corpus_dir: Path, store: Store
) -> int:
    """Ensure every gold review has a ``reviews`` row; backfill missing ones from corpus.

    Missing ids (gold's out-of-scope CS2 rows on a census-built pool) are read
    from their game's corpus file with their true metadata — the label pool's
    foreign key wants a real review, never a fabricated stand-in. Returns how
    many rows were inserted. Raises ``RunAbort`` when a gold id cannot be
    found in its corpus file: gold identity is corpus identity, so a miss
    means the wrong corpus directory or a damaged file, not a skippable row.
    """
    missing: dict[int, set[str]] = {}
    for record in gold_records:
        if store.reviews.get(record.review_id) is None:
            missing.setdefault(int(record.app_id), set()).add(record.review_id)
    backfilled = 0
    for app_id, wanted in sorted(missing.items()):
        result = read_reviews_file(corpus_dir / f"{app_id}_reviews.jsonl")
        by_id = {review.review_id: review for review in result.reviews}
        unfound = sorted(wanted - by_id.keys())
        if unfound:
            raise RunAbort(
                f"gold reviews absent from app {app_id}'s corpus file: {unfound} — "
                f"wrong corpus directory or damaged file; refusing to dispatch"
            )
        backfilled += store.reviews.put_many(by_id[rid] for rid in sorted(wanted))
    return backfilled


def assert_gold_text_matches_pool(
    gold_records: Sequence[GoldRecord], store: Store
) -> None:
    """Every gold record's text must equal its stored review's text, modulo edges.

    The judge prompts from gold's text while its envelope lands on the pool's
    review row — if the two diverged in content, the envelope would claim a
    review the judge never read. Equality is checked after ``strip()`` on
    both sides: the gold draw stripped edge whitespace at minting
    (``draw_gold_set.py``), the corpus rows are raw, and the pilot's verbatim
    check confirmed 14/250 differ by exactly that and none differ further
    (2026-07-23). Edge whitespace carries no annotation content; anything
    beyond it still aborts. Raises ``RunAbort`` naming every mismatched id.
    """
    mismatched: list[str] = []
    for record in gold_records:
        stored = store.reviews.get(record.review_id)
        if stored is None or stored.text.strip() != record.text.strip():
            mismatched.append(record.review_id)
    if mismatched:
        raise RunAbort(
            f"{len(mismatched)} gold reviews disagree with the stored review text "
            f"beyond edge whitespace: {mismatched} — the envelope would claim text "
            f"the judge never read"
        )


def pending_records(
    gold_records: Sequence[GoldRecord], store: Store, versions: ClassifierVersions
) -> tuple[GoldRecord, ...]:
    """The gold reviews still owed a judge verdict under ``versions`` — resume-clean.

    An envelope or a durable failure mark closes a review's selection, same
    contract as C1's selection query; the judge's scope is gold's id list, so
    the selection walks gold, never the reviews table.
    """
    return tuple(
        record
        for record in gold_records
        if store.labels.get(record.review_id, versions) is None
        and store.labels.get_failure(record.review_id, versions) is None
    )


def judge_review(
    client: LlmClient,
    ontology: AspectOntology,
    surface_index: Mapping[str, str],
    record: GoldRecord,
) -> JudgeOutcome:
    """One gold review through prompt → door → parse; the worker-side unit of work.

    Both refusal shapes converge on the typed path: a request-level rejection
    (``ProviderPermanentError``) and a generation-level refusal (Gemini's
    safety block — a ``REFUSAL`` finish with an empty body). A truncated or
    otherwise-incomplete generation is salvaged instead: its spend is already
    journaled and cached, so the partial text is parsed and the finish reason
    rides the outcome.
    """

    def refused(reason: str) -> JudgeOutcome:
        return JudgeOutcome(
            record=record,
            parse=BatchParseResult(
                parsed=(),
                failures=(IdxFailure(0, f"provider refused the request: {reason}"),),
                repairs=(),
            ),
            model_version="",
            finish="refused",
            usage=TokenUsage(prompt_tokens=0, output_tokens=0, thinking_tokens=0),
            refusal=reason,
        )

    prompt = build_classify_prompt([record.text], ontology)
    try:
        response = client.complete(LlmRequest(stage=LlmStage.JUDGE, prompt=prompt))
        finish = response.finish_reason.value
    except GenerationIncompleteError as exc:
        if exc.reason is FinishReason.REFUSAL:
            return refused(f"generation refused (finish={exc.reason.value})")
        response = exc.response
        finish = f"incomplete:{exc.reason.value}"
    except ProviderPermanentError as exc:
        return refused(str(exc))
    return JudgeOutcome(
        record=record,
        parse=parse_classify_response(response.text, [record.text], surface_index),
        model_version=response.model_version,
        finish=finish,
        usage=response.usage,
    )


def _write_outcome(
    outcome: JudgeOutcome,
    store: Store,
    versions: ClassifierVersions,
    run: Provenance,
    totals: JudgeTotals,
    drift: DriftWatch,
    sink: TeeSink,
) -> None:
    """Consume one outcome on the main thread: envelope in, or the durable mark.

    No retry stage exists at N=1 (see the module docstring) — a parse failure
    goes straight to its failure mark, closing the review's selection under
    the judge triple.
    """
    if outcome.refusal is not None:
        totals.refused += 1
        _narrate(
            sink, StageKind.WARN,
            f"provider refused review {outcome.record.review_id}: {outcome.refusal}",
        )
        if totals.refused > _REFUSED_LIMIT:
            raise RunAbort(
                f"{totals.refused} provider refusals exceeds the {_REFUSED_LIMIT}-request "
                f"circuit breaker — gold text is twice-vetted, so suspect a systemic "
                f"request problem"
            )
    else:
        drift.check(outcome.model_version)
        totals.model_versions_seen.add(outcome.model_version)
    totals.requests += 1
    totals.prompt_tokens += outcome.usage.prompt_tokens
    totals.output_tokens += outcome.usage.output_tokens
    totals.thinking_tokens += outcome.usage.thinking_tokens
    totals.repairs += len(outcome.parse.repairs)
    for parsed in outcome.parse.parsed:
        store.labels.put(
            ReviewClassification(
                review_id=outcome.record.review_id,
                origin=Origin.SURVEY,
                versions=versions,
                run=run,
                mentions=parsed.mentions,
            )
        )
        totals.labeled += 1
        if not parsed.mentions:
            totals.empty_envelopes += 1
    for failure in outcome.parse.failures:
        store.labels.record_failure(
            outcome.record.review_id, versions, run.run_id, failure.reason
        )
        totals.failed_durable += 1
        _narrate(
            sink, StageKind.WARN,
            f"review {outcome.record.review_id} took a durable mark: {failure.reason}",
        )


def _config_hash(cfg: JudgeRunConfig, ontology_version: str, ontology_content_hash: str,
                 gold_sha256: str) -> str:
    """A fingerprint of the decision-relevant config — checkable, never trusted."""
    resolved = {
        "model": JUDGE_MODEL_ID,
        "prompt_version": PROMPT_VERSION,
        "ontology_version": ontology_version,
        "ontology_content_hash": ontology_content_hash,
        "gold_path": cfg.gold_path.as_posix(),
        "gold_sha256": gold_sha256,
        "max_workers": cfg.max_workers,
        "budget_usd": cfg.budget_usd,
        "limit": cfg.limit,
    }
    canonical = json.dumps(resolved, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def execute_judge_run(
    cfg: JudgeRunConfig, entry: ProviderEntry, started: datetime | None = None
) -> int:
    """One judge invocation end to end; returns the process exit code.

    The composition root for a run: identity, the two-store split (same
    two-writer reasoning as the census driver — the client's cache/ledger on
    worker threads, envelope writes on the main thread), client, ontology,
    sink — then backfill, the text handshake, selection, single-review
    dispatch, and the manifest whether the run finished or aborted.
    """
    started = started if started is not None else datetime.now(UTC)
    run_id = f"judge-{started:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"
    run_dir = cfg.runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    stamp = load_ontology_version(cfg.ontology_path)
    ontology = load_ontology(cfg.ontology_path)
    surface_index = build_surface_index(ontology)
    versions = ClassifierVersions(
        model_version=JUDGE_MODEL_ID,
        prompt_version=PROMPT_VERSION,
        ontology_version=stamp.version,
    )
    gold_records = load_gold(cfg.gold_path)
    gold_sha256 = hashlib.sha256(cfg.gold_path.read_bytes()).hexdigest()
    run = Provenance(
        run_id=run_id,
        code_version=code_version(),
        created_at=started,
        config_hash=_config_hash(cfg, stamp.version, stamp.content_hash, gold_sha256),
    )

    totals = JudgeTotals()
    drift = DriftWatch()
    aborted: str | None = None
    backfilled = selected = 0

    with (
        (run_dir / "run.log").open("a", encoding="utf-8", buffering=1) as log,
        Store(cfg.db_path) as client_store,
        Store(cfg.db_path) as driver_store,
    ):
        sink = TeeSink(log)
        client = build_judge_client(entry, cfg.budget_usd, client_store, sink)
        _narrate(
            sink, StageKind.STARTED,
            f"run {run_id} · code {run.code_version} · {JUDGE_MODEL_ID} · single-review "
            f"· workers {cfg.max_workers} · ontology {stamp.version} · "
            f"gold {len(gold_records)} reviews ({gold_sha256[:12]}…) · "
            f"budget ${cfg.budget_usd:.2f}",
        )
        try:
            backfilled = backfill_gold_reviews(gold_records, cfg.corpus_dir, driver_store)
            if backfilled:
                _narrate(
                    sink, StageKind.PROGRESS,
                    f"backfilled {backfilled} out-of-scope gold reviews into the snapshot",
                )
            assert_gold_text_matches_pool(gold_records, driver_store)
            pending = pending_records(gold_records, driver_store, versions)
            already_settled = len(gold_records) - len(pending)
            if cfg.limit is not None:
                pending = pending[: cfg.limit]
            selected = len(pending)
            _narrate(
                sink, StageKind.PROGRESS,
                f"selection: {selected} to judge under {versions.model_version}/"
                f"{versions.prompt_version}/{versions.ontology_version} "
                f"({already_settled} of {len(gold_records)} already settled"
                + (f", limit {cfg.limit})" if cfg.limit is not None else ")"),
            )
            if pending:
                driver_store.labels.record_run(run)
                _dispatch(pending, cfg.max_workers, client, ontology, surface_index,
                          driver_store, versions, run, totals, drift, sink)
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
            "model": JUDGE_MODEL_ID,
            "model_versions_seen": sorted(totals.model_versions_seen),
            "prompt_version": PROMPT_VERSION,
            "ontology_version": stamp.version,
            "ontology_content_hash": stamp.content_hash,
            "gold_path": cfg.gold_path.as_posix(),
            "gold_sha256": gold_sha256,
            "max_workers": cfg.max_workers,
            "budget_usd": cfg.budget_usd,
            "limit": cfg.limit,
            "started_at": started.isoformat(),
            "finished_at": finished.isoformat(),
            "reviews": {
                "gold": len(gold_records),
                "backfilled": backfilled,
                "selected": selected,
                "labeled": totals.labeled,
                "empty_envelopes": totals.empty_envelopes,
                "evidence_repairs": totals.repairs,
                "failed_durable": totals.failed_durable,
                "refused": totals.refused,
            },
            "requests": totals.requests,
            "tokens": {
                "prompt": totals.prompt_tokens,
                "output": totals.output_tokens,
                "thinking": totals.thinking_tokens,
            },
            "cost_usd_run": run_cost,
            "aborted": aborted,
        }
        (run_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        outcome_kind = StageKind.WARN if aborted else StageKind.DONE
        _narrate(
            sink, outcome_kind,
            (f"ABORTED: {aborted}" if aborted else "run complete")
            + f" · judged {totals.labeled}/{selected} (empty {totals.empty_envelopes}, "
            f"failed durable {totals.failed_durable}) · ${run_cost:.4f} this run · "
            f"manifest {run_dir / 'manifest.json'}",
        )
    return 1 if aborted else 0


def _dispatch(
    pending: Sequence[GoldRecord],
    max_workers: int,
    client: LlmClient,
    ontology: AspectOntology,
    surface_index: Mapping[str, str],
    store: Store,
    versions: ClassifierVersions,
    run: Provenance,
    totals: JudgeTotals,
    drift: DriftWatch,
    sink: TeeSink,
) -> None:
    """Single pass over the pending gold records, consumed as futures finish.

    The first request runs synchronously before the pool opens — one completed
    call seeds the provider's prefix cache (the ~7K codebook prefix repeats on
    every request) and sets the drift watch's baseline before concurrency.
    Abort means stop: queued requests are cancelled; in-flight ones finish and
    cache harmlessly.
    """
    total = len(pending)
    done = 0

    def worker(record: GoldRecord) -> JudgeOutcome:
        return judge_review(client, ontology, surface_index, record)

    def consume(outcome: JudgeOutcome) -> None:
        nonlocal done
        _write_outcome(outcome, store, versions, run, totals, drift, sink)
        done += 1
        if done % 25 == 0 or done == total:
            _narrate(sink, StageKind.PROGRESS, f"judged {done}/{total}")

    consume(worker(pending[0]))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures: set[Future[JudgeOutcome]] = {
            pool.submit(worker, record) for record in pending[1:]
        }
        try:
            while futures:
                completed, futures = wait(futures, return_when=FIRST_COMPLETED)
                for future in completed:
                    consume(future.result())
        except BaseException:
            for future in futures:
                future.cancel()
            raise


def main() -> None:
    """Parse the dial, build the Gemini entry, run. The judge's front door."""
    parser = argparse.ArgumentParser(
        description="Judge-label the gold reviews into the pool (D2c calibration). "
                    "Pilot with --limit first."
    )
    parser.add_argument("--gold", type=Path, default=Path("eval/gold/gold.jsonl"),
                        help="the gold JSONL artifact (default: eval/gold/gold.jsonl)")
    parser.add_argument("--corpus", type=Path, required=True,
                        help="directory holding the <app_id>_reviews.jsonl corpus files "
                             "(the backfill source for out-of-scope gold reviews)")
    parser.add_argument("--db", type=Path, default=Path("data/steamlens.sqlite3"),
                        help="the label-pool database (default: data/steamlens.sqlite3)")
    parser.add_argument("--runs-dir", type=Path, default=Path("data/runs"),
                        help="where run manifests and logs land (default: data/runs)")
    parser.add_argument("--ontology", type=Path, required=True,
                        help="ontology artifact path — explicit on purpose; the judge "
                             "pins v2 by path like every consumer of the census pool")
    parser.add_argument("--max-workers", type=int, default=4,
                        help="concurrent requests (default 4)")
    parser.add_argument("--budget-usd", type=float, required=True,
                        help="this run's spend cap (calibration estimate: ~$1)")
    parser.add_argument("--limit", type=int, default=None,
                        help="judge only the first K gold reviews (the pilot dial)")
    args = parser.parse_args()

    key = os.environ.get(_KEY_ENV)
    if not key:
        raise SystemExit(f"missing {_KEY_ENV} in the environment — set it and rerun")
    cfg = JudgeRunConfig(
        gold_path=args.gold,
        corpus_dir=args.corpus,
        db_path=args.db,
        runs_dir=args.runs_dir,
        ontology_path=args.ontology,
        max_workers=args.max_workers,
        budget_usd=args.budget_usd,
        limit=args.limit,
    )
    raise SystemExit(execute_judge_run(cfg, gemini_entry(key)))


if __name__ == "__main__":
    main()
