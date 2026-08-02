"""The candidate interval formulas for displayed shares — the trio the study races.

The sampling study (M2) computes all three on every simulated draw and lets the
calibration gate — does the quoted interval cover the census truth at its
nominal rate? — pick the *simplest* one whose coverage is honest under the
winning policy (ruled 2026-08-02). They live in core because the winner ships:
production quotes exactly one of these next to every displayed share.

The candidates, and what each pretends: ``wilson_interval`` is the design-naive
representative — it treats the draw as simple random sampling (Wilson rather
than the cruder Wald, because racing a strawman would rig the "simplest honest
formula" verdict). ``exact_bootstrap_interval`` is the bootstrap-over-reviews
candidate: for a single proportion, resampling n whole-review flags with
replacement *is* a binomial draw, so the percentile interval is computed
exactly from the binomial distribution instead of simulated — the same
interval, deterministic and cheap, honoring the resample-whole-reviews
constraint by construction (the flag is per review). ``stratified_interval``
is the design-aware candidate for windowed draws: per-stratum variance with
finite-population correction off the claimed window populations — the numbers
the runtime would actually hold. It still pretends the within-window draw is
random when the plan's rule is a newest-first prefix; the coverage gate is
precisely the test of that pretense.

Confidence is fixed at 95% — the level the product quotes. Parameterizing it
would drag in inverse-normal machinery no consumer needs; if a second level
ever ships, that is the moment to build it.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

_Z_95 = 1.959963984540054
_LOWER_TAIL = 0.025
_UPPER_TAIL = 0.975


@dataclass(frozen=True, slots=True)
class Interval:
    """A closed confidence interval on a share, both bounds in ``[0, 1]``.

    ``covers`` is the calibration gate's primitive: whether the true value the
    interval claims to bracket actually lies inside it.
    """

    low: float
    high: float

    def covers(self, value: float) -> bool:
        """Whether ``value`` lies inside the interval, bounds included."""
        return self.low <= value <= self.high


@dataclass(frozen=True, slots=True)
class Stratum:
    """One window's contribution to a stratified estimate.

    ``successes`` of ``sample_size`` drawn reviews carried the aspect;
    ``population`` is the window's claimed review count — the finite population
    the finite-population correction runs against.
    """

    successes: int
    sample_size: int
    population: int


def wilson_interval(successes: int, sample_size: int) -> Interval:
    """The Wilson score interval — the design-naive candidate.

    Assumes the ``successes``-in-``sample_size`` draw was simple random
    sampling from an infinite population. Chosen over the Wald interval as the
    naive representative because Wald collapses at extreme shares (a zero-width
    interval at 0% or 100%), which would hand the race to the fancier methods
    by default rather than by measurement.

    >>> wilson_interval(27, 100).covers(0.27)
    True
    >>> wilson_interval(27, 100).covers(0.9)
    False
    """
    _guard_counts(successes, sample_size)
    share = successes / sample_size
    z_squared = _Z_95 * _Z_95
    denominator = 1 + z_squared / sample_size
    center = (share + z_squared / (2 * sample_size)) / denominator
    half_width = (
        _Z_95
        * math.sqrt(share * (1 - share) / sample_size + z_squared / (4 * sample_size**2))
        / denominator
    )
    return Interval(low=max(center - half_width, 0.0), high=min(center + half_width, 1.0))


def exact_bootstrap_interval(successes: int, sample_size: int) -> Interval:
    """The bootstrap-over-reviews percentile interval, computed exactly.

    The bootstrap distribution of a proportion under whole-review resampling
    is ``Binomial(sample_size, share) / sample_size``, so the 2.5th and 97.5th
    percentiles come straight from binomial quantiles — no simulation, no
    seed, no Monte Carlo error. Degenerate at the boundaries by the
    percentile bootstrap's own nature (a 0% or 100% sample share yields a
    zero-width interval); that flaw is left visible for the coverage gate to
    price rather than patched here.

    >>> exact_bootstrap_interval(50, 100)
    Interval(low=0.4, high=0.6)
    >>> exact_bootstrap_interval(0, 200)
    Interval(low=0.0, high=0.0)
    """
    _guard_counts(successes, sample_size)
    if successes in (0, sample_size):
        share = successes / sample_size
        return Interval(low=share, high=share)
    low = _binomial_quantile(sample_size, successes / sample_size, _LOWER_TAIL)
    high = _binomial_quantile(sample_size, successes / sample_size, _UPPER_TAIL)
    return Interval(low=low / sample_size, high=high / sample_size)


def stratified_interval(strata: Sequence[Stratum]) -> Interval:
    """The design-aware normal interval for a windowed (stratified) draw.

    Centers on the stratified estimate — window shares weighted by claimed
    population — with per-stratum variance under a with-replacement-free draw:
    ``(1 - n_h/N_h)`` finite-population correction times ``p_h(1-p_h)/(n_h-1)``.
    A fully-drawn stratum (sample equals population) therefore contributes
    zero variance, which is honest: a take-all window has no sampling error.
    Two degeneracies are carried openly rather than patched: a single-review
    stratum estimates zero variance (its share is 0 or 1, so ``p(1-p)`` is 0)
    — anti-conservative, and exactly the kind of flaw the coverage gate
    exists to catch; and the normal approximation itself, which the race
    judges rather than assumes. Raises on empty strata or on any stratum
    whose counts are incoherent.
    """
    if not strata:
        raise ValueError("cannot build a stratified interval from zero strata")
    for stratum in strata:
        _guard_counts(stratum.successes, stratum.sample_size)
        if stratum.sample_size > stratum.population:
            raise ValueError(
                f"stratum sampled {stratum.sample_size} from a claimed population "
                f"of {stratum.population} — more reviews than the window holds"
            )
    total_population = sum(stratum.population for stratum in strata)
    estimate = 0.0
    variance = 0.0
    for stratum in strata:
        weight = stratum.population / total_population
        share = stratum.successes / stratum.sample_size
        estimate += weight * share
        correction = 1 - stratum.sample_size / stratum.population
        spread = share * (1 - share) / max(stratum.sample_size - 1, 1)
        variance += weight * weight * correction * spread
    half_width = _Z_95 * math.sqrt(variance)
    return Interval(low=max(estimate - half_width, 0.0), high=min(estimate + half_width, 1.0))


def _guard_counts(successes: int, sample_size: int) -> None:
    """Refuse incoherent counts — a share outside its own sample is a caller bug."""
    if sample_size < 1:
        raise ValueError(f"sample_size is {sample_size} — an interval needs at least one draw")
    if not 0 <= successes <= sample_size:
        raise ValueError(f"{successes} successes out of {sample_size} draws is incoherent")


def _binomial_quantile(n: int, p: float, quantile: float) -> int:
    """The smallest ``k`` whose ``Binomial(n, p)`` CDF reaches ``quantile``.

    Log-space probability mass via ``lgamma`` keeps the terms finite at any
    ``n`` this project sees (sample sizes in the thousands); masses that
    underflow to zero are genuinely negligible against a 2.5% tail.
    """
    log_p = math.log(p)
    log_q = math.log1p(-p)
    log_n_factorial = math.lgamma(n + 1)
    cumulative = 0.0
    for k in range(n + 1):
        log_mass = (
            log_n_factorial
            - math.lgamma(k + 1)
            - math.lgamma(n - k + 1)
            + k * log_p
            + (n - k) * log_q
        )
        cumulative += math.exp(log_mass)
        if cumulative >= quantile:
            return k
    return n
