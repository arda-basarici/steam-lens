"""The serving shell — jobs, the one-at-a-time queue, and the runner's dials.

Deployment (M3)'s in-process serving skeleton: a *job* is the minutes-long,
money-spending cold analysis; ``JobQueue`` serializes cold jobs (one Steam
politeness budget, one honest narration timeline), ``Job`` carries a run's
state and its replayable event history, and ``ServeConfig`` holds the dials
the design deliberately left as numbers, not architecture. The HTTP surface
(FastAPI intake, the SSE bridge) lands on top of this package; nothing here
imports it.
"""

from steamlens.serve.config import ServeConfig
from steamlens.serve.jobs import Job, JobQueue, JobState
from steamlens.serve.runner import AnalysisRunner

__all__ = [
    "AnalysisRunner",
    "Job",
    "JobQueue",
    "JobState",
    "ServeConfig",
]
