"""Behavioral claims on the store — substitutability, durability, and the schema gate.

The parametrized contract suites are the commit's load-bearing claim: the
durable SQLite pair answers exactly like the in-memory pair the client's tests
already trust, so binding it into the client's constructor slots changes
lifetime, never behavior. The cross-restart smoke closes the loop end-to-end:
a response bought through a real client before a "restart" (close and reopen
the file, fresh client) is a cache hit after it — money moves exactly once.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from steamlens.contracts import (
    AspectMention,
    AspectSlot,
    ClassifierVersions,
    EvalMetric,
    EvalRun,
    FinishReason,
    LlmRequest,
    LlmResponse,
    LlmStage,
    Origin,
    Provenance,
    ReferenceKind,
    ResponseArchive,
    Review,
    ReviewClassification,
    Sentiment,
    SinkEvent,
    SpendLedger,
    SpendRecord,
    TokenUsage,
)
from steamlens.llm_client import (
    InMemoryResponseArchive,
    InMemorySpendLedger,
    LlmClient,
    LlmClientConfig,
    ModelSpec,
    ProviderEntry,
    ProviderPayload,
    Route,
)
from steamlens.store import SchemaVersionError, Store, StoreDataError, StoreError
from steamlens.store.schema import MIGRATION_STEPS, SCHEMA_VERSION

_NOON = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)
_EPOCH = datetime(2000, 1, 1, tzinfo=UTC)  # a `since` before every test's spend


def _record(
    *,
    model: str = "model-a",
    created_at: datetime = _NOON,
    cost: float = 0.001,
) -> SpendRecord:
    return SpendRecord(
        created_at=created_at,
        stage=LlmStage.CLASSIFY,
        model=model,
        model_version=f"{model}-001",
        usage=TokenUsage(prompt_tokens=100, output_tokens=50, thinking_tokens=0),
        cost=cost,
    )


# --- the parametrized contract suites: one behavior spec, both bindings ---


@pytest.fixture(params=["in_memory", "sqlite"])
def cache(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[ResponseArchive]:
    if request.param == "in_memory":
        yield InMemoryResponseArchive()
    else:
        with Store(tmp_path / "steamlens.sqlite3") as store:
            yield store.responses


@pytest.fixture(params=["in_memory", "sqlite"])
def ledger(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[SpendLedger]:
    if request.param == "in_memory":
        yield InMemorySpendLedger()
    else:
        with Store(tmp_path / "steamlens.sqlite3") as store:
            yield store.spend_ledger


class TestResponseArchiveContract:
    """The protocol's whole behavior: miss is None, hits round-trip, put replaces."""

    def test_miss_returns_none(self, cache: ResponseArchive) -> None:
        assert cache.get("absent") is None

    def test_put_get_round_trip(self, cache: ResponseArchive) -> None:
        cache.put("key", '{"raw": "body"}')
        assert cache.get("key") == '{"raw": "body"}'

    def test_put_replaces_previous_value(self, cache: ResponseArchive) -> None:
        cache.put("key", "first")
        cache.put("key", "second")
        assert cache.get("key") == "second"


