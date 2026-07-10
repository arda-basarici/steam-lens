"""Import-graph test — enforces DESIGN's dependency law (the two-track wall).

The law: entry shells → pipeline → clients/store/ontology → contracts; ``core``
imports only ``contracts``; nothing imports ``evals``. A module may import only from its
own layer or a lower one. This test parses intra-package imports statically and
fails on any forbidden edge, so a misplaced import is a red build, not a silent
erosion of the boundary. It is deliberately structural and grows as modules land
— with only ``contracts`` present it passes vacuously.
"""

from __future__ import annotations

import ast
from pathlib import Path

PKG = "steamlens"
SRC = Path(__file__).resolve().parent.parent / "src" / PKG

# Rank: a module may import only from its own rank or lower. ``contracts`` is the
# base everything may import; ``evals`` is import-forbidden to all (below).
_LAYER_RANK: dict[str, int] = {
    "contracts": 0,
    "core": 1,
    "steam_client": 2,
    "llm_client": 2,
    "store": 2,
    "ontology": 2,  # the artifact-loading shell; core receives the loaded record
    "pipeline": 3,
    "serve": 4,
    "studies": 4,
    "cli": 4,
    "evals": 4,
}
_IMPORT_FORBIDDEN = frozenset({"evals"})  # nothing may import the eval harness


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
    """Dotted steamlens imports made by the module at ``path``, as part lists."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[list[str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(PKG):
            found.append(node.module.split("."))
        elif isinstance(node, ast.Import):
            found.extend(a.name.split(".") for a in node.names if a.name.startswith(PKG))
    return found


def test_dependency_law() -> None:
    """No module imports a higher layer, and nothing imports ``evals``."""
    violations: list[str] = []
    for path in SRC.rglob("*.py"):
        parts = [PKG, *path.relative_to(SRC).with_suffix("").parts]
        src_sub = _subpackage(parts)
        if src_sub is None:
            continue
        for imported in _intra_package_imports(path):
            dst_sub = _subpackage(imported)
            if dst_sub is None:
                continue
            if dst_sub in _IMPORT_FORBIDDEN:
                violations.append(f"{'.'.join(parts)} imports forbidden '{dst_sub}'")
            elif _LAYER_RANK[src_sub] < _LAYER_RANK[dst_sub]:
                violations.append(f"{'.'.join(parts)} ({src_sub}) imports higher layer '{dst_sub}'")
    assert not violations, "dependency-law violations:\n" + "\n".join(violations)
