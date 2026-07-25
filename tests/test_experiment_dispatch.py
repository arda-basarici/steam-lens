"""D2d cell-dispatch tests — the registered conditions proven on the shared rig.

The batch machinery itself (chunking, salvage, drift, the client seams) is
proven by the census driver's tests; these cover what the experiment driver
owns: the closed cell registry's identities (the ruled ``@nK`` tag
convention), containment (cell envelopes never touch production's untagged
triple), the render matching the cell's prompt pin, the condition-pure
retry policy (an N=10 failure re-batches at N=10 and takes its mark — the
isolate pass deliberately does not exist), the gold scope's CS2 exclusion
and text handshake, and resume-clean selection.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from test_label_corpus import FakeProvider

from steamlens.contracts import ClassifierVersions, Origin, Review
from steamlens.core.classify import (
    COMPACT_PROMPT_VERSION,
    PROMPT_VERSION,
    build_classify_prompt,
    build_classify_prompt_compact,
)
from steamlens.evals.experiment_dispatch import (
    CELLS,
    ExperimentRunConfig,
    cell_prompt_builder,
    cell_versions,
    execute_experiment_run,
)
from steamlens.ontology import load_ontology_version
from steamlens.store import Store
from steamlens.studies.label_corpus import MODEL_ID

_ONTOLOGY_PATH = Path("src/steamlens/ontology/v1.toml")
_STAMP = load_ontology_version(_ONTOLOGY_PATH)
_REVIEWS_BLOCK = re.compile(r"<reviews>\n(.*)\n</reviews>", re.DOTALL)


def _batch_size(prompt: str) -> int:
    """How many reviews one dispatched prompt carried, read off its data channel."""
    match = _REVIEWS_BLOCK.search(prompt)
    assert match, "prompt carries no <reviews> data channel"
    return len(json.loads(match.group(1)))


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


def _sample_file(tmp_path: Path, rows: list[tuple[str, str]]) -> Path:
    path = tmp_path / "sample.jsonl"
    path.write_text(
        "\n".join(
            json.dumps(
                {
                    "review_id": rid,
                    "app_id": 440,
                    "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                }
            )
            for rid, text in rows
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _gold_file(tmp_path: Path, rows: list[tuple[str, str, str]]) -> Path:
    """Rows are (review_id, app_id, text) — mentions kept empty, unused by dispatch."""
    path = tmp_path / "gold.jsonl"
    path.write_text(
        "\n".join(
            json.dumps(
                {
                    "review_id": rid,
                    "app_id": app_id,
                    "text": text,
                    "mentions": [],
                    "instructions_version": "gold-v1",
                    "ontology_version": _STAMP.version,
                    "ontology_content_hash": _STAMP.content_hash,
                }
            )
            for rid, app_id, text in rows
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _config(tmp_path: Path, cell_name: str, **overrides: object) -> ExperimentRunConfig:
    defaults: dict[str, object] = {
        "cell": CELLS[cell_name],
        "sample_path": tmp_path / "sample.jsonl",
        "gold_path": tmp_path / "gold.jsonl",
        "db_path": tmp_path / "pool.sqlite3",
        "runs_dir": tmp_path / "runs",
        "ontology_path": _ONTOLOGY_PATH,
        "max_workers": 2,
        "budget_usd": 5.0,
        "limit": None,
    }
    defaults.update(overrides)
    return ExperimentRunConfig(**defaults)  # type: ignore[arg-type]


def _manifest(tmp_path: Path) -> dict[str, object]:
    return json.loads(
        next((tmp_path / "runs").glob("*/manifest.json")).read_text(encoding="utf-8")
    )


def test_cell_registry_identities() -> None:
    """The ruled tag convention: batch condition in model_version, render per pin."""
    triples = {
        name: cell_versions(cell, "v2") for name, cell in CELLS.items()
    }
    assert triples["full-n1-gold"] == ClassifierVersions(
        f"{MODEL_ID}@n1", PROMPT_VERSION, "v2"
    )
    assert triples["full-n1-sample"] == triples["full-n1-gold"]  # one annotator, two scopes
    assert triples["compact-n10-sample"] == ClassifierVersions(
        f"{MODEL_ID}@n10", COMPACT_PROMPT_VERSION, "v2"
    )
    assert triples["compact-n1-sample"] == ClassifierVersions(
        f"{MODEL_ID}@n1", COMPACT_PROMPT_VERSION, "v2"
    )
    assert cell_prompt_builder(CELLS["full-n1-sample"]) is build_classify_prompt
    assert cell_prompt_builder(CELLS["compact-n1-sample"]) is build_classify_prompt_compact


def test_sample_cell_prompts_singly_under_tagged_triple(tmp_path: Path) -> None:
    """full-n1-sample: one request per review, full render, envelopes under the
    tagged triple only — production's untagged triple stays untouched."""
    rows = [("001", "gameplay shines here"), ("002", "nothing aspecty"), ("003", "quiet")]
    _seed_reviews(tmp_path / "pool.sqlite3", rows)
    _sample_file(tmp_path, rows)
    provider = FakeProvider()
    assert execute_experiment_run(_config(tmp_path, "full-n1-sample"), provider.entry()) == 0

    assert len(provider.prompts) == 3
    assert all(_batch_size(p) == 1 for p in provider.prompts)
    assert all("Also known as:" in p for p in provider.prompts)  # the full render
    tagged = cell_versions(CELLS["full-n1-sample"], _STAMP.version)
    production = ClassifierVersions(MODEL_ID, PROMPT_VERSION, _STAMP.version)
    with Store(tmp_path / "pool.sqlite3") as store:
        envelope = store.labels.get("001", tagged)
        assert envelope is not None and envelope.origin is Origin.SURVEY
        assert [m.aspect for m in envelope.mentions] == ["gameplay"]
        assert all(store.labels.get(rid, production) is None for rid, _ in rows)
    manifest = _manifest(tmp_path)
    assert manifest["aborted"] is None
    assert manifest["cell"] == "full-n1-sample"
    assert manifest["annotator_model_version"] == f"{MODEL_ID}@n1"
    assert manifest["wire_model"] == MODEL_ID


