"""Behavioral claims on the D2a certification shell — scope, accounting, provenance.

The load-bearing claims: the out-of-scope rule excludes without penalizing
(a skipped game shrinks ``n_scored_reviews``, never scores as failure), a
durable failure mark *does* score as a parse failure, an unaccounted in-scope
review dies loud instead of silently shrinking the denominator, and the
minted record is deterministic under its seed and survives the journal
round-trip — the regenerability promise, tested end to end.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from steamlens.contracts import (
    AspectMention,
    AspectSlot,
    ClassifierVersions,
    Origin,
    Provenance,
    ReferenceKind,
    Review,
    ReviewClassification,
    Sentiment,
)
from steamlens.core.normalize import build_surface_index
from steamlens.evals import load_gold
from steamlens.evals.certify import JUDGE_SCORER, certify_pool, pool_tallies
from steamlens.ontology import load_ontology, load_ontology_version
from steamlens.store import Store

_NOON = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
_STAMP = load_ontology_version(None)
# The packaged (v1) ontology drives the tests: certify derives the versions
# triple's ontology slot from the artifact it loads, and v1 needs no path.
_VERSIONS = ClassifierVersions(
    model_version="model-t", prompt_version="prompt-t", ontology_version=_STAMP.version
)
_INDEX = build_surface_index(load_ontology(None))


def _review(review_id: str, app_id: int) -> Review:
    return Review(
        review_id=review_id,
        app_id=app_id,
        created_at=_NOON,
        language="english",
        text=f"review {review_id}",
        voted_up=True,
    )


def _mention(aspect: str, sentiment: Sentiment) -> AspectMention:
    return AspectMention(
        aspect=aspect, slot=AspectSlot.PINNED, sentiment=sentiment, evidence=None
    )


def _gold_line(review_id: str, app_id: str, mentions: list[dict[str, object]]) -> str:
    return json.dumps(
        {
            "review_id": review_id,
            "app_id": app_id,
            "text": f"review {review_id}",
            "mentions": mentions,
            "instructions_version": "gold-v1",
            "ontology_version": _STAMP.version,
            "ontology_content_hash": _STAMP.content_hash,
        }
    )


def _write_gold(path: Path, lines: list[str]) -> Path:
    gold_path = path / "gold.jsonl"
    gold_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return gold_path


def _pool_store(envelopes: dict[str, tuple[AspectMention, ...]], apps: dict[str, int]) -> Store:
    """An in-memory pool holding one envelope per entry, under ``_VERSIONS``."""
    store = Store(":memory:")
    store.reviews.put_many([_review(rid, app) for rid, app in apps.items()])
    run = Provenance(
        run_id="c1-test", code_version="testsha", created_at=_NOON, config_hash="cfg"
    )
    store.labels.record_run(run)
    for review_id, mentions in envelopes.items():
        store.labels.put(
            ReviewClassification(
                review_id=review_id,
                origin=Origin.SURVEY,
                versions=_VERSIONS,
                run=run,
                mentions=mentions,
            )
        )
    return store


# Three in-scope reviews (a hit, a miss, a both-empty) and one from the
# excluded game — the smallest pool that exercises every scope branch.
_APPS = {"r1": 10, "r2": 10, "r3": 20, "r-cs2": 730}
_GOLD_LINES = [
    _gold_line("r1", "10", [{"aspect": "gameplay", "sentiment": "positive"}]),
    _gold_line("r2", "10", [{"aspect": "performance", "sentiment": "negative"}]),
    _gold_line("r3", "20", []),
    _gold_line("r-cs2", "730", [{"aspect": "gameplay", "sentiment": "positive"}]),
]
_ENVELOPES = {
    "r1": (_mention("gameplay", Sentiment.POSITIVE),),
    "r2": (),  # the model found nothing where gold has a mention
    "r3": (),
}


class TestPoolTallies:
    """The scope rule and the three ways a gold review meets the pool."""

    def test_excluded_game_is_skipped_not_failed(self, tmp_path: Path) -> None:
        gold = load_gold(_write_gold(tmp_path, _GOLD_LINES))
        store = _pool_store(_ENVELOPES, _APPS)
        try:
            tallies = pool_tallies(store, gold, _INDEX, _VERSIONS)
        finally:
            store.close()
        assert len(tallies) == 3  # r-cs2 is out of scope: absent, not a zero row
        assert not any(t.parse_failed for t in tallies)
        assert sum(t.tp for t in tallies) == 1  # r1's gameplay hit
        assert sum(t.fn for t in tallies) == 1  # r2's missed performance

    def test_failure_mark_scores_as_parse_failure(self, tmp_path: Path) -> None:
        gold = load_gold(_write_gold(tmp_path, _GOLD_LINES))
        envelopes = dict(_ENVELOPES)
        del envelopes["r3"]
        store = _pool_store(envelopes, _APPS)
        try:
            store.labels.record_failure(
                "r3", _VERSIONS, "c1-test", "unclassifiable in the test"
            )
            tallies = pool_tallies(store, gold, _INDEX, _VERSIONS)
        finally:
            store.close()
        assert sum(t.parse_failed for t in tallies) == 1

    def test_unaccounted_in_scope_review_dies_loud(self, tmp_path: Path) -> None:
        gold = load_gold(_write_gold(tmp_path, _GOLD_LINES))
        envelopes = dict(_ENVELOPES)
        del envelopes["r2"]  # in scope, no envelope, no failure mark
        store = _pool_store(envelopes, _APPS)
        try:
            with pytest.raises(ValueError, match="r2"):
                pool_tallies(store, gold, _INDEX, _VERSIONS)
        finally:
            store.close()


class TestCertifyPool:
    """The minted record: accounting, determinism, and the journal round-trip."""

    def test_record_accounts_scope_and_pins_gold(self, tmp_path: Path) -> None:
        gold_path = _write_gold(tmp_path, _GOLD_LINES)
        store = _pool_store(_ENVELOPES, _APPS)
        try:
            eval_run = certify_pool(
                store,
                gold_path=gold_path,
                ontology_path=None,
                model_version=_VERSIONS.model_version,
                prompt_version=_VERSIONS.prompt_version,
                seed=7,
                n_resamples=200,
                started=_NOON,
            )
        finally:
            store.close()
        assert eval_run.n_reference_reviews == 4
        assert eval_run.n_scored_reviews == 3
        assert eval_run.versions == _VERSIONS
        assert eval_run.reference_kind is ReferenceKind.GOLD_FILE
        assert eval_run.reference_id == gold_path.as_posix()
        assert eval_run.reference_sha256 == hashlib.sha256(gold_path.read_bytes()).hexdigest()
        assert eval_run.ontology_content_hash == _STAMP.content_hash
        named = {m.metric for m in eval_run.metrics}
        assert {"precision", "recall", "f1", "sentiment_accuracy"} <= named
        assert {"zero_share_pred", "candidate_emission_rate", "parse_failure_rate"} <= named
        for m in eval_run.metrics:
            assert (m.ci_low is None) == (m.ci_high is None)

    def test_same_seed_regenerates_identical_metrics(self, tmp_path: Path) -> None:
        gold_path = _write_gold(tmp_path, _GOLD_LINES)
        store = _pool_store(_ENVELOPES, _APPS)
        try:
            runs = [
                certify_pool(
                    store,
                    gold_path=gold_path,
                    ontology_path=None,
                    model_version=_VERSIONS.model_version,
                    prompt_version=_VERSIONS.prompt_version,
                    seed=7,
                    n_resamples=200,
                    started=_NOON,
                )
                for _ in range(2)
            ]
        finally:
            store.close()
        assert runs[0].metrics == runs[1].metrics
        # Same resolved config → same fingerprint; only the run identity differs.
        assert runs[0].run.config_hash == runs[1].run.config_hash
        assert runs[0].run.run_id != runs[1].run.run_id

    def test_judge_scope_scores_all_games_under_its_own_scorer(self, tmp_path: Path) -> None:
        """The calibration variant: no exclusion, and the scorer identity says so."""
        gold_path = _write_gold(tmp_path, _GOLD_LINES)
        envelopes = dict(_ENVELOPES)
        envelopes["r-cs2"] = (_mention("gameplay", Sentiment.POSITIVE),)
        store = _pool_store(envelopes, _APPS)
        try:
            eval_run = certify_pool(
                store,
                gold_path=gold_path,
                ontology_path=None,
                model_version=_VERSIONS.model_version,
                prompt_version=_VERSIONS.prompt_version,
                seed=7,
                n_resamples=200,
                started=_NOON,
                excluded_app_ids=(),
                scorer=JUDGE_SCORER,
            )
        finally:
            store.close()
        assert eval_run.n_scored_reviews == 4  # the CS2 review scores, not skipped
        assert eval_run.scorer == JUDGE_SCORER

    def test_certification_survives_the_journal_round_trip(self, tmp_path: Path) -> None:
        gold_path = _write_gold(tmp_path, _GOLD_LINES)
        store = _pool_store(_ENVELOPES, _APPS)
        try:
            eval_run = certify_pool(
                store,
                gold_path=gold_path,
                ontology_path=None,
                model_version=_VERSIONS.model_version,
                prompt_version=_VERSIONS.prompt_version,
                seed=7,
                n_resamples=200,
                started=_NOON,
            )
            store.eval_runs.record(eval_run)
            assert store.eval_runs.get(eval_run.run.run_id) == eval_run
        finally:
            store.close()
