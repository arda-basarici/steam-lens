"""The closing test — the ruled size rule validated on the held-out long-tail games.

Step 10 of the M2 build (design ruled 2026-08-04): the staged long-tail
evidence's committed final stage. The fresh-buy session bought full labels for
three genuinely long-tail games under the frozen triple; this runner draws them
exactly as production would and reads the certified gates against each game's
own full-pool truth — the finished rule validated off-corpus, not argued by
transfer.

The population is the certified one — own-span query anchors × games ×
displayed aspects — with the verdict reading over all measured cells and the
full-corpus anchor serving as the report's headline unit ("a fresh game
queried today"). There is no repeat dimension: the closing test has no blend
randomness and windowed draws are deterministic, so each cell is exactly one
draw and the 95% register is readable only across the cell population — which
is what the anchor grid supplies.

Both sides of the size rule are under test, so — unlike the sweeps, where a
swallowed pool was free flattery for a convergence curve — take-all anchors
are *recorded*, not skipped: a pool at or under the cutoff is measured whole
and its exactness verified (a take-all draw quotes the exact number and no
interval — the promise on that side is exactness itself). The check guards
construction, not sampling: the sample being the pool, any nonzero error means
the measurement wiring diverged from the reference's. Pools above the cutoff
draw the ruled n time-proportional through the certified compile → execute →
measure seams and read the certified gates per cell — share error against the
regime-aware band tolerance, needed inflation against the shipped allowance.

Truth is each game's own full-pool fold under the frozen triple, read from the
fresh-buy run's own label store, and the run opens with the census-fold wiring
guard at the full anchor (exact id-set equality before anything is measured).
Vocabulary is each game's own pinned index — the mixing sweep's merged
vocabulary was contamination-specific and does not apply here.
"""

from __future__ import annotations

import argparse
import json
import time
import traceback
from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from steamlens.contracts import (
    ClassifierVersions,
    Review,
    SamplingPolicy,
    SamplingPolicyKind,
    Sink,
    StageKind,
)
from steamlens.core.classify import PROMPT_VERSION
from steamlens.core.sampling import compile_plan
from steamlens.corpus import read_reviews_file
from steamlens.dispatch import (
    RunAbort,
    code_version,
    config_hash,
    mint_run_id,
    narrate,
    write_manifest,
)
from steamlens.dispatch.census_arm import MODEL_ID
from steamlens.dispatch.narration import TeeSink
from steamlens.ontology import load_ontology_version
from steamlens.store import Store
from steamlens.studies.aggregate_corpus import mint_census_aggregates
from steamlens.studies.allowance import (
    ShareBand,
    is_spiky_regime,
    needed_inflation,
    primary_band_tolerance,
    primary_shipped_allowance,
    share_band,
)
from steamlens.studies.marked_pool import read_fetch_manifest
from steamlens.studies.measure import AspectMeasurement, measure_draw
from steamlens.studies.sample_corpus import corpus_histogram, execute_plan
from steamlens.studies.shape import peak_window_share
from steamlens.studies.sweep_corpus import (
    AnchorGrid,
    anchor_grid,
    anchored_reference_shares,
    assert_reference_wiring,
    census_shares_by_game,
    load_label_indexes,
    truncate_pool,
)

CLOSING_ROLE: Final = "long-tail"
"""The fetch manifest role this test consumes — the marked-window games in
the same run are the mixing experiment's supply, never measured here."""

RULED_SAMPLE_SIZE: Final = 1000
"""The size rule's sampled-path n (the curves checkpoint, 2026-08-02)."""

TAKE_ALL_CUTOFF: Final = 2000
"""The size rule's take-all boundary (same ruling) — the study's local pin of
the checkpoint value, like the sweeps'."""

ANCHOR_QUANTILES: Final = (0.40, 0.55, 0.70, 0.85, 1.00)
"""The certified population's anchor grid — the sweeps', unchanged."""

