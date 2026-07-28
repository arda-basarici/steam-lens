"""The D2d registered readings — the decision rules, executable before the data exists.

Usage:
    uv run python probes/d2d_reads.py [--read gold|matrix|all]
                                      [--seed 20260718] [--resamples 10000]

Committed with the dispatch driver, *before* any cell is bought, so the
decision rules are code — not post-hoc analysis. Two reads, per DESIGN's D2d
registered-experiments entry (2026-07-25):

**The gold read** (``--read gold``) puts the full-codebook N=1 re-label next
to the two existing anchors on the shared in-scope gold reviews — the census
condition (production's own envelopes) and the lab condition (the C0.5
capture, gold batched among gold at N=10) — with paired bootstrap CIs. The
anchor-position diagnosis: N=1 near the lab value says batch *company* did
the damage, above it says size itself costs, near the census value acquits
batching. **The registered trigger**: the contingent lab-recomposition rerun
fires iff the paired ΔF1 (N=1 minus census) fails to exclude zero upward —
that branch alone cannot distinguish "batching never mattered" from provider
drift, and the rerun separates them.

**The matrix read** (``--read matrix``) scores the codebook × batch 2×2
against the judge's stored verdicts over the minted agreement sample:
per-cell F1, each codebook's batch penalty (N=1 minus N=10, paired), the
deployment cell (compact-N=10 vs full-N=10, paired), and the interaction —
the full codebook's penalty minus the compact's, one index draw applied to
all four cells, so "does a leaner rule set suffer less from a muddier
context" gets its own interval.

**The contingent read** (``--read contingent``) runs only after the gold
read's trigger fired and the ``full-n10-gold-recomposed`` cell was bought:
the same gold reviews re-labeled *today* under census-composition batching.
Two paired tables split the confound the flat gold read cannot: recomposed
vs census (same composition, different day — a real gap here is provider
drift) and N=1 vs recomposed (same day, different composition — a real gap
here is batch contamination, drift-free).

Each read raises loudly (naming review ids) when its cells are not fully
dispatched — run the read matching what has been bought. Printed, never
persisted: regenerable from the census DB + captures + gold + seed.
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
from steamlens.evals.agreement import agreement_tallies  # noqa: E402
from steamlens.evals.certify import pool_tallies  # noqa: E402
from steamlens.evals.experiment_dispatch import CELLS, cell_versions  # noqa: E402
from steamlens.evals.judge_dispatch import JUDGE_MODEL_ID  # noqa: E402
from steamlens.evals.judge_sample import load_sample  # noqa: E402
from steamlens.ontology import load_ontology, load_ontology_version  # noqa: E402
from steamlens.store.store import Store  # noqa: E402
from steamlens.dispatch.census_arm import MODEL_ID  # noqa: E402
from steamlens.corpus import EXCLUDED_APP_IDS  # noqa: E402

_GOLD_PATH = _REPO / "eval" / "gold" / "gold.jsonl"
_SAMPLE_PATH = _REPO / "eval" / "agreement" / "sample.jsonl"
_LAB_CAPTURE = _REPO / "probes" / "captures" / "bakeoff" / "deepseek-v4-flash-v2" / "n10"
_DB = _REPO / "data" / "steamlens.sqlite3"
_ONTOLOGY_V2 = _REPO / "src" / "steamlens" / "ontology" / "v2.toml"

_METRICS: dict[str, Callable[[Sequence[ReviewTally]], float]] = {
    "precision": lambda t: score(t).precision,
    "recall": lambda t: score(t).recall,
    "f1": lambda t: score(t).f1,
    "sentiment": lambda t: score(t).sentiment_accuracy,
}
_F1 = _METRICS["f1"]


def _lab_capture_tallies(
    gold_records: Sequence[GoldRecord], index: dict[str, str]
) -> tuple[ReviewTally, ...]:
    """The C0.5 lab arm's tallies over the in-scope gold reviews, pool-scope aligned.

    Recomputed from the capture (never a hardcoded literal) so the lab anchor
    in this read and ``probes/census_vs_gold_gap.py``'s stay one source.
    """
    predictions: dict[str, tuple[list[tuple[str, Sentiment]], bool]] = {}
    lines = (_LAB_CAPTURE / "predictions.jsonl").read_text(encoding="utf-8").splitlines()
    for line in lines:
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


def _interaction_ci(
    full_n1: Sequence[ReviewTally],
    full_n10: Sequence[ReviewTally],
    compact_n1: Sequence[ReviewTally],
    compact_n10: Sequence[ReviewTally],
    *,
    n_resamples: int,
    seed: int,
) -> tuple[float, float]:
    """The 95% paired interval of (full's batch penalty − compact's), F1.

    One index draw per resample applied to all four cells — the four tally
    lists cover the same reviews in the same order, so shared review
    difficulty cancels inside every term.
    """
    import random

    rng = random.Random(seed)
    n = len(full_n1)
    values: list[float] = []
    for _ in range(n_resamples):
        idx = [rng.randrange(n) for _ in range(n)]
        full_delta = _F1([full_n1[i] for i in idx]) - _F1([full_n10[i] for i in idx])
        compact_delta = _F1([compact_n1[i] for i in idx]) - _F1([compact_n10[i] for i in idx])
        values.append(full_delta - compact_delta)
    values.sort()
    return (
        values[round(0.025 * (n_resamples - 1))],
        values[round(0.975 * (n_resamples - 1))],
    )


def _print_paired_table(
    label_a: str,
    label_b: str,
    tallies_a: Sequence[ReviewTally],
    tallies_b: Sequence[ReviewTally],
    *,
    n_resamples: int,
    seed: int,
) -> None:
    print(f"| metric | {label_a} | {label_b} | Δ ({label_a}−{label_b}) [95% CI] | read |")
    print("|---|---|---|---|---|")
    for name, fn in _METRICS.items():
        a, b = fn(tallies_a), fn(tallies_b)
        ci = paired_bootstrap_ci(tallies_a, tallies_b, fn, n_resamples=n_resamples, seed=seed)
        read = f"{label_a} > {label_b}" if ci.low > 0 \
            else f"{label_b} > {label_a}" if ci.high < 0 else "indistinguishable"
        print(f"| {name} | {a:.3f} | {b:.3f} | {a - b:+.3f} [{ci.low:+.3f}–{ci.high:+.3f}] "
              f"| {read} |")


def gold_read(store: Store, index: dict[str, str], ontology_version: str,
              *, n_resamples: int, seed: int) -> None:
    """The contamination arm's gold-referenced recovery read + the registered trigger."""
    gold_records = load_gold(_GOLD_PATH)
    census = ClassifierVersions(MODEL_ID, PROMPT_VERSION, ontology_version)
    n1 = cell_versions(CELLS["full-n1-gold"], ontology_version)
    census_tallies = pool_tallies(store, gold_records, index, census)
    n1_tallies = pool_tallies(store, gold_records, index, n1)
    lab_tallies = _lab_capture_tallies(gold_records, index)

    print(f"## Gold read — {len(n1_tallies)} shared in-scope gold reviews "
          f"({n_resamples:,} paired resamples, seed {seed})")
    print(f"anchors: census = pool {census.model_version}, N=1 = pool {n1.model_version}, "
          f"lab = capture {_LAB_CAPTURE.relative_to(_REPO).as_posix()}")
    print()
    _print_paired_table("n1", "census", n1_tallies, census_tallies,
                        n_resamples=n_resamples, seed=seed)
    print()
    _print_paired_table("n1", "lab", n1_tallies, lab_tallies,
                        n_resamples=n_resamples, seed=seed)
    print()
    trigger_ci = paired_bootstrap_ci(n1_tallies, census_tallies, _F1,
                                     n_resamples=n_resamples, seed=seed)
    fires = trigger_ci.low <= 0
    print(f"registered trigger — ΔF1(n1−census) = "
          f"{_F1(n1_tallies) - _F1(census_tallies):+.3f} "
          f"[{trigger_ci.low:+.3f}–{trigger_ci.high:+.3f}]:")
    print(
        "  CONTINGENT FIRES — the interval fails to exclude zero upward; buy the "
        "lab-recomposition rerun to separate drift from composition."
        if fires else
        "  contingent does not fire — N=1 recovers over the census condition; "
        "batch contamination confirmed, no further buy."
    )


