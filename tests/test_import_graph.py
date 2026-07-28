"""Import-graph test — enforces DESIGN's dependency law (the two-track wall).

The law: entry shells → pipeline → clients/store/ontology → contracts; ``core``
imports only ``contracts``; the entry shells (``evals``, ``studies``) are
import-forbidden to everything — they compose, nothing composes them. A module
may import only from its own layer or a lower one. This test parses
intra-package imports statically and fails on any forbidden edge, so a
misplaced import is a red build, not a silent erosion of the boundary.

The law refuses to fail open: every package under ``src`` must declare a rank
before it exists to the build (``test_every_package_is_ranked``), and relative
imports — which the edge scan cannot rank — are banned outright
(``test_no_relative_imports``). Both holes were latent when closed
(2026-07-28, the full-base review): erosion arrives exactly as a new package
or a new import style, which is when a guard that skips the unknown is worth
nothing.
"""

from __future__ import annotations

import ast
from pathlib import Path

PKG = "steamlens"
SRC = Path(__file__).resolve().parent.parent / "src" / PKG

# Rank: a module may import only from its own rank or lower. ``contracts`` is the
# base everything may import; the entry shells are import-forbidden (below).
_LAYER_RANK: dict[str, int] = {
    "contracts": 0,
    "core": 1,
    "corpus": 2,  # the frozen-snapshot reader, beside the live door
    "steam_client": 2,
    "llm_client": 2,
    "store": 2,
    "ontology": 2,  # the artifact-loading shell; core receives the loaded record
    "dispatch": 3,  # generic run machinery the entry shells compose
    "pipeline": 3,
    "serve": 4,
    "studies": 4,
    "cli": 4,
    "evals": 4,
}
# Entry shells: nothing may import the eval harness or the study drivers —
# checkable and symmetric, now that no src edge into either exists.
_IMPORT_FORBIDDEN = frozenset({"evals", "studies"})


def _subpackage(module_parts: list[str]) -> str | None:
    """The steamlens subpackage a dotted module belongs to, or None if top-level.

    >>> _subpackage(["steamlens", "core", "classify"])
    'core'
    >>> _subpackage(["steamlens", "__init__"]) is None
    True
    """
    if len(module_parts) < 2:
        return None
    sub = module_parts[1]
    return sub if sub in _LAYER_RANK else None


def _intra_package_imports(path: Path) -> list[list[str]]:
    """Dotted steamlens imports made by the module at ``path``, as part lists.

    Absolute imports only — relative imports are unrankable here and are
    banned wholesale by ``test_no_relative_imports``.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[list[str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(PKG):
            found.append(node.module.split("."))
        elif isinstance(node, ast.Import):
            found.extend(a.name.split(".") for a in node.names if a.name.startswith(PKG))
    return found


def test_every_package_is_ranked() -> None:
    """Declaring a rank is a precondition for adding a package, not a courtesy.

    ``_subpackage`` returns None for anything missing from ``_LAYER_RANK`` and
    the law test skips None — correct for ``steamlens/__init__``, fail-open
    for a real package someone forgot to rank. This closes that hole: a new
    package under ``src`` is red until it takes a place in the law. (The rank
    table may name packages that don't exist yet — declared ahead is fine;
    existing unranked is not.)
    """
    unranked = sorted(
        entry.name
        for entry in SRC.iterdir()
        if entry.is_dir() and (entry / "__init__.py").exists() and entry.name not in _LAYER_RANK
    )
    assert not unranked, (
        f"packages missing from _LAYER_RANK: {unranked} — declare each one's rank "
        f"so the dependency law can see it"
    )


def test_no_relative_imports() -> None:
    """Relative imports are banned in src — the law can only rank what it can name.

    The edge scan resolves imports by their dotted ``steamlens.`` prefix; a
    relative import (``from ..studies import ...``) carries no prefix and
    would cross layers invisibly. The codebase is uniformly absolute-import,
    so the cheap closure is a wholesale ban rather than level resolution.
    """
    violations: list[str] = []
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level > 0:
                dots = "." * node.level
                target = f"{dots}{node.module or ''}"
                violations.append(f"{path.relative_to(SRC)}: from {target} import ...")
    assert not violations, (
        "relative imports in src (invisible to the dependency law):\n" + "\n".join(violations)
    )


def test_dependency_law() -> None:
    """No module imports a higher layer, and nothing imports an entry shell."""
    violations: list[str] = []
    for path in SRC.rglob("*.py"):
        parts = [PKG, *path.relative_to(SRC).with_suffix("").parts]
        src_sub = _subpackage(parts)
        if src_sub is None:
            continue
        for imported in _intra_package_imports(path):
            dst_sub = _subpackage(imported)
            if dst_sub is None or dst_sub == src_sub:
                continue  # same-package imports are inside the boundary, always legal
            if dst_sub in _IMPORT_FORBIDDEN:
                violations.append(f"{'.'.join(parts)} imports forbidden '{dst_sub}'")
            elif _LAYER_RANK[src_sub] < _LAYER_RANK[dst_sub]:
                violations.append(f"{'.'.join(parts)} ({src_sub}) imports higher layer '{dst_sub}'")
    assert not violations, "dependency-law violations:\n" + "\n".join(violations)
