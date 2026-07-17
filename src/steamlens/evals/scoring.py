"""Gold-vs-prediction scoring — the frozen bake-off metrics as pure functions.

The protocol's metrics (DESIGN's C0 entries) computed from data alone: pairing
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
"""

from __future__ import annotations

import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from steamlens.contracts import AspectSlot, Sentiment
from steamlens.core.normalize import normalize_label


@dataclass(frozen=True, slots=True)
class ReviewTally:
    """One review's pairing outcome — the resample unit for every headline number.

    ``tp``/``fp``/``fn`` count pinned-label matches, unmatched predictions, and
    unmatched gold; ``sentiment_correct`` counts matched pairs whose predicted
    sentiment agrees with gold (denominator: ``tp``). ``pred_zero`` is an
    *honest* zero — the model parsed and said "no pinned aspects"; a parse
    failure scores as zero predictions per the protocol but sets
    ``parse_failed`` instead, so the zero-share diagnostic never credits a
    crash as a considered zero. The candidate tuples carry each side's
    candidate normal forms for the diagnostics, unscored.
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


@dataclass(frozen=True, slots=True)
class BakeoffScores:
    """The aggregate scorecard for one candidate run over the gold slice.

    Precision and recall stay separate fields on purpose — the known failure
    mode (flash-lite's over-extraction) is directional and F1 alone would blur
    it. Ratios with an empty denominator report 0.0; the ``n_*`` fields expose
    the denominators so a zero is never mistaken for measured badness.
    """

    n_reviews: int
    n_gold_mentions: int
    n_pred_mentions: int
    precision: float
    recall: float
    f1: float
    sentiment_accuracy: float
    zero_share_gold: float
    zero_share_pred: float
    candidate_emission_rate: float
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
    sentiment_correct = sum(
        1 for label in matched if pred_pinned[label] == {gold_pinned[label]}
    )
    return ReviewTally(
        tp=len(matched),
        fp=len(pred_pinned.keys() - gold_pinned.keys()),
        fn=len(gold_pinned.keys() - pred_pinned.keys()),
        sentiment_correct=sentiment_correct,
        gold_zero=not gold_pinned,
        pred_zero=not parse_failed and not pred_pinned and not pred_candidates,
        parse_failed=parse_failed,
        gold_candidates=tuple(sorted(set(gold_candidates))),
        pred_candidates=tuple(sorted(set(pred_candidates))),
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
    return BakeoffScores(
        n_reviews=len(tallies),
        n_gold_mentions=tp + fn,
        n_pred_mentions=tp + fp,
        precision=precision,
        recall=recall,
        f1=_ratio(2 * precision * recall, precision + recall),
        sentiment_accuracy=_ratio(sum(t.sentiment_correct for t in tallies), tp),
        zero_share_gold=_ratio(sum(t.gold_zero for t in tallies), len(tallies)),
        zero_share_pred=_ratio(sum(t.pred_zero for t in tallies), len(tallies)),
        candidate_emission_rate=_ratio(n_candidates, n_emitted),
        parse_failure_rate=_ratio(sum(t.parse_failed for t in tallies), len(tallies)),
    )


def bootstrap_ci(
    tallies: Sequence[ReviewTally],
    statistic: Callable[[Sequence[ReviewTally]], float],
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
    """
    if not tallies:
        raise ValueError("cannot bootstrap an empty tally sequence")
    rng = random.Random(seed)
    values = sorted(
        statistic(rng.choices(tallies, k=len(tallies))) for _ in range(n_resamples)
    )
    return ConfidenceInterval(
        low=values[round(0.025 * (n_resamples - 1))],
        high=values[round(0.975 * (n_resamples - 1))],
    )


def _ratio(numerator: float, denominator: float) -> float:
    """The quotient, or 0.0 on an empty denominator — exposed via the n_* fields."""
    return numerator / denominator if denominator else 0.0
