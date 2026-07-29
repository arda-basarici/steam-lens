"""Behavioral claims on the eval harness — the gold loader and the scoring core.

The loader claims are boundary-validation claims (bad artifacts die loudly at
the door); the scoring claims pin the pairing semantics ruled in DESIGN's C0
scorer-design entry (set intersection by label, one resolution authority,
honest zeros, conservative sentiment on collapsed duplicates). The suite ends
with the real-artifact round-trip: the actual minted gold file against the
actual v1 ontology, asserting the mint's own published facts — 250 records,
351 mentions, 11 candidates — and the provenance handshake between the gold
records' ontology pin and the packaged artifact.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import pytest

from steamlens.contracts import Sentiment
from steamlens.core.normalize import build_surface_index
from steamlens.evals import (
    ReviewTally,
    bootstrap_ci,
    load_gold,
    paired_bootstrap_ci,
    score,
    tally_review,
)
from steamlens.ontology import load_ontology, load_ontology_version

_GOLD_PATH = Path(__file__).resolve().parent.parent / "eval" / "gold" / "gold.jsonl"

# A minimal index in match-key form: pinned vocabulary for the unit tests.
_INDEX = {"combat": "combat", "voice acting": "voice_acting", "performance": "performance"}

_POS = Sentiment.POSITIVE
_NEG = Sentiment.NEGATIVE


def _gold_line(
    review_id: str = "r1", mentions: Sequence[Mapping[str, object]] | None = None
) -> dict[str, object]:
    return {
        "review_id": review_id,
        "app_id": "10",
        "text": "some review text",
        "mentions": list(mentions) if mentions is not None else [],
        "instructions_version": "gold-instructions-v1",
        "ontology_version": "v1",
        "ontology_content_hash": "abc123",
    }


def _write_gold(tmp_path: Path, lines: list[dict[str, object]]) -> Path:
    path = tmp_path / "gold.jsonl"
    path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")
    return path


# --- load_gold -------------------------------------------------------------------


def test_load_gold_round_trips_a_valid_record(tmp_path: Path) -> None:
    mention = {"aspect": "combat", "sentiment": "positive", "evidence": "combat is great"}
    records = load_gold(_write_gold(tmp_path, [_gold_line(mentions=[mention])]))
    assert len(records) == 1
    assert records[0].review_id == "r1"
    assert records[0].app_id == 10  # parsed to the int every scope consumer speaks
    assert records[0].mentions[0].aspect == "combat"
    assert records[0].mentions[0].sentiment is Sentiment.POSITIVE


def test_load_gold_rejects_a_non_digit_app_id(tmp_path: Path) -> None:
    """A malformed app id must error, not silently fail a scope comparison."""
    line = _gold_line()
    line["app_id"] = "730.0"
    with pytest.raises(ValueError, match="app_id"):
        load_gold(_write_gold(tmp_path, [line]))


def test_load_gold_accepts_an_absent_evidence_as_none(tmp_path: Path) -> None:
    """Evidence is encouraged, never required — a mention without one is intact."""
    mention = {"aspect": "combat", "sentiment": "negative"}
    records = load_gold(_write_gold(tmp_path, [_gold_line(mentions=[mention])]))
    assert records[0].mentions[0].evidence is None


def test_load_gold_rejects_a_duplicate_review_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="duplicate review_id"):
        load_gold(_write_gold(tmp_path, [_gold_line("r1"), _gold_line("r1")]))


def test_load_gold_rejects_a_duplicate_aspect_within_a_review(tmp_path: Path) -> None:
    """The set-pairing precondition dies at the door, not as a miscount later."""
    mentions = [
        {"aspect": "combat", "sentiment": "positive"},
        {"aspect": "combat", "sentiment": "negative"},
    ]
    with pytest.raises(ValueError, match="duplicate aspect"):
        load_gold(_write_gold(tmp_path, [_gold_line(mentions=mentions)]))


def test_load_gold_rejects_an_unknown_sentiment(tmp_path: Path) -> None:
    mention = {"aspect": "combat", "sentiment": "ecstatic"}
    with pytest.raises(ValueError, match="ecstatic"):
        load_gold(_write_gold(tmp_path, [_gold_line(mentions=[mention])]))


def test_load_gold_rejects_a_missing_field(tmp_path: Path) -> None:
    line = _gold_line()
    del line["ontology_content_hash"]
    with pytest.raises(ValueError, match="ontology_content_hash"):
        load_gold(_write_gold(tmp_path, [line]))


def test_load_gold_rejects_an_empty_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="empty"):
        load_gold(_write_gold(tmp_path, []))


# --- tally_review ----------------------------------------------------------------


def test_tally_pairs_by_label_and_scores_sentiment_on_matches() -> None:
    """One match (sentiment right), one miss, one false alarm — the atomic case."""
    tally = tally_review(
        gold=[("combat", _POS), ("voice_acting", _NEG)],
        predicted=[("combat", _POS), ("performance", _NEG)],
        index=_INDEX,
    )
    assert (tally.tp, tally.fp, tally.fn) == (1, 1, 1)
    assert tally.sentiment_correct == 1
    assert not tally.gold_zero
    assert not tally.pred_zero


def test_tally_counts_a_wrong_sentiment_as_matched_but_incorrect() -> None:
    """Polarity errors never double-punish detection: the pair still matches."""
    tally = tally_review(
        gold=[("combat", _POS)], predicted=[("combat", _NEG)], index=_INDEX
    )
    assert tally.tp == 1
    assert tally.sentiment_correct == 0


def test_tally_excludes_candidates_from_the_score_on_both_sides() -> None:
    """Candidate-slot mentions are diagnostics, not score — n=11 supports no metric."""
    tally = tally_review(
        gold=[("ship building", _POS)],
        predicted=[("Crafting Depth", _NEG)],
        index=_INDEX,
    )
    assert (tally.tp, tally.fp, tally.fn) == (0, 0, 0)
    assert tally.gold_candidates == ("ship building",)
    assert tally.pred_candidates == ("crafting depth",)
    assert tally.gold_zero
    assert not tally.pred_zero


def test_tally_resolves_both_sides_through_the_one_index() -> None:
    """Surface variants fold onto the canonical label — the two sides can't
    disagree about what pinned means."""
    tally = tally_review(
        gold=[("voice_acting", _POS)], predicted=[(" Voice-Acting ", _POS)], index=_INDEX
    )
    assert (tally.tp, tally.fp, tally.fn) == (1, 0, 0)
    assert tally.sentiment_correct == 1


def test_tally_collapses_prediction_phrasings_conservatively() -> None:
    """Two phrasings, one canonical label: one tp, and the sentiment point is
    earned only when every collapsed copy agrees with gold."""
    agreeing = tally_review(
        gold=[("voice_acting", _POS)],
        predicted=[("voice acting", _POS), ("Voice-Acting", _POS)],
        index=_INDEX,
    )
    assert (agreeing.tp, agreeing.sentiment_correct) == (1, 1)
    conflicted = tally_review(
        gold=[("voice_acting", _POS)],
        predicted=[("voice acting", _POS), ("Voice-Acting", _NEG)],
        index=_INDEX,
    )
    assert (conflicted.tp, conflicted.sentiment_correct) == (1, 0)


def test_tally_raises_on_gold_side_pinned_collision() -> None:
    """Gold resolving twice onto one pinned label is drift, not data."""
    with pytest.raises(ValueError, match="drifted"):
        tally_review(
            gold=[("voice acting", _POS), ("voice_acting", _NEG)],
            predicted=[],
            index=_INDEX,
        )


def test_tally_separates_honest_zero_from_parse_failure() -> None:
    """A parsed empty is a considered zero; a crash is not — the zero-share
    diagnostic must never credit failures."""
    honest = tally_review(gold=[], predicted=[], index=_INDEX)
    assert honest.pred_zero and not honest.parse_failed
    failed = tally_review(gold=[], predicted=[], index=_INDEX, parse_failed=True)
    assert failed.parse_failed and not failed.pred_zero
    assert failed.gold_zero


def test_tally_rejects_a_failed_review_carrying_predictions() -> None:
    with pytest.raises(ValueError, match="parse-failed"):
        tally_review(gold=[], predicted=[("combat", _POS)], index=_INDEX, parse_failed=True)


def test_tally_carries_aspect_identity_consistent_with_its_counts() -> None:
    """The aspect tuples name exactly the labels behind tp/fp/fn — collapsed
    phrasings once, candidates out — so per-aspect slicing never re-pairs."""
    tally = tally_review(
        gold=[("combat", _POS), ("voice acting", _NEG)],
        predicted=[("combat", _NEG), ("Combat", _POS), ("performance", _NEG), ("crafting", _POS)],
        index=_INDEX,
    )
    assert tally.matched_aspects == ("combat",)
    assert tally.pred_only_aspects == ("performance",)
    assert tally.gold_only_aspects == ("voice_acting",)
    assert (tally.tp, tally.fp, tally.fn) == (1, 1, 1)


# --- score -----------------------------------------------------------------------


def test_score_aggregates_the_hand_computed_fixture() -> None:
    """Two reviews, worked by hand: tp=2 fp=1 fn=2 → P=2/3, R=1/2, one of two
    matched sentiments right, one honest zero of two reviews."""
    tallies = [
        tally_review(
            gold=[("combat", _POS), ("voice_acting", _NEG), ("performance", _POS)],
            predicted=[("combat", _POS), ("voice_acting", _POS)],
            index=_INDEX,
        ),
        tally_review(gold=[], predicted=[("performance", _NEG)], index=_INDEX),
    ]
    scores = score(tallies)
    assert scores.n_reviews == 2
    assert (scores.n_gold_mentions, scores.n_pred_mentions) == (3, 3)
    assert scores.precision == pytest.approx(2 / 3)
    assert scores.recall == pytest.approx(2 / 3)
    assert scores.f1 == pytest.approx(2 / 3)
    assert scores.sentiment_accuracy == pytest.approx(1 / 2)
    assert scores.zero_share_gold == pytest.approx(1 / 2)
    assert scores.zero_share_pred == 0.0
    assert scores.parse_failure_rate == 0.0


def test_score_counts_candidate_emission_against_all_emitted_mentions() -> None:
    tallies = [
        tally_review(
            gold=[("combat", _POS)],
            predicted=[("combat", _POS), ("ship building", _POS)],
            index=_INDEX,
        )
    ]
    assert score(tallies).candidate_emission_rate == pytest.approx(1 / 2)


def test_score_reports_undefined_ratios_as_none_with_exposed_denominators() -> None:
    """All-failed run: nothing was predicted, so precision has nothing to
    measure — None, not 0.0 (recall keeps its defined 0.0: gold mentions
    existed and were missed). The n_* fields say why."""
    tallies = [tally_review(gold=[("combat", _POS)], predicted=[], index=_INDEX, parse_failed=True)]
    scores = score(tallies)
    assert scores.precision is None
    assert scores.recall == 0.0
    assert scores.f1 is None
    assert scores.n_pred_mentions == 0
    assert scores.parse_failure_rate == 1.0


def test_score_says_undefined_where_there_is_nothing_to_judge() -> None:
    """The bootstrap-undefined ruling's core claims, one denominator at a time:
    prediction-only → recall and sentiment undefined (no gold, no matches);
    empty-empty → every mention ratio undefined, including candidate emission."""
    pred_only = score([tally_review(gold=[], predicted=[("combat", _POS)], index=_INDEX)])
    assert pred_only.precision == 0.0
    assert pred_only.recall is None
    assert pred_only.f1 is None
    assert pred_only.sentiment_accuracy is None

    silent = score([tally_review(gold=[], predicted=[], index=_INDEX)])
    assert silent.precision is None
    assert silent.recall is None
    assert silent.f1 is None
    assert silent.candidate_emission_rate is None
    assert silent.zero_share_pred == 1.0  # the share fields never go undefined


def test_f1_is_zero_not_none_when_both_components_are_defined_zeros() -> None:
    """P=0 and R=0 both *measured* (predictions and gold exist, none match) is
    total badness, not "nothing to judge" — F1's limit there is 0.0."""
    scores = score(
        [tally_review(gold=[("combat", _POS)], predicted=[("performance", _NEG)], index=_INDEX)]
    )
    assert scores.precision == 0.0
    assert scores.recall == 0.0
    assert scores.f1 == 0.0


