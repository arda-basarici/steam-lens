"""The census-vs-lab gap — production envelopes paired against a bake-off capture.

Usage:
    uv run python probes/census_vs_gold_gap.py [--capture deepseek-v4-flash-v2/n10]
                                               [--seed 20260718] [--resamples 10000]

The D2a finding's evidence, regenerable: the pool's stored envelopes for
gold's reviews (the labels every displayed number folds) scored next to a
bake-off capture of the same configuration, with the paired bootstrap on the
shared reviews — the honest CI for "the lab arm beats the production labels".
Both sides restrict to gold's in-scope reviews (the pool's usable-games
scope; the CS2 exclusion), because the pool holds nothing for the rest.
Printed, never persisted: like every derived score, regenerable from the
census DB + captures + gold + seed. First read (2026-07-23): the gap is real —
F1 −0.033 [−0.061, −0.007] against the C0.5 v2 arm; batch composition is the
registered prime suspect (D2d).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "src"))

from steamlens.contracts import ClassifierVersions, Sentiment  # noqa: E402
from steamlens.core.classify import PROMPT_VERSION  # noqa: E402
from steamlens.core.normalize import build_surface_index  # noqa: E402
from steamlens.evals import (  # noqa: E402
    GoldRecord,
    ReviewTally,
    load_gold,
    paired_bootstrap_ci,
    score,
    tally_review,
)
from steamlens.evals.certify import pool_tallies  # noqa: E402
from steamlens.ontology import load_ontology  # noqa: E402
from steamlens.store.store import Store  # noqa: E402
from steamlens.studies.label_corpus import MODEL_ID  # noqa: E402
from steamlens.studies.local_corpus import EXCLUDED_APP_IDS  # noqa: E402

_GOLD_PATH = _REPO / "eval" / "gold" / "gold.jsonl"
_CAPTURES = _REPO / "probes" / "captures" / "bakeoff"
_DB = _REPO / "data" / "steamlens.sqlite3"
_ONTOLOGY_V2 = _REPO / "src" / "steamlens" / "ontology" / "v2.toml"


def _capture_tallies(
    capture_dir: Path, gold_records: Sequence[GoldRecord], index: dict[str, str]
) -> tuple[ReviewTally, ...]:
    """The capture's tallies over the in-scope gold reviews, pool-scope aligned."""
    predictions: dict[str, tuple[list[tuple[str, Sentiment]], bool]] = {}
    for line in (capture_dir / "predictions.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        predictions[str(row["review_id"])] = (
            [(str(m["aspect"]), Sentiment(str(m["sentiment"]))) for m in row["mentions"]],
            bool(row["failed"]),
        )
    excluded = {str(app_id) for app_id in EXCLUDED_APP_IDS}
    tallies: list[ReviewTally] = []
    for record in gold_records:
        if record.app_id in excluded:
            continue
        gold_pairs = [(m.aspect, m.sentiment) for m in record.mentions]
        pairs, failed = predictions.get(record.review_id, ([], True))
        tallies.append(
            tally_review(gold_pairs, [] if failed else pairs, index, parse_failed=failed)
        )
    return tuple(tallies)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Paired read: pool envelopes vs a bake-off capture, on shared gold."
    )
    parser.add_argument("--capture", default="deepseek-v4-flash-v2/n10",
                        help="capture label under probes/captures/bakeoff "
                        "(default: the C0.5 winning arm)")
    parser.add_argument("--seed", type=int, default=20260718)
    parser.add_argument("--resamples", type=int, default=10_000)
    args = parser.parse_args()

    capture_dir = _CAPTURES / Path(args.capture)
    if not (capture_dir / "predictions.jsonl").exists():
        raise SystemExit(f"no capture at {args.capture!r} under {_CAPTURES}")

    gold_records = load_gold(_GOLD_PATH)
    index = dict(build_surface_index(load_ontology(_ONTOLOGY_V2)))
    versions = ClassifierVersions(
        model_version=MODEL_ID,
        prompt_version=PROMPT_VERSION,
        ontology_version="v2",
    )
    with Store(_DB) as store:
        pool = pool_tallies(store, gold_records, index, versions)
    arm = _capture_tallies(capture_dir, gold_records, index)
    if len(pool) != len(arm):
        raise SystemExit(f"scope mismatch: pool covers {len(pool)}, capture {len(arm)}")

    metrics: dict[str, Callable[[Sequence[ReviewTally]], float]] = {
        "precision": lambda t: score(t).precision,
        "recall": lambda t: score(t).recall,
        "f1": lambda t: score(t).f1,
        "sentiment": lambda t: score(t).sentiment_accuracy,
    }
    print(f"pool envelopes vs {args.capture} · {len(pool)} shared in-scope gold reviews")
    print(f"  ({args.resamples:,} paired resamples, seed {args.seed})")
    print("| metric | pool | capture | Δ (pool−capture) [95% CI] | read |")
    print("|---|---|---|---|---|")
    for name, fn in metrics.items():
        p, c = fn(pool), fn(arm)
        ci = paired_bootstrap_ci(pool, arm, fn, n_resamples=args.resamples, seed=args.seed)
        read = "pool > capture" if ci.low > 0 else "capture > pool" if ci.high < 0 \
            else "indistinguishable"
        print(f"| {name} | {p:.3f} | {c:.3f} | {p - c:+.3f} [{ci.low:+.3f}–{ci.high:+.3f}] "
              f"| {read} |")


if __name__ == "__main__":
    main()