_STAGE: Final = "m2.close"


@dataclass(frozen=True, slots=True)
class AspectRead:
    """One aspect's read in one cell — the closing test's persisted atom.

    On a sampled cell the three gate fields carry the certified per-draw
    reads: ``within_tolerance`` is ``None`` exactly when the band carries no
    share tolerance under the cell's regime (headline everywhere, spiky
    mid — interval-governed numbers), ``shipped_covered`` is whether the
    shipped interval (Wilson plus the regime/band allowance) covered the
    truth, and ``wilson_width`` is the quoted Wilson width behind it. On a
    take-all cell all three are ``None``: the quoted number is exact and no
    interval ships, so there is no gate to read — the cell's promise is the
    exactness the runner already verified.
    """

    aspect: str
    band: ShareBand
    reference_share: float
    sample_share: float
    error: float
    within_tolerance: bool | None
    shipped_covered: bool | None
    wilson_width: float | None


@dataclass(frozen=True, slots=True)
class ClosingCellRow:
    """One (game, anchor) cell: the size rule's resolved side plus its reads.

    ``size`` is the drawn sample's actual size — the pool itself on the
    take-all side, the ruled n on the sampled side. ``spiky`` is the anchor
    pool's allowance regime, computed from the same histogram the plan
    compiles from.
    """

    app_id: int
    anchor_quantile: float
    anchor_cutoff: datetime
    pool_size: int
    take_all: bool
    size: int
    spiky: bool
    reads: tuple[AspectRead, ...]


@dataclass(frozen=True, slots=True)
class ClosingConfig:
    """The closing test's dials — parameters so tests exercise the real
    control flow at toy scale; production passes the ruled values."""

    quantiles: tuple[float, ...]
    sample_size: int
    take_all_cutoff: int


@dataclass(frozen=True, slots=True)
class GameClosing:
    """One game's closing output: rows plus the bookkeeping the manifest records."""

    rows: tuple[ClosingCellRow, ...]
    grid: AnchorGrid
    sampled_cells: int
    take_all_cells: int


def sampled_reads(
    measured: Sequence[AspectMeasurement], *, spiky: bool
) -> tuple[AspectRead, ...]:
    """The certified per-draw gate reads over one sampled cell's measurements.

    Per aspect: the band from its reference share, then the two reads the
    checkpoint's register is made of — share error at or under the band
    tolerance (absent where the regime rules none), and needed inflation at
    or under the shipped allowance, the exact centered reading the constants
    were minted from.
    """
    reads: list[AspectRead] = []
    for m in measured:
        band = share_band(m.reference_share)
        tolerance = primary_band_tolerance(band, spiky=spiky)
        allowance = primary_shipped_allowance(band, spiky=spiky)
        width = m.wilson.interval.high - m.wilson.interval.low
        reads.append(
            AspectRead(
                aspect=m.aspect,
                band=band,
                reference_share=m.reference_share,
                sample_share=m.sample_share,
                error=m.error,
                within_tolerance=None if tolerance is None else m.error <= tolerance,
                shipped_covered=needed_inflation(m.error, width) <= allowance,
                wilson_width=width,
            )
        )
    return tuple(reads)


def take_all_reads(measured: Sequence[AspectMeasurement]) -> tuple[AspectRead, ...]:
    """One take-all cell's reads, with the exactness verification.

    The sample being the whole pool, every aspect's measured share must equal
    its reference exactly — same integers, same division. A nonzero error is
    a construction failure (the measurement's universe diverged from the
    reference's), never a sampling outcome, and raises rather than recording
    a cell the verdict would then mis-read as evidence.
    """
    drifted = [m.aspect for m in measured if m.error != 0.0]
    if drifted:
        raise ValueError(
            f"take-all cell measured nonzero error on {len(drifted)} aspect(s) "
            f"(first: {drifted[:3]}) — a whole-pool draw must reproduce the "
            "reference exactly; the measurement wiring has diverged"
        )
    return tuple(
        AspectRead(
            aspect=m.aspect,
            band=share_band(m.reference_share),
            reference_share=m.reference_share,
            sample_share=m.sample_share,
            error=m.error,
            within_tolerance=None,
            shipped_covered=None,
            wilson_width=None,
        )
        for m in measured
    )