class TestSpendLedgerContract:
    """The quota and budget reads: filtered by model, windowed by `since`, inclusive."""

    def test_empty_ledger_reads_zero(self, ledger: SpendLedger) -> None:
        assert ledger.request_count_since("model-a", _EPOCH) == 0
        assert ledger.cost_since(_EPOCH) == 0.0

    def test_count_filters_by_model(self, ledger: SpendLedger) -> None:
        ledger.append(_record(model="model-a"))
        ledger.append(_record(model="model-a"))
        ledger.append(_record(model="model-b"))
        assert ledger.request_count_since("model-a", _EPOCH) == 2
        assert ledger.request_count_since("model-b", _EPOCH) == 1

    def test_count_window_is_at_or_after(self, ledger: SpendLedger) -> None:
        before = _NOON - timedelta(hours=1)
        ledger.append(_record(created_at=before))
        ledger.append(_record(created_at=_NOON))
        assert ledger.request_count_since("model-a", _NOON) == 1  # exactly-at is included
        assert ledger.request_count_since("model-a", before) == 2

    def test_cost_sums_across_models_within_window(self, ledger: SpendLedger) -> None:
        ledger.append(_record(model="model-a", created_at=_NOON - timedelta(hours=2), cost=0.5))
        ledger.append(_record(model="model-a", cost=0.25))
        ledger.append(_record(model="model-b", cost=0.125))
        assert ledger.cost_since(_EPOCH) == pytest.approx(0.875)
        assert ledger.cost_since(_NOON - timedelta(hours=1)) == pytest.approx(0.375)

    def test_offset_timestamps_window_chronologically(self, ledger: SpendLedger) -> None:
        """A +03:00 record is windowed by its instant, not its wall-clock text.

        12:00+03:00 is 09:00 UTC. A store comparing timestamp *text* without
        normalizing offsets would count it against a 10:00 UTC `since` — the
        lexicographic trap the write-side UTC normalization exists to close.
        """
        plus3 = timezone(timedelta(hours=3))
        ledger.append(_record(created_at=datetime(2026, 7, 14, 12, 0, tzinfo=plus3)))
        assert ledger.request_count_since("model-a", datetime(2026, 7, 14, 10, 0, tzinfo=UTC)) == 0
        assert ledger.request_count_since("model-a", datetime(2026, 7, 14, 8, 0, tzinfo=UTC)) == 1


# --- what only the durable binding can promise ---


class TestStoreDurability:
    def test_cache_and_ledger_survive_reopen(self, tmp_path: Path) -> None:
        path = tmp_path / "steamlens.sqlite3"
        with Store(path) as store:
            store.responses.put("key", "bought")
            store.spend_ledger.append(_record())
        with Store(path) as store:
            assert store.responses.get("key") == "bought"
            assert store.spend_ledger.request_count_since("model-a", _EPOCH) == 1

    def test_wal_journal_is_active_on_the_file(self, tmp_path: Path) -> None:
        path = tmp_path / "steamlens.sqlite3"
        Store(path).close()
        conn = sqlite3.connect(path)
        try:
            assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        finally:
            conn.close()


class TestSchemaGate:
    def test_fresh_file_lands_at_current_version(self, tmp_path: Path) -> None:
        path = tmp_path / "steamlens.sqlite3"
        Store(path).close()
        conn = sqlite3.connect(path)
        try:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        finally:
            conn.close()

    def test_file_from_newer_code_fails_loud_with_both_numbers(self, tmp_path: Path) -> None:
        path = tmp_path / "steamlens.sqlite3"
        Store(path).close()
        conn = sqlite3.connect(path)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
        conn.close()
        with pytest.raises(SchemaVersionError, match=rf"v{SCHEMA_VERSION + 1}.*v{SCHEMA_VERSION}"):
            Store(path)

    def test_naive_datetime_is_rejected_at_the_boundary(self, tmp_path: Path) -> None:
        naive = datetime(2026, 7, 14, 12, 0)
        with Store(tmp_path / "steamlens.sqlite3") as store:
            with pytest.raises(ValueError, match="naive"):
                store.spend_ledger.append(_record(created_at=naive))
            with pytest.raises(ValueError, match="naive"):
                store.spend_ledger.request_count_since("model-a", naive)


# --- the constructor-slot smoke: a real client over the durable pair ---


class _ScriptedProvider:
    """A minimal deterministic vendor with a send counter — enough for the smoke."""

    def __init__(self) -> None:
        self.sends = 0

    def entry(self) -> ProviderEntry:
        return ProviderEntry(build_payload=self._build, send=self._send, parse=self._parse)

    def _build(
        self, *, model: str, prompt: str, max_output_tokens: int, params: dict[str, object]
    ) -> ProviderPayload:
        return {"model": model, "prompt": prompt, "max_output_tokens": max_output_tokens}

    def _send(self, *, model: str, payload: ProviderPayload) -> str:
        self.sends += 1
        return json.dumps({"text": "labeled"})

    def _parse(self, raw: str) -> LlmResponse:
        body = json.loads(raw)
        return LlmResponse(
            text=str(body["text"]),
            model_version="scripted-001",
            finish_reason=FinishReason.STOP,
            usage=TokenUsage(prompt_tokens=10, output_tokens=5, thinking_tokens=0),
        )


