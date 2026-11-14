"""Reading the stored library against a chat request — the sheet's store-facing shell.

The sheet's rules are pure and live in ``core.sheet``. This module gathers
what they read: for every library game its newest report's cells, the store's
facts and the tag block; and for every search term in a request, how many of
each game's counted reviews match. ``sheet_for`` composes the two into the
sheet for one request.

Everything is read fresh on each call. The library grows while the app runs,
and at its present size (115 games read in 0.05 s on a laptop, 2026-11-15) a
cache would add an invalidation question and save nothing a chat turn can
feel.
"""

from __future__ import annotations

from steamlens.contracts import LibraryGame, PlayerRequest, Sheet, TermTarget
from steamlens.core.sheet import read_sheet, sheet_cells
from steamlens.store import Store


def load_library(store: Store) -> tuple[LibraryGame, ...]:
    """Every library game as a request is read against it, ordered by app id.

    A game is in the library when it has a published report, and it is
    represented by its newest one. Its store facts and tags are whatever was
    last captured, ``None`` where a capture is still owed.
    """
    return tuple(
        LibraryGame(
            app_id=head.app_id,
            name=head.game_name,
            run_id=head.run_id,
            reported_at=head.created_at,
            sample_size=head.sample_size,
            complete_count=head.take_all,
            labeler=head.versions.model_version,
            cells=sheet_cells(store.reports.get_snapshot(head.run_id)),
            storefront=store.storefront.metadata(head.app_id),
            tags=store.storefront.tags(head.app_id),
        )
        for head in store.reports.newest_heads()
    )


def term_hit_counts(store: Store, request: PlayerRequest) -> dict[TermTarget, dict[int, int]]:
    """For each search term among the request's wants, the matching reviews per game.

    One search per distinct term. The counts are over each game's counted
    reviews, so they compare to the sample size on its ``LibraryGame``.
    """
    terms = {want.target for want in request.wants if isinstance(want.target, TermTarget)}
    return {term: store.review_search.game_hit_counts(term.phrases) for term in terms}


def sheet_for(store: Store, request: PlayerRequest) -> Sheet:
    """The stored library read against ``request``."""
    return read_sheet(request, load_library(store), term_hit_counts(store, request))
