"""Behavioral claims on the Steam transport chokepoint — scripted wire, no network.

Every test runs against ``httpx.MockTransport`` with a scripted response
sequence and an injected sleep/clock, so the transport policy — the flat
pacing floor at the top of every attempt, exponential backoff on retryable
trouble only, permanent errors never retried, typed exhaustion — is pinned
without a real request or a real wait.
"""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
from fakes import CollectingSink

from steamlens.contracts import StageEvent, StageKind
from steamlens.steam_client import (
    SteamClientConfig,
    SteamResponseError,
    SteamTransport,
    SteamUnavailableError,
)

_URL = "https://store.steampowered.com/appreviews/440"


class Harness:
    """One transport over a scripted response sequence, with sleep/clock recorded.

    The clock is frozen: ``monotonic`` always returns the same instant, so the
    pacing computation sees zero elapsed time and every post-first attempt owes
    the full floor — which makes the expected sleep sequence exact.
    """

    def __init__(self, script: list[httpx.Response | Exception]) -> None:
        self.sleeps: list[float] = []
        self.sink = CollectingSink()
        self.requests: list[httpx.Request] = []
        feed: Iterator[httpx.Response | Exception] = iter(script)

        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            step = next(feed)
            if isinstance(step, Exception):
                raise step
            return step

        self.transport = SteamTransport(
            SteamClientConfig(),
            self.sink,
            transport=httpx.MockTransport(handler),
            sleep=self.sleeps.append,
            monotonic=lambda: 100.0,
        )


def _ok(body: str = '{"success": 1}') -> httpx.Response:
    return httpx.Response(200, text=body)


# --- the clean path ------------------------------------------------------------


def test_success_returns_parsed_object_and_first_request_pays_no_floor() -> None:
    """A clean 200 parses to the JSON object; the first-ever request has no
    predecessor, so the pacing floor owes nothing and no sleep happens."""
    h = Harness([_ok('{"success": 1, "cursor": "*"}')])
    assert h.transport.get_json(_URL, {"json": 1}) == {"success": 1, "cursor": "*"}
    assert h.sleeps == []
    assert h.transport.retries_spent == 0


def test_consecutive_requests_hold_the_pacing_floor() -> None:
    """Under a frozen clock the second request owes the whole floor — the flat
    1.5s politeness budget between any two requests, endpoint-independent."""
    h = Harness([_ok(), _ok()])
    h.transport.get_json(_URL, {})
    h.transport.get_json(_URL, {})
    assert h.sleeps == [1.5]


def test_params_reach_the_wire() -> None:
    """The params dict lands URL-encoded on the request — including the cursor
    characters (+/=) that would corrupt if double-encoded."""
    h = Harness([_ok()])
    h.transport.get_json(_URL, {"cursor": "AoJw+M8=", "num_per_page": 100})
    assert h.requests[0].url.params["cursor"] == "AoJw+M8="
    assert h.requests[0].url.params["num_per_page"] == "100"


def test_named_user_agent_on_every_request() -> None:
    """The default library UA gets throttled by Steam, so the configured named
    one must ride every request."""
    h = Harness([_ok()])
    h.transport.get_json(_URL, {})
    assert h.requests[0].headers["User-Agent"].startswith("steam-lens/")


# --- retryable trouble ---------------------------------------------------------


def test_retryable_status_backs_off_then_succeeds_with_pacing_inherited() -> None:
    """A 429 costs one backoff sleep (2s), and the retry attempt still pays the
    pacing floor at the top of the loop — every attempt inherits it."""
    h = Harness([httpx.Response(429), _ok()])
    assert h.transport.get_json(_URL, {}) == {"success": 1}
    assert h.sleeps == [2.0, 1.5]
    assert h.transport.retries_spent == 1
    warns = [e for e in h.sink.events if isinstance(e, StageEvent)]
    assert len(warns) == 1 and warns[0].kind is StageKind.WARN


def test_network_failures_are_retried() -> None:
    """Transport-level exceptions are the same transient weather as a 5xx."""
    h = Harness([httpx.ConnectError("boom"), httpx.ReadTimeout("slow"), _ok()])
    assert h.transport.get_json(_URL, {}) == {"success": 1}
    assert h.transport.retries_spent == 2


def test_exhaustion_raises_typed_after_six_attempts() -> None:
    """Six attempts, backoff 2**attempt between them, then the typed give-up —
    with the pacing floor paid before every attempt after the first."""
    h = Harness([httpx.Response(503)] * 6)
    with pytest.raises(SteamUnavailableError, match="outlived 6 attempts"):
        h.transport.get_json(_URL, {})
    assert len(h.requests) == 6
    backoffs = [s for s in h.sleeps if s != 1.5]
    assert backoffs == [2.0, 4.0, 8.0, 16.0, 32.0]
    assert h.sleeps.count(1.5) == 5


# --- permanent trouble: never retried ------------------------------------------


def test_non_retryable_status_raises_immediately() -> None:
    """A 404 is Steam answering for keeps — one request, no retry, no backoff."""
    h = Harness([httpx.Response(404, text="not found")])
    with pytest.raises(SteamResponseError, match="HTTP 404"):
        h.transport.get_json(_URL, {})
    assert len(h.requests) == 1
    assert h.sleeps == []


def test_200_with_unparseable_body_is_permanent() -> None:
    """A 200 wrapping garbage re-garbages on retry — permanent typed error."""
    h = Harness([_ok("<html>maintenance</html>")])
    with pytest.raises(SteamResponseError, match="unparseable body"):
        h.transport.get_json(_URL, {})
    assert len(h.requests) == 1


def test_200_with_non_object_json_is_permanent() -> None:
    """A JSON body that isn't an object breaks the contract the same way."""
    h = Harness([_ok("[1, 2, 3]")])
    with pytest.raises(SteamResponseError, match="non-object JSON"):
        h.transport.get_json(_URL, {})
    assert len(h.requests) == 1
