"""Loading and validating the ontology TOML — refuse a broken codebook loudly.

The vocabulary artifact is hand-edited during the free-edit window (until
gold-set pilot labeling starts), so this loader is the safety net that makes
those edits cheap: every load re-checks the invariants a quiet typo would
break. The checks encode bug classes the codebook's authoring passes actually
hit — an alias shadowing another aspect's label would have silently corrupted
two statistics at once (the ``voice_acting`` "performance" bug), and a
"do not label when → use `X`" route pointing at a demoted label would send
mentions nowhere. Violations raise ``OntologyValidationError`` listing every
problem at once, at load time — never a quiet mislabel at classify time.

The prose convention the reference check relies on: a backticked token in any
codebook prose field is a pinned-label reference, nothing else.
"""

from __future__ import annotations

import hashlib
import re
import tomllib
from collections.abc import Mapping
from importlib.resources import files
from pathlib import Path
from typing import cast

from steamlens.contracts import AspectDef, AspectOntology, OntologyVersion

_LABEL_RE = re.compile(r"[a-z][a-z0-9_]*")
_BACKTICK_REF_RE = re.compile(r"`([^`]+)`")
_PROSE_FIELDS = ("definition", "label_when", "do_not_label_when")


class OntologyValidationError(ValueError):
    """The artifact failed validation; the message lists every violation found."""


def load_ontology(path: Path | None = None) -> AspectOntology:
    """Load and validate an ontology artifact into the ``AspectOntology`` contract.

    ``path`` selects an artifact file for tests and future versions; the
    default is the packaged current vocabulary. Raises
    ``OntologyValidationError`` (with all violations, not just the first) if
    the artifact is structurally malformed or breaks a codebook invariant:
    duplicate or non-snake_case labels, an alias claimed by two aspects or
    shadowing another aspect's label, an undeclared category, or backticked
    prose referencing a label that is not pinned.

    >>> ontology = load_ontology()
    >>> any(aspect.label == "gameplay" for aspect in ontology.aspects)
    True
    """
    doc = tomllib.loads(_artifact_bytes(path).decode("utf-8"))

    problems: list[str] = []
    version = _str_field(doc, "version", "top level", problems)
    categories = _str_tuple_field(doc, "categories", "top level", problems)
    global_rules = _str_tuple_field(doc, "global_rules", "top level", problems)
    aspects = _parse_aspects(doc, problems)
    if problems:  # structural failures make semantic checks meaningless
        raise OntologyValidationError(_render(problems))

    problems += _semantic_problems(aspects, categories, global_rules)
    if problems:
        raise OntologyValidationError(_render(problems))
    return AspectOntology(version=version, aspects=aspects, global_rules=global_rules)


def load_ontology_version(path: Path | None = None) -> OntologyVersion:
    """The artifact's cheap stamp: its version label plus a hash of its raw bytes.

    The hash is computed over the file exactly as stored, so any edit — even
    one that leaves the version label untouched — produces a different stamp.
    This is the value to persist when a stale-content cache hit must be
    detectable (see ``OntologyVersion``).
    """
    raw = _artifact_bytes(path)
    version = _str_field(tomllib.loads(raw.decode("utf-8")), "version", "top level", [])
    return OntologyVersion(version=version, content_hash=hashlib.sha256(raw).hexdigest())


def _artifact_bytes(path: Path | None) -> bytes:
    if path is not None:
        return path.read_bytes()
    return (files("steamlens.ontology") / "v1.toml").read_bytes()


def _render(problems: list[str]) -> str:
    return "ontology artifact invalid:\n" + "\n".join(f"- {p}" for p in problems)


def _str_field(table: Mapping[str, object], key: str, where: str, problems: list[str]) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        problems.append(f"{where}: '{key}' must be a non-empty string")
        return ""
    return value


def _str_tuple_field(
    table: Mapping[str, object], key: str, where: str, problems: list[str]
) -> tuple[str, ...]:
    value = table.get(key)
    if not isinstance(value, list):
        problems.append(f"{where}: '{key}' must be a list of strings")
        return ()
    items = cast(list[object], value)
    if not items or not all(isinstance(item, str) and item.strip() for item in items):
        problems.append(f"{where}: '{key}' must be a non-empty list of non-empty strings")
        return ()
    return tuple(cast(list[str], items))


def _parse_aspects(doc: Mapping[str, object], problems: list[str]) -> tuple[AspectDef, ...]:
    value = doc.get("aspects")
    if not isinstance(value, list) or not value:
        problems.append("top level: 'aspects' must be a non-empty array of tables")
        return ()
    parsed: list[AspectDef] = []
    for index, item in enumerate(cast(list[object], value)):
        if not isinstance(item, dict):
            problems.append(f"aspects[{index}]: must be a table")
            continue
        table = cast(Mapping[str, object], item)
        where = f"aspect '{table.get('label', f'#{index}')}'"
        parsed.append(
            AspectDef(
                label=_str_field(table, "label", where, problems),
                definition=_str_field(table, "definition", where, problems),
                aliases=_str_tuple_field(table, "aliases", where, problems),
                category=_str_field(table, "category", where, problems),
                label_when=_str_field(table, "label_when", where, problems),
                do_not_label_when=_str_field(table, "do_not_label_when", where, problems),
                examples=_str_tuple_field(table, "examples", where, problems),
            )
        )
    return tuple(parsed)


def _semantic_problems(
    aspects: tuple[AspectDef, ...],
    categories: tuple[str, ...],
    global_rules: tuple[str, ...],
) -> list[str]:
    problems: list[str] = []
    labels = {aspect.label for aspect in aspects}
    if len(labels) != len(aspects):
        seen: set[str] = set()
        for aspect in aspects:
            if aspect.label in seen:
                problems.append(f"duplicate label '{aspect.label}'")
            seen.add(aspect.label)

    alias_owner: dict[str, str] = {}
    for aspect in aspects:
        if not _LABEL_RE.fullmatch(aspect.label):
            problems.append(f"label '{aspect.label}' is not snake_case")
        if aspect.category not in categories:
            problems.append(f"aspect '{aspect.label}': undeclared category '{aspect.category}'")
        for alias in aspect.aliases:
            key = alias.casefold()
            owner = alias_owner.setdefault(key, aspect.label)
            if owner != aspect.label:
                problems.append(f"alias '{alias}' claimed by both '{owner}' and '{aspect.label}'")
            if key in labels and key != aspect.label:
                problems.append(
                    f"aspect '{aspect.label}': alias '{alias}' shadows the label '{key}'"
                )

    for aspect in aspects:
        prose = [getattr(aspect, field) for field in _PROSE_FIELDS]
        texts = prose + list(aspect.examples)
        problems += _reference_problems(f"aspect '{aspect.label}'", texts, labels)
    problems += _reference_problems("global rules", list(global_rules), labels)
    return problems


def _reference_problems(where: str, texts: list[str], labels: set[str]) -> list[str]:
    """Every backticked token in codebook prose must resolve to a pinned label."""
    return [
        f"{where}: reference `{token}` does not resolve to a pinned label"
        for text in texts
        for token in _BACKTICK_REF_RE.findall(text)
        if token not in labels
    ]
