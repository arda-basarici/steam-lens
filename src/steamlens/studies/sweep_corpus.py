"""The curves sweep — error and coverage vs sample size, per policy, across the corpus.

M2's centerpiece simulation: every raced policy drawn at every ladder size from
every usable game, scored against the census truth, persisted as the
run-of-record the curves checkpoint rules over (tolerance · size rule · winning
policy · interval method). Offline simulation end to end — nothing here ever
mints a displayed number; the two-track wall stands.

The replication unit is the composed population (ruled 2026-08-02, the step-4
design pass): **query anchors × games × aspects**. Windowed draws are fully
deterministic — same corpus, same plan, same sample, true of the live runtime
too — so repeat-variance exists only for the uniform reference, and "coverage"
needs a population of report runs to be a rate over. Anchors supply the
time-of-query dimension deployment actually faces: truncating a game's corpus
at time T and compiling from the truncated histogram reproduces exactly what a
live query at T would have seen, so the checkpoint's rulings certify report
runs generally, not one snapshot date. Anchors sit at fixed quantiles of each
game's own review-time span — never an absolute calendar grid, which would
place anchors before thin-coverage games existed. One honesty caveat rides the
report, not the code: anchor cells within one game are nested (later corpora
contain earlier ones), so anchors widen the certified population without being
independent replications; and truncating today's corpus at T assumes Steam
would have served the same rows at T — edits and deletions make that an
approximation the live closing test grounds.

Two cell classes are recorded, not measured: an anchor whose truncated pool
duplicates an earlier anchor's (truncation is monotone, so equal size means the
identical pool — re-measuring would add correlated copies), and a
``size >= pool`` cell, which the planner would satisfy take-all with error
identically zero — free flattery for the convergence curves, skipped and
counted instead.

Every draw goes through the certified seams — ``compile_plan`` →
``execute_plan`` → ``measure_draw`` — and the run opens with a wiring guard:
at the full-corpus anchor, this module's id-set reference shares must equal the
census fold's own numbers (``mint_census_aggregates`` → ``mention_shares``),
exactly, for every game, before anything is measured. The sweep's per-game
universe is the *labeled* corpus (usable reviews holding survey envelopes), so
sample and reference shares live over the same denominator definition; the
census labeled all but a handful of the usable pool, and the dropped count is
manifest-recorded per game.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
import traceback
from bisect import bisect_right
from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from steamlens.contracts import (
    AspectAggregate,
    AspectSlot,
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
from steamlens.studies.measure import (
    AspectMeasurement,
    IntervalReading,
    measure_draw,
    mention_shares,
)
from steamlens.studies.sample_corpus import (
    corpus_histogram,
    execute_plan,
    uniform_reference_draw,
)

SIZE_LADDER: Final = (100, 250, 500, 750, 1000, 1500, 2000, 3000, 5000)
"""The ruled ladder (DESIGN, the study-design section) — dense at the low end."""

ANCHOR_QUANTILES: Final = (0.40, 0.55, 0.70, 0.85, 1.00)
"""Query anchors as fractions of each game's own review-time span.

The 100% anchor is the full corpus — continuity with the anchor-free view —
and the grid starts at 40% so even the earliest anchor sees a substantial
history rather than a launch-week fragment.
"""

UNIFORM_REFERENCE: Final = "uniform-random"
"""The reference draw's policy label in rows — deliberately not a
``SamplingPolicyKind`` value, because it is not runtime-expressible."""

_RACED_KINDS: Final = (
    SamplingPolicyKind.TIME_PROPORTIONAL,
    SamplingPolicyKind.EQUAL_PER_WINDOW,
    SamplingPolicyKind.CURSOR_PREFIX,
)

_STAGE: Final = "m2.sweep"


@dataclass(frozen=True, slots=True)
class Anchor:
    """One simulated query moment: its grid quantile, cutoff instant, and pool size."""

    quantile: float
    cutoff: datetime
    pool_size: int


@dataclass(frozen=True, slots=True)
class AnchorGrid:
    """A game's deduplicated anchors plus the quantiles dropped as duplicates."""

    anchors: tuple[Anchor, ...]
    duplicates: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class MethodSummary:
    """One interval method's tally over a cell's draws: coverage rate, mean width."""

    coverage: float
    mean_width: float


