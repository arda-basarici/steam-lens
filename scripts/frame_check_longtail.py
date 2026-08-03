"""The long-tail stage-2 frame checks — fresh histograms against the corpus frame.

Stage 2 of the long-tail evidence (DESIGN, the study-design section), sharpened
by the stage-1 ruling: the load-bearing question is the off-corpus regime
distribution — do genuinely long-tail games land in the spiky allowance regime
(peak window share at or above the ruled 2/3)? — alongside the original
in-range check on temporal structure and pool size. Everything reads from a
discovery run's persisted snapshots (``scripts/discover_longtail_games.py``)
plus the sweep run of record; no live fetch, no LLM spend.

Two instruments are kept honest side by side. The *native* reading is what
production will compute: peak window share over the live histogram's own
rollup buckets — months for old games, weeks for young ones — because the
windowed compiler plans one window per populated bucket as served. The
*month-rolled* reading re-buckets to calendar months, the corpus instrument
stage 1 minted its spikiness on, so the fresh distribution can sit next to the
corpus one without a unit confound. The instrument-agreement table grounds the
comparison: for a seeded handful of corpus games it puts the corpus-built
monthly histogram against the live one restricted to the same month range —
residual disagreement there is content (all-language claims vs the fetched
window's reviews), not bucketing.

A span caveat rides every corpus comparison, disclosed in the output: the
corpus is a recent-window fetch, so its units' shapes live on windowed pools,
while a fresh game's histogram covers its whole life — the comparison asks
whether production readings fall inside the range the calibration has support
on, not that the two populations match.

Figures land in the discovery run's own ``figures/``. Run from the repo root:
  uv run --with matplotlib python scripts/frame_check_longtail.py data/longtail/<run-id>
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final, cast

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from steamlens.contracts import HistogramBucket, HistogramSnapshot  # noqa: E402
from steamlens.corpus import read_reviews_file  # noqa: E402
from steamlens.steam_client import parse_histogram  # noqa: E402
from steamlens.studies.allowance import is_spiky_regime  # noqa: E402
from steamlens.studies.frame import (  # noqa: E402
    ListBand,
    histogram_anchor_grid,
    month_rolled,
    truncate_rollups,
)
from steamlens.studies.sample_corpus import corpus_histogram  # noqa: E402
from steamlens.studies.shape import peak_window_share  # noqa: E402
from steamlens.studies.sweep_corpus import ANCHOR_QUANTILES, truncate_pool  # noqa: E402

BAND_ORDER: Final = (ListBand.TRUE_TAIL, ListBand.ENGAGING, ListBand.BRIDGE)

# The dataviz reference palette's blue ordinal ramp (steps 250/450/650,
# validated): list bands are ordered small→large, so one hue, light→dark;
# the corpus reference wears muted ink, never a band color.
BAND_COLORS: Final = {
    ListBand.TRUE_TAIL: "#86b6ef",
    ListBand.ENGAGING: "#2a78d6",
    ListBand.BRIDGE: "#104281",
}
_INK = "#333333"
_MUTED = "#767676"
_GRID = "#e3e3e3"


@dataclass(frozen=True, slots=True)
class FreshUnit:
    """One fresh (game, anchor) reading — both instruments, production grain."""

    app_id: int
    band: ListBand
    quantile: float
    pool_size: int
    native_peak: float
    month_peak: float


@dataclass(frozen=True, slots=True)
class FreshGame:
    """One admitted game's whole-histogram reading plus its anchor units."""

    app_id: int
    name: str
    band: ListBand
    rollup_unit: str
    total_reviews: int
    english_total: int | None
    native_peak: float
    month_peak: float
    units: tuple[FreshUnit, ...]


