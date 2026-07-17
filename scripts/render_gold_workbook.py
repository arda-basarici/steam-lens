"""Render the gold adjudication workbook from the assist raw outputs.

The workbook is Arda's editing surface — the human half of the assist workflow
(eval/gold/INSTRUCTIONS.md section 8). Each batch becomes one markdown sheet
mirroring ``assist/raw/`` 1:1: the review text in a fenced block, the assist's
mentions pre-filled as editable lines, a ``reviewed`` checkbox per review. The
raw files stay immutable; the compile step derives accepted/corrected/deleted/
added by diffing the edited sheets against them, so adjudication needs no
manual bookkeeping beyond flipping checkboxes.

Design points the format carries:

- **Game-stripped, shuffled order** — the sheets inherit the assist batches'
  horizon discipline (round-3 ruling): id + text only, no same-game runs.
- **Explicit zero** — a zero-mention draft renders as the literal line
  ``Zero mentions.`` so an empty state is always deliberate, never an
  accident of deletion; the compiler rejects a reviewed block that has
  neither mentions nor a marker.
- **Copy-paste evidence** — the text block sits directly above the mention
  lines so spans are copied, never retyped (the four-defects lesson). A
  newline inside a span is written as ``\\n`` (rare — 1 of 395 in the assist
  run); the compiler unescapes before the verbatim check.
- **Fence safety** — the text fence grows past any backtick run inside the
  review, so review content can never terminate its own block.

Refuses to overwrite existing sheets: once Arda edits, the workbook is the
single copy of his pass — delete a sheet deliberately to re-render it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_ASSIST_DIR = _REPO / "eval" / "gold" / "assist"
_WORKBOOK_DIR = _REPO / "eval" / "gold" / "workbook"

_RULES = """\
Your adjudication surface — edit THIS file; `assist/raw/` stays immutable.

- Flip `- [ ] reviewed` to `- [x] reviewed` on every review you finish
  (accepting as-is included). Compile refuses to mint gold while any box
  is unchecked.
- Mention line: `- aspect / sentiment / "verbatim evidence"` — evidence is
  COPY-PASTED from the text block above (a newline inside a span is written
  `\\n`), or `(no span)` when no usable span exists.
- Zero mentions: the single line `Zero mentions.` — delete it if you add
  mentions; write it if you delete every mention.
- Skip (INSTRUCTIONS section 8): replace the mention lines with
  `SKIP: non_english`.
- `> assist note:` / `> assist flag:` lines are read-only context; keep or
  delete freely — the compiler ignores them.
"""


def _fence(text: str) -> str:
    """A backtick fence strictly longer than any backtick run in the text."""
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def _escape_evidence(evidence: str) -> str:
    return evidence.replace("\r", "\\r").replace("\n", "\\n")


def render_mention_line(mention: dict[str, str | None]) -> str:
    evidence = mention.get("evidence")
    shown = f'"{_escape_evidence(evidence)}"' if evidence else "(no span)"
    return f"- {mention['aspect']} / {mention['sentiment']} / {shown}"


def render_review_block(index: int, text: str, annotation: dict[str, object]) -> str:
    """One review's editable block: header, checkbox, text, pre-filled lines."""
    fence = _fence(text)
    lines = [
        f"## {index} · review {annotation['id']}",
        "- [ ] reviewed",
        "",
        f"{fence}text",
        text,
        fence,
        "",
    ]
    mentions = annotation.get("mentions") or []
    flags = annotation.get("flags") or []
    if "non_english" in flags:
        lines.append("SKIP: non_english")
    for m in mentions:  # type: ignore[union-attr]
        lines.append(render_mention_line(m))
    if not mentions and "non_english" not in flags:
        lines.append("Zero mentions.")
    if "non_english" in flags:
        lines.append(
            "> assist flag: non_english — keep the SKIP line, or delete it "
            "and keep/write the labels"
        )
    note = annotation.get("note")
    if note:
        lines.append(f"> assist note: {note}")
    lines.append("")
    return "\n".join(lines)


def render_batch(n: int, manifest: dict[str, object]) -> str:
    with (_ASSIST_DIR / "input" / f"batch_{n:02d}.jsonl").open(encoding="utf-8") as f:
        inputs = [json.loads(line) for line in f]
    raw = json.loads((_ASSIST_DIR / "raw" / f"batch_{n:02d}.json").read_text(encoding="utf-8"))
    annotations = {a["id"]: a for a in raw["annotations"]}

    header = (
        f"# Gold workbook — batch {n:02d} of {manifest['batches']}\n\n"
        f"Assist: `{manifest['assist_model']}` · instructions "
        f"`{manifest['instructions_version']}` · ontology `{manifest['ontology_version']}`\n\n"
        f"{_RULES}\n---\n\n"
    )
    blocks = [
        render_review_block(i, row["text"], annotations[row["id"]])
        for i, row in enumerate(inputs, start=1)
    ]
    return header + "\n".join(blocks)


def main() -> None:
    manifest = json.loads((_ASSIST_DIR / "manifest.json").read_text(encoding="utf-8"))
    _WORKBOOK_DIR.mkdir(parents=True, exist_ok=True)
    rendered = 0
    for n in range(1, int(manifest["batches"]) + 1):
        out = _WORKBOOK_DIR / f"batch_{n:02d}.md"
        if out.exists():
            raise SystemExit(
                f"{out} exists — the workbook may hold adjudication work; "
                "delete the sheet deliberately to re-render"
            )
        out.write_text(render_batch(n, manifest), encoding="utf-8", newline="\n")
        rendered += 1
    print(f"rendered {rendered} sheets to {_WORKBOOK_DIR}")


if __name__ == "__main__":
    main()