def test_score_rejects_an_empty_tally_sequence() -> None:
    with pytest.raises(ValueError, match="empty"):
        score([])


# --- bootstrap_ci ----------------------------------------------------------------


def test_bootstrap_is_deterministic_under_its_seed() -> None:
    # every tally carries gold and predictions so F1 is defined on every
    # resample — undefined-draw handling has its own tests below
    tallies = [
        tally_review(gold=[("combat", _POS)], predicted=[("combat", _POS)], index=_INDEX),
        tally_review(gold=[("performance", _NEG)], predicted=[("combat", _POS)], index=_INDEX),
        tally_review(
            gold=[("voice acting", _NEG), ("combat", _POS)],
            predicted=[("combat", _POS)],
            index=_INDEX,
        ),
    ]
    first = bootstrap_ci(tallies, lambda t: score(t).f1, n_resamples=200, seed=7)
    again = bootstrap_ci(tallies, lambda t: score(t).f1, n_resamples=200, seed=7)
    assert first == again
    assert 0.0 <= first.low <= first.high <= 1.0


def test_bootstrap_collapses_on_identical_reviews() -> None:
    """Resampling identical tallies moves nothing — the interval is the point."""
    tallies = [
        tally_review(gold=[("combat", _POS)], predicted=[("combat", _POS)], index=_INDEX)
    ] * 5
    interval = bootstrap_ci(tallies, lambda t: score(t).f1, n_resamples=50, seed=1)
    assert interval.low == interval.high == 1.0


