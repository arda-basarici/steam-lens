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
from fakes import NullSink

from steamlens.contracts import (
    AspectAggregate,
    AspectMention,
    AspectSlot,
    ClassifierVersions,
    ComposedNarrative,
    EpisodeMarker,
    EvalMetric,
    EvalRun,
    FinishReason,
    GroundedSpan,
    HistogramBucket,
    HistogramSnapshot,
    LanguageCount,
    LlmRequest,
    LlmResponse,
    LlmStage,
    MarkedWindowCount,
    NarrativeOutcome,
    Origin,
    PathOutcome,
    Provenance,
    ReferenceKind,
    Report,
    ResponseArchive,
    Review,
    ReviewClassification,
    ReviewEvent,
    RollupUnit,
    Sentiment,
    SentimentCounts,
    SpanKind,
    SpendLedger,
    SpendRecord,
    TokenUsage,
    WindowAccount,
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
    stage: LlmStage = LlmStage.CLASSIFY,
) -> SpendRecord:
    return SpendRecord(
        created_at=created_at,
        stage=stage,
        model=model,
        model_version=f"{model}-001",
        usage=TokenUsage(
            prompt_tokens=100, output_tokens=50, thinking_tokens=0,
            cached_prompt_tokens=80,
        ),
        cost=cost,
        duration_s=1.5,
        run_id="run-attr",
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
    """The shared protocol behavior: miss is None, hits round-trip.

    Conflict behavior deliberately splits by binding role and is tested per
    binding below: the in-memory cache replaces, the durable provenance
    archive keeps its first write and fails loud on a differing body.
    """

    def test_miss_returns_none(self, cache: ResponseArchive) -> None:
        assert cache.get("absent") is None

    def test_put_get_round_trip(self, cache: ResponseArchive) -> None:
        cache.put("key", '{"raw": "body"}')
        assert cache.get("key") == '{"raw": "body"}'


def test_in_memory_cache_put_replaces_previous_value() -> None:
    """The cache role: a second write wins — replacement is correct for a
    disposable binding."""
    cache = InMemoryResponseArchive()
    cache.put("key", "first")
    cache.put("key", "second")
    assert cache.get("key") == "second"


def test_durable_archive_keeps_first_write_and_refuses_a_different_body(
    tmp_path: Path,
) -> None:
    """The provenance role: an identical re-put is a safe no-op, a differing
    body fails loud — archived provider output is never silently destroyed."""
    with Store(tmp_path / "steamlens.sqlite3") as store:
        store.responses.put("key", "the bought body")
        store.responses.put("key", "the bought body")  # crash-replay shape: no-op
        assert store.responses.get("key") == "the bought body"
        with pytest.raises(StoreError, match="refusing to overwrite"):
            store.responses.put("key", "a different body")
        assert store.responses.get("key") == "the bought body"


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
        # the rejected file must be left unlocked: the constructor closed its
        # connection on failure, so the operator's next move (repair/move/delete)
        # is not blocked by a leaked handle (a real lock on Windows)
        path.unlink()

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
            NullSink(),
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
            NullSink(),
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


# --- the serving-persistence surfaces: manifests, member folds, and reports ---


def _record_run(store: Store, run_id: str) -> None:
    store.labels.record_run(_provenance(run_id))


class TestSampleManifest:
    def test_membership_round_trip(self, store: Store) -> None:
        _seed(store, "r1", "r2")
        store.sample_members.add_members("run-1", ["r2", "r1"])
        assert store.sample_members.member_ids("run-1") == ("r1", "r2")
        assert store.sample_members.count("run-1") == 2

    def test_duplicate_member_fails_loud(self, store: Store) -> None:
        _seed(store, "r1")
        store.sample_members.add_members("run-1", ["r1"])
        with pytest.raises(StoreError, match="duplicate"):
            store.sample_members.add_members("run-1", ["r1"])

    def test_membership_for_unrecorded_run_is_rejected(self, store: Store) -> None:
        store.reviews.put_many([_review("r1")])
        with pytest.raises(StoreError, match="not recorded"):
            store.sample_members.add_members("run-1", ["r1"])

    def test_membership_for_unrecorded_review_is_rejected(self, store: Store) -> None:
        store.labels.record_run(_provenance())
        with pytest.raises(StoreError, match="not recorded"):
            store.sample_members.add_members("run-1", ["ghost"])

    def test_failed_batch_writes_nothing(self, store: Store) -> None:
        """One bad id in a window's batch must not leave half a window filed."""
        _seed(store, "r1", "r2")
        with pytest.raises(StoreError):
            store.sample_members.add_members("run-1", ["r1", "ghost", "r2"])
        assert store.sample_members.count("run-1") == 0


class TestMemberSelection:
    """``members_unlabeled_under`` — the collision fix as a query."""

    def test_only_members_still_owed_a_verdict_are_selected(self, store: Store) -> None:
        """An envelope bought by a PRIOR run excludes the member — labels re-used,
        never re-bought — while an unlabeled non-member never enters the job."""
        _seed(store, "r1", "r2", "r3", "r4")  # records run-1, the prior buyer
        _record_run(store, "serve-2")
        store.sample_members.add_members("serve-2", ["r1", "r2", "r3"])
        store.labels.put(_classification("r1"))  # bought by run-1
        store.labels.record_failure("r2", _versions(), "serve-2", "unclassifiable alone")

        remaining = store.reviews.members_unlabeled_under("serve-2", _versions())
        assert [r.review_id for r in remaining] == ["r3"]

    def test_version_bump_reopens_members(self, store: Store) -> None:
        _seed(store, "r1")
        _record_run(store, "serve-2")
        store.sample_members.add_members("serve-2", ["r1"])
        store.labels.put(_classification("r1"))
        assert store.reviews.members_unlabeled_under("serve-2", _versions()) == ()
        bumped = _versions(prompt_version="classify-v2")
        reopened = store.reviews.members_unlabeled_under("serve-2", bumped)
        assert [r.review_id for r in reopened] == ["r1"]


class TestMemberFolds:
    """The mint reads fold membership + label pool — whoever bought the label."""

    def test_prior_runs_labels_count_for_this_runs_members(self, store: Store) -> None:
        _seed(store, "r1")  # the envelope below is bought by run-1
        _record_run(store, "serve-2")
        store.sample_members.add_members("serve-2", ["r1"])
        store.labels.put(_classification("r1"))

        assert store.labels.count_member_envelopes("serve-2", _versions()) == 1
        mentions = list(store.labels.iter_member_mentions("serve-2", _versions()))
        assert {(m[0], m[1]) for m in mentions} == {("r1", "gunplay"), ("r1", "netcode")}
        evidence = list(store.labels.iter_member_evidence("serve-2", _versions()))
        assert evidence == [("r1", "gunplay", Sentiment.POSITIVE, "great gunplay")]

    def test_non_members_and_off_version_labels_stay_out(self, store: Store) -> None:
        _seed(store, "r1", "r2")
        _record_run(store, "serve-2")
        store.sample_members.add_members("serve-2", ["r1"])
        store.labels.put(_classification("r1"))
        store.labels.put(_classification("r2"))  # labeled, but not a member

        assert store.labels.count_member_envelopes("serve-2", _versions()) == 1
        assert all(
            m[0] == "r1"
            for m in store.labels.iter_member_mentions("serve-2", _versions())
        )
        bumped = _versions(prompt_version="classify-v2")
        assert store.labels.count_member_envelopes("serve-2", bumped) == 0

    def test_investigation_labels_never_enter_the_fold(self, store: Store) -> None:
        """The two-track wall asserted at this fold boundary like every other."""
        _seed(store, "r1")
        _record_run(store, "serve-2")
        store.sample_members.add_members("serve-2", ["r1"])
        store.labels.put(
            ReviewClassification(
                review_id="r1",
                origin=Origin.INVESTIGATION,
                versions=_versions(),
                run=_provenance(),
                mentions=_MENTIONS,
            )
        )
        assert store.labels.count_member_envelopes("serve-2", _versions()) == 0
        assert list(store.labels.iter_member_mentions("serve-2", _versions())) == []


def _histogram(app_id: int = 440) -> HistogramSnapshot:
    return HistogramSnapshot(
        app_id=app_id,
        rollup_unit=RollupUnit.MONTH,
        rollups=(
            HistogramBucket(datetime(2026, 5, 1, tzinfo=UTC), 40, 10),
            HistogramBucket(datetime(2026, 6, 1, tzinfo=UTC), 900, 300),
        ),
        recent_daily=(HistogramBucket(datetime(2026, 7, 13, tzinfo=UTC), 5, 1),),
        past_events=(
            ReviewEvent(
                event_type=1,
                start=datetime(2026, 6, 5, tzinfo=UTC),
                end=datetime(2026, 6, 20, tzinfo=UTC),
            ),
        ),
        fetched_at=_NOON,
    )


def _narrative() -> ComposedNarrative:
    prose = 'Gunplay leads with 12 mentions. "great gunplay" is typical.'
    return ComposedNarrative(
        prose=prose,
        spans=(
            GroundedSpan(
                start=prose.index("12"), end=prose.index("12") + 2,
                text="12", kind=SpanKind.NUMERAL, value=12.0,
            ),
            GroundedSpan(
                start=prose.index("great gunplay"),
                end=prose.index("great gunplay") + len("great gunplay"),
                text="great gunplay", kind=SpanKind.QUOTE, review_id="r1",
            ),
        ),
        outcome=NarrativeOutcome.COMPOSED,
    )


def _report(
    run_id: str = "serve-1",
    *,
    app_id: int = 440,
    created_at: datetime = _NOON,
    sample_size: int = 20,
    narrative: ComposedNarrative | None = None,
    histogram: HistogramSnapshot | None = None,
) -> Report:
    return Report(
        run=_provenance(run_id),
        app_id=app_id,
        game_name="Team Fortress 2",
        created_at=created_at,
        versions=_versions(),
        sample_size=sample_size,
        take_all=False,
        windows=(
            WindowAccount(
                datetime(2026, 5, 1, tzinfo=UTC),
                datetime(2026, 6, 1, tzinfo=UTC),
                PathOutcome.WINDOWED,
            ),
            WindowAccount(
                datetime(2026, 6, 1, tzinfo=UTC),
                datetime(2026, 7, 1, tzinfo=UTC),
                PathOutcome.FALLBACK_WALKED,
            ),
        ),
        language_mix=(LanguageCount("english", 18), LanguageCount("schinese", 4)),
        narrative=narrative if narrative is not None else _narrative(),
        histogram=histogram if histogram is not None else _histogram(app_id),
        episodes=(
            EpisodeMarker(
                start=datetime(2026, 6, 1, tzinfo=UTC),
                end=datetime(2026, 7, 1, tzinfo=UTC),
                buckets=1,
                reviews=1200,
                peak_multiple=4.8,
                overlaps_marked_window=True,
            ),
        ),
        marked_window_counts=(
            MarkedWindowCount(
                start=datetime(2026, 6, 5, tzinfo=UTC),
                end=datetime(2026, 6, 20, tzinfo=UTC),
                members_inside=3,
            ),
        ),
    )


def _aggregate(
    run_id: str = "serve-1",
    *,
    aspect: str = "gunplay",
    app_id: int = 440,
    sample_size: int = 20,
) -> AspectAggregate:
    return AspectAggregate(
        app_id=app_id,
        aspect=aspect,
        slot=AspectSlot.PINNED,
        reviews_with_aspect=12,
        counts=SentimentCounts(positive=9, negative=1, mixed=1, neutral=1),
        sample_size=sample_size,
        versions=_versions(),
        manifest_id=run_id,
    )


class TestReportLog:
    """Published once, whole; served as-is; re-proved by reconstruction on read."""

    def _publish(self, store: Store, run_id: str = "serve-1") -> Report:
        _record_run(store, run_id)
        report = _report(run_id)
        store.reports.put(report, [_aggregate(run_id), _aggregate(run_id, aspect="netcode")])
        return report

    def test_publish_round_trip(self, store: Store) -> None:
        report = self._publish(store)
        assert store.reports.get("serve-1") == report

    def test_snapshot_rebuilds_full_aggregates_in_write_order(self, store: Store) -> None:
        self._publish(store)
        assert store.reports.get_snapshot("serve-1") == (
            _aggregate("serve-1"),
            _aggregate("serve-1", aspect="netcode"),
        )

    def test_missing_report_and_empty_snapshot_answer_quietly(self, store: Store) -> None:
        assert store.reports.get("absent") is None
        assert store.reports.latest_report(440) is None
        assert store.reports.get_snapshot("absent") == ()

    def test_latest_report_picks_the_newest_completion(self, store: Store) -> None:
        _record_run(store, "serve-1")
        _record_run(store, "serve-2")
        older = _report("serve-1", created_at=_NOON)
        newer = _report("serve-2", created_at=_NOON + timedelta(days=2))
        store.reports.put(older, [_aggregate("serve-1")])
        store.reports.put(newer, [_aggregate("serve-2")])
        latest = store.reports.latest_report(440)
        assert latest is not None
        assert latest.run.run_id == "serve-2"

    def test_duplicate_report_fails_loud(self, store: Store) -> None:
        self._publish(store)
        with pytest.raises(StoreError, match="serve-1"):
            store.reports.put(_report("serve-1"), [_aggregate("serve-1")])

    def test_report_for_unrecorded_run_is_rejected(self, store: Store) -> None:
        with pytest.raises(StoreError, match="not recorded"):
            store.reports.put(_report("serve-1"), [_aggregate("serve-1")])

    def test_duplicate_snapshot_row_rolls_back_the_whole_publish(self, store: Store) -> None:
        _record_run(store, "serve-1")
        doubled = [_aggregate("serve-1"), _aggregate("serve-1")]
        with pytest.raises(StoreError):
            store.reports.put(_report("serve-1"), doubled)
        assert store.reports.get("serve-1") is None  # no half-published state

    def test_disagreeing_aggregate_is_stopped_at_the_door(self, store: Store) -> None:
        _record_run(store, "serve-1")
        with pytest.raises(ValueError, match="disagrees"):
            store.reports.put(
                _report("serve-1"), [_aggregate("serve-1", sample_size=999)]
            )
        assert store.reports.get("serve-1") is None

    def test_foreign_histogram_is_stopped_at_the_door(self, store: Store) -> None:
        _record_run(store, "serve-1")
        with pytest.raises(ValueError, match="histogram"):
            store.reports.put(
                _report("serve-1", histogram=_histogram(app_id=730)),
                [_aggregate("serve-1")],
            )

    def test_withheld_narrative_with_prose_is_stopped_at_the_door(self, store: Store) -> None:
        _record_run(store, "serve-1")
        lying = ComposedNarrative(
            prose="prose that claims to be withheld", spans=(),
            outcome=NarrativeOutcome.WITHHELD,
        )
        with pytest.raises(ValueError, match="contradicts"):
            store.reports.put(_report("serve-1", narrative=lying), [_aggregate("serve-1")])

    def test_withheld_report_round_trips(self, store: Store) -> None:
        """The honest floor is publishable: no prose, disclosed outcome."""
        _record_run(store, "serve-1")
        withheld = ComposedNarrative(prose="", spans=(), outcome=NarrativeOutcome.WITHHELD)
        report = _report("serve-1", narrative=withheld)
        store.reports.put(report, [_aggregate("serve-1")])
        assert store.reports.get("serve-1") == report


class TestReportReadBoundary:
    """A stored report re-proves itself by full reconstruction — edits fail loud."""

    def _published(self, tmp_path: Path) -> Path:
        path = tmp_path / "steamlens.sqlite3"
        with Store(path) as store:
            store.labels.record_run(_provenance("serve-1"))
            store.reports.put(_report("serve-1"), [_aggregate("serve-1")])
        return path

    def _mangle(self, path: Path, sql: str) -> None:
        conn = sqlite3.connect(path)
        try:
            conn.execute(sql)
            conn.commit()
        finally:
            conn.close()

    def test_edited_span_breaks_the_certificate(self, tmp_path: Path) -> None:
        """Editing a certified span's text alone: the prose no longer signs it."""
        path = self._published(tmp_path)
        self._mangle(
            path,
            "UPDATE reports SET narrative_json ="
            """ replace(narrative_json, '"text": "12"', '"text": "13"')""",
        )
        with Store(path) as store, pytest.raises(StoreDataError, match="certificate"):
            store.reports.get("serve-1")

    def test_corrupt_narrative_outcome_fails_loud(self, tmp_path: Path) -> None:
        path = self._published(tmp_path)
        self._mangle(path, "UPDATE reports SET narrative_outcome = 'glorious'")
        with Store(path) as store, pytest.raises(StoreDataError, match="glorious"):
            store.reports.get("serve-1")

    def test_path_totals_disagreeing_with_windows_fail_loud(self, tmp_path: Path) -> None:
        path = self._published(tmp_path)
        self._mangle(path, "UPDATE reports SET windowed_windows = 5")
        with Store(path) as store, pytest.raises(StoreDataError, match="path totals"):
            store.reports.get("serve-1")

    def test_unparseable_payload_fails_loud_naming_the_column(self, tmp_path: Path) -> None:
        path = self._published(tmp_path)
        self._mangle(path, "UPDATE reports SET episodes_json = 'not json'")
        with Store(path) as store, pytest.raises(StoreDataError, match="episodes_json"):
            store.reports.get("serve-1")

    def test_corrupt_snapshot_slot_fails_loud(self, tmp_path: Path) -> None:
        path = self._published(tmp_path)
        self._mangle(path, "UPDATE aggregate_snapshots SET slot = 'vibes'")
        with Store(path) as store, pytest.raises(StoreDataError, match="vibes"):
            store.reports.get_snapshot("serve-1")

    def test_v3_file_upgrades_in_place_and_publishes(self, tmp_path: Path) -> None:
        """The pre-step-4 DB's shape: a v3 file gains the serving tables on open."""
        path = tmp_path / "steamlens.sqlite3"
        conn = sqlite3.connect(path)
        for step in MIGRATION_STEPS[:3]:
            for statement in step:
                conn.execute(statement)
        conn.execute("PRAGMA user_version = 3")
        conn.commit()
        conn.close()
        with Store(path) as store:
            store.labels.record_run(_provenance("serve-1"))
            store.reports.put(_report("serve-1"), [_aggregate("serve-1")])
            assert store.reports.latest_report(440) is not None
        conn = sqlite3.connect(path)
        try:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        finally:
            conn.close()


class TestAdmissionLog:
    """The submit gate's journal: appended admissions, counted from a day boundary."""

    def test_counts_at_or_after_since_and_survives_reopen(self, tmp_path: Path) -> None:
        path = tmp_path / "steamlens.sqlite3"
        with Store(path) as store:
            store.admissions.record("203.0.113.7", 440, at=_NOON - timedelta(days=1))
            store.admissions.record("203.0.113.7", 570, at=_NOON)
            assert store.admissions.count_since(_NOON) == 1
            assert store.admissions.count_since(_EPOCH) == 2
        with Store(path) as store:
            assert store.admissions.count_since(_EPOCH) == 2, "the day survives a restart"

    def test_offset_timestamps_window_chronologically(self, tmp_path: Path) -> None:
        """Same UTC-normalization discipline as the ledger: a +03:00 admission
        is windowed by its instant, not its wall-clock text."""
        plus3 = timezone(timedelta(hours=3))
        with Store(tmp_path / "steamlens.sqlite3") as store:
            store.admissions.record(
                "203.0.113.7", 440, at=datetime(2026, 7, 14, 12, 0, tzinfo=plus3)
            )
            assert store.admissions.count_since(datetime(2026, 7, 14, 10, 0, tzinfo=UTC)) == 0
            assert store.admissions.count_since(datetime(2026, 7, 14, 8, 0, tzinfo=UTC)) == 1


class TestOpsReads:
    """The ops page's aggregates: journal rows in, display totals out."""

    def test_daily_ledger_groups_by_utc_day_newest_first(self, store: Store) -> None:
        store.spend_ledger.append(_record(created_at=_NOON, cost=0.002))
        store.spend_ledger.append(_record(created_at=_NOON + timedelta(hours=1), cost=0.003))
        store.spend_ledger.append(_record(created_at=_NOON - timedelta(days=1), cost=0.010))
        days = store.ops.daily_ledger(_EPOCH)
        assert [(d.day, d.calls) for d in days] == [("2026-07-14", 2), ("2026-07-13", 1)]
        today = days[0]
        assert today.cost == pytest.approx(0.005)
        assert (today.prompt_tokens, today.output_tokens, today.thinking_tokens) == (200, 100, 0)
        assert today.cached_prompt_tokens == 160, "the cache-hit split aggregates per day"

    def test_daily_ledger_windows_at_or_after_since(self, store: Store) -> None:
        store.spend_ledger.append(_record(created_at=_NOON - timedelta(days=2)))
        store.spend_ledger.append(_record(created_at=_NOON))
        days = store.ops.daily_ledger(_NOON)
        assert [d.day for d in days] == ["2026-07-14"]

    def test_daily_ledger_groups_offset_timestamps_by_utc_day(self, store: Store) -> None:
        """A +03:00 call at 01:00 wall clock belongs to the *previous* UTC day —
        the day key is the normalized instant's date, not the wall-clock text."""
        plus3 = timezone(timedelta(hours=3))
        store.spend_ledger.append(
            _record(created_at=datetime(2026, 7, 14, 1, 0, tzinfo=plus3))
        )
        assert [d.day for d in store.ops.daily_ledger(_EPOCH)] == ["2026-07-13"]

    def test_stage_model_totals_group_costliest_first(self, store: Store) -> None:
        store.spend_ledger.append(_record(model="model-a", cost=0.001))
        store.spend_ledger.append(_record(model="model-a", cost=0.001))
        store.spend_ledger.append(
            _record(model="model-a", cost=0.005, stage=LlmStage.COMPOSE)
        )
        totals = store.ops.stage_model_totals()
        assert [(t.stage, t.calls) for t in totals] == [
            (LlmStage.COMPOSE.value, 1),
            (LlmStage.CLASSIFY.value, 2),
        ]
        assert totals[1].cost == pytest.approx(0.002)

    def test_daily_admissions_count_without_exposing_ips(self, store: Store) -> None:
        store.admissions.record("203.0.113.7", 440, at=_NOON)
        store.admissions.record("198.51.100.9", 570, at=_NOON)
        store.admissions.record("203.0.113.7", 440, at=_NOON - timedelta(days=1))
        days = store.ops.daily_admissions(_EPOCH)
        assert [(d.day, d.admissions) for d in days] == [("2026-07-14", 2), ("2026-07-13", 1)]
        # The row's whole shape is (day, count) — the audit's no-raw-IPs rule
        # holds structurally, not by renderer discipline.
        assert set(days[0].__dataclass_fields__) == {"day", "admissions"}

    def test_report_count_counts_published_reports(self, store: Store) -> None:
        assert store.ops.report_count() == 0
        _record_run(store, "serve-1")
        store.reports.put(_report("serve-1"), [_aggregate("serve-1")])
        assert store.ops.report_count() == 1

    def test_measured_prompt_excludes_rows_without_the_step6_accounting(
        self, store: Store
    ) -> None:
        """A pre-step-6 row (no recorded duration) never recorded its cache
        split — it must fall out of the hit rate's denominator, not read 0%."""
        store.spend_ledger.append(_record(created_at=_NOON))
        store._conn.execute(  # pyright: ignore[reportPrivateUsage]
            "INSERT INTO spend_ledger (created_at, stage, model, model_version,"
            " prompt_tokens, output_tokens, thinking_tokens, cost)"
            " VALUES ('2026-07-14T13:00:00+00:00', 'classify', 'model-a',"
            " 'model-a-001', 500, 10, 0, 0.01)"
        )
        day = store.ops.daily_ledger(_EPOCH)[0]
        assert day.prompt_tokens == 600
        assert day.measured_prompt_tokens == 100, "only the measured row's prompt counts"
        assert day.cached_prompt_tokens == 80

    def test_daily_refusals_count_per_day(self, store: Store) -> None:
        store.refusals.record("day_cap", at=_NOON)
        store.refusals.record("in_flight", at=_NOON)
        store.refusals.record("backstop", at=_NOON - timedelta(days=1))
        days = store.ops.daily_refusals(_EPOCH)
        assert [(d.day, d.refusals) for d in days] == [("2026-07-14", 2), ("2026-07-13", 1)]

    def test_recent_jobs_join_their_attributed_cost_newest_first(
        self, store: Store
    ) -> None:
        store.jobs.start("serve-1", 440, "Team Fortress 2", at=_NOON)
        store.jobs.settle(
            "serve-1", at=_NOON + timedelta(minutes=3), outcome="done", error=None,
            labeled=120, reused=30, failed_durable=1, refused_batches=0,
            stage_timings_json='{"serve.fetch": 10.0}',
        )
        store.jobs.start("serve-2", 570, "Dota 2", at=_NOON + timedelta(hours=1))
        store.spend_ledger.append(_record(cost=0.002))  # run-attr, not serve-1
        for _ in range(2):
            store.spend_ledger.append(
                SpendRecord(
                    created_at=_NOON, stage=LlmStage.CLASSIFY, model="model-a",
                    model_version="model-a-001",
                    usage=TokenUsage(prompt_tokens=10, output_tokens=5, thinking_tokens=0),
                    cost=0.003, duration_s=2.0, run_id="serve-1",
                )
            )
        jobs = store.ops.recent_jobs(10)
        assert [j.run_id for j in jobs] == ["serve-2", "serve-1"]
        settled = jobs[1]
        assert settled.outcome == "done"
        assert (settled.labeled, settled.reused) == (120, 30)
        assert settled.cost == pytest.approx(0.006), "cost joins by run_id only"
        running = jobs[0]
        assert running.outcome is None and running.finished_at is None
        assert running.cost == 0.0

    def test_stage_latencies_summarize_measured_rows_only(self, store: Store) -> None:
        for duration in (1.0, 2.0, 3.0, 4.0):
            store.spend_ledger.append(
                SpendRecord(
                    created_at=_NOON, stage=LlmStage.CLASSIFY, model="model-a",
                    model_version="model-a-001",
                    usage=TokenUsage(prompt_tokens=10, output_tokens=5, thinking_tokens=0),
                    cost=0.001, duration_s=duration,
                )
            )
        store._conn.execute(  # pyright: ignore[reportPrivateUsage]
            "INSERT INTO spend_ledger (created_at, stage, model, model_version,"
            " prompt_tokens, output_tokens, thinking_tokens, cost)"
            " VALUES ('2026-07-14T13:00:00+00:00', 'compose', 'model-a',"
            " 'model-a-001', 500, 10, 0, 0.01)"
        )
        rows = store.ops.stage_latencies()
        assert [(r.stage, r.calls) for r in rows] == [("classify", 4)]
        assert (rows[0].p50_s, rows[0].p95_s) == (2.0, 4.0)


class TestJobLog:
    """The lifecycle journal: started rows settle by update, orphans fail loud."""

    def test_start_then_settle_round_trips_through_the_ops_read(self, store: Store) -> None:
        store.jobs.start("serve-1", 440, "Team Fortress 2", at=_NOON)
        store.jobs.settle(
            "serve-1", at=_NOON + timedelta(minutes=2), outcome="failed",
            error="RunAbort: over budget", labeled=None, reused=None,
            failed_durable=None, refused_batches=None, stage_timings_json=None,
        )
        job = store.ops.recent_jobs(1)[0]
        assert job.outcome == "failed"
        assert job.error == "RunAbort: over budget"
        assert job.labeled is None, "counts unknown at abort stay honest NULLs"

    def test_duplicate_start_fails_loud(self, store: Store) -> None:
        store.jobs.start("serve-1", 440, "TF2", at=_NOON)
        with pytest.raises(StoreError, match="serve-1"):
            store.jobs.start("serve-1", 440, "TF2", at=_NOON)

    def test_settle_without_start_fails_loud(self, store: Store) -> None:
        with pytest.raises(StoreError, match="never started"):
            store.jobs.settle(
                "ghost", at=_NOON, outcome="done", error=None, labeled=0,
                reused=0, failed_durable=0, refused_batches=0, stage_timings_json=None,
            )

    def test_a_started_never_settled_row_reads_as_running(self, store: Store) -> None:
        """The process-death trace: no finished_at, no outcome — the row states
        exactly what is known, nothing backfills it."""
        store.jobs.start("serve-1", 440, "TF2", at=_NOON)
        job = store.ops.recent_jobs(1)[0]
        assert job.finished_at is None and job.outcome is None
