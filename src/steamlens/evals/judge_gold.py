"""The D2c calibration dispatch — gold's reviews re-labeled by the second annotator.

The judge is not a verifier: it never sees production's answers. It reads the
same review text under the same classify prompt and codebook the labeler read,
and answers into the label pool as its own envelope set under its own versions
triple — so judge-vs-gold and judge-vs-production agreement both come out of
the existing certify scorer with no new machinery (DESIGN "D2c judge design:
a second annotator, not a verifier", 2026-07-23). The instrument itself —
model, generation config, single-review/temperature-0 dispatch, refusal and
failure handling — lives in ``judge_dispatch``, shared with the census-sample
shell; this module owns what is gold's alone: the artifact as the id list,
the out-of-scope backfill, and the gold-vs-pool text handshake.

Calibration scope is ALL gold reviews, including those outside the census
pool's usable scope (the CS2 rows — pool scope was the labeler's constraint,
not the judge's; the judge reads text). The label pool's foreign key requires
a review row per envelope, so the driver backfills out-of-scope gold reviews
into ``reviews`` from their corpus files with their true metadata — never
fabricated rows; the census driver's supply assertion and selection are
scoped to ignore them (they were never the census's to price or buy).

This module lives in ``evals`` (not ``studies``) because it consumes the gold
artifact and nothing may import ``evals``; like the certify shell, the import
law forces the arrow.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import traceback
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from steamlens.contracts import ClassifierVersions, Provenance, StageKind
from steamlens.core.classify import PROMPT_VERSION
from steamlens.core.normalize import build_surface_index
from steamlens.evals.gold import GoldRecord, load_gold
from steamlens.evals.judge_dispatch import (
    JUDGE_MODEL_ID,
    KEY_ENV,
    JudgeItem,
    JudgeTotals,
    build_judge_client,
    dispatch_items,
    narrate,
)
from steamlens.llm_client import (
    AtCapacityError,
    LlmUnavailableError,
    ProviderEntry,
    gemini_entry,
)
from steamlens.ontology import load_ontology, load_ontology_version
from steamlens.store import Store
from steamlens.studies.label_corpus import DriftWatch, RunAbort, TeeSink, code_version
from steamlens.studies.local_corpus import read_reviews_file


@dataclass(frozen=True, slots=True)
class JudgeRunConfig:
    """One calibration invocation's resolved dial — everything the manifest reproduces.

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
    """One calibration invocation end to end; returns the process exit code.

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
        narrate(
            sink, StageKind.STARTED,
            f"run {run_id} · code {run.code_version} · {JUDGE_MODEL_ID} · single-review "
            f"· workers {cfg.max_workers} · ontology {stamp.version} · "
            f"gold {len(gold_records)} reviews ({gold_sha256[:12]}…) · "
            f"budget ${cfg.budget_usd:.2f}",
        )
        try:
            backfilled = backfill_gold_reviews(gold_records, cfg.corpus_dir, driver_store)
            if backfilled:
                narrate(
                    sink, StageKind.PROGRESS,
                    f"backfilled {backfilled} out-of-scope gold reviews into the snapshot",
                )
            assert_gold_text_matches_pool(gold_records, driver_store)
            pending = pending_records(gold_records, driver_store, versions)
            already_settled = len(gold_records) - len(pending)
            if cfg.limit is not None:
                pending = pending[: cfg.limit]
            selected = len(pending)
            narrate(
                sink, StageKind.PROGRESS,
                f"selection: {selected} to judge under {versions.model_version}/"
                f"{versions.prompt_version}/{versions.ontology_version} "
                f"({already_settled} of {len(gold_records)} already settled"
                + (f", limit {cfg.limit})" if cfg.limit is not None else ")"),
            )
            if pending:
                driver_store.labels.record_run(run)
                items = [JudgeItem(record.review_id, record.text) for record in pending]
                dispatch_items(items, cfg.max_workers, client, ontology, surface_index,
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
        narrate(
            sink, outcome_kind,
            (f"ABORTED: {aborted}" if aborted else "run complete")
            + f" · judged {totals.labeled}/{selected} (empty {totals.empty_envelopes}, "
            f"failed durable {totals.failed_durable}) · ${run_cost:.4f} this run · "
            f"manifest {run_dir / 'manifest.json'}",
        )
    return 1 if aborted else 0


def main() -> None:
    """Parse the dial, build the Gemini entry, run. The calibration front door."""
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

    key = os.environ.get(KEY_ENV)
    if not key:
        raise SystemExit(f"missing {KEY_ENV} in the environment — set it and rerun")
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
