"""The CI eval gate's fixture — committed store rows plus pinned expectations (D3).

CI has no ``data/steamlens.sqlite3`` — the label pool lives only on the dev
machine — yet the D3 design (DESIGN's evals-in-CI entry) wants CI to regenerate
the runs of record and fail on any digit drift. This module owns the committed
bridge under ``eval/ci/``: the exact store rows the two re-scores read
(reviews, run stamps, envelopes — normalized like the store's own tables), the
two pinned ``EvalRun`` expectations, and a provenance manifest. The exporter
(``python -m steamlens.evals.ci_fixture``, run locally against the real store)
re-scores both reads under current code, verifies the historical journal rows'
digits survive, and writes the fresh runs as the pins; the CI gate test
rebuilds a throwaway store from the fixture *through the real writer surfaces*
and demands ``pinned_view`` equality — CI's read path is production's, and an
intentional semantics change has exactly one honest path: bump the scorer
string and re-export the pins in the same commit.

The verification against history carries two disclosed relaxations, one per
run. The certification row of record was journaled before the item-type slice
rows existed, so its metrics must survive as an exact ordered *prefix* of the
fresh run's. The agreement row of record hashed the sample file's
pre-normalization CRLF bytes into its config hash, so that one field is
excluded there — and to keep any such byte skew from ever entering the pins,
the exporter refuses to run while a digest-pinned artifact carries CRLF bytes
(``.gitattributes`` holds them at LF from here on).
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, cast

from steamlens.contracts import (
    AspectMention,
    AspectSlot,
    ClassifierVersions,
    EvalMetric,
    EvalRun,
    Origin,
    Provenance,
    ReferenceKind,
    Review,
    ReviewClassification,
    Sentiment,
)
from steamlens.core.classify import PROMPT_VERSION
from steamlens.corpus import EXCLUDED_APP_IDS
from steamlens.evals.agreement import agreement_pool
from steamlens.evals.certify import certify_pool, render_eval_run
from steamlens.evals.gold import load_gold
from steamlens.evals.judge_dispatch import JUDGE_MODEL_ID
from steamlens.evals.judge_sample import load_sample
from steamlens.ontology import load_ontology_version
from steamlens.store import Store, parse_utc_isoformat, utc_isoformat

FIXTURE_DIR: Final = Path("eval/ci")
"""Where the committed fixture lives, relative to the repo root — the exporter's
default output and the gate test's default input."""

GOLD_PATH: Final = Path("eval/gold/gold.jsonl")
SAMPLE_PATH: Final = Path("eval/agreement/sample.jsonl")
ONTOLOGY_PATH: Final = Path("src/steamlens/ontology/v2.toml")
"""The three pinned scoring artifacts, as repo-root-relative paths. Relative on
purpose: the reference paths land inside journaled config hashes as given, so
the exporter and the gate must both run from the repo root to hash-agree."""

HISTORICAL_CERTIFY: Final = "certify-20260723T093643Z-4eab554c"
"""The journaled production certification (census-vs-gold/1, F1 0.766) the
certification pin must descend from — its digits survive as a metrics prefix."""

HISTORICAL_AGREEMENT: Final = "agree-20260723T203011Z-78258f68"
"""The journaled census-sample agreement read with the per-aspect rows
(judge-vs-production/1, F1 0.791) the agreement pin must reproduce in full."""

REVIEWS_FILE: Final = "reviews.jsonl"
RUNS_FILE: Final = "runs.jsonl"
ENVELOPES_FILE: Final = "envelopes.jsonl"
CERTIFY_PIN_FILE: Final = "expected_certify.json"
AGREEMENT_PIN_FILE: Final = "expected_agreement.json"
MANIFEST_FILE: Final = "manifest.json"


