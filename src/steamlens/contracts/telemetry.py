"""The narration/telemetry seam — one emission contract every shell inherits.

Observability is structural here, not retrofitted: a pipeline emits its human
story (stage events) and its machine metrics (token/cost/latency/quota events)
through a single ``Sink.emit``, and each running context binds whatever sink
fits — a console sink offline, an SSE sink under the web server, a structured-log
sink in CI. Defining the protocol at the contract layer is what lets every shell
share one emission surface instead of each inventing its own; the concrete sinks
live in the shells, never here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from steamlens.contracts.enums import StageKind


@dataclass(frozen=True, slots=True)
class StageEvent:
    """The human story — a stage crossing into a new state.

    ``stage`` names the pipeline stage; ``kind`` is where it now stands (started,
    progressing, done, or a non-fatal warn); ``message`` is the line a person
    reads. This is the narration a console prints and the SSE stream forwards.
    """

    stage: str
    kind: StageKind
    message: str


@dataclass(frozen=True, slots=True)
class MetricEvent:
    """The machine number — one measured quantity from a stage.

    ``stage`` names the source; ``name`` is the measure (tokens, cost, latency,
    remaining quota); ``value`` and ``unit`` carry the reading with its units, so
    a downstream dashboard needn't hardcode what "cost" is denominated in. These
    feed the ops-story panel; the stage narration is the separate ``StageEvent``.
    """

    stage: str
    name: str
    value: float
    unit: str


type SinkEvent = StageEvent | MetricEvent
"""Either kind of thing a sink carries — the closed union ``emit`` accepts."""


class Sink(Protocol):
    """The one-method emission contract a running context binds a concrete sink to.

    A sink receives every stage narration and metric a pipeline produces through
    ``emit``; what it does with them — print, stream over SSE, write structured
    logs — is the implementation's business. Kept to a single method so any shell
    can satisfy it trivially and no producer depends on a concrete sink.
    """

    def emit(self, event: SinkEvent) -> None:
        """Carry one event to wherever this sink sends it."""
        ...