class _NullSink:
    def emit(self, event: SinkEvent) -> None:
        pass


def _client_config() -> LlmClientConfig:
    return LlmClientConfig(
        routes={LlmStage.CLASSIFY: Route(provider="scripted", model="m", max_output_tokens=64)},
        models={"m": ModelSpec(rpm=6000, rpd=None, input_usd_per_1m=0.0, output_usd_per_1m=0.0)},
    )


def test_bought_response_survives_a_restart(tmp_path: Path) -> None:
    """The durable pair in the client's own slots: one purchase across two processes.

    The second client is built over a reopened file with a fresh provider whose
    send counter starts at zero — a hit there can only come from the durable
    cache, which is the cross-run "bought labels never re-paid" promise the
    first corpus-labeling run requires.
    """
    path = tmp_path / "steamlens.sqlite3"
    request = LlmRequest(stage=LlmStage.CLASSIFY, prompt="label this review")

    first = _ScriptedProvider()
    with Store(path) as store:
        client = LlmClient(
            _client_config(),
            store.responses,
            store.spend_ledger,
            _NullSink(),
            registry={"scripted": first.entry()},
        )
        assert client.complete(request).text == "labeled"
    assert first.sends == 1

    second = _ScriptedProvider()
    with Store(path) as store:
        client = LlmClient(
            _client_config(),
            store.responses,
            store.spend_ledger,
            _NullSink(),
            registry={"scripted": second.entry()},
        )
        assert client.complete(request).text == "labeled"
        assert second.sends == 0
        assert store.spend_ledger.request_count_since("m", _EPOCH) == 1


# --- the record surfaces: the corpus snapshot and the label pool ---


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    with Store(tmp_path / "steamlens.sqlite3") as s:
        yield s


def _review(review_id: str = "r1", *, created_at: datetime = _NOON, app_id: int = 440) -> Review:
    return Review(
        review_id=review_id,
        app_id=app_id,
        created_at=created_at,
        language="english",
        text="great gunplay, weak netcode",
        voted_up=True,
    )


def _versions(prompt_version: str = "classify-v1") -> ClassifierVersions:
    return ClassifierVersions(
        model_version="scripted-001",
        prompt_version=prompt_version,
        ontology_version="v1-draft",
    )


def _provenance(run_id: str = "run-1") -> Provenance:
    return Provenance(
        run_id=run_id, code_version="abc1234", created_at=_NOON, config_hash="cfg-hash"
    )


_MENTIONS = (
    AspectMention(
        aspect="gunplay",
        slot=AspectSlot.PINNED,
        sentiment=Sentiment.POSITIVE,
        evidence="great gunplay",
    ),
    AspectMention(
        aspect="netcode", slot=AspectSlot.PINNED, sentiment=Sentiment.NEGATIVE, evidence=None
    ),
)


def _classification(
    review_id: str = "r1",
    *,
    mentions: tuple[AspectMention, ...] = _MENTIONS,
    versions: ClassifierVersions | None = None,
) -> ReviewClassification:
    return ReviewClassification(
        review_id=review_id,
        origin=Origin.SURVEY,
        versions=versions if versions is not None else _versions(),
        run=_provenance(),
        mentions=mentions,
    )


def _seed(store: Store, *review_ids: str) -> None:
    """One recorded run plus the named reviews — what every envelope write needs first."""
    store.reviews.put_many(_review(rid) for rid in review_ids)
    store.labels.record_run(_provenance())