def eval_run_to_json(eval_run: EvalRun) -> dict[str, object]:
    """``eval_run`` as a JSON-ready mapping — a pin file's whole content.

    Field-complete: everything the contract carries round-trips, including the
    run stamp (``pinned_view`` decides what a comparison ignores — the
    serialization never pre-drops). Metrics keep journal order; a point-only
    row serializes its interval bounds as null together.
    """
    return {
        "run": {
            "run_id": eval_run.run.run_id,
            "code_version": eval_run.run.code_version,
            "created_at": utc_isoformat(eval_run.run.created_at),
            "config_hash": eval_run.run.config_hash,
        },
        "versions": {
            "model_version": eval_run.versions.model_version,
            "prompt_version": eval_run.versions.prompt_version,
            "ontology_version": eval_run.versions.ontology_version,
        },
        "ontology_content_hash": eval_run.ontology_content_hash,
        "reference_kind": eval_run.reference_kind.value,
        "reference_id": eval_run.reference_id,
        "reference_sha256": eval_run.reference_sha256,
        "n_reference_reviews": eval_run.n_reference_reviews,
        "n_scored_reviews": eval_run.n_scored_reviews,
        "seed": eval_run.seed,
        "n_resamples": eval_run.n_resamples,
        "scorer": eval_run.scorer,
        "metrics": [
            {"metric": m.metric, "value": m.value, "ci_low": m.ci_low, "ci_high": m.ci_high}
            for m in eval_run.metrics
        ],
    }


def eval_run_from_json(data: Mapping[str, Any]) -> EvalRun:
    """A pin file's mapping back as its contract.

    The committed pin is reviewed data, but enums and timestamps still re-enter
    through validating constructors — a hand-edited pin should fail here, named,
    not surface downstream as a comparison against garbage.
    """
    run = data["run"]
    versions = data["versions"]
    return EvalRun(
        run=Provenance(
            run_id=str(run["run_id"]),
            code_version=str(run["code_version"]),
            created_at=parse_utc_isoformat(str(run["created_at"]), context="pin.run.created_at"),
            config_hash=str(run["config_hash"]),
        ),
        versions=ClassifierVersions(
            model_version=str(versions["model_version"]),
            prompt_version=str(versions["prompt_version"]),
            ontology_version=str(versions["ontology_version"]),
        ),
        ontology_content_hash=str(data["ontology_content_hash"]),
        reference_kind=ReferenceKind(str(data["reference_kind"])),
        reference_id=str(data["reference_id"]),
        reference_sha256=str(data["reference_sha256"]),
        n_reference_reviews=int(data["n_reference_reviews"]),
        n_scored_reviews=int(data["n_scored_reviews"]),
        seed=int(data["seed"]),
        n_resamples=int(data["n_resamples"]),
        scorer=str(data["scorer"]),
        metrics=tuple(
            EvalMetric(
                metric=str(m["metric"]),
                value=float(m["value"]),
                ci_low=None if m["ci_low"] is None else float(m["ci_low"]),
                ci_high=None if m["ci_high"] is None else float(m["ci_high"]),
            )
            for m in data["metrics"]
        ),
    )


def pinned_view(eval_run: EvalRun) -> dict[str, object]:
    """The regeneration contract: every field a re-score must reproduce to the digit.

    Drops exactly the three fields a legitimate regeneration changes — run id,
    timestamp, code version — and keeps everything else, ``config_hash``
    included (it digests the scoring inputs, not the execution) along with
    every metric digit. What "exact-digit" means is decided here, once, for the
    exporter's verification and the CI gate alike.
    """
    view = eval_run_to_json(eval_run)
    view["run"] = {"config_hash": eval_run.run.config_hash}
    return view


