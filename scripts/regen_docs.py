"""Regenerate the API reference with pdoc. Output is generated, never hand-edited.

Run: ``uv run python scripts/regen_docs.py``. The rendered reference lands in
``docs/api`` (git-ignored) and is rebuilt from the docstrings — the single source
of truth for the caller's contract. Committed as a scaffold; wired into CI/publish
when the first public surface exists.
"""

from __future__ import annotations

import subprocess
import sys

_OUTPUT_DIR = "docs/api"


def main() -> None:
    subprocess.run(
        [sys.executable, "-m", "pdoc", "steamlens", "-o", _OUTPUT_DIR],
        check=True,
    )


if __name__ == "__main__":
    main()