def test_bootstrap_rejects_an_empty_tally_sequence() -> None:
    with pytest.raises(ValueError, match="empty"):
        bootstrap_ci([], lambda t: 0.0, n_resamples=10, seed=1)


# --- undefined resamples (the bootstrap-undefined ruling, DESIGN 2026-07-28) ------


def _scripted(values: Sequence[float | None]) -> Callable[[Sequence[ReviewTally]], float | None]:
    """A statistic that ignores its resample and replays ``values`` call by call.

    The bootstrap contract under test is about the *values* stream (drop the
    undefined, percentile the rest), so scripting the stream directly makes the
    expected interval hand-computable — deriving it through real tallies would
    re-implement the resampler in the test.
    """
    replay = iter(values)
    return lambda _tallies: next(replay)


_ONE_TALLY = [
    tally_review(gold=[("combat", _POS)], predicted=[("combat", _POS)], index=_INDEX)
]


def test_bootstrap_reads_percentiles_over_the_defined_draws_only() -> None:
    """One undefined draw of 100 is dropped, and the percentile ranks re-read
    over the 99 defined values — visibly shifting the low bound against the
    same stream with the draw defined. Folding None in as 0.0 (the old
    convention) would have crushed the low bound to 0.0 instead."""
    with_gap: list[float | None] = [float(i) for i in range(1, 101)]
    with_gap[2] = None  # the third draw is "nothing to judge"
    interval = bootstrap_ci(_ONE_TALLY, _scripted(with_gap), n_resamples=100, seed=1)
    assert (interval.low, interval.high) == (4.0, 98.0)

    dense = [float(i) for i in range(1, 101)]
    baseline = bootstrap_ci(_ONE_TALLY, _scripted(dense), n_resamples=100, seed=1)
    assert (baseline.low, baseline.high) == (3.0, 98.0)