@dataclass(frozen=True, slots=True)
class CellSummary:
    """One aspect's tally over a cell's draws — the persisted row's payload.

    For a deterministic (single-draw) cell the error statistics all equal the
    one observed error; for the uniform reference they summarize ``repeats``
    seeded draws. ``stratified`` is ``None`` exactly when the cell's draws had
    no strata (cursor-prefix and the uniform reference).
    """

    aspect: str
    reference_share: float
    repeats: int
    mean_sample_share: float
    mean_error: float
    p50_error: float
    p90_error: float
    max_error: float
    wilson: MethodSummary
    bootstrap: MethodSummary
    stratified: MethodSummary | None


@dataclass(frozen=True, slots=True)
class CellRow:
    """One (game, anchor, policy, size) cell with its per-aspect summaries."""

    app_id: int
    anchor_quantile: float
    anchor_cutoff: datetime
    pool_size: int
    policy: str
    size: int
    summaries: tuple[CellSummary, ...]


@dataclass(frozen=True, slots=True)
class SweepConfig:
    """The sweep's dials — everything ``sweep_game`` needs beyond the game itself."""

    sizes: tuple[int, ...]
    quantiles: tuple[float, ...]
    repeats: int
    base_seed: int


@dataclass(frozen=True, slots=True)
class GameSweep:
    """One game's sweep output: rows plus the bookkeeping the manifest records."""

    rows: tuple[CellRow, ...]
    grid: AnchorGrid
    skipped_take_all: int


def anchor_grid(reviews: Sequence[Review], quantiles: Sequence[float]) -> AnchorGrid:
    """Place the query anchors for one game's pool, dropping duplicate pools.

    Each quantile ``q`` cuts at ``oldest + q * (newest - oldest)`` of the
    game's own review-time span, and the anchor's pool is every review created
    at or before the cutoff. Truncation is monotone in the cutoff, so two
    anchors with equal pool sizes hold the *identical* pool — the later
    quantile is recorded as a duplicate and dropped rather than measured
    twice. Raises on an empty pool or an unsorted/out-of-range grid, both
    caller bugs.
    """
    if not reviews:
        raise ValueError("cannot place anchors over an empty review pool")
    if not quantiles or list(quantiles) != sorted(quantiles):
        raise ValueError(f"anchor quantiles must be ascending, got {quantiles!r}")
    if quantiles[0] <= 0.0 or quantiles[-1] > 1.0:
        raise ValueError(f"anchor quantiles must lie in (0, 1], got {quantiles!r}")

    times = sorted(review.created_at for review in reviews)
    oldest, newest = times[0], times[-1]
    anchors: list[Anchor] = []
    duplicates: list[float] = []
    for quantile in quantiles:
        cutoff = oldest + (newest - oldest) * quantile
        pool_size = bisect_right(times, cutoff)
        if anchors and anchors[-1].pool_size == pool_size:
            duplicates.append(quantile)
            continue
        anchors.append(Anchor(quantile=quantile, cutoff=cutoff, pool_size=pool_size))
    return AnchorGrid(anchors=tuple(anchors), duplicates=tuple(duplicates))


def truncate_pool(reviews: Sequence[Review], cutoff: datetime) -> tuple[Review, ...]:
    """The pool a query at ``cutoff`` would have seen — created at or before it."""
    return tuple(review for review in reviews if review.created_at <= cutoff)


def derive_seed(base_seed: int, app_id: int, quantile: float, size: int, repeat: int) -> int:
    """A stable per-draw seed for the uniform reference — order-independent.

    Hashed from the cell's full identity rather than handed out by a counter,
    so a draw's seed never depends on which games or cells ran before it —
    any cell is reproducible in isolation from the manifest's ``base_seed``.
    """
    key = f"{base_seed}|{app_id}|{quantile:.6f}|{size}|{repeat}"
    return int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big")


