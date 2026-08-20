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
from fakes import CollectingSink, FakeProvider, prompt_batch

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
_HEADER_ART = (
    "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/440/"
    "abf6e7b3b01ed20c35a8dc0a009a8f9fc3e57b93/header.jpg?t=1768303991"
)
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


def _histogram_body(
    buckets: list[tuple[datetime, int]],
    events: list[tuple[datetime, datetime]] | None = None,
) -> str:
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
            "past_events": [
                {
                    "type": 1,
                    "start_date": int(start.timestamp()),
                    "end_date": int(end.timestamp()),
                }
                for start, end in (events or [])
            ],
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
        events: list[tuple[datetime, datetime]] | None = None,
    ) -> None:
        self.requests: list[httpx.Request] = []
        self._totals = {"all": totals_all, "english": totals_english}
        self._histogram = _histogram_body(buckets, events)
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
                text=json.dumps({str(_APP): {"success": True, "data": {
                    "name": "Test Game", "header_image": _HEADER_ART,
                }}}),
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
    summary = runner.run(_APP, "Test Game", sink, run_id="serve-premint-1")

    with Store(db_path) as store:
        assert store.reviews.count() == 3
        assert store.reviews.unlabeled_under(_versions()) == ()
        report = store.reports.latest_report(_APP)
        assert report is not None
        assert report.run.run_id == "serve-premint-1", (
            "the pre-minted id IS the report's run id — jobs/reports/ledger join on it"
        )
    assert any("take-all" in m for m in _stage_messages(sink, "serve.plan"))
    assert any("3 English-usable" in m for m in _stage_messages(sink, "serve.fetch"))
    done = _stage_messages(sink, "serve.runner")
    assert any("labels banked: 3 labeled" in m for m in done)
    assert (summary.labeled, summary.reused, summary.failed_durable) == (3, 0, 0), (
        "the returned summary is what the journal wrapper settles with"
    )


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


def test_mint_and_compose_extend_the_spine(tmp_path: Path) -> None:
    """After labels bank, the mint folds the run's own labels read back from
    the store and the fenced narrative composes over them: the mint narration
    carries the top aspect at its true count, the compose prompt offers the
    stored evidence spans, and the gate-passed prose (numerals absent, the
    quotation verbatim from evidence) reaches the sink."""
    texts = [f"quotable gameplay that keeps pulling me back {i}" for i in range(5)]
    reviews = [
        _wire_review(f"e{i}", _JUNE, text=text) for i, text in enumerate(texts)
    ]
    wire = SteamWire(
        totals_all=5,
        totals_english=5,
        buckets=[(_JUNE, 5)],
        pages={None: [_page_body(reviews, None, 5)]},
    )
    sink = CollectingSink()
    provider = FakeProvider(
        compose_prose='Players say "quotable gameplay that keeps pulling me back" often.'
    )
    runner = _runner(
        wire, provider, ServeConfig(batch_n=2, classify_workers=2),
        tmp_path / "serve.sqlite3",
    )
    runner.run(_APP, "Test Game", sink)

    assert any("gameplay 5/5" in m for m in _stage_messages(sink, "serve.mint"))
    compose = _stage_messages(sink, "serve.compose")
    assert any("narrative grounded clean" in m for m in compose)
    assert provider.compose_prose in compose  # the PROGRESS event carrying the prose
    compose_prompts = [p for p in provider.prompts if "<evidence>" in p]
    assert len(compose_prompts) == 1
    assert "quotable gameplay that keeps pulling me back 0" in compose_prompts[0]
    assert "complete count of all 5 reviews" in compose_prompts[0]


def test_below_floor_selection_withholds_without_a_compose_call(tmp_path: Path) -> None:
    """Three mentions under the default floor of five: the mint still narrates,
    the narrative is withheld disclosed, and no compose prompt is ever paid."""
    reviews = [
        _wire_review(f"e{i}", _JUNE, text=f"great gameplay {i}") for i in range(3)
    ]
    wire = SteamWire(
        totals_all=3,
        totals_english=3,
        buckets=[(_JUNE, 3)],
        pages={None: [_page_body(reviews, None, 3)]},
    )
    sink = CollectingSink()
    provider = FakeProvider()
    runner = _runner(
        wire, provider, ServeConfig(batch_n=2, classify_workers=2),
        tmp_path / "serve.sqlite3",
    )
    runner.run(_APP, "Test Game", sink)

    assert any("minted 1 aspect" in m for m in _stage_messages(sink, "serve.mint"))
    assert any(
        "no aspect cleared the evidence floor" in m
        for m in _stage_messages(sink, "serve.compose")
    )
    assert all("<evidence>" not in p for p in provider.prompts)


