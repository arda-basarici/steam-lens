"""The retry/backoff GET chokepoint — every request to Steam passes through here.

One method, ``get_json``, carries the whole transport policy, so every caller,
every endpoint, and every retry attempt inherits it by construction: the flat
pacing floor sits at the top of the attempt loop (the donor client's proven
politeness discipline — an unenforced budget is how a polite client becomes
impolite), the adaptive half is the exponential backoff on retryable trouble,
and a 200 whose body isn't a JSON object is a permanent typed error, never
retried. The httpx transport and the sleep are both injection seams, so the
suite scripts wire responses and never really waits.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from typing import cast

import httpx

from steamlens.contracts import Sink, StageEvent, StageKind
from steamlens.steam_client.config import SteamClientConfig
from steamlens.steam_client.errors import SteamResponseError, SteamUnavailableError

# Fixed policy, deliberately not config: six attempts with 2**attempt backoff
# (2s, 4s, 8s, 16s, 32s between them) rides out Steam's transient 429/5xx
# weather; anything that survives all six is genuinely down.
_MAX_ATTEMPTS = 6
_BACKOFF_BASE = 2.0
_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})


class SteamTransport:
    """The one place Steam is actually spoken to — paced, retried, parsed.

    Construction binds the dial and the seams: ``transport`` is httpx's test
    seam (an ``httpx.MockTransport`` serves scripted responses with no
    network), ``sleep`` and ``monotonic`` let tests observe pacing and backoff
    without waiting. The one ``httpx.Client`` is shared across calls for
    connection pooling and carries the named User-Agent on every request.
    ``retries_spent`` is a cumulative counter callers may difference around an
    operation to report its retry cost in provenance.
    """

    def __init__(
        self,
        config: SteamClientConfig,
        sink: Sink,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config
        self._sink = sink
        self._sleep = sleep
        self._monotonic = monotonic
        self._http = httpx.Client(
            timeout=config.timeout_s,
            headers={"User-Agent": config.user_agent},
            transport=transport,
        )
        self._last_request_at: float | None = None
        self._retries_spent = 0

    @property
    def retries_spent(self) -> int:
        """Cumulative retries this transport has spent since construction."""
        return self._retries_spent

    def get_json(self, url: str, params: Mapping[str, str | int]) -> dict[str, object]:
        """One paced, retried GET, returning the response body as a JSON object.

        Raises ``SteamUnavailableError`` when network failures or retryable
        statuses (429/5xx) outlive the attempt budget, and
        ``SteamResponseError`` — immediately, no retry — on any other
        non-200 status or a 200 whose body isn't a JSON object.
        """
        last_failure = ""
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            self._pace()
            try:
                response = self._http.get(url, params=dict(params))
            except httpx.TransportError as exc:
                last_failure = f"network failure: {exc!r}"
            else:
                if response.status_code not in _RETRYABLE_STATUSES:
                    return _parse_object(response, url)
                last_failure = f"HTTP {response.status_code}: {response.text[:200]}"
            if attempt == _MAX_ATTEMPTS:
                raise SteamUnavailableError(
                    f"steam transient trouble outlived {_MAX_ATTEMPTS} attempts "
                    f"({url}): {last_failure}"
                )
            self._retries_spent += 1
            delay = _BACKOFF_BASE**attempt
            self._sink.emit(
                StageEvent(
                    stage="steam.transport",
                    kind=StageKind.WARN,
                    message=(
                        f"transient steam failure (attempt {attempt}/{_MAX_ATTEMPTS}), "
                        f"retrying in {delay:.0f}s: {last_failure}"
                    ),
                )
            )
            self._sleep(delay)
        raise AssertionError("unreachable: the retry loop returns or raises")

    def _pace(self) -> None:
        """Hold the flat floor between consecutive requests — attempts included."""
        now = self._monotonic()
        if self._last_request_at is not None:
            wait = self._config.pacing_floor_s - (now - self._last_request_at)
            if wait > 0:
                self._sleep(wait)
        self._last_request_at = self._monotonic()


def _parse_object(response: httpx.Response, url: str) -> dict[str, object]:
    """A 200's body as a JSON object, or the permanent typed error — never a retry."""
    if response.status_code != 200:
        raise SteamResponseError(
            f"HTTP {response.status_code} from {url}: {response.text[:200]}"
        )
    try:
        parsed = json.loads(response.text)
    except json.JSONDecodeError as exc:
        raise SteamResponseError(
            f"HTTP 200 with unparseable body from {url}: {response.text[:200]!r}"
        ) from exc
    if not isinstance(parsed, dict):
        raise SteamResponseError(
            f"HTTP 200 with non-object JSON from {url}: {response.text[:120]!r}"
        )
    return cast("dict[str, object]", parsed)
