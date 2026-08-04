"""Marked-pool loader tests — the fresh-buy boundary's claims, on a synthetic run dir.

Each test asserts one behavioral claim over a real on-disk run directory
(manifest + review JSONLs + a label store): marked-game selection in manifest
order, the labeled-∩-usable pool with its dropped-unlabeled accounting, the
pinned-only pool-restricted aspect index, inclusive window bounds mirroring
the walk's judgment, and the fail-loud boundary (store/file divergence,
out-of-window timestamps, empty pools, marked-game-free manifests).
"""

from __future__ import annotations

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
    Review,
    ReviewClassification,
    Sentiment,
)
from steamlens.store import Store
from steamlens.studies.marked_pool import MarkedPool, load_marked_pools

_VERSIONS = ClassifierVersions(
    model_version="model-t", prompt_version="prompt-t", ontology_version="v2-test"
)
_START = datetime(2026, 1, 1, tzinfo=UTC)
_END = datetime(2026, 1, 10, tzinfo=UTC)
_RUN_ID = "freshbuy-test"


def _epoch(moment: datetime) -> int:
    return int(moment.timestamp())


def _raw(review_id: str, moment: datetime, *, language: str = "english") -> dict[str, object]:
    return {
        "recommendationid": review_id,
        "language": language,
        "review": f"review {review_id}",
        "timestamp_created": _epoch(moment),
        "voted_up": True,
    }


def _game_entry(
    app_id: int, role: str, *, start: datetime = _START, end: datetime = _END
) -> dict[str, object]:
    return {
        "app_id": app_id,
        "name": f"Game {app_id}",
        "role": role,
        "windows": [{"start": start.isoformat(), "end": end.isoformat()}],
    }


def _write_run(
    run_dir: Path,
    games: list[dict[str, object]],
    files: dict[int, list[dict[str, object]]],
) -> None:
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text(
        json.dumps({"run_id": _RUN_ID, "games": games}), encoding="utf-8"
    )
    for app_id, records in files.items():
        (run_dir / f"{app_id}_reviews.jsonl").write_text(
            "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
        )


def _label(
    store: Store,
    run: Provenance,
    review_id: str,
    app_id: int,
    mentions: tuple[AspectMention, ...],
) -> None:
    store.reviews.put_many(
        [
            Review(
                review_id=review_id,
                app_id=app_id,
                created_at=_START,
                language="english",
                text=f"review {review_id}",
                voted_up=True,
            )
        ]
    )
    store.labels.put(
        ReviewClassification(
            review_id=review_id,
            origin=Origin.SURVEY,
            versions=_VERSIONS,
            run=run,
            mentions=mentions,
        )
    )


def _mention(aspect: str, slot: AspectSlot = AspectSlot.PINNED) -> AspectMention:
    return AspectMention(aspect=aspect, slot=slot, sentiment=Sentiment.POSITIVE, evidence=None)


def _provenance() -> Provenance:
    return Provenance(
        run_id=_RUN_ID, code_version="testsha", created_at=_START, config_hash="cfg"
    )


def _standard_run(tmp_path: Path) -> Path:
    """Two marked games and a long-tail neighbor, with one unlabeled usable review.

    Game 100: r1 (labeled, mentions combat pinned + grind candidate), r2
    (labeled, empty envelope), r3 (non-English — not usable), r4 (usable but
    never labeled — the durable-refusal shape). Game 300: s1 (labeled).
    Game 200 is long-tail material the loader must ignore entirely.
    """
    run_dir = tmp_path / _RUN_ID
    _write_run(
        run_dir,
        [
            _game_entry(100, "marked-window"),
            _game_entry(200, "long-tail"),
            _game_entry(300, "marked-window"),
        ],
        {
            100: [
                _raw("r1", _START),
                _raw("r2", _END),
                _raw("r3", _START, language="russian"),
                _raw("r4", _START),
            ],
            200: [_raw("q1", _START)],
            300: [_raw("s1", _START)],
        },
    )
    with Store(run_dir / "labels.sqlite3") as store:
        run = _provenance()
        store.labels.record_run(run)
        _label(
            store,
            run,
            "r1",
            100,
            (_mention("combat"), _mention("grind", slot=AspectSlot.CANDIDATE)),
        )
        _label(store, run, "r2", 100, ())
        _label(store, run, "q1", 200, (_mention("story"),))
        _label(store, run, "s1", 300, (_mention("combat"),))
    return run_dir


def test_loads_marked_games_in_manifest_order(tmp_path: Path) -> None:
    """Only marked-window games load, ordered as the fetch ordered them."""
    pools = load_marked_pools(_standard_run(tmp_path), _VERSIONS)
    assert [pool.app_id for pool in pools] == [100, 300]
    assert pools[0].name == "Game 100"
    assert all(pool.source_run_id == _RUN_ID for pool in pools)


