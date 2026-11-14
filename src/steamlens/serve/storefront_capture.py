"""Capturing what the store says a game is — the one routine the job and the backfill share.

Two paced reads per game, the store's metadata and the tag block of its store
page, each stored as that game's latest capture. The report job runs this
after it publishes, and the backfill runs it for library games published
before the capture existed; both go through this function so a game is read
and recorded the same way whichever asked.

Both reads fail soft. Steam trouble on either one is narrated as a warning
and the caller carries on: for a job the report is the product, and for the
backfill one game's trouble must not stop the rest. Only the Steam door's own
failures are absorbed; a failure in the store or in this code stays loud.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from steamlens.contracts import Sink, StageKind
from steamlens.dispatch import narrate
from steamlens.steam_client import SteamClient, SteamClientError
from steamlens.store import Store

STOREFRONT_STAGE: Final = "serve.storefront"
"""The stage these captures narrate under. The live page's checklist does not
list it, so the lines reach the run log and the job journal only: the capture
is bookkeeping for the recommender chat, not a step of the report."""


@dataclass(frozen=True, slots=True)
class CaptureResult:
    """Which of a game's two records one capture actually stored."""

    metadata: bool
    tags: bool


def capture_storefront(
    steam: SteamClient,
    store: Store,
    app_id: int,
    sink: Sink,
    *,
    metadata: bool = True,
    tags: bool = True,
) -> CaptureResult:
    """Read and record ``app_id``'s store facts, each read failing soft.

    ``metadata`` and ``tags`` select which reads are made, so a game owed
    only one is asked only that. A read that fails, a store with no record
    for the game, and a store page without a tag block each leave that record
    unstored and narrate why; nothing is stored in their place. In
    particular a page without a tag block (a gate in place of the game's
    page) is never recorded as a game without tags.
    """
    stored_metadata = metadata and _capture_metadata(steam, store, app_id, sink)
    stored_tags = tags and _capture_tags(steam, store, app_id, sink)
    return CaptureResult(metadata=stored_metadata, tags=stored_tags)


def _capture_metadata(steam: SteamClient, store: Store, app_id: int, sink: Sink) -> bool:
    try:
        metadata = steam.storefront_metadata(app_id)
    except SteamClientError as exc:
        narrate(
            sink, STOREFRONT_STAGE, StageKind.WARN,
            f"app {app_id}: store facts not captured: {exc}",
        )
        return False
    if metadata is None:
        narrate(
            sink, STOREFRONT_STAGE, StageKind.WARN,
            f"app {app_id}: store facts not captured: the store has no record for it",
        )
        return False
    store.storefront.put_metadata(metadata)
    narrate(
        sink, STOREFRONT_STAGE, StageKind.DONE,
        f"app {app_id}: store facts recorded "
        f"({len(metadata.genres)} genres, {len(metadata.categories)} categories)",
    )
    return True


def _capture_tags(steam: SteamClient, store: Store, app_id: int, sink: Sink) -> bool:
    try:
        tags = steam.storefront_tags(app_id)
    except SteamClientError as exc:
        narrate(
            sink, STOREFRONT_STAGE, StageKind.WARN,
            f"app {app_id}: store tags not captured: {exc}",
        )
        return False
    if tags is None:
        narrate(
            sink, STOREFRONT_STAGE, StageKind.WARN,
            f"app {app_id}: store tags not captured: "
            "the store page came back without a tag block",
        )
        return False
    store.storefront.put_tags(tags)
    narrate(
        sink, STOREFRONT_STAGE, StageKind.DONE,
        f"app {app_id}: store tags recorded ({len(tags.tags)} tags)",
    )
    return True
