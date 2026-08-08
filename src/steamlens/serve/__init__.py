"""The serving shell — jobs, the one-at-a-time queue, the runner, and the HTTP surface.

Deployment (M3)'s in-process serving skeleton: a *job* is the minutes-long,
money-spending cold analysis; ``JobQueue`` serializes cold jobs (one Steam
politeness budget, one honest narration timeline), ``Job`` carries a run's
state and its replayable event history, and ``ServeConfig`` holds the dials
the design deliberately left as numbers, not architecture. The HTTP surface
sits on top with the dependency arrow pointing strictly inward: ``app`` (the
FastAPI factory and its typed intake contracts) and ``sse`` (the wire encoding
and the replay-then-follow stream) import the jobs layer; jobs, runner, and
config never import them.
"""

from steamlens.serve.app import (
    AnalysisAccepted,
    AnalysisRequest,
    HealthReport,
    ReportReady,
    create_app,
)
from steamlens.serve.config import ServeConfig
from steamlens.serve.gate import SubmitGate
from steamlens.serve.jobs import Job, JobQueue, JobState
from steamlens.serve.runner import AnalysisRunner

__all__ = [
    "AnalysisAccepted",
    "AnalysisRequest",
    "AnalysisRunner",
    "HealthReport",
    "Job",
    "JobQueue",
    "JobState",
    "ReportReady",
    "ServeConfig",
    "SubmitGate",
    "create_app",
]
