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
import re
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
    DailyAdmissionRow,
    DailyLedgerRow,
    DailyRefusalRow,
    EpisodeMarker,
    EvidenceQuote,
    GroundedSpan,
    HistogramBucket,
    HistogramSnapshot,
    JobRow,
    LanguageCount,
    MarkedWindowCount,
    NarrativeOutcome,
    PathOutcome,
    Provenance,
    Report,
    Review,
    ReviewEvent,
    RollupUnit,
    Sentiment,
    SentimentCounts,
    SpanKind,
    StageLatencyRow,
    StageModelRow,
    WindowAccount,
)
from steamlens.core.allowance import shipped_interval
from steamlens.serve.web import OpsData, ReportPageData, attach_web
from steamlens.serve.web.csp import STEAM_CDN_FAMILY
from steamlens.serve.web.ops_view import build_ops_view
from steamlens.serve.web.view import (
    HEADER_ART_ORIGIN,
    QUOTE_DISPLAY_CHAR_CAP,
    build_report_view,
    narrative_segments,
    provenance_line,
    sentence_display_text,
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


def _review(review_id: str, text: str) -> Review:
    return Review(
        review_id=review_id, app_id=440, created_at=_STAMP,
        language="english", text=text, voted_up=True,
    )


def _page(
    report: Report | None = None,
    aggregates: tuple[AspectAggregate, ...] = (),
    evidence: tuple[EvidenceQuote, ...] = (),
    quoted_reviews: dict[str, Review] | None = None,
) -> ReportPageData:
    return ReportPageData(
        report=report or _report(),
        aggregates=aggregates,
        evidence=evidence,
        quoted_reviews=quoted_reviews or {},
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


def test_aspect_rows_sort_by_weight_and_wear_certified_intervals() -> None:
    """Pinned rows sort by evidence weight; a calm sampled game's ± IS the
    shipped interval's half-width (certified seam, never re-derived), with
    the exact bounds riding the label's hover title."""
    view = build_report_view(
        _page(aggregates=(_aggregate("story", 100), _aggregate("combat", 270)))
    )
    assert [row.aspect for row in view.aspects.rows] == ["combat", "story"]
    combat = view.aspects.rows[0]
    interval = shipped_interval(270, 1_000, spiky=False)
    half_width = (interval.high - interval.low) / 2 * 100
    assert combat.share_label.startswith(f"27.0% ±{half_width:.1f}")
    assert combat.interval_title == (
        f"sampling interval {interval.low:.1%}–{interval.high:.1%}"
    )
    assert "axis to 30%" in view.aspects.axis_label


def test_bar_segments_stack_the_polarity_split_on_the_bar_scale() -> None:
    """The stack shows what kind of talk, not just how much: poles at the
    ends, mixed+neutral folded between with its composition disclosed, empty
    segments absent, widths tiling exactly the share's length on the axis."""
    aggregate = AspectAggregate(
        app_id=440, aspect="combat", slot=AspectSlot.PINNED, reviews_with_aspect=270,
        counts=SentimentCounts(positive=200, negative=50, mixed=15, neutral=5),
        sample_size=1_000, versions=_VERSIONS, manifest_id="serve-test",
    )
    view = build_report_view(_page(aggregates=(aggregate,)))
    segments = view.aspects.rows[0].segments
    assert [s.kind for s in segments] == ["positive", "split", "negative"]
    assert segments[1].label == "15 mixed · 5 neutral"
    # axis rounds to 30%: total width = 0.27 / 0.30 of the track
    assert sum(s.pct for s in segments) == pytest.approx(0.27 / 0.30 * 100)
    all_positive = _aggregate("story", 100)
    story = build_report_view(_page(aggregates=(all_positive,))).aspects.rows[0]
    assert [s.kind for s in story.segments] == ["positive"]


def test_sub_floor_aspect_rows_fold_into_a_disclosed_tail() -> None:
    """Rows under 1% of the sample fold behind a disclosed tail (never
    dropped — the ± swallows values that small); a report where nothing
    clears the floor keeps its rows visible instead of folding everything."""
    view = build_report_view(
        _page(
            aggregates=(
                _aggregate("combat", 270),
                _aggregate("lore", 7),
                _aggregate("physics", 1),
            )
        )
    )
    assert [row.aspect for row in view.aspects.rows] == ["combat"]
    assert [row.aspect for row in view.aspects.tail] == ["lore", "physics"]
    assert view.aspects.tail_label == "2 more aspects under 1% of the sample"
    all_tiny = build_report_view(_page(aggregates=(_aggregate("lore", 7),)))
    assert [row.aspect for row in all_tiny.aspects.rows] == ["lore"]
    assert all_tiny.aspects.tail == ()


def test_take_all_reports_render_no_intervals() -> None:
    """An exact count has no sampling error to price — no ± on the label,
    and the axis note says exact counts (the ruled display)."""
    view = build_report_view(
        _page(
            report=_report(take_all=True, sample_size=300),
            aggregates=(_aggregate("combat", 90, sample_size=300),),
        )
    )
    row = view.aspects.rows[0]
    assert "±" not in row.share_label
    assert row.interval_title is None
    assert "exact counts" in view.aspects.axis_label


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


def test_aspect_names_display_without_underscores() -> None:
    """Ontology keys are storage identity; the rendered row wears the spaced
    form — the quotes still join on the exact stored key."""
    evidence = (
        EvidenceQuote(review_id="r1", aspect="voice_acting",
                      sentiment=Sentiment.POSITIVE, text="superb voices"),
    )
    view = build_report_view(
        _page(aggregates=(_aggregate("voice_acting", 24),), evidence=evidence)
    )
    row = view.aspects.rows[0]
    assert row.aspect == "voice acting"
    assert row.quotes[0].text == "superb voices"


def test_trust_panel_opens_itself_when_certification_caveat_fires() -> None:
    """The methodology panel folds by default (reference material), but a
    marked-share breach of the 2% floor means the calibrated bars are not
    certified — that disclosure is born visible, never behind the toggle."""
    assert build_report_view(_page()).trust_open is False
    marked = (MarkedWindowCount(start=_STAMP, end=_STAMP, members_inside=50),)
    assert build_report_view(_page(report=_report(marked=marked))).trust_open is True


def test_displayed_quotes_expand_to_their_containing_sentence() -> None:
    """The evidence-display ruling: a stored minimal span reads thin quoted
    bare, so the displayed quote is the review sentence containing it, dated
    from the review — while a review the bundle carries no record for
    degrades to the stored span, undated."""
    evidence = (
        EvidenceQuote(review_id="r1", aspect="combat",
                      sentiment=Sentiment.POSITIVE, text="razor sharp"),
        EvidenceQuote(review_id="r2", aspect="combat",
                      sentiment=Sentiment.POSITIVE, text="great gunplay"),
    )
    quoted = {
        "r1": _review("r1", "Long intro thought. The combat feels razor sharp at night! More.")
    }
    view = build_report_view(
        _page(aggregates=(_aggregate("combat", 270),), evidence=evidence,
              quoted_reviews=quoted)
    )
    quotes = view.aspects.rows[0].quotes
    assert [q.text for q in quotes] == [
        "The combat feels razor sharp at night!",
        "great gunplay",
    ]
    assert quotes[0].date_label == "Aug 01, 2026"
    assert quotes[1].date_label == ""


def test_sentence_expansion_breaks_on_newlines_and_keeps_terminal_marks() -> None:
    """Steam reviews often separate thoughts with bare newlines — a line is a
    sentence for display, and terminal punctuation stays with its sentence."""
    text = "story is great\nthe grind killed it for me\n10/10 anyway"
    assert (
        sentence_display_text("grind killed", text) == "the grind killed it for me"
    )


def test_sentence_expansion_caps_punctuation_poor_walls() -> None:
    """A review with no terminal punctuation must not expand a two-word span
    into the whole text: past the cap the display trims to a word-boundary
    window around the span, ellipses marking the trims openly."""
    wall = " ".join(f"word{i}" for i in range(120)) + " the span here " + " ".join(
        f"tail{i}" for i in range(120)
    )
    shown = sentence_display_text("span here", wall)
    assert len(shown) <= QUOTE_DISPLAY_CHAR_CAP + len("…  …")
    assert "span here" in shown
    assert shown.startswith("… ")
    assert shown.endswith(" …")


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


def _get(
    app: FastAPI, path: str, *,
    accept: str | None = None, raise_app_exceptions: bool = True,
) -> Response:
    headers = {"accept": accept} if accept is not None else {}

    async def drive() -> Response:
        transport = ASGITransport(app=app, raise_app_exceptions=raise_app_exceptions)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(path, headers=headers)

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


def test_report_page_carries_the_share_card() -> None:
    """A pasted report link renders a rich preview — the card layer speaks
    curiosity (the shopper's question as title, no methodology terms), with
    the Steam header art as the large card image. External scrapers read
    these tags, so they ride the page, not the CSP."""
    html = _get(_page_app(_page()), "/reports/440").text
    assert (
        '<meta property="og:title" '
        'content="What do players think about Team Fortress 2? — SteamLens">'
    ) in html
    assert (
        "See what players praise, what they complain about, "
        "and the reviews behind the numbers."
    ) in html
    assert f'property="og:image" content="{HEADER_ART_ORIGIN}' in html
    assert '<meta name="twitter:card" content="summary_large_image">' in html


def test_search_page_wears_the_site_default_card() -> None:
    """Pages without per-game data inherit the site-wide card: the plain-
    language pitch and the self-hosted homepage screenshot — whose URL must
    be absolute (scrapers resolve nothing), the app's one hardcoded self-URL."""
    html = _get(_page_app(None), "/").text
    assert '<meta property="og:site_name" content="SteamLens">' in html
    assert (
        '<meta property="og:title" '
        'content="SteamLens — What do players think about a game?">'
    ) in html
    assert '<meta name="twitter:card" content="summary_large_image">' in html
    assert '<meta property="og:image"' in html
    assert 'content="https://steamlens.ardabasarici.dev/static/og-home.png?v=' in html


def test_unanalyzed_game_gets_an_honest_404_page() -> None:
    """No published report and no live job is a 404 with a human answer — the
    page names the app and points at search, instead of a bare JSON error."""
    response = _get(_page_app(None), "/reports/999")
    assert response.status_code == 404
    assert "Not analyzed yet" in response.text
    assert "999" in response.text


def test_unknown_path_gets_the_html_404_for_browsers() -> None:
    """A browser navigating to a path that doesn't exist gets the styled
    not-found page pointing home, never FastAPI's bare JSON."""
    response = _get(_page_app(None), "/no-such-page", accept="text/html")
    assert response.status_code == 404
    assert "Page not found" in response.text
    assert "/no-such-page" in response.text


def test_unknown_path_stays_json_for_api_clients() -> None:
    """Non-browser clients keep FastAPI's default JSON 404 — programmatic
    consumers read ``detail``, and the HTML page must never replace it."""
    response = _get(_page_app(None), "/no-such-page")
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def _crashing_app() -> FastAPI:
    """An app whose report loader raises — drives the unhandled-error path."""
    def boom(_: int) -> ReportPageData | None:
        raise RuntimeError("boom")

    app = FastAPI()
    attach_web(app, boom, lambda _: False)
    return app


def test_unhandled_error_gets_the_html_500_for_browsers() -> None:
    """A crash mid-request shows a browser the styled error page. The
    traceback is not lost: Starlette's error middleware re-raises after
    answering, so the journal keeps the stack while the visitor gets a
    human answer."""
    response = _get(
        _crashing_app(), "/reports/440",
        accept="text/html", raise_app_exceptions=False,
    )
    assert response.status_code == 500
    assert "Something went wrong" in response.text


def test_unhandled_error_stays_plain_for_api_clients() -> None:
    """Non-browser clients keep the framework's exact plain-text 500 —
    the error pages are a browser-only affordance."""
    response = _get(_crashing_app(), "/reports/440", raise_app_exceptions=False)
    assert response.status_code == 500
    assert response.text == "Internal Server Error"


def test_live_job_renders_the_narration_page() -> None:
    """During a cold job the page IS the narration: a live job answers 200
    with the stage surface and the EventSource consumer wired to this app's
    stream; a published report still wins over the live branch."""
    live = _get(_page_app(None, live=True), "/reports/570")
    assert live.status_code == 200
    assert 'data-app-id="570"' in live.text
    assert '<script src="/static/report_live.js?v=' in live.text

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
    assert '<script src="/static/search.js?v=' in response.text


def _nonce(response: Response) -> str:
    """The nonce out of a response's CSP header — asserts the header's shape."""
    match = re.search(r"'nonce-([^']+)'", response.headers["content-security-policy"])
    assert match is not None
    return match.group(1)


def test_html_responses_wear_the_csp_with_a_fresh_nonce() -> None:
    """Every HTML page carries the policy, and the nonce differs per response.
    The nonce is the header's load-bearing part: Cloudflare's bot detection
    injects an inline script into proxied HTML and stamps it with the nonce
    it reads off this header — a static policy would block the injection, a
    repeated nonce would stop being a nonce."""
    app = _page_app(None)
    first = _get(app, "/")
    policy = first.headers["content-security-policy"]
    assert "default-src 'none'" in policy
    assert "script-src 'self' 'nonce-" in policy
    assert f"img-src 'self' {STEAM_CDN_FAMILY}" in policy
    assert "frame-ancestors 'none'" in policy
    assert _nonce(first) != _nonce(_get(app, "/"))


def test_the_minted_header_art_stays_inside_the_csp_image_allowance() -> None:
    """The policy's img-src is a wildcard over Valve's CDN family (search
    thumbnails arrive verbatim from Steam and hop hosts within it); the
    header-art URL is the one image origin WE mint, so this pins it inside
    that family — the drift check a shared exact-origin constant used to
    give structurally."""
    assert STEAM_CDN_FAMILY == "https://*.steamstatic.com"
    assert HEADER_ART_ORIGIN.startswith("https://")
    assert HEADER_ART_ORIGIN.endswith(".steamstatic.com")


def test_error_pages_wear_the_csp_too() -> None:
    """The negotiated HTML 404 and 500 are pages like any other — hostile
    input reaches them (the 404 echoes the requested path), so the backstop
    covers them; the API's JSON and plain-text twins stay bare, a policy on
    a programmatically-read body is dead weight."""
    html_404 = _get(_page_app(None), "/no-such-page", accept="text/html")
    assert "content-security-policy" in html_404.headers
    html_500 = _get(
        _crashing_app(), "/reports/440",
        accept="text/html", raise_app_exceptions=False,
    )
    assert "content-security-policy" in html_500.headers

    json_404 = _get(_page_app(None), "/no-such-page")
    assert "content-security-policy" not in json_404.headers


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


# --- the ops page ----------------------------------------------------------------


def _ops_data(
    *,
    report_count: int = 2,
    stage_model: tuple[StageModelRow, ...] = (
        StageModelRow(
            stage="classify", model="deepseek-chat", calls=180,
            prompt_tokens=90_000, cached_prompt_tokens=81_000,
            measured_prompt_tokens=90_000,
            output_tokens=30_000, thinking_tokens=0,
            cost=0.20,
        ),
    ),
    daily_ledger: tuple[DailyLedgerRow, ...] = (),
    daily_admissions: tuple[DailyAdmissionRow, ...] = (),
    daily_refusals: tuple[DailyRefusalRow, ...] = (),
    jobs: tuple[JobRow, ...] = (),
    stage_latencies: tuple[StageLatencyRow, ...] = (),
) -> OpsData:
    return OpsData(
        now=datetime(2026, 8, 9, 14, 30, tzinfo=UTC),
        admissions_today=2,
        daily_job_limit=5,
        per_ip_daily_job_limit=3,
        spend_today_usd=0.1101,
        daily_spend_backstop_usd=1.0,
        daily_ledger=daily_ledger,
        daily_admissions=daily_admissions,
        stage_model=stage_model,
        report_count=report_count,
        daily_refusals=daily_refusals,
        jobs=jobs,
        stage_latencies=stage_latencies,
    )


def test_ops_view_headline_stats_tell_the_day_and_the_unit_economics() -> None:
    """The stat plate reads straight off the gate's own numbers — allowance
    used, settled spend against the backstop — and the per-report average is
    all-time spend over published reports, or an honest dash before the first."""
    view = build_ops_view(_ops_data())
    stats = {stat.label: stat.value for stat in view.today}
    assert stats["public fresh analyses today"] == "2"
    assert any(
        "capped at 3 per visitor IP" in note and "allowance of 5" in note
        for note in view.notes
    ), "the caps live in the page notes, not on the tile"
    assert stats["settled LLM spend today"] == "$0.1101"
    assert stats["reports published"] == "2"
    assert stats["LLM spend per report"] == "$0.1000"

    unpublished = build_ops_view(_ops_data(report_count=0))
    assert {s.label: s.value for s in unpublished.today}["LLM spend per report"] == "—"


def test_ops_view_daily_table_merges_journal_days_zeros_worn_openly() -> None:
    """The daily table is the union of the journals' days, newest first: a
    day with admissions but no settled spend still renders (its calls zeroed),
    a spend-only day renders with zero admissions — the operator's exempt
    jobs are exactly that case — and refusal counts merge in by day."""
    view = build_ops_view(_ops_data(
        daily_ledger=(
            DailyLedgerRow(day="2026-08-08", calls=90, prompt_tokens=45_000,
                           cached_prompt_tokens=40_500,
                           measured_prompt_tokens=45_000, output_tokens=15_000,
                           thinking_tokens=0, cost=0.11),
        ),
        daily_admissions=(DailyAdmissionRow(day="2026-08-09", admissions=2),),
        daily_refusals=(DailyRefusalRow(day="2026-08-09", refusals=3),),
    ))
    daily = view.tables[1]
    assert daily.headers[1:4] == ("jobs admitted", "refusals", "LLM calls")
    assert [row[0] for row in daily.rows] == ["2026-08-09", "2026-08-08"]
    assert daily.rows[0][1:4] == ("2", "3", "0"), "admission-only day zeros its calls"
    assert daily.rows[1][1:4] == ("0", "0", "90"), "spend-only day zeros its admissions"
    assert daily.rows[1][5] == "90%", "the provider cache-hit share renders per day"
    assert daily.rows[1][8] == "$0.1100"


def test_ops_view_cache_hit_reads_dash_when_no_row_measured_the_split() -> None:
    """A day of pre-step-6 rows (nothing measured) reads "—", never 0% — an
    unrecorded split is not a zero hit rate (the designer misread it as a
    broken number, which is the proof it misleads)."""
    view = build_ops_view(_ops_data(
        daily_ledger=(
            DailyLedgerRow(day="2026-08-08", calls=90, prompt_tokens=45_000,
                           cached_prompt_tokens=0, measured_prompt_tokens=0,
                           output_tokens=15_000, thinking_tokens=0, cost=0.766),
        ),
    ))
    assert build_ops_view(_ops_data()).tables[2].rows[0][4] == "90%"
    assert view.tables[1].rows[0][5] == "—"


def test_ops_view_jobs_table_tells_the_trace_without_leaking_error_text() -> None:
    """The job history renders outcome, duration, banked counts, and joined
    cost; a never-settled job reads running with dashes; a failed job's raw
    error text never reaches the public page."""
    jobs = (
        JobRow(
            run_id="serve-2", app_id=570, requested_name="Dota 2",
            started_at="2026-08-09T14:00:00+00:00", finished_at=None,
            outcome=None, error=None, labeled=None, reused=None,
            failed_durable=None, refused_batches=None, cost=0.0,
        ),
        JobRow(
            run_id="serve-1", app_id=440, requested_name="Team Fortress 2",
            started_at="2026-08-09T12:00:00+00:00",
            finished_at="2026-08-09T12:03:12+00:00",
            outcome="failed", error="RunAbort: /srv/steamlens/secret path leaked",
            labeled=120, reused=30, failed_durable=1, refused_batches=0,
            cost=0.0851,
        ),
    )
    table = build_ops_view(_ops_data(jobs=jobs)).tables[0]
    assert table.rows[0][2:5] == ("running", "—", "—")
    assert table.rows[1][2:7] == ("failed", "3m 12s", "120", "30", "$0.0851")
    assert not any(
        "secret path" in cell for row in table.rows for cell in row
    ), "raw error text is operator-only, never public"


def test_ops_view_latency_table_summarizes_measured_calls() -> None:
    table = build_ops_view(_ops_data(
        stage_latencies=(
            StageLatencyRow(stage="classify", calls=180, p50_s=8.4, p95_s=21.9),
        ),
    )).tables[3]
    assert table.rows == (("classify", "180", "8.4s", "21.9s"),)


def test_ops_page_renders_the_full_surface() -> None:
    """The rendered page carries the stat plate and all four tables — job
    history, daily, stage/model, latency — plus the pre-fix pricing
    disclosure."""
    app = FastAPI()
    attach_web(app, lambda _: None, lambda _: False, lambda: _ops_data())
    html = _get(app, "/ops").text
    assert "fresh analyses today" in html
    assert "capped at 3 per visitor IP" in html
    assert "deepseek-chat" in html
    assert "jobs (newest 20)" in html
    assert "call latency by stage" in html
    assert "repriced 2026-08-10 from the archive" in html
    assert "generated 2026-08-09 14:30 UTC" in html


def test_ops_page_is_absent_when_unwired() -> None:
    """An app composed without an ops loader has no /ops route at all —
    the report-only test apps stay exactly as small as they were."""
    assert _get(_page_app(None), "/ops").status_code == 404
