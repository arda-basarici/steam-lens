"""The report URL canon — where a published analysis lives, said once.

A report's address is ``/reports/{app_id}/{slug}``: the Steam app id is the
authoritative half (the store keys every publication by it, and it is the
only identity Steam guarantees), the slug is decoration minted from the
stored game name so a shared link says what it opens. Steam's own store URLs
take the same stance. The id decides resolution everywhere — a stale or
mangled slug redirects to canonical, never 404s — because names change and
slugs are lossy; a name is never load-bearing in a URL.

Both HTTP surfaces consume this module (the pages' redirect-to-canonical,
the submit receipt's ``report_url``), which is why it lives beside them in
``serve`` rather than inside ``serve.web``: the JSON surface never imports
the rendering package.
"""

from __future__ import annotations

import re
import unicodedata

_SLUG_LENGTH_CAP = 80
"""Ceiling on a slug's length — a defensive cut for pathological names; real
game names sit far under it."""

_LEGAL_MARKS = str.maketrans("", "", "™℠")
"""Dropped before normalization: NFKD decomposes these to the *letters*
"TM"/"SM" (compatibility mapping), which would weld onto the last word.
® and © need no entry — they carry no decomposition and fall to the ascii
filter like any other symbol."""


def game_slug(name: str) -> str:
    """The name's URL-safe form: lowercase ascii words joined by hyphens.

    Lossy by design (the slug is decoration, the id is identity): diacritics
    fold to their base letters, everything outside letters and digits becomes
    a separator, and a name with no ascii letters at all yields "" — the
    caller then addresses the report by bare id.

    >>> game_slug("Team Fortress 2")
    'team-fortress-2'
    >>> game_slug("NieR:Automata™")
    'nier-automata'
    >>> game_slug("Pokémon")
    'pokemon'
    >>> game_slug("東方紅魔郷")
    ''
    """
    ascii_name = (
        unicodedata.normalize("NFKD", name.translate(_LEGAL_MARKS))
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    words = re.findall(r"[a-z0-9]+", ascii_name.lower())
    return "-".join(words)[:_SLUG_LENGTH_CAP].rstrip("-")


def report_path(app_id: int, game_name: str) -> str:
    """The canonical page path for a published report.

    >>> report_path(440, "Team Fortress 2")
    '/reports/440/team-fortress-2'
    >>> report_path(1229480, "東方紅魔郷")
    '/reports/1229480'
    """
    slug = game_slug(game_name)
    return f"/reports/{app_id}/{slug}" if slug else f"/reports/{app_id}"
