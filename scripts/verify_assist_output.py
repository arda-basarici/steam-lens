"""Mechanically verify assist pre-annotation outputs against their inputs.

The dry run's hardest-won lesson (four rounds, four distinct evidence-transfer
defects) is that evidence spans drift silently the moment a human — or a model
— retypes instead of copying. This verifier makes the verbatim rule a machine
check on the assist side, before any of it reaches Arda's workbook:

- every input review id answered exactly once, in input order;
- sentiments drawn from the contract's four values;
- every evidence string a verbatim, continuous substring of its review text;
- flags and notes shape-checked (the only defined flag is ``non_english``).

Violations print loud and fail the run (exit 1) — a defective batch is
re-run, never hand-patched. Also prints per-batch and overall stats
(mentions, zero-mention share, candidate labels seen) so drift from the
expected base rate (~half zero-mention) is visible immediately; candidate
listing doubles as a near-miss check on invented label names.

Usage: ``python scripts/verify_assist_output.py [batch numbers...]``
(no arguments = every batch with a raw output present).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from steamlens.ontology import load_ontology

_REPO = Path(__file__).resolve().parents[1]
_ASSIST_DIR = _REPO / "eval" / "gold" / "assist"

_SENTIMENTS = {"positive", "negative", "mixed", "neutral"}
_FLAGS = {"non_english"}


def load_batch_inputs(n: int) -> list[dict[str, str]]:
    """A batch's input rows (id + text), in file order."""
    path = _ASSIST_DIR / "input" / f"batch_{n:02d}.jsonl"
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def verify_batch(n: int, pinned: frozenset[str]) -> tuple[list[str], dict[str, object]]:
    """Check one raw output against its input; return (violations, stats)."""
    violations: list[str] = []
    inputs = load_batch_inputs(n)
    raw_path = _ASSIST_DIR / "raw" / f"batch_{n:02d}.json"
    try:
        data = json.loads(raw_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return [f"batch {n:02d}: unreadable output ({e})"], {}

    if data.get("batch") != n:
        violations.append(f"batch {n:02d}: batch field says {data.get('batch')!r}")

    annotations = data.get("annotations", [])
    got_ids = [a.get("id") for a in annotations]
    want_ids = [r["id"] for r in inputs]
    if got_ids != want_ids:
        violations.append(
            f"batch {n:02d}: id coverage mismatch — missing {set(want_ids) - set(got_ids) or '{}'}, "
            f"unexpected {set(got_ids) - set(want_ids) or '{}'}, "
            f"order_ok={sorted(got_ids) == sorted(want_ids)}"
        )

    texts = {r["id"]: r["text"] for r in inputs}
    n_mentions = 0
    n_zero = 0
    candidates: list[str] = []
    for a in annotations:
        rid = a.get("id")
        mentions = a.get("mentions", [])
        n_mentions += len(mentions)
        n_zero += not mentions
        for m in mentions:
            where = f"batch {n:02d} review {rid} [{m.get('aspect')!r}]"
            if m.get("sentiment") not in _SENTIMENTS:
                violations.append(f"{where}: bad sentiment {m.get('sentiment')!r}")
            evidence = m.get("evidence")
            if evidence is not None and evidence not in texts.get(rid, ""):
                violations.append(f"{where}: evidence not a verbatim substring: {evidence!r}")
            aspect = m.get("aspect")
            if not isinstance(aspect, str) or not aspect.strip():
                violations.append(f"{where}: bad aspect")
            elif aspect not in pinned:
                candidates.append(aspect)
        for flag in a.get("flags") or []:
            if flag not in _FLAGS:
                violations.append(f"batch {n:02d} review {rid}: unknown flag {flag!r}")
        note = a.get("note")
        if note is not None and not isinstance(note, str):
            violations.append(f"batch {n:02d} review {rid}: non-string note")

    stats = {
        "reviews": len(inputs),
        "mentions": n_mentions,
        "zero": n_zero,
        "candidates": candidates,
        "flags": sum(len(a.get("flags") or []) for a in annotations),
        "notes": sum(1 for a in annotations if a.get("note")),
    }
    return violations, stats


def main() -> None:
    pinned = frozenset(a.label for a in load_ontology().aspects)
    if len(sys.argv) > 1:
        batch_numbers = [int(x) for x in sys.argv[1:]]
    else:
        batch_numbers = sorted(
            int(p.stem.split("_")[1]) for p in (_ASSIST_DIR / "raw").glob("batch_*.json")
        )
    if not batch_numbers:
        raise SystemExit("no raw outputs to verify")

    all_violations: list[str] = []
    totals = {"reviews": 0, "mentions": 0, "zero": 0, "flags": 0, "notes": 0}
    all_candidates: list[str] = []
    print(f"{'batch':>5} {'reviews':>8} {'mentions':>9} {'zero':>5} {'flags':>6} {'notes':>6}")
    for n in batch_numbers:
        violations, stats = verify_batch(n, pinned)
        all_violations.extend(violations)
        if stats:
            print(
                f"{n:>5} {stats['reviews']:>8} {stats['mentions']:>9} "
                f"{stats['zero']:>5} {stats['flags']:>6} {stats['notes']:>6}"
            )
            for key in totals:
                totals[key] += stats[key]  # type: ignore[operator]
            all_candidates.extend(stats["candidates"])  # type: ignore[arg-type]

    zero_share = totals["zero"] / totals["reviews"] if totals["reviews"] else 0.0
    print(
        f"\ntotal: {totals['reviews']} reviews, {totals['mentions']} mentions, "
        f"{totals['zero']} zero-mention ({zero_share:.0%}), "
        f"{totals['flags']} flags, {totals['notes']} notes"
    )
    if all_candidates:
        print(f"candidate labels ({len(all_candidates)}): {sorted(set(all_candidates))}")

    if all_violations:
        print(f"\n{len(all_violations)} VIOLATION(S):")
        for v in all_violations:
            print(f"  !! {v}")
        raise SystemExit(1)
    print("\nall checks passed")


if __name__ == "__main__":
    main()
