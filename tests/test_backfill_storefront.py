"""Behavioral claims on the storefront backfill — owed games only, and the app goes first.

Each test seeds a library in a real store file, scripts the Steam wire through
``httpx.MockTransport``, and runs the real backfill over the real door. The
claims: the library is read from the published reports, a game is asked only
for the record it lacks, one game's trouble does not stop the rest, and the
run yields to a live analysis job both before it starts and between games.

Reports are seeded with a direct insert. Only three columns matter to the
backfill (the app id, the name, the creation time); the rest take the
smallest values the table accepts.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
from fakes import CollectingSink

from steamlens.contracts import (
    StageEvent,
    StorefrontLabel,
    StorefrontMetadata,
    StorefrontTag,
    StorefrontTagCapture,
)
from steamlens.serve.backfill_storefront import backfill, live_job
from steamlens.steam_client import SteamClient, SteamClientConfig, SteamTransport
from steamlens.store import Store, utc_isoformat

_NOW = datetime(2026, 11, 14, 18, 0, tzinfo=UTC)
_HADES, _DOOM, _STARDEW = 1145360, 782330, 413150


def _publish(path: Path, app_id: int, name: str, *, created_at: datetime = _NOW) -> None:
    """One published report row for ``app_id``, so the game is in the library."""
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
            " fetch_windows_json) VALUES (?, ?, ?, ?, 'm', 'p', 'v2', 10, 0, 1, 0, 0,"
            " 'withheld', '{}', '{}', '[]', '[]', '[]', '[]')",
            (run_id, app_id, name, utc_isoformat(created_at)),
        )
    conn.close()


def _metadata(app_id: int) -> StorefrontMetadata:
    return StorefrontMetadata(
        app_id=app_id,
        genres=(StorefrontLabel(1, "Action"),),
        categories=(StorefrontLabel(2, "Single-player"),),
        windows=True, mac=False, linux=False,
        release_date_text="Mar 19, 2020", release_date=date(2020, 3, 19),
        coming_soon=False, short_description="", captured_at=_NOW,
    )


class Wire:
    """A healthy store for every app, with per-path overrides and a request log."""

    def __init__(
        self,
        *,
        overrides: dict[str, httpx.Response] | None = None,
        on_request: Callable[[str], None] | None = None,
    ) -> None:
        self.paths: list[str] = []
        self._overrides = overrides or {}
        self._on_request = on_request

    def client(self) -> SteamClient:
        transport = SteamTransport(
            SteamClientConfig(),
            CollectingSink(),
            transport=httpx.MockTransport(self._handle),
            sleep=lambda _: None,
            monotonic=lambda: 100.0,
        )
        return SteamClient(transport, now=lambda: _NOW)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/appdetails":
            path = f"/api/appdetails/{request.url.params['appids']}"
        self.paths.append(path)
        if self._on_request is not None:
            self._on_request(path)
        if path in self._overrides:
            return self._overrides[path]
        app_id = path.rstrip("/").rsplit("/", 1)[-1]
        if path.startswith("/api/appdetails/"):
            return httpx.Response(200, text=json.dumps({app_id: {"success": True, "data": {
                "name": "A Game",
                "genres": [{"id": "1", "description": "Action"}],
                "categories": [{"id": 2, "description": "Single-player"}],
                "platforms": {"windows": True, "mac": False, "linux": False},
                "release_date": {"coming_soon": False, "date": "Mar 19, 2020"},
            }}}))
        return httpx.Response(
            200,
            text=f'InitAppTagModal( {app_id}, [{{"tagid":1,"name":"Action","count":9}}], [] );',
        )


def _messages(sink: CollectingSink) -> list[str]:
    return [event.message for event in sink.events if isinstance(event, StageEvent)]


def test_reads_the_library_from_the_reports_and_asks_only_what_is_owed(tmp_path: Path) -> None:
    """Three library games: one with nothing captured, one whose metadata
    already landed, one complete. The first costs two reads, the second one,
    the third none, and afterwards nothing is owed."""
    path = tmp_path / "serve.db"
    with Store(path) as store:
        _publish(path, _HADES, "Hades (old name)", created_at=_NOW - timedelta(days=90))
        _publish(path, _HADES, "Hades")
        _publish(path, _DOOM, "DOOM Eternal")
        _publish(path, _STARDEW, "Stardew Valley")
        store.storefront.put_metadata(_metadata(_DOOM))
        store.storefront.put_metadata(_metadata(_STARDEW))
        store.storefront.put_tags(
            StorefrontTagCapture(
                app_id=_STARDEW, tags=(StorefrontTag(1, "Farming Sim", 9),), captured_at=_NOW
            )
        )
        wire = Wire()
        steam = wire.client()

        owed = store.storefront.uncaptured_library_games()
        assert [(g.app_id, g.name, g.needs_metadata, g.needs_tags) for g in owed] == [
            (_DOOM, "DOOM Eternal", False, True),
            (_HADES, "Hades", True, True),
        ], "one row per game, named by its newest report"

        tally = backfill(steam, store, CollectingSink(), now=lambda: _NOW)

        assert wire.paths == [
            f"/app/{_DOOM}/",
            f"/api/appdetails/{_HADES}",
            f"/app/{_HADES}/",
        ]
        assert (tally.games_read, tally.metadata_stored, tally.tags_stored) == (2, 1, 2)
        assert (tally.left, tally.stopped_for) == (0, None)
        assert store.storefront.uncaptured_library_games() == ()


def test_one_games_store_trouble_leaves_it_owed_and_the_rest_captured(tmp_path: Path) -> None:
    path = tmp_path / "serve.db"
    redirect = httpx.Response(302, headers={"location": "https://store.steampowered.com/"})
    with Store(path) as store:
        _publish(path, _DOOM, "DOOM Eternal")
        _publish(path, _HADES, "Hades")
        wire = Wire(overrides={f"/app/{_DOOM}/": redirect})
        sink = CollectingSink()

        tally = backfill(wire.client(), store, sink, now=lambda: _NOW)

        assert (tally.games_read, tally.metadata_stored, tally.tags_stored) == (2, 2, 1)
        assert tally.left == 1
        [still_owed] = store.storefront.uncaptured_library_games()
        assert (still_owed.app_id, still_owed.needs_metadata, still_owed.needs_tags) == (
            _DOOM, False, True,
        )
        assert store.storefront.tags(_HADES) is not None
        assert any("HTTP 302" in message for message in _messages(sink))


def test_refuses_while_an_analysis_is_live_and_ignores_an_orphan(tmp_path: Path) -> None:
    """A job that started five minutes ago is running, so nothing is read. An
    unsettled row from two hours ago is a process death's trace and blocks
    nothing."""
    path = tmp_path / "serve.db"
    with Store(path) as store:
        _publish(path, _HADES, "Hades")
        store.jobs.start("serve-orphan", 570, "Dota 2", at=_NOW - timedelta(hours=2))
        assert live_job(store, _NOW) is None

        store.jobs.start("serve-live", 440, "Team Fortress 2", at=_NOW - timedelta(minutes=5))
        wire = Wire()
        sink = CollectingSink()
        tally = backfill(wire.client(), store, sink, now=lambda: _NOW)

        assert wire.paths == []
        assert tally.stopped_for is not None and tally.stopped_for.app_id == 440
        assert (tally.games_read, tally.left) == (0, 1)
        assert any("an analysis is live (Team Fortress 2" in m for m in _messages(sink))

        store.jobs.settle(
            "serve-live", at=_NOW, outcome="done", error=None, labeled=1, reused=0,
            failed_durable=0, refused_batches=0, stage_timings_json=None,
        )
        assert backfill(wire.client(), store, sink, now=lambda: _NOW).left == 0


def test_a_job_that_starts_mid_run_stops_the_backfill_at_the_next_game(tmp_path: Path) -> None:
    """The live check runs between games: the game in flight finishes, the
    next is never asked, and a second run picks it up."""
    path = tmp_path / "serve.db"
    with Store(path) as store, Store(path) as app_side:
        _publish(path, _DOOM, "DOOM Eternal")
        _publish(path, _HADES, "Hades")

        def a_visitor_submits(request_path: str) -> None:
            if request_path == f"/app/{_DOOM}/":
                app_side.jobs.start("serve-live", 440, "Team Fortress 2", at=_NOW)

        wire = Wire(on_request=a_visitor_submits)
        tally = backfill(wire.client(), store, CollectingSink(), now=lambda: _NOW)

        assert wire.paths == [f"/api/appdetails/{_DOOM}", f"/app/{_DOOM}/"]
        assert tally.stopped_for is not None
        assert (tally.games_read, tally.left) == (1, 1)
        assert [g.app_id for g in store.storefront.uncaptured_library_games()] == [_HADES]


def test_only_restricts_the_run_to_one_game(tmp_path: Path) -> None:
    path = tmp_path / "serve.db"
    with Store(path) as store:
        _publish(path, _DOOM, "DOOM Eternal")
        _publish(path, _HADES, "Hades")
        wire = Wire()

        tally = backfill(wire.client(), store, CollectingSink(), now=lambda: _NOW, only=_DOOM)

        assert wire.paths == [f"/api/appdetails/{_DOOM}", f"/app/{_DOOM}/"]
        assert (tally.games_read, tally.left) == (1, 0), "left counts the selection only"
        assert [g.app_id for g in store.storefront.uncaptured_library_games()] == [_HADES]
