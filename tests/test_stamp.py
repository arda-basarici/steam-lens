"""The code-identity stamp's two sources, and the refusal between them.

``code_version`` answers from the baked build stamp when one exists (how a
container states its identity — no repo survives into an image), falls back
to asking git, and refuses to answer at all rather than stamp ``unknown``:
the containers step's job-death bug (2026-08-08) was exactly this refusal
firing at the first minted ``Provenance`` inside an unstamped image.
"""

from __future__ import annotations

import subprocess

import pytest

from steamlens.dispatch import stamp
from steamlens.dispatch.stamp import code_version


def test_baked_stamp_wins_without_touching_git(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_git(*args: object, **kwargs: object) -> None:
        raise AssertionError("a baked stamp must answer without shelling out")

    monkeypatch.setenv("STEAMLENS_CODE_VERSION", "abc1234+dirty")
    monkeypatch.setattr(stamp.subprocess, "run", no_git)
    assert code_version() == "abc1234+dirty"


def test_blank_stamp_is_absent_and_git_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    # An empty env var (ARG defaulted, var exported blank) must not become
    # the stamped identity — blank falls through to the repo.
    monkeypatch.setenv("STEAMLENS_CODE_VERSION", "")
    version = code_version()
    sha = version.removesuffix("+dirty")
    assert sha and all(c in "0123456789abcdef" for c in sha)


def test_no_stamp_and_no_git_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_git(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("git")

    monkeypatch.delenv("STEAMLENS_CODE_VERSION", raising=False)
    monkeypatch.setattr(stamp.subprocess, "run", no_git)
    with pytest.raises(FileNotFoundError):
        code_version()


def test_repo_git_path_still_stamps() -> None:
    # The dev/CI path end to end: this test suite always runs inside the
    # repo, so the git fallback must produce a real stamp here.
    assert subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True).returncode == 0
    assert code_version()