def anchored_reference_shares(
    pool: Sequence[Review], aspect_reviews: Mapping[str, Set[str]]
) -> dict[str, float]:
    """The census truth restricted to an anchor's pool — the draw's reference.

    The same mention-share definition the fold mints (distinct reviews holding
    the aspect over the pool size), computed by id intersection so every
    anchor's truth is cheap; at the full-corpus anchor the run's wiring guard
    asserts this equals the fold's own numbers exactly. Aspects the truncated
    pool never mentions keep their zero share — a real truth to measure
    against, not a gap. Raises on an empty pool (a caller bug, never a truth).
    """
    if not pool:
        raise ValueError("cannot build reference shares over an empty pool")
    pool_ids = {review.review_id for review in pool}
    return {
        aspect: len(aspect_reviews[aspect] & pool_ids) / len(pool_ids)
        for aspect in sorted(aspect_reviews)
    }


def summarize_cell(draws: Sequence[tuple[AspectMeasurement, ...]]) -> tuple[CellSummary, ...]:
    """Tally a cell's draws into one summary per aspect.

    Every draw in a cell measures the same aspects in the same sorted order
    (``measure_draw``'s contract given a fixed reference) and shares one plan
    shape, so the stratified reading is either present in every draw or in
    none — a mix means the caller composed the cell wrong and raises. Error
    quantiles interpolate linearly; with a single draw every statistic is that
    draw's own error.
    """
    if not draws:
        raise ValueError("cannot summarize a cell with no draws")
    aspect_orders = {tuple(m.aspect for m in draw) for draw in draws}
    if len(aspect_orders) != 1:
        raise ValueError("draws in one cell measured different aspect sets — a wiring bug")

    summaries: list[CellSummary] = []
    for index, first in enumerate(draws[0]):
        rows = [draw[index] for draw in draws]
        errors = sorted(row.error for row in rows)
        stratified_present = {row.stratified is not None for row in rows}
        if len(stratified_present) != 1:
            raise ValueError(
                f"aspect {first.aspect!r}: stratified reading present in some draws "
                "but not others — one cell holds one plan shape"
            )
        summaries.append(
            CellSummary(
                aspect=first.aspect,
                reference_share=first.reference_share,
                repeats=len(rows),
                mean_sample_share=sum(row.sample_share for row in rows) / len(rows),
                mean_error=sum(errors) / len(errors),
                p50_error=_quantile(errors, 0.50),
                p90_error=_quantile(errors, 0.90),
                max_error=errors[-1],
                wilson=_method_summary([_reading(row.wilson) for row in rows]),
                bootstrap=_method_summary([_reading(row.bootstrap) for row in rows]),
                stratified=(
                    _method_summary(
                        [_reading(row.stratified) for row in rows if row.stratified is not None]
                    )
                    if first.stratified is not None
                    else None
                ),
            )
        )
    return tuple(summaries)


def sweep_game(
    reviews: Sequence[Review],
    aspect_reviews: Mapping[str, Set[str]],
    cfg: SweepConfig,
) -> GameSweep:
    """Run one game through the whole grid — anchors × sizes × policies.

    Deterministic end to end: windowed and cursor draws are single fixed
    draws through the certified compile → execute → measure seams; the
    uniform reference runs ``cfg.repeats`` seeded draws per cell with seeds
    derived from the cell's identity. Take-all cells (``size >= pool``) are
    counted and skipped, never measured.
    """
    if not reviews:
        raise ValueError("cannot sweep an empty review pool")
    app_id = reviews[0].app_id
    grid = anchor_grid(reviews, cfg.quantiles)

    rows: list[CellRow] = []
    skipped_take_all = 0
    for anchor in grid.anchors:
        pool = truncate_pool(reviews, anchor.cutoff)
        histogram = corpus_histogram(pool)
        references = anchored_reference_shares(pool, aspect_reviews)
        for size in cfg.sizes:
            if size >= anchor.pool_size:
                skipped_take_all += 1
                continue
            for kind in _RACED_KINDS:
                plan = compile_plan(histogram, SamplingPolicy(kind=kind, target_size=size))
                sample = execute_plan(pool, plan)
                measured = measure_draw(
                    sample, aspect_reviews, references, plan=plan, histogram=histogram
                )
                rows.append(_cell(app_id, anchor, kind.value, size, summarize_cell([measured])))

            uniform_draws = [
                measure_draw(
                    uniform_reference_draw(
                        pool,
                        size,
                        seed=derive_seed(cfg.base_seed, app_id, anchor.quantile, size, repeat),
                    ),
                    aspect_reviews,
                    references,
                )
                for repeat in range(cfg.repeats)
            ]
            uniform_summary = summarize_cell(uniform_draws)
            rows.append(_cell(app_id, anchor, UNIFORM_REFERENCE, size, uniform_summary))
    return GameSweep(rows=tuple(rows), grid=grid, skipped_take_all=skipped_take_all)


