"""Mint the per-band bias allowance constants from a sweep run of record.

The graduation of the curves checkpoint's in-session scratch (the FIXLOG
entry of 2026-08-02): DESIGN promises the shipped constants "re-derive from
the run of record, never hand-carried", and this script is that derivation as
a committed, rerunnable view. Since the long-tail stage-1 ruling (2026-08-03)
the shipped constants condition on the pool's spikiness regime — calm pools
need no allowance at all, spiky pools (peak window share at or above
two-thirds) carry the full measured price — so the mint reads the corpus too:
regime assignment needs each anchored pool's histogram. For the primary
policy and the fallback, per regime (plus the superseded flat pooling, kept
as the checkpoint's historical view):

- the full calibration table — per band and ladder size, the cell count,
  Wilson's raw coverage, and the flat inflation restoring the 95% register;
- the shipped constants — the smoothed allowance per band (the max over the
  shipped n=1,000 tier and its ladder neighbors). On the run of record the
  flat view must reproduce the checkpoint's tail 0.000 / mid 0.005 /
  headline 0.073, and the regimes the stage-1 ruling's calm 0.000 / 0.000 /
  0.000 and spiky 0.000 / 0.017 / 0.127;
- the shipped half-width per band at n=1,000 — Wilson's mean half-width plus
  the constant.

Only deterministic sampled draws enter: the windowed policies' cells are
single fixed draws (the uniform reference is a simulation baseline, and
equal-per-window was eliminated at the checkpoint — neither ships). The
inflation is the centered reading off the stored fields — error minus half
the mean Wilson width — the reading the ruled constants were minted from
(the module docstring carries the why). Spikiness histograms build over the
corpus's usable pools; the sweep drew from the labeled subset — a
manifest-recorded handful apart per game, noise at this metric's scale.

Run from the repo root:
  uv run python scripts/mint_allowances.py data/runs/<m2sweep-run-id>
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from steamlens.corpus import read_reviews_file
from steamlens.studies.allowance import (
    SHIPPED_SAMPLE_SIZE,
    ShareBand,
    flat_allowance,
    is_spiky_regime,
    needed_inflation,
    share_band,
    smoothed_allowance,
)
from steamlens.studies.sample_corpus import corpus_histogram
from steamlens.studies.shape import peak_window_share
from steamlens.studies.sweep_corpus import truncate_pool

MINTED_POLICIES = ("time-proportional", "cursor-prefix")
BAND_ORDER = (ShareBand.TAIL, ShareBand.MID, ShareBand.HEADLINE)
REGIME_ORDER = ("calm", "spiky", "flat (superseded)")


def load_rows(run_dir: Path) -> list[dict[str, object]]:
    """Every measurement row of the run — one dict per (cell, aspect)."""
    path = run_dir / "measurements.jsonl"
    with path.open(encoding="utf-8") as lines:
        return [json.loads(line) for line in lines if line.strip()]


def mean_wilson_width(row: dict[str, object]) -> float:
    """The stored mean Wilson width of one row, typed out of the raw JSON."""
    wilson = row["wilson"]
    assert isinstance(wilson, dict)
    return float(wilson["mean_width"])  # type: ignore[arg-type]


def row_inflation(row: dict[str, object]) -> float:
    """One row's needed inflation — the centered reading off its stored fields."""
    return needed_inflation(
        float(row["mean_error"]),  # type: ignore[arg-type]
        mean_wilson_width(row),
    )


