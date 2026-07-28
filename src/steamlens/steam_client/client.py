"""The Steam door's operations — the three answers, composed over one chokepoint.

``SteamClient`` is the surface callers hold: resolve a game (appdetails + the
identity guard + the one-request totals read), snapshot its review histogram,
and fetch a date window of reviews. Every operation speaks through the shared
``SteamTransport``, so pacing, retries, and the typed failure taxonomy are
inherited by construction — no operation can be impolite or trust a transient.
The construction seams (``transport``, ``sleep``, ``monotonic``, ``now``) are
for tests: scripted wire sequences, a frozen clock, and no real waiting.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Final

import httpx

from steamlens.contracts import (
    GameRef,
    HistogramSnapshot,
    PathOutcome,
    Sink,
    StageEvent,
    StageKind,
    WindowFetchResult,
)
from steamlens.steam_client.config import SteamClientConfig
from steamlens.steam_client.feasibility import estimate_skip_pages
from steamlens.steam_client.identity import identity_verdict
from steamlens.steam_client.parse import (
    ReviewPage,
    parse_appdetails,
    parse_histogram,
    parse_review_page,
)
from steamlens.steam_client.transport import SteamTransport
from steamlens.steam_client.walk import WalkTally, walk_pages

_APPDETAILS_URL: Final = "https://store.steampowered.com/api/appdetails"
_REVIEWS_URL: Final = "https://store.steampowered.com/appreviews/{app_id}"
_HISTOGRAM_URL: Final = "https://store.steampowered.com/appreviewhistogram/{app_id}"

# The bias-avoiding base every review fetch shares: the unfiltered trio keeps
# Steam's default sampling out of the data, and filter_offtopic_activity=0
# rides every fetch — a default fetch silently blanks flagged windows (the
# proven data-integrity bug).
_UNFILTERED_BASE: Final[dict[str, str | int]] = {
    "json": 1,
    "language": "all",
    "purchase_type": "all",
    "review_type": "all",
    "filter_offtopic_activity": 0,
}
# The one-request totals-only read: num_per_page=0 returns query_summary alone.
_TOTALS_PARAMS: Final[dict[str, str | int]] = {**_UNFILTERED_BASE, "num_per_page": 0}


def _utc_now() -> datetime:
    return datetime.now(UTC)


class SteamClient:
    """The one door to live Steam — every operation paced and typed by the transport.

    Holds the shared ``SteamTransport`` (and with it the single pacing clock),
    so one client instance per process is the intended shape: two clients
    would be two politeness budgets.
    """

    def __init__(
        self,
        config: SteamClientConfig,
        sink: Sink,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._config = config
        self._sink = sink
        self._transport = SteamTransport(
            config, sink, transport=transport, sleep=sleep, monotonic=monotonic
        )
        self._now = now

    def resolve_game(self, app_id: int, expected_name: str) -> GameRef:
        """What the store says ``app_id`` is — guard verdict and totals included.

        Two paced requests: appdetails for the current store name (the identity
        guard compares it against ``expected_name`` and records its verdict in
        the returned record — a mismatch is an answer, not an exception), and
        the totals-only read for Steam's own population claim. The totals stay
        ``None`` when Steam reported none — a no-data id can still carry
        review totals (delisted games keep their reviews), so the two reads
        are independent by design.
        """
        details = self._transport.get_json(
            _APPDETAILS_URL, {"appids": app_id, "cc": "us", "l": "english"}
        )
        store_name = parse_appdetails(details, app_id)
        totals_page = parse_review_page(
            self._transport.get_json(_REVIEWS_URL.format(app_id=app_id), _TOTALS_PARAMS),
            app_id,
        )
        summary = totals_page.summary
        return GameRef(
            app_id=app_id,
            requested_name=expected_name,
            store_name=store_name,
            verdict=identity_verdict(expected_name, store_name),
            total_reviews=summary.total_reviews if summary else None,
            total_positive=summary.total_positive if summary else None,
            total_negative=summary.total_negative if summary else None,
        )

    def fetch_histogram(self, app_id: int) -> HistogramSnapshot:
        """The game's review-volume histogram as Steam serves it right now.

        One paced request; the rollup unit is read from the response and the
        snapshot is stamped with this client's clock — histogram shape drives
        window planning and the fallback's feasibility estimate, so freshness
        must be checkable.
        """
        payload = self._transport.get_json(
            _HISTOGRAM_URL.format(app_id=app_id), {"l": "english"}
        )
        return parse_histogram(payload, app_id, self._now())

    def fetch_window(
        self, app_id: int, window_start: datetime, window_end: datetime
    ) -> WindowFetchResult:
        """Every review of ``app_id`` in the window (inclusive), with provenance.

        The primary path is the windowed-unfiltered walk: ``filter=recent``
        composed with the undocumented date-window params — the composition
        every probe this project ran validated, which the donor never used.
        Because the params are undocumented, nothing is trusted: every
        returned timestamp is checked against the window, and a clean walk
        returns as ``WINDOWED`` with the violation count (zero) as its
        semantic-validation verdict.

        A clean windowed walk that ended on empty-page exhaustion, or that
        collected fewer reviews than Steam's own window total, is still
        returned as ``WINDOWED`` but WARN-narrated — trusted with disclosure,
        never silently assumed complete. (The fallback's summary describes the
        whole game, so only the exhaustion check applies there.)

        A dirty verdict — any out-of-window review — means the window params
        were not honored, so the windowed collection cannot be trusted
        complete; the strict walk stops at the end of its first dirty page
        rather than paying the full descent the feasibility gate exists to
        refuse. The client then fetches the histogram (one more paced
        request), prices the plain-cursor approach with the feasibility
        estimate, and either walks the fallback (same engine, timestamp-gated;
        returns ``FALLBACK_WALKED``, whose ``reported_total`` is ``None``
        because a plain query's summary describes the whole game) or returns
        ``SKIPPED_INFEASIBLE`` with no reviews — a disclosed hole, never a
        silent one, keeping the windowed attempt's violation count as the
        evidence. ``pages_fetched`` and ``retries`` always account every page
        spent across both attempts; both decisions are narrated over the sink.

        Raises ``ValueError`` on a naive or inverted window — the wire speaks
        epoch seconds, and a naive datetime would silently shift by the
        machine's zone.
        """
        _check_window(window_start, window_end)
        url = _REVIEWS_URL.format(app_id=app_id)
        windowed_params: dict[str, str | int] = {
            **_UNFILTERED_BASE,
            "filter": "recent",
            "num_per_page": self._config.num_per_page,
            "start_date": int(window_start.timestamp()),
            "end_date": int(window_end.timestamp()),
            "date_range_type": "include",
        }
        retries_before = self._transport.retries_spent

        windowed = self._walk(url, windowed_params, app_id, window_start, window_end, strict=True)
        if windowed.out_of_window == 0:
            self._disclose_windowed_trust(app_id, windowed)
            return self._result(
                app_id, window_start, window_end, PathOutcome.WINDOWED, windowed,
                retries=self._transport.retries_spent - retries_before,
            )

        self._warn(
            f"windowed params not honored for app {app_id} "
            f"({windowed.out_of_window} out-of-window): falling back to the plain cursor walk"
        )
        histogram = self.fetch_histogram(app_id)
        skip_pages = estimate_skip_pages(histogram, window_end, self._config.num_per_page)
        if skip_pages > self._config.fallback_page_budget:
            self._warn(
                f"fallback infeasible for app {app_id}: ~{skip_pages} approach pages "
                f"> budget {self._config.fallback_page_budget} — window skipped"
            )
            skipped = WalkTally(
                reviews=(),
                pages_fetched=windowed.pages_fetched,
                out_of_window=windowed.out_of_window,
                reported_total=windowed.reported_total,
                stopped_on_empty_pages=windowed.stopped_on_empty_pages,
            )
            return self._result(
                app_id, window_start, window_end, PathOutcome.SKIPPED_INFEASIBLE, skipped,
                retries=self._transport.retries_spent - retries_before,
            )

        plain_params: dict[str, str | int] = {
            **_UNFILTERED_BASE,
            "filter": "recent",
            "num_per_page": self._config.num_per_page,
        }
        fallback = self._walk(url, plain_params, app_id, window_start, window_end, strict=False)
        if fallback.stopped_on_empty_pages:
            self._warn(
                f"fallback walk for app {app_id} ended on empty-page exhaustion — "
                "the collection may be truncated, not proven complete"
            )
        merged = WalkTally(
            reviews=fallback.reviews,
            pages_fetched=windowed.pages_fetched + fallback.pages_fetched,
            out_of_window=0,
            reported_total=None,
            stopped_on_empty_pages=fallback.stopped_on_empty_pages,
        )
        return self._result(
            app_id, window_start, window_end, PathOutcome.FALLBACK_WALKED, merged,
            retries=self._transport.retries_spent - retries_before,
        )

    def _walk(
        self,
        url: str,
        params: dict[str, str | int],
        app_id: int,
        window_start: datetime,
        window_end: datetime,
        *,
        strict: bool,
    ) -> WalkTally:
        """One engine run over ``params`` — the two paths differ only here."""

        def fetch_page(cursor: str) -> ReviewPage:
            return parse_review_page(
                self._transport.get_json(url, {**params, "cursor": cursor}), app_id
            )

        return walk_pages(
            fetch_page, window_start, window_end, out_of_window_is_violation=strict
        )

    def _result(
        self,
        app_id: int,
        window_start: datetime,
        window_end: datetime,
        outcome: PathOutcome,
        tally: WalkTally,
        *,
        retries: int,
    ) -> WindowFetchResult:
        return WindowFetchResult(
            app_id=app_id,
            window_start=window_start,
            window_end=window_end,
            outcome=outcome,
            pages_fetched=tally.pages_fetched,
            retries=retries,
            out_of_window_count=tally.out_of_window,
            reported_total=tally.reported_total,
            reviews=tally.reviews,
        )

    def _disclose_windowed_trust(self, app_id: int, tally: WalkTally) -> None:
        """WARN when a clean windowed walk is not beyond suspicion.

        An empty-page exhaustion stop or a shortfall against Steam's own
        window total means the collection may be truncated; both checks are
        windowed-only — the fallback's unwindowed summary describes the whole
        game and supports neither.
        """
        if tally.stopped_on_empty_pages:
            self._warn(
                f"windowed walk for app {app_id} ended on empty-page exhaustion — "
                "the collection may be truncated, not proven complete"
            )
        if tally.reported_total is not None and len(tally.reviews) < tally.reported_total:
            self._warn(
                f"windowed walk for app {app_id} collected {len(tally.reviews)} of "
                f"Steam's reported {tally.reported_total} for the window"
            )

    def _warn(self, message: str) -> None:
        self._sink.emit(StageEvent(stage="steam.fetch", kind=StageKind.WARN, message=message))


def _check_window(window_start: datetime, window_end: datetime) -> None:
    """Refuse naive or inverted windows before they reach the wire."""
    if window_start.tzinfo is None or window_end.tzinfo is None:
        raise ValueError("window datetimes must be timezone-aware")
    if window_start > window_end:
        raise ValueError(f"window_start {window_start} is after window_end {window_end}")