def contingent_read(store: Store, index: dict[str, str], ontology_version: str,
                    *, n_resamples: int, seed: int) -> None:
    """The fired contingent: drift vs composition, separated on the shared gold."""
    gold_records = load_gold(_GOLD_PATH)
    census = ClassifierVersions(MODEL_ID, PROMPT_VERSION, ontology_version)
    n1 = cell_versions(CELLS["full-n1-gold"], ontology_version)
    recomposed = cell_versions(CELLS["full-n10-gold-recomposed"], ontology_version)
    census_tallies = pool_tallies(store, gold_records, index, census)
    n1_tallies = pool_tallies(store, gold_records, index, n1)
    recomposed_tallies = pool_tallies(store, gold_records, index, recomposed)

    print(f"## Contingent read — {len(recomposed_tallies)} shared in-scope gold reviews "
          f"({n_resamples:,} paired resamples, seed {seed})")
    print("drift test (same composition, different day):")
    _print_paired_table("recomposed", "census", recomposed_tallies, census_tallies,
                        n_resamples=n_resamples, seed=seed)
    print()
    print("composition test (same day, different composition):")
    _print_paired_table("n1", "recomposed", n1_tallies, recomposed_tallies,
                        n_resamples=n_resamples, seed=seed)
    print()
    drift_ci = paired_bootstrap_ci(recomposed_tallies, census_tallies, _F1,
                                   n_resamples=n_resamples, seed=seed)
    comp_ci = paired_bootstrap_ci(n1_tallies, recomposed_tallies, _F1,
                                  n_resamples=n_resamples, seed=seed)
    drift_real = drift_ci.low > 0 or drift_ci.high < 0
    comp_real = comp_ci.low > 0 or comp_ci.high < 0
    print("verdict:")
    print(f"  drift ΔF1(recomposed−census) {'REAL' if drift_real else 'not detected'} "
          f"[{drift_ci.low:+.3f}–{drift_ci.high:+.3f}] · "
          f"composition ΔF1(n1−recomposed) {'REAL' if comp_real else 'not detected'} "
          f"[{comp_ci.low:+.3f}–{comp_ci.high:+.3f}]")


