"""Behavioral claims on the page renderer — view models and the rendered page.

Two layers, tested at their own grain. The view builders are pure (contracts
in, display records out), so their claims run with no app: the narrative cut
exactly along its certificate, whiskers through the certified shipped
interval and absent for take-all, the candidate stratum's singleton fold, the
quote cap's dominant-polarity preference, timeline geometry on a linear time
axis, and the trust panel's disclosures. The page tests drive the real app
over httpx's in-process ASGI transport and claim the sections land in HTML
with hostile content inert. The boundary test is load-bearing: the rendering
ruling says a frontend swap touches ``serve.web`` alone, which stays true
only while the JSON surface never imports the renderer — the import-graph law
ranks whole subpackages and cannot see an edge inside ``serve``, so the wall
gets its own static scan here.
"""

from __future__ import annotations

import ast
import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response

from steamlens.contracts import (
    AspectAggregate,
    AspectSlot,
    ClassifierVersions,
    ComposedNarrative,
    EpisodeMarker,
    EvidenceQuote,
    GroundedSpan,
    HistogramBucket,
    HistogramSnapshot,
    LanguageCount,
    MarkedWindowCount,
    NarrativeOutcome,
    PathOutcome,
    Provenance,
    Report,
    ReviewEvent,
    RollupUnit,
    Sentiment,
    SentimentCounts,
    SpanKind,
    WindowAccount,
)
from steamlens.core.allowance import shipped_interval
from steamlens.serve.web import ReportPageData, attach_web
from steamlens.serve.web.view import (
    build_report_view,
    narrative_segments,
    provenance_line,
)

_SERVE_DIR = Path(__file__).resolve().parent.parent / "src" / "steamlens" / "serve"
_STAMP = datetime(2026, 8, 1, tzinfo=UTC)
_VERSIONS = ClassifierVersions(
    model_version="deepseek-v4-flash", prompt_version="p3", ontology_version="v2"
)


def _bucket(year: int, month: int, up: int, down: int = 0) -> HistogramBucket:
    return HistogramBucket(
        start=datetime(year, month, 1, tzinfo=UTC),
        recommendations_up=up,
        recommendations_down=down,
    )


def _histogram(
    buckets: tuple[HistogramBucket, ...],
    events: tuple[ReviewEvent, ...] = (),
) -> HistogramSnapshot:
    return HistogramSnapshot(
        app_id=440, rollup_unit=RollupUnit.MONTH, rollups=buckets,
        recent_daily=(), past_events=events, fetched_at=_STAMP,
    )