def test_bootstrap_raises_past_the_sparsity_floor() -> None:
    """Two undefined draws of 100 exceed the 1% floor — the honest output is
    no interval, not a wide one."""
    values: list[float | None] = [float(i) for i in range(1, 101)]
    values[10] = values[20] = None
    with pytest.raises(ValueError, match="too sparse"):
        bootstrap_ci(_ONE_TALLY, _scripted(values), n_resamples=100, seed=1)


def test_bootstrap_refuses_a_sparse_slice_through_a_real_statistic() -> None:
    """The reachable production case in miniature: sentiment accuracy over a
    slice where matches are rare — resamples without a single matched pair
    have nothing to judge, and there are far too many of them to drop."""
    tallies = [
        tally_review(gold=[("combat", _POS)], predicted=[("combat", _POS)], index=_INDEX),
        *(
            tally_review(gold=[("performance", _NEG)], predicted=[], index=_INDEX)
            for _ in range(4)
        ),
    ]
    with pytest.raises(ValueError, match="too sparse"):
        bootstrap_ci(
            tallies, lambda t: score(t).sentiment_accuracy, n_resamples=200, seed=7
        )


def test_paired_bootstrap_drops_draws_where_either_side_is_undefined() -> None:
    """The paired loop calls the statistic twice per draw (a then b); a None on
    either side drops that draw's difference. One dropped draw of 200 stays
    under the floor and leaves the identical-runs interval at exactly [0, 0]."""
    values: list[float | None] = [1.0] * 400
    values[1] = None  # resample 1's b-side
    interval = paired_bootstrap_ci(
        _ONE_TALLY, _ONE_TALLY, _scripted(values), n_resamples=200, seed=3
    )
    assert (interval.low, interval.high) == (0.0, 0.0)

    sparse: list[float | None] = [1.0] * 400
    sparse[1] = sparse[3] = sparse[5] = None  # three dropped draws breach 1% of 200
    with pytest.raises(ValueError, match="too sparse"):
        paired_bootstrap_ci(_ONE_TALLY, _ONE_TALLY, _scripted(sparse), n_resamples=200, seed=3)


