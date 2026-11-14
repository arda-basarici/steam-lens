"""Behavioral claims on the sheet's store-facing shell — what a request is read against.

Each test seeds a library in a real store file and reads it back through the
shell. The claims: a game is represented by its newest report, a capture that
is still owed arrives as ``None`` and not as an empty one, and a request's
search terms are each searched once.

Reports are seeded with direct inserts. The shell reads only a report's
scalar columns and its aggregate rows, so the display payloads take the
smallest values the table accepts.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from steamlens.contracts import (
    AspectTarget,
    Firmness,
    MustStanding,
    PlayerRequest,
    RequestIntent,
    SentimentGroup,
    Stance,
    StoreFactTarget,
    StorefrontLabel,
    StorefrontMetadata,
    StorefrontTag,
    StorefrontTagCapture,
    TermTarget,
    Want,
    WantFinding,
    WantStatus,
    WantTarget,
)
from steamlens.serve.chat_sheet import load_library, sheet_for, term_hit_counts
from steamlens.store import Store, utc_isoformat

_NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
_HADES, _STARDEW = 1145360, 413150


def _publish(
    path: Path,
    app_id: int,
    name: str,
    aspects: dict[str, tuple[int, int]],
    *,
    created_at: datetime = _NOW,
    sample_size: int = 600,
) -> str:
    """One published report for ``app_id`` with pinned aggregates; returns its run id.

    ``aspects`` maps an aspect to its positive and negative mention counts.
    """
    run_id = f"serve-{app_id}-{created_at:%Y%m%dT%H%M%S}"
    conn = sqlite3.connect(path)
    with conn:
        conn.execute(
            "INSERT INTO runs (run_id, code_version, created_at, config_hash)"
            " VALUES (?, 'abc1234', ?, 'cfg')",
            (run_id, utc_isoformat(created_at)),
        )
        conn.execute(
            "INSERT INTO reports (run_id, app_id, game_name, created_at, model_version,"
            " prompt_version, ontology_version, sample_size, take_all, windowed_windows,"
            " fallback_windows, skipped_windows, narrative_outcome, narrative_json,"
            " histogram_json, episodes_json, language_mix_json, marked_windows_json,"
            " fetch_windows_json) VALUES (?, ?, ?, ?, 'labeler-b', 'p', 'v2', ?, 1, 1, 0, 0,"
            " 'withheld', '{}', '{}', '[]', '[]', '[]', '[]')",
            (run_id, app_id, name, utc_isoformat(created_at), sample_size),
        )
        conn.executemany(
            "INSERT INTO aggregate_snapshots (run_id, aspect, slot, reviews_with_aspect,"
            " positive, negative, mixed, neutral, sample_size)"
            " VALUES (?, ?, 'pinned', ?, ?, ?, 0, 0, ?)",
            [
                (run_id, aspect, positive + negative, positive, negative, sample_size)
                for aspect, (positive, negative) in aspects.items()
            ],
        )
    conn.close()
    return run_id


def _metadata(app_id: int, *categories: StorefrontLabel) -> StorefrontMetadata:
    return StorefrontMetadata(
        app_id=app_id,
        genres=(StorefrontLabel(1, "Action"),),
        categories=(StorefrontLabel(2, "Single-player"), *categories),
        windows=True, mac=False, linux=False,
        release_date_text="Sep 17, 2020", release_date=date(2020, 9, 17),
        coming_soon=False, short_description="", captured_at=_NOW,
    )


def _want(target: WantTarget, firmness: Firmness = Firmness.MUST) -> Want:
    return Want(words="as said", firmness=firmness, stance=Stance.WANTS, target=target)


def test_a_game_is_read_from_its_newest_report(tmp_path: Path) -> None:
    """A re-run replaces what the game is read from: the cells, the sample
    size and the report's identity all come from the later report."""
    path = tmp_path / "steamlens.sqlite3"
    with Store(path):
        pass
    _publish(path, _HADES, "Hades", {"story": (2, 40)}, created_at=_NOW - timedelta(days=30))
    newest = _publish(path, _HADES, "Hades", {"story": (60, 5), "combat": (41, 4)},
                      sample_size=602)
    with Store(path) as store:
        (hades,) = load_library(store)
    assert (hades.run_id, hades.sample_size, hades.reported_at) == (newest, 602, _NOW)
    assert (hades.name, hades.labeler, hades.complete_count) == ("Hades", "labeler-b", True)
    assert [(cell.aspect, cell.group) for cell in hades.cells] == [
        ("combat", SentimentGroup.STRONGLY_POSITIVE),
        ("story", SentimentGroup.STRONGLY_POSITIVE),
    ]


