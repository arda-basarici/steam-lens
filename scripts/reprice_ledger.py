"""Reprice flat-priced spend-ledger rows from the archive's recorded usage.

The one-off migration behind the 2026-08-10 re-ruling that overturned the
cost-truth fix's forward-only stance: pre-fix ledger rows were priced with
every prompt token at the full input rate, ~5x over the provider's bill
(~90% of a classify prompt is prefix-cache hits billed at a 50x discount),
and leaving them as written kept every all-time surface on /ops — spend per
report, stage totals, the daily table — broadcasting inflated numbers. The
repricing is exact, not estimated: the response archive stores each call's
raw provider body, whose ``usage`` block records the true cache split, so
each ledger row's cost is *recomputed* by the same formula the live client
prices with (``llm_client.client._actual_cost``).

Standalone by design — stdlib only, no steamlens import — because it runs on
the box against ``/srv/steamlens/data/serve.db`` where only the container
carries the package. The price table and the usage-parsing rules are
duplicated here from ``dispatch/census_arm.py`` and
``llm_client/openai_compat.py`` deliberately: a migration must state the
numbers it applied, and this one runs once.

Matching: ledger rows and archive bodies pair 1:1 (verified 643 = 643 at the
2026-08-09 restore check) but share no key, so rows claim bodies by their
full token tuple (prompt, output, thinking). Rows whose tuple appears more
than once get an arbitrary body from the tied group — harmless for cost
totals when the tied bodies agree on the cache split, reported loudly when
they do not. The built-in self-check: post-fix rows recompute to their
stored cost exactly, so a nonzero "disagrees" count on rows already priced
with the split means the mechanism is wrong — apply refuses.

Dry-run by default; ``--apply`` rewrites inside one transaction and re-reads
the day totals from disk. Take a snapshot first (the runbook's
``sqlite3 .backup``) — this is the ledger's one sanctioned revision.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass

# USD per million tokens — DeepSeek's table, verified against
# api-docs.deepseek.com and reconciled to the billed dashboard 2026-08-09.
PRICES: dict[str, tuple[float, float, float]] = {
    # model -> (input, cached input, output); the serving path routes every
    # stage through the census arm's client, so one model row covers it
    "deepseek-v4-flash": (0.14, 0.0028, 0.28),
}
# Recomputation must reproduce post-fix stored costs bit-for-bit (same
# doubles, same formula); anything past rounding noise is a real difference.
TOLERANCE = 1e-9


@dataclass(frozen=True)
class ArchiveUsage:
    """One archived body's token accounting, parsed by the adapter's rules."""

    prompt: int
    output: int
    thinking: int
    cached: int

    @property
    def key(self) -> tuple[int, int, int]:
        return (self.prompt, self.output, self.thinking)


def usage_from_body(raw: str) -> ArchiveUsage | None:
    """The adapter's usage read (openai_compat), mirrored: subset-vs-disjoint
    reasoning, both cache spellings, cached capped at prompt. None when the
    body is not JSON or carries no usage block (nothing to reprice from)."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    usage = data.get("usage")
    if not isinstance(usage, dict):
        return None

    def as_int(value: object) -> int:
        return value if isinstance(value, int) else 0

    def as_dict(value: object) -> dict:
        return value if isinstance(value, dict) else {}

    completion = as_int(usage.get("completion_tokens"))
    reasoning = as_int(as_dict(usage.get("completion_tokens_details")).get("reasoning_tokens"))
    output = completion if reasoning > completion else completion - reasoning
    prompt = as_int(usage.get("prompt_tokens"))
    cached = as_int(as_dict(usage.get("prompt_tokens_details")).get("cached_tokens")) or as_int(
        usage.get("prompt_cache_hit_tokens")
    )
    return ArchiveUsage(
        prompt=prompt, output=output, thinking=reasoning, cached=min(cached, prompt)
    )


def true_cost(usage: ArchiveUsage, model: str) -> float:
    """``_actual_cost``, restated: cache hits at their rate, thinking at output's."""
    input_rate, cached_rate, output_rate = PRICES[model]
    fresh = usage.prompt - usage.cached
    return (
        fresh * input_rate
        + usage.cached * cached_rate
        + (usage.output + usage.thinking) * output_rate
    ) / 1_000_000


@dataclass
class RowPlan:
    """One ledger row's repricing verdict."""

    rowid: int
    day: str
    stored_cost: float
    new_cost: float
    stored_cached: int
    new_cached: int

    @property
    def changes(self) -> bool:
        return (
            abs(self.new_cost - self.stored_cost) > TOLERANCE
            or self.new_cached != self.stored_cached
        )


