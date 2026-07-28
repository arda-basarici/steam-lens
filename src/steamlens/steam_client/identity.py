"""The identity guard — is the game Steam returned the one we asked about?

An app id is caller-supplied configuration, and a wrong or stale id resolves
to *some* game — silently polluting every window fetched under it. The guard
compares the store's name against the caller's expectation and concludes a
verdict the ``GameRef`` records (never throws — a mismatch is an honest answer
about what Steam returned). The comparison is deliberately forgiving about
decoration and deliberately strict about identity: trademark glyphs, accents,
punctuation, and case all wash out in normalization; what remains must match
nearly whole, or extend the expected name the way an edition suffix does —
and its numerals must agree either way, because the likeliest wrong id inside
a high-similarity pair is a franchise sibling ("Fallout 3" resolves against
"Fallout 4" at ratio 0.889), the exact pollution this guard exists to catch.
"""

from __future__ import annotations

import unicodedata
from difflib import SequenceMatcher

from steamlens.contracts import IdentityVerdict

# Stripped before NFKD, not left to the punctuation collapse: NFKD *decomposes*
# ™ to "tm" and ℠ to "sm", which would weld a phantom token onto the name.
_TRADEMARK_GLYPHS = frozenset("™®©℠")
_MATCH_THRESHOLD = 0.85

# Roman-numeral folding sticks to the {i, v, x} alphabet: sequels rarely pass
# XX, and admitting l/c/d/m would read ordinary words ("mix", "dim") as
# numerals. Within that alphabet a token is trusted as a numeral outright —
# game titles do not use "iv"/"vii"-shaped words for anything else.
_ROMAN_CHARS = frozenset("ivx")
_ROMAN_VALUES = {"i": 1, "v": 5, "x": 10}


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
    unrelated game. Both accept paths are gated on the names' numeral
    signatures agreeing (arabic digits and short roman numerals, folded so
    "2" equals "ii"): franchise siblings differ almost only in that numeral
    and sail past the ratio ("Civilization V"/"Civilization VI" reaches
    0.966), and a bare series name must not prefix-accept its own sequel.
    The known cost, accepted deliberately: an edition suffix that introduces
    a new number ("... Edition 2015") now reads as a mismatch — numerals are
    treated as identity, never decoration.

    >>> identity_verdict("Team Fortress 2", "Team Fortress 2") is IdentityVerdict.OK
    True
    >>> identity_verdict("Fallout 3", "Fallout 4") is IdentityVerdict.MISMATCH
    True
    >>> identity_verdict("Rust", None) is IdentityVerdict.NO_DATA
    True
    """
    if actual is None:
        return IdentityVerdict.NO_DATA
    expected_norm = normalize_name(expected)
    actual_norm = normalize_name(actual)
    if _numeral_signature(expected_norm) != _numeral_signature(actual_norm):
        return IdentityVerdict.MISMATCH
    if SequenceMatcher(None, expected_norm, actual_norm).ratio() >= _MATCH_THRESHOLD:
        return IdentityVerdict.OK
    expected_tokens = expected_norm.split()
    if len(expected_tokens) >= 2 and actual_norm.split()[: len(expected_tokens)] == expected_tokens:
        return IdentityVerdict.OK
    return IdentityVerdict.MISMATCH


def _numeral_signature(normalized: str) -> tuple[int, ...]:
    """The name's discriminating numerals, in order, notation-folded.

    Arabic-digit tokens and {i,v,x}-alphabet roman tokens both fold to their
    integer values, so "Half-Life 2" and "Half-Life II" carry the same
    signature while "Dark Souls II" and "Dark Souls III" do not.
    """
    signature: list[int] = []
    for token in normalized.split():
        if token.isdigit():
            signature.append(int(token))
        elif set(token) <= _ROMAN_CHARS:
            signature.append(_roman_value(token))
    return tuple(signature)


def _roman_value(token: str) -> int:
    """Standard subtractive reading over the {i, v, x} alphabet."""
    total = 0
    highest_seen = 0
    for char in reversed(token):
        value = _ROMAN_VALUES[char]
        total = total - value if value < highest_seen else total + value
        highest_seen = max(highest_seen, value)
    return total
