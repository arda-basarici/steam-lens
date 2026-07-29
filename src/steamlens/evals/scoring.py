"""Gold-vs-prediction scoring — the frozen bake-off metrics as pure functions.

The protocol's metrics (DESIGN's bake-off protocol, in the
choosing-the-labeler section) computed from data alone: pairing
is set intersection by label within a review, both sides resolved through
``core/normalize``'s surface index so the scorer and the candidates can never
disagree about what "pinned" means. The per-review ``ReviewTally`` is the unit
everything else is built from — aggregation sums tallies into scores, and the
bootstrap resamples *tallies* (reviews), never mentions, because mentions
within a review aren't independent. Keeping the tally per review is what makes
the CI honest and the whole module testable data-in/data-out.

Candidate-slot mentions stay out of the score on both sides per the protocol
(n=11 in gold supports no metric); they surface in the tallies for the
candidate-emission diagnostic and the qualitative overlap table.

A ratio with an empty denominator is *undefined* (``None``), never 0.0: a
resample with nothing to judge is not measured badness, and folding it into a
bootstrap distribution as 0.0 would pull the interval's lower tail toward
zero (the 2026-07-28 bootstrap-undefined ruling, in DESIGN's eval-harness
section). Reporting conventions — what a journal row shows when a statistic
is undefined — live with the callers; here a statistic just tells the truth.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from steamlens.contracts import AspectSlot, Sentiment
from steamlens.core.normalize import normalize_label


@dataclass(frozen=True, slots=True)
class ReviewTally:
    """One review's pairing outcome — the resample unit for every headline number.

    ``tp``/``fp``/``fn`` count pinned-label matches, unmatched predictions, and
    unmatched gold; ``sentiment_correct`` counts matched pairs whose predicted
    sentiment agrees with gold (denominator: ``tp``). ``pred_zero`` is an
    *honest* zero — the model parsed and emitted no mention of any kind,
    pinned or candidate; a parse failure scores as zero predictions per the
    protocol but sets ``parse_failed`` instead, so the zero-share diagnostic
    never credits a crash as a considered zero. The two zero-shares are
    deliberately asymmetric: ``gold_zero`` is pinned-only (gold's candidates
    are excluded from the scored stratum by the protocol), while a candidate
    emission from the model is a considered non-silence and so blocks
    ``pred_zero``. The candidate tuples carry each side's
    candidate normal forms for the diagnostics, unscored.

    The aspect tuples decorate the counts with *identity* — which pinned
    labels matched, which were prediction-only, which reference-only — so
    per-aspect slicing can happen downstream without re-pairing. The counts
    stay the scored truth; ``tally_review`` derives both from the same sets,
    so at the real construction site they cannot disagree. They default empty
    for hand-built tallies that only exercise the counts.
    """

    tp: int
    fp: int
    fn: int
    sentiment_correct: int
    gold_zero: bool
    pred_zero: bool
    parse_failed: bool
    gold_candidates: tuple[str, ...]
    pred_candidates: tuple[str, ...]
    matched_aspects: tuple[str, ...] = ()
    pred_only_aspects: tuple[str, ...] = ()
    gold_only_aspects: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BakeoffScores:
    """The aggregate scorecard for one candidate run over the gold slice.

    Precision and recall stay separate fields on purpose — the known failure
    mode (flash-lite's over-extraction) is directional and F1 alone would blur
    it. A ratio with an empty denominator is ``None`` — undefined, "nothing to
    judge" — never 0.0; the ``n_*`` fields expose the denominators. ``f1`` is
    ``None`` iff precision or recall is; precision and recall both *defined*
    at 0.0 give F1 0.0, the correct measured-badness limit. The share fields
    stay plain ``float``: their denominator is the tally count, and ``score``
    rejects an empty sequence outright.
    """

    n_reviews: int
    n_gold_mentions: int
    n_pred_mentions: int
    precision: float | None
    recall: float | None
    f1: float | None
    sentiment_accuracy: float | None
    zero_share_gold: float
    zero_share_pred: float
    candidate_emission_rate: float | None
    parse_failure_rate: float


@dataclass(frozen=True, slots=True)
class ConfidenceInterval:
    """A two-sided bootstrap percentile interval."""

    low: float
    high: float


def tally_review(
    gold: Sequence[tuple[str, Sentiment]],
    predicted: Sequence[tuple[str, Sentiment]],
    index: Mapping[str, str],
    *,
    parse_failed: bool = False,
) -> ReviewTally:
    """Pair one review's predictions against its gold — the atomic scoring step.

    Both sides pass through ``normalize_label`` under the same ``index``. Gold
    resolving two entries onto one pinned label is gold-side drift and raises —
    the gold file is supposed to be canonical and duplicate-free, so a
    collision means the artifact and the ontology disagree. Predictions that
    collapse onto one pinned label (distinct raw phrasings, one canonical
    label) count that label once — set semantics — and its sentiment is
    correct only if *all* collapsed copies agree with gold: a self-contradicting
    prediction never earns the point. A ``parse_failed`` review must carry no
    predictions (it scores as zero by construction); passing both is a caller
    bug and raises.
    """
    if parse_failed and predicted:
        raise ValueError("a parse-failed review cannot carry predictions")

    gold_pinned: dict[str, Sentiment] = {}
    gold_candidates: list[str] = []
    for label, sentiment in gold:
        resolved = normalize_label(label, index)
        if resolved.slot is AspectSlot.CANDIDATE:
            gold_candidates.append(resolved.aspect)
        elif resolved.aspect in gold_pinned:
            raise ValueError(
                f"gold labels collide on pinned {resolved.aspect!r} — gold drifted "
                "from the ontology's surface forms"
            )
        else:
            gold_pinned[resolved.aspect] = sentiment

    pred_pinned: dict[str, set[Sentiment]] = {}
    pred_candidates: list[str] = []
    for label, sentiment in predicted:
        resolved = normalize_label(label, index)
        if resolved.slot is AspectSlot.CANDIDATE:
            pred_candidates.append(resolved.aspect)
        else:
            pred_pinned.setdefault(resolved.aspect, set()).add(sentiment)

    matched = gold_pinned.keys() & pred_pinned.keys()
    pred_only = pred_pinned.keys() - gold_pinned.keys()
    gold_only = gold_pinned.keys() - pred_pinned.keys()
    sentiment_correct = sum(
        1 for label in matched if pred_pinned[label] == {gold_pinned[label]}
    )
    return ReviewTally(
        tp=len(matched),
        fp=len(pred_only),
        fn=len(gold_only),
        sentiment_correct=sentiment_correct,
        gold_zero=not gold_pinned,
        pred_zero=not parse_failed and not pred_pinned and not pred_candidates,
        parse_failed=parse_failed,
        gold_candidates=tuple(sorted(set(gold_candidates))),
        pred_candidates=tuple(sorted(set(pred_candidates))),
        matched_aspects=tuple(sorted(matched)),
        pred_only_aspects=tuple(sorted(pred_only)),
        gold_only_aspects=tuple(sorted(gold_only)),
    )


def score(tallies: Sequence[ReviewTally]) -> BakeoffScores:
    """Aggregate per-review tallies into the candidate's scorecard.

    Pure summation over tallies — no re-pairing — so the same function serves
    the headline numbers and every bootstrap resample identically. An empty
    tally sequence is a caller bug (nothing was scored) and raises rather than
    minting a scorecard of zeros.
    """
    if not tallies:
        raise ValueError("cannot score an empty tally sequence")
    tp = sum(t.tp for t in tallies)
    fp = sum(t.fp for t in tallies)
    fn = sum(t.fn for t in tallies)
    n_candidates = sum(len(t.pred_candidates) for t in tallies)
    n_emitted = tp + fp + n_candidates
    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    if precision is None or recall is None:
        f1 = None
    elif precision + recall == 0:
        # both defined at 0.0 is measured badness, not "nothing to judge" —
        # F1's limit there is 0.0, not undefined
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)
    return BakeoffScores(
        n_reviews=len(tallies),
        n_gold_mentions=tp + fn,
        n_pred_mentions=tp + fp,
        precision=precision,
        recall=recall,
        f1=f1,
        sentiment_accuracy=_ratio(sum(t.sentiment_correct for t in tallies), tp),
        zero_share_gold=sum(t.gold_zero for t in tallies) / len(tallies),
        zero_share_pred=sum(t.pred_zero for t in tallies) / len(tallies),
        candidate_emission_rate=_ratio(n_candidates, n_emitted),
        parse_failure_rate=sum(t.parse_failed for t in tallies) / len(tallies),
    )


def bootstrap_ci(
    tallies: Sequence[ReviewTally],
    statistic: Callable[[Sequence[ReviewTally]], float | None],
    *,
    n_resamples: int = 10_000,
    seed: int,
) -> ConfidenceInterval:
    """The 95% bootstrap percentile interval of ``statistic`` over the reviews.

    Resamples whole reviews (tallies) with replacement — the protocol's unit of
    independence — and reads the 2.5th/97.5th percentiles of the resampled
    statistic by nearest rank. ``seed`` is required, never defaulted: the
    interval lands in a manifest, and a manifest number must be regenerable
    from its recorded inputs.

    A resample where the statistic is undefined (``None`` — nothing to judge)
    is dropped, and the percentiles read over the defined draws: folding it in
    as 0.0 would count "nothing to score" as measured badness and bias the
    lower tail. Past ``MAX_UNDEFINED_SHARE`` the interval itself stops being
    honest — the input is too sparse for this statistic — and this raises
    rather than journal noise wearing a certified metric's name. The RNG
    stream never depends on the drops, so digits move only where an undefined
    draw actually occurred.
    """
    if not tallies:
        raise ValueError("cannot bootstrap an empty tally sequence")
    rng = random.Random(seed)
    resampled = [
        statistic(rng.choices(tallies, k=len(tallies))) for _ in range(n_resamples)
    ]
    values = sorted(v for v in resampled if v is not None)
    _require_mostly_defined(n_resamples - len(values), n_resamples)
    return ConfidenceInterval(
        low=values[round(0.025 * (len(values) - 1))],
        high=values[round(0.975 * (len(values) - 1))],
    )


def paired_bootstrap_ci(
    tallies_a: Sequence[ReviewTally],
    tallies_b: Sequence[ReviewTally],
    statistic: Callable[[Sequence[ReviewTally]], float | None],
    *,
    n_resamples: int = 10_000,
    seed: int,
) -> ConfidenceInterval:
    """The 95% bootstrap interval of ``statistic(a) − statistic(b)``, paired.

    Every bake-off run scores the *same* gold reviews, so comparing two runs
    through their separate intervals overstates the uncertainty of the gap —
    review difficulty is shared, not independent. Here each resample draws one
    set of review indices and applies it to *both* runs, so the interval is on
    the difference itself. A gap whose interval excludes zero is real at the
    95% level; the two runs must therefore cover the same reviews in the same
    order, and mismatched lengths raise rather than silently pair wrong.

    A draw where either side's statistic is undefined has no defined
    difference — dropped and floored exactly as in ``bootstrap_ci``, same
    reasoning, same determinism guarantee.
    """
    if not tallies_a:
        raise ValueError("cannot bootstrap an empty tally sequence")
    if len(tallies_a) != len(tallies_b):
        raise ValueError(
            f"paired runs must cover the same reviews: {len(tallies_a)} vs {len(tallies_b)}"
        )
    rng = random.Random(seed)
    n = len(tallies_a)
    values: list[float] = []
    n_undefined = 0
    for _ in range(n_resamples):
        idx = [rng.randrange(n) for _ in range(n)]
        value_a = statistic([tallies_a[i] for i in idx])
        value_b = statistic([tallies_b[i] for i in idx])
        if value_a is None or value_b is None:
            n_undefined += 1
        else:
            values.append(value_a - value_b)
    _require_mostly_defined(n_undefined, n_resamples)
    values.sort()
    return ConfidenceInterval(
        low=values[round(0.025 * (len(values) - 1))],
        high=values[round(0.975 * (len(values) - 1))],
    )


MAX_UNDEFINED_SHARE: Final = 0.01
"""The bootstrap's sparsity floor: the largest share of undefined resamples an
interval may silently drop. A few undefined draws in 10,000 don't change what
the interval claims; past this, the input is too sparse for the statistic and
the honest output is no interval at all (the caller's slice-skip / raise
policy takes over), not a wide one."""


def _require_mostly_defined(n_undefined: int, n_resamples: int) -> None:
    """Raise when undefined draws exceed the sparsity floor — no interval over noise."""
    if n_undefined > n_resamples * MAX_UNDEFINED_SHARE:
        raise ValueError(
            f"{n_undefined} of {n_resamples} resamples have an undefined statistic "
            f"(> {MAX_UNDEFINED_SHARE:.0%}) — the input is too sparse to bootstrap"
        )


def _ratio(numerator: float, denominator: float) -> float | None:
    """The quotient, or ``None`` on an empty denominator — undefined, never 0.0."""
    return numerator / denominator if denominator else None
