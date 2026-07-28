"""The loud stop — ``RunAbort`` and the model-version drift watch that raises it.

The drivers' shared abort vocabulary lives together because ``DriftWatch``'s
only behavior is raising ``RunAbort``: a run that must stop does so through
one exception type every composition root's abort ladder already catches.
"""

from __future__ import annotations


class RunAbort(Exception):
    """A condition the design says stops the run loudly; always resume-clean."""


class DriftWatch:
    """Holds the first provider-reported model version; a change aborts the run.

    A silent provider roll mid-census would split the pool's "one annotator"
    claim, so the change is a stop-and-rule event — resume is free, and the
    envelopes already written carry their true build in the spend ledger.
    """

    def __init__(self) -> None:
        self._first: str | None = None

    def check(self, reported: str) -> None:
        if self._first is None:
            self._first = reported
            return
        if reported != self._first:
            raise RunAbort(
                f"model version drift: run started under {self._first!r}, provider now "
                f"reports {reported!r} — stopping so the pool keeps one annotator; "
                f"per-call versions are in the spend ledger"
            )
