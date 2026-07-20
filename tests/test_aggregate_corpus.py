"""Census-fold orchestrator tests — the store reads composing into the pure fold.

The in-memory cases prove the shell folds only what may become a number:
per-game grain, denominators that count empty envelopes, and the two-track and
version filters that keep investigation-origin and off-version labels out. The
gated smoke folds the real bought census and checks it against its known totals.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from steamlens.contracts import (
    AspectAggregate,
    AspectMention,
    AspectSlot,
    ClassifierVersions,
    Origin,
    Provenance,
    Review,
    ReviewClassification,
    Sentiment,
    SentimentCounts,
)
from steamlens.store import Store
from steamlens.studies import mint_census_aggregates

_NOON = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)
_V2 = ClassifierVersions(
    model_version="deepseek-v4-flash", prompt_version="classify-v1", ontology_version="v2"
)
_V1 = ClassifierVersions(
    model_version="deepseek-v4-flash", prompt_version="classify-v1", ontology_version="v1"
)


def _review(review_id: str, app_id: int) -> Review:
    return Review(
        review_id=review_id, app_id=app_id, created_at=_NOON, language="english",
        text="t", voted_up=True,
    )


def _prov(run_id: str = "run-1") -> Provenance:
    return Provenance(run_id=run_id, code_version="abc1234", created_at=_NOON, config_hash="cfg")


def _mention(
    aspect: str, sentiment: Sentiment = Sentiment.POSITIVE, slot: AspectSlot = AspectSlot.PINNED
) -> AspectMention:
    return AspectMention(aspect=aspect, slot=slot, sentiment=sentiment)


def _envelope(
    review_id: str,
    mentions: Iterable[AspectMention] = (),
    *,
    origin: Origin = Origin.SURVEY,
    versions: ClassifierVersions = _V2,
) -> ReviewClassification:
    return ReviewClassification(
        review_id=review_id, origin=origin, versions=versions, run=_prov(), mentions=tuple(mentions)
    )


def _seed(reviews: list[Review], envelopes: list[ReviewClassification]) -> Store:
    store = Store(":memory:")
    store.reviews.put_many(reviews)
    store.labels.record_run(_prov())
    for envelope in envelopes:
        store.labels.put(envelope)
    return store


def _find(aggregates: tuple[AspectAggregate, ...], app_id: int, aspect: str) -> AspectAggregate:
    return next(a for a in aggregates if a.app_id == app_id and a.aspect == aspect)


def _total(counts: SentimentCounts) -> int:
    return counts.positive + counts.negative + counts.mixed + counts.neutral


def test_mints_per_game_survey_aggregates_with_empty_denominators() -> None:
    """Per game and aspect: counts from mentions, denominator over all envelopes incl. empties."""
    store = _seed(
        [_review(r, 10) for r in ("r1", "r2", "r3")] + [_review(r, 20) for r in ("r4", "r5")],
        [
            _envelope(
                "r1",
                [_mention("combat", Sentiment.POSITIVE), _mention("story", Sentiment.NEGATIVE)],
            ),
            _envelope("r2", [_mention("combat", Sentiment.POSITIVE)]),
            _envelope("r3", []),
            _envelope("r4", [_mention("combat", Sentiment.NEGATIVE)]),
            _envelope("r5", []),
        ],
    )
    aggregates = mint_census_aggregates(store, versions=_V2)
    store.close()

    got = {(a.app_id, a.aspect) for a in aggregates}
    assert got == {(10, "combat"), (10, "story"), (20, "combat")}
    combat10 = _find(aggregates, 10, "combat")
    assert combat10.counts == SentimentCounts(2, 0, 0, 0)
    assert combat10.reviews_with_aspect == 2
    assert combat10.sample_size == 3  # r1, r2, and the empty r3 all count as reviews looked at
    assert _find(aggregates, 10, "story").counts == SentimentCounts(0, 1, 0, 0)
    combat20 = _find(aggregates, 20, "combat")
    assert combat20.counts == SentimentCounts(0, 1, 0, 0)
    assert combat20.sample_size == 2  # r4 and the empty r5


def test_investigation_labels_never_enter_a_number() -> None:
    """An investigation-origin envelope adds neither a mention nor a denominator to the survey."""
    store = _seed(
        [_review("r1", 10), _review("r2", 10)],
        [
            _envelope("r1", [_mention("combat")]),
            _envelope("r2", [_mention("combat")], origin=Origin.INVESTIGATION),
        ],
    )
    aggregates = mint_census_aggregates(store, versions=_V2)
    store.close()
    combat = _find(aggregates, 10, "combat")
    assert combat.reviews_with_aspect == 1
    assert combat.sample_size == 1


def test_off_version_labels_never_enter_a_number() -> None:
    """A v1 envelope is invisible to a v2 fold — a number knows its own vocabulary."""
    store = _seed(
        [_review("r1", 10), _review("r2", 10)],
        [
            _envelope("r1", [_mention("combat")], versions=_V2),
            _envelope("r2", [_mention("combat")], versions=_V1),
        ],
    )
    aggregates = mint_census_aggregates(store, versions=_V2)
    store.close()
    combat = _find(aggregates, 10, "combat")
    assert combat.reviews_with_aspect == 1
    assert combat.sample_size == 1


def test_game_with_only_empty_envelopes_mints_no_aggregate() -> None:
    """A game whose surveyed reviews all found nothing produces no aspect rows."""
    store = _seed(
        [_review("r1", 10), _review("r2", 20)],
        [_envelope("r1", [_mention("combat")]), _envelope("r2", [])],
    )
    aggregates = mint_census_aggregates(store, versions=_V2)
    store.close()
    assert all(a.app_id != 20 for a in aggregates)


def test_manifest_id_is_deterministic_and_stamped() -> None:
    """Folding the same pool twice stamps the identical manifest on every row."""
    store = _seed([_review("r1", 10)], [_envelope("r1", [_mention("combat")])])
    first = mint_census_aggregates(store, versions=_V2)
    second = mint_census_aggregates(store, versions=_V2)
    store.close()
    assert first == second
    assert first[0].manifest_id.startswith("census/v2/")
    assert all(a.versions == _V2 for a in first)


_CENSUS_DB = Path(__file__).resolve().parent.parent / "data" / "steamlens.sqlite3"


@pytest.mark.skipif(
    not os.environ.get("STEAMLENS_CENSUS_SMOKE") or not _CENSUS_DB.exists(),
    reason="census smoke: set STEAMLENS_CENSUS_SMOKE=1 with the bought census DB present",
)
def test_census_fold_matches_known_totals() -> None:
    """Real census folds to settled totals: 49 games, 170,532 mentions, 135,259 envelopes."""
    with Store(_CENSUS_DB) as store:
        aggregates = mint_census_aggregates(store, versions=_V2)
    assert len({a.app_id for a in aggregates}) == 49
    assert sum(_total(a.counts) for a in aggregates) == 170_532
    denominator = {a.app_id: a.sample_size for a in aggregates}
    assert sum(denominator.values()) == 135_259
    assert all(a.reviews_with_aspect == _total(a.counts) for a in aggregates)
