"""D2c judge-dispatch tests — the calibration orchestration proven on a fake provider.

The rig drives ``execute_judge_run`` whole: a real gold fixture, real corpus
fixture files (the backfill source), real ``Store`` connections on a temp
database, the real client with a fake ``ProviderEntry`` injected. The
load-bearing claims: every request carries exactly ONE review (the
batch-composition rider), out-of-scope gold reviews are backfilled with true
corpus metadata before any dispatch, both refusal shapes take the typed
failure path, a parse failure marks durably on first attempt (N=1 is already
the isolate case), and the gold-vs-pool text handshake refuses to dispatch
over divergent text.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path

import pytest

import steamlens.evals.judge_gold as judge_gold
from steamlens.contracts import (
    ClassifierVersions,
    FinishReason,
    LlmResponse,
    Origin,
    TokenUsage,
)
from steamlens.core.classify import PROMPT_VERSION
from steamlens.evals.judge_gold import (
    JUDGE_MODEL_ID,
    JudgeRunConfig,
    execute_judge_run,
)
from steamlens.llm_client import ProviderEntry, ProviderPayload, ProviderPermanentError
from steamlens.ontology import load_ontology_version
from steamlens.store import Store

_ONTOLOGY_PATH = Path("src/steamlens/ontology/v1.toml")
_STAMP = load_ontology_version(_ONTOLOGY_PATH)
_REVIEWS_BLOCK = re.compile(r"<reviews>\n(.*)\n</reviews>", re.DOTALL)


@pytest.fixture(autouse=True)
def unthrottled_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """The live RPM backstop is real pacing — pointless seconds in a fake-provider rig."""
    monkeypatch.setattr(judge_gold, "_RPM", 100_000)


class FakeGemini:
    """A scripted judge-provider stand-in: answers per review text, records dispatches.

    Text markers script the failure shapes: ``REFUSE`` raises the
    request-level rejection, ``SAFETYBLOCK`` answers a Gemini-shaped
    generation refusal (``REFUSAL`` finish, empty body), ``MALFORMED``
    answers non-JSON. ``version_for`` scripts the reported model version per
    call so drift is testable.
    """

    def __init__(self, version_for: list[str] | None = None) -> None:
        self.prompts: list[str] = []
        self._versions = version_for or []
        self._lock = threading.Lock()

    def entry(self) -> ProviderEntry:
        return ProviderEntry(build_payload=self._build, send=self._send, parse=self._parse)

    @staticmethod
    def batch(prompt: str) -> list[tuple[int, str]]:
        match = _REVIEWS_BLOCK.search(prompt)
        assert match, "prompt carries no <reviews> data channel"
        rows = json.loads(match.group(1))
        return [(int(row["idx"]), str(row["text"])) for row in rows]

    def _build(
        self, *, model: str, prompt: str, max_output_tokens: int, params: dict[str, object]
    ) -> ProviderPayload:
        return {"model": model, "prompt": prompt}

    def _send(self, *, model: str, payload: ProviderPayload) -> str:
        prompt = str(payload["prompt"])
        with self._lock:
            call_index = len(self.prompts)
            self.prompts.append(prompt)
        if "REFUSE" in prompt:
            raise ProviderPermanentError("gemini HTTP 400: blocked request")
        version = (
            self._versions[call_index] if call_index < len(self._versions) else JUDGE_MODEL_ID
        )
        if "SAFETYBLOCK" in prompt:
            return json.dumps({"model_version": version, "finish": "refusal", "answers": None})
        if "MALFORMED" in prompt:
            return json.dumps({"model_version": version, "finish": "stop", "answers": "oops"})
        answers = [
            {"idx": idx, "aspects": self._aspects_for(text)}
            for idx, text in self.batch(prompt)
        ]
        return json.dumps({"model_version": version, "finish": "stop", "answers": answers})

    @staticmethod
    def _aspects_for(text: str) -> list[dict[str, str]]:
        if "gameplay" in text:
            return [{"aspect": "gameplay", "sentiment": "positive"}]
        return []

    @staticmethod
    def _parse(raw: str) -> LlmResponse:
        body = json.loads(raw)
        if body["finish"] == "refusal":
            return LlmResponse(
                text="",
                model_version=str(body["model_version"]),
                finish_reason=FinishReason.REFUSAL,
                usage=TokenUsage(prompt_tokens=100, output_tokens=0, thinking_tokens=0),
            )
        text = "not json at all" if body["answers"] == "oops" else json.dumps(body["answers"])
        return LlmResponse(
            text=text,
            model_version=str(body["model_version"]),
            finish_reason=FinishReason.STOP,
            usage=TokenUsage(prompt_tokens=100, output_tokens=20, thinking_tokens=0),
        )


def _corpus(tmp_path: Path, texts_by_app: dict[int, list[tuple[str, str]]]) -> Path:
    """Corpus fixture files: ``{app_id: [(review_id, text), ...]}``."""
    corpus = tmp_path / "corpus"
    corpus.mkdir(exist_ok=True)
    for app_id, rows in texts_by_app.items():
        lines = [
            json.dumps(
                {
                    "recommendationid": rid,
                    "language": "english",
                    "review": text,
                    "timestamp_created": 1_781_279_000,
                    "voted_up": True,
                }
            )
            for rid, text in rows
        ]
        (corpus / f"{app_id}_reviews.jsonl").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )
    return corpus


def _gold(tmp_path: Path, records: list[tuple[str, str, str]]) -> Path:
    """Gold fixture: ``(review_id, app_id, text)`` rows, no mentions needed —
    the driver reads identity and text; truth only matters to the scorer."""
    gold_path = tmp_path / "gold.jsonl"
    gold_path.write_text(
        "\n".join(
            json.dumps(
                {
                    "review_id": rid,
                    "app_id": app,
                    "text": text,
                    "mentions": [],
                    "instructions_version": "gold-v1",
                    "ontology_version": _STAMP.version,
                    "ontology_content_hash": _STAMP.content_hash,
                }
            )
            for rid, app, text in records
        )
        + "\n",
        encoding="utf-8",
    )
    return gold_path


def _config(tmp_path: Path, **overrides: object) -> JudgeRunConfig:
    defaults: dict[str, object] = {
        "gold_path": tmp_path / "gold.jsonl",
        "corpus_dir": tmp_path / "corpus",
        "db_path": tmp_path / "pool.sqlite3",
        "runs_dir": tmp_path / "runs",
        "ontology_path": _ONTOLOGY_PATH,
        "max_workers": 2,
        "budget_usd": 1.0,
        "limit": None,
    }
    defaults.update(overrides)
    return JudgeRunConfig(**defaults)  # type: ignore[arg-type]


def _versions() -> ClassifierVersions:
    return ClassifierVersions(
        model_version=JUDGE_MODEL_ID,
        prompt_version=PROMPT_VERSION,
        ontology_version=_STAMP.version,
    )


def _manifest(tmp_path: Path) -> dict[str, object]:
    return json.loads(
        next((tmp_path / "runs").glob("*/manifest.json")).read_text(encoding="utf-8")
    )


def test_happy_path_judges_singly_and_backfills(tmp_path: Path) -> None:
    """Four gold reviews across two games: one request per review, all enveloped.

    The empty database is the strongest backfill case — every gold review is
    missing, and all four must arrive from their corpus files with true
    metadata before dispatch. The single-review rider is asserted on the
    wire: every dispatched prompt's data channel carries exactly one row.
    """
    rows_440 = [("001", "gameplay shines here"), ("002", "nothing aspecty to say")]
    rows_730 = [("cs1", "cs2 gameplay row"), ("cs2", "another quiet row")]
    _corpus(tmp_path, {440: rows_440, 730: rows_730})
    _gold(tmp_path, [(rid, "440", t) for rid, t in rows_440]
          + [(rid, "730", t) for rid, t in rows_730])
    provider = FakeGemini()
    assert execute_judge_run(_config(tmp_path), provider.entry()) == 0

    assert len(provider.prompts) == 4
    assert all(len(FakeGemini.batch(p)) == 1 for p in provider.prompts)
    with Store(tmp_path / "pool.sqlite3") as store:
        for rid in ("001", "002", "cs1", "cs2"):
            review = store.reviews.get(rid)
            assert review is not None and review.language == "english"  # true metadata
        envelope = store.labels.get("001", _versions())
        assert envelope is not None and envelope.origin is Origin.SURVEY
        assert [m.aspect for m in envelope.mentions] == ["gameplay"]
        quiet = store.labels.get("002", _versions())
        assert quiet is not None and quiet.mentions == ()
    manifest = _manifest(tmp_path)
    assert manifest["aborted"] is None
    reviews = manifest["reviews"]
    assert isinstance(reviews, dict)
    assert reviews["backfilled"] == 4
    assert reviews["labeled"] == 4
    assert reviews["empty_envelopes"] == 2  # 002 and cs2 carry no aspect talk
    assert manifest["model_versions_seen"] == [JUDGE_MODEL_ID]


def test_resume_never_rejudges(tmp_path: Path) -> None:
    """A second run over a settled judge set selects nothing and dispatches nothing."""
    rows = [("001", "review one"), ("002", "review two")]
    _corpus(tmp_path, {440: rows})
    _gold(tmp_path, [(rid, "440", t) for rid, t in rows])
    first = FakeGemini()
    assert execute_judge_run(_config(tmp_path), first.entry()) == 0
    assert len(first.prompts) == 2

    second = FakeGemini()
    assert execute_judge_run(_config(tmp_path), second.entry()) == 0
    assert second.prompts == []


def test_both_refusal_shapes_take_the_typed_path(tmp_path: Path) -> None:
    """A request rejection and a safety-block finish both mark durably, run survives."""
    rows = [("001", "fine game"), ("002", "REFUSE tripwire"), ("003", "SAFETYBLOCK text")]
    _corpus(tmp_path, {440: rows})
    _gold(tmp_path, [(rid, "440", t) for rid, t in rows])
    provider = FakeGemini()
    assert execute_judge_run(_config(tmp_path, max_workers=1), provider.entry()) == 0

    with Store(tmp_path / "pool.sqlite3") as store:
        assert store.labels.get("001", _versions()) is not None
        for refused_id in ("002", "003"):
            assert store.labels.get(refused_id, _versions()) is None
            assert store.labels.get_failure(refused_id, _versions()) is not None
    reviews = _manifest(tmp_path)["reviews"]
    assert isinstance(reviews, dict)
    assert reviews["refused"] == 2
    assert reviews["failed_durable"] == 2
    assert reviews["labeled"] == 1


def test_malformed_answer_marks_durably_on_first_attempt(tmp_path: Path) -> None:
    """N=1 is already the isolate case: no retry pass, straight to the mark."""
    rows = [("001", "fine game"), ("002", "MALFORMED answer please")]
    _corpus(tmp_path, {440: rows})
    _gold(tmp_path, [(rid, "440", t) for rid, t in rows])
    provider = FakeGemini()
    assert execute_judge_run(_config(tmp_path, max_workers=1), provider.entry()) == 0

    assert sum("MALFORMED" in p for p in provider.prompts) == 1  # exactly one attempt
    with Store(tmp_path / "pool.sqlite3") as store:
        assert store.labels.get_failure("002", _versions()) is not None


def test_refusal_circuit_breaker_aborts_on_systemic_failure(tmp_path: Path) -> None:
    """Mass refusals mean a broken request, not toxic gold — the run aborts loud."""
    rows = [(f"{i:03d}", f"REFUSE everything {i}") for i in range(8)]
    _corpus(tmp_path, {440: rows})
    _gold(tmp_path, [(rid, "440", t) for rid, t in rows])
    provider = FakeGemini()
    assert execute_judge_run(_config(tmp_path, max_workers=1), provider.entry()) == 1
    assert "circuit breaker" in str(_manifest(tmp_path)["aborted"])


def test_text_mismatch_refuses_before_any_dispatch(tmp_path: Path) -> None:
    """Gold text diverging from the stored review text aborts with zero requests."""
    _corpus(tmp_path, {440: [("001", "the corpus wording")]})
    _gold(tmp_path, [("001", "440", "different gold wording")])
    provider = FakeGemini()
    assert execute_judge_run(_config(tmp_path), provider.entry()) == 1
    assert provider.prompts == []
    assert "never read" in str(_manifest(tmp_path)["aborted"])


def test_edge_whitespace_difference_is_not_a_mismatch(tmp_path: Path) -> None:
    """The gold draw stripped edges; a raw corpus row still passes the handshake."""
    _corpus(tmp_path, {440: [("001", "  the same wording \r\n")]})
    _gold(tmp_path, [("001", "440", "the same wording")])
    provider = FakeGemini()
    assert execute_judge_run(_config(tmp_path), provider.entry()) == 0
    assert len(provider.prompts) == 1


def test_gold_id_missing_from_corpus_refuses_before_any_dispatch(tmp_path: Path) -> None:
    """A gold id its corpus file cannot supply aborts the backfill loudly."""
    _corpus(tmp_path, {440: [("001", "present review")]})
    _gold(tmp_path, [("001", "440", "present review"), ("ghost", "440", "no such row")])
    provider = FakeGemini()
    assert execute_judge_run(_config(tmp_path), provider.entry()) == 1
    assert provider.prompts == []
    assert "ghost" in str(_manifest(tmp_path)["aborted"])


def test_model_version_drift_aborts_loud(tmp_path: Path) -> None:
    """A mid-run change in the reported model version stops the run, exit 1."""
    rows = [(f"{i:03d}", f"review number {i}") for i in range(6)]
    _corpus(tmp_path, {440: rows})
    _gold(tmp_path, [(rid, "440", t) for rid, t in rows])
    provider = FakeGemini(version_for=[JUDGE_MODEL_ID, "gemini-3-flash-0930"])
    assert execute_judge_run(_config(tmp_path, max_workers=1), provider.entry()) == 1
    assert "drift" in str(_manifest(tmp_path)["aborted"])


def test_limit_is_the_pilot_dial(tmp_path: Path) -> None:
    """--limit judges only the first K gold reviews; the rest stay selectable."""
    rows = [(f"{i:03d}", f"review number {i}") for i in range(5)]
    _corpus(tmp_path, {440: rows})
    _gold(tmp_path, [(rid, "440", t) for rid, t in rows])
    pilot = FakeGemini()
    assert execute_judge_run(_config(tmp_path, limit=2), pilot.entry()) == 0
    assert len(pilot.prompts) == 2

    rest = FakeGemini()
    assert execute_judge_run(_config(tmp_path), rest.entry()) == 0
    assert len(rest.prompts) == 3  # only the remainder — resume composes with limit
