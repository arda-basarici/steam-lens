"""The closing-test verdict — registers and figures over an m2close run of record.

Reads one ``m2close`` run directory (``measurements.jsonl`` + ``manifest.json``)
and renders the step-10 deliverable in three views:

- **The verdict tables** — per held-out game, both sides of the size rule:
  the take-all exactness re-verification, and (where the game sampled) the
  cell-weighted register reads against the certified 95% register, with the
  full-anchor slice quoted separately — the report's headline unit, "a fresh
  game queried today".
- **The band diagnosis** — the sampled cells' reads sliced by display band,
  pooled across games. Diagnosis only; the verdict never gates per band,
  mirroring the certification's pooled reading.
- **The figures** — ``figures/closing_register_by_anchor.png`` (both gates
  vs anchor quantile against the 95% rule — the held-out promise across
  simulated query moments) and ``figures/closing_error_vs_reference.png``
  (each sampled cell's error vs its reference share, coverage as the mark's
  identity, band boundaries and the calm-regime tolerances ruled in).

The verdict also lands as ``closing_verdict.json`` beside the manifest,
regenerable by re-running this script. Figures are regenerable views, never
precious.

Run from the repo root:
  uv run --with matplotlib python scripts/analyze_closing_test.py data/runs/<m2close-run-id>
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from steamlens.studies.allowance import ShareBand  # noqa: E402
from steamlens.studies.closing import (  # noqa: E402
    REGISTER,
    ClosingRow,
    GameVerdict,
    SampledRead,
    band_reads,
    game_verdicts,
    sampled_read,
)

# The dataviz reference palette's fixed categorical order — the two-state
# coverage identity takes the first two hues, same pair the mix figures use.
COVERED_COLOR = "#2a78d6"
UNCOVERED_COLOR = "#eb6834"
GATE_COLORS = {"tolerance": "#2a78d6", "coverage": "#eb6834"}
_MUTED = "#767676"
_GRID = "#e3e3e3"
BAND_ORDER = (ShareBand.TAIL, ShareBand.MID, ShareBand.HEADLINE)
# The calm-regime ruled tolerances, drawn as reference rules on the scatter;
# interval-governed bands draw none.
BAND_TOLERANCE_RULES = {ShareBand.TAIL: 0.010, ShareBand.MID: 0.025}
# The display bands' share boundaries (allowance.py's ruled edges).
BAND_EDGES = (0.05, 0.15)
FULL_ANCHOR = 1.0


def load_rows(run_dir: Path) -> list[dict[str, object]]:
    """Every measurement row of the run — one dict per (cell, aspect)."""
    path = run_dir / "measurements.jsonl"
    with path.open(encoding="utf-8") as lines:
        return [json.loads(line) for line in lines if line.strip()]


def closing_rows(rows: list[dict[str, object]]) -> list[ClosingRow]:
    """The rows' verdict slices, typed out of the raw JSON."""
    out: list[ClosingRow] = []
    for row in rows:
        within = row["within_tolerance"]
        covered = row["shipped_covered"]
        out.append(
            ClosingRow(
                app_id=int(row["app_id"]),  # type: ignore[arg-type]
                anchor_quantile=float(row["anchor_quantile"]),  # type: ignore[arg-type]
                take_all=bool(row["take_all"]),
                band=ShareBand(str(row["band"])),
                error=float(row["error"]),  # type: ignore[arg-type]
                within_tolerance=None if within is None else bool(within),
                shipped_covered=None if covered is None else bool(covered),
            )
        )
    return out


def _rate(value: float | None) -> str:
    return "     —" if value is None else f"{value:.4f}"


def _read_line(label: str, read: SampledRead) -> str:
    return (
        f"  {label:<14} tol {_rate(read.tolerance_rate)} ({read.tolerance_cells} cells) · "
        f"cov {read.coverage_rate:.4f} ({read.coverage_cells} cells) · "
        f"{'pass' if read.passes() else 'FAIL'}"
    )


