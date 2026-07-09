"""The cleaned review record — one Steam review as it crosses into the core.

``Review`` is source-neutral by design: it holds an already-parsed review, not a
Steam payload. Whichever shell ingests raw data — the live ``steam_client`` or
the offline corpus reader — does the source-specific parsing (Steam's epoch
seconds become a timezone-aware ``datetime`` there, not here), so the contract
carries no allegiance to any one wire format. Once built, a ``Review`` is trusted
by construction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Review:
    """One cleaned Steam review.

    ``review_id`` is Steam's ``recommendationid`` (a string, kept verbatim as the
    stable identity); ``app_id`` is the game it belongs to; ``created_at`` is when
    it was posted, as a timezone-aware ``datetime`` (the shell converts Steam's
    unix epoch — the contract never sees the raw number); ``language`` is Steam's
    language tag; ``text`` is the review body; ``voted_up`` is the reviewer's
    overall recommend/not-recommend verdict, deliberately separate from any
    per-aspect sentiment. Reception metadata (helpful votes, playtime) is left
    off until a consumer — detection or weighting — actually needs it.
    """

    review_id: str
    app_id: int
    created_at: datetime
    language: str
    text: str
    voted_up: bool
