"""The plain-data spine — every record that crosses a module seam.

Frozen, slotted dataclasses (and the sink ``Protocol``) only. This package
imports nothing outside itself, so it sits at the base of the dependency law:
everything may import ``contracts``, ``contracts`` imports no other layer. Raw
external data is validated into these records at the shells, never here — once
built, a record is trusted by construction. See DESIGN's contract-modeling
decision for the reasoning.

Callers import the public names straight from the package
(``from steamlens.contracts import Review``); the module split below is an
internal navigation aid, not part of the contract.
"""

from steamlens.contracts.aggregate import AspectAggregate, SentimentCounts
from steamlens.contracts.classification import AspectMention, ReviewClassification
from steamlens.contracts.enums import (
    AspectSlot,
    FinishReason,
    LlmStage,
    Origin,
    ReferenceKind,
    Sentiment,
    StageKind,
)
from steamlens.contracts.evaluation import EvalMetric, EvalRun
from steamlens.contracts.llm import (
    LlmRequest,
    LlmResponse,
    ResponseArchive,
    SpendLedger,
    SpendRecord,
    TokenUsage,
)
from steamlens.contracts.ontology import AspectDef, AspectOntology, OntologyVersion
from steamlens.contracts.provenance import ClassifierVersions, Provenance
from steamlens.contracts.reviews import Review
from steamlens.contracts.telemetry import MetricEvent, Sink, SinkEvent, StageEvent

__all__ = [
    # enums
    "Origin",
    "AspectSlot",
    "Sentiment",
    "StageKind",
    "LlmStage",
    "FinishReason",
    "ReferenceKind",
    # provenance
    "Provenance",
    "ClassifierVersions",
    # ontology
    "AspectDef",
    "AspectOntology",
    "OntologyVersion",
    # reviews
    "Review",
    # classification
    "AspectMention",
    "ReviewClassification",
    # aggregate
    "AspectAggregate",
    "SentimentCounts",
    # evaluation
    "EvalRun",
    "EvalMetric",
    # telemetry
    "Sink",
    "StageEvent",
    "MetricEvent",
    "SinkEvent",
    # llm seam
    "LlmRequest",
    "LlmResponse",
    "TokenUsage",
    "SpendRecord",
    "ResponseArchive",
    "SpendLedger",
]
