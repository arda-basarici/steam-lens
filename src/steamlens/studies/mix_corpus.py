"""The mixing sweep — displayed-share drift vs marked-window contamination share.

Step 9 of the M2 build (design ruled 2026-08-04): the corpus holds zero
marked-window reviews, so the marked-share floor tunes here, offline, from the
fresh-buy material. Each cell blends one bomb game's labeled marked-window
reviews into a certified base draw at a fixed share and re-runs the study's
own measurement — share error and interval coverage against the census truth —
so the floor the analyzer later extracts is "the last share at which the
certified 95%-register promise still holds", the checkpoint's exact gates
re-run with contamination, never a new standard.

The grid is the certified population's (query anchors × games) with three
deliberate specializations. **One size, the ruled n**: the size race is over —
production samples n = 1,000 above the take-all cutoff — so the mixing
question is asked only about the draw production ships. **Take-all anchors are
skipped and counted**: at or under the cutoff the sample *is* the pool, so
contamination moves shares mechanically (a share-s blend shifts each aspect by
exactly s times the composition gap) with no sampling interplay to measure,
and the ruled n never fires there. **Measurement is plan-free**: the shipped
interval method is Wilson (the checkpoint ruling), and a stratified reading
over a blended sample would describe strata the blend just falsified —
swapped-in reviews sit outside the plan's windows by construction.

Per (game, anchor, source): the base draw is the deterministic
time-proportional plan draw; each share then runs seeded repeat blends of
that one fixed sample, seeds derived from the full cell identity — any cell
reproduces in isolation from the manifest's base seed. The share-0 cell is
recorded once per source as the curve's own drift-free baseline, and the run
opens with the sweep's census-fold wiring guard. Aspects are measured over
the union of the base game's and the source's pinned vocabularies: an aspect
the base pool never mentions holds a true zero reference, so bomb material
inventing an aspect (the fresh buy's ``platform_access`` signature) is
measured drift, not an invisible one.
"""

from __future__ import annotations

import argparse
import hashlib
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
from steamlens.corpus import corpus_review_files, read_reviews_file
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
from steamlens.studies.marked_pool import MarkedPool, load_marked_pools
from steamlens.studies.measure import measure_draw
from steamlens.studies.mixing import contaminate
from steamlens.studies.sample_corpus import corpus_histogram, execute_plan
from steamlens.studies.sweep_corpus import (
    AnchorGrid,
    CellSummary,
    anchor_grid,
    anchored_reference_shares,
    assert_reference_wiring,
    census_shares_by_game,
    load_label_indexes,
    summarize_cell,
    truncate_pool,
)

SHARE_GRID: Final = (0.0, 0.02, 0.05, 0.10, 0.15, 0.20, 0.30, 0.50)
"""The ruled contamination grid — dense at the low end, like the size ladder,
because the floor is expected among the small shares."""

RULED_SAMPLE_SIZE: Final = 1000
"""The size rule's sampled-path n (the curves checkpoint, 2026-08-02)."""

TAKE_ALL_CUTOFF: Final = 2000
"""The size rule's take-all boundary (same ruling). Both constants are the
study's local pin of the checkpoint values; when deployment (M3) wires the
runtime policy, the runtime's constants become the source and these must
match them."""

ANCHOR_QUANTILES: Final = (0.40, 0.55, 0.70, 0.85, 1.00)
"""The certified population's anchor grid — the sweep's, unchanged."""

_STAGE: Final = "m2.mix"


@dataclass(frozen=True, slots=True)
class MixCellRow:
    """One (game, anchor, source, share) cell with its per-aspect summaries."""

    app_id: int
    anchor_quantile: float
    anchor_cutoff: datetime
    pool_size: int
    source_app_id: int
    share: float
    size: int
    summaries: tuple[CellSummary, ...]


@dataclass(frozen=True, slots=True)
class MixConfig:
    """The mixing sweep's dials — everything ``mix_game`` needs beyond its inputs.

    ``sample_size`` and ``take_all_cutoff`` are parameters rather than baked
    constants so tests exercise the real control flow at toy scale; production
    invocations pass the ruled values via the driver's defaults.
    """

    shares: tuple[float, ...]
    quantiles: tuple[float, ...]
    sample_size: int
    take_all_cutoff: int
    repeats: int
    base_seed: int


@dataclass(frozen=True, slots=True)
class GameMix:
    """One game's mixing output: rows plus the bookkeeping the manifest records."""

    rows: tuple[MixCellRow, ...]
    grid: AnchorGrid
    skipped_take_all_anchors: int


