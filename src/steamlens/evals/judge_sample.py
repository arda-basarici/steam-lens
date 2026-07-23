"""The census-sample judge dispatch — drawn census reviews re-labeled fresh.

Calibration proved the judge reference-grade (F1 0.816 vs gold, PASS —
SESSION_LOG 2026-07-23); this shell carries the instrument out where gold
doesn't reach: the minted agreement sample (``probes/mint_census_sample.py``,
1,000 census reviews, seeded systematic draw). The judge re-labels each
sampled review fresh — never seeing production's answer — and its envelopes
land under the judge's versions triple; the agreement scorer then reads both
triples' envelopes for the same reviews.

The sample artifact carries no review text, only each drawn review's
``text_sha256`` pin. The dispatch prompts from the *stored* review row and
refuses to run if any stored text no longer hashes to its pin — the minted
frame and the judged text must be byte-identical, or the agreement read
would compare labels of texts nobody drew. (Gold's shell solves the same
identity problem with a strip-equality handshake against the gold file; here
the store is the single text source, so the pin is exact.)

The instrument itself — model, generation config, the single-review and
temperature-0 riders, refusal and failure handling — is ``judge_dispatch``,
shared with the calibration shell. Lives in ``evals`` under the import law,
same as its sibling.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import traceback
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from steamlens.contracts import ClassifierVersions, Provenance, Review, StageKind
from steamlens.core.classify import PROMPT_VERSION
from steamlens.core.normalize import build_surface_index
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


@dataclass(frozen=True, slots=True)
class SampledReview:
    """One drawn review as the sample artifact records it — identity plus pins."""

    review_id: str
    app_id: int
    text_sha256: str


@dataclass(frozen=True, slots=True)
class SampleRunConfig:
    """One sample-dispatch invocation's resolved dial.

    ``ontology_path`` is required and explicit for the same reason as the
    calibration shell's: the judge must annotate under the census's v2
    artifact, pinned by path. ``limit`` is the pilot dial.
    """

    sample_path: Path
    db_path: Path
    runs_dir: Path
    ontology_path: Path
    max_workers: int
    budget_usd: float
    limit: int | None


def load_sample(path: Path) -> tuple[SampledReview, ...]:
    """Read and validate the sample JSONL at ``path`` — every record, or a loud error.

    The boundary check for a minted artifact: every line must carry a
    non-empty ``review_id`` (unique across the file), an integer ``app_id``,
    and a 64-hex ``text_sha256``. Raises ``ValueError`` naming the offending
    line; an unreadable file propagates as its natural ``OSError``.
    """
    records: list[SampledReview] = []
    seen: set[str] = set()
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
            review_id = str(raw["review_id"])
            app_id = int(raw["app_id"])
            text_sha256 = str(raw["text_sha256"])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"sample line {lineno}: malformed record — {exc}") from exc
        if not review_id:
            raise ValueError(f"sample line {lineno}: empty review_id")
        if review_id in seen:
            raise ValueError(f"sample line {lineno}: duplicate review_id {review_id!r}")
        if len(text_sha256) != 64 or any(c not in "0123456789abcdef" for c in text_sha256):
            raise ValueError(f"sample line {lineno}: text_sha256 is not 64 lowercase hex")
        seen.add(review_id)
        records.append(
            SampledReview(review_id=review_id, app_id=app_id, text_sha256=text_sha256)
        )
    if not records:
        raise ValueError(f"sample file is empty: {path}")
    return tuple(records)


def stored_reviews_matching_pins(
    sample: tuple[SampledReview, ...], store: Store
) -> dict[str, Review]:
    """Every sampled review's stored row, verified against its minted text pin.

    Raises ``RunAbort`` naming every id that is missing from the store or
    whose stored text no longer hashes to the sample's ``text_sha256`` — a
    drifted store means the frame the sample describes no longer exists, and
    judging today's text under yesterday's draw would corrupt the read.
    """
    reviews: dict[str, Review] = {}
    missing: list[str] = []
    drifted: list[str] = []
    for record in sample:
        stored = store.reviews.get(record.review_id)
        if stored is None:
            missing.append(record.review_id)
        elif hashlib.sha256(stored.text.encode("utf-8")).hexdigest() != record.text_sha256:
            drifted.append(record.review_id)
        else:
            reviews[record.review_id] = stored
    if missing or drifted:
        raise RunAbort(
            f"sample-vs-store handshake failed: {len(missing)} sampled reviews missing "
            f"from the store {missing}, {len(drifted)} with text that no longer matches "
            f"the minted pin {drifted} — refusing to dispatch over a drifted frame"
        )
    return reviews


def pending_sample(
    sample: tuple[SampledReview, ...], store: Store, versions: ClassifierVersions
) -> tuple[SampledReview, ...]:
    """The sampled reviews still owed a judge verdict under ``versions`` — resume-clean.

    Same closure contract as the calibration shell's selection: an envelope
    or a durable failure mark settles a review; the scope is the sample's id
    list, never the reviews table.
    """
    return tuple(
        record
        for record in sample
        if store.labels.get(record.review_id, versions) is None
        and store.labels.get_failure(record.review_id, versions) is None
    )


def _config_hash(cfg: SampleRunConfig, ontology_version: str, ontology_content_hash: str,
                 sample_sha256: str) -> str:
    """A fingerprint of the decision-relevant config — checkable, never trusted."""
    resolved = {
        "model": JUDGE_MODEL_ID,
        "prompt_version": PROMPT_VERSION,
        "ontology_version": ontology_version,
        "ontology_content_hash": ontology_content_hash,
        "sample_path": cfg.sample_path.as_posix(),
        "sample_sha256": sample_sha256,
        "max_workers": cfg.max_workers,
        "budget_usd": cfg.budget_usd,
        "limit": cfg.limit,
    }
    canonical = json.dumps(resolved, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def execute_sample_run(
    cfg: SampleRunConfig, entry: ProviderEntry, started: datetime | None = None
) -> int:
    """One sample-dispatch invocation end to end; returns the process exit code.

    The composition root, mirroring the calibration shell: identity, the
    two-store split, client, ontology, sink — then the sample-vs-store
    handshake, selection, single-review dispatch, and the manifest whether
    the run finished or aborted.
    """
    started = started if started is not None else datetime.now(UTC)
    run_id = f"judge-sample-{started:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"
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
    sample = load_sample(cfg.sample_path)
    sample_sha256 = hashlib.sha256(cfg.sample_path.read_bytes()).hexdigest()
    run = Provenance(
        run_id=run_id,
        code_version=code_version(),
        created_at=started,
        config_hash=_config_hash(cfg, stamp.version, stamp.content_hash, sample_sha256),
    )

    totals = JudgeTotals()
    drift = DriftWatch()
    aborted: str | None = None
    selected = 0

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
            f"sample {len(sample)} reviews ({sample_sha256[:12]}…) · "
            f"budget ${cfg.budget_usd:.2f}",
        )
        try:
            stored = stored_reviews_matching_pins(sample, driver_store)
            pending = pending_sample(sample, driver_store, versions)
            already_settled = len(sample) - len(pending)
            if cfg.limit is not None:
                pending = pending[: cfg.limit]
            selected = len(pending)
            narrate(
                sink, StageKind.PROGRESS,
                f"selection: {selected} to judge under {versions.model_version}/"
                f"{versions.prompt_version}/{versions.ontology_version} "
                f"({already_settled} of {len(sample)} already settled"
                + (f", limit {cfg.limit})" if cfg.limit is not None else ")"),
            )
            if pending:
                driver_store.labels.record_run(run)
                items = [
                    JudgeItem(record.review_id, stored[record.review_id].text)
                    for record in pending
                ]
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
            "sample_path": cfg.sample_path.as_posix(),
            "sample_sha256": sample_sha256,
            "max_workers": cfg.max_workers,
            "budget_usd": cfg.budget_usd,
            "limit": cfg.limit,
            "started_at": started.isoformat(),
            "finished_at": finished.isoformat(),
            "reviews": {
                "sampled": len(sample),
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
    """Parse the dial, build the Gemini entry, run. The sample dispatch's front door."""
    parser = argparse.ArgumentParser(
        description="Judge-label the census agreement sample into the pool "
                    "(D2c census-sample read). Pilot with --limit first."
    )
    parser.add_argument("--sample", type=Path, default=Path("eval/agreement/sample.jsonl"),
                        help="the minted sample JSONL (default: eval/agreement/sample.jsonl)")
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
                        help="this run's spend cap (1,000-review estimate: ~$6)")
    parser.add_argument("--limit", type=int, default=None,
                        help="judge only the first K sampled reviews (the pilot dial)")
    args = parser.parse_args()

    key = os.environ.get(KEY_ENV)
    if not key:
        raise SystemExit(f"missing {KEY_ENV} in the environment — set it and rerun")
    cfg = SampleRunConfig(
        sample_path=args.sample,
        db_path=args.db,
        runs_dir=args.runs_dir,
        ontology_path=args.ontology,
        max_workers=args.max_workers,
        budget_usd=args.budget_usd,
        limit=args.limit,
    )
    raise SystemExit(execute_sample_run(cfg, gemini_entry(key)))


if __name__ == "__main__":
    main()