def print_verdicts(
    rows: list[ClosingRow],
    verdicts: dict[int, GameVerdict],
    names: dict[int, str],
) -> None:
    """The per-game verdict tables — both sides of the size rule, then the headline."""
    for app_id in sorted(verdicts):
        verdict = verdicts[app_id]
        print(f"\n== {names.get(app_id, str(app_id))} (app {app_id}) ==")
        take_all_total = sum(1 for r in rows if r.app_id == app_id and r.take_all)
        if take_all_total:
            print(
                f"  take-all side: {verdict.take_all_cells_exact}/{take_all_total} "
                f"rows exact · {'pass' if verdict.exact else 'FAIL'}"
            )
        if verdict.sampled is not None:
            print(_read_line("sampled cells:", verdict.sampled))
            full = [
                r
                for r in rows
                if r.app_id == app_id and not r.take_all and r.anchor_quantile == FULL_ANCHOR
            ]
            if full:
                print(_read_line("full anchor:", sampled_read(full)))
        print(f"  verdict: {'pass' if verdict.passes() else 'FAIL'}")


def print_band_diagnosis(rows: list[ClosingRow]) -> None:
    """Where the misses live: sampled reads per band. Never a gate."""
    reads = band_reads(rows)
    if not reads:
        return
    print("\n== band diagnosis (sampled cells, pooled across games; never a gate) ==")
    for band in BAND_ORDER:
        if band in reads:
            print(_read_line(f"{band.value}:", reads[band]))


def _style_axis(ax: plt.Axes) -> None:
    """Recessive grid and spines; the data carries the figure."""
    ax.grid(True, color=_GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(_MUTED)
    ax.tick_params(colors=_MUTED, labelsize=8)


def plot_register_by_anchor(
    rows: list[ClosingRow], names: dict[int, str], out: Path
) -> None:
    """Both gates vs anchor quantile, per sampled game, against the 95% rule."""
    sampled_games = sorted({r.app_id for r in rows if not r.take_all})
    fig, axes = plt.subplots(
        1, len(sampled_games), figsize=(4.2 * len(sampled_games), 3.6),
        dpi=150, sharey=True, squeeze=False,
    )
    for ax, app_id in zip(axes[0], sampled_games, strict=True):
        _style_axis(ax)
        quantiles = sorted(
            {r.anchor_quantile for r in rows if r.app_id == app_id and not r.take_all}
        )
        reads = {
            q: sampled_read(
                r for r in rows
                if r.app_id == app_id and not r.take_all and r.anchor_quantile == q
            )
            for q in quantiles
        }
        ax.axhline(REGISTER, color=_MUTED, linewidth=1, linestyle="--")
        ax.plot(
            quantiles,
            [reads[q].tolerance_rate for q in quantiles],
            color=GATE_COLORS["tolerance"], linewidth=2, marker="o", markersize=4,
            label="tolerance register",
        )
        ax.plot(
            quantiles,
            [reads[q].coverage_rate for q in quantiles],
            color=GATE_COLORS["coverage"], linewidth=2, marker="o", markersize=4,
            label="coverage register",
        )
        ax.set_title(names.get(app_id, str(app_id)), fontsize=9)
        ax.set_xlabel("anchor quantile (of the game's own review-time span)", fontsize=8)
    axes[0][0].set_ylabel("cells satisfying the gate", fontsize=8)
    axes[0][0].legend(fontsize=7, frameon=False)
    fig.suptitle(
        f"The certified gates held out (dashed rule: the {REGISTER:.0%} register)",
        fontsize=10,
    )
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)


