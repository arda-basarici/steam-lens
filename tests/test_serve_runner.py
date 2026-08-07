"""Behavioral claims on the serving runner — the spine, the seams, the guards.

Every test drives the real pipeline end to end over scripted seams: an
``httpx.MockTransport`` serves the Steam wire (appdetails, the two totals
reads, the histogram, and per-window review pages, routed by params) and the
``FakeProvider`` answers classification — so the claims are about the
runner's composition, not stand-ins for it. The dials come from a toy-scale
``ServeConfig`` (the config fields exist so tests exercise the real control
flow cheaply; the defaults' own claim — that they equal the study's ruled
pins — is a test here too).
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
from fakes import CollectingSink, FakeProvider

from steamlens.contracts import ClassifierVersions, StageEvent
from steamlens.core.classify import PROMPT_VERSION
from steamlens.dispatch import RunAbort
from steamlens.dispatch.census_arm import MODEL_ID
from steamlens.ontology import load_ontology_version
from steamlens.serve import AnalysisRunner, ServeConfig
from steamlens.steam_client import SteamClient, SteamClientConfig, SteamTransport
from steamlens.store import Store
from steamlens.studies.mix_corpus import RULED_SAMPLE_SIZE, TAKE_ALL_CUTOFF

_APP = 440
_NOW = datetime(2026, 8, 1, tzinfo=UTC)
_JUNE = datetime(2026, 6, 1, tzinfo=UTC)
_JULY = datetime(2026, 7, 1, tzinfo=UTC)


def _wire_review(
    review_id: str, created_at: datetime, *, language: str = "english", text: str = "good"
) -> dict[str, object]:
    return {
        "recommendationid": review_id,
        "language": language,
        "review": text,
        "timestamp_created": int(created_at.timestamp()),
        "voted_up": True,
    }


def _page_body(reviews: list[dict[str, object]], cursor: str | None, total: int) -> str:
    body: dict[str, object] = {
        "success": 1,
        "query_summary": {"total_reviews": total, "total_positive": total, "total_negative": 0},
        "reviews": reviews,
    }
    if cursor is not None:
        body["cursor"] = cursor
    return json.dumps(body)


def _totals_body(total: int) -> str:
    return json.dumps(
        {
            "success": 1,
            "query_summary": {
                "num_reviews": 0,
                "total_reviews": total,
                "total_positive": total,
                "total_negative": 0,
            },
        }
    )


def _histogram_body(buckets: list[tuple[datetime, int]]) -> str:
    return json.dumps(
        {
            "success": 1,
            "results": {
                "rollup_type": "month",
                "rollups": [
                    {
                        "date": int(start.timestamp()),
                        "recommendations_up": volume,
                        "recommendations_down": 0,
                    }
                    for start, volume in buckets
                ],
                "recent": [],
            },
        }
    )


class SteamWire:
    """The scripted Steam side: totals by language, pages by window start.

    ``pages`` maps a window's ``start_date`` epoch to its page-body sequence
    (served in order; a request beyond the script fails the test loudly); the
    ``None`` key is the wildcard for windows whose exact start the runner
    derives (the margin-shifted whole-life window). ``page_hooks`` run before
    a window's page is served — the overlap test's gating seam. ``requests``
    records every wire hit for cost/param assertions.
    """

    def __init__(
        self,
        *,
        totals_all: int,
        totals_english: int,
        buckets: list[tuple[datetime, int]],
        pages: dict[int | None, list[str]],
        page_hooks: dict[int, Callable[[], None]] | None = None,
    ) -> None:
        self.requests: list[httpx.Request] = []
        self._totals = {"all": totals_all, "english": totals_english}
        self._histogram = _histogram_body(buckets)
        self._pages = {key: iter(script) for key, script in pages.items()}
        self._hooks = dict(page_hooks or {})
        self._lock = threading.Lock()

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        with self._lock:
            self.requests.append(request)
        params = parse_qs(request.url.query.decode())
        if request.url.path == "/api/appdetails":
            return httpx.Response(
                200,
                text=json.dumps({str(_APP): {"success": True, "data": {"name": "Test Game"}}}),
            )
        if request.url.path == f"/appreviewhistogram/{_APP}":
            return httpx.Response(200, text=self._histogram)
        assert request.url.path == f"/appreviews/{_APP}", request.url.path
        if params.get("num_per_page") == ["0"]:
            return httpx.Response(200, text=_totals_body(self._totals[params["language"][0]]))
        start = params.get("start_date")
        key = int(start[0]) if start is not None else None
        if key is not None and key in self._hooks:
            self._hooks[key]()
        script = self._pages.get(key)
        if script is None:
            script = self._pages.get(None)
        assert script is not None, f"no page script for start_date {key}"
        with self._lock:
            body = next(script, None)
        assert body is not None, f"page script for start_date {key} over-fetched"
        return httpx.Response(200, text=body)


def _runner(
    wire: SteamWire, provider: FakeProvider, config: ServeConfig, db_path: Path
) -> AnalysisRunner:
    transport = SteamTransport(
        SteamClientConfig(),
        CollectingSink(),
        transport=wire.transport(),
        sleep=lambda _: None,
        monotonic=lambda: 100.0,
    )
    steam = SteamClient(transport, now=lambda: _NOW)
    return AnalysisRunner(config, steam, provider.entry(), db_path, None)


def _versions() -> ClassifierVersions:
    stamp = load_ontology_version(None)
    return ClassifierVersions(
        model_version=MODEL_ID,
        prompt_version=PROMPT_VERSION,
        ontology_version=stamp.version,
    )


def _stage_messages(sink: CollectingSink, stage: str) -> list[str]:
    return [
        event.message
        for event in sink.events
        if isinstance(event, StageEvent) and event.stage == stage
    ]


def test_take_all_labels_the_english_usable_pool(tmp_path: Path) -> None:
    """An English pool under the cutoff takes the whole game through one
    whole-life window: every English-usable review is stored, labeled under
    the production versions triple, and the account narrated — non-English
    and empty-text rows are fetched but never enter the sample."""
    reviews = [
        _wire_review("e1", _JUNE, text="great gameplay"),
        _wire_review("e2", _JUNE, text="nice gameplay"),
        _wire_review("e3", _JULY, text="story was fine"),
        _wire_review("e4", _JULY, text="   "),
        _wire_review("g1", _JULY, language="german", text="gut"),
        _wire_review("s1", _JULY, language="schinese", text="好"),
    ]
    wire = SteamWire(
        totals_all=6,
        totals_english=4,
        buckets=[(_JUNE, 3), (_JULY, 3)],
        pages={None: [_page_body(reviews, None, 6)]},
    )
    sink = CollectingSink()
    db_path = tmp_path / "serve.sqlite3"
    runner = _runner(
        wire, FakeProvider(), ServeConfig(batch_n=2, classify_workers=2), db_path
    )
    runner.run(_APP, "Test Game", sink)

    with Store(db_path) as store:
        assert store.reviews.count() == 3
        assert store.reviews.unlabeled_under(_versions()) == ()
    assert any("take-all" in m for m in _stage_messages(sink, "serve.plan"))
    assert any("3 English-usable" in m for m in _stage_messages(sink, "serve.fetch"))
    done = _stage_messages(sink, "serve.runner")
    assert any("labels banked: 3 labeled" in m for m in done)


def test_sampled_branch_stops_each_window_at_quota(tmp_path: Path) -> None:
    """Above the cutoff the certified plan runs: per-window quotas bound the
    walk (the second page of an over-supplied window is never requested),
    selection is the newest-first prefix, and the English yield below quota
    is the disclosed shortfall, not an error."""
    june_pages = [
        _page_body(
            [
                _wire_review("j1", _JUNE.replace(day=20), text="gameplay rocks"),
                _wire_review("j2", _JUNE.replace(day=18), text="gameplay again"),
                _wire_review("j3", _JUNE.replace(day=15), text="never fetched"),
            ],
            "JUNE2",
            3,
        ),
        _page_body([_wire_review("j4", _JUNE.replace(day=10))], None, 3),
    ]
    july_pages = [
        _page_body(
            [
                _wire_review("y1", _JULY.replace(day=20), text="gameplay solid"),
                _wire_review("y2", _JULY.replace(day=18), language="german", text="gut"),
            ],
            None,
            2,
        ),
    ]
    wire = SteamWire(
        totals_all=20,
        totals_english=10,
        buckets=[(_JUNE, 10), (_JULY, 10)],
        pages={
            int(_JUNE.timestamp()): june_pages,
            int(_JULY.timestamp()): july_pages,
        },
    )
    sink = CollectingSink()
    db_path = tmp_path / "serve.sqlite3"
    config = ServeConfig(take_all_cutoff=2, sample_target=4, batch_n=2, classify_workers=2)
    runner = _runner(wire, FakeProvider(), config, db_path)
    runner.run(_APP, "Test Game", sink)

    with Store(db_path) as store:
        assert store.reviews.count() == 3  # j1, j2 (quota prefix), y1 (y2 non-English)
        assert store.reviews.unlabeled_under(_versions()) == ()
    june_page_requests = [
        request
        for request in wire.requests
        if b"cursor" in request.url.query
        and f"start_date={int(_JUNE.timestamp())}".encode() in request.url.query
    ]
    assert len(june_page_requests) == 1  # quota 2 filled on page one — page two never paid
    assert any("sample n=4" in m for m in _stage_messages(sink, "serve.plan"))


def test_classify_starts_while_fetch_is_still_running(tmp_path: Path) -> None:
    """The overlap seam's live claim: the final window's wire request is
    gated on the provider having already received a batch — a sequential
    fetch-then-classify runner would deadlock here, so completion IS the
    proof of overlap."""
    provider = FakeProvider()
    overlap_seen = threading.Event()

    def wait_for_classify() -> None:
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if provider.prompts:
                overlap_seen.set()
                return
            time.sleep(0.01)

    may = datetime(2026, 5, 1, tzinfo=UTC)
    wire = SteamWire(
        totals_all=30,
        totals_english=30,
        buckets=[(may, 10), (_JUNE, 10), (_JULY, 10)],
        pages={
            int(may.timestamp()): [
                _page_body([_wire_review("m1", may.replace(day=5), text="gameplay a")], None, 10)
            ],
            int(_JUNE.timestamp()): [
                _page_body([_wire_review("j1", _JUNE.replace(day=5), text="gameplay b")], None, 10)
            ],
            int(_JULY.timestamp()): [
                _page_body([_wire_review("y1", _JULY.replace(day=5), text="gameplay c")], None, 10)
            ],
        },
        page_hooks={int(_JULY.timestamp()): wait_for_classify},
    )
    sink = CollectingSink()
    config = ServeConfig(
        take_all_cutoff=1, sample_target=3, batch_n=1, classify_workers=2, window_buffer=1
    )
    runner = _runner(wire, provider, config, tmp_path / "serve.sqlite3")
    runner.run(_APP, "Test Game", sink)

    assert overlap_seen.is_set(), "the last fetch completed without classify ever starting"


def test_page_budget_degrades_take_all_and_refuses_a_heavy_plan(tmp_path: Path) -> None:
    """The fetch-cost guard's two arms: an over-budget take-all degrades to
    the sampled draw with a WARN disclosure; a sampled plan that still busts
    the budget refuses the job loudly instead of fetching for an hour."""
    wire = SteamWire(
        totals_all=1_000,
        totals_english=2,
        buckets=[(_JUNE, 500), (_JULY, 500)],
        pages={
            int(_JUNE.timestamp()): [
                _page_body([_wire_review("j1", _JUNE.replace(day=5), text="gameplay")], None, 500)
            ],
            int(_JULY.timestamp()): [
                _page_body([_wire_review("y1", _JULY.replace(day=5), text="gameplay")], None, 500)
            ],
        },
    )
    sink = CollectingSink()
    config = ServeConfig(sample_target=2, batch_n=2, fetch_page_budget=5)
    runner = _runner(wire, FakeProvider(), config, tmp_path / "serve.sqlite3")
    runner.run(_APP, "Test Game", sink)
    warns = _stage_messages(sink, "serve.plan")
    assert any("degrading to the sampled draw" in m for m in warns)

    heavy = SteamWire(
        totals_all=100_000,
        totals_english=50_000,
        buckets=[(_JUNE, 50_000), (_JULY, 50_000)],
        pages={},
    )
    refusing = _runner(
        heavy,
        FakeProvider(),
        ServeConfig(sample_target=1_000, fetch_page_budget=3),
        tmp_path / "refuse.sqlite3",
    )
    with pytest.raises(RunAbort, match="page budget|pages against"):
        refusing.run(_APP, "Test Game", CollectingSink())


def test_serve_defaults_match_the_studies_ruled_pins() -> None:
    """The study modules pin the curves-checkpoint values locally and name
    the runtime as the source once deployment wires the policy — this is
    that must-match claim, enforced."""
    config = ServeConfig()
    assert config.take_all_cutoff == TAKE_ALL_CUTOFF
    assert config.sample_target == RULED_SAMPLE_SIZE
