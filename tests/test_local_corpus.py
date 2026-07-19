"""Local-corpus reader tests — the usable filter's claims and the boundary's teeth.

Unit tests exercise the pure predicate and the record conversion directly;
file-level tests write tiny JSONL fixtures under ``tmp_path`` so the drop
arithmetic, the fail-loud lines, and the excluded-game walk are proven on real
files rather than mocks.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from steamlens.studies import (
    EXCLUDED_APP_IDS,
    corpus_review_files,
    has_content,
    read_reviews_file,
    review_from_raw,
)


def _raw(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "recommendationid": "227797385",
        "language": "english",
        "review": "Great gunplay, terrible servers.",
        "timestamp_created": 1_781_279_000,
        "voted_up": True,
    }
    record.update(overrides)
    return record


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n", encoding="utf-8"
    )


def test_has_content_accepts_real_text() -> None:
    """Ordinary review text — including non-Latin scripts — counts as content."""
    assert has_content("gud game 10/10")
    assert has_content("ок\n")  # Cyrillic: non-Latin is content, not emptiness


def test_has_content_rejects_invisible_text() -> None:
    """Whitespace, controls, and format characters alone are emptiness."""
    assert not has_content("")
    assert not has_content(" \t\n ")
    assert not has_content("​﻿")  # zero-width space, control, BOM


def test_review_from_raw_maps_fields() -> None:
    """The conversion: id verbatim, epoch to aware UTC, verdict preserved."""
    review = review_from_raw(_raw(voted_up=False), app_id=440)
    assert review.review_id == "227797385"
    assert review.app_id == 440
    assert review.created_at == datetime.fromtimestamp(1_781_279_000, tz=UTC)
    assert review.created_at.tzinfo is not None
    assert review.language == "english"
    assert review.voted_up is False


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"recommendationid": None}, "recommendationid"),
        ({"recommendationid": ""}, "recommendationid"),
        ({"timestamp_created": "1781279000"}, "timestamp_created"),
        ({"timestamp_created": True}, "timestamp_created"),  # bool is not an epoch
        ({"voted_up": 1}, "voted_up"),
        ({"review": None}, "review text"),
    ],
)
def test_review_from_raw_fails_loud(overrides: dict[str, object], match: str) -> None:
    """A mistyped field in a frozen-corpus record is damage, not a skippable row."""
    with pytest.raises(ValueError, match=match):
        review_from_raw(_raw(**overrides), app_id=440)


def test_read_reviews_file_counts_reconcile(tmp_path: Path) -> None:
    """The drop arithmetic: total = non-English + empty + usable, in file order."""
    path = tmp_path / "440_reviews.jsonl"
    _write_jsonl(
        path,
        [
            _raw(recommendationid="1", review="Solid movement tech."),
            _raw(recommendationid="2", language="russian", review="ок"),
            _raw(recommendationid="3", review="​ \n"),  # English but invisible
            _raw(recommendationid="4", review="Matchmaking is broken."),
        ],
    )
    result = read_reviews_file(path)
    assert result.app_id == 440
    assert (result.total, result.non_english, result.empty, result.usable) == (4, 1, 1, 2)
    assert result.total == result.non_english + result.empty + result.usable
    assert [r.review_id for r in result.reviews] == ["1", "4"]


def test_read_reviews_file_missing_review_field_counts_empty(tmp_path: Path) -> None:
    """A record with no review text lands in ``empty`` — the ruling's accounting."""
    path = tmp_path / "440_reviews.jsonl"
    record = _raw(recommendationid="5")
    del record["review"]
    _write_jsonl(path, [record])
    result = read_reviews_file(path)
    assert (result.total, result.empty, result.usable) == (1, 1, 0)


def test_read_reviews_file_skips_blank_lines_uncounted(tmp_path: Path) -> None:
    """Blank lines are file-format artifacts, invisible to the arithmetic."""
    path = tmp_path / "440_reviews.jsonl"
    path.write_text(
        "\n" + json.dumps(_raw()) + "\n\n" + json.dumps(_raw(recommendationid="9")) + "\n\n",
        encoding="utf-8",
    )
    result = read_reviews_file(path)
    assert (result.total, result.usable) == (2, 2)


def test_read_reviews_file_undecodable_line_names_the_line(tmp_path: Path) -> None:
    """Corruption fails loud with file and line — never a silently skipped row."""
    path = tmp_path / "440_reviews.jsonl"
    path.write_text(json.dumps(_raw()) + "\n{not json\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"440_reviews\.jsonl line 2"):
        read_reviews_file(path)


def test_read_reviews_file_rejects_unparseable_filename(tmp_path: Path) -> None:
    """A file the app-id convention can't name is refused, not guessed at."""
    path = tmp_path / "notes_reviews.jsonl"
    _write_jsonl(path, [_raw()])
    with pytest.raises(ValueError, match="notes_reviews.jsonl"):
        read_reviews_file(path)


def test_corpus_review_files_excludes_and_sorts(tmp_path: Path) -> None:
    """The walk covers exactly the usable games: CS2 dropped, order deterministic."""
    for app_id in (570, 730, 440):
        _write_jsonl(tmp_path / f"{app_id}_reviews.jsonl", [_raw()])
    files = corpus_review_files(tmp_path)
    assert [f.name for f in files] == ["440_reviews.jsonl", "570_reviews.jsonl"]
    assert 730 in EXCLUDED_APP_IDS


def test_corpus_review_files_refuses_empty_walk(tmp_path: Path) -> None:
    """A missing directory or a matchless glob is an error, not a no-op ingest."""
    with pytest.raises(ValueError, match="does not exist"):
        corpus_review_files(tmp_path / "nowhere")
    with pytest.raises(ValueError, match="no \\*_reviews\\.jsonl"):
        corpus_review_files(tmp_path)