def derive_mix_seed(
    base_seed: int, app_id: int, quantile: float, source_app_id: int, share: float, repeat: int
) -> int:
    """A stable per-blend seed hashed from the cell's full identity.

    The sweep's seed discipline: order-independent, so any cell is
    reproducible in isolation from the manifest's ``base_seed`` — the source
    game and the share join the key because they are part of the cell's
    identity here.
    """
    key = f"{base_seed}|{app_id}|{quantile:.6f}|{source_app_id}|{share:.6f}|{repeat}"
    return int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big")


def merged_aspect_index(
    base: Mapping[str, Set[str]], marked: Mapping[str, Set[str]]
) -> dict[str, frozenset[str]]:
    """The measurement index over both vocabularies — union per aspect.

    Aspects only the marked material mentions enter with the base game
    contributing nothing, which is what gives them a true zero reference
    share at every anchor: contamination inventing an aspect scores as error
    from zero rather than escaping measurement.
    """
    empty: frozenset[str] = frozenset()
    return {
        aspect: frozenset(base.get(aspect, empty)) | frozenset(marked.get(aspect, empty))
        for aspect in set(base) | set(marked)
    }


def mix_game(
    reviews: Sequence[Review],
    aspect_reviews: Mapping[str, Set[str]],
    sources: Sequence[MarkedPool],
    cfg: MixConfig,
) -> GameMix:
    """Run one base game through the whole grid — anchors × sources × shares.

    Per admitted anchor (pool above the take-all cutoff): one deterministic
    time-proportional base draw at ``cfg.sample_size`` through the certified
    compile → execute seams, then per source and share, ``cfg.repeats``
    seeded blends of that fixed draw, each measured plan-free against the
    anchor's census truth over the merged vocabulary. Share 0.0 records a
    single deterministic baseline draw per source. Raises on an empty pool
    (a caller bug) — and propagates ``contaminate``'s supply failure rather
    than shrinking a share, because a quietly smaller swap would mislabel
    the curve's x-axis.
    """
    if not reviews:
        raise ValueError("cannot mix over an empty review pool")
    app_id = reviews[0].app_id
    grid = anchor_grid(reviews, cfg.quantiles)

    rows: list[MixCellRow] = []
    skipped = 0
    for anchor in grid.anchors:
        if anchor.pool_size <= cfg.take_all_cutoff:
            skipped += 1
            continue
        pool = truncate_pool(reviews, anchor.cutoff)
        histogram = corpus_histogram(pool)
        plan = compile_plan(
            histogram,
            SamplingPolicy(kind=SamplingPolicyKind.TIME_PROPORTIONAL, target_size=cfg.sample_size),
        )
        base_sample = execute_plan(pool, plan)
        for source in sources:
            index = merged_aspect_index(aspect_reviews, source.aspect_reviews)
            references = anchored_reference_shares(pool, index)
            for share in cfg.shares:
                if share == 0.0:
                    draws = [measure_draw(base_sample, index, references)]
                else:
                    draws = [
                        measure_draw(
                            contaminate(
                                base_sample,
                                source.reviews,
                                share,
                                seed=derive_mix_seed(
                                    cfg.base_seed, app_id, anchor.quantile,
                                    source.app_id, share, repeat,
                                ),
                            ),
                            index,
                            references,
                        )
                        for repeat in range(cfg.repeats)
                    ]
                rows.append(
                    MixCellRow(
                        app_id=app_id,
                        anchor_quantile=anchor.quantile,
                        anchor_cutoff=anchor.cutoff,
                        pool_size=anchor.pool_size,
                        source_app_id=source.app_id,
                        share=share,
                        size=cfg.sample_size,
                        summaries=summarize_cell(draws),
                    )
                )
    return GameMix(rows=tuple(rows), grid=grid, skipped_take_all_anchors=skipped)


# --- the driver shell -----------------------------------------------------


@dataclass(frozen=True, slots=True)
class RunConfig:
    """One invocation's resolved dial — everything the manifest reproduces.

    ``ontology_path`` is required for the same reason as the sweep's: the
    label pools are under v2 while the packaged default is v1. ``freshbuy_dir``
    is the fetch run that supplies the marked pools; its label store must be
    under the same frozen triple as the census store, which the pool loader
    enforces by construction (an off-triple store loads empty and dies loud).
    """

    corpus_dir: Path
    db_path: Path
    freshbuy_dir: Path
    runs_dir: Path
    ontology_path: Path
    repeats: int
    base_seed: int
    app_ids: tuple[int, ...] | None


