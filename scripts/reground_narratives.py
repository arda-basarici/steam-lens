"""Repair gate-trimmed and gate-retried narratives from their runs' own archived drafts.

The one-off migration behind the 2026-08-16 grounding-gate ruling: the gate
had judged a quotation's closing punctuation as content, so the composer's
American-style ``"…too high,"`` failed verbatim against evidence that ends
without the comma. Every archived compose draft replayed under the corrected
gate shows 119 of 122 violations were exactly that; eight published reports
paid a corrective retry for it and seven published with true sentences cut.
The repair is exact, not regenerated: each affected run's *first* draft sits
in the response archive, passes the corrected gate against the run's own
stored aggregates and quote pool, and becomes the narrative the ladder would
have published — outcome ``composed`` — with a fresh certificate. No model
call, no re-sample, provenance stays this run's purchase (the precedent is
``reprice_ledger.py``: exact recovery from archived provider bodies).

Two modes, because the box carries the package only inside the container:

* ``plan`` runs locally over a copy of the box database, needs ``steamlens``,
  and writes a manifest — per run, the narrative row as it must read now
  ("before") and as it will read ("after") — then rehearses the manifest on
  a scratch copy and reads every repaired report back through the store's
  own decoder. The printed report is the review artifact.
* ``apply`` is stdlib-only, runs on the box against the live database, and
  writes inside one transaction; it refuses outright if any row's current
  narrative differs from the manifest's "before" (a job that ran between plan
  and apply, or a wrong copy). Dry-run by default; ``--apply`` writes.

Draft identity is recovered from the ledger where rows carry a run id (token
tuple, exact) and from content otherwise (a foreign draft cannot certify
against a run's own quote pool); draft *order* is recovered from the stored
narrative itself — the stored prose is the second draft (retried) or a
subset of it (trimmed) — so the other draft is the first. Runs whose first
draft still fails the corrected gate (a real paraphrase; three in the
archive) are reported unchanged: their retry was the ladder working.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

# A sentence ends at terminal punctuation, optionally followed by a closing quote.
_SENTENCE_END = re.compile(r"[.!?]+\"?(?=\s|$)")


@dataclass(frozen=True)
class NarrativeRow:
    """The two columns the repair touches, as stored."""

    outcome: str
    payload: str


@dataclass(frozen=True)
class RepairEntry:
    run_id: str
    game_name: str
    before: NarrativeRow
    after: NarrativeRow
    sentences_before: int
    sentences_after: int
    certified_after: int


# --- plan (needs steamlens) -------------------------------------------------------


def _sentences(prose: str) -> int:
    return len(_SENTENCE_END.findall(prose))


def _prose_drafts(conn: sqlite3.Connection) -> list[tuple[tuple[int, int], str]]:
    """Every archived compose completion as ``(token signature, normalized prose)``."""
    from steamlens.core.grounding import normalize_quotes

    drafts = []
    for (raw,) in conn.execute("SELECT raw_response FROM classify_cache"):
        body = json.loads(raw)
        content = body.get("choices", [{}])[0].get("message", {}).get("content")
        if not content or content.lstrip().startswith(("{", "[", "```")):
            continue
        usage = body.get("usage", {})
        drafts.append(
            ((usage.get("prompt_tokens"), usage.get("completion_tokens")),
             normalize_quotes(content.strip()))
        )
    return drafts


def plan(db: Path) -> list[RepairEntry]:
    from steamlens.contracts import ComposedNarrative, EvidenceQuote, NarrativeOutcome
    from steamlens.core.compose import select_facts
    from steamlens.core.grounding import derive_whitelist, ground
    from steamlens.store import Store
    from steamlens.store.reports import narrative_payload

    entries: list[RepairEntry] = []
    # The archive and ledger reads are raw SQL over a second, read-only handle;
    # the store's public surface serves the report, snapshot, and evidence reads.
    raw = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    drafts = _prose_drafts(raw)
    by_signature: dict[tuple[int, int], set[str]] = {}
    for run_id, p, o in raw.execute(
        "SELECT run_id, prompt_tokens, output_tokens FROM spend_ledger"
        " WHERE stage = 'compose' AND run_id IS NOT NULL"
    ):
        by_signature.setdefault((p, o), set()).add(run_id)
    run_ids = [r for (r,) in raw.execute("SELECT run_id FROM reports ORDER BY created_at")]
    raw.close()

    with Store(db) as store:
        runs: dict[str, tuple] = {}  # run_id -> (report, whitelist, pool)
        for run_id in run_ids:
            report = store.reports.get(run_id)
            assert report is not None
            aggregates = store.reports.get_snapshot(run_id)
            quotes = tuple(
                EvidenceQuote(review_id=r, aspect=a, sentiment=s, text=t)
                for r, a, s, t in store.labels.iter_member_evidence(run_id, report.versions)
            )
            facts = select_facts(
                aggregates, quotes, game_name=report.game_name,
                sample_size=report.sample_size, take_all=report.take_all, floor=5,
            )
            pool = tuple(q for brief in facts.aspects for q in brief.quotes)
            # The two claimed totals rode the whitelist at run time and are not
            # stored; the replay showed no numeral ever failed, and a numeral
            # violation below skips the run loudly rather than guessing.
            whitelist = derive_whitelist(aggregates, sample_size=report.sample_size)
            runs[run_id] = (report, whitelist, pool)

        # Draft identity: the ledger's token tuple where the row carries a run
        # id; otherwise the one run (of all of them) whose pool verifies the
        # most of the draft's quotations — a foreign pool verifies none.
        candidates: dict[str, list[str]] = {run_id: [] for run_id in runs}
        pairing: dict[str, str] = {}
        for sig, prose in drafts:
            if by_signature.get(sig) and len(by_signature[sig]) == 1:
                run_id = next(iter(by_signature[sig]))
                candidates[run_id].append(prose)
                pairing[run_id] = "ledger"
                continue
            scored = sorted(
                (
                    sum(1 for span in ground(prose, w, pool).certified if span.kind == "quote"),
                    run_id,
                )
                for run_id, (_, w, pool) in runs.items()
            )
            top_score, top_run = scored[-1]
            if top_score == 0 or (len(scored) > 1 and scored[-2][0] == top_score):
                print(f"UNPAIRED draft ({len(prose)} chars): no run verifies its quotations "
                      f"uniquely (best {top_score})")
                continue
            candidates[top_run].append(prose)
            pairing[top_run] = "content"

        for run_id, (report, whitelist, pool) in runs.items():
            if report.narrative.outcome is NarrativeOutcome.COMPOSED:
                continue
            drafts_here, how = candidates[run_id], pairing.get(run_id, "none")
            stored = report.narrative.prose
            second = [p for p in drafts_here if _stored_matches(stored, p)]
            first = [p for p in drafts_here if not _stored_matches(stored, p)]
            label = (f"{report.game_name} [{run_id}] "
                     f"stored={report.narrative.outcome.value} pairing={how}")
            if len(drafts_here) != 2 or len(second) != 1 or len(first) != 1:
                print(f"SKIP  {label}: {len(drafts_here)} candidate drafts, "
                      f"{len(second)} match the stored prose — cannot order")
                continue
            verdict = ground(first[0], whitelist, pool)
            numeral_fails = [v for v in verdict.violations if v.kind == "numeral"]
            if numeral_fails:
                print(f"SKIP  {label}: first draft has numeral violations "
                      f"{[v.text for v in numeral_fails]} (claimed totals unstored?)")
                continue
            if not verdict.passed:
                print(f"KEEP  {label}: first draft still fails — "
                      f"{[v.text for v in verdict.violations]}; the retry was legitimate")
                continue
            narrative = ComposedNarrative(first[0], verdict.certified, NarrativeOutcome.COMPOSED)
            entries.append(RepairEntry(
                run_id=run_id, game_name=report.game_name,
                before=NarrativeRow(
                    report.narrative.outcome.value, narrative_payload(report.narrative)
                ),
                after=NarrativeRow(NarrativeOutcome.COMPOSED.value, narrative_payload(narrative)),
                sentences_before=_sentences(stored), sentences_after=_sentences(first[0]),
                certified_after=len(verdict.certified),
            ))
            print(f"REPAIR {label}: {_sentences(stored)} → {_sentences(first[0])} sentences, "
                  f"{len(verdict.certified)} certified spans")
    return entries


def _stored_matches(stored: str, draft: str) -> bool:
    """Whether ``stored`` is ``draft`` itself (retried) or a sentence subset of it (trimmed)."""
    if stored == draft:
        return True
    if not stored:
        return False
    return all(sentence.strip() in draft for sentence in _split(stored))


def _split(prose: str) -> list[str]:
    parts, last = [], 0
    for match in _SENTENCE_END.finditer(prose):
        parts.append(prose[last:match.end()])
        last = match.end()
    return parts


def rehearse(db: Path, entries: list[RepairEntry]) -> None:
    """Apply the manifest to a scratch copy and read every repaired report back."""
    from steamlens.store import Store

    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp) / "rehearsal.db"
        shutil.copy(db, scratch)
        conn = sqlite3.connect(scratch)
        try:
            apply_entries(conn, entries, write=True)
        finally:
            conn.close()
        with Store(scratch) as store:
            for entry in entries:
                report = store.reports.get(entry.run_id)
                assert report is not None
                assert report.narrative.outcome.value == entry.after.outcome
                assert len(report.narrative.spans) == entry.certified_after
                print(f"\n--- {entry.game_name} ({report.narrative.outcome.value}, "
                      f"{len(report.narrative.spans)} spans)\n{report.narrative.prose}")
    print(f"\nrehearsal: {len(entries)} report(s) decoded back through the store")


# --- apply (stdlib only) ----------------------------------------------------------


def apply_entries(conn: sqlite3.Connection, entries: list[RepairEntry], *, write: bool) -> None:
    """Check every 'before' against the live rows, then write every 'after' — or nothing."""
    mismatches = []
    for entry in entries:
        row = conn.execute(
            "SELECT narrative_outcome, narrative_json FROM reports WHERE run_id = ?",
            (entry.run_id,),
        ).fetchone()
        if row is None or NarrativeRow(*row) != entry.before:
            mismatches.append(entry.run_id)
    if mismatches:
        raise SystemExit(
            f"refusing: {len(mismatches)} row(s) differ from the manifest's 'before' — "
            f"{mismatches}"
        )
    print(f"{len(entries)} row(s) match their 'before'")
    if not write:
        print("dry run — pass --apply to write")
        return
    with conn:
        for entry in entries:
            conn.execute(
                "UPDATE reports SET narrative_outcome = ?, narrative_json = ? WHERE run_id = ?",
                (entry.after.outcome, entry.after.payload, entry.run_id),
            )
    for entry in entries:
        outcome, = conn.execute(
            "SELECT narrative_outcome FROM reports WHERE run_id = ?", (entry.run_id,)
        ).fetchone()
        print(f"  {entry.game_name}: {entry.before.outcome} → {outcome}")


def _load_manifest(path: Path) -> list[RepairEntry]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        RepairEntry(
            run_id=e["run_id"], game_name=e["game_name"],
            before=NarrativeRow(**e["before"]), after=NarrativeRow(**e["after"]),
            sentences_before=e["sentences_before"], sentences_after=e["sentences_after"],
            certified_after=e["certified_after"],
        )
        for e in data["entries"]
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="mode", required=True)
    p_plan = sub.add_parser(
        "plan", help="build + rehearse the manifest from a DB copy (needs steamlens)"
    )
    p_plan.add_argument("--db", type=Path, required=True)
    p_plan.add_argument("--out", type=Path, required=True)
    p_apply = sub.add_parser("apply", help="apply a manifest to the live DB (stdlib only)")
    p_apply.add_argument("--db", type=Path, required=True)
    p_apply.add_argument("--manifest", type=Path, required=True)
    p_apply.add_argument("--apply", action="store_true", help="write (default: check only)")
    args = parser.parse_args()

    if args.mode == "plan":
        entries = plan(args.db)
        args.out.write_text(
            json.dumps({"source_db": str(args.db), "entries": [asdict(e) for e in entries]},
                       indent=1, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"\nmanifest: {len(entries)} repair(s) → {args.out}")
        rehearse(args.db, entries)
        return
    entries = _load_manifest(args.manifest)
    conn = sqlite3.connect(args.db)
    try:
        apply_entries(conn, entries, write=args.apply)
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
