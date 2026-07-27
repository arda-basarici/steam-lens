"""Behavioral claims on the fallback path — the estimate, the trigger, the skip.

The feasibility tests exercise the pure estimate directly (histogram in, page
count out — including the straddling-bucket over-count in the skip
direction). The path tests script full wire sequences through
``httpx.MockTransport``: a dirty windowed verdict triggering the histogram
read and the plain walk, an unaffordable approach becoming the disclosed
skip, and a clean windowed walk never spending the extra request.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import httpx

from steamlens.contracts import (
    HistogramBucket,
    HistogramSnapshot,
    PathOutcome,
    RollupUnit,
    SinkEvent,
    StageEvent,
)
from steamlens.steam_client import SteamClient, SteamClientConfig
from steamlens.steam_client.feasibility import estimate_skip_pages

_START = datetime(2026, 6, 1, tzinfo=UTC)
_END = datetime(2026, 6, 30, tzinfo=UTC)
_NOW = datetime(2026, 7, 27, tzinfo=UTC)


def _histogram(buckets: list[tuple[datetime, int]], unit: RollupUnit) -> HistogramSnapshot:
    return HistogramSnapshot(
        app_id=440,
        rollup_unit=unit,
        rollups=tuple(
            HistogramBucket(start=start, recommendations_up=up, recommendations_down=0)
            for start, up in buckets
        ),
        recent_daily=(),
        past_events=(),
        fetched_at=_NOW,
    )


# --- the pure estimate ---------------------------------------------------------


def test_estimate_counts_buckets_above_the_window_end() -> None:
    """Two weekly buckets after the window (250 reviews) at page size 100 →
    3 approach pages; the bucket ending before the window costs nothing."""
    histogram = _histogram(
        [
            (_END - timedelta(days=14), 999),  # span ends before the window's end
            (_END + timedelta(days=1), 150),
            (_END + timedelta(days=8), 100),
        ],
        RollupUnit.WEEK,
    )
    assert estimate_skip_pages(histogram, _END, page_size=100) == 3


def test_estimate_counts_the_straddling_bucket_whole() -> None:
    """A weekly bucket starting just before the window's end straddles it —
    counted whole, the deliberate over-count toward a disclosed skip."""
    histogram = _histogram([(_END - timedelta(days=3), 500)], RollupUnit.WEEK)
    assert estimate_skip_pages(histogram, _END, page_size=100) == 5


def test_estimate_is_zero_for_a_window_reaching_the_present() -> None:
    histogram = _histogram([(_END - timedelta(days=60), 100_000)], RollupUnit.MONTH)
    assert estimate_skip_pages(histogram, _END, page_size=100) == 0


# --- the path decision on the wire ---------------------------------------------


class RecordingSink:
    def __init__(self) -> None:
        self.events: list[SinkEvent] = []

    def emit(self, event: SinkEvent) -> None:
        self.events.append(event)


def _wire_review(review_id: str, created_at: datetime) -> dict[str, object]:
    return {
        "recommendationid": review_id,
        "language": "english",
        "review": "good",
        "timestamp_created": int(created_at.timestamp()),
        "voted_up": True,
    }


def _review_page_body(
    reviews: list[dict[str, object]], cursor: str | None, total: int = 50
) -> str:
    body: dict[str, object] = {
        "success": 1,
        "query_summary": {"total_reviews": total, "total_positive": total, "total_negative": 0},
        "reviews": reviews,
    }
    if cursor is not None:
        body["cursor"] = cursor
    return json.dumps(body)


def _histogram_body(above_count: int) -> str:
    """A weekly histogram with one bucket after the window holding ``above_count``."""
    bucket_start = int((_END + timedelta(days=1)).timestamp())
    return json.dumps(
        {
            "success": 1,
            "results": {
                "rollup_type": "week",
                "rollups": [
                    {
                        "date": bucket_start,
                        "recommendations_up": above_count,
                        "recommendations_down": 0,
                    }
                ],
                "recent": [],
            },
        }
    )


class Harness:
    def __init__(self, script: list[str]) -> None:
        self.requests: list[httpx.Request] = []
        self.sink = RecordingSink()
        feed: Iterator[str] = iter(script)

        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return httpx.Response(200, text=next(feed))

        self.client = SteamClient(
            SteamClientConfig(),
            self.sink,
            transport=httpx.MockTransport(handler),
            sleep=lambda _: None,
            monotonic=lambda: 100.0,
            now=lambda: _NOW,
        )


def test_dirty_windowed_verdict_falls_back_and_walks_plain() -> None:
    """An out-of-window review on the windowed path distrusts the whole
    collection: the client prices the approach off the histogram, then walks
    the plain cursor path — no date params — and returns FALLBACK_WALKED with
    a clean verdict, no window-scoped total, and every page accounted."""
    windowed_dirty = _review_page_body([_wire_review("x", _END + timedelta(days=5))], None)
    histogram = _histogram_body(above_count=120)  # 2 approach pages — affordable
    approach = _review_page_body([_wire_review("a", _END + timedelta(days=5))], "B")
    straddle = _review_page_body(
        [
            _wire_review("b", _START + timedelta(days=10)),
            _wire_review("c", _START - timedelta(days=2)),
        ],
        None,
    )
    h = Harness([windowed_dirty, histogram, approach, straddle])
    result = h.client.fetch_window(440, _START, _END)

    assert result.outcome is PathOutcome.FALLBACK_WALKED
    assert [r.review_id for r in result.reviews] == ["b"]
    assert result.out_of_window_count == 0
    assert result.reported_total is None
    assert result.pages_fetched == 3  # 1 windowed + 2 fallback; histogram is not a page

    windowed_req, histogram_req, plain_req, _ = h.requests
    assert "start_date" in dict(windowed_req.url.params)
    assert histogram_req.url.path == "/appreviewhistogram/440"
    assert plain_req.url.path == "/appreviews/440"
    assert "start_date" not in dict(plain_req.url.params)
    assert plain_req.url.params["filter"] == "recent"
    assert plain_req.url.params["filter_offtopic_activity"] == "0"

    warns = [e for e in h.sink.events if isinstance(e, StageEvent)]
    assert any("falling back" in w.message for w in warns)


def test_unaffordable_fallback_is_a_disclosed_skip() -> None:
    """The same dirty verdict against a deep game: the estimate exceeds the
    page budget, so the window is skipped — empty reviews, the windowed
    attempt's violation count kept as evidence, and the skip narrated."""
    windowed_dirty = _review_page_body([_wire_review("x", _END + timedelta(days=5))], None)
    histogram = _histogram_body(above_count=1_000_000)  # 10,000 pages > budget 200
    h = Harness([windowed_dirty, histogram])
    result = h.client.fetch_window(440, _START, _END)

    assert result.outcome is PathOutcome.SKIPPED_INFEASIBLE
    assert result.reviews == ()
    assert result.out_of_window_count == 1
    assert result.pages_fetched == 1
    assert len(h.requests) == 2  # windowed page + histogram, nothing more
    warns = [e for e in h.sink.events if isinstance(e, StageEvent)]
    assert any("window skipped" in w.message for w in warns)


def test_clean_windowed_walk_never_pays_the_histogram_request() -> None:
    """The happy path spends exactly its pages: no histogram read, no fallback."""
    clean = _review_page_body([_wire_review("a", _START + timedelta(days=1))], None)
    h = Harness([clean])
    result = h.client.fetch_window(440, _START, _END)
    assert result.outcome is PathOutcome.WINDOWED
    assert len(h.requests) == 1


def test_fetch_histogram_stamps_the_injected_clock() -> None:
    """The histogram op: l=english on the wire, the snapshot carrying now()."""
    h = Harness([_histogram_body(above_count=10)])
    snapshot = h.client.fetch_histogram(440)
    assert h.requests[0].url.params["l"] == "english"
    assert snapshot.fetched_at is _NOW
    assert snapshot.rollup_unit is RollupUnit.WEEK
