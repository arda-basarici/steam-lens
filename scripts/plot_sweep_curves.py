"""The curves-checkpoint figures — rendered views over a sweep run of record.

Reads one ``m2sweep`` run directory (``measurements.jsonl`` + ``manifest.json``)
and regenerates the checkpoint's figure pack:

- ``error_curves.png`` — absolute share error vs sample size, per policy:
  the median and the p90 over all (game × anchor × aspect) cells, the ruled
  replication population. The p90 panel is the tolerance conversation: "at
  size n, 90% of displayed shares land within this."
- ``coverage_curves.png`` — measured interval coverage vs sample size, one
  panel per policy, one line per candidate method against the nominal 95%.
- ``signed_bias.png`` — signed error (sample − census share) per policy:
  median line with a p10–p90 band. Absolute-error pooling can cancel
  direction across aspects; this view is where cursor-prefix's trust-panel
  disclosure number comes from, and where a windowed policy would betray a
  net drift.
- ``error_by_share_band.png`` — the p90 error curves sliced by the aspect's
  census share (small / mid / large): absolute error scales with
  ``sqrt(p(1-p))``, so one pooled tolerance blurs bands the display treats
  very differently.
- ``error_by_pool_size.png`` — the p90 error curves sliced by the anchor
  pool's size: previews whether one (cutoff, n) size rule is plausible or
  the rule must condition on game size (the long-tail split stage then
  formalizes it).

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
from collections.abc import Callable
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


def plot_signed_bias(rows: list[dict[str, object]], sizes: list[int], out: Path) -> None:
    """Median signed error with a p10-p90 band, faceted per policy, zero-anchored."""
    pools: dict[tuple[str, int], list[float]] = defaultdict(list)
    for row in rows:
        signed = float(row["mean_sample_share"]) - float(row["reference_share"])  # type: ignore[arg-type]
        pools[(str(row["policy"]), int(row["size"]))].append(signed)  # type: ignore[arg-type]
    fig, axes = plt.subplots(1, 4, figsize=(13, 3.6), dpi=150, sharey=True)
    for ax, policy in zip(axes, POLICY_ORDER, strict=True):
        _style_axis(ax)
        ax.axhline(0.0, color=_MUTED, linewidth=1, linestyle="--")
        xs = [size for size in sizes if pools.get((policy, size))]
        ordered = [sorted(pools[(policy, size)]) for size in xs]
        color = POLICY_COLORS[policy]
        ax.plot(
            xs, [quantile(values, 0.5) for values in ordered],
            color=color, linewidth=2, marker="o", markersize=3,
        )
        ax.fill_between(
            xs,
            [quantile(values, 0.1) for values in ordered],
            [quantile(values, 0.9) for values in ordered],
            color=color, alpha=0.18, linewidth=0,
        )
        ax.set_xscale("log")
        ax.set_xticks(sizes)
        ax.set_xticklabels([str(s) for s in sizes], rotation=45)
        ax.minorticks_off()
        ax.set_title(policy, color=_INK, fontsize=10)
        ax.set_xlabel("sample size", color=_INK, fontsize=9)
    axes[0].set_ylabel("sample share − census share\n(median, p10–p90 band)",
                       color=_INK, fontsize=9)
    fig.suptitle("Signed bias per policy — direction the |error| pooling can hide",
                 color=_INK, fontsize=11)
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)


def _facet_p90_error(
    rows: list[dict[str, object]],
    sizes: list[int],
    out: Path,
    band_of: Callable[[dict[str, object]], str],
    band_order: list[str],
    suptitle: str,
) -> None:
    """The p90 |error| curves per policy, faceted by a row-derived band."""
    pools: dict[tuple[str, str, int], list[float]] = defaultdict(list)
    for row in rows:
        key = (band_of(row), str(row["policy"]), int(row["size"]))  # type: ignore[arg-type]
        pools[key].append(float(row["mean_error"]))  # type: ignore[arg-type]
    fig, axes = plt.subplots(1, len(band_order), figsize=(11, 3.8), dpi=150, sharey=True)
    for ax, band in zip(axes, band_order, strict=True):
        _style_axis(ax)
        for policy in POLICY_ORDER:
            xs = [size for size in sizes if pools.get((band, policy, size))]
            ys = [quantile(sorted(pools[(band, policy, size)]), 0.9) for size in xs]
            ax.plot(
                xs, ys, color=POLICY_COLORS[policy], linewidth=2,
                marker="o", markersize=3, label=policy,
            )
        ax.set_xscale("log")
        ax.set_xticks(sizes)
        ax.set_xticklabels([str(s) for s in sizes], rotation=45)
        ax.minorticks_off()
        cells = sum(len(v) for (b, _, _), v in pools.items() if b == band)
        ax.set_title(f"{band}  ({cells:,} cells)", color=_INK, fontsize=10)
        ax.set_xlabel("sample size", color=_INK, fontsize=9)
    axes[-1].legend(fontsize=8, frameon=False, loc="upper right")
    axes[0].set_ylabel("p90 |sample − census share|", color=_INK, fontsize=9)
    fig.suptitle(suptitle, color=_INK, fontsize=11)
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)


def plot_error_by_share_band(
    rows: list[dict[str, object]], sizes: list[int], out: Path
) -> None:
    """The p90 curves sliced by the aspect's census share."""
    def band(row: dict[str, object]) -> str:
        share = float(row["reference_share"])  # type: ignore[arg-type]
        if share < 0.05:
            return "share < 5%"
        if share < 0.15:
            return "share 5–15%"
        return "share ≥ 15%"

    _facet_p90_error(
        rows, sizes, out, band, ["share < 5%", "share 5–15%", "share ≥ 15%"],
        "Convergence by census share — one tolerance means different things per band",
    )