def load_snapshot(path: Path) -> HistogramSnapshot:
    """One persisted raw histogram snapshot, re-parsed at the boundary."""
    record = _object(json.loads(path.read_text(encoding="utf-8")), str(path))
    app_id = record.get("app_id")
    fetched_at = record.get("fetched_at")
    assert isinstance(app_id, int) and isinstance(fetched_at, str)
    return parse_histogram(
        _object(record.get("payload"), f"{path} payload"),
        app_id,
        datetime.fromisoformat(fetched_at),
    )


def load_fresh_games(run_dir: Path) -> list[FreshGame]:
    """Every admitted game with its snapshots measured on both instruments."""
    admitted = json.loads((run_dir / "admitted.json").read_text(encoding="utf-8"))
    games: list[FreshGame] = []
    for raw in cast("list[object]", admitted):
        entry = _object(raw, "admitted entry")
        app_id, band = entry.get("app_id"), entry.get("band")
        name, total = entry.get("store_name"), entry.get("total_reviews")
        english = entry.get("english_total_reviews")
        assert isinstance(app_id, int) and isinstance(band, str)
        assert isinstance(name, str) and isinstance(total, int)
        histogram = load_snapshot(run_dir / "histograms" / f"{app_id}.json")
        games.append(_measure_game(
            histogram, ListBand(band), name, total,
            english if isinstance(english, int) else None,
        ))
    return games


def _measure_game(
    histogram: HistogramSnapshot,
    band: ListBand,
    name: str,
    total: int,
    english_total: int | None,
) -> FreshGame:
    units: list[FreshUnit] = []
    for anchor in histogram_anchor_grid(histogram, ANCHOR_QUANTILES).anchors:
        truncated = truncate_rollups(histogram, anchor.cutoff)
        units.append(FreshUnit(
            app_id=histogram.app_id,
            band=band,
            quantile=anchor.quantile,
            pool_size=anchor.pool_size,
            native_peak=peak_window_share(truncated),
            month_peak=peak_window_share(month_rolled(truncated)),
        ))
    return FreshGame(
        app_id=histogram.app_id,
        name=name,
        band=band,
        rollup_unit=histogram.rollup_unit.value,
        total_reviews=total,
        english_total=english_total,
        native_peak=peak_window_share(histogram),
        month_peak=peak_window_share(month_rolled(histogram)),
        units=tuple(units),
    )


def corpus_unit_peaks(sweep_run: Path, corpus_dir: Path) -> list[tuple[int, float, float]]:
    """(app_id, pool, monthly peak share) per corpus (game, anchor) unit.

    Rebuilt the stage-1 way — truncate at the manifest's recorded cutoff, roll
    into the monthly histogram — so the corpus side of every comparison is the
    identical instrument stage 1 ruled on.
    """
    manifest = _object(
        json.loads((sweep_run / "manifest.json").read_text(encoding="utf-8")),
        "sweep manifest",
    )
    games = _object(manifest.get("games"), "sweep manifest games")
    units: list[tuple[int, float, float]] = []
    for app_id, raw_meta in games.items():
        meta = _object(raw_meta, f"game {app_id}")
        reviews = read_reviews_file(corpus_dir / f"{app_id}_reviews.jsonl").reviews
        anchors = meta.get("anchors")
        assert isinstance(anchors, list)
        for raw_anchor in cast("list[object]", anchors):
            anchor = _object(raw_anchor, "anchor")
            cutoff, pool = anchor.get("cutoff"), anchor.get("pool")
            assert isinstance(cutoff, str) and isinstance(pool, (int, float))
            peak = peak_window_share(corpus_histogram(
                truncate_pool(reviews, datetime.fromisoformat(cutoff))
            ))
            units.append((int(app_id), float(pool), peak))
    return units


