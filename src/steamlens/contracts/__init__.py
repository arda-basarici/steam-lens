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
from steamlens.contracts.chat import (
    Answer,
    AnswerBasis,
    AskDecision,
    AspectStanding,
    CandidatesDecision,
    CandidatesMaterial,
    ChatMessage,
    CitedExcerpt,
    Excerpt,
    GameMaterial,
    LeftOut,
    NamedSideMaterial,
    NothingFitsDecision,
    NothingFitsMaterial,
    Objection,
    OneGameMaterial,
    Pick,
    PickCandidate,
    PickDecision,
    Reply,
    ReplyStatement,
    SettledObjection,
    SubjectMaterial,
    Understanding,
    WantAcrossLibrary,
    WantMaterial,
)
from steamlens.contracts.classification import AspectMention, ReviewClassification
from steamlens.contracts.compose import ComposedNarrative, EvidenceQuote, GroundedSpan
from steamlens.contracts.enums import (
    AnswerOutcome,
    AspectSlot,
    ChatMessageKind,
    ChatRole,
    CheckRule,
    Feeling,
    FinishReason,
    Firmness,
    IdentityVerdict,
    LlmStage,
    MustStanding,
    NamedGameRole,
    NameMatch,
    NarrativeOutcome,
    ObjectionRung,
    Origin,
    PathOutcome,
    PickOutcome,
    ReadState,
    ReferenceKind,
    RequestIntent,
    RollupUnit,
    SamplingPolicyKind,
    Sentiment,
    SentimentGroup,
    SpanKind,
    StageKind,
    Stance,
    StoreFactSource,
    UnderstandOutcome,
    WantFinding,
    WantStatus,
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
    ReportHead,
    WindowAccount,
)
from steamlens.contracts.request import (
    AspectTarget,
    NamedGame,
    PlayerRequest,
    ReleaseYearsTarget,
    StoreFactDef,
    StoreFactTarget,
    Subject,
    TermTarget,
    Want,
    WantTarget,
)
from steamlens.contracts.reviews import Review
from steamlens.contracts.sampling import FetchPlan, PlannedWindow, SamplingPolicy
from steamlens.contracts.sheet import (
    LibraryGame,
    Sheet,
    SheetCell,
    SheetRow,
    SideFinding,
    WantReading,
    WantTally,
)
from steamlens.contracts.steam import (
    GameRef,
    GameSearchHit,
    HistogramBucket,
    HistogramSnapshot,
    ReviewEvent,
    WindowFetchResult,
)
from steamlens.contracts.storefront import (
    EARLY_ACCESS_GENRE_ID,
    StorefrontLabel,
    StorefrontMetadata,
    StorefrontTag,
    StorefrontTagCapture,
    UncapturedGame,
)
from steamlens.contracts.telemetry import MetricEvent, Sink, SinkEvent, StageEvent

__all__ = [
    # enums
    "Origin",
    "AspectSlot",
    "Sentiment",
    "SentimentGroup",
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
    "RequestIntent",
    "Firmness",
    "Stance",
    "NamedGameRole",
    "Feeling",
    "NameMatch",
    "ChatRole",
    "ChatMessageKind",
    "UnderstandOutcome",
    "PickOutcome",
    "AnswerOutcome",
    "CheckRule",
    "ObjectionRung",
    "ReadState",
    "StoreFactSource",
    "WantStatus",
    "WantFinding",
    "MustStanding",
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
    # storefront facts
    "EARLY_ACCESS_GENRE_ID",
    "StorefrontLabel",
    "StorefrontMetadata",
    "StorefrontTag",
    "StorefrontTagCapture",
    "UncapturedGame",
    # the chat's structured request
    "PlayerRequest",
    "NamedGame",
    "Want",
    "Subject",
    "WantTarget",
    "StoreFactTarget",
    "ReleaseYearsTarget",
    "AspectTarget",
    "TermTarget",
    "StoreFactDef",
    # the chat conversation and what its steps make of it
    "ChatMessage",
    "Understanding",
    "PickCandidate",
    "CandidatesDecision",
    "AskDecision",
    "NothingFitsDecision",
    "PickDecision",
    "Pick",
    "Excerpt",
    "CitedExcerpt",
    "WantMaterial",
    "GameMaterial",
    "NamedSideMaterial",
    "LeftOut",
    "CandidatesMaterial",
    "SubjectMaterial",
    "AspectStanding",
    "OneGameMaterial",
    "WantAcrossLibrary",
    "NothingFitsMaterial",
    "AnswerBasis",
    "ReplyStatement",
    "Reply",
    "Objection",
    "SettledObjection",
    "Answer",
    # the cross-game sheet
    "SheetCell",
    "LibraryGame",
    "SideFinding",
    "WantReading",
    "SheetRow",
    "WantTally",
    "Sheet",
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
    "ReportHead",
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