def _cell(
    app_id: int, anchor: Anchor, policy: str, size: int, summaries: tuple[CellSummary, ...]
) -> CellRow:
    """Assemble one cell row — the (game, anchor, policy, size) identity plus payload."""
    return CellRow(
        app_id=app_id,
        anchor_quantile=anchor.quantile,
        anchor_cutoff=anchor.cutoff,
        pool_size=anchor.pool_size,
        policy=policy,
        size=size,
        summaries=summaries,
    )


def _reading(reading: IntervalReading) -> tuple[bool, float]:
    """One interval reading as the ``(covered, width)`` pair the tallies consume."""
    return reading.covered, reading.interval.high - reading.interval.low


def _method_summary(readings: Sequence[tuple[bool, float]]) -> MethodSummary:
    """Coverage rate and mean width over one method's ``(covered, width)`` readings."""
    return MethodSummary(
        coverage=sum(covered for covered, _ in readings) / len(readings),
        mean_width=sum(width for _, width in readings) / len(readings),
    )


def _quantile(ordered: Sequence[float], q: float) -> float:
    """Linear-interpolation quantile of an already-sorted sequence."""
    position = q * (len(ordered) - 1)
    low = math.floor(position)
    high = math.ceil(position)
    fraction = position - low
    return ordered[low] * (1 - fraction) + ordered[high] * fraction


# --- the driver shell -----------------------------------------------------


@dataclass(frozen=True, slots=True)
class RunConfig:
    """One invocation's resolved dial — everything the manifest reproduces.

    ``ontology_path`` is required, never defaulted: the label pool is under
    v2 while the packaged default is still v1 (gold's identity pin), so the
    pin must be explicit or the pool query would silently match nothing.
    ``app_ids`` restricts the run to a subset of games — the smoke dial.
    """

    corpus_dir: Path
    db_path: Path
    runs_dir: Path
    ontology_path: Path
    repeats: int
    base_seed: int
    app_ids: tuple[int, ...] | None


def load_label_indexes(
    store: Store, versions: ClassifierVersions
) -> tuple[dict[int, frozenset[str]], dict[int, dict[str, frozenset[str]]]]:
    """The pool's two id indexes, per game: envelope ids and pinned aspect → mentions.

    Envelopes (empties included) define the labeled universe the sweep draws
    from; the pinned mention index is ``measure_draw``'s ``aspect_reviews``.
    Candidate-slot mentions stay out — the gate applies to displayed aspects,
    and display vocabulary is pinned (the checkpoint's evidence floor then
    filters *within* these). Public because every census-store study consumes
    the same two indexes — the mixing sweep loads through this same function,
    so "what counts as the labeled universe" stays a single definition.
    """
    app_id_of = store.reviews.app_id_by_review()
    envelope_ids: dict[int, set[str]] = {}
    for review_id in store.labels.iter_survey_envelope_review_ids(versions):
        envelope_ids.setdefault(app_id_of[review_id], set()).add(review_id)
    mention_ids: dict[int, dict[str, set[str]]] = {}
    for review_id, aspect, slot, _sentiment in store.labels.iter_survey_mentions(versions):
        if slot is not AspectSlot.PINNED:
            continue
        game = mention_ids.setdefault(app_id_of[review_id], {})
        game.setdefault(aspect, set()).add(review_id)
    return (
        {app_id: frozenset(ids) for app_id, ids in envelope_ids.items()},
        {
            app_id: {aspect: frozenset(ids) for aspect, ids in aspects.items()}
            for app_id, aspects in mention_ids.items()
        },
    )


