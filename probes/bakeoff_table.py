"""The C0 comparison table — regenerated from captures + gold, never stored scores.

Usage:
    uv run python probes/bakeoff_table.py [--seed 20260718] [--resamples 10000]

Reads every ``probes/captures/bakeoff/<candidate>/n<N>/`` capture (manifest +
predictions), scores it against gold with the ``evals`` core, adds the
gold-assist reference line from ``eval/gold/assist/raw`` (it competes with
nobody — it calibrates the field), and writes ``TABLE.md`` next to the
captures with full provenance in its header. Derived scores are deliberately
never persisted per candidate: this script IS the one source of scored truth,
regenerable from raw artifacts at any time (DESIGN's C0 entries).

A run whose unrecoverable-parse rate exceeds the 2% gate is marked DQ; a
partial capture (aborted run) is scored with its missing reviews counted as
failures and flagged PARTIAL — visible, never silently flattering.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "src"))

from steamlens.contracts import Sentiment  # noqa: E402
from steamlens.core.normalize import build_surface_index  # noqa: E402
from steamlens.evals import (  # noqa: E402
    BakeoffScores,
    ConfidenceInterval,
    GoldRecord,
    ReviewTally,
    bootstrap_ci,
    load_gold,
    score,
    tally_review,
)
from steamlens.ontology import load_ontology  # noqa: E402

_GOLD_PATH = _REPO / "eval" / "gold" / "gold.jsonl"
_CAPTURES = _REPO / "probes" / "captures" / "bakeoff"
_ASSIST_RAW = _REPO / "eval" / "gold" / "assist" / "raw"
_GATE = 0.02


@dataclass(frozen=True)
class ScoredRun:
    """One capture (or the reference line), scored and ready to render."""

    label: str
    model: str
    n: str
    structured_output: str
    scores: BakeoffScores
    cis: dict[str, ConfidenceInterval]
    tallies: tuple[ReviewTally, ...]
    tokens: str
    cost_usd: float
    partial: bool
    reference: bool


def _predicted_pairs(mentions: list[dict[str, object]]) -> list[tuple[str, Sentiment]]:
    return [(str(m["aspect"]), Sentiment(str(m["sentiment"]))) for m in mentions]


def _tallies_for(
    predictions: dict[str, tuple[list[tuple[str, Sentiment]], bool]],
    gold_records: tuple[GoldRecord, ...],
    index: dict[str, str],
) -> tuple[ReviewTally, ...]:
    """One tally per gold review; a review absent from ``predictions`` failed."""
    tallies: list[ReviewTally] = []
    for record in gold_records:
        gold_pairs = [(m.aspect, m.sentiment) for m in record.mentions]
        pairs, failed = predictions.get(record.review_id, ([], True))
        tallies.append(
            tally_review(gold_pairs, [] if failed else pairs, index, parse_failed=failed)
        )
    return tuple(tallies)


def _score_run(
    tallies: tuple[ReviewTally, ...], *, seed: int, resamples: int
) -> tuple[BakeoffScores, dict[str, ConfidenceInterval]]:
    metrics = {
        "precision": lambda t: score(t).precision,
        "recall": lambda t: score(t).recall,
        "f1": lambda t: score(t).f1,
        "sentiment": lambda t: score(t).sentiment_accuracy,
    }
    cis = {
        name: bootstrap_ci(tallies, fn, n_resamples=resamples, seed=seed)
        for name, fn in metrics.items()
    }
    return score(tallies), cis


def _load_capture_predictions(
    path: Path,
) -> dict[str, tuple[list[tuple[str, Sentiment]], bool]]:
    predictions: dict[str, tuple[list[tuple[str, Sentiment]], bool]] = {}
    for line in (path / "predictions.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        predictions[str(row["review_id"])] = (
            _predicted_pairs(row["mentions"]),
            bool(row["failed"]),
        )
    return predictions


def _load_assist_predictions() -> dict[str, tuple[list[tuple[str, Sentiment]], bool]]:
    predictions: dict[str, tuple[list[tuple[str, Sentiment]], bool]] = {}
    for batch_file in sorted(_ASSIST_RAW.glob("batch_*.json")):
        data = json.loads(batch_file.read_text(encoding="utf-8"))
        for annotation in data["annotations"]:
            predictions[str(annotation["id"])] = (
                _predicted_pairs(annotation["mentions"]),
                False,
            )
    return predictions


def _fmt(value: float, ci: ConfidenceInterval | None = None) -> str:
    if ci is None:
        return f"{value:.3f}"
    return f"{value:.3f} [{ci.low:.3f}–{ci.high:.3f}]"


def _render(runs: list[ScoredRun], gold_candidates: set[str], meta: str) -> str:
    lines = [
        "# C0 bake-off — the comparison table",
        "",
        meta,
        "",
        "| run | model | N | structured output | precision [95% CI] | recall [95% CI] "
        "| F1 [95% CI] | sentiment acc [95% CI] | parse fail | flags |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for run in sorted(runs, key=lambda r: r.scores.f1, reverse=True):
        flags: list[str] = []
        if run.reference:
            flags.append("REFERENCE — competes with nobody")
        if run.scores.parse_failure_rate > _GATE:
            flags.append("DQ (parse gate)")
        if run.partial:
            flags.append("PARTIAL")
        lines.append(
            f"| {run.label} | {run.model} | {run.n} | {run.structured_output} "
            f"| {_fmt(run.scores.precision, run.cis['precision'])} "
            f"| {_fmt(run.scores.recall, run.cis['recall'])} "
            f"| {_fmt(run.scores.f1, run.cis['f1'])} "
            f"| {_fmt(run.scores.sentiment_accuracy, run.cis['sentiment'])} "
            f"| {run.scores.parse_failure_rate:.1%} | {', '.join(flags) or '—'} |"
        )
    lines += [
        "",
        "## Diagnostics (unscored, per the protocol)",
        "",
        "| run | zero-share (gold 49.2%) | candidate emission (gold 5.1% of mentions) "
        "| candidate overlap with gold's 11 | tokens | cost USD |",
        "|---|---|---|---|---|---|",
    ]
    for run in sorted(runs, key=lambda r: r.scores.f1, reverse=True):
        emitted = sorted({c for t in run.tallies for c in t.pred_candidates})
        overlap = sorted(set(emitted) & gold_candidates)
        overlap_note = f"{len(overlap)}/11" + (f" ({', '.join(overlap)})" if overlap else "")
        lines.append(
            f"| {run.label} | {run.scores.zero_share_pred:.1%} "
            f"| {run.scores.candidate_emission_rate:.1%} | {overlap_note} "
            f"| {run.tokens} | {run.cost_usd:.4f} |"
        )
    lines += [
        "",
        "Notes: parse-failed reviews score as zero predictions, never excluded; "
        "salvage-parsed rows count as parsed (rates in each capture's manifest). "
        "Candidate-slot mentions are excluded from the score on both sides. "
        "N is per-candidate by design (the batch-size amendment) — read quality "
        "differences with N in view.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Regenerate the bake-off comparison table.")
    parser.add_argument("--seed", type=int, default=20260718)
    parser.add_argument("--resamples", type=int, default=10_000)
    args = parser.parse_args()

    gold_records = load_gold(_GOLD_PATH)
    index = dict(build_surface_index(load_ontology()))
    gold_candidates = {
        c
        for t in _tallies_for({}, gold_records, index)
        for c in t.gold_candidates
    }

    runs: list[ScoredRun] = []
    for manifest_path in sorted(_CAPTURES.glob("*/n*/manifest.json")):
        capture_dir = manifest_path.parent
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        predictions = _load_capture_predictions(capture_dir)
        tallies = _tallies_for(predictions, gold_records, index)
        scores, cis = _score_run(tallies, seed=args.seed, resamples=args.resamples)
        tokens = manifest.get("tokens", {})
        runs.append(
            ScoredRun(
                label=f"{manifest['candidate']}/n{manifest['n']}",
                model=manifest["model"],
                n=str(manifest["n"]),
                structured_output=manifest.get("structured_output", "?"),
                scores=scores,
                cis=cis,
                tallies=tallies,
                tokens=f"{tokens.get('prompt', 0):,}p/{tokens.get('output', 0):,}o",
                cost_usd=float(manifest.get("cost_usd", 0.0)),
                partial=bool(manifest.get("aborted")) or manifest.get("limit") is not None,
                reference=False,
            )
        )

    if _ASSIST_RAW.exists():
        tallies = _tallies_for(_load_assist_predictions(), gold_records, index)
        scores, cis = _score_run(tallies, seed=args.seed, resamples=args.resamples)
        runs.append(
            ScoredRun(
                label="gold-assist (reference)",
                model="claude-sonnet-5",
                n="—",
                structured_output="session-agent",
                scores=scores,
                cis=cis,
                tallies=tallies,
                tokens="—",
                cost_usd=0.0,
                partial=False,
                reference=True,
            )
        )

    if not runs:
        raise SystemExit(f"no captures under {_CAPTURES} — run bakeoff_runner.py first")

    meta = (
        f"Generated {datetime.now(UTC).isoformat(timespec='seconds')} · "
        f"gold: 250 reviews / 333 pinned mentions (351 incl. 18 candidate) · "
        f"bootstrap: {args.resamples:,} resamples over reviews, seed {args.seed} · "
        f"regenerate: `uv run python probes/bakeoff_table.py --seed {args.seed}`"
    )
    table = _render(runs, gold_candidates, meta)
    out_path = _CAPTURES / "TABLE.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(table, encoding="utf-8")
    print(table)
    print(f"written -> {out_path.relative_to(_REPO)}")


if __name__ == "__main__":
    main()
