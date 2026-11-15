"""Print the review excerpts the chat would read, for a few games and wants.

What it answers: what a model is actually handed when the chat reads a game's
reviews. For a handful of library games it prints the excerpts of one aspect
read by label (a seeded draw in proportion to the labels' sentiments) and of
one set of words read by search (the keyword index's best matches), each cut
to the sentence around its anchor, and how many reviews containing "spoiler"
each read left out.

The cases are written by hand and are not the example conversations. They
were picked to show the two reads on a game the thing clusters in, on one
where it is thin, and on the search words of a store fact.

Read-only on the reviews; opening the copy migrates it to the current schema,
so point this at a scratch copy and never at the dated copies under ``data/``.
No request leaves the machine.

Run: python probes/excerpts_read.py <path to a database copy>
"""

from __future__ import annotations

import sys

from steamlens.chat.evidence import EXCERPTS_PER_READ, aspect_excerpts, term_excerpts
from steamlens.chat.sheet import load_library
from steamlens.contracts import Excerpt, LibraryGame
from steamlens.core.excerpt import mentions_spoiler
from steamlens.core.game_names import resolve_name
from steamlens.core.store_facts import store_fact
from steamlens.store import Store

# (library title, a pinned aspect to read by label, words to read by search).
CASES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("Hades", "story", ("frantic", "hectic", "chaotic")),
    ("Baldur's Gate 3", "characters", store_fact("co-op").search_words),
    ("Blue Prince", "difficulty", ("timer", "timed", "time limit")),
    ("Graveyard Keeper", "progression", ("grind", "grindy", "grinding")),
    ("Stardew Valley", "music", store_fact("adjustable-difficulty").search_words),
)


def show(excerpts: tuple[Excerpt, ...]) -> None:
    if not excerpts:
        print("      nothing read")
    for excerpt in excerpts:
        mark = f"{excerpt.sentiment.value:<8}" if excerpt.sentiment else ""
        print(f"      {excerpt.review_id:>10} {mark} {excerpt.text}")


def spoilers_among(store: Store, game: LibraryGame, phrases: tuple[str, ...]) -> int:
    """How many of the game's matches for ``phrases`` contain "spoiler"."""
    ids = store.review_search.search_game(game.app_id, phrases, limit=game.sample_size)
    return sum(mentions_spoiler(review.text) for review in store.reviews.get_many(ids).values())


def main(db_path: str) -> None:
    with Store(db_path) as store:
        library = {game.app_id: game for game in load_library(store)}
        names = {app_id: game.name for app_id, game in library.items()}
        print(f"{len(library)} games · at most {EXCERPTS_PER_READ} excerpts a read\n")
        for title, aspect, phrases in CASES:
            found = resolve_name([title], names)
            if found.app_id is None:
                raise SystemExit(f"{title!r} is not one title in this library copy")
            game = library[found.app_id]
            mentions = next((cell.mentions for cell in game.cells if cell.aspect == aspect), 0)
            print(f"{game.name} · {game.sample_size} counted reviews")
            print(f"   by label: {aspect} ({mentions} reviews mention it)")
            show(aspect_excerpts(store, game, aspect))
            matches = len(
                store.review_search.search_game(game.app_id, phrases, limit=game.sample_size)
            )
            left_out = spoilers_among(store, game, phrases)
            print(
                f"   by search: {' / '.join(phrases)} ({matches} reviews match,"
                f" {left_out} of them left out for containing \"spoiler\")"
            )
            show(term_excerpts(store, game, phrases))
            print()


if __name__ == "__main__":
    main(sys.argv[1])
