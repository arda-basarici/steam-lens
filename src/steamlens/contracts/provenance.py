"""The two-layer provenance stamp — a run record orthogonal to a content-cache key.

Reproducibility needs two questions answered separately, so two records answer
them. ``Provenance`` says *which run* produced an artifact (regenerate it, trace
it, blame it). ``ClassifierVersions`` says *what a piece of content was computed
under* — model, prompt, ontology — and is the cache key: two runs sharing a
``ClassifierVersions`` may reuse each other's labels, because the same content
under the same versions is the same answer. Keeping them orthogonal is what lets
a fresh run (new ``run_id``) still hit the cache (same versions).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Provenance:
    """Which run minted an artifact — the universal run stamp on every output.

    ``run_id`` names the execution; ``code_version`` is the source revision it
    ran (a git sha); ``created_at`` is when it started (timezone-aware);
    ``config_hash`` fingerprints the resolved configuration, so two runs that
    claim the same setup can be checked rather than trusted. This layer is pure
    lineage — it says nothing about *what* was computed, only *who* computed it;
    the content-cache key is the separate ``ClassifierVersions``.
    """

    run_id: str
    code_version: str
    created_at: datetime
    config_hash: str


@dataclass(frozen=True, slots=True)
class ClassifierVersions:
    """The content-cache key — the versions a label was computed under.

    Model, prompt, and ontology versions together determine a classification's
    answer, so a label keyed by these can be reused across runs without re-paying
    the model: bought labels are never re-bought while the versions hold. Bump
    any one and the key changes, correctly invalidating stale labels. The
    ontology is pinned by its ``version`` label here (matching the model and
    prompt); the richer stamp that also carries a content hash is
    ``OntologyVersion``, used where label drift under a stable version name must
    be detectable.
    """

    model_version: str
    prompt_version: str
    ontology_version: str