def instrument_rows(
    run_dir: Path, corpus_dir: Path
) -> list[tuple[int, float, float, float, float, str]]:
    """Per checked corpus game: the two instruments over comparable spans.

    (app_id, corpus-built peak, live peak restricted to the corpus month
    range, live full-life month peak, live native peak, native unit). The
    restricted column is the like-for-like read; the full-life columns show
    the span effect production will actually see.
    """
    rows: list[tuple[int, float, float, float, float, str]] = []
    for path in sorted((run_dir / "histograms_corpus").glob("*.json")):
        live = load_snapshot(path)
        reviews = read_reviews_file(corpus_dir / f"{live.app_id}_reviews.jsonl").reviews
        built = corpus_histogram(reviews)
        built_months = [b.start for b in built.rollups if _claims_of(b) > 0]
        rolled = month_rolled(live)
        lo, hi = min(built_months), max(built_months)
        restricted = tuple(b for b in rolled.rollups if lo <= b.start <= hi)
        rows.append((
            live.app_id,
            peak_window_share(built),
            _peak_of_buckets(restricted),
            peak_window_share(rolled),
            peak_window_share(live),
            live.rollup_unit.value,
        ))
    return rows


def _peak_of_buckets(buckets: tuple[HistogramBucket, ...]) -> float:
    claims = [_claims_of(b) for b in buckets]
    total = sum(claims)
    return max(claims) / total if total else float("nan")


def _claims_of(bucket: HistogramBucket) -> int:
    return bucket.recommendations_up + bucket.recommendations_down