class TestReviewStore:
    def test_round_trip_preserves_the_instant(self, store: Store) -> None:
        """A +03:00 review reads back equal: normalization changes text, never the instant."""
        plus3 = timezone(timedelta(hours=3))
        review = _review(created_at=datetime(2026, 7, 14, 12, 0, tzinfo=plus3))
        store.reviews.put_many([review])
        assert store.reviews.get("r1") == review

    def test_get_missing_returns_none(self, store: Store) -> None:
        assert store.reviews.get("absent") is None

    def test_ingest_is_idempotent_and_counts_only_the_new(self, store: Store) -> None:
        assert store.reviews.put_many([_review("r1"), _review("r2")]) == 2
        assert store.reviews.put_many([_review("r1"), _review("r2"), _review("r3")]) == 1
        assert store.reviews.count() == 3

    def test_count_scoped_ignores_backfilled_out_of_scope_reviews(self, store: Store) -> None:
        """The census supply assertion must not move when an eval backfills CS2 rows."""
        store.reviews.put_many([_review("r1"), _review("r2"), _review("cs2", app_id=730)])
        assert store.reviews.count() == 3
        assert store.reviews.count(excluding_app_ids={730}) == 2


class TestLabelPool:
    def test_envelope_round_trip(self, store: Store) -> None:
        _seed(store, "r1")
        classification = _classification()
        store.labels.put(classification)
        assert store.labels.get("r1", _versions()) == classification

    def test_empty_mentions_envelope_is_a_first_class_result(self, store: Store) -> None:
        _seed(store, "r1")
        processed_found_nothing = _classification(mentions=())
        store.labels.put(processed_found_nothing)
        assert store.labels.get("r1", _versions()) == processed_found_nothing

    def test_get_misses_on_absent_review_and_on_other_versions(self, store: Store) -> None:
        _seed(store, "r1")
        store.labels.put(_classification())
        assert store.labels.get("r2", _versions()) is None
        assert store.labels.get("r1", _versions(prompt_version="classify-v2")) is None

    def test_duplicate_envelope_fails_loud(self, store: Store) -> None:
        _seed(store, "r1")
        store.labels.put(_classification())
        with pytest.raises(StoreError, match="duplicate"):
            store.labels.put(_classification())

    def test_envelope_for_unrecorded_run_is_rejected(self, store: Store) -> None:
        store.reviews.put_many([_review("r1")])  # review present, run never recorded
        with pytest.raises(StoreError, match="not recorded"):
            store.labels.put(_classification())

    def test_envelope_for_unrecorded_review_is_rejected(self, store: Store) -> None:
        store.labels.record_run(_provenance())  # run present, review never ingested
        with pytest.raises(StoreError, match="not recorded"):
            store.labels.put(_classification())

    def test_duplicate_run_fails_loud(self, store: Store) -> None:
        store.labels.record_run(_provenance())
        with pytest.raises(StoreError, match="already recorded"):
            store.labels.record_run(_provenance())

    def test_duplicate_failure_mark_fails_loud(self, store: Store) -> None:
        _seed(store, "r1")
        store.labels.record_failure("r1", _versions(), "run-1", "no entry in the response")
        with pytest.raises(StoreError, match="duplicate"):
            store.labels.record_failure("r1", _versions(), "run-1", "no entry in the response")


class TestSelectionLoop:
    """The query C1's never-re-paid promise loops on."""

    def test_labeled_and_failed_are_excluded_and_a_version_bump_reopens(
        self, store: Store
    ) -> None:
        _seed(store, "r1", "r2", "r3")
        store.labels.put(_classification("r1"))
        store.labels.record_failure("r2", _versions(), "run-1", "idx was never in the input batch")

        remaining = store.reviews.unlabeled_under(_versions())
        assert [r.review_id for r in remaining] == ["r3"]

        bumped = _versions(prompt_version="classify-v2")
        reopened = store.reviews.unlabeled_under(bumped)
        assert [r.review_id for r in reopened] == ["r1", "r2", "r3"]  # deterministic order

    def test_selection_order_is_by_review_id_not_insertion(self, store: Store) -> None:
        store.reviews.put_many([_review("r2"), _review("r1")])
        assert [r.review_id for r in store.reviews.unlabeled_under(_versions())] == ["r1", "r2"]

    def test_selection_scoped_never_offers_backfilled_out_of_scope_reviews(
        self, store: Store
    ) -> None:
        """A future labeling run must not buy labels for eval-backfilled CS2 rows."""
        store.reviews.put_many([_review("r1"), _review("cs2", app_id=730)])
        scoped = store.reviews.unlabeled_under(_versions(), excluding_app_ids={730})
        assert [r.review_id for r in scoped] == ["r1"]
        assert [
            r.review_id for r in store.reviews.unlabeled_under(_versions())
        ] == ["cs2", "r1"]  # unscoped still sees everything — the judge's own selection


