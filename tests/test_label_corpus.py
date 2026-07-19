"""C1 driver tests — the census orchestration proven end-to-end on a fake provider.

The rig drives ``execute_run`` whole: real corpus fixture files, real ``Store``
connections on a temp database, the real client with a fake ``ProviderEntry``
injected — so ingest, the supply assertion, selection/resume, the three-pass
failure sweep, envelope writes, the drift watch, and the manifest are all
exercised through the same seams the census will use. The fake's ``send``
records every prompt (the never-re-buy claims assert on what was actually
dispatched) and embeds its reported model version in the raw body so ``parse``
stays pure over cached responses, exactly as the registry contract requires.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path

from steamlens.contracts import (
    ClassifierVersions,
    FinishReason,
    LlmResponse,
    TokenUsage,
)
from steamlens.core.classify import PROMPT_VERSION
from steamlens.llm_client import ProviderEntry, ProviderPayload, ProviderPermanentError
from steamlens.ontology import load_ontology_version
from steamlens.store import Store
from steamlens.studies.label_corpus import MODEL_ID, RunConfig, execute_run

_REVIEWS_BLOCK = re.compile(r"<reviews>\n(.*)\n</reviews>", re.DOTALL)


class FakeProvider:
    """A scripted DeepSeek stand-in: answers per review text, records dispatches.

    ``send`` extracts the batch from the prompt's data channel and answers one
    row per idx — empty aspects by default, a ``gameplay`` mention when the
    review text asks for one, and *no row at all* for texts carrying ``FAIL``
    (the driver's re-batch path runs on missing idxs). ``model_version`` for
    each call comes from ``version_for`` so drift is scriptable per call.
    """

    def __init__(self, version_for: list[str] | None = None) -> None:
        self.prompts: list[str] = []
        self._versions = version_for or []
        self._lock = threading.Lock()

    def entry(self) -> ProviderEntry:
        return ProviderEntry(build_payload=self._build, send=self._send, parse=self._parse)

    def dispatched_texts(self) -> list[str]:
        """Every review text sent to the provider, in dispatch order, flattened."""
        texts: list[str] = []
        for prompt in self.prompts:
            texts.extend(text for _, text in self._batch(prompt))
        return texts

    @staticmethod
    def _batch(prompt: str) -> list[tuple[int, str]]:
        match = _REVIEWS_BLOCK.search(prompt)
        assert match, "prompt carries no <reviews> data channel"
        rows = json.loads(match.group(1))
        return [(int(row["idx"]), str(row["text"])) for row in rows]

    def _build(
        self, *, model: str, prompt: str, max_output_tokens: int, params: dict[str, object]
    ) -> ProviderPayload:
        return {"model": model, "prompt": prompt}

    def _send(self, *, model: str, payload: ProviderPayload) -> str:
        with self._lock:
            call_index = len(self.prompts)
            self.prompts.append(str(payload["prompt"]))
        if "REFUSE" in str(payload["prompt"]):
            raise ProviderPermanentError("HTTP 400: Content Exists Risk")
        version = (
            self._versions[call_index] if call_index < len(self._versions) else MODEL_ID
        )
        answers = [
            {"idx": idx, "aspects": self._aspects_for(text)}
            for idx, text in self._batch(str(payload["prompt"]))
            if "FAIL" not in text
        ]
        return json.dumps({"model_version": version, "answers": answers})

    @staticmethod
    def _aspects_for(text: str) -> list[dict[str, str]]:
        if "gameplay" in text:
            return [{"aspect": "gameplay", "sentiment": "positive"}]
        return []

    @staticmethod
    def _parse(raw: str) -> LlmResponse:
        body = json.loads(raw)
        return LlmResponse(
            text=json.dumps(body["answers"]),
            model_version=str(body["model_version"]),
            finish_reason=FinishReason.STOP,
            usage=TokenUsage(prompt_tokens=100, output_tokens=20, thinking_tokens=0),
        )


def _corpus(tmp_path: Path, texts: list[str]) -> Path:
    """One usable-game corpus file; ids zero-padded so selection order is sane."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    rows = [
        {
            "recommendationid": f"{i:03d}",
            "language": "english",
            "review": text,
            "timestamp_created": 1_781_279_000 + i,
            "voted_up": True,
        }
        for i, text in enumerate(texts)
    ]
    (corpus / "440_reviews.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )
    return corpus


def _config(tmp_path: Path, supply: int, **overrides: object) -> RunConfig:
    defaults: dict[str, object] = {
        "corpus_dir": tmp_path / "corpus",
        "db_path": tmp_path / "pool.sqlite3",
        "runs_dir": tmp_path / "runs",
        "ontology_path": None,
        "n": 5,
        "max_workers": 2,
        "budget_usd": 1.0,
        "limit": None,
        "expected_supply": supply,
    }
    defaults.update(overrides)
    return RunConfig(**defaults)  # type: ignore[arg-type]


def _versions() -> ClassifierVersions:
    return ClassifierVersions(
        model_version=MODEL_ID,
        prompt_version=PROMPT_VERSION,
        ontology_version=load_ontology_version().version,
    )


def test_happy_path_labels_everything(tmp_path: Path) -> None:
    """Twelve reviews, three batches: every review gets its envelope, manifest true."""
    texts = [f"Solid game, {'gameplay shines' if i % 4 == 0 else 'nothing to say'} {i}"
             for i in range(12)]
    _corpus(tmp_path, texts)
    provider = FakeProvider()
    exit_code = execute_run(_config(tmp_path, supply=12), provider.entry())
    assert exit_code == 0

    with Store(tmp_path / "pool.sqlite3") as store:
        assert store.reviews.unlabeled_under(_versions()) == ()
        with_mentions = sum(
            1
            for i in range(12)
            if (env := store.labels.get(f"{i:03d}", _versions())) and env.mentions
        )
        assert with_mentions == 3  # idx 0, 4, 8 asked for a gameplay mention

    manifests = list((tmp_path / "runs").glob("*/manifest.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert manifest["aborted"] is None
    assert manifest["reviews"]["labeled"] == 12
    assert manifest["reviews"]["failed_durable"] == 0
    assert manifest["model_versions_seen"] == [MODEL_ID]
    assert (manifests[0].parent / "run.log").exists()


def test_resume_never_rebuys(tmp_path: Path) -> None:
    """A second run over a settled pool selects nothing and dispatches nothing."""
    _corpus(tmp_path, [f"review number {i}" for i in range(7)])
    first = FakeProvider()
    assert execute_run(_config(tmp_path, supply=7), first.entry()) == 0
    bought = len(first.prompts)
    assert bought > 0

    second = FakeProvider()
    assert execute_run(_config(tmp_path, supply=7), second.entry()) == 0
    assert second.prompts == []  # the selection query is the checkpoint


def test_partial_pool_selects_only_the_remainder(tmp_path: Path) -> None:
    """Envelopes already in the pool keep their reviews out of the dispatch."""
    _corpus(tmp_path, [f"review number {i}" for i in range(6)])
    cfg = _config(tmp_path, supply=6, limit=2, max_workers=1)
    provider = FakeProvider()
    assert execute_run(cfg, provider.entry()) == 0  # buys 000 and 001 only

    rest = FakeProvider()
    assert execute_run(_config(tmp_path, supply=6, max_workers=1), rest.entry()) == 0
    dispatched = rest.dispatched_texts()
    assert len(dispatched) == 4
    assert all(f"number {i}" not in " ".join(dispatched) for i in (0, 1))


def test_failure_sweep_marks_durably_after_three_attempts(tmp_path: Path) -> None:
    """Reviews failing batched, re-batched, and alone get their durable marks.

    Two failing reviews on purpose: with one, the rebatch already isolates it
    and the isolation pass replays the identical bought response from cache —
    correct, but then the provider sees no third dispatch to assert on. Two
    failures make every pass compose a distinct batch, so each failing review
    demonstrably reaches the provider three times before its mark.
    """
    texts = ["fine game one", "FAIL alpha", "FAIL beta", "fine game two"]
    _corpus(tmp_path, texts)
    provider = FakeProvider()
    exit_code = execute_run(_config(tmp_path, supply=4, n=4, max_workers=1), provider.entry())
    assert exit_code == 0

    for failing in ("FAIL alpha", "FAIL beta"):
        assert sum(failing in p for p in provider.prompts) == 3  # initial, rebatch, isolate
    with Store(tmp_path / "pool.sqlite3") as store:
        assert store.labels.get("001", _versions()) is None  # no envelope
        assert store.labels.get("002", _versions()) is None
        assert store.reviews.unlabeled_under(_versions()) == ()  # yet not selectable
    manifest = json.loads(
        next((tmp_path / "runs").glob("*/manifest.json")).read_text(encoding="utf-8")
    )
    assert manifest["reviews"]["failed_durable"] == 2
    assert manifest["reviews"]["labeled"] == 2


def test_model_version_drift_aborts_loud(tmp_path: Path) -> None:
    """A mid-run change in the reported model version stops the run, exit 1."""
    _corpus(tmp_path, [f"review number {i}" for i in range(10)])
    provider = FakeProvider(version_for=[MODEL_ID, "deepseek-v4-flash-0921"])
    cfg = _config(tmp_path, supply=10, n=5, max_workers=1)
    assert execute_run(cfg, provider.entry()) == 1

    manifest = json.loads(
        next((tmp_path / "runs").glob("*/manifest.json")).read_text(encoding="utf-8")
    )
    assert manifest["aborted"] is not None
    assert "drift" in manifest["aborted"]
    with Store(tmp_path / "pool.sqlite3") as store:  # first batch's envelopes persist
        assert store.labels.get("000", _versions()) is not None


def test_provider_refusal_isolates_the_offending_review(tmp_path: Path) -> None:
    """A content-filter 400 walks the sweep: hostages labeled, offender marked.

    The live case (2026-07-20): DeepSeek refused a whole 10-review request over
    one review's text, and the pre-fix driver aborted the run — permanently,
    since deterministic batching re-forms the same batch every relaunch. Now
    the refusal fails the batch's rows into the ordinary sweep: the innocent
    reviews label on isolation, only the trigger review gets the durable mark,
    with the provider's refusal recorded as its reason.
    """
    texts = ["fine game one", "REFUSE tripwire text", "fine game two", "fine game three"]
    _corpus(tmp_path, texts)
    provider = FakeProvider()
    exit_code = execute_run(_config(tmp_path, supply=4, n=4, max_workers=1), provider.entry())
    assert exit_code == 0

    with Store(tmp_path / "pool.sqlite3") as store:
        assert store.labels.get("001", _versions()) is None  # the offender: marked, not labeled
        for innocent in ("000", "002", "003"):
            assert store.labels.get(innocent, _versions()) is not None
        assert store.reviews.unlabeled_under(_versions()) == ()
    manifest = json.loads(
        next((tmp_path / "runs").glob("*/manifest.json")).read_text(encoding="utf-8")
    )
    assert manifest["aborted"] is None
    assert manifest["reviews"]["failed_durable"] == 1
    assert manifest["reviews"]["labeled"] == 3
    assert manifest["reviews"]["refused_batches"] == 3  # initial, rebatch, isolate


def test_refusal_circuit_breaker_aborts_on_systemic_failure(tmp_path: Path) -> None:
    """Mass refusals mean a broken request, not toxic text — the run aborts loud."""
    _corpus(tmp_path, [f"REFUSE everything {i}" for i in range(25)])
    provider = FakeProvider()
    exit_code = execute_run(
        _config(tmp_path, supply=25, n=1, max_workers=1), provider.entry()
    )
    assert exit_code == 1
    manifest = json.loads(
        next((tmp_path / "runs").glob("*/manifest.json")).read_text(encoding="utf-8")
    )
    assert "circuit breaker" in str(manifest["aborted"])


def test_abort_cancels_the_queued_batches(tmp_path: Path) -> None:
    """After an abort, queued batches never dispatch — abort means stop.

    Pre-fix, the pool's context manager *waited* for the queue, which kept
    buying responses for 11 minutes behind tranche 2's abort. Scripted here
    via drift: the second response reports a different model version, the run
    aborts, and the provider must have seen only the few requests already in
    motion — not the 30 queued behind them.
    """
    _corpus(tmp_path, [f"review number {i}" for i in range(30)])
    provider = FakeProvider(version_for=[MODEL_ID, "deepseek-v4-flash-0921"])
    cfg = _config(tmp_path, supply=30, n=1, max_workers=1)
    assert execute_run(cfg, provider.entry()) == 1
    assert len(provider.prompts) <= 6  # in-motion slack only; 30 without the fix


def test_supply_mismatch_refuses_before_any_dispatch(tmp_path: Path) -> None:
    """The ruled-census assertion fires before money: zero provider calls."""
    _corpus(tmp_path, ["only one review"])
    provider = FakeProvider()
    assert execute_run(_config(tmp_path, supply=99), provider.entry()) == 1
    assert provider.prompts == []
    manifest = json.loads(
        next((tmp_path / "runs").glob("*/manifest.json")).read_text(encoding="utf-8")
    )
    assert "supply assertion failed" in str(manifest["aborted"])
