"""The long-tail stage-1 splits — the sweep's curves sliced by game shape.

Within-corpus transfer evidence (DESIGN, the study-design section): the ruled
size rule was certified over the whole corpus pooled; this view asks whether
it *holds across game shapes* or must condition on them. Three axes, one
value per (game, anchor) unit — the replication population's own grain:

- **population** — the anchor pool's size (the manifest's per-anchor count),
  tercile split;
- **temporal spikiness** — ``peak_window_share`` over the anchored pool's
  monthly histogram (the largest single window's claim on the draw),
  tercile split;
- **aspect concentration** — ``headline_aspect_count`` over the anchor's
  census shares, split into discrete groups (0 / 1 / 2+): 113 of the run of
  record's 243 units hold zero headline aspects, so equal-count terciles
  would cut through a tie and file identical units under different groups.

For each axis: a figure — the primary policy's p90 error curves per share
band, one line per shape group — and a ruling table at the shipped
n=1,000 — the register error against the ruled tolerance (tail ±1pt,
mid ±2.5pt), and the shipped interval's coverage (Wilson plus the per-band
allowance, re-derived from this run via the mint arithmetic, never
hand-carried) against the 95% register. Curves flat across groups mean the
transfer risk is measured, not suspected; curves that vary are the case for
a shape-conditioned size rule.

Two honesty caveats ride the readings. Spikiness histograms are built over
the corpus's *usable* pools; the sweep drew from the *labeled* subset — the
gap is a manifest-recorded handful per game, noise at this metric's scale.
And the corpus is ~50 popular games, so the "low population" tercile is
small-among-popular: these splits measure within-corpus shape sensitivity;
genuinely long-tail structure is what the frame checks (stage 2) and the
closing test probe.

Figures land in the run's own ``figures/`` folder, regenerable. Run from
the repo root:
  uv run --with matplotlib python scripts/split_sweep_by_shape.py data/runs/<m2sweep-run-id>
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from steamlens.core.allowance import (  # noqa: E402
    SHIPPED_SAMPLE_SIZE,
    ShareBand,
    peak_window_share,
    share_band,
)
from steamlens.corpus import read_reviews_file  # noqa: E402
from steamlens.studies.allowance import (  # noqa: E402
    flat_allowance,
    needed_inflation,
    smoothed_allowance,
)
from steamlens.studies.sample_corpus import corpus_histogram  # noqa: E402
from steamlens.studies.shape import headline_aspect_count  # noqa: E402
from steamlens.studies.sweep_corpus import truncate_pool  # noqa: E402

PRIMARY_POLICY = "time-proportional"
BAND_ORDER = (ShareBand.TAIL, ShareBand.MID, ShareBand.HEADLINE)
BAND_TITLES = {
    ShareBand.TAIL: "share < 5%",
    ShareBand.MID: "share 5–15%",
    ShareBand.HEADLINE: "share ≥ 15%",
}
RULED_TOLERANCES = {ShareBand.TAIL: 0.010, ShareBand.MID: 0.025}
"""The checkpoint's band tolerances at the 95% register; headline carries
none — its promise is the calibrated interval, checked as coverage below."""

# The dataviz reference palette's blue ordinal ramp (steps 250/450/650,
# validated): shape groups are ordered low→high, so one hue, light→dark.
GROUP_COLORS = ("#86b6ef", "#2a78d6", "#104281")
_INK = "#333333"
_MUTED = "#767676"
_GRID = "#e3e3e3"

Unit = tuple[int, float]
"""One (app_id, anchor_quantile) replication unit."""


def load_rows(run_dir: Path) -> list[dict[str, object]]:
    """Every measurement row of the run — one dict per (cell, aspect)."""
    path = run_dir / "measurements.jsonl"
    with path.open(encoding="utf-8") as lines:
        return [json.loads(line) for line in lines if line.strip()]


def row_unit(row: dict[str, object]) -> Unit:
    """The (game, anchor) unit a measurement row belongs to."""
    return int(row["app_id"]), float(row["anchor_quantile"])  # type: ignore[arg-type]


def population_by_unit(manifest: dict[str, object]) -> dict[Unit, float]:
    """Each unit's anchor pool size, from the manifest's per-game anchor list."""
    games = manifest["games"]
    assert isinstance(games, dict)
    pools: dict[Unit, float] = {}
    for app_id, meta in games.items():
        for anchor in meta["anchors"]:
            pools[(int(app_id), float(anchor["quantile"]))] = float(anchor["pool"])
    return pools


def spikiness_by_unit(manifest: dict[str, object], corpus_dir: Path) -> dict[Unit, float]:
    """Each unit's peak window share, from one corpus pass per game.

    The anchored pool is rebuilt the sweep's way — truncate at the manifest's
    recorded cutoff, roll into the monthly histogram — over the usable pool
    (the labeled subset differs by a manifest-recorded handful per game).
    """
    games = manifest["games"]
    assert isinstance(games, dict)
    shares: dict[Unit, float] = {}
    for app_id, meta in games.items():
        path = corpus_dir / f"{app_id}_reviews.jsonl"
        if not path.is_file():
            raise SystemExit(f"corpus file missing for app {app_id}: {path}")
        reviews = read_reviews_file(path).reviews
        for anchor in meta["anchors"]:
            pool = truncate_pool(reviews, datetime.fromisoformat(anchor["cutoff"]))
            shares[(int(app_id), float(anchor["quantile"]))] = peak_window_share(
                corpus_histogram(pool)
            )
    return shares


def concentration_by_unit(rows: list[dict[str, object]]) -> dict[Unit, float]:
    """Each unit's headline-aspect count, from the rows' own reference shares."""
    references: dict[Unit, dict[str, float]] = defaultdict(dict)
    for row in rows:
        references[row_unit(row)][str(row["aspect"])] = float(row["reference_share"])  # type: ignore[arg-type]
    return {unit: float(headline_aspect_count(shares)) for unit, shares in references.items()}


def tercile_groups(values: dict[Unit, float]) -> tuple[dict[Unit, int], list[str]]:
    """Equal-count terciles over the units, with value-range labels.

    Units sort by (value, unit) so ties split deterministically; the labels
    carry each tercile's actual value range so a reader sees what "low"
    meant on this run.
    """
    ordered = sorted(values, key=lambda unit: (values[unit], unit))
    cuts = (len(ordered) // 3, 2 * len(ordered) // 3)
    assignment = {
        unit: (0 if index < cuts[0] else 1 if index < cuts[1] else 2)
        for index, unit in enumerate(ordered)
    }
    labels = []
    for group in range(3):
        members = [values[unit] for unit in ordered if assignment[unit] == group]
        labels.append(f"{_terse(min(members))}-{_terse(max(members))}")
    return assignment, labels


def _terse(value: float) -> str:
    """A range-label number: integers plain, fractions at two decimals."""
    return f"{value:g}" if value == int(value) else f"{value:.2f}"


def discrete_groups(values: dict[Unit, float]) -> tuple[dict[Unit, int], list[str]]:
    """The concentration axis's 0 / 1 / 2+ groups — ties never split."""
    assignment = {
        unit: (0 if count == 0 else 1 if count == 1 else 2) for unit, count in values.items()
    }
    return assignment, ["0", "1", "2+"]


