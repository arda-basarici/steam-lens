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
    ClassifyCache,
    FinishReason,
    LlmRequest,
    LlmResponse,
    LlmStage,
    SinkEvent,
    SpendLedger,
    SpendRecord,
    TokenUsage,
)
from steamlens.llm_client import (
    InMemoryClassifyCache,
    InMemorySpendLedger,
    LlmClient,
    LlmClientConfig,
    ModelSpec,
    ProviderEntry,
    ProviderPayload,
    Route,
)
from steamlens.store import SchemaVersionError, Store
from steamlens.store.schema import SCHEMA_VERSION

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
def cache(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[ClassifyCache]:
    if request.param == "in_memory":
        yield InMemoryClassifyCache()
    else:
        with Store(tmp_path / "steamlens.sqlite3") as store:
            yield store.classify_cache


@pytest.fixture(params=["in_memory", "sqlite"])
def ledger(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[SpendLedger]:
    if request.param == "in_memory":
        yield InMemorySpendLedger()
    else:
        with Store(tmp_path / "steamlens.sqlite3") as store:
            yield store.spend_ledger


class TestClassifyCacheContract:
    """The protocol's whole behavior: miss is None, hits round-trip, put replaces."""

    def test_miss_returns_none(self, cache: ClassifyCache) -> None:
        assert cache.get("absent") is None

    def test_put_get_round_trip(self, cache: ClassifyCache) -> None:
        cache.put("key", '{"raw": "body"}')
        assert cache.get("key") == '{"raw": "body"}'

    def test_put_replaces_previous_value(self, cache: ClassifyCache) -> None:
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
            store.classify_cache.put("key", "bought")
            store.spend_ledger.append(_record())
        with Store(path) as store:
            assert store.classify_cache.get("key") == "bought"
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
            store.classify_cache,
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
            store.classify_cache,
            store.spend_ledger,
            _NullSink(),
            registry={"scripted": second.entry()},
        )
        assert client.complete(request).text == "labeled"
        assert second.sends == 0
        assert store.spend_ledger.request_count_since("m", _EPOCH) == 1