def spiky_units(manifest: dict[str, object], corpus_dir: Path) -> set[tuple[int, float]]:
    """The (app_id, anchor_quantile) units in the spiky regime — one corpus pass.

    The anchored pool is rebuilt the sweep's way — truncate at the manifest's
    recorded cutoff, roll into the monthly histogram — and the regime is the
    ruled boundary over its peak window share.
    """
    games = manifest["games"]
    assert isinstance(games, dict)
    spiky: set[tuple[int, float]] = set()
    for app_id, meta in games.items():
        path = corpus_dir / f"{app_id}_reviews.jsonl"
        if not path.is_file():
            raise SystemExit(f"corpus file missing for app {app_id}: {path}")
        reviews = read_reviews_file(path).reviews
        for anchor in meta["anchors"]:
            pool = truncate_pool(reviews, datetime.fromisoformat(anchor["cutoff"]))
            if is_spiky_regime(peak_window_share(corpus_histogram(pool))):
                spiky.add((int(app_id), float(anchor["quantile"])))
    return spiky


def main() -> None:
    """Read the run, calibrate per policy × regime × band × size, print the tables."""
    parser = argparse.ArgumentParser(
        description="Mint the shipped allowance constants from a sweep run of record."
    )
    parser.add_argument("run_dir", type=Path, help="the m2sweep run directory")
    parser.add_argument("--corpus", type=Path, default=None,
                        help="corpus reviews dir (default: the manifest's corpus_dir)")
    args = parser.parse_args()

    manifest = json.loads((args.run_dir / "manifest.json").read_text(encoding="utf-8"))
    corpus_dir = args.corpus if args.corpus is not None else Path(str(manifest["corpus_dir"]))
    spiky = spiky_units(manifest, corpus_dir)
    rows = load_rows(args.run_dir)

    pools: dict[tuple[str, str, ShareBand, int], list[float]] = defaultdict(list)
    widths: dict[tuple[str, str, ShareBand], list[float]] = defaultdict(list)
    for row in rows:
        policy = str(row["policy"])
        if policy not in MINTED_POLICIES:
            continue
        unit = (int(row["app_id"]), float(row["anchor_quantile"]))  # type: ignore[arg-type]
        band = share_band(float(row["reference_share"]))  # type: ignore[arg-type]
        size = int(row["size"])  # type: ignore[arg-type]
        regime = "spiky" if unit in spiky else "calm"
        inflation = row_inflation(row)
        for bucket in (regime, "flat (superseded)"):
            pools[(policy, bucket, band, size)].append(inflation)
            if size == SHIPPED_SAMPLE_SIZE:
                widths[(policy, bucket, band)].append(mean_wilson_width(row))

    sizes = sorted({size for _, _, _, size in pools})
    for policy in MINTED_POLICIES:
        print(f"\n=== {policy} ===")
        for regime in REGIME_ORDER:
            print(f"\n--- {regime} ---")
            print(f"{'band':<10}{'size':>6}{'cells':>8}{'wilson cov':>12}{'inflation':>11}")
            calibrations: dict[ShareBand, dict[int, float]] = {band: {} for band in BAND_ORDER}
            for band in BAND_ORDER:
                for size in sizes:
                    pool = pools.get((policy, regime, band, size))
                    if not pool:
                        continue
                    covered = sum(1 for value in pool if value == 0.0) / len(pool)
                    delta = flat_allowance(pool)
                    calibrations[band][size] = delta
                    print(f"{band:<10}{size:>6}{len(pool):>8}{covered:>12.3f}{delta:>11.4f}")

            print(f"shipped constants (n={SHIPPED_SAMPLE_SIZE}, smoothed over neighbors):")
            for band in BAND_ORDER:
                if SHIPPED_SAMPLE_SIZE not in calibrations[band]:
                    print(f"  {band:<10}n/a (no cells at the shipped tier)")
                    continue
                constant = smoothed_allowance(calibrations[band], shipped=SHIPPED_SAMPLE_SIZE)
                width_pool = widths.get((policy, regime, band), [])
                half_width = (
                    sum(width_pool) / len(width_pool) / 2 + constant if width_pool else None
                )
                shipped = (
                    "" if half_width is None else f"   shipped half-width {half_width:.3f}"
                )
                print(f"  {band:<10}{constant:.3f}  (raw {constant:.6f}){shipped}")


if __name__ == "__main__":
    main()