def register_statistic(values: list[float], register: float = 0.95) -> float:
    """The minimal value at or below which the register's fraction of draws sits."""
    ordered = sorted(values)
    return ordered[math.ceil(register * len(ordered)) - 1]


def shipped_constants(rows: list[dict[str, object]]) -> dict[ShareBand, float]:
    """The per-band allowance constants, re-derived from this run's own rows."""
    pools: dict[tuple[ShareBand, int], list[float]] = defaultdict(list)
    for row in rows:
        if str(row["policy"]) != PRIMARY_POLICY:
            continue
        band = share_band(float(row["reference_share"]))  # type: ignore[arg-type]
        pools[(band, int(row["size"]))].append(_row_inflation(row))  # type: ignore[arg-type]
    constants: dict[ShareBand, float] = {}
    for band in BAND_ORDER:
        calibrations = {
            size: flat_allowance(pool) for (b, size), pool in pools.items() if b is band
        }
        constants[band] = smoothed_allowance(calibrations, shipped=SHIPPED_SAMPLE_SIZE)
    return constants


def _row_inflation(row: dict[str, object]) -> float:
    """One row's needed inflation — the centered reading off its stored fields."""
    wilson = row["wilson"]
    assert isinstance(wilson, dict)
    return needed_inflation(
        float(row["mean_error"]),  # type: ignore[arg-type]
        float(wilson["mean_width"]),  # type: ignore[arg-type]
    )


def _style_axis(ax: plt.Axes) -> None:
    """Recessive grid and spines; the data carries the figure."""
    ax.grid(True, color=_GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(_MUTED)
    ax.tick_params(colors=_MUTED, labelsize=8)


def plot_split(
    rows: list[dict[str, object]],
    sizes: list[int],
    assignment: dict[Unit, int],
    group_labels: list[str],
    axis_name: str,
    out: Path,
) -> None:
    """The primary policy's p90 error curves per band, one line per shape group."""
    pools: dict[tuple[ShareBand, int, int], list[float]] = defaultdict(list)
    for row in rows:
        if str(row["policy"]) != PRIMARY_POLICY:
            continue
        band = share_band(float(row["reference_share"]))  # type: ignore[arg-type]
        key = (band, assignment[row_unit(row)], int(row["size"]))  # type: ignore[arg-type]
        pools[key].append(float(row["mean_error"]))  # type: ignore[arg-type]

    fig, axes = plt.subplots(1, len(BAND_ORDER), figsize=(11, 3.8), dpi=150, sharey=True)
    for ax, band in zip(axes, BAND_ORDER, strict=True):
        _style_axis(ax)
        for group, (label, color) in enumerate(zip(group_labels, GROUP_COLORS, strict=True)):
            xs = [size for size in sizes if pools.get((band, group, size))]
            ys = [register_statistic(pools[(band, group, size)], 0.90) for size in xs]
            ax.plot(
                xs, ys, color=color, linewidth=2,
                marker="o", markersize=3, label=label,
            )
        ax.set_xscale("log")
        ax.set_xticks(sizes)
        ax.set_xticklabels([str(s) for s in sizes], rotation=45)
        ax.minorticks_off()
        cells = sum(len(v) for (b, _, _), v in pools.items() if b is band)
        ax.set_title(f"{BAND_TITLES[band]}  ({cells:,} cells)", color=_INK, fontsize=10)
        ax.set_xlabel("sample size", color=_INK, fontsize=9)
    axes[-1].legend(fontsize=8, frameon=False, loc="upper right", title=axis_name, title_fontsize=8)
    axes[0].set_ylabel("p90 |sample − census share|", color=_INK, fontsize=9)
    fig.suptitle(
        f"{PRIMARY_POLICY} convergence by {axis_name} — flat lines mean the rule transfers",
        color=_INK, fontsize=11,
    )
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)


