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
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from steamlens.contracts import Sentiment
from steamlens.core.normalize import build_surface_index
from steamlens.evals import (
    bootstrap_ci,
    load_gold,
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
    assert records[0].mentions[0].aspect == "combat"
    assert records[0].mentions[0].sentiment is Sentiment.POSITIVE


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


def test_score_reports_zero_ratios_with_exposed_denominators() -> None:
    """All-failed run: every ratio 0.0, and the n_* fields say why."""
    tallies = [tally_review(gold=[("combat", _POS)], predicted=[], index=_INDEX, parse_failed=True)]
    scores = score(tallies)
    assert scores.precision == 0.0
    assert scores.n_pred_mentions == 0
    assert scores.parse_failure_rate == 1.0


def test_score_rejects_an_empty_tally_sequence() -> None:
    with pytest.raises(ValueError, match="empty"):
        score([])


# --- bootstrap_ci ----------------------------------------------------------------


def test_bootstrap_is_deterministic_under_its_seed() -> None:
    tallies = [
        tally_review(gold=[("combat", _POS)], predicted=[("combat", _POS)], index=_INDEX),
        tally_review(gold=[("performance", _NEG)], predicted=[], index=_INDEX),
        tally_review(gold=[], predicted=[], index=_INDEX),
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
