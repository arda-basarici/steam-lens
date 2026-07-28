"""Run provenance stamps — the code-version fingerprint a run refuses to start without."""

from __future__ import annotations

import subprocess
from pathlib import Path


def code_version() -> str:
    """The repo's short commit sha, ``+dirty`` when the tree has changes.

    Provenance is a design pillar — a run that cannot state what code produced
    it refuses to start, so a failed ``git`` call raises rather than stamping
    ``unknown``.
    """
    repo = Path(__file__).resolve().parents[3]
    sha = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=repo, capture_output=True, text=True, check=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo, capture_output=True, text=True, check=True,
    ).stdout.strip()
    return f"{sha}+dirty" if status else sha
