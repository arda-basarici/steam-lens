"""The one door to Steam — resolve, histogram, and window fetches behind one seam.

All live Steam access goes through this package: ``SteamTransport`` is the
paced, retried GET chokepoint every operation shares, dialed by
``SteamClientConfig``, with typed failures in ``errors``. The operations
(resolve + identity guard, histogram snapshot, the windowed walk and its
cursor fallback) land on top of it. Design record: DESIGN.md's
"``steam_client`` E1 build: the door, three operations, both paths" entry
(2026-07-27).
"""

from steamlens.steam_client.config import SteamClientConfig
from steamlens.steam_client.errors import (
    SteamClientError,
    SteamResponseError,
    SteamUnavailableError,
)
from steamlens.steam_client.parse import (
    QuerySummary,
    ReviewPage,
    parse_histogram,
    parse_review_page,
    review_from_raw,
)
from steamlens.steam_client.transport import SteamTransport

__all__ = [
    # the chokepoint
    "SteamTransport",
    # config
    "SteamClientConfig",
    # parsers
    "parse_review_page",
    "parse_histogram",
    "review_from_raw",
    "ReviewPage",
    "QuerySummary",
    # errors
    "SteamClientError",
    "SteamUnavailableError",
    "SteamResponseError",
]