def run_discrepancies(
    reference: EvalRun,
    fresh: EvalRun,
    *,
    ignore_config_hash: bool = False,
    metrics_prefix: bool = False,
) -> tuple[str, ...]:
    """Human-readable differences between a reference run and a fresh re-score.

    Empty means the fresh run reproduces the reference under ``pinned_view``'s
    contract. The two relaxations exist for the historical anchors only — the
    module docstring carries their stories — and every deviation they forgive
    is named at the call site, never defaulted on: ``metrics_prefix`` accepts
    fresh runs whose metric family *grew* (the reference rows must survive as
    an exact ordered prefix), ``ignore_config_hash`` skips the one field the
    agreement anchor can no longer reproduce byte-for-byte.
    """
    problems: list[str] = []
    reference_view = pinned_view(reference)
    fresh_view = pinned_view(fresh)
    reference_metrics = cast(list[dict[str, object]], reference_view.pop("metrics"))
    fresh_metrics = cast(list[dict[str, object]], fresh_view.pop("metrics"))
    if ignore_config_hash:
        reference_view.pop("run")
        fresh_view.pop("run")
    for key, reference_value in reference_view.items():
        if fresh_view[key] != reference_value:
            problems.append(f"{key}: reference {reference_value!r} != fresh {fresh_view[key]!r}")
    compared = fresh_metrics[: len(reference_metrics)] if metrics_prefix else fresh_metrics
    if len(compared) != len(reference_metrics):
        problems.append(
            f"metrics: {len(reference_metrics)} reference rows vs {len(fresh_metrics)} fresh"
        )
    for reference_row, fresh_row in zip(reference_metrics, compared, strict=False):
        if reference_row != fresh_row:
            problems.append(
                f"metric {reference_row['metric']!r}: "
                f"reference {reference_row!r} != fresh {fresh_row!r}"
            )
    return tuple(problems)


def review_to_row(review: Review) -> dict[str, object]:
    """One ``Review`` as a fixture row, timestamps in the store's one format."""
    return {
        "review_id": review.review_id,
        "app_id": review.app_id,
        "created_at": utc_isoformat(review.created_at),
        "language": review.language,
        "text": review.text,
        "voted_up": review.voted_up,
    }


def review_from_row(row: Mapping[str, Any]) -> Review:
    """A fixture review row back as its contract."""
    review_id = str(row["review_id"])
    return Review(
        review_id=review_id,
        app_id=int(row["app_id"]),
        created_at=parse_utc_isoformat(
            str(row["created_at"]), context=f"fixture reviews[{review_id}].created_at"
        ),
        language=str(row["language"]),
        text=str(row["text"]),
        voted_up=bool(row["voted_up"]),
    )


def provenance_to_row(run: Provenance) -> dict[str, object]:
    """One run stamp as a fixture row — envelopes reference it by ``run_id``."""
    return {
        "run_id": run.run_id,
        "code_version": run.code_version,
        "created_at": utc_isoformat(run.created_at),
        "config_hash": run.config_hash,
    }


def provenance_from_row(row: Mapping[str, Any]) -> Provenance:
    """A fixture run-stamp row back as its contract."""
    run_id = str(row["run_id"])
    return Provenance(
        run_id=run_id,
        code_version=str(row["code_version"]),
        created_at=parse_utc_isoformat(
            str(row["created_at"]), context=f"fixture runs[{run_id}].created_at"
        ),
        config_hash=str(row["config_hash"]),
    )


def envelope_to_row(envelope: ReviewClassification) -> dict[str, object]:
    """One envelope as a fixture row, its run stamp normalized out to ``run_id``.

    Mirrors the store's own normalization (``classifications`` rows reference
    ``runs``), so the fixture never carries one stamp per envelope when a whole
    dispatch shares it.
    """
    return {
        "review_id": envelope.review_id,
        "origin": envelope.origin.value,
        "model_version": envelope.versions.model_version,
        "prompt_version": envelope.versions.prompt_version,
        "ontology_version": envelope.versions.ontology_version,
        "run_id": envelope.run.run_id,
        "mentions": [
            {
                "aspect": m.aspect,
                "slot": m.slot.value,
                "sentiment": m.sentiment.value,
                "evidence": m.evidence,
            }
            for m in envelope.mentions
        ],
    }