def matrix_read(store: Store, index: dict[str, str], ontology_version: str,
                *, n_resamples: int, seed: int) -> None:
    """The codebook × batch 2×2 against the judge's verdicts over the sample."""
    sample = load_sample(_SAMPLE_PATH)
    judge = ClassifierVersions(JUDGE_MODEL_ID, PROMPT_VERSION, ontology_version)
    cells = {
        "full-n10": ClassifierVersions(MODEL_ID, PROMPT_VERSION, ontology_version),
        "full-n1": cell_versions(CELLS["full-n1-sample"], ontology_version),
        "compact-n10": cell_versions(CELLS["compact-n10-sample"], ontology_version),
        "compact-n1": cell_versions(CELLS["compact-n1-sample"], ontology_version),
    }
    tallies: dict[str, tuple[ReviewTally, ...]] = {}
    for name, versions in cells.items():
        cell_tallies, dropped, _ = agreement_tallies(store, sample, index, versions, judge)
        tallies[name] = cell_tallies
        if dropped:
            print(f"  note: {len(dropped)} judge-unread reviews dropped from {name}")
    lengths = {name: len(t) for name, t in tallies.items()}
    if len(set(lengths.values())) != 1:
        raise SystemExit(f"cells cover different review sets: {lengths}")

    print(f"## Matrix read — {lengths['full-n10']} sampled reviews vs the judge "
          f"({n_resamples:,} paired resamples, seed {seed})")
    print("| cell | F1 vs judge |")
    print("|---|---|")
    for name in cells:
        print(f"| {name} | {_F1(tallies[name]):.3f} |")
    print()
    print("batch penalty per codebook (N=1 − N=10, paired):")
    for codebook in ("full", "compact"):
        n1_t, n10_t = tallies[f"{codebook}-n1"], tallies[f"{codebook}-n10"]
        ci = paired_bootstrap_ci(n1_t, n10_t, _F1, n_resamples=n_resamples, seed=seed)
        print(f"  {codebook}: {_F1(n1_t) - _F1(n10_t):+.3f} [{ci.low:+.3f}–{ci.high:+.3f}]")
    low, high = _interaction_ci(
        tallies["full-n1"], tallies["full-n10"],
        tallies["compact-n1"], tallies["compact-n10"],
        n_resamples=n_resamples, seed=seed,
    )
    full_delta = _F1(tallies["full-n1"]) - _F1(tallies["full-n10"])
    compact_delta = _F1(tallies["compact-n1"]) - _F1(tallies["compact-n10"])
    print(f"interaction (full penalty − compact penalty): "
          f"{full_delta - compact_delta:+.3f} [{low:+.3f}–{high:+.3f}]")
    print("  (interval excluding zero upward = the leaner codebook suffers less "
          "from batching — the registered hypothesis)")
    print()
    print("deployment cell (compact-n10 vs full-n10, paired):")
    _print_paired_table("compact-n10", "full-n10",
                        tallies["compact-n10"], tallies["full-n10"],
                        n_resamples=n_resamples, seed=seed)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="The D2d registered readings over the pool's dispatched cells."
    )
    parser.add_argument("--read", choices=("gold", "matrix", "contingent", "all"),
                        default="all",
                        help="which registered read to run (default: all; 'all' skips "
                             "the contingent unless its cell has been dispatched)")
    parser.add_argument("--seed", type=int, default=20260718)
    parser.add_argument("--resamples", type=int, default=10_000)
    args = parser.parse_args()

    stamp = load_ontology_version(_ONTOLOGY_V2)
    index = dict(build_surface_index(load_ontology(_ONTOLOGY_V2)))
    with Store(_DB) as store:
        if args.read in ("gold", "all"):
            gold_read(store, index, stamp.version,
                      n_resamples=args.resamples, seed=args.seed)
        if args.read == "contingent":
            contingent_read(store, index, stamp.version,
                            n_resamples=args.resamples, seed=args.seed)
        elif args.read == "all":
            print()
            try:
                contingent_read(store, index, stamp.version,
                                n_resamples=args.resamples, seed=args.seed)
            except ValueError:
                print("(contingent read skipped — its cell is not fully dispatched)")
        if args.read in ("matrix", "all"):
            print()
            matrix_read(store, index, stamp.version,
                        n_resamples=args.resamples, seed=args.seed)


if __name__ == "__main__":
    main()
