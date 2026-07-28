"""Generic run machinery for the dispatch drivers — narration, abort, stamps, batches.

The census, cell, and judge drivers each compose the same run mechanics: a
tee'd narration sink, the loud-stop vocabulary (``RunAbort`` plus the
model-version drift watch), the code-version provenance stamp, and the
chunk/pass batch engine. This package is that machinery's one home — rank 3
under the dependency law, so entry shells compose it without reaching into
each other's interiors (the ``evals`` → ``studies/label_corpus`` edge this
relocation removed, 2026-07-28). The machinery modules are study-blind — what
identifies a *run* belongs to the driver that owns it. The one deliberate
exception is ``census_arm`` (imported by module path, not re-exported here):
the production annotator's identity as a citable instrument, so eval shells
name the model under judgment without importing the labeling driver.
"""

from steamlens.dispatch.abort import DriftWatch, RunAbort
from steamlens.dispatch.batches import BatchOutcome, RunTotals, chunk, run_pass
from steamlens.dispatch.narration import TeeSink, narrate
from steamlens.dispatch.stamp import code_version

__all__ = [
    # narration
    "TeeSink",
    "narrate",
    # the loud stop
    "RunAbort",
    "DriftWatch",
    # provenance stamps
    "code_version",
    # the batch engine
    "RunTotals",
    "BatchOutcome",
    "chunk",
    "run_pass",
]