def close_game(
    reviews: Sequence[Review],
    aspect_reviews: Mapping[str, Set[str]],
    cfg: ClosingConfig,
) -> GameClosing:
    """Run one held-out game through the anchor grid — the size rule as shipped.

    Deterministic end to end, no seeds anywhere: per anchor, the pool at or
    under the cutoff is measured whole (exactness verified), the pool above
    it draws the ruled n time-proportional through the certified seams and
    reads the certified gates. Raises on an empty pool — a caller bug.
    """
    if not reviews:
        raise ValueError("cannot run a closing test over an empty review pool")
    grid = anchor_grid(reviews, cfg.quantiles)

    rows: list[ClosingCellRow] = []
    for anchor in grid.anchors:
        pool = truncate_pool(reviews, anchor.cutoff)
        histogram = corpus_histogram(pool)
        spiky = is_spiky_regime(peak_window_share(histogram))
        references = anchored_reference_shares(pool, aspect_reviews)
        take_all = anchor.pool_size <= cfg.take_all_cutoff
        if take_all:
            reads = take_all_reads(measure_draw(pool, aspect_reviews, references))
            size = anchor.pool_size
        else:
            plan = compile_plan(
                histogram,
                SamplingPolicy(
                    kind=SamplingPolicyKind.TIME_PROPORTIONAL,
                    target_size=cfg.sample_size,
                ),
            )
            sample = execute_plan(pool, plan)
            reads = sampled_reads(measure_draw(sample, aspect_reviews, references), spiky=spiky)
            size = cfg.sample_size
        rows.append(
            ClosingCellRow(
                app_id=reviews[0].app_id,
                anchor_quantile=anchor.quantile,
                anchor_cutoff=anchor.cutoff,
                pool_size=anchor.pool_size,
                take_all=take_all,
                size=size,
                spiky=spiky,
                reads=reads,
            )
        )
    take_all_cells = sum(row.take_all for row in rows)
    return GameClosing(
        rows=tuple(rows),
        grid=grid,
        sampled_cells=len(rows) - take_all_cells,
        take_all_cells=take_all_cells,
    )


# --- the driver shell -----------------------------------------------------


@dataclass(frozen=True, slots=True)
class RunConfig:
    """One invocation's resolved dial — everything the manifest reproduces.

    ``fetch_dir`` is the fresh-buy run directory: review files, the run-local
    label store, and the manifest whose ``role`` field selects the long-tail
    games all live there. ``ontology_path`` is required for the sweeps'
    reason: the label pools are under v2 while the packaged default is v1.
    """

    fetch_dir: Path
    runs_dir: Path
    ontology_path: Path
    app_ids: tuple[int, ...] | None


def _row_lines(row: ClosingCellRow) -> list[str]:
    """One JSON line per (cell, aspect) — the measurements file's grain."""
    lines: list[str] = []
    for read in row.reads:
        payload: dict[str, object] = {
            "app_id": row.app_id,
            "anchor_quantile": row.anchor_quantile,
            "anchor_cutoff": row.anchor_cutoff.isoformat(),
            "pool_size": row.pool_size,
            "take_all": row.take_all,
            "size": row.size,
            "spiky": row.spiky,
            "aspect": read.aspect,
            "band": read.band.value,
            "reference_share": read.reference_share,
            "sample_share": read.sample_share,
            "error": read.error,
            "within_tolerance": read.within_tolerance,
            "shipped_covered": read.shipped_covered,
            "wilson_width": read.wilson_width,
        }
        lines.append(json.dumps(payload, ensure_ascii=False))
    return lines