class TestReadBoundary:
    """A stored value re-proves itself on the way out — corruption fails loud, named."""

    def _mangle(self, path: Path, sql: str) -> None:
        conn = sqlite3.connect(path)
        try:
            conn.execute(sql)
            conn.commit()
        finally:
            conn.close()

    def test_corrupt_sentiment_fails_loud(self, tmp_path: Path) -> None:
        path = tmp_path / "steamlens.sqlite3"
        with Store(path) as store:
            _seed(store, "r1")
            store.labels.put(_classification())
        self._mangle(path, "UPDATE mentions SET sentiment = 'glorious'")
        with Store(path) as store, pytest.raises(StoreDataError, match="glorious"):
            store.labels.get("r1", _versions())

    def test_naive_stored_timestamp_fails_loud(self, tmp_path: Path) -> None:
        path = tmp_path / "steamlens.sqlite3"
        with Store(path) as store:
            store.reviews.put_many([_review("r1")])
        self._mangle(path, "UPDATE reviews SET created_at = '2026-07-14T12:00:00'")
        with Store(path) as store, pytest.raises(StoreDataError, match="naive"):
            store.reviews.get("r1")


def _eval_run(
    run_id: str = "certify-1",
    *,
    metrics: tuple[EvalMetric, ...] = (
        EvalMetric(metric="f1", value=0.766, ci_low=0.713, ci_high=0.811),
        EvalMetric(metric="zero_share_pred", value=0.51),
    ),
) -> EvalRun:
    return EvalRun(
        run=_provenance(run_id),
        versions=_versions(),
        ontology_content_hash="onto-hash",
        reference_kind=ReferenceKind.GOLD_FILE,
        reference_id="eval/gold/gold.jsonl",
        reference_sha256="gold-hash",
        n_reference_reviews=250,
        n_scored_reviews=245,
        seed=7,
        n_resamples=100,
        scorer="census-vs-gold/1",
        metrics=metrics,
    )


