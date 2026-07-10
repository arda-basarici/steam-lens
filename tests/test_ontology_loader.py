"""Loader tests — the packaged artifact loads, and every guarded bug class is caught.

The happy path pins only stable facts (the artifact validates, ``gameplay``
exists as the fallback aspect) rather than the live entry count, which Arda's
pruning pass will change. The failure-mode tests each recreate one bug class
the validation exists for, on a minimal two-aspect artifact.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from steamlens.ontology import OntologyValidationError, load_ontology, load_ontology_version

_MINIMAL = """
version = "test"
categories = ["play"]
global_rules = ["Bare verdicts get no label."]

[[aspects]]
label = "combat"
category = "play"
definition = "Fighting systems."
aliases = ["fighting"]
label_when = "The review evaluates fighting."
do_not_label_when = "Enemy intelligence — use `ai_behavior`."
examples = ["\\"Combat is deep.\\" → `combat`"]

[[aspects]]
label = "ai_behavior"
category = "play"
definition = "Quality of NPC behavior."
aliases = ["enemy AI"]
label_when = "The review evaluates non-player behavior."
do_not_label_when = "Fighting itself — use `combat`."
examples = ["\\"NPCs walk into walls.\\" → `ai_behavior`"]
"""


def _artifact(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "ontology.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_packaged_artifact_loads_and_validates() -> None:
    """The shipped vocabulary passes its own validation and carries the codebook."""
    ontology = load_ontology()
    assert ontology.version
    assert ontology.global_rules
    gameplay = next(a for a in ontology.aspects if a.label == "gameplay")
    assert gameplay.category and gameplay.label_when and gameplay.examples


def test_version_stamp_matches_and_hashes(tmp_path: Path) -> None:
    """The stamp carries the artifact's version label and changes with any byte."""
    path = _artifact(tmp_path, _MINIMAL)
    stamp = load_ontology_version(path)
    assert stamp.version == load_ontology(path).version == "test"
    touched = _artifact(tmp_path, _MINIMAL + "\n# comment\n")
    assert load_ontology_version(touched).content_hash != stamp.content_hash


def test_minimal_artifact_loads(tmp_path: Path) -> None:
    ontology = load_ontology(_artifact(tmp_path, _MINIMAL))
    assert [a.label for a in ontology.aspects] == ["combat", "ai_behavior"]


def test_dangling_reference_rejected(tmp_path: Path) -> None:
    """A "use `X`" route to a label that is not pinned must fail the load."""
    broken = _MINIMAL.replace("use `ai_behavior`", "use `balance`")
    with pytest.raises(OntologyValidationError, match="`balance` does not resolve"):
        load_ontology(_artifact(tmp_path, broken))


def test_cross_aspect_alias_claim_rejected(tmp_path: Path) -> None:
    broken = _MINIMAL.replace('aliases = ["enemy AI"]', 'aliases = ["fighting"]')
    with pytest.raises(OntologyValidationError, match="'fighting' claimed by both"):
        load_ontology(_artifact(tmp_path, broken))


def test_alias_shadowing_a_label_rejected(tmp_path: Path) -> None:
    """The voice_acting "performance" bug class: an alias equal to another label."""
    broken = _MINIMAL.replace('aliases = ["enemy AI"]', 'aliases = ["combat"]')
    with pytest.raises(OntologyValidationError, match="shadows the label 'combat'"):
        load_ontology(_artifact(tmp_path, broken))


def test_undeclared_category_rejected(tmp_path: Path) -> None:
    broken = _MINIMAL.replace(
        'label = "combat"\ncategory = "play"', 'label = "combat"\ncategory = "combat_stuff"'
    )
    with pytest.raises(OntologyValidationError, match="undeclared category 'combat_stuff'"):
        load_ontology(_artifact(tmp_path, broken))


def test_duplicate_label_rejected(tmp_path: Path) -> None:
    broken = _MINIMAL.replace('label = "ai_behavior"', 'label = "combat"')
    with pytest.raises(OntologyValidationError, match="duplicate label 'combat'"):
        load_ontology(_artifact(tmp_path, broken))


def test_missing_field_rejected_with_location(tmp_path: Path) -> None:
    broken = _MINIMAL.replace('definition = "Fighting systems."\n', "")
    with pytest.raises(OntologyValidationError, match="aspect 'combat': 'definition'"):
        load_ontology(_artifact(tmp_path, broken))
