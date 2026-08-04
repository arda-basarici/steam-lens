"""The closing-test verdict arithmetic — register reads over a closing run's rows.

The closing runner's rows carry per-cell gate reads minted while the draws
existed (``closing_corpus.AspectRead``); this module owns the reduction from
those rows to the verdict the M2 report quotes. The promise language is the
checkpoint's own, and the population reading is the certified one: a game's
sampled side passes when at least the register's fraction of its *cells*
(anchors × aspects, each exactly one deterministic draw) satisfies each gate —
the share-error tolerance where the regime rules one, and shipped-interval
coverage everywhere. The take-all side carries the other half of the size
rule's promise: exactness, re-verified here from the persisted rows because
the verdict stands on the file, not on the runner's memory of having checked.

A game that closed entirely take-all (every anchor pool at or under the
cutoff) has no sampled read at all — its verdict is the exactness
verification alone, which is precisely what the size rule promises such a
game. Per-band reads are diagnosis for the narrative; the verdict never gates
per band, mirroring the certification's pooled reading.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from steamlens.studies.allowance import ShareBand
from steamlens.studies.floor import REGISTER

__all__ = [
    "REGISTER",
    "ClosingRow",
    "SampledRead",
    "GameVerdict",
    "game_verdicts",
    "sampled_read",
    "band_reads",
]


@dataclass(frozen=True, slots=True)
class ClosingRow:
    """One measurement row's verdict slice — the closing arithmetic's input atom.

    ``anchor_quantile`` keeps the full-anchor headline slice extractable;
    the two gate fields are ``None`` on take-all rows (no interval ships)
    and ``within_tolerance`` is additionally ``None`` on sampled rows in
    interval-governed bands.
    """

    app_id: int
    anchor_quantile: float
    take_all: bool
    band: ShareBand
    error: float
    within_tolerance: bool | None
    shipped_covered: bool | None


@dataclass(frozen=True, slots=True)
class SampledRead:
    """Pooled promise reads over a set of sampled cells — cell-weighted.

    Each cell is exactly one deterministic draw, so cells are the draw
    weights. ``tolerance_rate`` is ``None`` when every pooled cell sat in an
    interval-governed band; the two cell counts are the evidence mass behind
    each rate.
    """

    tolerance_rate: float | None
    coverage_rate: float
    tolerance_cells: int
    coverage_cells: int

    def passes(self, register: float = REGISTER) -> bool:
        """Whether both gates hold at the register — an absent tolerance gate holds."""
        coverage_ok = self.coverage_rate >= register
        tolerance_ok = self.tolerance_rate is None or self.tolerance_rate >= register
        return coverage_ok and tolerance_ok


@dataclass(frozen=True, slots=True)
class GameVerdict:
    """One held-out game's closing verdict — both sides of the size rule.

    ``exact`` is the take-all side's re-verification over the persisted rows
    (vacuously true for a game with none); ``sampled`` is ``None`` exactly
    when the game closed entirely take-all — the honest shape for a game the
    size rule never samples.
    """

    take_all_cells_exact: int
    exact: bool
    sampled: SampledRead | None

    def passes(self, register: float = REGISTER) -> bool:
        """The game's verdict: exactness holds, and the sampled read (if any) passes."""
        return self.exact and (self.sampled is None or self.sampled.passes(register))


def sampled_read(rows: Iterable[ClosingRow]) -> SampledRead:
    """Pool sampled rows into one cell-weighted read.

    Public for the verdict's slices — the full-anchor headline read and the
    band diagnosis pool through the same arithmetic as the game verdicts.
    Raises on an empty pool: a rate over nothing is a caller bug.
    """
    rows = list(rows)
    if not rows:
        raise ValueError("cannot pool a sampled read over no rows")
    covered = sum(bool(row.shipped_covered) for row in rows)
    tolerance_rows = [row for row in rows if row.within_tolerance is not None]
    return SampledRead(
        tolerance_rate=(
            sum(bool(row.within_tolerance) for row in tolerance_rows) / len(tolerance_rows)
            if tolerance_rows
            else None
        ),
        coverage_rate=covered / len(rows),
        tolerance_cells=len(tolerance_rows),
        coverage_cells=len(rows),
    )


def game_verdicts(rows: Iterable[ClosingRow]) -> dict[int, GameVerdict]:
    """Reduce a run's rows to one verdict per held-out game.

    The take-all side re-verifies exactness from the rows themselves (a
    nonzero error fails the game — the file no longer supports the promise);
    the sampled side pools each game's cells into its register read. Raises
    on an empty input: a verdict over nothing is a caller bug.
    """
    grouped: dict[int, list[ClosingRow]] = {}
    for row in rows:
        grouped.setdefault(row.app_id, []).append(row)
    if not grouped:
        raise ValueError("no closing rows to read a verdict over")

    verdicts: dict[int, GameVerdict] = {}
    for app_id, members in grouped.items():
        take_all = [row for row in members if row.take_all]
        sampled = [row for row in members if not row.take_all]
        verdicts[app_id] = GameVerdict(
            take_all_cells_exact=sum(row.error == 0.0 for row in take_all),
            exact=all(row.error == 0.0 for row in take_all),
            sampled=sampled_read(sampled) if sampled else None,
        )
    return verdicts


def band_reads(rows: Iterable[ClosingRow]) -> dict[ShareBand, SampledRead]:
    """The sampled cells' reads sliced by display band — diagnosis, never a gate.

    Pooled across games; take-all rows stay out (they quote no interval and
    carry no gate to read). Bands with no sampled cells are simply absent.
    """
    grouped: dict[ShareBand, list[ClosingRow]] = {}
    for row in rows:
        if not row.take_all:
            grouped.setdefault(row.band, []).append(row)
    return {band: sampled_read(members) for band, members in grouped.items()}
