"""Behavioral claims on the D2c agreement read — pairing direction, drops, the pin.

The load-bearing claims: the judge's labels take the reference role (direction
is fixed, not configurable), a judge-unread review drops from the intersection
while a production failure scores as a parse failure, a partially-dispatched
sample dies loud instead of quietly scoring, the reference digest pins labels
(insensitive to envelope order and run stamps, sensitive to any label change),
and the minted record journals as a ``pool-labels`` run surviving the
round-trip.
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
from steamlens.core.classify import PROMPT_VERSION
from steamlens.evals.agreement import (
    AGREEMENT_SCORER,
    agreement_pool,
    reference_digest,
)
from steamlens.evals.judge_dispatch import JUDGE_MODEL_ID
from steamlens.ontology import load_ontology_version
from steamlens.store import Store

_NOON = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
_STAMP = load_ontology_version(None)
_PRODUCTION = ClassifierVersions(
    model_version="model-t", prompt_version="prompt-t", ontology_version=_STAMP.version
)
_JUDGE = ClassifierVersions(
    model_version=JUDGE_MODEL_ID,
    prompt_version=PROMPT_VERSION,
    ontology_version=_STAMP.version,
)


def _mention(aspect: str, sentiment: Sentiment) -> AspectMention:
    return AspectMention(
        aspect=aspect, slot=AspectSlot.PINNED, sentiment=sentiment, evidence=None
    )


def _envelope(
    review_id: str,
    versions: ClassifierVersions,
    mentions: tuple[AspectMention, ...],
    run: Provenance,
) -> ReviewClassification:
    return ReviewClassification(
        review_id=review_id,
        origin=Origin.SURVEY,
        versions=versions,
        run=run,
        mentions=mentions,
    )


def _store(
    review_ids: list[str],
    production: dict[str, tuple[AspectMention, ...]],
    judge: dict[str, tuple[AspectMention, ...]],
    *,
    production_failures: tuple[str, ...] = (),
    judge_failures: tuple[str, ...] = (),
) -> Store:
    """An in-memory pool with both annotators' envelopes over the same reviews."""
    store = Store(":memory:")
    store.reviews.put_many(
        Review(
            review_id=rid,
            app_id=10,
            created_at=_NOON,
            language="english",
            text=f"review {rid}",
            voted_up=True,
        )
        for rid in review_ids
    )
    run = Provenance(
        run_id="agree-test", code_version="testsha", created_at=_NOON, config_hash="cfg"
    )
    store.labels.record_run(run)
    for rid, mentions in production.items():
        store.labels.put(_envelope(rid, _PRODUCTION, mentions, run))
    for rid, mentions in judge.items():
        store.labels.put(_envelope(rid, _JUDGE, mentions, run))
    for rid in production_failures:
        store.labels.record_failure(rid, _PRODUCTION, run.run_id, "malformed")
    for rid in judge_failures:
        store.labels.record_failure(rid, _JUDGE, run.run_id, "provider refused")
    return store


