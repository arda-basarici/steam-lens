"""Closing-test tests — the gate reads' pure pieces and one game end to end.

The load-bearing claims: the size rule resolves per anchor (take-all at or
under the cutoff, the ruled n above it) with take-all cells recorded rather
than skipped, the take-all exactness verification passing by construction and
failing loud on a diverged measurement, the sampled cells carrying the
certified per-draw gate reads (tolerance where the regime rules one, shipped
coverage everywhere, interval-governed bands tolerance-free), and the whole
game closing being a pure function of its inputs — no seeds anywhere.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from steamlens.contracts import Review
from steamlens.core.allowance import ShareBand
from steamlens.core.intervals import Interval
from steamlens.studies.closing_corpus import (
    ClosingConfig,
    GameClosing,
    close_game,
    sampled_reads,
    take_all_reads,
)
from steamlens.studies.measure import AspectMeasurement, IntervalReading

_START = datetime(2026, 1, 1, tzinfo=UTC)


def _review(review_id: str, day: int, *, app_id: int = 10) -> Review:
    return Review(
        review_id=review_id,
        app_id=app_id,
        created_at=_START + timedelta(days=day),
        language="english",
        text=f"review {review_id}",
        voted_up=True,
    )


def _pool(n: int = 60) -> tuple[Review, ...]:
    """A pool spread across months — reviews r0..r{n-1}, ~2/day."""
    return tuple(_review(f"r{i}", i * 2) for i in range(n))


def _index(pool: tuple[Review, ...]) -> dict[str, frozenset[str]]:
    """Even-numbered reviews mention combat — a ~0.5 reference share."""
    return {
        "combat": frozenset(r.review_id for i, r in enumerate(pool) if i % 2 == 0),
    }


def _cfg(**overrides: object) -> ClosingConfig:
    dials: dict[str, object] = {
        "quantiles": (0.4, 1.0),
        "sample_size": 20,
        "take_all_cutoff": 30,
    }
    dials.update(overrides)
    return ClosingConfig(**dials)  # type: ignore[arg-type]


def _close(**overrides: object) -> GameClosing:
    pool = _pool()
    return close_game(pool, _index(pool), _cfg(**overrides))


def test_size_rule_resolves_per_anchor() -> None:
    """The 40% anchor sits under the cutoff (take-all at pool size); the full
    anchor sits above it (sampled at the ruled n) — both recorded."""
    result = _close()
    assert result.take_all_cells == 1
    assert result.sampled_cells == 1
    by_take_all = {row.take_all: row for row in result.rows}
    assert by_take_all[True].size == by_take_all[True].pool_size <= 30
    assert by_take_all[False].size == 20
    assert by_take_all[False].pool_size == 60


def test_take_all_cells_are_exact_with_no_gate_fields() -> None:
    """A whole-pool draw reproduces the reference exactly, and no gate or
    interval field is quoted — the cell's promise is exactness itself."""
    result = _close()
    take_all = next(row for row in result.rows if row.take_all)
    for read in take_all.reads:
        assert read.error == 0.0
        assert read.sample_share == read.reference_share
        assert read.within_tolerance is None
        assert read.shipped_covered is None
        assert read.wilson_width is None


def test_sampled_cells_carry_gate_reads() -> None:
    """Sampled cells read the certified gates: a quoted Wilson width and a
    coverage verdict on every aspect."""
    result = _close()
    sampled = next(row for row in result.rows if not row.take_all)
    assert sampled.reads
    for read in sampled.reads:
        assert read.shipped_covered is not None
        assert read.wilson_width is not None and read.wilson_width > 0


def test_close_game_is_deterministic() -> None:
    """The whole closing is a pure function of (pool, index, cfg) — no seeds."""
    assert _close() == _close()


def test_all_take_all_game_records_no_sampled_cells() -> None:
    """A game whose every anchor pool sits under the cutoff — the Dragonkin /
    Sword and Fairy shape — closes entirely on the take-all side."""
    result = _close(take_all_cutoff=100)
    assert result.sampled_cells == 0
    assert result.take_all_cells == len(result.rows) > 0


def test_concentrated_pool_is_spiky() -> None:
    """A pool whose one month holds everything crosses the 2/3 regime boundary."""
    pool = tuple(_review(f"r{i}", i % 20) for i in range(40))
    index = {"combat": frozenset(r.review_id for i, r in enumerate(pool) if i % 2 == 0)}
    result = close_game(pool, index, _cfg(quantiles=(1.0,), sample_size=10, take_all_cutoff=5))
    assert result.rows
    assert all(row.spiky for row in result.rows)


def test_empty_pool_fails_loud() -> None:
    """Closing over nothing is a caller bug, never a run."""
    with pytest.raises(ValueError, match="empty review pool"):
        close_game((), {}, _cfg())


def _measurement(aspect: str, reference: float, error: float, width: float) -> AspectMeasurement:
    reading = IntervalReading(interval=Interval(low=0.1, high=0.1 + width), covered=True)
    return AspectMeasurement(
        aspect=aspect,
        sample_share=reference + error,
        reference_share=reference,
        error=error,
        wilson=reading,
        bootstrap=reading,
        stratified=None,
    )


def test_sampled_reads_apply_the_calm_mid_gates() -> None:
    """Calm mid: tolerance ±2.5pts and a zero allowance, judged per the
    centered inflation reading the constants were minted from."""
    within = sampled_reads([_measurement("a", 0.10, 0.02, 0.05)], spiky=False)[0]
    assert within.band is ShareBand.MID
    assert within.within_tolerance is True
    assert within.shipped_covered is True  # inflation max(0, 0.02 - 0.025) = 0

    broken = sampled_reads([_measurement("a", 0.10, 0.03, 0.02)], spiky=False)[0]
    assert broken.within_tolerance is False
    assert broken.shipped_covered is False  # inflation 0.02 over the zero allowance


def test_sampled_reads_interval_governed_bands_are_tolerance_free() -> None:
    """Headline everywhere and spiky mid rule no share tolerance — the read
    is coverage alone, against the regime's own allowance."""
    headline = sampled_reads([_measurement("a", 0.20, 0.03, 0.02)], spiky=False)[0]
    assert headline.band is ShareBand.HEADLINE
    assert headline.within_tolerance is None
    assert headline.shipped_covered is False  # inflation 0.02 over the calm zero

    spiky_mid = sampled_reads([_measurement("a", 0.10, 0.03, 0.02)], spiky=True)[0]
    assert spiky_mid.within_tolerance is None
    assert spiky_mid.shipped_covered is False  # inflation 0.02 over the spiky 0.017


def test_take_all_reads_refuse_a_diverged_measurement() -> None:
    """Nonzero error on a whole-pool draw is a wiring failure, never evidence."""
    with pytest.raises(ValueError, match="reproduce the reference exactly"):
        take_all_reads([_measurement("a", 0.10, 0.01, 0.05)])
