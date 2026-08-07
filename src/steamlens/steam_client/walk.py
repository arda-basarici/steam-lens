"""The cursor-walk engine — one loop discipline shared by both fetch paths.

The windowed walk and the plain-cursor fallback are the same machinery —
pagination, the seen-cursor and no-cursor guards, the empty-page retry — under
different page parameters and one judgment flag, so the engine lives once
behind a ``fetch_page`` callable and the client binds the parameters around
it. The stop discipline inverts the donor's proven-unsafe rule: a short or
empty page inside a window is *suspicious, not conclusive* — Steam serves
short pages mid-stream routinely — so short pages simply continue, and empty
pages retry the same cursor a bounded number of times before the walk
concludes the stream is really dry. The stops that ARE trusted: timestamps
exiting the window on the old side, a repeated cursor, a missing cursor, and
Steam's own "no result" answer (``success == 2``). A strict walk additionally
stops at the end of the first page carrying any out-of-window review — one
violation already refutes the window params, and descending further would pay
the very approach the feasibility gate exists to refuse. The empty-page
exhaustion stop is the one stop the module itself distrusts, so the tally
discloses it (``stopped_on_empty_pages``) instead of letting a possibly
truncated walk read as a trusted one.

Every review is judged against the window by zone: newer than the window,
inside it, or older. The two paths differ only in what "newer" means —
a violation of the windowed params (counted into the semantic-validation
verdict), or the fallback's expected skip phase (not a violation; timestamp
gating is the mechanism there).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from steamlens.contracts import Review
from steamlens.steam_client.errors import SteamResponseError
from steamlens.steam_client.parse import ReviewPage

# How many times an empty page re-asks the same cursor before the walk accepts
# the stream is dry. Bounded so a genuinely exhausted stream can't loop, but
# above zero so one flaky empty answer can't silently truncate a window. The
# budget resets whenever a page yields reviews — each suspicious stretch gets
# its own retries.
_EMPTY_PAGE_RETRIES: Final = 2

_FIRST_CURSOR: Final = "*"


@dataclass(frozen=True, slots=True)
class WalkTally:
    """What one cursor walk gathered and what it cost — the engine's answer.

    ``pages_fetched`` counts every successful page request, same-cursor
    retries included (they are real, paced requests); ``out_of_window`` is the
    semantic-validation count (always zero when the walk judges out-of-window
    reviews expected — the fallback's skip phase), scoped to the first
    violating page since a strict walk stops there rather than censusing the
    rest; ``reported_total`` is the first page's ``query_summary`` total,
    captured even from an empty answer. ``stopped_on_empty_pages`` names the
    one untrusted stop — the empty-page retry budget ran dry — so the caller
    can disclose a possibly truncated collection instead of trusting it.
    """

    reviews: tuple[Review, ...]
    pages_fetched: int
    out_of_window: int
    reported_total: int | None
    stopped_on_empty_pages: bool


def walk_pages(
    fetch_page: Callable[[str], ReviewPage],
    window_start: datetime,
    window_end: datetime,
    *,
    out_of_window_is_violation: bool,
    stop_after: int | None = None,
) -> WalkTally:
    """Walk ``fetch_page`` from the first cursor until a trusted stop, judging
    every review against the window (inclusive on both ends).

    ``fetch_page`` binds the endpoint and params (the two paths differ there);
    ``out_of_window_is_violation`` is the one judgment fork: the windowed path
    counts any out-of-window timestamp as a params violation and stops at the
    end of the first violating page (the count is evidence, not a census —
    one violation is all the dirty verdict needs), the fallback path treats
    out-of-window reviews as its expected approach and boundary phases (the
    trim is the mechanism, not a defect).

    ``stop_after`` is the sampling contract's quota stop: the stream serves
    newest-first, so ending the walk once that many in-window reviews are
    collected (truncating a mid-page overshoot) IS the plan contract's
    "newest-first, in the API's return order, up to quota" — and it is what
    keeps a sampled window's cost proportional to its quota instead of its
    volume. A deliberate quota stop is a trusted stop, not a truncation
    suspicion; the violation and past-the-window judgments run first on any
    page, so a dirty page still refutes the params even when it also fills
    the quota. Raises ``SteamResponseError`` on a ``success`` value that is
    neither 1 nor the documented no-result 2 — new wire knowledge, surfaced
    rather than guessed at.
    """
    cursor = _FIRST_CURSOR
    seen_cursors = {_FIRST_CURSOR}
    collected: list[Review] = []
    pages_fetched = 0
    out_of_window = 0
    reported_total: int | None = None
    empty_retries_left = _EMPTY_PAGE_RETRIES
    stopped_on_empty_pages = False

    while True:
        page = fetch_page(cursor)
        pages_fetched += 1
        if reported_total is None and page.summary is not None:
            reported_total = page.summary.total_reviews
        if page.success == 2:
            break  # Steam's own clean "no result" — an answer, not a suspicion
        if page.success != 1:
            raise SteamResponseError(
                f"review page: success is {page.success}, expected 1 or the no-result 2"
            )
        if not page.reviews:
            if empty_retries_left > 0:
                empty_retries_left -= 1
                continue  # re-ask the same cursor — suspicious, not conclusive
            stopped_on_empty_pages = True
            break
        empty_retries_left = _EMPTY_PAGE_RETRIES

        past_the_window = False
        for review in page.reviews:
            if review.created_at > window_end:
                if out_of_window_is_violation:
                    out_of_window += 1
            elif review.created_at < window_start:
                if out_of_window_is_violation:
                    out_of_window += 1
                past_the_window = True
            else:
                collected.append(review)
        if past_the_window:
            break  # the newest-first stream has descended below the window
        if out_of_window_is_violation and out_of_window:
            break  # first dirty page: the params are refuted — stop paying the descent
        if stop_after is not None and len(collected) >= stop_after:
            break  # quota filled: the newest-first prefix is complete
        if page.cursor is None or page.cursor in seen_cursors:
            break
        seen_cursors.add(page.cursor)
        cursor = page.cursor

    if stop_after is not None:
        # One truncation for every exit path — a page can overshoot the quota
        # mid-page, including on the same page that ends the walk another way.
        del collected[stop_after:]
    return WalkTally(
        reviews=tuple(collected),
        pages_fetched=pages_fetched,
        out_of_window=out_of_window,
        reported_total=reported_total,
        stopped_on_empty_pages=stopped_on_empty_pages,
    )