def _row_lines(row: MixCellRow) -> list[str]:
    """One JSON line per (cell, aspect) — the measurements file's grain."""
    lines: list[str] = []
    for summary in row.summaries:
        payload: dict[str, object] = {
            "app_id": row.app_id,
            "anchor_quantile": row.anchor_quantile,
            "anchor_cutoff": row.anchor_cutoff.isoformat(),
            "pool_size": row.pool_size,
            "source_app_id": row.source_app_id,
            "share": row.share,
            "size": row.size,
            "aspect": summary.aspect,
            "reference_share": summary.reference_share,
            "repeats": summary.repeats,
            "mean_sample_share": summary.mean_sample_share,
            "mean_error": summary.mean_error,
            "p50_error": summary.p50_error,
            "p90_error": summary.p90_error,
            "max_error": summary.max_error,
            "wilson": {
                "coverage": summary.wilson.coverage,
                "mean_width": summary.wilson.mean_width,
            },
            "bootstrap": {
                "coverage": summary.bootstrap.coverage,
                "mean_width": summary.bootstrap.mean_width,
            },
        }
        lines.append(json.dumps(payload, ensure_ascii=False))
    return lines


def execute_run(cfg: RunConfig, started: datetime | None = None) -> int:
    """One mixing-sweep invocation end to end; returns the process exit code.

    The composition root, mirroring the curves sweep's shell: identity, the
    marked pools, the census store's indexes and the wiring guard, then the
    game loop streaming rows to ``measurements.jsonl`` with per-game
    narration. The manifest is written whether the run finished or aborted.
    """
    started = started if started is not None else datetime.now(UTC)
    run_id = mint_run_id("m2mix", started)
    run_dir = cfg.runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    stamp = load_ontology_version(cfg.ontology_path)
    versions = ClassifierVersions(
        model_version=MODEL_ID,
        prompt_version=PROMPT_VERSION,
        ontology_version=stamp.version,
    )
    mix_cfg = MixConfig(
        shares=SHARE_GRID,
        quantiles=ANCHOR_QUANTILES,
        sample_size=RULED_SAMPLE_SIZE,
        take_all_cutoff=TAKE_ALL_CUTOFF,
        repeats=cfg.repeats,
        base_seed=cfg.base_seed,
    )
    code = code_version()
    resolved_hash = config_hash({
        "model_version": versions.model_version,
        "prompt_version": versions.prompt_version,
        "ontology_version": versions.ontology_version,
        "ontology_content_hash": stamp.content_hash,
        "shares": list(SHARE_GRID),
        "quantiles": list(ANCHOR_QUANTILES),
        "sample_size": RULED_SAMPLE_SIZE,
        "take_all_cutoff": TAKE_ALL_CUTOFF,
        "repeats": cfg.repeats,
        "base_seed": cfg.base_seed,
        "freshbuy_dir": str(cfg.freshbuy_dir),
        "app_ids": None if cfg.app_ids is None else sorted(cfg.app_ids),
    })

    aborted: str | None = None
    games_meta: dict[str, object] = {}
    sources_meta: dict[str, object] = {}
    total_rows = total_cells = 0

    with (
        (run_dir / "run.log").open("a", encoding="utf-8", buffering=1) as log,
        (run_dir / "measurements.jsonl").open("w", encoding="utf-8") as out,
        Store(cfg.db_path) as store,
    ):
        sink: Sink = TeeSink(log)
        narrate(
            sink, _STAGE, StageKind.STARTED,
            f"run {run_id} · code {code} · labels {versions.model_version}/"
            f"{versions.prompt_version}/{versions.ontology_version} · "
            f"shares {SHARE_GRID} · n {RULED_SAMPLE_SIZE} · cutoff {TAKE_ALL_CUTOFF} · "
            f"repeats {cfg.repeats} · base seed {cfg.base_seed}",
        )
        try:
            sources = load_marked_pools(cfg.freshbuy_dir, versions)
            sources_meta = {
                str(s.app_id): {
                    "name": s.name,
                    "pool": len(s.reviews),
                    "dropped_unlabeled": s.dropped_unlabeled,
                    "source_run_id": s.source_run_id,
                }
                for s in sources
            }
            narrate(
                sink, _STAGE, StageKind.PROGRESS,
                "marked pools: "
                + " · ".join(f"{s.name} {len(s.reviews):,}" for s in sources)
                + f" (run {sources[0].source_run_id})",
            )
            envelope_ids, mention_ids = load_label_indexes(store, versions)
            if not envelope_ids:
                raise RunAbort(
                    f"no survey envelopes under {versions.model_version}/"
                    f"{versions.prompt_version}/{versions.ontology_version} — "
                    "wrong version pin or wrong database"
                )
            census = census_shares_by_game(mint_census_aggregates(store, versions=versions))

            for path in corpus_review_files(cfg.corpus_dir):
                result = read_reviews_file(path)
                app_id = result.app_id
                if cfg.app_ids is not None and app_id not in cfg.app_ids:
                    continue
                labeled = envelope_ids.get(app_id)
                aspect_reviews = mention_ids.get(app_id)
                if labeled is None or aspect_reviews is None or app_id not in census:
                    raise RunAbort(
                        f"app_id {app_id}: corpus game absent from the label pool — "
                        "the census covered every usable game; wrong db or corpus"
                    )
                pool = tuple(r for r in result.reviews if r.review_id in labeled)
                assert_reference_wiring(app_id, pool, aspect_reviews, census[app_id])

                game_started = time.monotonic()
                mixed = mix_game(pool, aspect_reviews, sources, mix_cfg)
                for row in mixed.rows:
                    for line in _row_lines(row):
                        out.write(line + "\n")
                        total_rows += 1
                total_cells += len(mixed.rows)
                games_meta[str(app_id)] = {
                    "pool": len(pool),
                    "aspects": len(aspect_reviews),
                    "anchors_admitted": len(mixed.grid.anchors) - mixed.skipped_take_all_anchors,
                    "skipped_take_all_anchors": mixed.skipped_take_all_anchors,
                    "duplicate_anchor_quantiles": list(mixed.grid.duplicates),
                }
                narrate(
                    sink, _STAGE, StageKind.PROGRESS,
                    f"app {app_id}: pool {len(pool):,} · "
                    f"{len(mixed.grid.anchors) - mixed.skipped_take_all_anchors} anchors admitted "
                    f"({mixed.skipped_take_all_anchors} take-all skipped) · "
                    f"{len(mixed.rows)} cells · {time.monotonic() - game_started:.1f}s",
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
            "corpus_dir": str(cfg.corpus_dir),
            "db_path": str(cfg.db_path),
            "freshbuy_dir": str(cfg.freshbuy_dir),
            "marked_sources": sources_meta,
            "shares": list(SHARE_GRID),
            "anchor_quantiles": list(ANCHOR_QUANTILES),
            "sample_size": RULED_SAMPLE_SIZE,
            "take_all_cutoff": TAKE_ALL_CUTOFF,
            "repeats": cfg.repeats,
            "base_seed": cfg.base_seed,
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
            (f"ABORTED: {aborted}" if aborted else "mixing sweep complete")
            + f" · {len(games_meta)} games · {total_cells:,} cells · {total_rows:,} rows · "
            f"manifest {manifest_path}",
        )
    return 1 if aborted else 0


