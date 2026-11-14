"""Keyword search over the reviews each game's newest report counted.

The recommender chat may discuss what a game's report was built from and
nothing else, so every read here is narrowed to one pool per game: the
members of its newest report's sample that hold a label under that report's
versions. That is exactly the set the report's sample size counts, which is
what lets a hit count be read as a share of it. A sample can hold members
without such a label; they are outside the report's numbers and outside this
pool.

Two reads. ``game_hit_counts`` answers, across the library, how many of each
game's counted reviews match: the input for nominating games on a want the
aspect vocabulary cannot express. ``search_game`` answers, inside one game,
which counted reviews match best: the retrieval behind a follow-up question.
Both return identifiers and counts, never text; the caller reads the reviews
it wants through ``ReviewStore``.

Search terms arrive as plain phrases and are never passed to the index as
written. FTS5's match argument is a query language (operators, column
filters, prefix stars, and a syntax error on stray punctuation), and the
phrases originate in a model's reading of a visitor's message.
``match_expression`` quotes each phrase and joins them with OR, so a phrase
can only ever mean "these words, in this order". There is no stemming and no
prefix matching: ``rogue*`` nominates games whose reviews discuss a rogue
character class, so spelling variants are listed by the caller.

The index itself is the ``review_search`` table and its insert trigger
(schema step 10). This is the seam a second retrieval method would sit
behind: callers hold these two methods and plain data, and know nothing of
how matching is done.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

# The reviews a game's newest report counted, joined onto the index rows a
# MATCH selected. The newest report is chosen as ``ReportLog.latest_report``
# chooses it, with the run id breaking a tie so the choice is deterministic.
_COUNTED = """
    FROM review_search
    JOIN reports r ON r.run_id = (
        SELECT n.run_id FROM reports n WHERE n.app_id = review_search.app_id
        ORDER BY n.created_at DESC, n.run_id LIMIT 1
    )
    JOIN sample_members m
        ON m.run_id = r.run_id AND m.review_id = review_search.review_id
    JOIN classifications c
        ON c.review_id = review_search.review_id
        AND c.model_version = r.model_version
        AND c.prompt_version = r.prompt_version
        AND c.ontology_version = r.ontology_version
    WHERE review_search MATCH ?
"""


def match_expression(phrases: Sequence[str]) -> str:
    """The FTS5 match argument for "any of these phrases", each taken literally.

    Each phrase becomes one quoted FTS5 string, so nothing in it can act as
    an operator; the tokenizer then splits it into words and matches them in
    order ("co-op" is the words ``co op``). Raises ``ValueError`` on an empty
    list or a phrase with no letter or digit in it: such a phrase has no
    words to match, and searching for it is a caller bug, not an empty
    result.

    >>> match_expression(["roguelike", "rogue like"])
    '"roguelike" OR "rogue like"'
    >>> match_expression(['say "hi" OR text:x*'])
    '"say ""hi"" OR text:x*"'
    """
    if not phrases:
        raise ValueError("a search needs at least one phrase")
    quoted: list[str] = []
    for phrase in phrases:
        if not any(character.isalnum() for character in phrase):
            raise ValueError(f"search phrase {phrase!r} holds no letter or digit to match")
        quoted.append('"' + phrase.strip().replace('"', '""') + '"')
    return " OR ".join(quoted)


class ReviewSearch:
    """Table-backed keyword search, constructed by ``Store`` with its connection."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def game_hit_counts(self, phrases: Sequence[str]) -> dict[int, int]:
        """Per game, how many of its counted reviews match any of ``phrases``.

        Games with no matching review are absent from the map. A count is
        comparable to the game's report sample size, since both are taken
        over the same reviews; a review matching several phrases counts once.
        """
        rows = self._conn.execute(
            f"SELECT review_search.app_id, COUNT(*) {_COUNTED} GROUP BY review_search.app_id",
            (match_expression(phrases),),
        ).fetchall()
        return {int(app_id): int(hits) for app_id, hits in rows}

    def search_game(self, app_id: int, phrases: Sequence[str], *, limit: int) -> tuple[str, ...]:
        """The ids of ``app_id``'s counted reviews matching ``phrases``, best match first.

        Ranked by the index's own relevance score, the review id breaking
        ties so the order is deterministic. At most ``limit`` ids; an empty
        tuple when nothing matches or the game has no report.
        """
        if limit < 1:
            raise ValueError(f"limit is {limit} — a search returns at least one review")
        rows = self._conn.execute(
            f"SELECT review_search.review_id {_COUNTED} AND review_search.app_id = ?"
            " ORDER BY review_search.rank, review_search.review_id LIMIT ?",
            (match_expression(phrases), app_id, limit),
        ).fetchall()
        return tuple(str(review_id) for (review_id,) in rows)
