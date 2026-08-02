"""Mint the per-band bias allowance constants from a sweep run of record.

The graduation of the curves checkpoint's in-session scratch (the FIXLOG
entry of 2026-08-02): DESIGN promises the shipped constants "re-derive from
the run of record, never hand-carried", and this script is that derivation as
a committed, rerunnable view. Reads one ``m2sweep`` run directory
(``measurements.jsonl``) and prints, for the primary policy and the fallback:

- the full calibration table — per band and ladder size, the cell count,
  Wilson's raw coverage, and the flat inflation restoring the 95% register
  (the checkpoint's decision table, regenerable);
- the shipped constants — the smoothed allowance per band (the max over the
  shipped n=1,000 tier and its ladder neighbors), which must reproduce the
  ruled tail 0.000 / mid 0.005 / headline 0.073 on the run of record;
- the shipped half-width per band at n=1,000 — Wilson's mean half-width plus
  the constant, the "headline ships at roughly ±10 points" number.

Only deterministic sampled draws enter: the windowed policies' cells are
single fixed draws (the uniform reference is a simulation baseline, and
equal-per-window was eliminated at the checkpoint — neither ships). The
inflation is the centered reading off the stored fields — error minus half
the mean Wilson width — the reading the ruled constants were minted from
(the module docstring carries the why).

Run from the repo root:
  uv run python scripts/mint_allowances.py data/runs/<m2sweep-run-id>
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

from steamlens.studies.allowance import (
    SHIPPED_SAMPLE_SIZE,
    ShareBand,
    flat_allowance,
    needed_inflation,
    share_band,
    smoothed_allowance,
)

MINTED_POLICIES = ("time-proportional", "cursor-prefix")
BAND_ORDER = (ShareBand.TAIL, ShareBand.MID, ShareBand.HEADLINE)


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


def main() -> None:
    """Read the run, calibrate per policy × band × size, print the tables."""
    if len(sys.argv) != 2:
        raise SystemExit("usage: mint_allowances.py <run-dir>")
    run_dir = Path(sys.argv[1])
    rows = load_rows(run_dir)

    pools: dict[tuple[str, ShareBand, int], list[float]] = defaultdict(list)
    widths: dict[tuple[str, ShareBand], list[float]] = defaultdict(list)
    for row in rows:
        policy = str(row["policy"])
        if policy not in MINTED_POLICIES:
            continue
        band = share_band(float(row["reference_share"]))  # type: ignore[arg-type]
        size = int(row["size"])  # type: ignore[arg-type]
        pools[(policy, band, size)].append(row_inflation(row))
        if size == SHIPPED_SAMPLE_SIZE:
            widths[(policy, band)].append(mean_wilson_width(row))

    sizes = sorted({size for _, _, size in pools})
    for policy in MINTED_POLICIES:
        print(f"\n=== {policy} ===")
        print(f"{'band':<10}{'size':>6}{'cells':>8}{'wilson cov':>12}{'inflation':>11}")
        calibrations: dict[ShareBand, dict[int, float]] = {band: {} for band in BAND_ORDER}
        for band in BAND_ORDER:
            for size in sizes:
                pool = pools.get((policy, band, size))
                if not pool:
                    continue
                covered = sum(1 for value in pool if value == 0.0) / len(pool)
                delta = flat_allowance(pool)
                calibrations[band][size] = delta
                print(f"{band:<10}{size:>6}{len(pool):>8}{covered:>12.3f}{delta:>11.4f}")

        print(f"\nshipped constants (n={SHIPPED_SAMPLE_SIZE}, smoothed over neighbors):")
        for band in BAND_ORDER:
            constant = smoothed_allowance(calibrations[band], shipped=SHIPPED_SAMPLE_SIZE)
            width_pool = widths.get((policy, band), [])
            half_width = (
                sum(width_pool) / len(width_pool) / 2 + constant if width_pool else None
            )
            shipped = "" if half_width is None else f"   shipped half-width {half_width:.3f}"
            print(f"  {band:<10}{constant:.3f}  (raw {constant:.6f}){shipped}")


if __name__ == "__main__":
    main()