# --- paired_bootstrap_ci ---------------------------------------------------------


def test_paired_bootstrap_identical_runs_gap_is_zero() -> None:
    """A run compared against itself: the gap interval is exactly [0, 0]."""
    tallies = tuple(
        tally_review(gold=[("combat", _POS)], predicted=[("combat", _POS)], index=_INDEX)
        for _ in range(4)
    )
    interval = paired_bootstrap_ci(
        tallies, tallies, lambda t: score(t).f1, n_resamples=50, seed=3
    )
    assert interval.low == interval.high == 0.0


def test_paired_bootstrap_detects_a_uniform_gap() -> None:
    """A perfect run vs an all-wrong run (predictions exist, none match — F1 a
    measured 0.0, not undefined): every resample shows the same +1 F1 gap."""
    perfect = tuple(
        tally_review(gold=[("combat", _POS)], predicted=[("combat", _POS)], index=_INDEX)
        for _ in range(5)
    )
    all_wrong = tuple(
        tally_review(gold=[("combat", _POS)], predicted=[("performance", _NEG)], index=_INDEX)
        for _ in range(5)
    )
    interval = paired_bootstrap_ci(
        perfect, all_wrong, lambda t: score(t).f1, n_resamples=50, seed=3
    )
    assert interval.low == interval.high == 1.0


def test_paired_bootstrap_is_deterministic_under_its_seed() -> None:
    a = tuple(
        tally_review(gold=[("combat", _POS)], predicted=[("combat", _POS)], index=_INDEX)
        for _ in range(3)
    )
    # b's tallies all carry gold and predictions — F1 defined on every draw
    b = (
        tally_review(gold=[("combat", _POS)], predicted=[("performance", _NEG)], index=_INDEX),
        tally_review(gold=[("performance", _NEG)], predicted=[("performance", _NEG)], index=_INDEX),
        tally_review(gold=[("voice acting", _POS)], predicted=[("combat", _POS)], index=_INDEX),
    )
    first = paired_bootstrap_ci(a, b, lambda t: score(t).f1, n_resamples=200, seed=7)
    again = paired_bootstrap_ci(a, b, lambda t: score(t).f1, n_resamples=200, seed=7)
    assert first == again


def test_paired_bootstrap_rejects_mismatched_lengths() -> None:
    """Different review counts can't be the same slice — pairing would be silent lies."""
    tallies = (tally_review(gold=[("combat", _POS)], predicted=[], index=_INDEX),)
    with pytest.raises(ValueError, match="same reviews"):
        paired_bootstrap_ci(tallies, tallies * 2, lambda t: score(t).f1, n_resamples=10, seed=1)


# --- the real artifacts, round-tripped -------------------------------------------


def test_the_minted_gold_scores_cleanly_against_the_v1_ontology() -> None:
    """The whole chain on the real files: the loader admits the mint, the
    provenance handshake holds, and resolution reproduces the mint's published
    facts — 250 records, 351 mentions, 18 candidate mentions across the
    manifest's 11 distinct labels, zero collisions."""
    records = load_gold(_GOLD_PATH)
    assert len(records) == 250
    assert sum(len(r.mentions) for r in records) == 351

    stamp = load_ontology_version()
    assert {r.ontology_version for r in records} == {stamp.version}
    assert {r.ontology_content_hash for r in records} == {stamp.content_hash}

    index = build_surface_index(load_ontology())
    tallies = [
        tally_review(
            gold=[(m.aspect, m.sentiment) for m in record.mentions],
            predicted=[],
            index=index,
        )
        for record in records
    ]
    candidate_mentions = [c for t in tallies for c in t.gold_candidates]
    assert len(candidate_mentions) == 18
    assert len(set(candidate_mentions)) == 11
    assert sum(t.tp + t.fn for t in tallies) == 351 - 18