def census_shares_by_game(
    aggregates: Sequence[AspectAggregate],
) -> dict[int, dict[str, float]]:
    """The fold's own pinned mention shares, per game — the wiring guard's truth.

    Public alongside ``load_label_indexes`` and ``assert_reference_wiring``:
    the census-store studies share one wiring-guard vocabulary.
    """
    pinned: dict[int, list[AspectAggregate]] = {}
    for aggregate in aggregates:
        if aggregate.slot is AspectSlot.PINNED:
            pinned.setdefault(aggregate.app_id, []).append(aggregate)
    return {app_id: mention_shares(rows) for app_id, rows in pinned.items()}


def assert_reference_wiring(
    app_id: int,
    pool: Sequence[Review],
    aspect_reviews: Mapping[str, Set[str]],
    census: Mapping[str, float],
) -> None:
    """Die loud unless the id-set shares equal the fold's at the full anchor.

    Exact float equality on purpose: both sides divide the same two integers
    when the wiring is right, so any difference at all means the universes
    diverged (a labeled review missing from the corpus read, a slot mix-up) —
    a measurement built on that would be confidently wrong everywhere.
    """
    mine = anchored_reference_shares(pool, aspect_reviews)
    if mine != dict(census):
        drifted = sorted(
            aspect
            for aspect in set(mine) | set(census)
            if mine.get(aspect) != census.get(aspect)
        )
        raise RunAbort(
            f"app_id {app_id}: id-set reference shares disagree with the census fold "
            f"on {len(drifted)} aspect(s) (first: {drifted[:3]}) — the sweep's universe "
            "and the fold's have diverged; refusing to measure"
        )


def _row_lines(row: CellRow) -> list[str]:
    """One JSON line per (cell, aspect) — the measurements file's grain."""
    lines: list[str] = []
    for summary in row.summaries:
        payload: dict[str, object] = {
            "app_id": row.app_id,
            "anchor_quantile": row.anchor_quantile,
            "anchor_cutoff": row.anchor_cutoff.isoformat(),
            "pool_size": row.pool_size,
            "policy": row.policy,
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
            "stratified": (
                None
                if summary.stratified is None
                else {
                    "coverage": summary.stratified.coverage,
                    "mean_width": summary.stratified.mean_width,
                }
            ),
        }
        lines.append(json.dumps(payload, ensure_ascii=False))
    return lines


