"""The pinned aspect vocabulary — the definitions that anchor classification and eval.

The ontology is the fixed core of the hybrid design: a ratified set of aspects,
each with a definition and example synonyms, that both steers the classify
prompt and *is* the labeling instruction the gold set is judged against. Loading
it produces an ``AspectOntology``; pinning it into a cache key is the job of the
lightweight ``OntologyVersion`` stamp. This module is design-time data, not
runtime state — the ratified vocabulary is an artifact, versioned like code.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AspectDef:
    """One pinned aspect — its label, its meaning, and the synonyms that map to it.

    ``label`` is the canonical name a mention normalizes to; ``definition`` is
    the human-authored meaning that goes verbatim into both the classify prompt
    and the gold-set instructions, so the model and the human labeler share one
    contract; ``synonyms`` are the surface forms the normalization step folds
    onto this label. The definition is what makes a pinned aspect measurable —
    without it, "graphics" means whatever each labeler guesses.
    """

    label: str
    definition: str
    synonyms: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AspectOntology:
    """The full loaded core vocabulary — a version tag over its aspect definitions.

    ``version`` is the label this vocabulary is pinned by (the same string that
    lands in a cache key's ``ontology_version``); ``aspects`` are its definitions.
    Kept as plain data with no lookup behavior on purpose — a label→def index
    belongs with the first consumer that needs it (the normalization / classify
    step, ``core``), not speculated here.
    """

    version: str
    aspects: tuple[AspectDef, ...]


@dataclass(frozen=True, slots=True)
class OntologyVersion:
    """The cheap ontology stamp — a version label plus a hash of its content.

    A bare version *name* can't catch content that changed while the name stayed
    put; the ``content_hash`` closes that gap, so a silent edit to the ratified
    vocabulary is detectable rather than a stale cache hit. This is the stamp to
    reach for when that distinction matters; routine cache keys carry only the
    version label via ``ClassifierVersions``.
    """

    version: str
    content_hash: str
