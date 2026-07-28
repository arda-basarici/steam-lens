"""The Steam-door records — what the live client answers with.

Three operations, three answers: resolving a game yields a ``GameRef``, reading
its review histogram yields a ``HistogramSnapshot``, and fetching a date window
of reviews yields a ``WindowFetchResult``. The window params and much of the
review API are undocumented, so these records are built to carry their own
verification instead of trusting Steam: the identity guard's conclusion lives
*in* the ``GameRef`` (recorded, never thrown), and every window fetch stamps
which path it took and whether the response actually honored the requested
window. Like every contract, they hold already-parsed data — the
``steam_client`` shell does the wire-format work (epoch seconds become
timezone-aware ``datetime``\\ s there), and a built record is trusted by
construction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from steamlens.contracts.enums import IdentityVerdict, PathOutcome, RollupUnit
from steamlens.contracts.reviews import Review


@dataclass(frozen=True, slots=True)
class GameRef:
    """One resolved game — what the store says this ``app_id`` is, guard verdict included.

    ``requested_name`` is what the caller expected; ``store_name`` is what the
    store returned (``None`` when the store had no data for the id); ``verdict``
    is the identity guard's comparison of the two — absorbed into the record
    because a mismatch is an honest answer about what Steam returned, not an
    exception (a wrapper record was rejected as a layer for one field). The
    totals are Steam's own population claim from the one-request totals-only
    read (``query_summary``): captured for feasibility estimates and coverage
    checks, never trusted as ground truth; ``None`` when the read yielded
    nothing.
    """

    app_id: int
    requested_name: str
    store_name: str | None
    verdict: IdentityVerdict
    total_reviews: int | None
    total_positive: int | None
    total_negative: int | None


@dataclass(frozen=True, slots=True)
class HistogramBucket:
    """One bucket of a review histogram — recommend/not-recommend counts from ``start``.

    ``start`` is the bucket's opening instant (timezone-aware; the shell
    converts Steam's epoch seconds); the bucket's width is carried by the
    series it belongs to — the rollup unit for the rollup series, one day for
    the recent strip.
    """

    start: datetime
    recommendations_up: int
    recommendations_down: int


@dataclass(frozen=True, slots=True)
class ReviewEvent:
    """One Steam-flagged anomalous review period — the histogram's ``past_events`` entry.

    Steam marks windows of off-topic review activity (review bombs) and
    *excludes their reviews from a default fetch* — the proven data-integrity
    bug that forces ``filter_offtopic_activity=0`` on every review request.
    These windows are also exactly where event investigation looks, so they are
    kept on the snapshot. ``event_type`` is Steam's undocumented numeric code,
    carried verbatim.
    """

    event_type: int
    start: datetime
    end: datetime


@dataclass(frozen=True, slots=True)
class HistogramSnapshot:
    """A game's review-volume histogram as Steam served it at ``fetched_at``.

    ``rollups`` is the full-lifetime series in ``rollup_unit`` buckets — the
    unit is read from the response, never assumed, because Steam sizes it by
    the game's age; ``recent_daily`` is the last-30-days daily strip;
    ``past_events`` are the flagged anomalous windows. ``fetched_at`` makes the
    snapshot's freshness checkable — histogram shape drives window planning,
    and a stale snapshot plans the wrong windows.
    """

    app_id: int
    rollup_unit: RollupUnit
    rollups: tuple[HistogramBucket, ...]
    recent_daily: tuple[HistogramBucket, ...]
    past_events: tuple[ReviewEvent, ...]
    fetched_at: datetime


@dataclass(frozen=True, slots=True)
class WindowFetchResult:
    """The reviews of one requested date window, plus the provenance to trust them.

    ``window_start``/``window_end`` are the window as requested; ``outcome``
    says which path delivered it. ``pages_fetched`` and ``retries`` record the
    request cost. ``out_of_window_count`` is the semantic-validation verdict as
    a measurement: how many returned reviews fell outside the requested window
    on the windowed path (trimmed from ``reviews``, counted here — nonzero
    means the undocumented window params were not honored; the count is
    evidence from the walk's first violating page, not a census, because a
    strict walk stops paying once the params are refuted). On the fallback
    path it is zero by construction, since timestamp gating *is* the mechanism
    there, not a violation. ``reported_total`` is Steam's own count for the
    windowed query from the first page's ``query_summary`` — captured even when
    the fetch returns nothing; ``None`` on the fallback path, whose unwindowed
    query summarizes the whole game, not the window.
    """

    app_id: int
    window_start: datetime
    window_end: datetime
    outcome: PathOutcome
    pages_fetched: int
    retries: int
    out_of_window_count: int
    reported_total: int | None
    reviews: tuple[Review, ...] = ()
