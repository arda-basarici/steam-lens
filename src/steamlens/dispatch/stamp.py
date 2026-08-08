"""Run provenance stamps — identity a run mints once and carries everywhere.

The three stamps a manifest reproduces a run from: which code ran
(``code_version``), which invocation this was (``mint_run_id``), and which
resolved config it ran under (``config_hash``). What counts as
decision-relevant config is each driver's own knowledge; this module owns
only the stamp mechanics.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import uuid
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path


def code_version() -> str:
    """The code identity stamp: the baked build stamp when set, else git.

    Provenance is a design pillar — a run that cannot state what code produced
    it refuses to start, so with neither source available this raises rather
    than stamping ``unknown``. ``STEAMLENS_CODE_VERSION`` carries identity
    where no repo exists at runtime: an image's contents freeze at build time,
    so the Dockerfile bakes the sha in then (and refuses to build without
    one). Anywhere with a working tree — dev, CI — asks git, ``+dirty`` when
    the tree has changes.
    """
    baked = os.environ.get("STEAMLENS_CODE_VERSION")
    if baked:
        return baked
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


def mint_run_id(prefix: str, started: datetime) -> str:
    """A run id that sorts and greps: ``<prefix>-<UTC second stamp>-<8 hex>``.

    The timestamp makes run directories chronologically listable; the uuid
    tail keeps two runs minted in the same second distinct.
    """
    return f"{prefix}-{started:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"


def config_hash(resolved: Mapping[str, object]) -> str:
    """The sha256 of ``resolved`` in canonical JSON — checkable, never trusted.

    The caller owns which fields are decision-relevant; this owns only the
    canonical form (sorted keys, no whitespace) so equal configs hash equal
    regardless of dict construction order.
    """
    canonical = json.dumps(resolved, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
