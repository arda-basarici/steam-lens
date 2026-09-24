"""Reprice the V4.1 Flash ledger rows that were written at the flat V4 table.

The migration behind the 2026-09-24 rate-period rule. DeepSeek re-pointed the
requested id at V4.1 Flash on 2026-09-10 (first serving call 2026-09-16), with
a different price table and the peak/off-peak split it had introduced on
2026-08-16; the ledger kept pricing every call at the flat V4 table until the
rule landed on 2026-09-24. Leaving those rows as written keeps every all-time
surface on /ops (spend per report, stage totals, the daily table)
broadcasting understated numbers — the same reasoning that overturned
"forward-only" for the 2026-08-10 repricing.

The repricing is exact, not estimated: every row since the 2026-08-10
migration carries its own token split (``cached_prompt_tokens``), and the rate
period is a pure function of the row's ``created_at``, so each cost is
*recomputed* by the formula the live client prices with
(``llm_client.client._actual_cost`` over ``dispatch.census_arm.MODEL_SPEC``).
Scope is the ledger's own evidence, not a date guess: rows whose
provider-reported ``model_version`` is ``deepseek-flash`` are exactly the
V4.1 rows.

Standalone by design — stdlib only, no steamlens import — because it runs on
the box against ``/srv/steamlens/data/serve.db`` where only the container
carries the package. The two price tables and the schedule are duplicated
here from ``dispatch/census_arm.py`` deliberately: a migration must state the
numbers it applied, and this one runs once.

The built-in self-check: every in-scope row must recompute to *either* its
stored cost under the old flat table (a row awaiting repricing) or its stored
cost under the new rule (a row the live client already priced after the
deploy). A row matching neither means the mechanism is wrong — apply refuses.

Dry-run by default; ``--apply`` rewrites inside one transaction and re-reads
the day totals from disk. Take a snapshot first (the runbook's
``sqlite3 .backup``) — the ledger's second sanctioned revision.
"""

from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

IN_SCOPE_MODEL_VERSION = "deepseek-flash"

# (input, cached input, output) USD per million tokens.
OLD_FLAT_TABLE = (0.14, 0.0028, 0.28)  # V4 Flash, reconciled 2026-08-09
NEW_PEAK_TABLE = (0.30, 0.006, 1.20)  # V4.1 Flash peak, api-docs 2026-09-24

# DeepSeek's split: peak 01:00–04:00 and 06:00–10:00 UTC, Monday–Friday,
# off-peak at half. Holidays approximated as peak (census_arm states why).
PEAK_WINDOWS_UTC = ((1, 4), (6, 10))
PEAK_WEEKDAYS = frozenset(range(5))
OFF_PEAK_MULTIPLIER = 0.5

# Recomputation must reproduce stored costs bit-for-bit under one of the two
# rules (same doubles, same formula); anything past rounding noise is real.
TOLERANCE = 1e-9


def period_multiplier(created_at: str) -> float:
    """``RateSchedule.multiplier_at`` restated for the row's ISO-8601 UTC stamp."""
    moment = datetime.fromisoformat(created_at)
    if moment.tzinfo is None:
        raise SystemExit(f"naive timestamp in the ledger ({created_at!r}) — refusing")
    moment = moment.astimezone(UTC)
    in_window = any(start <= moment.hour < end for start, end in PEAK_WINDOWS_UTC)
    return 1.0 if moment.weekday() in PEAK_WEEKDAYS and in_window else OFF_PEAK_MULTIPLIER


def cost_under(
    table: tuple[float, float, float],
    *,
    prompt: int,
    cached: int,
    output: int,
    thinking: int,
    multiplier: float,
) -> float:
    """``_actual_cost``, restated: cache hits at their rate, thinking at output's,
    the whole call at its period multiplier."""
    input_rate, cached_rate, output_rate = table
    fresh = prompt - cached
    return multiplier * (
        fresh * input_rate + cached * cached_rate + (output + thinking) * output_rate
    ) / 1_000_000


@dataclass(frozen=True)
class RowPlan:
    """One ledger row's verdict: awaiting repricing, already on the new rule, or unexplained."""

    rowid: int
    day: str
    stored_cost: float
    new_cost: float
    verdict: str  # "reprice" | "already_true" | "unexplained"


def plan(conn: sqlite3.Connection) -> list[RowPlan]:
    """Price every in-scope row under both rules and classify it by its stored cost."""
    rows = conn.execute(
        "SELECT rowid, created_at, prompt_tokens, cached_prompt_tokens, output_tokens,"
        " thinking_tokens, cost FROM spend_ledger WHERE model_version = ?"
        " ORDER BY created_at, rowid",
        (IN_SCOPE_MODEL_VERSION,),
    ).fetchall()
    plans: list[RowPlan] = []
    for rowid, created_at, prompt, cached, output, thinking, cost in rows:
        tokens = {
            "prompt": int(prompt), "cached": int(cached),
            "output": int(output), "thinking": int(thinking),
        }
        flat = cost_under(OLD_FLAT_TABLE, multiplier=1.0, **tokens)
        new = cost_under(NEW_PEAK_TABLE, multiplier=period_multiplier(str(created_at)), **tokens)
        stored = float(cost)
        if abs(stored - new) <= TOLERANCE:
            verdict = "already_true"
        elif abs(stored - flat) <= TOLERANCE:
            verdict = "reprice"
        else:
            verdict = "unexplained"
        plans.append(RowPlan(int(rowid), str(created_at)[:10], stored, new, verdict))
    return plans


def report(plans: list[RowPlan]) -> None:
    verdicts = ("reprice", "already_true", "unexplained")
    counts = {v: sum(1 for p in plans if p.verdict == v) for v in verdicts}
    print(f"in-scope rows (model_version = {IN_SCOPE_MODEL_VERSION!r}): {len(plans)}")
    print(f"  to reprice        : {counts['reprice']} (stored == old flat table)")
    print(
        f"  already true      : {counts['already_true']} "
        "(stored == new rule; the live client's rows)"
    )
    print(f"  unexplained       : {counts['unexplained']} (match neither rule)")
    if counts["unexplained"]:
        rowids = [p.rowid for p in plans if p.verdict == "unexplained"][:10]
        print(f"SELF-CHECK FAILED   : first unexplained rowids {rowids}")
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
        plans = plan(conn)
        report(plans)
        if any(p.verdict == "unexplained" for p in plans):
            raise SystemExit("\nself-check failed — rows match neither rule; nothing written")
        changed = [p for p in plans if p.verdict == "reprice"]
        if not args.apply:
            print("\ndry run — pass --apply to write")
            return
        with conn:
            conn.executemany(
                "UPDATE spend_ledger SET cost = ? WHERE rowid = ?",
                [(p.new_cost, p.rowid) for p in changed],
            )
        settled = conn.execute("SELECT COALESCE(SUM(cost), 0.0) FROM spend_ledger").fetchone()[0]
        print(f"\napplied: {len(changed)} rows rewritten; ledger total now {settled:.4f} USD")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
