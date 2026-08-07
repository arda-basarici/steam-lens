"""Behavioral claims on the cursor-walk engine and the windowed fetch path.

The engine tests script ``ReviewPage`` sequences straight at the ``fetch_page``
seam — no HTTP at all — pinning the stop discipline the design ruled: short
pages continue, empty pages retry the same cursor before concluding, repeated
and missing cursors stop, a boundary page trims, and Steam's no-result answer
is clean. The wire tests below them assert what ``fetch_window`` actually
sends — the windowed-unfiltered param set with the off-topic restore flag —
through ``httpx.MockTransport``.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fakes import CollectingSink, NullSink

from steamlens.contracts import PathOutcome, Review, StageEvent, StageKind
from steamlens.steam_client import (
    QuerySummary,
    ReviewPage,
    SteamClient,
    SteamClientConfig,
    SteamResponseError,
    SteamTransport,
)
from steamlens.steam_client.walk import walk_pages

_START = datetime(2026, 6, 1, tzinfo=UTC)
_END = datetime(2026, 6, 30, tzinfo=UTC)


def _review(created_at: datetime, review_id: str = "") -> Review:
    return Review(
        review_id=review_id or f"r{created_at.timestamp():.0f}",
        app_id=440,
        created_at=created_at,
        language="english",
        text="the hats are load-bearing",
        voted_up=True,
    )


def _in_window(count: int, offset_hours: int = 0) -> tuple[Review, ...]:
    base = _START + timedelta(hours=offset_hours)
    return tuple(
        _review(base + timedelta(minutes=index), review_id=f"r{offset_hours}-{index}")
        for index in range(count)
    )


def _page(
    reviews: tuple[Review, ...],
    cursor: str | None,
    *,
    success: int = 1,
    total: int | None = None,
) -> ReviewPage:
    summary = None if total is None else QuerySummary(total, total, 0)
    return ReviewPage(success=success, cursor=cursor, summary=summary, reviews=reviews)


class Feed:
    """Scripted pages at the ``fetch_page`` seam, cursors asked recorded."""

    def __init__(self, pages: list[ReviewPage]) -> None:
        self.asked: list[str] = []
        self._feed: Iterator[ReviewPage] = iter(pages)

    def __call__(self, cursor: str) -> ReviewPage:
        self.asked.append(cursor)
        return next(self._feed)


# --- the engine's stop discipline ----------------------------------------------


def test_short_page_mid_stream_continues() -> None:
    """A 40-review page mid-stream is Steam being Steam — the walk advances,
    and the dry tail still costs the empty-page retries before concluding."""
    feed = Feed(
        [
            _page(_in_window(100), "A", total=140),
            _page(_in_window(40, offset_hours=200), "B"),
            _page((), "C"),
            _page((), "C"),
            _page((), None),
        ]
    )
    tally = walk_pages(feed, _START, _END, out_of_window_is_violation=True)
    assert len(tally.reviews) == 140
    assert tally.pages_fetched == 5
    assert feed.asked == ["*", "A", "B", "B", "B"]
    assert tally.reported_total == 140
    assert tally.out_of_window == 0


def test_empty_pages_retry_the_same_cursor_before_concluding() -> None:
    """Empty is suspicious, not conclusive: the same cursor is re-asked twice
    before the walk accepts a dry stream."""
    feed = Feed([_page((), "A")] * 3)
    tally = walk_pages(feed, _START, _END, out_of_window_is_violation=True)
    assert tally.reviews == ()
    assert feed.asked == ["*", "*", "*"]
    assert tally.stopped_on_empty_pages  # the one stop the engine distrusts, disclosed


def test_empty_page_retry_budget_resets_per_stretch() -> None:
    """The budget is per suspicious stretch, not per walk: a page that yields
    reviews hands the next stretch a fresh budget — without the reset the walk
    would conclude one page early and silently truncate the window."""
    feed = Feed(
        [
            _page(_in_window(3), "A"),
            _page((), "A"),
            _page(_in_window(2, offset_hours=5), "B"),
            _page((), "B"),
            _page((), "B"),
            _page((), "B"),
        ]
    )
    tally = walk_pages(feed, _START, _END, out_of_window_is_violation=True)
    assert len(tally.reviews) == 5
    assert tally.pages_fetched == 6
    assert feed.asked == ["*", "A", "A", "B", "B", "B"]
    assert tally.stopped_on_empty_pages


def test_quota_stop_ends_the_walk_and_truncates_the_prefix() -> None:
    """The plan contract's quota executed as an early stop: the walk ends the
    moment the collected in-window prefix reaches ``stop_after`` — a mid-page
    overshoot is truncated, and the pages beyond are never paid for."""
    feed = Feed(
        [
            _page(_in_window(100), "A", total=400),
            _page(_in_window(100, offset_hours=48), "B"),
            _page(_in_window(100, offset_hours=96), "C"),
        ]
    )
    tally = walk_pages(
        feed, _START, _END, out_of_window_is_violation=True, stop_after=150
    )
    assert len(tally.reviews) == 150
    assert tally.pages_fetched == 2
    assert feed.asked == ["*", "A"]
    assert not tally.stopped_on_empty_pages


def test_quota_overshoot_on_a_boundary_page_still_truncates() -> None:
    """A single page can both overfill the quota and descend below the window
    (the fallback's boundary page) — the past-the-window stop must not skip
    the quota truncation."""
    boundary_page = _page(
        _in_window(3) + (_review(_START - timedelta(days=2), review_id="older"),),
        "A",
    )
    tally = walk_pages(
        Feed([boundary_page]), _START, _END,
        out_of_window_is_violation=False, stop_after=2,
    )
    assert len(tally.reviews) == 2
    assert tally.out_of_window == 0  # the fallback judges the descent expected


def test_quota_fetch_window_skips_the_shortfall_disclosure() -> None:
    """A quota'd windowed fetch collecting less than Steam's reported window
    total is the quota working — the collected-versus-reported WARN must not
    fire (the plan-versus-delivered account belongs to the plan's holder)."""
    sink = CollectingSink()
    pages = iter(
        [_wire_page([_wire_review("a", _START + timedelta(days=1))], "")]
    )
    client = SteamClient(SteamTransport(
        SteamClientConfig(), sink,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text=next(pages))
        ),
        sleep=lambda _: None,
        monotonic=lambda: 100.0,
    ))
    result = client.fetch_window(440, _START, _END, quota=1)
    assert result.outcome is PathOutcome.WINDOWED
    assert len(result.reviews) == 1
    warns = [
        e.message
        for e in sink.events
        if isinstance(e, StageEvent) and e.kind is StageKind.WARN
    ]
    assert not any("collected 1 of Steam's reported" in m for m in warns)