class TestEvalRunLog:
    """The certification journal: minted once, whole, and re-proved on the way out."""

    def test_round_trip_preserves_the_record(self, store: Store) -> None:
        recorded = _eval_run()
        store.eval_runs.record(recorded)
        assert store.eval_runs.get("certify-1") == recorded

    def test_get_missing_returns_none(self, store: Store) -> None:
        assert store.eval_runs.get("absent") is None

    def test_duplicate_run_id_fails_loud(self, store: Store) -> None:
        store.eval_runs.record(_eval_run())
        with pytest.raises(StoreError, match="certify-1"):
            store.eval_runs.record(_eval_run())

    def test_duplicate_metric_name_fails_loud_and_writes_nothing(self, store: Store) -> None:
        doubled = (
            EvalMetric(metric="f1", value=0.7),
            EvalMetric(metric="f1", value=0.8),
        )
        with pytest.raises(StoreError, match="certify-1"):
            store.eval_runs.record(_eval_run(metrics=doubled))
        assert store.eval_runs.get("certify-1") is None  # the whole run rolled back

    def test_half_interval_is_a_scorer_bug_stopped_at_the_door(self, store: Store) -> None:
        half = (EvalMetric(metric="f1", value=0.7, ci_low=0.6, ci_high=None),)
        with pytest.raises(ValueError, match="half an interval"):
            store.eval_runs.record(_eval_run(metrics=half))
        assert store.eval_runs.get("certify-1") is None

    def test_stored_half_interval_fails_loud_on_read(self, tmp_path: Path) -> None:
        path = tmp_path / "steamlens.sqlite3"
        with Store(path) as store:
            store.eval_runs.record(_eval_run())
        conn = sqlite3.connect(path)
        try:
            conn.execute("UPDATE eval_metrics SET ci_high = NULL WHERE metric = 'f1'")
            conn.commit()
        finally:
            conn.close()
        with Store(path) as store, pytest.raises(StoreDataError, match="half-interval"):
            store.eval_runs.get("certify-1")

    def test_v1_file_upgrades_in_place_to_current(self, tmp_path: Path) -> None:
        """The census DB's shape: a step-1 file gains the step-2 tables on open.

        Built by hand at version 1 — exactly what the bought file looks like —
        then opened by current code: the migration runner must apply only the
        missing step, leave step-1 data alone, and land the file at the
        current stamp with a working eval-run journal.
        """
        path = tmp_path / "steamlens.sqlite3"
        conn = sqlite3.connect(path)
        for statement in MIGRATION_STEPS[0]:
            conn.execute(statement)
        conn.execute("PRAGMA user_version = 1")
        conn.commit()
        conn.close()
        with Store(path) as store:
            store.eval_runs.record(_eval_run())
            assert store.eval_runs.get("certify-1") is not None
        conn = sqlite3.connect(path)
        try:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        finally:
            conn.close()

    def test_v2_file_with_minted_runs_upgrades_to_reference_columns(
        self, tmp_path: Path
    ) -> None:
        """The post-D2a DB's shape: gold-named journal rows survive the step-3 rename.

        Built by hand at version 2 with an eval run minted under the old
        column names — exactly what the real DB holds — then opened by
        current code: the row must read back whole, with the backfilled
        ``reference_kind`` saying what was always true of pre-step-3 rows.
        """
        path = tmp_path / "steamlens.sqlite3"
        conn = sqlite3.connect(path)
        for step in MIGRATION_STEPS[:2]:
            for statement in step:
                conn.execute(statement)
        conn.execute(
            "INSERT INTO runs (run_id, code_version, created_at, config_hash)"
            " VALUES ('certify-old', 'abc1234', '2026-07-23T09:36:43.000000+00:00', 'cfg')"
        )
        conn.execute(
            "INSERT INTO eval_runs (run_id, model_version, prompt_version,"
            " ontology_version, ontology_content_hash, gold_path, gold_sha256,"
            " n_gold_reviews, n_scored_reviews, seed, n_resamples, scorer)"
            " VALUES ('certify-old', 'm', 'p', 'v2', 'onto-hash',"
            " 'eval/gold/gold.jsonl', 'gold-hash', 250, 245, 7, 100, 'census-vs-gold/1')"
        )
        conn.execute(
            "INSERT INTO eval_metrics (run_id, metric, value, ci_low, ci_high)"
            " VALUES ('certify-old', 'f1', 0.766, 0.713, 0.811)"
        )
        conn.execute("PRAGMA user_version = 2")
        conn.commit()
        conn.close()
        with Store(path) as store:
            migrated = store.eval_runs.get("certify-old")
        assert migrated is not None
        assert migrated.reference_kind is ReferenceKind.GOLD_FILE
        assert migrated.reference_id == "eval/gold/gold.jsonl"
        assert migrated.reference_sha256 == "gold-hash"
        assert migrated.n_reference_reviews == 250
        assert migrated.metrics == (
            EvalMetric(metric="f1", value=0.766, ci_low=0.713, ci_high=0.811),
        )

    def test_corrupt_reference_kind_fails_loud(self, tmp_path: Path) -> None:
        path = tmp_path / "steamlens.sqlite3"
        with Store(path) as store:
            store.eval_runs.record(_eval_run())
        conn = sqlite3.connect(path)
        try:
            conn.execute("UPDATE eval_runs SET reference_kind = 'vibes'")
            conn.commit()
        finally:
            conn.close()
        with Store(path) as store, pytest.raises(StoreDataError, match="vibes"):
            store.eval_runs.get("certify-1")