def test_an_owed_capture_is_none_and_a_captured_empty_tag_block_is_not(tmp_path: Path) -> None:
    """The reading rules tell "never read" from "read, and empty": only the
    first withholds a genre failure. The shell must not blur them."""
    path = tmp_path / "steamlens.sqlite3"
    with Store(path) as store:
        store.storefront.put_metadata(_metadata(_HADES))
        store.storefront.put_tags(StorefrontTagCapture(app_id=_HADES, tags=(), captured_at=_NOW))
        store.storefront.put_tags(StorefrontTagCapture(
            app_id=_STARDEW, tags=(StorefrontTag(1, "Farming Sim", 900),), captured_at=_NOW,
        ))
    _publish(path, _HADES, "Hades", {})
    _publish(path, _STARDEW, "Stardew Valley", {})
    with Store(path) as store:
        stardew, hades = load_library(store)
    assert (stardew.app_id, hades.app_id) == (_STARDEW, _HADES), "ordered by app id"
    assert hades.storefront == _metadata(_HADES)
    assert hades.tags is not None and hades.tags.tags == ()
    assert stardew.storefront is None
    assert stardew.tags is not None and stardew.tags.tags[0].name == "Farming Sim"


def test_each_distinct_search_term_is_searched_once_and_other_wants_are_not(
    tmp_path: Path,
) -> None:
    timer = TermTarget(phrases=("timer", "timed"))
    request = PlayerRequest(
        intent=RequestIntent.RECOMMEND,
        wants=(
            _want(timer),
            _want(AspectTarget("story")),
            _want(TermTarget(phrases=("timer", "timed"))),
            _want(StoreFactTarget("online-co-op")),
        ),
    )
    with Store(tmp_path / "steamlens.sqlite3") as store:
        assert term_hit_counts(store, request) == {timer: {}}


def test_the_sheet_for_a_request_reads_the_stored_library(tmp_path: Path) -> None:
    """End to end over a store file: a store fact from the metadata, an
    aspect from the newest report, a term from review search. No review is
    stored here, so the term is one reviews do not go into."""
    path = tmp_path / "steamlens.sqlite3"
    with Store(path) as store:
        store.storefront.put_metadata(_metadata(_HADES))
        store.storefront.put_metadata(_metadata(_STARDEW, StorefrontLabel(38, "Online Co-op")))
    _publish(path, _HADES, "Hades", {"story": (60, 5)})
    _publish(path, _STARDEW, "Stardew Valley", {"story": (3, 0)})
    request = PlayerRequest(
        intent=RequestIntent.RECOMMEND,
        wants=(
            _want(StoreFactTarget("online-co-op")),
            _want(AspectTarget("story"), Firmness.WANT),
            _want(TermTarget(phrases=("curling",))),
        ),
    )
    with Store(path) as store:
        sheet = sheet_for(store, request)

    stardew, hades = sheet.rows
    assert (stardew.game.name, stardew.standing) == ("Stardew Valley", MustStanding.OPEN)
    assert (hades.game.name, hades.standing) == ("Hades", MustStanding.CONFLICTS)
    assert [reading.status for reading in hades.readings] == [
        WantStatus.FAILS, WantStatus.MATCHES, WantStatus.CANNOT_TELL,
    ]
    assert [reading.finding for reading in stardew.readings] == [
        WantFinding.LISTED, WantFinding.ASPECT_GROUP, WantFinding.NOT_WRITTEN_ABOUT,
    ]
    assert stardew.readings[1].group is SentimentGroup.TOO_FEW_MENTIONS