def _object(value: object, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise SystemExit(f"{context}: expected a JSON object, got {type(value).__name__}")
    return cast("Mapping[str, object]", value)


def print_game_table(games: list[FreshGame]) -> None:
    """The per-game readings — the run's roster, one line each."""
    print("\n=== fresh games — production-instrument readings ===")
    print(f"{'app':>9}  {'band':<10}{'unit':<6}{'total':>8}{'en':>7}"
          f"{'peak(native)':>13}{'peak(month)':>12}  {'regime':<6} name")
    for game in sorted(games, key=lambda g: (g.band.value, g.total_reviews)):
        regime = "SPIKY" if is_spiky_regime(game.native_peak) else "calm"
        english = "-" if game.english_total is None else f"{game.english_total:,}"
        print(f"{game.app_id:>9}  {game.band.value:<10}{game.rollup_unit:<6}"
              f"{game.total_reviews:>8,}{english:>7}{game.native_peak:>13.3f}"
              f"{game.month_peak:>12.3f}  {regime:<6} {game.name[:38]}")


def print_regime_table(games: list[FreshGame], corpus_peaks: list[float]) -> None:
    """The load-bearing table: spiky fractions, fresh bands vs the corpus."""
    print("\n=== regime distribution (spiky = peak window share >= 2/3) ===")
    print(f"{'group':<12}{'games':>6}{'spiky':>7}{'units':>7}{'spiky':>7}{'unit spiky %':>14}")
    for band in BAND_ORDER:
        members = [g for g in games if g.band is band]
        if not members:
            print(f"{band.value:<12}{0:>6}{'-':>7}{'-':>7}{'-':>7}{'-':>14}")
            continue
        units = [u for g in members for u in g.units]
        spiky_games = sum(1 for g in members if is_spiky_regime(g.native_peak))
        spiky_units = sum(1 for u in units if is_spiky_regime(u.native_peak))
        print(f"{band.value:<12}{len(members):>6}{spiky_games:>7}{len(units):>7}"
              f"{spiky_units:>7}{spiky_units / len(units):>13.1%}")
    all_units = [u for g in games for u in g.units]
    spiky_all = sum(1 for u in all_units if is_spiky_regime(u.native_peak))
    spiky_corpus = sum(1 for p in corpus_peaks if is_spiky_regime(p))
    print(f"{'fresh all':<12}{len(games):>6}"
          f"{sum(1 for g in games if is_spiky_regime(g.native_peak)):>7}"
          f"{len(all_units):>7}{spiky_all:>7}{spiky_all / len(all_units):>13.1%}")
    print(f"{'corpus':<12}{'-':>6}{'-':>7}{len(corpus_peaks):>7}{spiky_corpus:>7}"
          f"{spiky_corpus / len(corpus_peaks):>13.1%}")
    print("(fresh regime on the native instrument — what production computes; "
          "corpus on its monthly instrument, windowed-pool span)")


def print_range_table(
    games: list[FreshGame], corpus_units: list[tuple[int, float, float]]
) -> None:
    """The in-range check: where fresh readings sit against corpus support."""
    fresh_month = sorted(u.month_peak for g in games for u in g.units)
    fresh_native = sorted(u.native_peak for g in games for u in g.units)
    corpus_peaks = sorted(peak for _, _, peak in corpus_units)
    corpus_pools = sorted(pool for _, pool, _ in corpus_units)
    fresh_pools = sorted(float(u.pool_size) for g in games for u in g.units)

    def spread(values: list[float]) -> str:
        mid = values[len(values) // 2]
        return (f"min {values[0]:.3f} · p50 {mid:.3f} · max {values[-1]:.3f}")

    print("\n=== in-range check — peak window share ===")
    print(f"{'corpus (monthly)':<22}{spread(corpus_peaks)}")
    print(f"{'fresh (month-rolled)':<22}{spread(fresh_month)}")
    print(f"{'fresh (native)':<22}{spread(fresh_native)}")
    print("\n=== in-range check — anchor pool sizes ===")
    print(f"{'corpus':<22}min {corpus_pools[0]:,.0f} · p50 "
          f"{corpus_pools[len(corpus_pools) // 2]:,.0f} · max {corpus_pools[-1]:,.0f}")
    print(f"{'fresh':<22}min {fresh_pools[0]:,.0f} · p50 "
          f"{fresh_pools[len(fresh_pools) // 2]:,.0f} · max {fresh_pools[-1]:,.0f}")


def print_instrument_table(rows: list[tuple[int, float, float, float, float, str]]) -> None:
    """Instrument agreement over the seeded corpus handful."""
    print("\n=== instrument agreement — corpus-built vs live histogram ===")
    print(f"{'app':>9}{'corpus-built':>14}{'live(window)':>14}"
          f"{'live(full,mo)':>15}{'live(native)':>14}{'unit':>7}")
    for app_id, built, windowed, full_month, native, unit in rows:
        print(f"{app_id:>9}{built:>14.3f}{windowed:>14.3f}"
              f"{full_month:>15.3f}{native:>14.3f}{unit:>7}")
    print("(live(window) = live month buckets restricted to the corpus month "
          "range — the like-for-like read; residual gaps are content, not bucketing)")


def _style_axis(ax: plt.Axes) -> None:
    """Recessive grid and spines; the data carries the figure."""
    ax.grid(True, color=_GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(_MUTED)
    ax.tick_params(colors=_MUTED, labelsize=8)


def plot_ecdf(
    games: list[FreshGame],
    corpus_units: list[tuple[int, float, float]],
    out: Path,
) -> None:
    """ECDFs of peak window share — fresh bands (both instruments) vs corpus."""
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8), dpi=150, sharey=True)
    instruments = (("month-rolled (corpus instrument)", lambda u: u.month_peak),
                   ("native (production instrument)", lambda u: u.native_peak))
    corpus_peaks = sorted(peak for _, _, peak in corpus_units)
    for ax, (title, reader) in zip(axes, instruments, strict=True):
        _style_axis(ax)
        ax.plot(corpus_peaks, _ecdf_y(corpus_peaks), color=_MUTED, linewidth=2,
                linestyle="--", label="corpus units")
        for band in BAND_ORDER:
            values = sorted(reader(u) for g in games if g.band is band for u in g.units)
            if values:
                ax.plot(values, _ecdf_y(values), color=BAND_COLORS[band],
                        linewidth=2, label=band.value)
        ax.axvline(2 / 3, color=_INK, linewidth=1, linestyle=":")
        ax.annotate("spiky ≥ 2/3", xy=(2 / 3, 0.93), fontsize=7, color=_INK,
                    xytext=(3, 0), textcoords="offset points")
        ax.set_title(title, color=_INK, fontsize=10)
        ax.set_xlabel("peak window share", color=_INK, fontsize=9)
        ax.set_xlim(0, 1)
    axes[0].set_ylabel("fraction of units ≤ x", color=_INK, fontsize=9)
    axes[-1].legend(fontsize=8, frameon=False, loc="lower right")
    fig.suptitle("Long-tail frame check: where fresh pools sit against corpus support",
                 color=_INK, fontsize=11)
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)


