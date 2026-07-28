"""D2d cell-dispatch tests — the registered conditions proven on the shared rig.

The batch machinery itself (chunking, salvage, drift, the client seams) is
proven by the census driver's tests; these cover what the experiment driver
owns: the closed cell registry's identities (the ruled ``@nK`` tag
convention), containment (cell envelopes never touch production's untagged
triple), the render matching the cell's prompt pin, the condition-pure
retry policy (an N=10 failure re-batches once at exactly N, the sub-N
remainder takes durable marks, the recomposed cell never retries — the
isolate pass deliberately does not exist), the gold scope's CS2 exclusion
and text handshake, resume-clean selection, and the settled-filler skip a
re-formed recomposed batch depends on.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from fakes import FakeProvider, prompt_batch, seed_reviews

from steamlens.contracts import (
    ClassifierVersions,
    Origin,
    Provenance,
    ReviewClassification,
)
from steamlens.core.classify import (
    COMPACT_PROMPT_VERSION,
    PROMPT_VERSION,
    build_classify_prompt,
    build_classify_prompt_compact,
)
from steamlens.dispatch.census_arm import MODEL_ID
from steamlens.evals.experiment_dispatch import (
    CELLS,
    ExperimentRunConfig,
    cell_prompt_builder,
    cell_versions,
    execute_experiment_run,
    recomposed_batches,
)
from steamlens.ontology import load_ontology_version
from steamlens.store import Store

_ONTOLOGY_PATH = Path("src/steamlens/ontology/v1.toml")
_STAMP = load_ontology_version(_ONTOLOGY_PATH)


def _batch_size(prompt: str) -> int:
    """How many reviews one dispatched prompt carried, read off its data channel."""
    return len(prompt_batch(prompt))


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
    seed_reviews(tmp_path / "pool.sqlite3", rows)
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
    seed_reviews(tmp_path / "pool.sqlite3", rows)
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


def test_n10_failures_rebatch_at_exactly_n_and_the_remainder_marks(tmp_path: Path) -> None:
    """Condition purity: failed rows retry once at exactly the cell's N — a
    full ten-row rebatch, never an off-size request under the @n10 tag — and
    the sub-N remainder goes straight to durable marks, with every dispatched
    rebatch size disclosed in the manifest."""
    # Twelve FAIL rows split across the two initial batches: the rebatch
    # re-chunks them into one full N=10 request (a composition no initial
    # prompt had, so the content-keyed cache cannot answer it) plus a 2-row
    # remainder that must never be dispatched.
    rows = [(f"a{i:02d}", f"review number {i}") for i in range(4)]
    rows += [(f"x{i:02d}", f"FAIL alpha {i}") for i in range(6)]
    rows += [(f"b{i:02d}", f"review number {10 + i}") for i in range(4)]
    rows += [(f"y{i:02d}", f"FAIL beta {i}") for i in range(6)]
    seed_reviews(tmp_path / "pool.sqlite3", rows)
    _sample_file(tmp_path, rows)
    provider = FakeProvider()
    assert execute_experiment_run(
        _config(tmp_path, "compact-n10-sample"), provider.entry()
    ) == 0

    batch_sizes = sorted(_batch_size(p) for p in provider.prompts)
    assert batch_sizes == [10, 10, 10]  # initial 10+10, then ONE full-N rebatch
    tagged = cell_versions(CELLS["compact-n10-sample"], _STAMP.version)
    failed_ids = [rid for rid, text in rows if "FAIL" in text]
    with Store(tmp_path / "pool.sqlite3") as store:
        assert all(store.labels.get_failure(rid, tagged) is not None for rid in failed_ids)
    manifest = _manifest(tmp_path)
    reviews = manifest["reviews"]
    assert isinstance(reviews, dict)
    assert reviews["labeled"] == 8
    assert reviews["rebatched"] == 10
    assert reviews["rebatch_sizes"] == [10]
    assert reviews["failed_durable"] == 12  # 10 retried + the 2-row remainder


def test_n1_failure_marks_on_first_attempt(tmp_path: Path) -> None:
    """At N=1 a failure is already the isolate case: one request, straight to its mark."""
    rows = [("001", "FAIL solo")]
    seed_reviews(tmp_path / "pool.sqlite3", rows)
    _sample_file(tmp_path, rows)
    provider = FakeProvider()
    assert execute_experiment_run(_config(tmp_path, "full-n1-sample"), provider.entry()) == 0

    assert len(provider.prompts) == 1
    tagged = cell_versions(CELLS["full-n1-sample"], _STAMP.version)
    with Store(tmp_path / "pool.sqlite3") as store:
        assert store.labels.get_failure("001", tagged) is not None


def test_limit_caps_the_dispatch(tmp_path: Path) -> None:
    """--limit is the pilot dial that caps the first live spend of a cell —
    one dispatch, and the manifest discloses the cap."""
    rows = [("001", "review one"), ("002", "review two"), ("003", "review three")]
    seed_reviews(tmp_path / "pool.sqlite3", rows)
    _sample_file(tmp_path, rows)
    provider = FakeProvider()
    assert execute_experiment_run(
        _config(tmp_path, "full-n1-sample", limit=1), provider.entry()
    ) == 0
    assert len(provider.prompts) == 1
    manifest = _manifest(tmp_path)
    assert manifest["limit"] == 1
    reviews = manifest["reviews"]
    assert isinstance(reviews, dict)
    assert reviews["selected"] == 1


def test_resume_never_rebuys(tmp_path: Path) -> None:
    """A second run over a settled cell selects nothing and dispatches nothing."""
    rows = [("001", "review one"), ("002", "review two")]
    seed_reviews(tmp_path / "pool.sqlite3", rows)
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
    seed_reviews(tmp_path / "pool.sqlite3", in_scope)
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


def test_recomposed_composition_is_seeded_same_game_and_fresh(tmp_path: Path) -> None:
    """Each batch: exactly one gold review among nine same-game fillers, fillers
    never reused across batches, and the whole composition regenerable byte-for-byte."""
    gold = [("g01", "gameplay is tight"), ("g02", "soundtrack slaps")]
    fillers = [(f"f{i:02d}", f"filler review {i}") for i in range(18)]
    seed_reviews(tmp_path / "pool.sqlite3", gold + fillers)
    seed_reviews(tmp_path / "pool.sqlite3", [("x01", "other game")], app_id=570)
    _gold_file(tmp_path, [(rid, "440", text) for rid, text in gold])
    cfg = _config(tmp_path, "full-n10-gold-recomposed")

    with Store(tmp_path / "pool.sqlite3") as store:
        batches, gold_ids, descriptor = recomposed_batches(cfg, store)
        again, _, _ = recomposed_batches(cfg, store)
    assert batches == again  # seeded — a resume re-forms identical batches
    assert gold_ids == {"g01", "g02"}
    assert descriptor["n_topup_cross_game"] == 0
    seen_fillers: set[str] = set()
    for batch in batches:
        assert len(batch) == 10
        members_gold = [r.review_id for r in batch if r.review_id in gold_ids]
        members_fill = [r for r in batch if r.review_id not in gold_ids]
        assert len(members_gold) == 1
        assert all(r.app_id == 440 for r in members_fill)  # same-game fillers
        assert seen_fillers.isdisjoint(r.review_id for r in members_fill)
        seen_fillers.update(r.review_id for r in members_fill)


def test_recomposed_tops_up_cross_game_when_short(tmp_path: Path) -> None:
    """A game too small for nine same-game fillers tops up from the corpus, disclosed."""
    seed_reviews(tmp_path / "pool.sqlite3", [("g01", "gameplay is tight")])
    seed_reviews(
        tmp_path / "pool.sqlite3", [(f"f{i}", f"same game {i}") for i in range(5)]
    )
    seed_reviews(
        tmp_path / "pool.sqlite3",
        [(f"x{i}", f"other game {i}") for i in range(10)],
        app_id=570,
    )
    _gold_file(tmp_path, [("g01", "440", "gameplay is tight")])

    with Store(tmp_path / "pool.sqlite3") as store:
        batches, _, descriptor = recomposed_batches(
            _config(tmp_path, "full-n10-gold-recomposed"), store
        )
    assert descriptor["n_topup_cross_game"] == 4
    (batch,) = batches
    same_game = [r for r in batch if r.app_id == 440 and r.review_id != "g01"]
    cross_game = [r for r in batch if r.app_id == 570]
    assert len(batch) == 10
    assert len(same_game) == 5 and len(cross_game) == 4


def test_recomposed_dispatch_lands_batch_and_resumes(tmp_path: Path) -> None:
    """The recomposed cell dispatches N=10 batches under the full @n10 triple —
    gold and filler envelopes both land — and a second run selects nothing."""
    gold = [("g01", "gameplay is tight")]
    fillers = [(f"f{i:02d}", f"filler review {i}") for i in range(9)]
    seed_reviews(tmp_path / "pool.sqlite3", gold + fillers)
    _gold_file(tmp_path, [("g01", "440", "gameplay is tight")])
    provider = FakeProvider()
    assert execute_experiment_run(
        _config(tmp_path, "full-n10-gold-recomposed"), provider.entry()
    ) == 0

    assert [_batch_size(p) for p in provider.prompts] == [10]
    assert all("Also known as:" in p for p in provider.prompts)  # the full render
    tagged = cell_versions(CELLS["full-n10-gold-recomposed"], _STAMP.version)
    with Store(tmp_path / "pool.sqlite3") as store:
        assert store.labels.get("g01", tagged) is not None
        assert all(store.labels.get(rid, tagged) is not None for rid, _ in fillers)
    manifest = _manifest(tmp_path)
    assert manifest["aborted"] is None
    assert manifest["annotator_model_version"] == f"{MODEL_ID}@n10"
    reviews = manifest["reviews"]
    assert isinstance(reviews, dict)
    assert reviews["in_scope"] == 1  # gold-anchored batches
    assert reviews["labeled"] == 10  # gold + fillers

    second = FakeProvider()
    assert execute_experiment_run(
        _config(tmp_path, "full-n10-gold-recomposed"), second.entry()
    ) == 0
    assert second.prompts == []


def test_recomposed_resume_skips_a_settled_filler(tmp_path: Path) -> None:
    """The skip_settled guard, exercised: a re-formed batch containing an
    already-settled filler skips that write instead of crashing on the
    duplicate-write guard — the exact state an aborted run leaves behind
    (fillers settled, the gold member not), and the manifest discloses it."""
    gold = [("g01", "gameplay is tight")]
    fillers = [(f"f{i:02d}", f"filler review {i}") for i in range(9)]
    seed_reviews(tmp_path / "pool.sqlite3", gold + fillers)
    _gold_file(tmp_path, [("g01", "440", "gameplay is tight")])
    tagged = cell_versions(CELLS["full-n10-gold-recomposed"], _STAMP.version)
    prior = Provenance(
        run_id="prior-aborted-run",
        code_version="test",
        created_at=datetime(2026, 7, 1, tzinfo=UTC),
        config_hash="prior",
    )
    with Store(tmp_path / "pool.sqlite3") as store:
        store.labels.record_run(prior)
        store.labels.put(
            ReviewClassification(
                review_id="f00", origin=Origin.SURVEY, versions=tagged,
                run=prior, mentions=(),
            )
        )

    provider = FakeProvider()
    assert execute_experiment_run(
        _config(tmp_path, "full-n10-gold-recomposed"), provider.entry()
    ) == 0

    assert [_batch_size(p) for p in provider.prompts] == [10]  # the batch re-forms whole
    with Store(tmp_path / "pool.sqlite3") as store:
        assert store.labels.get("g01", tagged) is not None
    manifest = _manifest(tmp_path)
    assert manifest["aborted"] is None
    reviews = manifest["reviews"]
    assert isinstance(reviews, dict)
    assert reviews["labeled"] == 9  # the settled filler is skipped, not re-written
    assert reviews["skipped_settled"] == 1


def test_gold_text_mismatch_refuses_to_dispatch(tmp_path: Path) -> None:
    """A gold text diverging from the stored review beyond edges aborts pre-spend."""
    seed_reviews(tmp_path / "pool.sqlite3", [("001", "what the store holds")])
    _gold_file(tmp_path, [("001", "440", "what gold claims instead")])
    provider = FakeProvider()
    assert execute_experiment_run(_config(tmp_path, "full-n1-gold"), provider.entry()) == 1
    assert provider.prompts == []
    assert "001" in str(_manifest(tmp_path)["aborted"])
