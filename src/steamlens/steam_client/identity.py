"""The identity guard — is the game Steam returned the one we asked about?

An app id is caller-supplied configuration, and a wrong or stale id resolves
to *some* game — silently polluting every window fetched under it. The guard
compares the store's name against the caller's expectation and concludes a
verdict the ``GameRef`` records (never throws — a mismatch is an honest answer
about what Steam returned). The comparison is deliberately forgiving about
decoration and deliberately strict about identity: trademark glyphs, accents,
punctuation, and case all wash out in normalization; what remains must match
nearly whole, or extend the expected name the way an edition suffix does.
"""

from __future__ import annotations

import unicodedata
from difflib import SequenceMatcher

from steamlens.contracts import IdentityVerdict

# Stripped before NFKD, not left to the punctuation collapse: NFKD *decomposes*
# ™ to "tm" and ℠ to "sm", which would weld a phantom token onto the name.
_TRADEMARK_GLYPHS = frozenset("™®©℠")
_MATCH_THRESHOLD = 0.85


def normalize_name(name: str) -> str:
    """``name`` reduced to its comparable core — the guard's common ground.

    Trademark glyphs go first (see the module constant for why order matters),
    then casefold, NFKD decomposition with combining marks dropped (so accents
    compare as their base letters), and every non-alphanumeric run collapses to
    a single space.

    >>> normalize_name("Half-Life 2: Episode Two™")
    'half life 2 episode two'
    >>> normalize_name("Pokémon")
    'pokemon'
    """
    without_marks = "".join(ch for ch in name if ch not in _TRADEMARK_GLYPHS)
    decomposed = unicodedata.normalize("NFKD", without_marks.casefold())
    base = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    collapsed = "".join(ch if ch.isalnum() else " " for ch in base)
    return " ".join(collapsed.split())


def identity_verdict(expected: str, actual: str | None) -> IdentityVerdict:
    """The guard's conclusion about a resolved name — recorded, never thrown.

    ``actual`` is what the store returned (``None`` — no data at all — is its
    own verdict, distinct from a mismatch: there was no name to compare). The
    normalized names must reach a ``SequenceMatcher`` ratio of 0.85, or fall to
    the edition-prefix rule: the actual name's tokens start with all of the
    expected name's tokens — accepted only when the expectation carries at
    least two tokens, so a one-word name like "Rust" cannot prefix-match an
    unrelated game.

    >>> identity_verdict("Team Fortress 2", "Team Fortress 2") is IdentityVerdict.OK
    True
    >>> identity_verdict("Rust", None) is IdentityVerdict.NO_DATA
    True
    """
    if actual is None:
        return IdentityVerdict.NO_DATA
    expected_norm = normalize_name(expected)
    actual_norm = normalize_name(actual)
    if SequenceMatcher(None, expected_norm, actual_norm).ratio() >= _MATCH_THRESHOLD:
        return IdentityVerdict.OK
    expected_tokens = expected_norm.split()
    if len(expected_tokens) >= 2 and actual_norm.split()[: len(expected_tokens)] == expected_tokens:
        return IdentityVerdict.OK
    return IdentityVerdict.MISMATCH