def test_compact_cell_batches_at_ten_under_its_own_pin(tmp_path: Path) -> None:
    """compact-n10-sample: 12 reviews → batches of 10+2, compact render, compact pin."""
    rows = [(f"{i:03d}", f"review number {i}") for i in range(12)]
    _seed_reviews(tmp_path / "pool.sqlite3", rows)
    _sample_file(tmp_path, rows)
    provider = FakeProvider()
    assert execute_experiment_run(
        _config(tmp_path, "compact-n10-sample"), provider.entry()
    ) == 0

    assert sorted(_batch_size(p) for p in provider.prompts) == [2, 10]
    assert all("Also known as:" not in p for p in provider.prompts)  # the compact render
    tagged = cell_versions(CELLS["compact-n10-sample"], _STAMP.version)
    with Store(tmp_path / "pool.sqlite3") as store:
        assert all(store.labels.get(rid, tagged) is not None for rid, _ in rows)


def test_n10_failures_rebatch_at_n_never_isolate(tmp_path: Path) -> None:
    """Condition purity: failed rows retry once at the cell's N (a 2-row batch,
    never two solo requests) and then take durable marks — no isolate pass."""
    # The two FAIL rows sit inside the first batch of ten, so the rebatch's
    # 2-row composition differs from every initial prompt — a tail-batch
    # placement would re-form an identical prompt and the content-keyed cache
    # would answer it without a dispatch, hiding the very pass under test.
    rows = [(f"{i:03d}", f"review number {i}") for i in range(8)]
    rows += [("900", "FAIL alpha"), ("901", "FAIL beta")]
    rows += [("010", "review number 10"), ("011", "review number 11")]
    _seed_reviews(tmp_path / "pool.sqlite3", rows)
    _sample_file(tmp_path, rows)
    provider = FakeProvider()
    assert execute_experiment_run(
        _config(tmp_path, "compact-n10-sample"), provider.entry()
    ) == 0

    batch_sizes = sorted(_batch_size(p) for p in provider.prompts)
    assert batch_sizes == [2, 2, 10]  # initial 10+2, then ONE rebatch of the 2 failures
    tagged = cell_versions(CELLS["compact-n10-sample"], _STAMP.version)
    with Store(tmp_path / "pool.sqlite3") as store:
        assert store.labels.get_failure("900", tagged) is not None
        assert store.labels.get_failure("901", tagged) is not None
    manifest = _manifest(tmp_path)
    reviews = manifest["reviews"]
    assert isinstance(reviews, dict)
    assert reviews["labeled"] == 10
    assert reviews["rebatched"] == 2
    assert reviews["failed_durable"] == 2


