"""The mixing-floor verdict — registers, floors, and figures over a mix run of record.

Reads one ``m2mix`` run directory (``measurements.jsonl`` + ``manifest.json``)
and renders the step-9 deliverable in three views:

- **The verdict tables** — per bomb source, the draw-weighted register reads
  at every contamination share (both gates against the certified 95%
  register) and the floor the prefix rule extracts; the overall floor is the
  worst case across sources (the design ruling: per-source curves, floor
  from the worst). The share-0 baseline row is the run's own control — it
  restates the checkpoint's certified promise and must pass before any floor
  is quotable.
- **The band diagnosis** — the same reads sliced by display band, pooled
  across sources: names *where* the break lives (the smoke's preview: the
  tail band, whose bomb-inflated aspects break the ±1pt tolerance first).
  Diagnosis only; the verdict never gates per band.
- **The figures** — ``figures/mix_register_curves.png`` (both registers vs
  share, per source, against the 95% rule) and
  ``figures/mix_drift_by_band.png`` (p90 across cells of the cell-mean
  error vs share, per band, one line per source, ruled tolerances drawn
  where the calm regime prices one).

The verdict also lands as ``floor_verdict.json`` beside the manifest —
floor values with their provenance, regenerable by re-running this script.
Figures are regenerable views, never precious.

Run from the repo root:
  uv run --with matplotlib python scripts/analyze_mix_floor.py data/runs/<m2mix-run-id>
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from steamlens.studies.allowance import ShareBand  # noqa: E402
from steamlens.studies.floor import (  # noqa: E402
    REGISTER,
    FloorRead,
    GateRow,
    RegisterRead,
    floor_from_reads,
    register_reads,
)

# The dataviz reference palette's fixed categorical order — color follows the
# source game across every figure and rerun.
SOURCE_COLORS = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100")
GATE_COLORS = {"tolerance": "#2a78d6", "coverage": "#eb6834"}
_MUTED = "#767676"
_GRID = "#e3e3e3"
BAND_ORDER = (ShareBand.TAIL, ShareBand.MID, ShareBand.HEADLINE)
# The calm-regime ruled tolerances, drawn as reference rules on the drift
# figure; interval-governed bands draw none.
BAND_TOLERANCE_RULES = {ShareBand.TAIL: 0.010, ShareBand.MID: 0.025}


def load_rows(run_dir: Path) -> list[dict[str, object]]:
    """Every measurement row of the run — one dict per (cell, aspect)."""
    path = run_dir / "measurements.jsonl"
    with path.open(encoding="utf-8") as lines:
        return [json.loads(line) for line in lines if line.strip()]


def gate_rows(rows: list[dict[str, object]]) -> list[GateRow]:
    """The rows' gate slices, typed out of the raw JSON."""
    out: list[GateRow] = []
    for row in rows:
        rate = row["within_tolerance_rate"]
        out.append(
            GateRow(
                source_app_id=int(row["source_app_id"]),  # type: ignore[arg-type]
                share=float(row["share"]),  # type: ignore[arg-type]
                band=ShareBand(str(row["band"])),
                repeats=int(row["repeats"]),  # type: ignore[arg-type]
                within_tolerance_rate=None if rate is None else float(rate),  # type: ignore[arg-type]
                shipped_coverage_rate=float(row["shipped_coverage_rate"]),  # type: ignore[arg-type]
            )
        )
    return out


def reads_by_source(
    rows: list[GateRow],
) -> dict[int, dict[float, RegisterRead]]:
    """The pooled register reads, regrouped per source for the floor walk."""
    grouped: dict[int, dict[float, RegisterRead]] = defaultdict(dict)
    for (source, share), read in register_reads(rows).items():
        grouped[source][share] = read
    return dict(grouped)


def _rate(value: float | None) -> str:
    return "     —" if value is None else f"{value:.4f}"


def _floor_quote(result: FloorRead) -> str:
    if result.floor is None:
        return "NO FLOOR — the share-0 baseline fails; resolve the wiring first"
    if result.censored:
        return f">= {result.floor:.2f} (grid-censored — the promise never broke)"
    return f"{result.floor:.2f}"