def ruling_table(
    rows: list[dict[str, object]],
    assignment: dict[Unit, int],
    group_labels: list[str],
    axis_name: str,
    constants: dict[ShareBand, float],
) -> None:
    """The shipped-n verdicts per shape group: register error and shipped coverage."""
    errors: dict[tuple[int, ShareBand], list[float]] = defaultdict(list)
    covered: dict[tuple[int, ShareBand], list[bool]] = defaultdict(list)
    for row in rows:
        if str(row["policy"]) != PRIMARY_POLICY or int(row["size"]) != SHIPPED_SAMPLE_SIZE:  # type: ignore[arg-type]
            continue
        band = share_band(float(row["reference_share"]))  # type: ignore[arg-type]
        key = (assignment[row_unit(row)], band)
        errors[key].append(float(row["mean_error"]))  # type: ignore[arg-type]
        covered[key].append(_row_inflation(row) <= constants[band])

    print(f"\n=== {axis_name} - at the shipped n={SHIPPED_SAMPLE_SIZE} ===")
    print(
        f"{'group':<14}{'band':<10}{'cells':>6}{'p95 err':>9}"
        f"{'tolerance':>11}{'shipped cov':>13}"
    )
    for group, label in enumerate(group_labels):
        for band in BAND_ORDER:
            pool = errors.get((group, band))
            if not pool:
                print(f"{label:<14}{band:<10}{'-':>6}{'-':>9}{'-':>11}{'-':>13}")
                continue
            p95 = register_statistic(pool)
            tolerance = RULED_TOLERANCES.get(band)
            verdict = "-" if tolerance is None else ("PASS" if p95 <= tolerance else "FAIL")
            coverage = sum(covered[(group, band)]) / len(covered[(group, band)])
            cov_mark = "ok" if coverage >= 0.95 else "LOW"
            print(
                f"{label:<14}{band:<10}{len(pool):>6}{p95:>9.4f}{verdict:>11}"
                f"{coverage:>9.3f} {cov_mark:>3}"
            )


def main() -> None:
    """Compute the shape axes, render the split figures, print the verdicts."""
    parser = argparse.ArgumentParser(
        description="Slice a sweep run's curves by game shape (long-tail stage 1)."
    )
    parser.add_argument("run_dir", type=Path, help="the m2sweep run directory")
    parser.add_argument("--corpus", type=Path, default=None,
                        help="corpus reviews dir (default: the manifest's corpus_dir)")
    args = parser.parse_args()

    manifest = json.loads((args.run_dir / "manifest.json").read_text(encoding="utf-8"))
    corpus_dir = args.corpus if args.corpus is not None else Path(str(manifest["corpus_dir"]))
    rows = load_rows(args.run_dir)
    sizes = sorted({int(row["size"]) for row in rows})  # type: ignore[arg-type]
    constants = shipped_constants(rows)
    print("allowance constants re-derived from this run:",
          {band.value: round(value, 3) for band, value in constants.items()})

    figures_dir = args.run_dir / "figures"
    figures_dir.mkdir(exist_ok=True)

    axes: list[tuple[str, dict[Unit, int], list[str]]] = []
    population, population_labels = tercile_groups(population_by_unit(manifest))
    axes.append(("pool size", population, population_labels))
    spikiness, spikiness_labels = tercile_groups(spikiness_by_unit(manifest, corpus_dir))
    axes.append(("peak window share", spikiness, spikiness_labels))
    concentration, concentration_labels = discrete_groups(concentration_by_unit(rows))
    axes.append(("headline aspects", concentration, concentration_labels))

    slugs = ("population", "spikiness", "concentration")
    for slug, (axis_name, assignment, labels) in zip(slugs, axes, strict=True):
        plot_split(rows, sizes, assignment, labels, axis_name, figures_dir / f"split_{slug}.png")
        ruling_table(rows, assignment, labels, axis_name, constants)
    print(f"\nfigures: {figures_dir}")


if __name__ == "__main__":
    main()
