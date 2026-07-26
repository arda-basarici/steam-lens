"""The CI eval gate — regenerate the pinned runs from the committed fixture, to the digit.

The D3 design's teeth (DESIGN's evals-in-CI entry): CI re-scores stored
envelopes against pinned references, which is deterministic and free, so any
digit that moves means code, scorer, or artifact drift — never model drift,
which can only enter at a label re-buy and is governed there by the buy-time
recertification caveat. A mismatch here therefore *fails*; the deliberate-change
path is to bump the scorer identity and re-export the pins in the same commit
(``python -m steamlens.evals.ci_fixture``).

Env-gated like the other deliberate suites because the re-score (~20s of
bootstrap) roughly doubles the default local loop, not because it is optional:
CI always sets ``STEAMLENS_EVAL_GATE=1`` on its pytest step, and with the gate
armed a missing fixture is a loud failure, never a skip — harness errors fail.

Each test chdirs to the repo root first: the pins' config hashes embed the
scoring artifacts' repo-relative paths exactly as the journaled runs recorded
them, so regeneration must resolve them from the same place.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from steamlens.contracts import EvalRun
from steamlens.evals.agreement import agreement_pool
from steamlens.evals.certify import certify_pool
from steamlens.evals.ci_fixture import (
    AGREEMENT_PIN_FILE,
    CERTIFY_PIN_FILE,
    FIXTURE_DIR,
    GOLD_PATH,
    ONTOLOGY_PATH,
    SAMPLE_PATH,
    eval_run_from_json,
    load_fixture_into,
    run_discrepancies,
)
from steamlens.store import Store

_REPO_ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(
    os.environ.get("STEAMLENS_EVAL_GATE") != "1",
    reason="the eval gate re-scores at 10k bootstrap resamples (~20s); "
    "set STEAMLENS_EVAL_GATE=1 to run — CI always does",
)


def _pin(name: str) -> EvalRun:
    path = _REPO_ROOT / FIXTURE_DIR / name
    return eval_run_from_json(json.loads(path.read_text(encoding="utf-8")))


def _fixture_store() -> Store:
    store = Store(":memory:")
    load_fixture_into(store, _REPO_ROOT / FIXTURE_DIR)
    return store


def _assert_reproduced(pin: EvalRun, regenerated: EvalRun) -> None:
    problems = run_discrepancies(pin, regenerated)
    detail = "\n  ".join(problems)
    assert not problems, (
        f"{pin.scorer} drifted from its pin — either fix the unintended change, or "
        f"bump the scorer identity and re-export the pins in this commit:\n  {detail}"
    )


def test_certification_regenerates_to_the_pinned_digits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(_REPO_ROOT)
    pin = _pin(CERTIFY_PIN_FILE)
    with _fixture_store() as store:
        regenerated = certify_pool(
            store,
            gold_path=GOLD_PATH,
            ontology_path=ONTOLOGY_PATH,
            model_version=pin.versions.model_version,
            prompt_version=pin.versions.prompt_version,
            seed=pin.seed,
            n_resamples=pin.n_resamples,
        )
    _assert_reproduced(pin, regenerated)


def test_agreement_regenerates_to_the_pinned_digits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(_REPO_ROOT)
    pin = _pin(AGREEMENT_PIN_FILE)
    with _fixture_store() as store:
        regenerated = agreement_pool(
            store,
            sample_path=SAMPLE_PATH,
            ontology_path=ONTOLOGY_PATH,
            model_version=pin.versions.model_version,
            prompt_version=pin.versions.prompt_version,
            seed=pin.seed,
            n_resamples=pin.n_resamples,
        )
    _assert_reproduced(pin, regenerated)