def test_repeated_cursor_stops() -> None:
    """A page pointing back at a cursor already walked would loop forever —
    trusted stop, page's reviews still kept."""
    feed = Feed(
        [
            _page(_in_window(100), "A"),
            _page(_in_window(50, offset_hours=300), "A"),
        ]
    )
    tally = walk_pages(feed, _START, _END, out_of_window_is_violation=True)
    assert len(tally.reviews) == 150
    assert tally.pages_fetched == 2


def test_missing_cursor_stops() -> None:
    feed = Feed([_page(_in_window(30), None)])
    tally = walk_pages(feed, _START, _END, out_of_window_is_violation=True)
    assert len(tally.reviews) == 30
    assert tally.pages_fetched == 1
    assert not tally.stopped_on_empty_pages  # a trusted stop reads as one


def test_boundary_page_trims_and_stops() -> None:
    """Timestamps below the window mean the newest-first stream has passed it:
    the sub-window tail is trimmed, counted as a violation on the windowed
    path, and the walk stops without asking the next cursor."""
    straddling = _in_window(3) + (_review(_START - timedelta(days=2)),)
    feed = Feed([_page(straddling, "A")])
    tally = walk_pages(feed, _START, _END, out_of_window_is_violation=True)
    assert len(tally.reviews) == 3
    assert tally.out_of_window == 1
    assert feed.asked == ["*"]


def test_dirty_page_stops_the_strict_walk() -> None:
    """A too-new review on the windowed path is a params violation — counted,
    trimmed, and the walk stops at that page's end instead of descending: one
    violation already refutes the params, and the descent it would otherwise
    pay is exactly what the feasibility gate exists to refuse."""
    mixed = (_review(_END + timedelta(days=3)),) + _in_window(2)
    feed = Feed([_page(mixed, "A"), _page((), "A")])
    tally = walk_pages(feed, _START, _END, out_of_window_is_violation=True)
    assert len(tally.reviews) == 2
    assert tally.out_of_window == 1
    assert tally.pages_fetched == 1
    assert feed.asked == ["*"]


def test_fallback_judgment_skips_without_counting() -> None:
    """The same zones under the fallback flag: out-of-window reviews are the
    approach and boundary phases, not violations — the verdict stays clean."""
    approach = (_review(_END + timedelta(days=3)),)
    straddle = _in_window(2) + (_review(_START - timedelta(days=1)),)
    feed = Feed([_page(approach, "A"), _page(straddle, "B")])
    tally = walk_pages(feed, _START, _END, out_of_window_is_violation=False)
    assert len(tally.reviews) == 2
    assert tally.out_of_window == 0
    assert tally.pages_fetched == 2


