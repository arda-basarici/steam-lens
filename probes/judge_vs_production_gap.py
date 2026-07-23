"""The judge-vs-production paired read — the D2c calibration's pre-registered verdict.

Usage:
    uv run python probes/judge_vs_production_gap.py [--seed 20260718] [--resamples 10000]

The decision rule (DESIGN "D2c judge design", fork 2) reads the paired
bootstrap Δ(judge − production) on shared gold: **pass** — significantly
above → census-sample verdicts are reference-grade; **marginal** —
indistinguishable → the judge is a disagreement flagger only; **fail** —
significantly below → an honest finding, certification stands on the
mechanical layers. Both envelope sets live in the one pool under their own
versions triples, so both sides score through the same ``pool_tallies`` walk
of gold — aligned review-by-review by construction. The pairing restricts to
gold's in-scope reviews (production holds nothing for the CS2 rows; the
judge's five CS2 envelopes are calibration-scored by ``certify --judge`` but
cannot enter a paired read — disclosed, not hidden). Printed, never
persisted: regenerable from the census DB + gold + seed.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "src"))

from steamlens.contracts import ClassifierVersions  # noqa: E402
from steamlens.core.classify import PROMPT_VERSION  # noqa: E402
from steamlens.core.normalize import build_surface_index  # noqa: E402
from steamlens.evals import ReviewTally, load_gold, paired_bootstrap_ci, score  # noqa: E402
from steamlens.evals.certify import pool_tallies  # noqa: E402
from steamlens.evals.judge_gold import JUDGE_MODEL_ID  # noqa: E402
from steamlens.ontology import load_ontology  # noqa: E402
from steamlens.store.store import Store  # noqa: E402
from steamlens.studies.label_corpus import MODEL_ID  # noqa: E402

_GOLD_PATH = _REPO / "eval" / "gold" / "gold.jsonl"
_DB = _REPO / "data" / "steamlens.sqlite3"
_ONTOLOGY_V2 = _REPO / "src" / "steamlens" / "ontology" / "v2.toml"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Paired read: judge envelopes vs production envelopes, on shared gold."
    )
    parser.add_argument("--seed", type=int, default=20260718)
    parser.add_argument("--resamples", type=int, default=10_000)
    args = parser.parse_args()

    gold_records = load_gold(_GOLD_PATH)
    index = dict(build_surface_index(load_ontology(_ONTOLOGY_V2)))
    production = ClassifierVersions(
        model_version=MODEL_ID, prompt_version=PROMPT_VERSION, ontology_version="v2"
    )
    judge = ClassifierVersions(
        model_version=JUDGE_MODEL_ID, prompt_version=PROMPT_VERSION, ontology_version="v2"
    )
    with Store(_DB) as store:
        production_tallies = pool_tallies(store, gold_records, index, production)
        judge_tallies = pool_tallies(store, gold_records, index, judge)
    if len(production_tallies) != len(judge_tallies):
        raise SystemExit(
            f"scope mismatch: production covers {len(production_tallies)}, "
            f"judge {len(judge_tallies)}"
        )

    metrics: dict[str, Callable[[Sequence[ReviewTally]], float]] = {
        "precision": lambda t: score(t).precision,
        "recall": lambda t: score(t).recall,
        "f1": lambda t: score(t).f1,
        "sentiment": lambda t: score(t).sentiment_accuracy,
    }
    print(
        f"judge ({JUDGE_MODEL_ID}) vs production ({MODEL_ID}) · "
        f"{len(judge_tallies)} shared in-scope gold reviews"
    )
    print(f"  ({args.resamples:,} paired resamples, seed {args.seed})")
    print("| metric | judge | production | Δ (judge−production) [95% CI] | read |")
    print("|---|---|---|---|---|")
    verdicts: dict[str, str] = {}
    for name, fn in metrics.items():
        j, p = fn(judge_tallies), fn(production_tallies)
        ci = paired_bootstrap_ci(
            judge_tallies, production_tallies, fn, n_resamples=args.resamples, seed=args.seed
        )
        read = "judge > production" if ci.low > 0 else \
            "production > judge" if ci.high < 0 else "indistinguishable"
        verdicts[name] = read
        print(f"| {name} | {j:.3f} | {p:.3f} | {j - p:+.3f} [{ci.low:+.3f}–{ci.high:+.3f}] "
              f"| {read} |")
    rule = {"judge > production": "PASS", "indistinguishable": "MARGINAL",
            "production > judge": "FAIL"}[verdicts["f1"]]
    print(f"\npre-registered rule reads F1: **{rule}** — "
          + {"PASS": "census-sample verdicts are reference-grade.",
             "MARGINAL": "the judge is a disagreement flagger only; the sample reports "
                         "agreement rates, never judge-corrected quality.",
             "FAIL": "an honest finding; certification stands on the mechanical layers."}[rule])


if __name__ == "__main__":
    main()
