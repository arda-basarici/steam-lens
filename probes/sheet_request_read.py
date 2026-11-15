"""Read example requests against a copy of the serving database, through the sheet.

What it answers: with no game removed on evidence, how the library divides on
real requests. For each request it prints the tally per want and how many
games meet the musts, are open on one, or conflict with one, and names the
games in the smaller groups.

The requests are five of the example conversations the request structure was
ruled from, written here as the understand step should fill them, plus "an
RPG", which shows the games the store does not list under a genre and
players tag.

Run:  python probes/sheet_request_read.py <path to a database copy>

The copy must be at the current schema; opening it migrates it forward, so
point this at a scratch copy and never at the dated copies under ``data/``.
"""

from __future__ import annotations

import sys
import time
from collections import Counter

from steamlens.contracts import (
    AspectTarget,
    Firmness,
    MustStanding,
    PlayerRequest,
    RequestIntent,
    Stance,
    StoreFactTarget,
    TermTarget,
    Want,
    WantFinding,
)
from steamlens.chat.sheet import load_library, term_hit_counts
from steamlens.core.sheet import read_sheet
from steamlens.store import Store

MUST, WANT, NICE = Firmness.MUST, Firmness.WANT, Firmness.NICE_TO_HAVE


def want(words, target, firmness, stance=Stance.WANTS, partial=False):
    return Want(words=words, firmness=firmness, stance=stance, target=target, partial=partial)


REQUESTS = {
    "1. single player, a good story, characters i care about": (
        want("single player", StoreFactTarget("single-player"), MUST),
        want("a good story", AspectTarget("story"), WANT),
        want("characters i care about", AspectTarget("characters"), WANT),
    ),
    "4. relaxing, runs at 60 fps on my laptop": (
        want("relaxing", AspectTarget("relaxation"), WANT),
        want("60 fps on my laptop", AspectTarget("performance"), MUST, partial=True),
    ),
    "5 (turn 2). scary, it needs online co-op": (
        want("scary", TermTarget(("horror", "scary", "creepy")), MUST),
        want("online co-op", StoreFactTarget("online-co-op"), MUST),
    ),
    "12. a puzzle game, nothing with a timer, nice music a bonus": (
        want("a puzzle game", TermTarget(("puzzle", "puzzles")), MUST),
        want("a timer", TermTarget(("timer", "timed", "time limit")), MUST, Stance.AVOIDS),
        want("nice music", AspectTarget("music"), NICE),
    ),
    "3. a realistic curling game": (
        want("curling", TermTarget(("curling",)), MUST),
        want("realistic, full matches", None, WANT),
    ),
    "an RPG": (want("an rpg", StoreFactTarget("rpg"), MUST),),
}


def main(db_path: str) -> None:
    with Store(db_path) as store:
        started = time.perf_counter()
        library = load_library(store)
        print(f"library: {len(library)} games, read in {time.perf_counter() - started:.2f} s\n")
        for title, wants in REQUESTS.items():
            request = PlayerRequest(intent=RequestIntent.RECOMMEND, wants=wants)
            sheet = read_sheet(request, library, term_hit_counts(store, request))
            standing = Counter(row.standing for row in sheet.rows)
            print(title)
            print(
                f"   meets the musts {standing[MustStanding.MEETS]:>3} · open on a must "
                f"{standing[MustStanding.OPEN]:>3} · conflicts {standing[MustStanding.CONFLICTS]:>3}"
            )
            for index, (item, tally) in enumerate(zip(wants, sheet.tallies, strict=True)):
                findings = Counter(row.readings[index].finding.value for row in sheet.rows)
                print(
                    f"   {item.firmness.value:<12} {item.words:<26} matches {tally.matches:>3}  "
                    f"fails {tally.fails:>3}  cannot tell {tally.cannot_tell:>3}   "
                    + ", ".join(f"{name} {count}" for name, count in sorted(findings.items()))
                )
            for group in (MustStanding.MEETS, MustStanding.OPEN):
                names = [row.game.name for row in sheet.rows if row.standing is group]
                if 0 < len(names) <= 12:
                    print(f"   {group.value}: " + "; ".join(names))
            tagged = [
                row.game.name for row in sheet.rows
                if any(r.finding is WantFinding.TAGGED_NOT_LISTED for r in row.readings)
            ]
            if tagged:
                print("   tagged by players, not listed by the store: " + "; ".join(tagged))
            print()


if __name__ == "__main__":
    main(sys.argv[1])