def _sample_file(tmp_path: Path, review_ids: list[str]) -> Path:
    path = tmp_path / "sample.jsonl"
    path.write_text(
        "\n".join(
            json.dumps(
                {
                    "review_id": rid,
                    "app_id": 10,
                    "text_sha256": hashlib.sha256(
                        f"review {rid}".encode()
                    ).hexdigest(),
                }
            )
            for rid in review_ids
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _run(store: Store, sample_path: Path):
    return agreement_pool(
        store,
        sample_path=sample_path,
        ontology_path=None,
        model_version=_PRODUCTION.model_version,
        prompt_version=_PRODUCTION.prompt_version,
        seed=7,
        n_resamples=200,
        started=_NOON,
    )


def test_accounting_drops_judge_unread_and_scores_the_rest(tmp_path: Path) -> None:
    """Four sampled: agree / production-miss / both-empty / judge-refused.

    The judge-refused review narrows ``n_scored_reviews`` below the sample
    size; the other three score. Direction shows in recall < 1 (the judge's
    r2 mention that production missed) with precision = 1 (everything
    production said, the judge corroborates).
    """
    ids = ["r1", "r2", "r3", "r4"]
    store = _store(
        ids,
        production={"r1": (_mention("gameplay", Sentiment.POSITIVE),), "r2": (), "r3": (),
                    "r4": ()},
        judge={"r1": (_mention("gameplay", Sentiment.POSITIVE),),
               "r2": (_mention("performance", Sentiment.NEGATIVE),), "r3": ()},
        judge_failures=("r4",),
    )
    try:
        eval_run = _run(store, _sample_file(tmp_path, ids))
    finally:
        store.close()
    assert eval_run.n_reference_reviews == 4
    assert eval_run.n_scored_reviews == 3
    assert eval_run.reference_kind is ReferenceKind.POOL_LABELS
    assert eval_run.scorer == AGREEMENT_SCORER
    assert JUDGE_MODEL_ID in eval_run.reference_id
    assert "sample.jsonl" in eval_run.reference_id
    named = {m.metric: m.value for m in eval_run.metrics}
    assert named["precision"] == 1.0
    assert named["recall"] == 0.5
    assert named["parse_failure_rate"] == 0.0


def test_production_failure_scores_as_parse_failure(tmp_path: Path) -> None:
    ids = ["r1", "r2"]
    store = _store(
        ids,
        production={"r1": (_mention("gameplay", Sentiment.POSITIVE),)},
        judge={"r1": (_mention("gameplay", Sentiment.POSITIVE),),
               "r2": (_mention("performance", Sentiment.NEGATIVE),)},
        production_failures=("r2",),
    )
    try:
        eval_run = _run(store, _sample_file(tmp_path, ids))
    finally:
        store.close()
    assert eval_run.n_scored_reviews == 2
    named = {m.metric: m.value for m in eval_run.metrics}
    assert named["parse_failure_rate"] == 0.5


def test_partially_dispatched_sample_dies_loud(tmp_path: Path) -> None:
    ids = ["r1", "r2"]
    store = _store(
        ids,
        production={"r1": (), "r2": ()},
        judge={"r1": ()},  # r2 never judged, no failure mark either
    )
    try:
        with pytest.raises(ValueError, match="r2"):
            _run(store, _sample_file(tmp_path, ids))
    finally:
        store.close()


def test_missing_production_side_dies_loud(tmp_path: Path) -> None:
    ids = ["r1"]
    store = _store(ids, production={}, judge={"r1": ()})
    try:
        with pytest.raises(ValueError, match="production"):
            _run(store, _sample_file(tmp_path, ids))
    finally:
        store.close()


def test_reference_digest_pins_labels_not_bookkeeping() -> None:
    """Same labels under different run stamps or orders digest identically;
    any label change digests differently."""
    run_a = Provenance(run_id="a", code_version="x", created_at=_NOON, config_hash="1")
    run_b = Provenance(run_id="b", code_version="y", created_at=_NOON, config_hash="2")
    e1 = _envelope("r1", _JUDGE, (_mention("gameplay", Sentiment.POSITIVE),), run_a)
    e1_other_run = _envelope("r1", _JUDGE, (_mention("gameplay", Sentiment.POSITIVE),), run_b)
    e2 = _envelope("r2", _JUDGE, (), run_a)
    assert reference_digest((e1, e2)) == reference_digest((e2, e1_other_run))
    e1_changed = _envelope("r1", _JUDGE, (_mention("gameplay", Sentiment.NEGATIVE),), run_a)
    assert reference_digest((e1, e2)) != reference_digest((e1_changed, e2))


def test_agreement_run_survives_the_journal_round_trip(tmp_path: Path) -> None:
    ids = ["r1"]
    store = _store(
        ids,
        production={"r1": (_mention("gameplay", Sentiment.POSITIVE),)},
        judge={"r1": (_mention("gameplay", Sentiment.POSITIVE),)},
    )
    try:
        eval_run = _run(store, _sample_file(tmp_path, ids))
        store.eval_runs.record(eval_run)
        assert store.eval_runs.get(eval_run.run.run_id) == eval_run
    finally:
        store.close()
