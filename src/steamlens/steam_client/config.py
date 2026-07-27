"""The Steam door's dial — the few knobs the client deliberately exposes.

Small on purpose: most of the door's behavior (retry ceiling, backoff shape,
retryable statuses) is fixed policy the design ruled, not configuration — a
knob that must never be turned is safer as a constant. What remains here are
the values with a legitimate reason to vary per composition: the pacing floor
(the politeness budget), the request timeout, and the User-Agent (Steam
throttles the default library UA, and the escape hatch if the named one is
ever rejected is a browser string — a config edit, not a code change).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SteamClientConfig:
    """The Steam client's composition-time settings.

    ``pacing_floor_s`` is the flat inter-request delay every attempt inherits —
    the default 1.5s sits at the folklore ~200-requests-per-5-minutes budget;
    ``timeout_s`` bounds each attempt; ``user_agent`` names us to Steam (the
    default requests/urllib UA gets throttled, so a named one is required).
    ``num_per_page`` is the review-page size — deliberately non-load-bearing:
    no batch size is universally safe (the donor's "80 is reliable" comment is
    a documented inaccuracy — the same bug thread reports 80 failing where 100
    works), so safety lives in the walk's detect-and-retry and window-bounded
    stops, never in this number. Default 100 matches every probe this project
    ran.
    """

    pacing_floor_s: float = 1.5
    timeout_s: float = 30.0
    user_agent: str = "steam-lens/0.1 (+https://github.com/arda-basarici)"
    num_per_page: int = 100
