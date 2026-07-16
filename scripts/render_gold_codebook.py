"""Splice the rendered codebook into the gold labeling instructions.

The gold instructions (``eval/gold/INSTRUCTIONS.md``) must show the human
annotator the exact codebook text the classify prompt shows the model — the
design call recorded in ``core.classify``: an agreement number is only clean
when both annotators worked from one contract. This script regenerates the
section between the ``CODEBOOK_RENDER`` markers from the loaded ontology using
the same public renderers the prompt uses; the section is generated, never
hand-edited. Run after any ontology version bump:
``uv run python scripts/render_gold_codebook.py``.
"""

from __future__ import annotations

import re
from pathlib import Path

from steamlens.core.classify import render_codebook, render_global_rules
from steamlens.ontology import load_ontology, load_ontology_version

_INSTRUCTIONS = Path("eval/gold/INSTRUCTIONS.md")
_START = "<!-- CODEBOOK_RENDER_START -->"
_END = "<!-- CODEBOOK_RENDER_END -->"


def main() -> None:
    ontology = load_ontology()
    pin = load_ontology_version()
    section = "\n\n".join(
        (
            f"*Ontology `{pin.version}`, content hash `{pin.content_hash}`.*",
            "Global rules:\n\n" + render_global_rules(ontology.global_rules),
            render_codebook(ontology),
        )
    )
    text = _INSTRUCTIONS.read_text(encoding="utf-8")
    if _START not in text or _END not in text:
        raise SystemExit(f"{_INSTRUCTIONS}: CODEBOOK_RENDER markers not found")
    spliced = re.sub(
        re.escape(_START) + r".*?" + re.escape(_END),
        f"{_START}\n{section}\n{_END}",
        text,
        count=1,
        flags=re.DOTALL,
    )
    _INSTRUCTIONS.write_text(spliced, encoding="utf-8")
    print(f"spliced {pin.version} codebook ({len(ontology.aspects)} aspects) into {_INSTRUCTIONS}")


if __name__ == "__main__":
    main()
