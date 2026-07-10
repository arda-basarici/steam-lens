"""The ontology artifact and its one door — the versioned vocabulary, loaded safely.

This package holds the pinned aspect vocabulary as a versioned TOML file
(``v1.toml``, the single-source annotation codebook) together with the loader
that turns it into the ``AspectOntology`` contract. It is a shell: it reads a
file, validates it, and hands pure data inward — ``core`` never loads the
ontology itself, it receives the loaded record.

Callers import the public names straight from the package
(``from steamlens.ontology import load_ontology``).
"""

from steamlens.ontology.loader import (
    OntologyValidationError,
    load_ontology,
    load_ontology_version,
)

__all__ = [
    "OntologyValidationError",
    "load_ontology",
    "load_ontology_version",
]