def plan(conn: sqlite3.Connection) -> tuple[list[RowPlan], list[int], int]:
    """Match every ledger row to an archive body and price it.

    Returns (plans, unmatched rowids, count of tied tuples whose candidate
    bodies disagree on the cache split — attribution inside such a group is
    arbitrary; the group's total stays exact).
    """
    pool: dict[tuple[int, int, int], list[ArchiveUsage]] = defaultdict(list)
    for (raw,) in conn.execute("SELECT raw_response FROM classify_cache"):
        parsed = usage_from_body(str(raw))
        if parsed is not None:
            pool[parsed.key].append(parsed)
    ambiguous_groups = sum(
        1 for candidates in pool.values() if len({c.cached for c in candidates}) > 1
    )

    plans: list[RowPlan] = []
    unmatched: list[int] = []
    rows = conn.execute(
        "SELECT rowid, created_at, model, prompt_tokens, output_tokens,"
        " thinking_tokens, cached_prompt_tokens, cost"
        " FROM spend_ledger ORDER BY created_at, rowid"
    ).fetchall()
    for rowid, created_at, model, prompt, output, thinking, cached, cost in rows:
        if model not in PRICES:
            raise SystemExit(f"no price table for model {model!r} (rowid {rowid}) — refusing")
        candidates = pool.get((int(prompt), int(output), int(thinking)))
        if not candidates:
            unmatched.append(int(rowid))
            continue
        body = candidates.pop()
        plans.append(
            RowPlan(
                rowid=int(rowid),
                day=str(created_at)[:10],
                stored_cost=float(cost),
                new_cost=true_cost(body, str(model)),
                stored_cached=int(cached),
                new_cached=body.cached,
            )
        )
    return plans, unmatched, ambiguous_groups


def report(plans: list[RowPlan], unmatched: list[int], ambiguous_groups: int) -> None:
    changed = [p for p in plans if p.changes]
    already_true = [p for p in plans if not p.changes]
    # Rows that already carry a cache split are post-fix: recomputation must
    # agree with their stored cost, or the matching itself is broken.
    disagreeing_postfix = [p for p in changed if p.stored_cached > 0]

    print(f"ledger rows matched : {len(plans)}")
    print(f"  already true      : {len(already_true)} (post-fix rows, recomputed == stored)")
    print(f"  to reprice        : {len(changed)}")
    unmatched_detail = f"  rowids {unmatched}" if unmatched else ""
    print(f"unmatched rows      : {len(unmatched)}{unmatched_detail}")
    print(f"ambiguous groups    : {ambiguous_groups} (tied token tuples, differing cache splits)")
    if disagreeing_postfix:
        print(
            f"SELF-CHECK FAILED   : {len(disagreeing_postfix)} post-fix rows "
            "recompute differently"
        )

    by_day: dict[str, tuple[float, float]] = {}
    for p in plans:
        before, after = by_day.get(p.day, (0.0, 0.0))
        by_day[p.day] = (before + p.stored_cost, after + p.new_cost)
    print(f"\n{'day':<12}{'stored USD':>12}{'repriced USD':>14}")
    for day in sorted(by_day, reverse=True):
        before, after = by_day[day]
        print(f"{day:<12}{before:>12.4f}{after:>14.4f}")
    total_before = sum(p.stored_cost for p in plans)
    total_after = sum(p.new_cost for p in plans)
    print(f"{'total':<12}{total_before:>12.4f}{total_after:>14.4f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", required=True, help="path to serve.db")
    parser.add_argument(
        "--apply", action="store_true", help="rewrite the rows (default: dry-run report only)"
    )
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    try:
        plans, unmatched, ambiguous_groups = plan(conn)
        report(plans, unmatched, ambiguous_groups)
        changed = [p for p in plans if p.changes]
        if any(p.stored_cached > 0 for p in changed):
            raise SystemExit("\nself-check failed — post-fix rows disagree; nothing written")
        if unmatched:
            raise SystemExit("\nunmatched ledger rows — nothing written; investigate first")
        if not args.apply:
            print("\ndry run — pass --apply to write")
            return
        with conn:
            conn.executemany(
                "UPDATE spend_ledger SET cost = ?, cached_prompt_tokens = ? WHERE rowid = ?",
                [(p.new_cost, p.new_cached, p.rowid) for p in changed],
            )
        settled = conn.execute("SELECT COALESCE(SUM(cost), 0.0) FROM spend_ledger").fetchone()[0]
        print(f"\napplied: {len(changed)} rows rewritten; ledger total now {settled:.4f} USD")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