def test_no_result_answer_is_clean_and_keeps_the_summary() -> None:
    """success == 2 concludes immediately — no retry — with Steam's own totals
    claim still captured from the first page."""
    feed = Feed([_page((), None, success=2, total=0)])
    tally = walk_pages(feed, _START, _END, out_of_window_is_violation=True)
    assert tally.reviews == ()
    assert tally.pages_fetched == 1
    assert tally.reported_total == 0


def test_unknown_success_value_fails_loud() -> None:
    """A third success value is new wire knowledge — surfaced, never guessed at."""
    feed = Feed([_page((), "A", success=3)])
    with pytest.raises(SteamResponseError, match="success is 3"):
        walk_pages(feed, _START, _END, out_of_window_is_violation=True)


# --- the windowed path on the wire ---------------------------------------------


def _wire_page(reviews: list[dict[str, object]], cursor: str) -> str:
    return json.dumps(
        {
            "success": 1,
            "cursor": cursor,
            "query_summary": {"total_reviews": 2, "total_positive": 2, "total_negative": 0},
            "reviews": reviews,
        }
    )


def _wire_review(review_id: str, created_at: datetime) -> dict[str, object]:
    return {
        "recommendationid": review_id,
        "language": "english",
        "review": "good",
        "timestamp_created": int(created_at.timestamp()),
        "voted_up": True,
    }


def test_fetch_window_sends_the_ruled_params_and_stamps_provenance() -> None:
    """The windowed-unfiltered param set reaches the wire on every page —
    window epochs, date_range_type=include, the unfiltered trio, the off-topic
    restore flag, the config page size — and the cursor Steam returned goes
    back verbatim. The result carries the WINDOWED outcome and the verdicts."""
    requests: list[httpx.Request] = []
    pages = iter(
        [
            _wire_page([_wire_review("a", _START + timedelta(days=1))], "NEXT+/="),
            _wire_page([_wire_review("b", _START + timedelta(days=2))], "NEXT+/="),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text=next(pages))

    client = SteamClient(
        SteamTransport(
            SteamClientConfig(),
            NullSink(),
            transport=httpx.MockTransport(handler),
            sleep=lambda _: None,
            monotonic=lambda: 100.0,
        )
    )
    result = client.fetch_window(440, _START, _END)

    first = requests[0]
    assert first.url.path == "/appreviews/440"
    assert first.url.params["filter"] == "recent"
    assert first.url.params["language"] == "all"
    assert first.url.params["purchase_type"] == "all"
    assert first.url.params["review_type"] == "all"
    assert first.url.params["filter_offtopic_activity"] == "0"
    assert first.url.params["num_per_page"] == "100"
    assert first.url.params["start_date"] == str(int(_START.timestamp()))
    assert first.url.params["end_date"] == str(int(_END.timestamp()))
    assert first.url.params["date_range_type"] == "include"
    assert first.url.params["cursor"] == "*"
    assert requests[1].url.params["cursor"] == "NEXT+/="

    assert result.outcome is PathOutcome.WINDOWED
    assert result.app_id == 440
    assert len(result.reviews) == 2
    assert result.pages_fetched == 2
    assert result.retries == 0
    assert result.out_of_window_count == 0
    assert result.reported_total == 2


def test_windowed_truncation_is_warn_narrated() -> None:
    """A clean windowed walk that ended on empty-page exhaustion, short of
    Steam's own window total, still returns WINDOWED — but both suspicions
    reach the sink, so a possibly truncated collection is never silently
    trusted complete."""
    pages = iter(
        [_wire_page([_wire_review("a", _START + timedelta(days=1))], "A")]
        + [_wire_page([], "A")] * 3
    )
    sink = CollectingSink()
    client = SteamClient(
        SteamTransport(
            SteamClientConfig(),
            sink,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, text=next(pages))
            ),
            sleep=lambda _: None,
            monotonic=lambda: 100.0,
        )
    )
    result = client.fetch_window(440, _START, _END)

    assert result.outcome is PathOutcome.WINDOWED
    assert len(result.reviews) == 1
    warns = [
        e.message
        for e in sink.events
        if isinstance(e, StageEvent) and e.kind is StageKind.WARN
    ]
    assert any("empty-page exhaustion" in message for message in warns)
    assert any("collected 1 of Steam's reported 2" in message for message in warns)


def test_fetch_window_refuses_naive_and_inverted_windows() -> None:
    """A naive datetime would silently shift by the machine's zone on its way
    to epoch seconds; an inverted window is a caller bug — both loud."""
    client = SteamClient(SteamTransport(
        SteamClientConfig(), NullSink(),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text="{}")),
    ))
    with pytest.raises(ValueError, match="timezone-aware"):
        client.fetch_window(440, _START.replace(tzinfo=None), _END)
    with pytest.raises(ValueError, match="after window_end"):
        client.fetch_window(440, _END, _START)
