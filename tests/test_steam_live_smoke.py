"""The Steam door's live smoke — real requests, run deliberately, never in CI.

Five checks against the live API, mirroring the door's ruled verification:
resolve through the identity guard, the histogram with its rollup-unit read,
one windowed fetch with a clean semantic verdict, the blank/restore pair on
Borderlands 2's real review-bomb window (the data-integrity bug observed
live), and the plain-cursor walk forced over a shallow window (the live API
honors its window params, so the fallback must be invoked directly to be
smoked). Pacing is active throughout — the suite really sleeps here.

Gated on a flag, not detection: a plain ``pytest`` run must never touch Steam.
Run it deliberately: ``STEAMLENS_LIVE_SMOKE=1 uv run pytest -k steam_live -s``
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

from steamlens.contracts import (
    IdentityVerdict,
    PathOutcome,
    RollupUnit,
    SinkEvent,
)
from steamlens.steam_client import (
    ReviewPage,
    SteamClient,
    SteamClientConfig,
    SteamTransport,
    parse_review_page,
)
from steamlens.steam_client.walk import walk_pages

_GATE = pytest.mark.skipif(
    os.environ.get("STEAMLENS_LIVE_SMOKE") != "1",
    reason="live smoke hits Steam; set STEAMLENS_LIVE_SMOKE=1 to run deliberately",
)

_TF2 = 440
_BORDERLANDS_2 = 49520
_REVIEWS_URL = "https://store.steampowered.com/appreviews/{app_id}"

_UNFILTERED: dict[str, str | int] = {
    "json": 1,
    "filter": "recent",
    "language": "all",
    "purchase_type": "all",
    "review_type": "all",
    "num_per_page": 100,
}


class PrintSink:
    """Narrates the smoke to stdout — run with ``-s`` to watch it live."""

    def emit(self, event: SinkEvent) -> None:
        print(event)


@pytest.fixture(scope="module")
def client() -> SteamClient:
    return SteamClient(SteamClientConfig(), PrintSink())


@pytest.fixture(scope="module")
def transport() -> SteamTransport:
    """A raw transport for the reads the client deliberately won't make
    (the blanked default fetch) and the forced fallback walk."""
    return SteamTransport(SteamClientConfig(), PrintSink())


@_GATE
def test_resolve_through_the_guard(client: SteamClient) -> None:
    """TF2 resolves to its own name with an OK verdict and real totals."""
    ref = client.resolve_game(_TF2, "Team Fortress 2")
    print(f"resolved: {ref}")
    assert ref.verdict is IdentityVerdict.OK
    assert ref.store_name == "Team Fortress 2"
    assert ref.total_reviews is not None and ref.total_reviews > 500_000


@_GATE
def test_histogram_rollup_unit(client: SteamClient) -> None:
    """A 2007 game rolls up monthly (the M0 probe's verdict, still true live),
    with a populated lifetime series and the 30-day recent strip."""
    snapshot = client.fetch_histogram(_TF2)
    print(f"histogram: unit={snapshot.rollup_unit} rollups={len(snapshot.rollups)}")
    assert snapshot.rollup_unit is RollupUnit.MONTH
    assert len(snapshot.rollups) > 100
    assert snapshot.recent_daily


@_GATE
def test_windowed_fetch_validates_semantically(client: SteamClient) -> None:
    """A six-hour window a week back comes back WINDOWED with a clean verdict —
    every timestamp inside the window, Steam's window params honored."""
    window_end = datetime.now(UTC) - timedelta(days=7)
    window_start = window_end - timedelta(hours=6)
    result = client.fetch_window(_TF2, window_start, window_end)
    print(
        f"windowed: {len(result.reviews)} reviews, {result.pages_fetched} pages, "
        f"violations={result.out_of_window_count}, reported={result.reported_total}"
    )
    assert result.outcome is PathOutcome.WINDOWED
    assert result.out_of_window_count == 0
    assert result.reviews, "six hours of TF2 with zero reviews is itself suspicious"
    assert all(window_start <= r.created_at <= window_end for r in result.reviews)


@_GATE
def test_blank_restore_on_borderlands(client: SteamClient, transport: SteamTransport) -> None:
    """The proven bug, live: a slice of the review-bomb window Steam flags on
    Borderlands 2 yields more reviews with ``filter_offtopic_activity=0`` than
    a default fetch — the window comes from the live ``past_events``."""
    snapshot = client.fetch_histogram(_BORDERLANDS_2)
    assert snapshot.past_events, "expected the 2019 review-bomb event on the live histogram"
    event = snapshot.past_events[0]
    slice_end = min(event.end, event.start + timedelta(days=1))
    params: dict[str, str | int] = {
        **_UNFILTERED,
        "start_date": int(event.start.timestamp()),
        "end_date": int(slice_end.timestamp()),
        "date_range_type": "include",
        "cursor": "*",
    }
    url = _REVIEWS_URL.format(app_id=_BORDERLANDS_2)
    blanked = parse_review_page(transport.get_json(url, params), _BORDERLANDS_2)
    restored = parse_review_page(
        transport.get_json(url, {**params, "filter_offtopic_activity": 0}), _BORDERLANDS_2
    )
    print(f"blank/restore: default={len(blanked.reviews)} restored={len(restored.reviews)}")
    assert len(restored.reviews) > len(blanked.reviews)


@_GATE
def test_forced_fallback_walks_a_shallow_window(transport: SteamTransport) -> None:
    """The plain-cursor walk, timestamp-gated to the last twelve hours: the
    live API honors its window params, so the fallback path is invoked
    directly — same engine, no date params on the wire."""
    window_end = datetime.now(UTC)
    window_start = window_end - timedelta(hours=12)
    url = _REVIEWS_URL.format(app_id=_TF2)
    params: dict[str, str | int] = {**_UNFILTERED, "filter_offtopic_activity": 0}

    def fetch_page(cursor: str) -> ReviewPage:
        return parse_review_page(transport.get_json(url, {**params, "cursor": cursor}), _TF2)

    tally = walk_pages(fetch_page, window_start, window_end, out_of_window_is_violation=False)
    print(f"fallback: {len(tally.reviews)} reviews over {tally.pages_fetched} pages")
    assert tally.reviews
    # window_end is "now", so the newest-first stream has no approach phase to
    # skip — a claim only a live run can make about the fallback's real cost
    assert tally.pages_fetched <= 25
    assert all(window_start <= r.created_at <= window_end for r in tally.reviews)
