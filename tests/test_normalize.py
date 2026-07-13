"""Normalization tests — the two-slot policy's behavioral claims, plus the artifact.

Unit tests build minimal ``AspectDef`` records directly (pure core: data in →
data out, no loader involved); the closing test round-trips the real packaged
artifact through the index so every shipped label and alias provably resolves
to its own aspect — the consumer-side re-guard of the loader's invariants.
"""

from __future__ import annotations

import pytest

from steamlens.contracts import AspectDef, AspectOntology, AspectSlot
from steamlens.core.normalize import NormalizedAspect, build_surface_index, normalize_label
from steamlens.ontology import load_ontology


def _aspect(label: str, aliases: tuple[str, ...] = ()) -> AspectDef:
    return AspectDef(
        label=label,
        definition=f"{label} definition.",
        aliases=aliases,
        category="play",
        label_when="When evaluated.",
        do_not_label_when="When another label owns it.",
        examples=(),
    )


def _ontology(*aspects: AspectDef) -> AspectOntology:
    return AspectOntology(version="test", aspects=aspects, global_rules=("A rule.",))


def test_label_and_alias_resolve_pinned() -> None:
    """Both a canonical label and any of its aliases fold onto the pinned slot."""
    index = build_surface_index(_ontology(_aspect("combat", ("fighting", "gunplay"))))
    assert normalize_label("combat", index) == NormalizedAspect("combat", AspectSlot.PINNED)
    assert normalize_label("gunplay", index) == NormalizedAspect("combat", AspectSlot.PINNED)


def test_surface_variants_fold_to_one_label() -> None:
    """Case, separators, and padding never split one aspect into two statistics."""
    index = build_surface_index(_ontology(_aspect("voice_acting", ("VA",))))
    variants = ["voice_acting", "Voice Acting", " voice-acting ", "VOICE\tACTING", "va"]
    resolved = {normalize_label(v, index) for v in variants}
    assert resolved == {NormalizedAspect("voice_acting", AspectSlot.PINNED)}


def test_miss_becomes_candidate_in_normal_form() -> None:
    """An unknown phrase lands in the candidate stratum, countable across reviews."""
    index = build_surface_index(_ontology(_aspect("combat")))
    assert normalize_label("  Ship   Building ", index) == NormalizedAspect(
        "ship building", AspectSlot.CANDIDATE
    )


def test_candidate_keeps_reviewer_wording() -> None:
    """Hyphens survive in candidates: normal form counts, it does not rewrite."""
    index = build_surface_index(_ontology(_aspect("combat")))
    assert normalize_label("Co-Op partner", index) == NormalizedAspect(
        "co-op partner", AspectSlot.CANDIDATE
    )


def test_empty_label_rejected() -> None:
    """A phrase that canonicalizes to nothing is a parser bug, not a candidate."""
    index = build_surface_index(_ontology(_aspect("combat")))
    for raw in ("", "   ", "_-_"):
        with pytest.raises(ValueError, match="empty after canonicalization"):
            normalize_label(raw, index)


def test_index_collision_rejected() -> None:
    """A pair the loader admits can still collide under the stronger match key."""
    colliding = _ontology(
        _aspect("voice_acting"),
        _aspect("audio", ("voice acting",)),  # verbatim-distinct, key-identical
    )
    with pytest.raises(ValueError, match="'voice acting' of 'audio' collides"):
        build_surface_index(colliding)


def test_real_artifact_every_surface_resolves_to_its_own_aspect() -> None:
    """The shipped vocabulary round-trips: each label and alias folds onto its aspect."""
    ontology = load_ontology()
    index = build_surface_index(ontology)
    for aspect in ontology.aspects:
        for surface in (aspect.label, *aspect.aliases):
            assert normalize_label(surface, index) == NormalizedAspect(
                aspect.label, AspectSlot.PINNED
            ), f"surface '{surface}' did not resolve to '{aspect.label}'"