def test_completed_job_publishes_the_report_whole(tmp_path: Path) -> None:
    """Completion publishes everything the page shows in one transaction: the
    report row (narrative outcome recorded, fetch provenance at the ruled
    grain, language mix), the frozen aggregate snapshot, detected episode
    markers with the Valve-overlap fact, and the members-inside count per
    marked window — and the instant read path serves it back whole."""
    quiet = [(datetime(2026, month, 1, tzinfo=UTC), 50) for month in range(1, 7)]
    event = (_JULY.replace(day=5), _JULY.replace(day=20))
    inside = [
        _wire_review(f"in{i}", _JULY.replace(day=10), text=f"quotable gameplay wow {i}")
        for i in range(2)
    ]
    outside = [
        _wire_review(f"out{i}", _JUNE.replace(day=10), text=f"quotable gameplay yes {i}")
        for i in range(3)
    ]
    wire = SteamWire(
        totals_all=5,
        totals_english=5,
        buckets=[*quiet, (_JULY, 900)],
        pages={None: [_page_body([*inside, *outside], None, 5)]},
        events=[event],
    )
    sink = CollectingSink()
    db_path = tmp_path / "serve.sqlite3"
    runner = _runner(
        wire, FakeProvider(), ServeConfig(batch_n=2, classify_workers=2), db_path
    )
    runner.run(_APP, "Test Game", sink)

    assert any(
        "1 span(s) of unusual review volume" in m
        for m in _stage_messages(sink, "serve.detect")
    )
    assert any("report published" in m for m in _stage_messages(sink, "serve.report"))
    with Store(db_path) as store:
        report = store.reports.latest_report(_APP)
        assert report is not None
        assert report.game_name == "Test Game"
        assert report.header_image == _HEADER_ART, (
            "the resolve read's art URL must reach the published report"
        )
        assert report.sample_size == 5
        assert report.take_all is True
        assert report.versions == _versions()
        assert [w.outcome.value for w in report.windows] == ["windowed"]
        assert report.language_mix[0].language == "english"
        assert report.narrative.outcome.value == "composed"
        assert "gameplay" in report.narrative.prose
        [episode] = report.episodes
        assert episode.start == _JULY
        assert episode.reviews == 900
        assert episode.overlaps_marked_window is True
        [marked] = report.marked_window_counts
        assert (marked.start, marked.end) == event
        assert marked.members_inside == 2
        [aggregate] = store.reports.get_snapshot(report.run.run_id)
        assert aggregate.aspect == "gameplay"
        assert aggregate.reviews_with_aspect == 5
        assert aggregate.sample_size == 5
        assert aggregate.manifest_id == report.run.run_id


def test_job_that_classified_nothing_publishes_no_report(tmp_path: Path) -> None:
    """No members, no numbers, no report row — the next request re-queues
    honestly instead of reading an empty publication."""
    wire = SteamWire(
        totals_all=1,
        totals_english=0,
        buckets=[(_JUNE, 1)],
        pages={None: [_page_body([_wire_review("g1", _JUNE, language="german")], None, 1)]},
    )
    db_path = tmp_path / "serve.sqlite3"
    runner = _runner(wire, FakeProvider(), ServeConfig(batch_n=2), db_path)
    runner.run(_APP, "Test Game", CollectingSink())
    with Store(db_path) as store:
        assert store.reports.latest_report(_APP) is None


def test_second_job_reuses_labels_and_pays_only_for_new_reviews(tmp_path: Path) -> None:
    """The re-run collision fix end to end: a second job on the same game
    files its own manifest, skips every member the pool already answers for
    (no duplicate-envelope death, no re-buy), classifies only the genuinely
    new reviews, and still mints the FULL sample's numbers — prior runs'
    labels count through membership."""
    texts = [f"quotable gameplay that keeps pulling me back {i}" for i in range(5)]
    first_batch = [_wire_review(f"e{i}", _JUNE, text=text) for i, text in enumerate(texts)]
    db_path = tmp_path / "serve.sqlite3"
    config = ServeConfig(batch_n=2, classify_workers=2)

    first_wire = SteamWire(
        totals_all=5, totals_english=5, buckets=[(_JUNE, 5)],
        pages={None: [_page_body(first_batch, None, 5)]},
    )
    _runner(first_wire, FakeProvider(), config, db_path).run(
        _APP, "Test Game", CollectingSink()
    )

    new_reviews = [
        _wire_review("n1", _JULY, text="fresh gameplay six"),
        _wire_review("n2", _JULY, text="fresh gameplay seven"),
    ]
    second_wire = SteamWire(
        totals_all=7, totals_english=7, buckets=[(_JUNE, 5), (_JULY, 2)],
        pages={None: [_page_body([*new_reviews, *first_batch], None, 7)]},
    )
    second_provider = FakeProvider()
    sink = CollectingSink()
    _runner(second_wire, second_provider, config, db_path).run(_APP, "Test Game", sink)

    classify_prompts = [p for p in second_provider.prompts if "<evidence>" not in p]
    dispatched = [
        text for prompt in classify_prompts for _, text in prompt_batch(prompt)
    ]
    assert sorted(dispatched) == ["fresh gameplay seven", "fresh gameplay six"]
    done = _stage_messages(sink, "serve.runner")
    assert any(
        "labels banked: 2 labeled" in m and "5 verdicts re-used" in m for m in done
    )
    assert any("gameplay 7/7" in m for m in _stage_messages(sink, "serve.mint"))
    with Store(db_path) as store:
        latest = store.reports.latest_report(_APP)
        assert latest is not None
        assert latest.sample_size == 7  # both jobs published; newest row serves


def test_serve_defaults_match_the_studies_ruled_pins() -> None:
    """The study modules pin the curves-checkpoint values locally and name
    the runtime as the source once deployment wires the policy — this is
    that must-match claim, enforced."""
    config = ServeConfig()
    assert config.take_all_cutoff == TAKE_ALL_CUTOFF
    assert config.sample_target == RULED_SAMPLE_SIZE
