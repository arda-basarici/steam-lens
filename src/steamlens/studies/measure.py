"""Measure one simulated draw — mention shares, the interval trio, error, coverage.

The study's per-draw scoring: given a drawn sample and the census-derived
ground truth, compute each measured aspect's mention share, its distance from
the census share, and whether each candidate interval covers the truth. The
convergence gates (ruled 2026-08-02) read these directly — share error within
tolerance, intervals covering at their nominal rate — and the mention share is
the gated quantity (``reviews_with_aspect / n``, review-denominated; sentiment
mix is descriptive reporting, not a gate).

Shares are computed by set intersection against a per-aspect review index
rather than re-running the aggregate fold: the census reference counts an
aspect's distinct reviews, so a sample's share under the identical definition
is the overlap between the sample's ids and that aspect's reviews — the same
number the fold would mint, at a fraction of the cost across hundreds of
thousands of draws. *Which* aspects get measured is deliberately the caller's:
the gate applies to aspects the report would display, and display selection
(pinned vocabulary, the evidence floor) is the checkpoint's policy, not this
module's.

The stratified interval applies only to draws that actually had strata — a
windowed plan's — and is honestly absent otherwise (cursor-prefix and the
uniform reference draw have no windows to stratify by). Its strata are rebuilt
here from the plan and the histogram the plan was compiled from: window
populations are the claimed bucket volumes, the numbers a runtime would hold.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass
from datetime import datetime

from steamlens.contracts import (
    AspectAggregate,
    FetchPlan,
    HistogramSnapshot,
    Review,
)
from steamlens.core.intervals import (
    Interval,
    Stratum,
    exact_bootstrap_interval,
    stratified_interval,
    wilson_interval,
)


@dataclass(frozen=True, slots=True)
class IntervalReading:
    """One candidate interval on one aspect's share, judged against the truth.

    ``covered`` is the calibration gate's atom: whether the census share fell
    inside the interval this method quoted. Tallied over many draws it becomes
    the method's measured coverage rate.
    """

    interval: Interval
    covered: bool


@dataclass(frozen=True, slots=True)
class AspectMeasurement:
    """One aspect's scoring for one draw — the row the sweep accumulates.

    ``sample_share`` and ``reference_share`` are mention shares (distinct
    reviews mentioning the aspect over the denominator); ``error`` is their
    absolute gap — the share-error gate's atom. ``stratified`` is ``None``
    exactly when the draw had no strata to be design-aware about.
    """

    aspect: str
    sample_share: float
    reference_share: float
    error: float
    wilson: IntervalReading
    bootstrap: IntervalReading
    stratified: IntervalReading | None


def mention_shares(aggregates: Sequence[AspectAggregate]) -> dict[str, float]:
    """Census aggregates for one game into the reference shares the gate uses.

    ``reviews_with_aspect / sample_size`` per aspect — the review-denominated
    mention share, the gated quantity. Raises on aggregates spanning more than
    one game (a reference describes one game's truth) and on a duplicate
    aspect string across slots: a pinned and a candidate aspect sharing a name
    would silently overwrite each other's truth, and which one the report
    displays is a policy question the caller must resolve first.
    """
    games = {aggregate.app_id for aggregate in aggregates}
    if len(games) > 1:
        raise ValueError(
            f"aggregates span app_ids {sorted(games)} — reference shares describe one game"
        )
    shares: dict[str, float] = {}
    for aggregate in aggregates:
        if aggregate.aspect in shares:
            raise ValueError(
                f"aspect {aggregate.aspect!r} appears in more than one slot — "
                "resolve the pinned/candidate collision before measuring against it"
            )
        shares[aggregate.aspect] = aggregate.reviews_with_aspect / aggregate.sample_size
    return shares


def measure_draw(
    sample: Sequence[Review],
    aspect_reviews: Mapping[str, Set[str]],
    reference_shares: Mapping[str, float],
    *,
    plan: FetchPlan | None = None,
    histogram: HistogramSnapshot | None = None,
) -> tuple[AspectMeasurement, ...]:
    """Score one draw against the census truth, aspect by aspect.

    ``aspect_reviews`` maps each aspect to the ids of every corpus review
    mentioning it (built once per game from the label pool); an aspect the
    sample never drew scores a zero share and its full reference share as
    error — a real measurement, not a gap. Pass the windowed ``plan`` together
    with the ``histogram`` it was compiled from to get the stratified reading;
    draws without windows (cursor-prefix, the uniform reference) leave it
    ``None``. Output is sorted by aspect name, deterministically. Raises on an
    empty sample, an empty reference (measuring nothing is a caller bug), or
    a windowed plan arriving without its histogram.
    """
    if not sample:
        raise ValueError("cannot measure an empty sample")
    if not reference_shares:
        raise ValueError("no reference shares — nothing to measure against")

    sample_ids = {review.review_id for review in sample}
    if len(sample_ids) != len(sample):
        raise ValueError("sample contains duplicate review ids — a draw never repeats a review")

    windows = plan.windows if plan is not None else ()
    window_members: list[set[str]] = []
    populations: list[int] = []
    if windows:
        if histogram is None:
            raise ValueError("a windowed plan needs its histogram to rebuild strata populations")
        populations = [_window_population(histogram, window.start) for window in windows]
        window_members = [
            {
                review.review_id
                for review in sample
                if window.start <= review.created_at < window.end
            }
            for window in windows
        ]

    measurements: list[AspectMeasurement] = []
    for aspect in sorted(reference_shares):
        mentioning = aspect_reviews.get(aspect, frozenset())
        successes = len(sample_ids & mentioning)
        share = successes / len(sample)
        reference = reference_shares[aspect]
        stratified = None
        if windows:
            strata = tuple(
                Stratum(
                    successes=len(members & mentioning),
                    sample_size=window.quota,
                    population=population,
                )
                for window, members, population in zip(
                    windows, window_members, populations, strict=True
                )
            )
            reading = stratified_interval(strata)
            stratified = IntervalReading(interval=reading, covered=reading.covers(reference))
        wilson = wilson_interval(successes, len(sample))
        bootstrap = exact_bootstrap_interval(successes, len(sample))
        measurements.append(
            AspectMeasurement(
                aspect=aspect,
                sample_share=share,
                reference_share=reference,
                error=abs(share - reference),
                wilson=IntervalReading(interval=wilson, covered=wilson.covers(reference)),
                bootstrap=IntervalReading(interval=bootstrap, covered=bootstrap.covers(reference)),
                stratified=stratified,
            )
        )
    return tuple(measurements)


def _window_population(histogram: HistogramSnapshot, start: datetime) -> int:
    """The claimed review count of the bucket a window was planned from.

    Windows are minted one-per-populated-bucket, so the window's start *is*
    its bucket's start; a miss means the plan and histogram were not compiled
    together — a wiring bug worth dying on.
    """
    for bucket in histogram.rollups:
        if bucket.start == start:
            return bucket.recommendations_up + bucket.recommendations_down
    raise ValueError(
        f"no histogram bucket starts at {start} — the plan was not compiled from this histogram"
    )