def _ecdf_y(values: list[float]) -> list[float]:
    return [(i + 1) / len(values) for i in range(len(values))]


def plot_scatter(
    games: list[FreshGame],
    corpus_units: list[tuple[int, float, float]],
    out: Path,
) -> None:
    """Pool size vs native peak share — the two shape axes in one view."""
    fig, ax = plt.subplots(figsize=(7, 4.2), dpi=150)
    _style_axis(ax)
    ax.scatter([pool for _, pool, _ in corpus_units],
               [peak for _, _, peak in corpus_units],
               s=14, color=_GRID, edgecolors=_MUTED, linewidths=0.5,
               label="corpus units")
    for band in BAND_ORDER:
        units = [u for g in games if g.band is band for u in g.units]
        if units:
            ax.scatter([u.pool_size for u in units], [u.native_peak for u in units],
                       s=22, color=BAND_COLORS[band], label=band.value)
    ax.axhline(2 / 3, color=_INK, linewidth=1, linestyle=":")
    ax.set_xscale("log")
    ax.set_xlabel("anchor pool size (log)", color=_INK, fontsize=9)
    ax.set_ylabel("peak window share (native)", color=_INK, fontsize=9)
    ax.set_ylim(0, 1)
    ax.legend(fontsize=8, frameon=False, loc="upper right")
    ax.set_title("Fresh units against the corpus cloud — the 2/3 regime line",
                 color=_INK, fontsize=10)
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    """Load the run, measure both sides, print the verdict tables, render figures."""
    parser = argparse.ArgumentParser(
        description="Frame-check a long-tail discovery run against the sweep run of record."
    )
    parser.add_argument("run_dir", type=Path, help="the longtail discovery run directory")
    parser.add_argument("--sweep-run", type=Path,
                        default=Path("data/runs/m2sweep-20260802T132010Z-2969bcab"))
    parser.add_argument("--corpus", type=Path, default=None,
                        help="corpus reviews dir (default: the sweep manifest's corpus_dir)")
    args = parser.parse_args()

    sweep_manifest = _object(
        json.loads((args.sweep_run / "manifest.json").read_text(encoding="utf-8")),
        "sweep manifest",
    )
    corpus_dir = args.corpus if args.corpus is not None else Path(
        str(sweep_manifest["corpus_dir"])
    )

    games = load_fresh_games(args.run_dir)
    if not games:
        raise SystemExit(f"{args.run_dir}: no admitted games to check")
    corpus_units = corpus_unit_peaks(args.sweep_run, corpus_dir)

    print_game_table(games)
    print_regime_table(games, [peak for _, _, peak in corpus_units])
    print_range_table(games, corpus_units)
    print_instrument_table(instrument_rows(args.run_dir, corpus_dir))
    units_weekly = sum(1 for g in games if g.rollup_unit == "week")
    print(f"\nunit mix: {units_weekly}/{len(games)} fresh games served weekly rollups")
    print("(span caveat: corpus units live on windowed pools; fresh histograms "
          "cover each game's whole life)")

    figures_dir = args.run_dir / "figures"
    figures_dir.mkdir(exist_ok=True)
    plot_ecdf(games, corpus_units, figures_dir / "frame_ecdf.png")
    plot_scatter(games, corpus_units, figures_dir / "frame_scatter.png")
    print(f"\nfigures: {figures_dir}")


if __name__ == "__main__":
    main()
