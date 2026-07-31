"""Dark-theme chart variants for the portfolio site.

Same data path as the report's figures (``generate_report.parse_bakeoff`` and its
pinned ``DATA``, both artifact-verified), re-rendered on the site's dark palette
(paper #14161b · ink #e9e6df · muted #9a968c · hair #2b2f38 · amber #e0a458).
The report's light versions are untouched; these land in ``report/figures/site/``.

Run from the repo root:
  uv run --with reportlab --with matplotlib --with pyphen python report/site_figures.py
(reportlab/pyphen only because importing the generator builds its styles.)
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

# The Agg backend must be selected before pyplot binds one, so this import trails it.
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

# report/ is a script directory, not a package, so the generator is reachable only
# once its own directory is on the path.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_report import DATA, parse_bakeoff, verify_data  # noqa: E402

OUT = Path(__file__).resolve().parent / "figures" / "site"
OUT.mkdir(parents=True, exist_ok=True)

PAPER, INK, MUTED, GRID, AMBER = "#14161b", "#e9e6df", "#9a968c", "#2b2f38", "#e0a458"

plt.rcParams.update({"font.family": "sans-serif", "font.size": 10})


def _dark_axes(ax) -> None:
    ax.set_facecolor(PAPER)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(MUTED)
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.yaxis.grid(False)


def bakeoff_dark() -> None:
    best: dict[str, dict] = {}
    for r in parse_bakeoff():
        if r["dq"]:
            continue
        if r["name"] not in best or r["f1"] > best[r["name"]]["f1"]:
            best[r["name"]] = r
    rows = sorted(best.values(), key=lambda r: r["f1"])
    fig, ax = plt.subplots(figsize=(8.4, 0.42 * len(rows) + 1.0), dpi=200)
    fig.patch.set_facecolor(PAPER)
    for i, r in enumerate(rows):
        chosen = r["name"] == "deepseek-v4-flash"
        color = AMBER if chosen else INK
        ax.hlines(i, r["lo"], r["hi"], color=color, linewidth=1.6, alpha=0.9)
        ax.plot(r["f1"], i, "o", color=color, markersize=7 if chosen else 5.5)
        if chosen:
            ax.annotate(f"chosen · batch {r['n']} · {r['f1']:.3f}", (r["hi"], i),
                        xytext=(6, -3), textcoords="offset points", fontsize=9,
                        color=AMBER, fontweight="bold")
        elif i == len(rows) - 1:
            ax.annotate(f"frontier · batch {r['n']} · {r['f1']:.3f}", (r["hi"], i),
                        xytext=(6, -3), textcoords="offset points", fontsize=9, color=MUTED)
    ax.set_yticks(range(len(rows)), [r["name"] for r in rows])
    ax.tick_params(axis="y", colors=INK)
    _dark_axes(ax)
    ax.set_xlabel("F1 vs gold (95% bootstrap CI)", color=MUTED, fontsize=9)
    fig.tight_layout()
    fig.savefig(OUT / "bakeoff.png", bbox_inches="tight", facecolor=PAPER)
    plt.close(fig)


def bracketing_dark() -> None:
    series = [
        ("production vs gold", DATA["certify_f1"], DATA["certify_ci"], INK),
        ("judge vs production (census sample)", DATA["agree_f1"], DATA["agree_ci"], AMBER),
        ("judge vs gold", DATA["judge_f1"], DATA["judge_ci"], INK),
    ]
    fig, ax = plt.subplots(figsize=(8.4, 2.2), dpi=200)
    fig.patch.set_facecolor(PAPER)
    for i, (_label, value, (lo, hi), color) in enumerate(series):
        ax.hlines(i, lo, hi, color=color, linewidth=1.6, alpha=0.9)
        ax.plot(value, i, "o", color=color, markersize=7)
        ax.annotate(f"{value:.3f}", (value, i), xytext=(0, 7),
                    textcoords="offset points", ha="center", fontsize=9,
                    color=color, fontweight="bold")
    ax.set_yticks(range(len(series)), [s[0] for s in series])
    ax.tick_params(axis="y", colors=INK)
    ax.set_ylim(-0.6, len(series) - 0.4)
    _dark_axes(ax)
    ax.set_xlabel("F1 (95% bootstrap CI)", color=MUTED, fontsize=9)
    fig.tight_layout()
    fig.savefig(OUT / "bracketing.png", bbox_inches="tight", facecolor=PAPER)
    plt.close(fig)


if __name__ == "__main__":
    verify_data()
    bakeoff_dark()
    bracketing_dark()
    print(f"dark site charts rendered into {OUT}")