def plot_error_vs_reference(
    raw: list[dict[str, object]], names: dict[int, str], out: Path
) -> None:
    """Each sampled cell's error vs its reference share; coverage is the identity."""
    sampled = [r for r in raw if not r["take_all"]]
    games = sorted({int(r["app_id"]) for r in sampled})  # type: ignore[arg-type]
    fig, axes = plt.subplots(
        1, len(games), figsize=(5.4 * len(games), 3.8), dpi=150, squeeze=False
    )
    for ax, app_id in zip(axes[0], games, strict=True):
        _style_axis(ax)
        mine = [r for r in sampled if int(r["app_id"]) == app_id]  # type: ignore[arg-type]
        for covered, color, label in (
            (True, COVERED_COLOR, "covered by the shipped interval"),
            (False, UNCOVERED_COLOR, "uncovered"),
        ):
            points = [r for r in mine if bool(r["shipped_covered"]) is covered]
            ax.scatter(
                [float(r["reference_share"]) for r in points],  # type: ignore[arg-type]
                [float(r["error"]) for r in points],  # type: ignore[arg-type]
                s=22, color=color, label=label,
                edgecolors="white", linewidths=0.5,
            )
        for edge in BAND_EDGES:
            ax.axvline(edge, color=_GRID, linewidth=1)
        for band, rule in BAND_TOLERANCE_RULES.items():
            lo = 0.0 if band is ShareBand.TAIL else BAND_EDGES[0]
            hi = BAND_EDGES[0] if band is ShareBand.TAIL else BAND_EDGES[1]
            ax.plot([lo, hi], [rule, rule], color=_MUTED, linewidth=1, linestyle="--")
        ax.set_title(names.get(app_id, str(app_id)), fontsize=9)
        ax.set_xlabel("census reference share (band edges at 5% / 15%)", fontsize=8)
    axes[0][0].set_ylabel("share error", fontsize=8)
    axes[0][0].legend(fontsize=7, frameon=False)
    fig.suptitle(
        "Sampled cells held out (dashed rules: the calm-regime tolerances)",
        fontsize=10,
    )
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    """Load the run, print the verdicts, write the JSON and the figures."""
    parser = argparse.ArgumentParser(
        description="Extract the closing-test verdict from an m2close run of record."
    )
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()

    manifest = json.loads((args.run_dir / "manifest.json").read_text(encoding="utf-8"))
    names = {
        int(app_id): str(meta["name"])
        for app_id, meta in manifest.get("games", {}).items()
    }
    raw = load_rows(args.run_dir)
    rows = closing_rows(raw)
    verdicts = game_verdicts(rows)

    print(
        f"run {manifest['run_id']} · {manifest['cells']:,} cells · "
        f"{len(raw):,} rows · register {REGISTER:.0%}"
    )
    print_verdicts(rows, verdicts, names)
    print_band_diagnosis(rows)

    overall = all(v.passes() for v in verdicts.values())
    print(f"\noverall: {'PASS — the size rule holds held-out' if overall else 'FAIL'}")

    def _read_json(read: SampledRead | None) -> dict[str, object] | None:
        if read is None:
            return None
        return {
            "tolerance_rate": read.tolerance_rate,
            "coverage_rate": read.coverage_rate,
            "tolerance_cells": read.tolerance_cells,
            "coverage_cells": read.coverage_cells,
            "passes": read.passes(),
        }

    verdict = {
        "run_id": manifest["run_id"],
        "config_hash": manifest["config_hash"],
        "register": REGISTER,
        "overall_pass": overall,
        "games": {
            str(app_id): {
                "name": names.get(app_id, str(app_id)),
                "take_all_cells_exact": v.take_all_cells_exact,
                "exact": v.exact,
                "sampled": _read_json(v.sampled),
                "full_anchor": _read_json(
                    sampled_read(full)
                    if (full := [
                        r for r in rows
                        if r.app_id == app_id
                        and not r.take_all
                        and r.anchor_quantile == FULL_ANCHOR
                    ])
                    else None
                ),
                "passes": v.passes(),
            }
            for app_id, v in sorted(verdicts.items())
        },
        "bands": {
            band.value: _read_json(read)
            for band, read in sorted(band_reads(rows).items(), key=lambda kv: kv[0].value)
        },
    }
    verdict_path = args.run_dir / "closing_verdict.json"
    verdict_path.write_text(
        json.dumps(verdict, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    figures_dir = args.run_dir / "figures"
    figures_dir.mkdir(exist_ok=True)
    plot_register_by_anchor(rows, names, figures_dir / "closing_register_by_anchor.png")
    plot_error_vs_reference(raw, names, figures_dir / "closing_error_vs_reference.png")
    print(f"verdict: {verdict_path}")
    print(f"figures: {figures_dir}")


if __name__ == "__main__":
    main()