def execute_run(cfg: RunConfig, started: datetime | None = None) -> int:
    """One sweep invocation end to end; returns the process exit code.

    The composition root: identity, the read-only store pass, the census
    cross-check, then the game loop streaming rows to ``measurements.jsonl``
    with per-game narration a second-pane ``tail`` can follow. The manifest
    is written whether the run finished or aborted, and an aborted run still
    records its true progress.
    """
    started = started if started is not None else datetime.now(UTC)
    run_id = mint_run_id("m2sweep", started)
    run_dir = cfg.runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    stamp = load_ontology_version(cfg.ontology_path)
    versions = ClassifierVersions(
        model_version=MODEL_ID,
        prompt_version=PROMPT_VERSION,
        ontology_version=stamp.version,
    )
    sweep_cfg = SweepConfig(
        sizes=SIZE_LADDER,
        quantiles=ANCHOR_QUANTILES,
        repeats=cfg.repeats,
        base_seed=cfg.base_seed,
    )
    code = code_version()
    resolved_hash = config_hash({
        "model_version": versions.model_version,
        "prompt_version": versions.prompt_version,
        "ontology_version": versions.ontology_version,
        "ontology_content_hash": stamp.content_hash,
        "sizes": list(SIZE_LADDER),
        "quantiles": list(ANCHOR_QUANTILES),
        "repeats": cfg.repeats,
        "base_seed": cfg.base_seed,
        "app_ids": None if cfg.app_ids is None else sorted(cfg.app_ids),
    })

    aborted: str | None = None
    games_meta: dict[str, object] = {}
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
            f"ladder {SIZE_LADDER} · anchors {ANCHOR_QUANTILES} · "
            f"repeats {cfg.repeats} · base seed {cfg.base_seed}",
        )
        try:
            envelope_ids, mention_ids = load_label_indexes(store, versions)
            if not envelope_ids:
                raise RunAbort(
                    f"no survey envelopes under {versions.model_version}/"
                    f"{versions.prompt_version}/{versions.ontology_version} — "
                    "wrong version pin or wrong database"
                )
            census = census_shares_by_game(mint_census_aggregates(store, versions=versions))
            narrate(
                sink, _STAGE, StageKind.PROGRESS,
                f"label pool loaded: {len(envelope_ids)} games, "
                f"{sum(len(ids) for ids in envelope_ids.values()):,} envelopes",
            )

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
                sweep = sweep_game(pool, aspect_reviews, sweep_cfg)
                for row in sweep.rows:
                    for line in _row_lines(row):
                        out.write(line + "\n")
                        total_rows += 1
                total_cells += len(sweep.rows)
                games_meta[str(app_id)] = {
                    "pool": len(pool),
                    "dropped_unlabeled": result.usable - len(pool),
                    "aspects": len(aspect_reviews),
                    "anchors": [
                        {
                            "quantile": a.quantile,
                            "cutoff": a.cutoff.isoformat(),
                            "pool": a.pool_size,
                        }
                        for a in sweep.grid.anchors
                    ],
                    "duplicate_anchor_quantiles": list(sweep.grid.duplicates),
                    "skipped_take_all": sweep.skipped_take_all,
                }
                narrate(
                    sink, _STAGE, StageKind.PROGRESS,
                    f"app {app_id}: pool {len(pool):,} · {len(sweep.grid.anchors)} anchors "
                    f"({len(sweep.grid.duplicates)} dup) · {len(sweep.rows)} cells · "
                    f"{sweep.skipped_take_all} take-all skipped · "
                    f"{time.monotonic() - game_started:.1f}s",
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
            "sizes": list(SIZE_LADDER),
            "anchor_quantiles": list(ANCHOR_QUANTILES),
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
            (f"ABORTED: {aborted}" if aborted else "sweep complete")
            + f" · {len(games_meta)} games · {total_cells:,} cells · {total_rows:,} rows · "
            f"manifest {manifest_path}",
        )
    return 1 if aborted else 0


def main() -> None:
    """Parse the dial and run. The curves sweep's front door."""
    parser = argparse.ArgumentParser(
        description="Run the M2 curves sweep over the labeled corpus. Smoke with --games first."
    )
    parser.add_argument("--corpus", type=Path, required=True,
                        help="directory holding the <app_id>_reviews.jsonl corpus files")
    parser.add_argument("--db", type=Path, default=Path("data/steamlens.sqlite3"),
                        help="the label-pool database (default: data/steamlens.sqlite3)")
    parser.add_argument("--runs-dir", type=Path, default=Path("data/runs"),
                        help="where run artifacts land (default: data/runs)")
    parser.add_argument("--ontology", type=Path, required=True,
                        help="ontology artifact path — the census pool needs the explicit v2 pin")
    parser.add_argument("--repeats", type=int, default=200,
                        help="seeded uniform-reference draws per cell (default 200)")
    parser.add_argument("--base-seed", type=int, default=20260802,
                        help="the run's base seed; per-draw seeds derive from it")
    parser.add_argument("--games", type=int, nargs="*", default=None,
                        help="restrict to these app ids (the smoke dial)")
    args = parser.parse_args()

    cfg = RunConfig(
        corpus_dir=args.corpus,
        db_path=args.db,
        runs_dir=args.runs_dir,
        ontology_path=args.ontology,
        repeats=args.repeats,
        base_seed=args.base_seed,
        app_ids=None if args.games is None else tuple(args.games),
    )
    raise SystemExit(execute_run(cfg))


if __name__ == "__main__":
    main()