def plot_error_by_pool_size(
    rows: list[dict[str, object]], sizes: list[int], out: Path
) -> None:
    """The p90 curves sliced by the anchor pool's population."""
    def band(row: dict[str, object]) -> str:
        pool = int(row["pool_size"])  # type: ignore[arg-type]
        if pool < 1000:
            return "pool < 1k"
        if pool < 3000:
            return "pool 1–3k"
        return "pool ≥ 3k"

    _facet_p90_error(
        rows, sizes, out, band, ["pool < 1k", "pool 1–3k", "pool ≥ 3k"],
        "Convergence by anchor-pool size — is one (cutoff, n) rule plausible?",
    )


def plot_coverage_by_share_band(
    rows: list[dict[str, object]], sizes: list[int], out: Path
) -> None:
    """Interval coverage sliced by census share, under the primary-path policy.

    The pooled coverage figure is dominated by small-share cells; this view
    asks whether each method keeps its promise on the big-share aspects a
    report leads with, for time-proportional draws specifically.
    """
    bands = ["share < 5%", "share 5–15%", "share ≥ 15%"]

    def band(row: dict[str, object]) -> str:
        share = float(row["reference_share"])  # type: ignore[arg-type]
        if share < 0.05:
            return bands[0]
        if share < 0.15:
            return bands[1]
        return bands[2]

    pools: dict[tuple[str, str, int], list[float]] = defaultdict(list)
    for row in rows:
        if row["policy"] != "time-proportional":
            continue
        for method in ("wilson", "bootstrap", "stratified"):
            reading = row.get(method)
            if isinstance(reading, dict):
                pools[(band(row), method, int(row["size"]))].append(  # type: ignore[arg-type]
                    float(reading["coverage"])
                )
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.8), dpi=150, sharey=True)
    for ax, band_name in zip(axes, bands, strict=True):
        _style_axis(ax)
        ax.axhline(0.95, color=_MUTED, linewidth=1, linestyle="--")
        for method, color in METHOD_COLORS.items():
            xs = [size for size in sizes if pools.get((band_name, method, size))]
            if not xs:
                continue
            ys = [
                sum(pools[(band_name, method, size)]) / len(pools[(band_name, method, size)])
                for size in xs
            ]
            ax.plot(xs, ys, color=color, linewidth=2, marker="o", markersize=3, label=method)
        ax.set_xscale("log")
        ax.set_xticks(sizes)
        ax.set_xticklabels([str(s) for s in sizes], rotation=45)
        ax.minorticks_off()
        cells = sum(len(v) for (b, _, _), v in pools.items() if b == band_name) // 3
        ax.set_title(f"{band_name}  (~{cells:,} cells)", color=_INK, fontsize=10)
        ax.set_xlabel("sample size", color=_INK, fontsize=9)
    axes[0].set_ylabel("measured coverage", color=_INK, fontsize=9)
    axes[-1].legend(fontsize=8, frameon=False, loc="lower right")
    fig.suptitle(
        "Coverage by census share under time-proportional draws — the promise where it's loudest",
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
    plot_signed_bias(rows, sizes, figures_dir / "signed_bias.png")
    plot_error_by_share_band(rows, sizes, figures_dir / "error_by_share_band.png")
    plot_error_by_pool_size(rows, sizes, figures_dir / "error_by_pool_size.png")
    plot_coverage_by_share_band(rows, sizes, figures_dir / "coverage_by_share_band.png")
    print(f"{len(rows):,} rows -> 6 figures under {figures_dir}")


if __name__ == "__main__":
    main()