def test_pool_is_labeled_usable_with_dropped_accounting(tmp_path: Path) -> None:
    """The pool is labeled ∩ usable; the unlabeled usable review counts as dropped."""
    pool = load_marked_pools(_standard_run(tmp_path), _VERSIONS)[0]
    assert [review.review_id for review in pool.reviews] == ["r1", "r2"]
    assert pool.dropped_unlabeled == 1  # r4: usable, never labeled
    assert (pool.window_start, pool.window_end) == (_START, _END)


def test_aspect_index_is_pinned_only_and_pool_restricted(tmp_path: Path) -> None:
    """Candidate mentions and other games' mentions never enter the index."""
    pool = load_marked_pools(_standard_run(tmp_path), _VERSIONS)[0]
    assert pool.aspect_reviews == {"combat": frozenset({"r1"})}


def test_window_bounds_are_inclusive(tmp_path: Path) -> None:
    """Reviews created exactly at the window's ends load — the walk's zone rule.

    The standard run places r1 at the window start and r2 at the window end;
    both sit in the pool, so the check is inclusive on both sides.
    """
    pool = load_marked_pools(_standard_run(tmp_path), _VERSIONS)[0]
    created = {review.review_id: review.created_at for review in pool.reviews}
    assert created == {"r1": _START, "r2": _END}


def test_out_of_window_review_fails_loud(tmp_path: Path) -> None:
    """A labeled review outside the manifest window refutes the recorded walk."""
    run_dir = tmp_path / _RUN_ID
    _write_run(
        run_dir,
        [_game_entry(100, "marked-window")],
        {100: [_raw("r1", datetime(2026, 2, 1, tzinfo=UTC))]},
    )
    with Store(run_dir / "labels.sqlite3") as store:
        run = _provenance()
        store.labels.record_run(run)
        _label(store, run, "r1", 100, ())
    with pytest.raises(ValueError, match="outside the manifest window"):
        load_marked_pools(run_dir, _VERSIONS)


def test_labeled_review_missing_from_file_fails_loud(tmp_path: Path) -> None:
    """An envelope with no usable file row means the store and files diverged."""
    run_dir = tmp_path / _RUN_ID
    _write_run(run_dir, [_game_entry(100, "marked-window")], {100: [_raw("r1", _START)]})
    with Store(run_dir / "labels.sqlite3") as store:
        run = _provenance()
        store.labels.record_run(run)
        _label(store, run, "r1", 100, ())
        _label(store, run, "r9", 100, ())  # labeled, but absent from the JSONL
    with pytest.raises(ValueError, match="diverged"):
        load_marked_pools(run_dir, _VERSIONS)


def test_empty_pool_fails_loud(tmp_path: Path) -> None:
    """A marked game with no envelopes under the triple is a wiring failure."""
    run_dir = tmp_path / _RUN_ID
    _write_run(run_dir, [_game_entry(100, "marked-window")], {100: [_raw("r1", _START)]})
    Store(run_dir / "labels.sqlite3").close()  # a real but empty label store
    with pytest.raises(ValueError, match="no usable review holds a survey envelope"):
        load_marked_pools(run_dir, _VERSIONS)


def test_manifest_without_marked_games_fails_loud(tmp_path: Path) -> None:
    """A run dir with only long-tail games is the wrong supply for mixing."""
    run_dir = tmp_path / _RUN_ID
    _write_run(run_dir, [_game_entry(200, "long-tail")], {200: [_raw("q1", _START)]})
    Store(run_dir / "labels.sqlite3").close()
    with pytest.raises(ValueError, match="no marked-window games"):
        load_marked_pools(run_dir, _VERSIONS)


def test_multi_window_game_fails_loud(tmp_path: Path) -> None:
    """A game entry carrying two windows breaks the one-walk-per-game contract."""
    run_dir = tmp_path / _RUN_ID
    entry = _game_entry(100, "marked-window")
    entry["windows"] = [entry["windows"][0], entry["windows"][0]]  # type: ignore[index]
    _write_run(run_dir, [entry], {100: [_raw("r1", _START)]})
    with pytest.raises(ValueError, match="exactly one"):
        load_marked_pools(run_dir, _VERSIONS)


def test_result_type_is_the_published_contract(tmp_path: Path) -> None:
    """The loader returns ``MarkedPool`` records — the seam's plain-data shape."""
    pools = load_marked_pools(_standard_run(tmp_path), _VERSIONS)
    assert all(isinstance(pool, MarkedPool) for pool in pools)
