"""The recommender chat's steps, below the shells that run them.

A chat turn is a fixed order of steps: understand the conversation into a
structured request, read the stored library against it, judge, check. This
package is the home of those steps' shells. It sits at rank 3 under the
dependency law, so the serving route and an evaluation run compose the same
code, and neither imports the other to reach it.

Each step's rules are pure and live in ``core``; what a step does here is the
reading and the calling. Built so far: the understand step's call and its
ladder (``chat.understand``), the library read behind the sheet
(``chat.sheet``), the pick step's call and its ladder (``chat.pick``), the
review excerpts a reply is written from (``chat.evidence``) and the fetch
that reads them for a turn (``chat.fetch``).
"""

from steamlens.chat.evidence import EXCERPTS_PER_READ, aspect_excerpts, term_excerpts
from steamlens.chat.fetch import FETCH_STAGE, fetch_about_game, fetch_candidates
from steamlens.chat.pick import PICK_STAGE, pick, pick_route
from steamlens.chat.sheet import load_library, sheet_for, term_hit_counts
from steamlens.chat.understand import UNDERSTAND_STAGE, understand, understand_route

__all__ = [
    # the understand step
    "UNDERSTAND_STAGE",
    "understand",
    "understand_route",
    # the sheet's library read
    "load_library",
    "sheet_for",
    "term_hit_counts",
    # the pick step
    "PICK_STAGE",
    "pick",
    "pick_route",
    # the fetch
    "FETCH_STAGE",
    "fetch_about_game",
    "fetch_candidates",
    # the review excerpts
    "EXCERPTS_PER_READ",
    "aspect_excerpts",
    "term_excerpts",
]
