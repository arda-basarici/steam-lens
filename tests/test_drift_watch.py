"""The drift watch's two anchors: the declared version, and the run's first response.

The declared anchor is the 2026-09-24 addition — a provider re-pointing the
requested id at another model must fail on the first bought call, not stay
invisible because every call in the run agrees with itself.
"""

from __future__ import annotations

import pytest

from steamlens.dispatch import DriftWatch, RunAbort


def test_declared_version_rejects_a_foreign_first_response() -> None:
    """The swap that went unflagged for eight days: the first response names a
    different model than the instrument declares — abort before a second call."""
    watch = DriftWatch(expected="deepseek-flash")
    with pytest.raises(RunAbort, match="instrument declares 'deepseek-flash'"):
        watch.check("deepseek-flash-1021")


def test_declared_version_accepts_matching_responses_then_watches_within_run() -> None:
    watch = DriftWatch(expected="deepseek-flash")
    watch.check("deepseek-flash")
    watch.check("deepseek-flash")
    with pytest.raises(RunAbort, match="provider now reports 'deepseek-flash-1021'"):
        watch.check("deepseek-flash-1021")


def test_undeclared_watch_anchors_on_the_first_response() -> None:
    """The original contract, kept for the judge dispatchers: within-run only."""
    watch = DriftWatch()
    watch.check("judge-a")
    watch.check("judge-a")
    with pytest.raises(RunAbort, match="run started under 'judge-a'"):
        watch.check("judge-b")
