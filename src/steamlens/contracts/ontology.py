"""The pinned aspect vocabulary — the definitions that anchor classification and eval.

The ontology is the fixed core of the hybrid design: a ratified set of aspects,
each with a definition and known aliases, that both steers the classify
prompt and *is* the labeling instruction the gold set is judged against. Loading
it produces an ``AspectOntology``; pinning it into a cache key is the job of the
lightweight ``OntologyVersion`` stamp. This module is design-time data, not
runtime state — the ratified vocabulary is an artifact, versioned like code.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AspectDef:
    """One pinned aspect — a full codebook entry, not just a name and a gloss.

    ``label`` is the canonical name a mention normalizes to; ``definition`` is
    the human-authored meaning that goes verbatim into both the classify prompt
    and the gold-set instructions, so the model and the human labeler share one
    contract; ``aliases`` are the surface forms the normalization step folds
    onto this label — surface variants only, never distinct sub-concepts (a
    distinct concept gets its own slot or stays candidate).

    The remaining fields carry the annotation-codebook detail that makes the
    boundary between near-neighbor aspects decidable: ``label_when`` states the
    positive rule, ``do_not_label_when`` states the exclusions and routes
    borderline mentions to their owning label (backticked tokens in the prose
    are label references — the loader validates each resolves to a pinned
    label), ``examples`` are worked review sentences with their verdicts.
    ``category`` groups entries for rendering and navigation only — it is never
    a classification target. The definition is what makes a pinned aspect
    measurable — without it, "graphics" means whatever each labeler guesses.
    """

    label: str
    definition: str
    aliases: tuple[str, ...]
    category: str
    label_when: str
    do_not_label_when: str
    examples: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AspectOntology:
    """The full loaded core vocabulary — a version tag over its aspect definitions.

    ``version`` is the label this vocabulary is pinned by (the same string that
    lands in a cache key's ``ontology_version``); ``aspects`` are its definitions;
    ``global_rules`` are the labeling rules that apply across every entry (bare
    verdicts get no label, multi-label is normal, unlisted aspects become
    candidates, …) — they travel with the vocabulary because the classify prompt
    and the gold-set instructions both need them, and a rule left behind in a
    design doc would silently fork from the artifact.
    Kept as plain data with no lookup behavior on purpose — a label→def index
    belongs with the first consumer that needs it (the normalization / classify
    step, ``core``), not speculated here.
    """

    version: str
    aspects: tuple[AspectDef, ...]
    global_rules: tuple[str, ...]


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
