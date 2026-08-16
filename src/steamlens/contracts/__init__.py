"""The plain-data spine — every record that crosses a module seam.

What the package admits: frozen, slotted dataclasses; closed ``StrEnum``
vocabularies (whose values are wire format); unions over them; and the
narrow structural protocols a shell binds an implementation to (the sink,
the response archive, the spend ledger). This package
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
from steamlens.contracts.compose import ComposedNarrative, EvidenceQuote, GroundedSpan
from steamlens.contracts.enums import (
    AspectSlot,
    FinishReason,
    IdentityVerdict,
    LlmStage,
    NarrativeOutcome,
    Origin,
    PathOutcome,
    ReferenceKind,
    RollupUnit,
    SamplingPolicyKind,
    Sentiment,
    SpanKind,
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
from steamlens.contracts.ops import (
    DailyAdmissionRow,
    DailyLedgerRow,
    DailyRefusalRow,
    JobRow,
    StageLatencyRow,
    StageModelRow,
    UnjournaledTotals,
)
from steamlens.contracts.provenance import ClassifierVersions, Provenance
from steamlens.contracts.report import (
    EpisodeMarker,
    LanguageCount,
    MarkedWindowCount,
    Report,
    ReportCard,
    WindowAccount,
)
from steamlens.contracts.reviews import Review
from steamlens.contracts.sampling import FetchPlan, PlannedWindow, SamplingPolicy
from steamlens.contracts.steam import (
    GameRef,
    GameSearchHit,
    HistogramBucket,
    HistogramSnapshot,
    ReviewEvent,
    WindowFetchResult,
)
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
    "IdentityVerdict",
    "RollupUnit",
    "PathOutcome",
    "SamplingPolicyKind",
    "SpanKind",
    "NarrativeOutcome",
    # provenance
    "Provenance",
    "ClassifierVersions",
    # ontology
    "AspectDef",
    "AspectOntology",
    "OntologyVersion",
    # reviews
    "Review",
    # steam door
    "GameRef",
    "GameSearchHit",
    "HistogramBucket",
    "HistogramSnapshot",
    "ReviewEvent",
    "WindowFetchResult",
    # sampling
    "SamplingPolicy",
    "PlannedWindow",
    "FetchPlan",
    # classification
    "AspectMention",
    "ReviewClassification",
    # aggregate
    "AspectAggregate",
    "SentimentCounts",
    # compose
    "EvidenceQuote",
    "GroundedSpan",
    "ComposedNarrative",
    # report
    "Report",
    "ReportCard",
    "WindowAccount",
    "LanguageCount",
    "EpisodeMarker",
    "MarkedWindowCount",
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
    # ops aggregates
    "DailyLedgerRow",
    "StageModelRow",
    "DailyAdmissionRow",
    "DailyRefusalRow",
    "JobRow",
    "StageLatencyRow",
    "UnjournaledTotals",
]
