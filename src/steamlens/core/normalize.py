"""Two-slot label normalization — the runtime half of the hybrid-ontology decision.

The classifier emits raw aspect phrases; this module decides each phrase's
slot: fold it onto a pinned canonical label, or keep it as a free-form
candidate in a countable normal form. The matching policy is deliberately
conservative — casefold, trim, collapse whitespace, unify ``_``/``-`` to
spaces, then *exact* lookup only. No stemming, no edit distance: a false merge
silently corrupts two aspects' statistics at once (the same bug class the
ontology loader guards at load time), while a false miss lands in the
candidate stratum where recurrence surfaces it for alias promotion. Fuzz
lives in the human-gated alias list, and the promotion loop is the designed
correction path — so the conservative policy pays only the recoverable price.

Candidates keep the reviewer's own wording (a codebook global rule): they are
casefolded and whitespace-collapsed so recurrences count as one, but hyphens
and phrasing survive — and spaces keep them visually distinct from the
snake_case pinned namespace.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from steamlens.contracts import AspectOntology, AspectSlot

_SEPARATORS_RE = re.compile(r"[_\-]+")
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class NormalizedAspect:
    """One resolved label: the aspect string and which stratum it landed in.

    ``aspect`` is the canonical snake_case label when ``slot`` is pinned, the
    candidate normal form when it is not. This record is core-internal — it
    flows from normalization into envelope assembly, which composes it into
    the cross-seam ``AspectMention``; that record, not this one, is the contract.
    """

    aspect: str
    slot: AspectSlot


def build_surface_index(ontology: AspectOntology) -> Mapping[str, str]:
    """The pinned lookup: every known surface form's match key → its canonical label.

    Indexes each aspect's label (so its spaced form matches too) and all its
    aliases, keyed by the same canonicalization ``normalize_label`` applies to
    raw phrases. Built once per run and passed to every ``normalize_label``
    call — this is the label index the ``AspectOntology`` contract deliberately
    left to its first consumer.

    Raises ``ValueError`` (listing every collision) if two aspects' surface
    forms canonicalize to the same key. The loader's alias checks compare
    surfaces casefolded but verbatim; the match key here is stronger (``_``/
    ``-`` unify to spaces), so an artifact the loader admits can still collide
    under lookup — and a collision would silently route mentions to whichever
    aspect indexed first.
    """
    index: dict[str, str] = {}
    collisions: list[str] = []
    for aspect in ontology.aspects:
        for surface in (aspect.label, *aspect.aliases):
            key = _match_key(surface)
            owner = index.setdefault(key, aspect.label)
            if owner != aspect.label:
                collisions.append(
                    f"surface form '{surface}' of '{aspect.label}'"
                    f" collides with '{owner}' at match key '{key}'"
                )
    if collisions:
        raise ValueError(
            "ontology surface forms collide under match canonicalization:\n"
            + "\n".join(f"- {c}" for c in collisions)
        )
    return index


def normalize_label(raw: str, index: Mapping[str, str]) -> NormalizedAspect:
    """Resolve one raw aspect phrase to its slot: pinned canonical or candidate.

    A phrase whose match key is in ``index`` (built by ``build_surface_index``)
    folds onto its canonical pinned label; anything else becomes a candidate in
    normal form — casefolded and whitespace-collapsed, wording otherwise kept.
    Raises ``ValueError`` on a phrase that is empty once canonicalized: the
    classify parser never passes one, so accepting it would hide a parser bug.

    >>> index = {"voice acting": "voice_acting"}
    >>> normalize_label(" Voice-Acting ", index)
    NormalizedAspect(aspect='voice_acting', slot=<AspectSlot.PINNED: 'pinned'>)
    >>> normalize_label("Ship  Building", index)
    NormalizedAspect(aspect='ship building', slot=<AspectSlot.CANDIDATE: 'candidate'>)
    """
    key = _match_key(raw)
    if not key:
        raise ValueError(f"aspect label is empty after canonicalization: {raw!r}")
    pinned = index.get(key)
    if pinned is not None:
        return NormalizedAspect(aspect=pinned, slot=AspectSlot.PINNED)
    return NormalizedAspect(aspect=_candidate_form(raw), slot=AspectSlot.CANDIDATE)


def _match_key(text: str) -> str:
    """The form all surface variants collapse to for pinned-vocabulary lookup."""
    return _WHITESPACE_RE.sub(" ", _SEPARATORS_RE.sub(" ", text.casefold())).strip()


def _candidate_form(text: str) -> str:
    """The countable normal form of a free-form label — reviewer's wording kept."""
    return _WHITESPACE_RE.sub(" ", text.casefold()).strip()
