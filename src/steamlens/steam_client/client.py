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

from steamlens.contracts import GameRef, Sink
from steamlens.steam_client.config import SteamClientConfig
from steamlens.steam_client.identity import identity_verdict
from steamlens.steam_client.parse import parse_appdetails, parse_review_page
from steamlens.steam_client.transport import SteamTransport

_APPDETAILS_URL: Final = "https://store.steampowered.com/api/appdetails"
_REVIEWS_URL: Final = "https://store.steampowered.com/appreviews/{app_id}"

# The one-request totals-only read: num_per_page=0 returns query_summary alone.
# The unfiltered trio avoids the sampling bias a default fetch bakes in, and
# filter_offtopic_activity=0 rides every fetch — the proven blanking bug.
_TOTALS_PARAMS: Final[dict[str, str | int]] = {
    "json": 1,
    "num_per_page": 0,
    "language": "all",
    "purchase_type": "all",
    "review_type": "all",
    "filter_offtopic_activity": 0,
}


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
