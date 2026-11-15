"""Reading a game's reviews for the chat — the excerpts behind a reply.

Two reads, one per kind of thing a turn can ask reviews about. A pinned
aspect is read by label: the reviews the classifier marked with it, each cut
to the sentence around its stored evidence span, chosen by a seeded draw
because a label gives nothing to rank by. Words are read by search: the
game's best-ranked matches from the keyword index, each cut to the sentence
around the matched words. That covers a want on a search term and the
search words a store fact carries. The cutting and the draw are pure and
live in ``core.excerpt``; this module does the reading.

Both reads cover the reviews the game's newest report counted and nothing
else, the pool every number on the sheet was counted over. And both leave
out a review that contains "spoiler" before anything is chosen or cut, so
such a review reaches no prompt and can be neither quoted nor paraphrased.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from steamlens.contracts import EvidenceQuote, Excerpt, LibraryGame
from steamlens.core.excerpt import (
    LABELLED_READ_FLOOR,
    mentions_spoiler,
    seeded_draw,
    sentence_display_text,
    term_excerpt_text,
)
from steamlens.store import Store

EXCERPTS_PER_READ: Final = 6
"""How many excerpts one read returns at most: enough to see a word used in
another meaning, few enough that six candidates on four wants stay readable."""

_SEARCH_MARGIN: Final = 4
"""A word read asks the index for this many times the limit, so a review left
out for containing "spoiler" does not shorten the read. About one counted
review in a hundred contains it."""


def aspect_excerpts(
    store: Store, game: LibraryGame, aspect: str, *, limit: int = EXCERPTS_PER_READ
) -> tuple[Excerpt, ...]:
    """Excerpts from ``game``'s reviews labelled with the pinned ``aspect``.

    At most ``limit``, drawn in proportion to the labels' sentiments and
    fixed by the game's report and the aspect, so the same read returns the
    same excerpts. Each carries its label's sentiment. A review whose label
    holds no evidence span has nothing to cut around and is not read.

    Empty when fewer of the game's reviews mention the aspect than the read
    floor (``core.excerpt.LABELLED_READ_FLOOR``): below it a label is too
    often about something else.

    Raises ``ValueError`` when the game's report is not in the store, which
    means the game was not loaded from it.
    """
    mentions = next((cell.mentions for cell in game.cells if cell.aspect == aspect), 0)
    if mentions < LABELLED_READ_FLOOR:
        return ()
    versions = store.reports.versions(game.run_id)
    if versions is None:
        raise ValueError(
            f"game {game.app_id} is read from report {game.run_id!r}, which the store does "
            "not hold"
        )
    quotes = [
        EvidenceQuote(review_id, aspect, sentiment, evidence)
        for review_id, labelled, sentiment, evidence in store.labels.iter_member_evidence(
            game.run_id, versions
        )
        if labelled == aspect
    ]
    reviews = store.reviews.get_many({quote.review_id for quote in quotes})
    readable = [
        quote for quote in quotes
        if quote.review_id in reviews and not mentions_spoiler(reviews[quote.review_id].text)
    ]
    return tuple(
        Excerpt(
            app_id=game.app_id,
            review_id=quote.review_id,
            text=sentence_display_text(quote.text, reviews[quote.review_id].text),
            sentiment=quote.sentiment,
        )
        for quote in seeded_draw(readable, limit, seed=f"{game.run_id}:{aspect}")
    )


def term_excerpts(
    store: Store, game: LibraryGame, phrases: Sequence[str], *, limit: int = EXCERPTS_PER_READ
) -> tuple[Excerpt, ...]:
    """Excerpts from ``game``'s reviews that match any of ``phrases``, best match first.

    At most ``limit``, in the keyword index's own order. A match says a
    review uses the words and not which way it points, so an excerpt here
    carries no sentiment.
    """
    ranked = store.review_search.search_game(
        game.app_id, phrases, limit=limit * _SEARCH_MARGIN
    )
    reviews = store.reviews.get_many(ranked)
    excerpts: list[Excerpt] = []
    for review_id in ranked:
        review = reviews.get(review_id)
        if review is None or mentions_spoiler(review.text):
            continue
        excerpts.append(
            Excerpt(game.app_id, review_id, term_excerpt_text(review.text, phrases))
        )
        if len(excerpts) == limit:
            break
    return tuple(excerpts)
