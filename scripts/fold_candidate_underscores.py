"""Fold underscore-spelled candidate labels into their spaced form, in place.

The one-off repair behind the 2026-08-17 normalization ruling: the classifier
sometimes echoes the pinned namespace's snake_case into an emergent theme
(``base_building`` beside ``base building``), and the candidate normal form
kept underscores as "the reviewer's wording", so one theme became two
countable rows that render identically (``base building 6 · base building
6`` on a live report). ``core/normalize.py`` now folds underscores at the
boundary; this script brings the stored labels to the same form, because
stored mentions are reused by any later run of the same reviews (a verdict
bought once counts forever) and the frozen aggregate snapshots are what the
published pages cite.

Two tables, one transaction:

* ``mentions`` rows in the candidate slot with an underscore are renamed to
  the folded label.
* ``aggregate_snapshots`` rows in the candidate slot with an underscore are
  renamed, or, where the run already holds the folded label, merged into it
  (counts summed, the underscore row deleted).

The merge is exact only when the two spellings were labels on disjoint
reviews; the script verifies that from the run's own members and mentions
and refuses otherwise. It also refuses if a rename would leave one
classification carrying the same candidate twice. Stdlib-only so it runs on
the box's system Python against the live database; dry-run by default and
prints the whole plan, ``--apply`` writes it. Take a file snapshot first
(the previous repairs' precedent: ``serve-pre-<name>-<date>.db``).
"""

from __future__ import annotations

import argparse
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

_UNDERSCORES = re.compile(r"_+")
_WHITESPACE = re.compile(r"\s+")


def folded(label: str) -> str:
    """The candidate normal form ``core/normalize.py`` now produces, restated."""
    return _WHITESPACE.sub(" ", _UNDERSCORES.sub(" ", label)).strip()


@dataclass(frozen=True)
class MentionRename:
    mention_id: int
    before: str
    after: str


@dataclass(frozen=True)
class SnapshotChange:
    run_id: str
    game_name: str
    before: str
    after: str
    merged_into: int | None  # the surviving row's id when the run already holds `after`
    counts_before: tuple[int, ...]
    counts_after: tuple[int, ...]


_COUNT_COLUMNS = ("reviews_with_aspect", "positive", "negative", "mixed", "neutral")


def plan_mentions(conn: sqlite3.Connection) -> list[MentionRename]:
    rows = conn.execute(
        "SELECT id, classification_id, aspect FROM mentions"
        " WHERE slot = 'candidate' AND instr(aspect, '_') > 0 ORDER BY id"
    ).fetchall()
    renames = [MentionRename(int(i), str(a), folded(str(a))) for i, _, a in rows]
    # A rename must not leave one classification carrying the same candidate twice.
    for (mention_id, classification_id, aspect) in rows:
        clash = conn.execute(
            "SELECT id FROM mentions WHERE classification_id = ? AND slot = 'candidate'"
            " AND aspect = ? AND id != ?",
            (classification_id, folded(str(aspect)), mention_id),
        ).fetchone()
        if clash is not None:
            raise SystemExit(
                f"refusing: mention {mention_id} ({aspect!r}) would duplicate mention"
                f" {clash[0]} on classification {classification_id}"
            )
    return renames


def _review_set(conn: sqlite3.Connection, run_id: str, aspect: str) -> set[str]:
    """Reviews in ``run_id``'s sample whose stored labels carry ``aspect`` as a candidate."""
    return {
        str(r)
        for (r,) in conn.execute(
            "SELECT DISTINCT c.review_id FROM mentions m"
            " JOIN classifications c ON c.id = m.classification_id"
            " JOIN sample_members s ON s.review_id = c.review_id AND s.run_id = ?"
            " WHERE m.slot = 'candidate' AND m.aspect = ?",
            (run_id, aspect),
        )
    }