def print_verdicts(
    source_reads: dict[int, dict[float, RegisterRead]],
    names: dict[int, str],
) -> dict[int, FloorRead]:
    """The per-source verdict tables and floor quotes; returns the floor reads."""
    floors: dict[int, FloorRead] = {}
    for source in sorted(source_reads):
        reads = source_reads[source]
        result = floor_from_reads(reads)
        floors[source] = result
        print(f"\n== {names.get(source, str(source))} (app {source}) ==")
        print(f"{'share':>6}  {'tol rate':>8}  {'cov rate':>8}  {'draws':>7}  verdict")
        for share, passed in result.verdicts:
            read = reads[share]
            print(
                f"{share:>6.2f}  {_rate(read.tolerance_rate):>8}  "
                f"{read.coverage_rate:>8.4f}  {read.coverage_draws:>7,}  "
                f"{'pass' if passed else 'FAIL'}"
            )
        print(f"floor: {_floor_quote(result)}")
    return floors


def print_band_diagnosis(rows: list[GateRow]) -> None:
    """Where the break lives: pooled reads per band and share, across sources."""
    print("\n== band diagnosis (pooled across sources; verdict never gates here) ==")
    print(f"{'band':>9}  {'share':>6}  {'tol rate':>8}  {'cov rate':>8}")
    for band in BAND_ORDER:
        by_share: dict[float, list[GateRow]] = defaultdict(list)
        for row in rows:
            if row.band is band:
                by_share[row.share].append(row)
        for share in sorted(by_share):
            members = by_share[share]
            coverage = sum(m.shipped_coverage_rate * m.repeats for m in members) / sum(
                m.repeats for m in members
            )
            with_tolerance = [m for m in members if m.within_tolerance_rate is not None]
            tolerance = (
                sum(m.within_tolerance_rate * m.repeats for m in with_tolerance)  # type: ignore[misc]
                / sum(m.repeats for m in with_tolerance)
                if with_tolerance
                else None
            )
            print(
                f"{band.value:>9}  {share:>6.2f}  {_rate(tolerance):>8}  {coverage:>8.4f}"
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


def plot_register_curves(
    source_reads: dict[int, dict[float, RegisterRead]],
    names: dict[int, str],
    out: Path,
) -> None:
    """Both registers vs share, one panel per source, against the 95% rule."""
    sources = sorted(source_reads)
    fig, axes = plt.subplots(
        1, len(sources), figsize=(3.8 * len(sources), 3.6), dpi=150, sharey=True
    )
    for ax, source in zip(axes, sources, strict=True):
        _style_axis(ax)
        reads = source_reads[source]
        shares = sorted(reads)
        ax.axhline(REGISTER, color=_MUTED, linewidth=1, linestyle="--")
        ax.plot(
            shares,
            [reads[s].tolerance_rate for s in shares],
            color=GATE_COLORS["tolerance"], linewidth=2, marker="o", markersize=4,
            label="tolerance register",
        )
        ax.plot(
            shares,
            [reads[s].coverage_rate for s in shares],
            color=GATE_COLORS["coverage"], linewidth=2, marker="o", markersize=4,
            label="coverage register",
        )
        ax.set_title(names.get(source, str(source)), fontsize=9)
        ax.set_xlabel("marked share", fontsize=8)
    axes[0].set_ylabel("draws satisfying the gate", fontsize=8)
    axes[0].legend(fontsize=7, frameon=False)
    fig.suptitle(
        f"The certified gates under contamination (dashed rule: the {REGISTER:.0%} register)",
        fontsize=10,
    )
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)


