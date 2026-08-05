"""Mint the M2 report's two human-eval figures from their stored artifacts.

The other M2 figures render inside their analyzers' run directories; the two
human-eval charts have no run dir of their own — the holdout mirror
(``eval/holdout/agreement.json``) and the journaled certify rows are the
artifacts — so this script is their committed mint, keeping the report rule
that every figure regenerates from a recorded source.

Outputs (``report/figures/m2/``):
- ``holdout_gradient.png`` — the three-stratum agreement gradient with Wilson
  bars, the limitations story in one chart.
- ``buytime_certificates.png`` — the three-point buy-time certificate series
  (census, July recomposed, fresh buy), the visual argument that the annotator
  under the fresh labels is the instrument the census certified.

Run from the repo root:  uv run --with matplotlib python scripts/plot_human_eval_figures.py
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "pyproject.toml").is_file())
AGREEMENT_JSON = ROOT / "eval" / "holdout" / "agreement.json"
JOURNAL_DB = ROOT / "data" / "steamlens.sqlite3"
OUT_DIR = ROOT / "report" / "figures" / "m2"

# The certificate series, oldest instrument first. Labels carry the story;
# the run ids are the provenance (journaled certify rows, scorer /2 era).
CERTIFY_SERIES = [
    ("Census\n(2026-07, /2 re-anchor)", "certify-20260728T184100Z-5f3f4652"),
    ("July recomposed\n(gold-recert cell)", "certify-20260725T181938Z-bd6ceca8"),
    ("Fresh buy\n(2026-08-03)", "certify-20260803T120942Z-8b10f7c4"),
]

# The gradient reads in trust order: the stratum gold covered, then the two
# the study newly extended trust into.
STRATA = [("corpus", "Corpus"), ("marked-window", "Marked-window"), ("long-tail", "Long-tail")]

ACCENT = "#2a78d6"
CONTRAST = "#eb6834"
_MUTED = "#767676"
_GRID = "#e3e3e3"


def _style(ax) -> None:
    ax.grid(True, color=_GRID, linewidth=0.6, axis="y")
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(_MUTED)
    ax.tick_params(colors=_MUTED, labelsize=8)


def load_gradient() -> tuple[list[dict], dict]:
    """The per-stratum agreement rows plus the overall row, from the mirror."""
    doc = json.loads(AGREEMENT_JSON.read_text(encoding="utf-8"))
    metrics = {m["metric"]: m for m in doc["metrics"]}
    rows = []
    for key, label in STRATA:
        m = metrics[f"holdout_agreement/{key}"]
        n = int(metrics[f"holdout_n/{key}"]["value"])
        rows.append({"label": f"{label}\n(n={n})", "value": m["value"],
                     "lo": m["ci_low"], "hi": m["ci_high"]})
    return rows, metrics["holdout_agreement"]


def load_certificates() -> list[dict]:
    """The three journaled F1 rows, in series order."""
    con = sqlite3.connect(JOURNAL_DB)
    try:
        rows = []
        for label, run_id in CERTIFY_SERIES:
            got = con.execute(
                "SELECT value, ci_low, ci_high FROM eval_metrics"
                " WHERE run_id = ? AND metric = 'f1'", (run_id,)).fetchone()
            if got is None:
                raise SystemExit(f"journal has no f1 row for {run_id}")
            rows.append({"label": label, "value": got[0], "lo": got[1], "hi": got[2]})
        return rows
    finally:
        con.close()


def plot_gradient(rows: list[dict], overall: dict, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(5.6, 3.6), dpi=150)
    xs = range(len(rows))
    ax.axhline(overall["value"], color=_MUTED, linewidth=1, linestyle="--")
    ax.annotate(f"overall {overall['value']:.3f}",
                xy=(1.5, overall["value"]),
                xytext=(0, 5), textcoords="offset points",
                ha="center", color=_MUTED, fontsize=8)
    ax.bar(xs, [r["value"] for r in rows], width=0.55, color=ACCENT)
    ax.errorbar(xs, [r["value"] for r in rows],
                yerr=[[r["value"] - r["lo"] for r in rows],
                      [r["hi"] - r["value"] for r in rows]],
                fmt="none", ecolor=CONTRAST, elinewidth=2, capsize=4)
    for x, r in zip(xs, rows):
        ax.annotate(f"{r['value']:.3f}", xy=(x, r["lo"]),
                    xytext=(0, -12), textcoords="offset points",
                    ha="center", color="#333333", fontsize=9)
    ax.set_xticks(list(xs), [r["label"] for r in rows])
    ax.set_ylim(0, 1)
    ax.set_ylabel("strict-envelope agreement", color=_MUTED, fontsize=9)
    ax.set_title("Human-holdout agreement by stratum (Wilson 95%)",
                 fontsize=10, color="#333333")
    _style(ax)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def plot_certificates(rows: list[dict], path: Path) -> None:
    fig, ax = plt.subplots(figsize=(5.6, 3.6), dpi=150)
    xs = range(len(rows))
    ax.errorbar(xs, [r["value"] for r in rows],
                yerr=[[r["value"] - r["lo"] for r in rows],
                      [r["hi"] - r["value"] for r in rows]],
                fmt="o", color=ACCENT, ecolor=ACCENT,
                elinewidth=1.4, capsize=4,
                markersize=6, markeredgecolor="white", markeredgewidth=0.5)
    for x, r in zip(xs, rows):
        ax.annotate(f"{r['value']:.3f}", xy=(x, r["value"]),
                    xytext=(8, 6), textcoords="offset points",
                    color="#333333", fontsize=9)
    ax.set_xticks(list(xs), [r["label"] for r in rows])
    ax.set_xlim(-0.4, len(rows) - 0.6)
    ax.set_ylim(0.60, 0.90)
    ax.set_ylabel("F1 vs gold (bootstrap 95%)", color=_MUTED, fontsize=9)
    ax.set_title("One instrument, three buy times", fontsize=10, color="#333333")
    _style(ax)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows, overall = load_gradient()
    plot_gradient(rows, overall, OUT_DIR / "holdout_gradient.png")
    certs = load_certificates()
    plot_certificates(certs, OUT_DIR / "buytime_certificates.png")
    for name in ("holdout_gradient.png", "buytime_certificates.png"):
        print(f"minted {OUT_DIR / name}")


if __name__ == "__main__":
    main()