# A calm three-year spread: no bucket close to the ⅔ spiky boundary.
_CALM_BUCKETS = tuple(
    _bucket(2023 + (m // 12), (m % 12) + 1, 40 + m, 5) for m in range(30)
)


def _aggregate(
    aspect: str,
    reviews: int,
    *,
    slot: AspectSlot = AspectSlot.PINNED,
    sample_size: int = 1_000,
) -> AspectAggregate:
    return AspectAggregate(
        app_id=440, aspect=aspect, slot=slot, reviews_with_aspect=reviews,
        counts=SentimentCounts(positive=reviews, negative=0, mixed=0, neutral=0),
        sample_size=sample_size, versions=_VERSIONS, manifest_id="serve-test",
    )


def _report(
    *,
    game_name: str = "Team Fortress 2",
    narrative: ComposedNarrative | None = None,
    take_all: bool = False,
    sample_size: int = 1_000,
    histogram: HistogramSnapshot | None = None,
    episodes: tuple[EpisodeMarker, ...] = (),
    marked: tuple[MarkedWindowCount, ...] = (),
) -> Report:
    return Report(
        run=Provenance(
            run_id="serve-test", code_version="abc1234", created_at=_STAMP,
            config_hash="cfg",
        ),
        app_id=440,
        game_name=game_name,
        created_at=_STAMP,
        versions=_VERSIONS,
        sample_size=sample_size,
        take_all=take_all,
        windows=(
            WindowAccount(start=_STAMP, end=_STAMP, outcome=PathOutcome.WINDOWED),
            WindowAccount(start=_STAMP, end=_STAMP, outcome=PathOutcome.FALLBACK_WALKED),
        ),
        language_mix=(LanguageCount("english", 900), LanguageCount("schinese", 300)),
        narrative=narrative
        or ComposedNarrative(prose="", spans=(), outcome=NarrativeOutcome.WITHHELD),
        histogram=histogram if histogram is not None else _histogram(_CALM_BUCKETS),
        episodes=episodes,
        marked_window_counts=marked,
    )


def _page(
    report: Report | None = None,
    aggregates: tuple[AspectAggregate, ...] = (),
    evidence: tuple[EvidenceQuote, ...] = (),
) -> ReportPageData:
    return ReportPageData(
        report=report or _report(), aggregates=aggregates, evidence=evidence
    )


# --- the view builders: pure claims ---------------------------------------------


def test_narrative_cuts_exactly_along_the_certificate() -> None:
    """Prose renders as plain voice between certified spans — offsets from the
    stored certificate, never re-scanned — with each span keeping its kind and
    (for quotes) the review it verified against."""
    prose = 'Players praise combat. "great gunplay" said one; 27% mention it.'
    spans = (
        GroundedSpan(start=23, end=38, text='"great gunplay"', kind=SpanKind.QUOTE,
                     review_id="r9"),
        GroundedSpan(start=49, end=52, text="27%", kind=SpanKind.NUMERAL, value=0.27),
    )
    segments = narrative_segments(prose, spans)
    assert [s.text for s in segments] == [
        "Players praise combat. ",
        '"great gunplay"',
        " said one; ",
        "27%",
        " mention it.",
    ]
    assert segments[1].kind is SpanKind.QUOTE
    assert segments[1].review_id == "r9"
    assert segments[3].kind is SpanKind.NUMERAL
    assert segments[0].kind is None


def test_aspect_rows_sort_by_weight_and_wear_certified_whiskers() -> None:
    """Pinned rows sort by evidence weight; a calm sampled game's whisker IS
    the shipped interval (certified seam, never re-derived), scaled to the
    section's stated axis."""
    view = build_report_view(
        _page(aggregates=(_aggregate("story", 100), _aggregate("combat", 270)))
    )
    assert [row.aspect for row in view.aspects.rows] == ["combat", "story"]
    combat = view.aspects.rows[0]
    assert combat.share_label.startswith("27.0%")
    interval = shipped_interval(270, 1_000, spiky=False)
    assert combat.whisker is not None
    # the axis rounds up to 30%, so pct positions are interval / 0.30 * 100
    assert combat.whisker.low_pct == pytest.approx(interval.low / 0.30 * 100)
    assert combat.whisker.high_pct == pytest.approx(interval.high / 0.30 * 100)
    assert "axis to 30%" in view.aspects.axis_label


def test_take_all_reports_render_no_whiskers() -> None:
    """An exact count has no sampling error to price — no whisker, and the
    axis note says complete count (the ruled display)."""
    view = build_report_view(
        _page(
            report=_report(take_all=True, sample_size=300),
            aggregates=(_aggregate("combat", 90, sample_size=300),),
        )
    )
    assert view.aspects.rows[0].whisker is None
    assert "complete count" in view.aspects.axis_label


def test_candidate_stratum_folds_singletons() -> None:
    """Recurring candidates list with counts; once-mentioned ones fold into a
    single disclosed number instead of a wall of rows."""
    view = build_report_view(
        _page(
            aggregates=(
                _aggregate("combat", 270),
                _aggregate("grind", 8, slot=AspectSlot.CANDIDATE),
                _aggregate("ship bilding", 1, slot=AspectSlot.CANDIDATE),
                _aggregate("space exploration", 1, slot=AspectSlot.CANDIDATE),
            )
        )
    )
    assert [row.aspect for row in view.candidates.rows] == ["grind"]
    assert view.candidates.singleton_count == 2


def test_quotes_cap_at_three_dominant_polarity_first() -> None:
    """The display cap: at most three quotes per aspect, the aspect's majority
    polarity preferred, stream order preserved within a polarity."""
    evidence = tuple(
        EvidenceQuote(review_id=f"r{i}", aspect="combat", sentiment=sentiment,
                      text=f"quote {i}")
        for i, sentiment in enumerate(
            [Sentiment.NEGATIVE, Sentiment.POSITIVE, Sentiment.POSITIVE,
             Sentiment.POSITIVE, Sentiment.NEGATIVE]
        )
    )
    view = build_report_view(
        _page(aggregates=(_aggregate("combat", 270),), evidence=evidence)
    )
    quotes = view.aspects.rows[0].quotes
    assert len(quotes) == 3
    assert [q.sentiment for q in quotes] == [Sentiment.POSITIVE] * 3
    assert [q.review_id for q in quotes] == ["r1", "r2", "r3"]


def test_timeline_maps_buckets_and_marker_layers_to_one_scale() -> None:
    """Bars scale to the busiest bucket on a linear time axis; episode and
    Valve layers land as spans on the same scale, labels in the no-causal-noun
    vocabulary; an empty histogram renders no timeline at all."""
    episode = EpisodeMarker(
        start=datetime(2024, 3, 1, tzinfo=UTC), end=datetime(2024, 4, 1, tzinfo=UTC),
        buckets=1, reviews=900, peak_multiple=4.2, overlaps_marked_window=True,
    )
    event = ReviewEvent(
        event_type=0,
        start=datetime(2024, 3, 5, tzinfo=UTC), end=datetime(2024, 3, 20, tzinfo=UTC),
    )
    view = build_report_view(
        _page(report=_report(histogram=_histogram(_CALM_BUCKETS, (event,)),
                             episodes=(episode,)))
    )
    timeline = view.timeline
    assert timeline is not None
    assert len(timeline.bars) == len(_CALM_BUCKETS)
    peak_bar = max(timeline.bars, key=lambda b: b.height)
    assert peak_bar.height == timeline.baseline_y - 12.0  # full plot height
    assert "74 reviews" in peak_bar.label
    assert len(timeline.episodes) == 1
    assert "review activity spike" in timeline.episodes[0].label
    assert "overlaps a Steam-marked period" in timeline.episodes[0].label
    assert len(timeline.valve_windows) == 1
    assert timeline.episodes[0].x < timeline.episodes[0].x + timeline.episodes[0].width
    # An empty histogram is only coherent for a take-all game (a sampled plan
    # compiled off this snapshot, so emptiness there fails loud in _regime).
    empty = build_report_view(
        _page(report=_report(take_all=True, histogram=_histogram(())))
    )
    assert empty.timeline is None


def test_trust_panel_discloses_the_ruled_facts() -> None:
    """The protected element: sample method, recomputed regime, fetch paths,
    language mix, the marked-share state against the 2% floor, the published
    instrument readings, and the versions triple — all present."""
    view = build_report_view(
        _page(
            report=_report(
                marked=(
                    MarkedWindowCount(
                        start=datetime(2024, 3, 5, tzinfo=UTC),
                        end=datetime(2024, 3, 20, tzinfo=UTC),
                        members_inside=35,
                    ),
                )
            )
        )
    )
    entries = dict(view.trust_entries)
    assert "time-proportional draw" in entries["Sample"]
    assert entries["Interval regime"].startswith("calm")
    assert "1 windowed" in entries["Fetch paths"]
    assert "1 fallback-walked" in entries["Fetch paths"]
    assert "english 900" in entries["Language mix"]
    assert "3.5%" in entries["Marked share"]
    assert "over the 2% floor" in entries["Marked share"]
    assert entries["Instrument: classifier F1 vs gold"] == "0.766 [0.713–0.811]"
    assert "deepseek-v4-flash" in entries["Versions"]


def test_provenance_line_states_the_two_denominators() -> None:
    """Take-all is a complete count, a sampled run names its n — the two-track
    honesty rule surfacing in one line of header text."""
    assert (
        provenance_line(_report(take_all=True))
        == "analyzed 2026-08-01 · complete count of 1,000 English reviews"
    )
    assert (
        provenance_line(_report())
        == "analyzed 2026-08-01 · sample of 1,000 English reviews"
    )


# --- the rendered page ----------------------------------------------------------


def _get(app: FastAPI, path: str) -> Response:
    async def drive() -> Response:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(path)

    return asyncio.run(asyncio.wait_for(drive(), timeout=10.0))


def _page_app(page: ReportPageData | None, *, live: bool = False) -> FastAPI:
    app = FastAPI()
    attach_web(app, lambda _: page, lambda _: live)
    return app


def test_report_page_renders_every_section() -> None:
    """The ruled top-to-bottom structure lands in HTML: header + provenance,
    narrative with certified spans marked, aspect bars with quotes, the
    candidate stratum tagged uncalibrated, the timeline SVG with its
    discipline line, and the trust panel."""
    narrative = ComposedNarrative(
        prose="Players praise combat.",
        spans=(GroundedSpan(start=15, end=21, text="combat", kind=SpanKind.QUOTE,
                            review_id="r1"),),
        outcome=NarrativeOutcome.COMPOSED,
    )
    page = _page(
        report=_report(narrative=narrative),
        aggregates=(
            _aggregate("combat", 270),
            _aggregate("grind", 4, slot=AspectSlot.CANDIDATE),
        ),
        evidence=(
            EvidenceQuote(review_id="r1", aspect="combat",
                          sentiment=Sentiment.POSITIVE, text="great gunplay"),
        ),
    )
    html = _get(_page_app(page), "/reports/440").text
    assert "Team Fortress 2" in html
    assert "analyzed 2026-08-01" in html
    assert '<mark class="span-quote"' in html
    assert "combat" in html
    assert "great gunplay" in html
    assert "uncalibrated" in html
    assert "timeline-chart" in html
    assert "no cause attributed" in html
    assert "How this report was made" in html
    assert "0.766 [0.713–0.811]" in html


def test_unanalyzed_game_gets_an_honest_404_page() -> None:
    """No published report and no live job is a 404 with a human answer — the
    page names the app and points at search, instead of a bare JSON error."""
    response = _get(_page_app(None), "/reports/999")
    assert response.status_code == 404
    assert "Not analyzed yet" in response.text
    assert "999" in response.text


def test_live_job_renders_the_narration_page() -> None:
    """During a cold job the page IS the narration: a live job answers 200
    with the stage surface and the EventSource consumer wired to this app's
    stream; a published report still wins over the live branch."""
    live = _get(_page_app(None, live=True), "/reports/570")
    assert live.status_code == 200
    assert 'data-app-id="570"' in live.text
    assert '<script src="/static/report_live.js">' in live.text

    published = _get(_page_app(_page(), live=True), "/reports/440")
    assert published.status_code == 200
    assert "How this report was made" in published.text


def test_search_page_serves_at_the_root() -> None:
    """The front door: GET / is the search page, HTML, spine sentence on it,
    with the search flow's script wired in."""
    response = _get(_page_app(None), "/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Type a game name" in response.text
    assert '<script src="/static/search.js">' in response.text


def test_hostile_review_content_renders_inert() -> None:
    """The escaping wall: game name, narrative prose, quote text, and
    candidate aspect names are all hostile by assumption — markup in any of
    them must land escaped. The full canary sweep is its own chunk; this pins
    the mechanism across every content field the page renders."""
    hostile = "<script>alert(1)</script>"
    page = _page(
        report=_report(
            game_name=hostile,
            narrative=ComposedNarrative(
                prose=f"{hostile} praised the gunplay.", spans=(),
                outcome=NarrativeOutcome.COMPOSED,
            ),
        ),
        aggregates=(
            _aggregate("combat", 270),
            _aggregate(hostile, 5, slot=AspectSlot.CANDIDATE),
        ),
        evidence=(
            EvidenceQuote(review_id="r1", aspect="combat",
                          sentiment=Sentiment.POSITIVE, text=f"nice {hostile}"),
        ),
    )
    html = _get(_page_app(page), "/reports/440").text
    assert "<script>alert(1)</script>" not in html
    assert html.count("&lt;script&gt;") >= 4


def test_json_surface_never_imports_the_renderer() -> None:
    """The rendering boundary, pinned: only the composition root may import
    ``serve.web`` — the JSON surface staying renderer-blind is what keeps a
    future frontend swap a one-package change."""
    violations: list[str] = []
    for path in _SERVE_DIR.rglob("*.py"):
        relative = path.relative_to(_SERVE_DIR)
        if relative.parts[0] in {"web", "main.py"}:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported = node.module
            elif isinstance(node, ast.Import):
                imported = ",".join(a.name for a in node.names)
            else:
                continue
            if "serve.web" in imported:
                violations.append(f"{relative}: imports {imported}")
    assert not violations, (
        "the JSON surface imports the renderer (the rendering boundary ruling):\n"
        + "\n".join(violations)
    )
