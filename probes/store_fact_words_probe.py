"""Store-fact search words probe: do the words written for a store fact find reviews about it?

Each store fact in the chat's vocabulary carries a short list of search words
(``core/store_facts.py``). They fetch a game's reviews on the fact's subject
in two cases: a game offered although it conflicts with a must on that fact,
and a question about one game ("does it have co-op?"). The same words run
every time, so each list can be read once, here, against the store's own
listing. Per fact:

- reach: of the games the store lists the fact for, and of the games it does
  not, how many have at least one counted review matching the list, and how
  many reviews a game with any has (the median);
- each phrase alone: how many reviews and games it matches on each side of
  the listing, so a phrase that adds nothing or matches everywhere shows;
- what a phrase finds: the review the search ranks first for it, in the game
  where it matches most, cut to the words around the match. This is where an
  off-meaning use of a word shows ("solo" as a name, "mac" as a nickname).

A match says a review is about the subject and not which way it points, so
nothing here is a hit rate for the fact itself: "not listed, with a review to
read" is how often the judge would have something to read against the store's
answer, not how often the store is wrong.

The window printed around a match is this probe's own cut for reading the
output. It is not the excerpt the chat shows a model.

Result (2026-11-15, a copy of the serving database taken on the evening of
2026-11-14: 115 games with store facts, 60,514 counted reviews, 40 facts and
145 phrases):

- Where reviewers name the thing, a game the store lists it for nearly
  always has a review to read: RPG 45 of 46 games, simulation 30 of 32,
  strategy 27 of 31, multi-player 48 of 48, co-op 37 of 37, Steam Workshop
  20 of 20, controller support 56 of 65.
- Features reviewers do not name stay thin whatever the words: LAN play 0 of
  5 and 0 of 3 listed games, Remote Play Together 1 of 7, level editor 1 of
  7, split screen 2 of 7, "Playable without timed input" 2 of 26, subtitle
  options 3 of 14. A question about one of these is answered from the
  store's listing with few or no reviews behind it.
- A game the store does not list a fact for often has reviews on the subject
  anyway: simulation 43 of 83 games, Linux 57 of 91, adjustable difficulty
  45 of 91, co-op 39 of 78. Those reviews do not say the game has the thing,
  which is why they are read and not counted.
- The first pass dropped words found matching another meaning: "races" (a
  role-playing game's playable races), "simulator" (219 reviews in 61 games
  the store does not list as simulations, its first read a joke title),
  "versus" (a game's name), "headset" (headphones), "racers" (characters in
  a racing game).

Limits: one library on one day, and the lists were written and trimmed by
hand against this output. The first read shown for a phrase is one review,
enough to catch a wrong meaning that dominates and not one that is rare.

Read-only on the reviews; opening the copy migrates it to the current schema,
so point this at a scratch copy and never at the dated copies under ``data/``.
No request leaves the machine.

Run: python probes/store_fact_words_probe.py <path to a database copy>
"""

from __future__ import annotations

import re
import statistics
import sys

from steamlens.chat.sheet import load_library
from steamlens.contracts import LibraryGame, StoreFactDef
from steamlens.core.store_facts import STORE_FACTS, is_listed
from steamlens.store import Store

WINDOW = 110
"""Characters shown on each side of a match."""


def match_window(text: str, phrase: str) -> str:
    """``text`` cut to the first place ``phrase`` matches, with a window around it.

    The index matches a phrase as its words in order, whatever separates
    them, so "co-op" finds "co op" and "CO-OP". The same reading is used
    here to find the place. A review the index matched and this pattern
    does not find is shown from its start.
    """
    words = re.findall(r"\w+", phrase)
    found = re.search(r"\W+".join(re.escape(word) for word in words), text, re.IGNORECASE)
    start = max(0, found.start() - WINDOW) if found else 0
    end = min(len(text), found.end() + WINDOW) if found else 2 * WINDOW
    cut = " ".join(text[start:end].split())
    return ("…" if start > 0 else "") + cut + ("…" if end < len(text) else "")


def reach(games: list[LibraryGame], hits: dict[int, int]) -> str:
    """How many of ``games`` have a matching review, and the median count among those."""
    counts = [hits[game.app_id] for game in games if game.app_id in hits]
    median = f", median {statistics.median(counts):.0f} matching reviews" if counts else ""
    return f"{len(games):>3} games, {len(counts):>3} with a review to read{median}"


def side_counts(games: list[LibraryGame], hits: dict[int, int]) -> str:
    """The reviews and games a phrase matches among ``games``."""
    counts = [hits[game.app_id] for game in games if game.app_id in hits]
    return f"{sum(counts):>5} reviews in {len(counts):>3} games"


def read_fact(store: Store, fact: StoreFactDef, library: list[LibraryGame]) -> None:
    names = {game.app_id: game.name for game in library}
    listed = [game for game in library if game.storefront and is_listed(fact, game.storefront)]
    unlisted = [game for game in library if game not in listed]
    together = store.review_search.game_hit_counts(fact.search_words)
    kind = "every game declares it" if fact.complete else "declared by choice"
    print(f"{fact.key} · {fact.label} · {kind}")
    print(f"   the store lists it:   {reach(listed, together)}")
    print(f"   the store does not:   {reach(unlisted, together)}")
    for phrase in fact.search_words:
        hits = store.review_search.game_hit_counts([phrase])
        print(
            f"   {phrase!r:<24} listed {side_counts(listed, hits)}"
            f" · not listed {side_counts(unlisted, hits)}"
        )
        if not hits:
            continue
        most = min(hits, key=lambda app_id: (-hits[app_id], app_id))
        (review_id,) = store.review_search.search_game(most, [phrase], limit=1)
        review = store.reviews.get(review_id)
        if review is None:
            raise SystemExit(f"review {review_id} is in the search index and not in the store")
        window = match_window(review.text, phrase)
        print(f"      first read, {names[most]} ({hits[most]}): {window}")
    print()


def main(db_path: str) -> None:
    with Store(db_path) as store:
        library = [game for game in load_library(store) if game.storefront is not None]
        phrases = sum(len(fact.search_words) for fact in STORE_FACTS)
        print(
            f"{len(STORE_FACTS)} store facts · {phrases} phrases · {len(library)} games with"
            f" store facts · {sum(game.sample_size for game in library):,} counted reviews\n"
        )
        for fact in STORE_FACTS:
            read_fact(store, fact, library)


if __name__ == "__main__":
    main(sys.argv[1])