def test_n1_failure_marks_on_first_attempt(tmp_path: Path) -> None:
    """At N=1 a failure is already the isolate case: one request, straight to its mark."""
    rows = [("001", "FAIL solo")]
    _seed_reviews(tmp_path / "pool.sqlite3", rows)
    _sample_file(tmp_path, rows)
    provider = FakeProvider()
    assert execute_experiment_run(_config(tmp_path, "full-n1-sample"), provider.entry()) == 0

    assert len(provider.prompts) == 1
    tagged = cell_versions(CELLS["full-n1-sample"], _STAMP.version)
    with Store(tmp_path / "pool.sqlite3") as store:
        assert store.labels.get_failure("001", tagged) is not None


def test_resume_never_rebuys(tmp_path: Path) -> None:
    """A second run over a settled cell selects nothing and dispatches nothing."""
    rows = [("001", "review one"), ("002", "review two")]
    _seed_reviews(tmp_path / "pool.sqlite3", rows)
    _sample_file(tmp_path, rows)
    assert execute_experiment_run(
        _config(tmp_path, "full-n1-sample"), FakeProvider().entry()
    ) == 0
    second = FakeProvider()
    assert execute_experiment_run(_config(tmp_path, "full-n1-sample"), second.entry()) == 0
    assert second.prompts == []


def test_gold_scope_excludes_cs2_and_prompts_stored_text(tmp_path: Path) -> None:
    """full-n1-gold: only in-scope gold reviews dispatch; the excluded game's row
    is neither prompted nor required to exist in the store."""
    in_scope = [("001", "gameplay is tight"), ("002", "soundtrack slaps")]
    _seed_reviews(tmp_path / "pool.sqlite3", in_scope)
    _gold_file(
        tmp_path,
        [(rid, "440", text) for rid, text in in_scope]
        + [("777", "730", "cs2 review never stored")],
    )
    provider = FakeProvider()
    assert execute_experiment_run(_config(tmp_path, "full-n1-gold"), provider.entry()) == 0

    assert sorted(provider.dispatched_texts()) == sorted(text for _, text in in_scope)
    manifest = _manifest(tmp_path)
    scope = manifest["scope"]
    assert isinstance(scope, dict)
    assert scope["scope"] == "gold"
    assert scope["excluded_app_ids"] == [730]
    reviews = manifest["reviews"]
    assert isinstance(reviews, dict)
    assert reviews["in_scope"] == 2


def test_gold_text_mismatch_refuses_to_dispatch(tmp_path: Path) -> None:
    """A gold text diverging from the stored review beyond edges aborts pre-spend."""
    _seed_reviews(tmp_path / "pool.sqlite3", [("001", "what the store holds")])
    _gold_file(tmp_path, [("001", "440", "what gold claims instead")])
    provider = FakeProvider()
    assert execute_experiment_run(_config(tmp_path, "full-n1-gold"), provider.entry()) == 1
    assert provider.prompts == []
    assert "001" in str(_manifest(tmp_path)["aborted"])
