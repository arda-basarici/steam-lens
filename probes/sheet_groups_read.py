"""Sheet groups read (2026-11-14): what do a mention floor and the sentiment
groups do to the library, read from a copy of the serving database?

The recommender chat compares games on an aspect through groups, not through a
sorted number. Two dials set the groups: the mention floor below which a game
has no reading on an aspect, and the lines the sentiment share's interval has
to clear. This read prices both on the stored aggregates, pinned aspects only,
one report per game (the newest).

The sentiment share is ``positive / reviews_with_aspect``: every review that
mentions the aspect is in the denominator, mixed and neutral included. Its
interval is a plain Wilson interval on the mentions. The sampling study's
shipped interval is not used here, because it was calibrated on the mention
share and never on sentiment.

The rule as read (the working values of 2026-11-14, set to be cheap to move):

- fewer than ``FLOOR`` reviews mention the aspect: too few mentions
- the positive share's interval starts above ``STRONG_LINE``: strongly positive
- it starts above ``MAJORITY_LINE``: mostly positive
- the negative share's interval starts above ``MAJORITY_LINE``: clearly negative
- otherwise split when the interval's half-width is at most ``SPLIT_HALF_WIDTH``,
  and unclear when it is wider

Read-only. No request leaves the machine.

Result (2026-11-14, the box copy of that date: 107 games, 4,524 game-and-aspect
cells): 3,632 cells have too few mentions, 337 are strongly positive, 214
mostly positive, 130 clearly negative, 155 split and 56 unclear. A floor of 30
leaves 15 aspects readable in twenty or more games, where 20 leaves 31 and 50
leaves 6. Combat reads in 46 games: 12 strongly positive, 24 mostly positive,
10 split, none clearly negative. No game is positive on ``bugs``; 21 are
clearly negative and 83 have too few mentions. 171 of the 892 cells above the
floor change group if mixed and neutral mentions leave the denominator.

Run: python probes/sheet_groups_read.py <path to a serving database copy>
"""

import sqlite3
import statistics
import sys
from collections import Counter, defaultdict

from steamlens.core.intervals import wilson_interval

FLOOR = 30
STRONG_LINE = 0.70
MAJORITY_LINE = 0.50
SPLIT_HALF_WIDTH = 0.15

FLOORS_COMPARED = (20, 30, 50)
GROUPS = ("strongly positive", "mostly positive", "clearly negative", "split", "unclear",
          "too few mentions")
FEATURED = ("combat", "story", "gameplay", "graphics", "difficulty", "music", "price_value",
            "multiplayer", "replayability", "performance", "bugs")


def group(positive: int, negative: int, mentions: int, floor: int = FLOOR) -> str:
    """The group one game falls in on one aspect, from its stored counts."""
    if mentions < floor:
        return "too few mentions"
    praise = wilson_interval(positive, mentions)
    if praise.low > STRONG_LINE:
        return "strongly positive"
    if praise.low > MAJORITY_LINE:
        return "mostly positive"
    if wilson_interval(negative, mentions).low > MAJORITY_LINE:
        return "clearly negative"
    if (praise.high - praise.low) / 2 <= SPLIT_HALF_WIDTH:
        return "split"
    return "unclear"


def read_cells(path: str) -> list[tuple]:
    """Pinned aggregate rows of each game's newest report."""
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    return con.execute("""
        select r.game_name, a.aspect, a.reviews_with_aspect, a.positive, a.negative,
               a.mixed, a.neutral
        from aggregate_snapshots a join reports r using (run_id)
        where a.slot = 'pinned'
          and r.created_at = (select max(created_at) from reports where app_id = r.app_id)
    """).fetchall()


def main() -> None:
    cells = read_cells(sys.argv[1])
    by_aspect: dict[str, list[tuple]] = defaultdict(list)
    for cell in cells:
        by_aspect[cell[1]].append(cell)
    games = {cell[0] for cell in cells}
    print(f"{len(games)} games, {len(cells)} game-and-aspect cells, {len(by_aspect)} aspects")

    print("\n== widest interval a floor lets in (half-width in points, share at 50%) ==")
    for floor in FLOORS_COMPARED:
        interval = wilson_interval(floor // 2, floor)
        print(f"  floor {floor}: {(interval.high - interval.low) / 2 * 100:.1f}")

    print("\n== aspects readable in at least N games, per floor ==")
    for floor in FLOORS_COMPARED:
        clearing = [sum(c[2] >= floor for c in rows) for rows in by_aspect.values()]
        print(f"  floor {floor}: " + ", ".join(
            f"{n}+ games: {sum(count >= n for count in clearing)}" for n in (10, 20, 40)))

    print(f"\n== cells per group (floor {FLOOR}, lines {MAJORITY_LINE:.0%} and "
          f"{STRONG_LINE:.0%}, split within {SPLIT_HALF_WIDTH * 100:.0f} points) ==")
    tally = Counter(group(c[3], c[4], c[2]) for c in cells)
    for name in GROUPS:
        print(f"  {name:<18} {tally[name]:>5}")

    print("\n== games per group, by aspect ==")
    print(f"{'aspect':<14} " + " ".join(f"{name:>17}" for name in GROUPS))
    for aspect in FEATURED:
        counts = Counter(group(c[3], c[4], c[2]) for c in by_aspect[aspect])
        print(f"{aspect:<14} " + " ".join(f"{counts[name]:>17}" for name in GROUPS))

    above = [c for c in cells if c[2] >= FLOOR]
    soft = sorted((c[5] + c[6]) / c[2] for c in above)
    moved = sum(
        group(c[3], c[4], c[2]) != group(c[3], c[4], c[3] + c[4], floor=1)
        for c in above if c[3] + c[4]
    )
    print(f"\n== mixed and neutral mentions, the {len(above)} cells above the floor ==")
    print(f"  share of mentions: median {statistics.median(soft):.1%}, "
          f"90th percentile {soft[int(len(soft) * 0.9)]:.1%}, max {soft[-1]:.1%}")
    print(f"  cells that change group if they leave the denominator: {moved}")

    print("\n== combat above the floor, game by game ==")
    print(f"{'game':<36} {'mentions':>8} {'pos':>4} {'neg':>4} {'mixed':>5} {'neutral':>7} "
          f"{'positive':>8} {'interval':>10}  group")
    for cell in sorted(by_aspect["combat"], key=lambda c: -c[3] / c[2]):
        name, _, mentions, positive, negative, mixed, neutral = cell
        if mentions < FLOOR:
            continue
        interval = wilson_interval(positive, mentions)
        print(f"{name[:35]:<36} {mentions:>8} {positive:>4} {negative:>4} {mixed:>5} "
              f"{neutral:>7} {positive / mentions:>8.0%} "
              f"{interval.low:>4.0%}-{interval.high:<4.0%}  {group(positive, negative, mentions)}")


if __name__ == "__main__":
    main()