def plan_snapshots(conn: sqlite3.Connection) -> list[SnapshotChange]:
    rows = conn.execute(
        "SELECT a.id, a.run_id, r.game_name, a.aspect,"
        "       a.reviews_with_aspect, a.positive, a.negative, a.mixed, a.neutral"
        " FROM aggregate_snapshots a JOIN reports r ON r.run_id = a.run_id"
        " WHERE a.slot = 'candidate' AND instr(a.aspect, '_') > 0 ORDER BY a.id"
    ).fetchall()
    changes: list[SnapshotChange] = []
    for _row_id, run_id, game_name, aspect, *counts in rows:
        after = folded(str(aspect))
        before_counts = tuple(int(c) for c in counts)
        target = conn.execute(
            "SELECT id, reviews_with_aspect, positive, negative, mixed, neutral"
            " FROM aggregate_snapshots WHERE run_id = ? AND slot = 'candidate' AND aspect = ?",
            (run_id, after),
        ).fetchone()
        if target is None:
            changes.append(SnapshotChange(
                str(run_id), str(game_name), str(aspect), after, None,
                before_counts, before_counts,
            ))
            continue
        # Merge exactness: the two spellings must sit on disjoint reviews, else
        # a review counted under both would be counted twice by the sum.
        overlap = _review_set(conn, str(run_id), str(aspect)) & _review_set(
            conn, str(run_id), after
        )
        if overlap:
            raise SystemExit(
                f"refusing: {game_name}: {aspect!r} and {after!r} share {len(overlap)}"
                f" review(s); a summed merge would double count"
            )
        target_id, *target_counts = target
        merged = tuple(int(a) + int(b) for a, b in zip(before_counts, target_counts, strict=True))
        changes.append(SnapshotChange(
            str(run_id), str(game_name), str(aspect), after, int(target_id),
            tuple(int(c) for c in target_counts), merged,
        ))
    return changes


def apply(conn: sqlite3.Connection, renames: list[MentionRename],
          changes: list[SnapshotChange]) -> None:
    with conn:
        for rename in renames:
            conn.execute(
                "UPDATE mentions SET aspect = ? WHERE id = ?", (rename.after, rename.mention_id)
            )
        for change in changes:
            if change.merged_into is None:
                conn.execute(
                    "UPDATE aggregate_snapshots SET aspect = ? WHERE run_id = ?"
                    " AND slot = 'candidate' AND aspect = ?",
                    (change.after, change.run_id, change.before),
                )
                continue
            sets = ", ".join(f"{col} = ?" for col in _COUNT_COLUMNS)
            conn.execute(
                f"UPDATE aggregate_snapshots SET {sets} WHERE id = ?",
                (*change.counts_after, change.merged_into),
            )
            conn.execute(
                "DELETE FROM aggregate_snapshots WHERE run_id = ? AND slot = 'candidate'"
                " AND aspect = ?",
                (change.run_id, change.before),
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", help="write (default: plan only)")
    args = parser.parse_args()
    conn = sqlite3.connect(args.db)
    renames = plan_mentions(conn)
    changes = plan_snapshots(conn)
    print(f"mentions to rename: {len(renames)}")
    for rename in renames:
        print(f"  #{rename.mention_id}: {rename.before!r} -> {rename.after!r}")
    print(f"snapshot rows to change: {len(changes)}")
    for change in changes:
        verb = "merge into" if change.merged_into is not None else "rename to"
        print(
            f"  {change.game_name}: {change.before!r} {verb} {change.after!r},"
            f" counts {change.counts_before} -> {change.counts_after}"
        )
    if not args.apply:
        print("dry run: pass --apply to write")
        return
    apply(conn, renames, changes)
    left = conn.execute(
        "SELECT count(*) FROM aggregate_snapshots WHERE slot = 'candidate'"
        " AND instr(aspect, '_') > 0"
    ).fetchone()[0]
    left_m = conn.execute(
        "SELECT count(*) FROM mentions WHERE slot = 'candidate' AND instr(aspect, '_') > 0"
    ).fetchone()[0]
    print(f"written; underscore candidates remaining: snapshots {left}, mentions {left_m}")


if __name__ == "__main__":
    main()