def main() -> None:
    """Parse the dial and run. The mixing sweep's front door."""
    parser = argparse.ArgumentParser(
        description="Run the M2 mixing sweep over the labeled corpus. Smoke with --games first."
    )
    parser.add_argument("--corpus", type=Path, required=True,
                        help="directory holding the <app_id>_reviews.jsonl corpus files")
    parser.add_argument("--db", type=Path, default=Path("data/steamlens.sqlite3"),
                        help="the label-pool database (default: data/steamlens.sqlite3)")
    parser.add_argument("--freshbuy", type=Path, required=True,
                        help="the fresh-buy fetch run directory supplying the marked pools")
    parser.add_argument("--runs-dir", type=Path, default=Path("data/runs"),
                        help="where run artifacts land (default: data/runs)")
    parser.add_argument("--ontology", type=Path, required=True,
                        help="ontology artifact path — the census pool needs the explicit v2 pin")
    parser.add_argument("--repeats", type=int, default=200,
                        help="seeded blends per (source, share) cell (default 200)")
    parser.add_argument("--base-seed", type=int, default=20260804,
                        help="the run's base seed; per-blend seeds derive from it")
    parser.add_argument("--games", type=int, nargs="*", default=None,
                        help="restrict to these app ids (the smoke dial)")
    args = parser.parse_args()

    cfg = RunConfig(
        corpus_dir=args.corpus,
        db_path=args.db,
        freshbuy_dir=args.freshbuy,
        runs_dir=args.runs_dir,
        ontology_path=args.ontology,
        repeats=args.repeats,
        base_seed=args.base_seed,
        app_ids=None if args.games is None else tuple(args.games),
    )
    raise SystemExit(execute_run(cfg))


if __name__ == "__main__":
    main()