def plot_drift_by_band(
    rows: list[dict[str, object]],
    names: dict[int, str],
    out: Path,
) -> None:
    """p90 across cells of the cell-mean error vs share, per band, per source."""
    pools: dict[tuple[ShareBand, int, float], list[float]] = defaultdict(list)
    for row in rows:
        key = (
            ShareBand(str(row["band"])),
            int(row["source_app_id"]),  # type: ignore[arg-type]
            float(row["share"]),  # type: ignore[arg-type]
        )
        pools[key].append(float(row["mean_error"]))  # type: ignore[arg-type]

    sources = sorted({source for _, source, _ in pools})
    fig, axes = plt.subplots(1, len(BAND_ORDER), figsize=(11.4, 3.6), dpi=150)
    for ax, band in zip(axes, BAND_ORDER, strict=True):
        _style_axis(ax)
        rule = BAND_TOLERANCE_RULES.get(band)
        if rule is not None:
            ax.axhline(rule, color=_MUTED, linewidth=1, linestyle="--")
        for color, source in zip(SOURCE_COLORS, sources, strict=False):
            shares = sorted(
                {share for b, s, share in pools if b is band and s == source}
            )
            if not shares:
                continue
            p90s = []
            for share in shares:
                errors = sorted(pools[(band, source, share)])
                p90s.append(errors[min(len(errors) - 1, int(0.9 * len(errors)))])
            ax.plot(
                shares, p90s, color=color, linewidth=2, marker="o", markersize=4,
                label=names.get(source, str(source)),
            )
        ax.set_title(f"{band.value} band", fontsize=9)
        ax.set_xlabel("marked share", fontsize=8)
    axes[0].set_ylabel("p90 of cell-mean share error", fontsize=8)
    axes[0].legend(fontsize=7, frameon=False)
    fig.suptitle(
        "Displayed-share drift by band (dashed rules: the calm-regime tolerances)",
        fontsize=10,
    )
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    """Load the run, print the verdicts, write the JSON and the figures."""
    parser = argparse.ArgumentParser(
        description="Extract the marked-share floor from an m2mix run of record."
    )
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()

    manifest = json.loads((args.run_dir / "manifest.json").read_text(encoding="utf-8"))
    names = {
        int(app_id): str(meta["name"])
        for app_id, meta in manifest.get("marked_sources", {}).items()
    }
    raw = load_rows(args.run_dir)
    rows = gate_rows(raw)
    source_reads = reads_by_source(rows)

    print(
        f"run {manifest['run_id']} · {manifest['cells']:,} cells · "
        f"{len(raw):,} rows · register {REGISTER:.0%}"
    )
    floors = print_verdicts(source_reads, names)
    print_band_diagnosis(rows)

    quotable = [f.floor for f in floors.values()]
    overall = None if any(f is None for f in quotable) else min(q for q in quotable)
    overall_censored = overall is not None and all(
        f.censored for f in floors.values() if f.floor == overall
    )
    print(
        "\noverall floor (worst source): "
        + (
            "NOT QUOTABLE — a baseline failed"
            if overall is None
            else f"{'>= ' if overall_censored else ''}{overall:.2f}"
        )
    )

    verdict = {
        "run_id": manifest["run_id"],
        "config_hash": manifest["config_hash"],
        "register": REGISTER,
        "overall_floor": overall,
        "overall_censored": overall_censored,
        "sources": {
            str(source): {
                "name": names.get(source, str(source)),
                "floor": result.floor,
                "censored": result.censored,
                "verdicts": [[share, passed] for share, passed in result.verdicts],
                "reads": {
                    f"{share:.2f}": {
                        "tolerance_rate": read.tolerance_rate,
                        "coverage_rate": read.coverage_rate,
                        "tolerance_draws": read.tolerance_draws,
                        "coverage_draws": read.coverage_draws,
                    }
                    for share, read in sorted(source_reads[source].items())
                },
            }
            for source, result in floors.items()
        },
    }
    verdict_path = args.run_dir / "floor_verdict.json"
    verdict_path.write_text(
        json.dumps(verdict, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    figures_dir = args.run_dir / "figures"
    figures_dir.mkdir(exist_ok=True)
    plot_register_curves(source_reads, names, figures_dir / "mix_register_curves.png")
    plot_drift_by_band(raw, names, figures_dir / "mix_drift_by_band.png")
    print(f"verdict: {verdict_path}")
    print(f"figures: {figures_dir}")


if __name__ == "__main__":
    main()