def execute_run(cfg: RunConfig, started: datetime | None = None) -> int:
    """One closing-test invocation end to end; returns the process exit code.

    The composition root, mirroring the sweeps' shell: identity, the fetch
    manifest's long-tail selection, the run-local store's indexes and the
    census-fold wiring guard, then the game loop streaming rows to
    ``measurements.jsonl`` with per-game narration. The manifest is written
    whether the run finished or aborted.
    """
    started = started if started is not None else datetime.now(UTC)
    run_id = mint_run_id("m2close", started)
    run_dir = cfg.runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    stamp = load_ontology_version(cfg.ontology_path)
    versions = ClassifierVersions(
        model_version=MODEL_ID,
        prompt_version=PROMPT_VERSION,
        ontology_version=stamp.version,
    )
    closing_cfg = ClosingConfig(
        quantiles=ANCHOR_QUANTILES,
        sample_size=RULED_SAMPLE_SIZE,
        take_all_cutoff=TAKE_ALL_CUTOFF,
    )
    code = code_version()
    resolved_hash = config_hash({
        "model_version": versions.model_version,
        "prompt_version": versions.prompt_version,
        "ontology_version": versions.ontology_version,
        "ontology_content_hash": stamp.content_hash,
        "quantiles": list(ANCHOR_QUANTILES),
        "sample_size": RULED_SAMPLE_SIZE,
        "take_all_cutoff": TAKE_ALL_CUTOFF,
        "fetch_dir": str(cfg.fetch_dir),
        "app_ids": None if cfg.app_ids is None else sorted(cfg.app_ids),
    })

    aborted: str | None = None
    games_meta: dict[str, object] = {}
    source_run_id: str | None = None
    total_rows = total_cells = 0

    with (
        (run_dir / "run.log").open("a", encoding="utf-8", buffering=1) as log,
        (run_dir / "measurements.jsonl").open("w", encoding="utf-8") as out,
        Store(cfg.fetch_dir / "labels.sqlite3") as store,
    ):
        sink: Sink = TeeSink(log)
        narrate(
            sink, _STAGE, StageKind.STARTED,
            f"run {run_id} · code {code} · labels {versions.model_version}/"
            f"{versions.prompt_version}/{versions.ontology_version} · "
            f"anchors {ANCHOR_QUANTILES} · n {RULED_SAMPLE_SIZE} · "
            f"cutoff {TAKE_ALL_CUTOFF} · fetch {cfg.fetch_dir}",
        )
        try:
            manifest = read_fetch_manifest(cfg.fetch_dir)
            source_run_id = manifest.run_id
            held_out = [game for game in manifest.games if game.role == CLOSING_ROLE]
            if not held_out:
                raise RunAbort(
                    f"{cfg.fetch_dir}: manifest holds no {CLOSING_ROLE!r} games — "
                    "wrong run directory"
                )
            envelope_ids, mention_ids = load_label_indexes(store, versions)
            if not envelope_ids:
                raise RunAbort(
                    f"no survey envelopes under {versions.model_version}/"
                    f"{versions.prompt_version}/{versions.ontology_version} — "
                    "wrong version pin or wrong store"
                )
            census = census_shares_by_game(mint_census_aggregates(store, versions=versions))

            for game in held_out:
                if cfg.app_ids is not None and game.app_id not in cfg.app_ids:
                    continue
                result = read_reviews_file(cfg.fetch_dir / f"{game.app_id}_reviews.jsonl")
                labeled = envelope_ids.get(game.app_id)
                aspect_reviews = mention_ids.get(game.app_id)
                if labeled is None or aspect_reviews is None or game.app_id not in census:
                    raise RunAbort(
                        f"app_id {game.app_id}: held-out game absent from the label "
                        "pool — the fresh buy labeled every usable review; wrong store"
                    )
                pool = tuple(r for r in result.reviews if r.review_id in labeled)
                assert_reference_wiring(game.app_id, pool, aspect_reviews, census[game.app_id])

                game_started = time.monotonic()
                closing = close_game(pool, aspect_reviews, closing_cfg)
                for row in closing.rows:
                    for line in _row_lines(row):
                        out.write(line + "\n")
                        total_rows += 1
                total_cells += len(closing.rows)
                games_meta[str(game.app_id)] = {
                    "name": game.name,
                    "pool": len(pool),
                    "dropped_unlabeled": result.usable - len(pool),
                    "aspects": len(aspect_reviews),
                    "anchors": [
                        {
                            "quantile": a.quantile,
                            "cutoff": a.cutoff.isoformat(),
                            "pool": a.pool_size,
                        }
                        for a in closing.grid.anchors
                    ],
                    "duplicate_anchor_quantiles": list(closing.grid.duplicates),
                    "sampled_cells": closing.sampled_cells,
                    "take_all_cells": closing.take_all_cells,
                }
                narrate(
                    sink, _STAGE, StageKind.PROGRESS,
                    f"app {game.app_id} ({game.name}): pool {len(pool):,} · "
                    f"{closing.sampled_cells} sampled + {closing.take_all_cells} take-all "
                    f"cells · {time.monotonic() - game_started:.1f}s",
                )
        except KeyboardInterrupt:
            aborted = "keyboard interrupt"
        except RunAbort as exc:
            aborted = str(exc)
        except Exception as exc:  # manifest still written even when dying loud
            aborted = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()

        finished = datetime.now(UTC)
        manifest_path = write_manifest(run_dir, {
            "run_id": run_id,
            "code_version": code,
            "config_hash": resolved_hash,
            "model_version": versions.model_version,
            "prompt_version": versions.prompt_version,
            "ontology_version": versions.ontology_version,
            "ontology_content_hash": stamp.content_hash,
            "ontology_override": str(cfg.ontology_path),
            "fetch_dir": str(cfg.fetch_dir),
            "source_run_id": source_run_id,
            "anchor_quantiles": list(ANCHOR_QUANTILES),
            "sample_size": RULED_SAMPLE_SIZE,
            "take_all_cutoff": TAKE_ALL_CUTOFF,
            "app_ids": None if cfg.app_ids is None else sorted(cfg.app_ids),
            "games": games_meta,
            "cells": total_cells,
            "rows": total_rows,
            "started_at": started.isoformat(),
            "finished_at": finished.isoformat(),
            "aborted": aborted,
        })
        outcome_kind = StageKind.WARN if aborted else StageKind.DONE
        narrate(
            sink, _STAGE, outcome_kind,
            (f"ABORTED: {aborted}" if aborted else "closing test complete")
            + f" · {len(games_meta)} games · {total_cells:,} cells · {total_rows:,} rows · "
            f"manifest {manifest_path}",
        )
    return 1 if aborted else 0


def main() -> None:
    """Parse the dial and run. The closing test's front door."""
    parser = argparse.ArgumentParser(
        description="Run the M2 closing test over the fresh-buy long-tail games."
    )
    parser.add_argument("--fetch", type=Path, required=True,
                        help="the fresh-buy fetch run directory (reviews + labels + manifest)")
    parser.add_argument("--runs-dir", type=Path, default=Path("data/runs"),
                        help="where run artifacts land (default: data/runs)")
    parser.add_argument("--ontology", type=Path, required=True,
                        help="ontology artifact path — the label pool needs the explicit v2 pin")
    parser.add_argument("--games", type=int, nargs="*", default=None,
                        help="restrict to these app ids (the smoke dial)")
    args = parser.parse_args()

    cfg = RunConfig(
        fetch_dir=args.fetch,
        runs_dir=args.runs_dir,
        ontology_path=args.ontology,
        app_ids=None if args.games is None else tuple(args.games),
    )
    raise SystemExit(execute_run(cfg))


if __name__ == "__main__":
    main()
