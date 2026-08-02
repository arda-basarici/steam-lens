"""The curves-checkpoint figures — rendered views over a sweep run of record.

Reads one ``m2sweep`` run directory (``measurements.jsonl`` + ``manifest.json``)
and regenerates the two centerpiece figures the checkpoint rules over:

- ``error_curves.png`` — absolute share error vs sample size, per policy:
  the median and the p90 over all (game × anchor × aspect) cells, the ruled
  replication population. The p90 panel is the tolerance conversation: "at
  size n, 90% of displayed shares land within this."
- ``coverage_curves.png`` — measured interval coverage vs sample size, one
  panel per policy, one line per candidate method against the nominal 95%.

Figures are regenerable views, never precious: they land in the run's own
``figures/`` folder and re-running overwrites them (keep the run artifact,
regenerate plots). Uniform-reference cells enter the pools by their per-cell
mean over the seeded repeats; deterministic cells by their single fixed error.

Run from the repo root:
  uv run --with matplotlib python scripts/plot_sweep_curves.py data/runs/<m2sweep-run-id>
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

# The dataviz reference palette's fixed categorical order (slots 1-4, light
# mode): color follows the entity, so every figure paints a policy the same.
POLICY_COLORS = {
    "uniform-random": "#2a78d6",
    "time-proportional": "#eb6834",
    "equal-per-window": "#1baf7a",
    "cursor-prefix": "#eda100",
}
POLICY_ORDER = tuple(POLICY_COLORS)
METHOD_COLORS = {"wilson": "#2a78d6", "bootstrap": "#eb6834", "stratified": "#1baf7a"}
_INK = "#333333"
_MUTED = "#767676"
_GRID = "#e3e3e3"


def load_rows(run_dir: Path) -> list[dict[str, object]]:
    """Every measurement row of the run — one dict per (cell, aspect)."""
    path = run_dir / "measurements.jsonl"
    with path.open(encoding="utf-8") as lines:
        return [json.loads(line) for line in lines if line.strip()]


def error_pools(
    rows: list[dict[str, object]],
) -> dict[tuple[str, int], list[float]]:
    """Cell mean errors pooled per (policy, size) over games × anchors × aspects."""
    pools: dict[tuple[str, int], list[float]] = defaultdict(list)
    for row in rows:
        pools[(str(row["policy"]), int(row["size"]))].append(float(row["mean_error"]))  # type: ignore[arg-type]
    return pools


def coverage_pools(
    rows: list[dict[str, object]],
) -> dict[tuple[str, str, int], list[float]]:
    """Per-cell coverage rates pooled per (policy, method, size)."""
    pools: dict[tuple[str, str, int], list[float]] = defaultdict(list)
    for row in rows:
        for method in ("wilson", "bootstrap", "stratified"):
            reading = row.get(method)
            if isinstance(reading, dict):
                pools[(str(row["policy"]), method, int(row["size"]))].append(  # type: ignore[arg-type]
                    float(reading["coverage"])
                )
    return pools


def quantile(ordered: list[float], q: float) -> float:
    """Linear-interpolation quantile of a pre-sorted list."""
    position = q * (len(ordered) - 1)
    low, high = int(position), min(int(position) + 1, len(ordered) - 1)
    fraction = position - low
    return ordered[low] * (1 - fraction) + ordered[high] * fraction


def _style_axis(ax: plt.Axes) -> None:
    """Recessive grid and spines; the data carries the figure."""
    ax.grid(True, color=_GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(_MUTED)
    ax.tick_params(colors=_MUTED, labelsize=8)


def plot_error_curves(rows: list[dict[str, object]], sizes: list[int], out: Path) -> None:
    """Median and p90 absolute share error vs size, one line per policy."""
    pools = error_pools(rows)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), dpi=150, sharey=True)
    for ax, q, title in ((axes[0], 0.5, "median"), (axes[1], 0.9, "p90")):
        _style_axis(ax)
        for policy in POLICY_ORDER:
            xs = [size for size in sizes if pools.get((policy, size))]
            ys = [quantile(sorted(pools[(policy, size)]), q) for size in xs]
            ax.plot(
                xs, ys, color=POLICY_COLORS[policy], linewidth=2,
                marker="o", markersize=3.5, label=policy,
            )
        ax.set_xscale("log")
        ax.set_xticks(sizes)
        ax.set_xticklabels([str(s) for s in sizes], rotation=45)
        ax.minorticks_off()
        ax.set_xlabel("sample size", color=_INK, fontsize=9)
        ax.set_title(f"{title} absolute share error", color=_INK, fontsize=10)
    axes[1].legend(fontsize=8, frameon=False, loc="upper right")
    axes[0].set_ylabel("|sample share − census share|", color=_INK, fontsize=9)
    fig.suptitle(
        "Convergence over the certified population (games × anchors × aspects)",
        color=_INK, fontsize=11,
    )
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)


def plot_coverage_curves(rows: list[dict[str, object]], sizes: list[int], out: Path) -> None:
    """Measured coverage vs size, faceted per policy, against nominal 95%."""
    pools = coverage_pools(rows)
    fig, axes = plt.subplots(1, 4, figsize=(13, 3.6), dpi=150, sharey=True)
    for ax, policy in zip(axes, POLICY_ORDER, strict=True):
        _style_axis(ax)
        ax.axhline(0.95, color=_MUTED, linewidth=1, linestyle="--")
        for method, color in METHOD_COLORS.items():
            xs = [size for size in sizes if pools.get((policy, method, size))]
            if not xs:
                continue
            ys = [
                sum(pools[(policy, method, size)]) / len(pools[(policy, method, size)])
                for size in xs
            ]
            ax.plot(xs, ys, color=color, linewidth=2, marker="o", markersize=3, label=method)
        ax.set_xscale("log")
        ax.set_xticks(sizes)
        ax.set_xticklabels([str(s) for s in sizes], rotation=45)
        ax.minorticks_off()
        ax.set_title(policy, color=_INK, fontsize=10)
        ax.set_xlabel("sample size", color=_INK, fontsize=9)
    axes[0].set_ylabel("measured coverage", color=_INK, fontsize=9)
    # the legend lives on a windowed panel — the only place all three methods draw
    axes[1].legend(fontsize=8, frameon=False, loc="lower right")
    fig.suptitle(
        "Interval calibration: measured coverage vs the quoted 95%",
        color=_INK, fontsize=11,
    )
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    """Render both figures into ``<run_dir>/figures/``."""
    if len(sys.argv) != 2:
        raise SystemExit("usage: plot_sweep_curves.py <m2sweep run directory>")
    run_dir = Path(sys.argv[1])
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    sizes = [int(size) for size in manifest["sizes"]]
    rows = load_rows(run_dir)
    figures_dir = run_dir / "figures"
    figures_dir.mkdir(exist_ok=True)
    plot_error_curves(rows, sizes, figures_dir / "error_curves.png")
    plot_coverage_curves(rows, sizes, figures_dir / "coverage_curves.png")
    print(f"{len(rows):,} rows -> {figures_dir / 'error_curves.png'}")
    print(f"{'':>14}-> {figures_dir / 'coverage_curves.png'}")


if __name__ == "__main__":
    main()
