"""The marked-share floor arithmetic — register reads over a mixing run's gate rates.

The mixing sweep's rows carry per-cell gate rates minted while the draws
existed (``mix_corpus.GateSummary``); this module owns the reduction from
those rows to the floor the M2 report quotes. The promise language is the
checkpoint's own: a (source, share) passes when at least the register's
fraction of the population's *draws* satisfies each gate — the share-error
tolerance where the regime rules one, and shipped-interval coverage
everywhere. Draws weight the pooling because a blended draw is one simulated
report run: a cell with 200 blends contributes 200 promise reads, the
share-0 baseline cell contributes its single deterministic one.

The floor itself is a prefix rule, not a pointwise one: the floor is the
largest share such that **every** share at or below it passes, so one
failing low share caps the floor even if a higher share squeaks back over
the register (noise never re-opens a broken promise). A failing share-0
baseline yields no floor at all — the uncontaminated cells restate the
checkpoint's certified promise, and their failure means the run disagrees
with the certification, a wiring question to resolve before any floor is
quotable. A floor equal to the grid's top share is *censored*: the promise
never broke on the grid, and the honest quote is "at least this", never a
point value.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from steamlens.studies.allowance import ShareBand

REGISTER: float = 0.95
"""The certified register (the curves checkpoint, 2026-08-02) — the fraction
of population draws each gate must satisfy."""


@dataclass(frozen=True, slots=True)
class GateRow:
    """One measurement row's gate slice — the floor arithmetic's input atom."""

    source_app_id: int
    share: float
    band: ShareBand
    repeats: int
    within_tolerance_rate: float | None
    shipped_coverage_rate: float


@dataclass(frozen=True, slots=True)
class RegisterRead:
    """Pooled promise reads for one (source, share) — draw-weighted rates.

    ``tolerance_rate`` is ``None`` when no row carried a tolerance (possible
    only in a degenerate slice — some cell always sits in a tolerance-governed
    band on the real grid); ``tolerance_draws``/``coverage_draws`` are the
    weights behind each rate, kept so a verdict can show its evidence mass.
    """

    tolerance_rate: float | None
    coverage_rate: float
    tolerance_draws: int
    coverage_draws: int

    def passes(self, register: float = REGISTER) -> bool:
        """Whether both gates hold at the register — an absent tolerance gate holds."""
        coverage_ok = self.coverage_rate >= register
        tolerance_ok = self.tolerance_rate is None or self.tolerance_rate >= register
        return coverage_ok and tolerance_ok


@dataclass(frozen=True, slots=True)
class FloorRead:
    """One source's floor verdict over its share grid.

    ``floor`` is ``None`` when the share-0 baseline itself fails (no promise
    to extend — a wiring question, not a measurement); ``censored`` is true
    when every share passed, so the floor is the grid's top share as a lower
    bound, not a located break. ``verdicts`` carries the per-share pass/fail
    walk in grid order for the narrative and the figures.
    """

    floor: float | None
    censored: bool
    verdicts: tuple[tuple[float, bool], ...]


def register_reads(rows: Iterable[GateRow]) -> dict[tuple[int, float], RegisterRead]:
    """Pool gate rows into one draw-weighted read per (source, share).

    Tolerance pools only over rows whose regime ruled a tolerance — the
    interval-governed cells (headline, spiky mid) contribute to coverage
    alone, mirroring exactly which promises the checkpoint made. Raises on
    an empty input: reading a register over nothing is a caller bug.
    """
    grouped: dict[tuple[int, float], list[GateRow]] = {}
    for row in rows:
        grouped.setdefault((row.source_app_id, row.share), []).append(row)
    if not grouped:
        raise ValueError("no gate rows to read a register over")

    reads: dict[tuple[int, float], RegisterRead] = {}
    for key, members in grouped.items():
        coverage_draws = sum(m.repeats for m in members)
        coverage_hits = sum(m.shipped_coverage_rate * m.repeats for m in members)
        tolerance_members = [m for m in members if m.within_tolerance_rate is not None]
        tolerance_draws = sum(m.repeats for m in tolerance_members)
        tolerance_rate = (
            sum(m.within_tolerance_rate * m.repeats for m in tolerance_members)  # type: ignore[misc]
            / tolerance_draws
            if tolerance_members
            else None
        )
        reads[key] = RegisterRead(
            tolerance_rate=tolerance_rate,
            coverage_rate=coverage_hits / coverage_draws,
            tolerance_draws=tolerance_draws,
            coverage_draws=coverage_draws,
        )
    return reads


def floor_from_reads(
    reads: Mapping[float, RegisterRead], *, register: float = REGISTER
) -> FloorRead:
    """One source's floor: the largest share whose whole prefix passes.

    Walks the shares in ascending order; the floor is the last passing share
    before the first failure. Requires a share-0 read (the baseline is the
    promise being extended — its absence means the run is missing its own
    control), and a failing baseline yields ``floor=None``. Raises on an
    empty mapping.
    """
    if not reads:
        raise ValueError("no register reads to extract a floor from")
    shares = sorted(reads)
    if shares[0] != 0.0:
        raise ValueError(
            f"share grid starts at {shares[0]}, not 0.0 — the baseline control is missing"
        )
    verdicts = tuple((share, reads[share].passes(register)) for share in shares)
    if not verdicts[0][1]:
        return FloorRead(floor=None, censored=False, verdicts=verdicts)
    floor = 0.0
    for share, passed in verdicts[1:]:
        if not passed:
            break
        floor = share
    censored = floor == shares[-1]
    return FloorRead(floor=floor, censored=censored, verdicts=verdicts)
