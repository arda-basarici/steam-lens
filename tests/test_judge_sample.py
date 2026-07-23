"""Census-sample judge-dispatch tests — the sample shell proven on the shared rig.

The engine (single-review dispatch, refusal shapes, durable marks) is proven
by the calibration shell's tests over the same ``dispatch_items``; these
cover what the sample shell owns: the sample loader's boundary checks, the
sample-vs-store sha256 handshake (missing and drifted rows both refuse to
dispatch), prompting from *stored* text, and resume-clean selection.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from test_judge_gold import FakeGemini

import steamlens.evals.judge_dispatch as judge_dispatch
from steamlens.contracts import ClassifierVersions, Origin, Review
from steamlens.core.classify import PROMPT_VERSION
from steamlens.evals.judge_dispatch import JUDGE_MODEL_ID
from steamlens.evals.judge_sample import (
    SampleRunConfig,
    execute_sample_run,
    load_sample,
)
from steamlens.ontology import load_ontology_version
from steamlens.store import Store

_ONTOLOGY_PATH = Path("src/steamlens/ontology/v1.toml")
_STAMP = load_ontology_version(_ONTOLOGY_PATH)


@pytest.fixture(autouse=True)
def unthrottled_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """The live RPM backstop is real pacing — pointless seconds in a fake-provider rig."""
    monkeypatch.setattr(judge_dispatch, "_RPM", 100_000)


def _seed_reviews(db_path: Path, rows: list[tuple[str, str]]) -> None:
    with Store(db_path) as store:
        store.reviews.put_many(
            Review(
                review_id=rid,
                app_id=440,
                created_at=datetime(2026, 6, 1, tzinfo=UTC),
                language="english",
                text=text,
                voted_up=True,
            )
            for rid, text in rows
        )


def _sample_file(
    tmp_path: Path, rows: list[tuple[str, str]], *, break_hash_for: str | None = None
) -> Path:
    path = tmp_path / "sample.jsonl"
    lines: list[str] = []
    for i, (rid, text) in enumerate(rows, start=1):
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if rid == break_hash_for:
            digest = "0" * 64
        lines.append(
            json.dumps({"item": i, "review_id": rid, "app_id": 440, "text_sha256": digest})
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _config(tmp_path: Path, **overrides: object) -> SampleRunConfig:
    defaults: dict[str, object] = {
        "sample_path": tmp_path / "sample.jsonl",
        "db_path": tmp_path / "pool.sqlite3",
        "runs_dir": tmp_path / "runs",
        "ontology_path": _ONTOLOGY_PATH,
        "max_workers": 2,
        "budget_usd": 6.0,
        "limit": None,
    }
    defaults.update(overrides)
    return SampleRunConfig(**defaults)  # type: ignore[arg-type]


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


def test_happy_path_prompts_stored_text_singly(tmp_path: Path) -> None:
    """Three sampled reviews: one request each, prompted from the store's text,
    envelopes landing under the judge triple with survey origin."""
    rows = [("001", "gameplay shines here"), ("002", "nothing aspecty"), ("003", "quiet")]
    _seed_reviews(tmp_path / "pool.sqlite3", rows)
    _sample_file(tmp_path, rows)
    provider = FakeGemini()
    assert execute_sample_run(_config(tmp_path), provider.entry()) == 0

    assert len(provider.prompts) == 3
    batches = [FakeGemini.batch(p) for p in provider.prompts]
    assert all(len(batch) == 1 for batch in batches)
    assert {text for batch in batches for _, text in batch} == {t for _, t in rows}
    with Store(tmp_path / "pool.sqlite3") as store:
        envelope = store.labels.get("001", _versions())
        assert envelope is not None and envelope.origin is Origin.SURVEY
        assert [m.aspect for m in envelope.mentions] == ["gameplay"]
    manifest = _manifest(tmp_path)
    assert manifest["aborted"] is None
    reviews = manifest["reviews"]
    assert isinstance(reviews, dict)
    assert reviews["sampled"] == 3
    assert reviews["labeled"] == 3
    assert reviews["empty_envelopes"] == 2


def test_drifted_text_refuses_to_dispatch(tmp_path: Path) -> None:
    """A stored text that no longer hashes to its minted pin aborts before any request."""
    rows = [("001", "original text"), ("002", "still fine")]
    _seed_reviews(tmp_path / "pool.sqlite3", rows)
    _sample_file(tmp_path, rows, break_hash_for="001")
    provider = FakeGemini()
    assert execute_sample_run(_config(tmp_path), provider.entry()) == 1
    assert provider.prompts == []
    assert "001" in str(_manifest(tmp_path)["aborted"])


def test_missing_review_refuses_to_dispatch(tmp_path: Path) -> None:
    """A sampled id absent from the store aborts — the frame no longer exists."""
    rows = [("001", "present"), ("ghost", "never ingested")]
    _seed_reviews(tmp_path / "pool.sqlite3", rows[:1])
    _sample_file(tmp_path, rows)
    provider = FakeGemini()
    assert execute_sample_run(_config(tmp_path), provider.entry()) == 1
    assert provider.prompts == []
    assert "ghost" in str(_manifest(tmp_path)["aborted"])


def test_resume_never_rejudges(tmp_path: Path) -> None:
    """A second run over a settled sample selects nothing and dispatches nothing."""
    rows = [("001", "review one"), ("002", "review two")]
    _seed_reviews(tmp_path / "pool.sqlite3", rows)
    _sample_file(tmp_path, rows)
    assert execute_sample_run(_config(tmp_path), FakeGemini().entry()) == 0
    second = FakeGemini()
    assert execute_sample_run(_config(tmp_path), second.entry()) == 0
    assert second.prompts == []


def test_loader_rejects_duplicates_and_bad_hashes(tmp_path: Path) -> None:
    path = tmp_path / "sample.jsonl"
    good = {"review_id": "001", "app_id": 440, "text_sha256": "a" * 64}
    path.write_text(json.dumps(good) + "\n" + json.dumps(good) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        load_sample(path)
    path.write_text(
        json.dumps({"review_id": "001", "app_id": 440, "text_sha256": "zz"}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="hex"):
        load_sample(path)
