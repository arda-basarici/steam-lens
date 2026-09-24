"""The loud stop — ``RunAbort`` and the model-version drift watch that raises it.

The drivers' shared abort vocabulary lives together because ``DriftWatch``'s
only behavior is raising ``RunAbort``: a run that must stop does so through
one exception type every composition root's abort ladder already catches.
"""

from __future__ import annotations


class RunAbort(Exception):
    """A condition the design says stops the run loudly; always resume-clean."""


class DriftWatch:
    """The provider-reported model version must hold — across runs when ``expected``
    is given, within the run otherwise — or the run aborts.

    A silent provider roll mid-census would split the pool's "one annotator"
    claim, so the change is a stop-and-rule event — resume is free, and the
    envelopes already written carry their true build in the spend ledger.
    The within-run watch alone missed the swap that matters most: on
    2026-09-10 the provider re-pointed the requested id at a retired model's
    successor, every run after that was internally consistent, and nothing
    flagged it for eight days. ``expected`` is the instrument's declared
    version; the first response naming anything else stops the run before a
    second call is bought.
    """

    def __init__(self, expected: str | None = None) -> None:
        self._first = expected
        self._declared = expected is not None

    def check(self, reported: str) -> None:
        if self._first is None:
            self._first = reported
            return
        if reported == self._first:
            return
        origin = (
            f"the instrument declares {self._first!r}" if self._declared
            else f"run started under {self._first!r}"
        )
        raise RunAbort(
            f"model version drift: {origin}, provider now reports {reported!r} — "
            "stopping so the pool keeps one annotator; per-call versions are in "
            "the spend ledger"
        )