def envelope_from_row(
    row: Mapping[str, Any], runs: Mapping[str, Provenance]
) -> ReviewClassification:
    """A fixture envelope row back as its contract, its run stamp rejoined.

    A ``run_id`` absent from ``runs`` raises ``ValueError`` — the fixture's
    files disagree with each other, which is corruption worth naming, not a
    silent placeholder stamp.
    """
    review_id = str(row["review_id"])
    run_id = str(row["run_id"])
    if run_id not in runs:
        raise ValueError(
            f"fixture envelope for review {review_id!r} references run {run_id!r} "
            f"which {RUNS_FILE} does not carry"
        )
    return ReviewClassification(
        review_id=review_id,
        origin=Origin(str(row["origin"])),
        versions=ClassifierVersions(
            model_version=str(row["model_version"]),
            prompt_version=str(row["prompt_version"]),
            ontology_version=str(row["ontology_version"]),
        ),
        run=runs[run_id],
        mentions=tuple(
            AspectMention(
                aspect=str(m["aspect"]),
                slot=AspectSlot(str(m["slot"])),
                sentiment=Sentiment(str(m["sentiment"])),
                evidence=None if m["evidence"] is None else str(m["evidence"]),
            )
            for m in row["mentions"]
        ),
    )


def verify_fixture_digests(fixture_dir: Path) -> None:
    """Re-hash every file the manifest names; refuse a fixture whose bytes moved.

    Without this check, a truncated, hand-edited, or partially committed
    fixture presents to CI as a pinned-digit mismatch — a message that points
    at the code when the cause is the data. Corruption must name itself.
    Raises ``ValueError`` naming the first file whose bytes differ.
    """
    manifest = json.loads((fixture_dir / MANIFEST_FILE).read_text(encoding="utf-8"))
    recorded = cast(dict[str, str], manifest["sha256"])
    for name, expected in recorded.items():
        actual = hashlib.sha256((fixture_dir / name).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(
                f"fixture file {name} does not match its manifest sha256 — the "
                "fixture's bytes moved (truncated, edited, or partially "
                "committed); this is data corruption, not metric drift"
            )


def load_fixture_into(store: Store, fixture_dir: Path) -> tuple[int, int, int]:
    """Rebuild the fixture's rows in ``store`` through the real writer surfaces.

    Order follows the store's own foreign keys — reviews, then run stamps, then
    envelopes — so the gate exercises the exact write discipline production
    uses (a fixture that only a special loader could ingest would be testing
    the loader). The digests are verified first (``verify_fixture_digests``),
    so every consumer of the fixture inherits the corruption check. Returns
    (reviews, runs, envelopes) counts for narration.
    """
    verify_fixture_digests(fixture_dir)
    reviews = [review_from_row(row) for row in _read_jsonl(fixture_dir / REVIEWS_FILE)]
    store.reviews.put_many(reviews)
    runs = {
        stamp.run_id: stamp
        for stamp in (provenance_from_row(row) for row in _read_jsonl(fixture_dir / RUNS_FILE))
    }
    for stamp in runs.values():
        store.labels.record_run(stamp)
    n_envelopes = 0
    for row in _read_jsonl(fixture_dir / ENVELOPES_FILE):
        store.labels.put(envelope_from_row(row, runs))
        n_envelopes += 1
    return len(reviews), len(runs), n_envelopes


def gate_review_ids(gold_path: Path, sample_path: Path) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(gold-scope ids, sample ids) — the two re-scores' scoring frames.

    Gold narrows by the certification's scope rule (out-of-scope games are
    skipped, never scored), so the fixture carries exactly what the re-score
    reads and nothing that would dress it as bigger than it is.
    """
    excluded = {str(app_id) for app_id in EXCLUDED_APP_IDS}
    gold_ids = tuple(r.review_id for r in load_gold(gold_path) if r.app_id not in excluded)
    sample_ids = tuple(s.review_id for s in load_sample(sample_path))
    return gold_ids, sample_ids


def collect_envelopes(
    store: Store, review_ids: Iterable[str], versions: ClassifierVersions
) -> tuple[ReviewClassification, ...]:
    """Every envelope for ``review_ids`` under ``versions`` — all present, or loud.

    A failure mark is a deliberate stop, not a row: the fixture format carries
    none because neither run of record scored one, and silently inventing a
    representation here would let CI diverge from what was actually measured.
    If a future export hits one, the format grows first, deliberately.
    """
    envelopes: list[ReviewClassification] = []
    missing: list[str] = []
    for review_id in review_ids:
        envelope = store.labels.get(review_id, versions)
        if envelope is not None:
            envelopes.append(envelope)
        elif store.labels.get_failure(review_id, versions) is not None:
            raise ValueError(
                f"review {review_id!r} under {versions!r} carries a failure mark — "
                "the fixture format deliberately has no failure rows; extend it "
                "before exporting this state"
            )
        else:
            missing.append(review_id)
    if missing:
        raise ValueError(
            f"{len(missing)} reviews have no envelope under {versions!r}: {missing}"
        )
    return tuple(envelopes)


def collect_reviews(store: Store, review_ids: Iterable[str]) -> tuple[Review, ...]:
    """The stored reviews behind ``review_ids``, sorted for a deterministic file."""
    reviews: list[Review] = []
    missing: list[str] = []
    for review_id in sorted(set(review_ids)):
        review = store.reviews.get(review_id)
        if review is None:
            missing.append(review_id)
        else:
            reviews.append(review)
    if missing:
        raise ValueError(
            f"{len(missing)} reviews are not in the store despite carrying envelopes "
            f"(foreign keys should make this impossible): {missing}"
        )
    return tuple(reviews)


def export_fixture(
    store: Store,
    out_dir: Path,
    *,
    source_db: Path,
    gold_path: Path = GOLD_PATH,
    sample_path: Path = SAMPLE_PATH,
    ontology_path: Path | None = ONTOLOGY_PATH,
) -> tuple[EvalRun, EvalRun]:
    """Re-score, verify against the journal, write the fixture — the exporter's core.

    Returns the two fresh runs that became the pins. Every scoring dial (model,
    prompt, seed, resamples) is inherited from the journaled anchors rather
    than restated here — the pin descends from the run of record by
    construction, not by convention. Raises before writing anything if a
    digest-pinned artifact carries CRLF bytes or the verification finds a
    discrepancy.
    """
    for pinned_artifact in (gold_path, sample_path, ontology_path):
        if pinned_artifact is not None:
            _require_lf(pinned_artifact)

    historical_certify = _journaled(store, HISTORICAL_CERTIFY)
    fresh_certify = certify_pool(
        store,
        gold_path=gold_path,
        ontology_path=ontology_path,
        model_version=historical_certify.versions.model_version,
        prompt_version=historical_certify.versions.prompt_version,
        seed=historical_certify.seed,
        n_resamples=historical_certify.n_resamples,
    )
    _verified(historical_certify, fresh_certify, metrics_prefix=True)

    historical_agreement = _journaled(store, HISTORICAL_AGREEMENT)
    fresh_agreement = agreement_pool(
        store,
        sample_path=sample_path,
        ontology_path=ontology_path,
        model_version=historical_agreement.versions.model_version,
        prompt_version=historical_agreement.versions.prompt_version,
        seed=historical_agreement.seed,
        n_resamples=historical_agreement.n_resamples,
    )
    _verified(historical_agreement, fresh_agreement, ignore_config_hash=True)

    gold_ids, sample_ids = gate_review_ids(gold_path, sample_path)
    production = fresh_certify.versions
    judge = ClassifierVersions(
        model_version=JUDGE_MODEL_ID,
        prompt_version=PROMPT_VERSION,
        ontology_version=load_ontology_version(ontology_path).version,
    )
    by_key: dict[tuple[str, ClassifierVersions], ReviewClassification] = {}
    for versions, ids in ((production, gold_ids), (production, sample_ids), (judge, sample_ids)):
        for envelope in collect_envelopes(store, ids, versions):
            by_key[(envelope.review_id, envelope.versions)] = envelope
    envelopes = sorted(
        by_key.values(), key=lambda e: (e.review_id, e.versions.model_version)
    )
    reviews = collect_reviews(store, (*gold_ids, *sample_ids))
    runs = {e.run.run_id: e.run for e in envelopes}

    out_dir.mkdir(parents=True, exist_ok=True)
    digests = {
        REVIEWS_FILE: _write_jsonl(out_dir / REVIEWS_FILE, map(review_to_row, reviews)),
        RUNS_FILE: _write_jsonl(
            out_dir / RUNS_FILE,
            (provenance_to_row(runs[run_id]) for run_id in sorted(runs)),
        ),
        ENVELOPES_FILE: _write_jsonl(out_dir / ENVELOPES_FILE, map(envelope_to_row, envelopes)),
        CERTIFY_PIN_FILE: _write_json(
            out_dir / CERTIFY_PIN_FILE, eval_run_to_json(fresh_certify)
        ),
        AGREEMENT_PIN_FILE: _write_json(
            out_dir / AGREEMENT_PIN_FILE, eval_run_to_json(fresh_agreement)
        ),
    }
    manifest = {
        "created_at": utc_isoformat(datetime.now(UTC)),
        "source_db": source_db.as_posix(),
        "verified_against": {
            "certification": {
                "run_id": HISTORICAL_CERTIFY,
                "comparison": "identity + metrics as ordered prefix (the anchor was "
                "journaled before the item-type slice rows existed)",
            },
            "agreement": {
                "run_id": HISTORICAL_AGREEMENT,
                "comparison": "identity + full metrics, config hash excluded (the "
                "anchor's hash digests the sample file's pre-normalization CRLF "
                "bytes; same parsed content)",
            },
        },
        "counts": {
            "reviews": len(reviews),
            "runs": len(runs),
            "envelopes": len(envelopes),
        },
        "sha256": digests,
    }
    _write_json(out_dir / MANIFEST_FILE, manifest)
    return fresh_certify, fresh_agreement


def _journaled(store: Store, run_id: str) -> EvalRun:
    """The journaled anchor row, or a loud stop — the pin must descend from it."""
    eval_run = store.eval_runs.get(run_id)
    if eval_run is None:
        raise ValueError(f"anchor run {run_id!r} is not in this store's journal")
    return eval_run


def _verified(reference: EvalRun, fresh: EvalRun, **relaxations: bool) -> None:
    """Raise with every discrepancy named when the fresh run drifts from its anchor."""
    problems = run_discrepancies(reference, fresh, **relaxations)
    if problems:
        detail = "\n  ".join(problems)
        raise ValueError(
            f"fresh re-score does not reproduce {reference.run.run_id}:\n  {detail}"
        )


def _require_lf(path: Path) -> None:
    """Refuse to pin a digest over CRLF bytes CI's LF checkout can never reproduce."""
    if b"\r\n" in path.read_bytes():
        raise ValueError(
            f"{path} carries CRLF bytes — its digest lands in the pins and CI checks "
            "out LF; normalize the working copy (see .gitattributes) and re-run"
        )


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, object]]) -> str:
    """Write one row per line with LF bytes; returns the file's sha256 for the manifest."""
    data = "".join(
        json.dumps(row, ensure_ascii=False) + "\n" for row in rows
    ).encode("utf-8")
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def _write_json(path: Path, document: Mapping[str, object]) -> str:
    """Write one indented JSON document with LF bytes; returns its sha256."""
    data = (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    """Parse one JSON object per line, naming the file and line on corruption."""
    with path.open(encoding="utf-8") as lines:
        for number, line in enumerate(lines, start=1):
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{number}: unparseable fixture row: {exc}") from exc
            if not isinstance(parsed, dict):
                raise ValueError(f"{path}:{number}: fixture row is not an object")
            yield cast(dict[str, Any], parsed)


def main() -> None:
    """Export the CI gate's fixture from the local store — run from the repo root."""
    parser = argparse.ArgumentParser(
        description="Re-score the runs of record, verify, and export the CI eval fixture."
    )
    parser.add_argument("--db", type=Path, default=Path("data/steamlens.sqlite3"),
                        help="the label-pool database (default: data/steamlens.sqlite3)")
    parser.add_argument("--out", type=Path, default=FIXTURE_DIR,
                        help=f"fixture output directory (default: {FIXTURE_DIR})")
    args = parser.parse_args()

    with Store(args.db) as store:
        fresh_certify, fresh_agreement = export_fixture(
            store, args.out, source_db=args.db
        )
    print(render_eval_run(fresh_certify))
    print()
    print(render_eval_run(fresh_agreement))
    print()
    print(f"verified against {HISTORICAL_CERTIFY} and {HISTORICAL_AGREEMENT}")
    print(f"fixture written -> {args.out}")


if __name__ == "__main__":
    main()
