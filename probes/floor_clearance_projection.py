"""Floor-clearance projection for the survey-slice-size ruling.

Reuses the pruning pass's label->pin mapping (probes/pruning_evidence_table.py,
executed via runpy) to estimate per-game per-pin mention rates from the B1 probe
captures, then projects: at candidate slice sizes, how many of the 51 pins clear
the evidence floor (>= 5 expected mentions, the mock's illustrative value) for
each game. Supply per game = English-nonempty counts (per_game_counts.py).

Honesty caveats carried in the output: rates come from ~100-review probes per
game (a 1%-rate aspect shows zero mentions in a 100-review probe ~37% of the
time), the probe instrument differs from classify-v1, and unmapped labels stay
candidates -- so projected clearance is a noisy floor, not a promise.
"""

import runpy
import statistics
import collections
from pathlib import Path

PROBES = Path("C:/Users/ardab/Desktop/projects/steam-lens/probes")
FLOOR = 5
CANDIDATES = [500, 1000, 2000, 3000, "census"]

# English-nonempty supply per game (per_game_counts.py, 2026-07-19), by name.
SUPPLY = {
    "Shadow of the Tomb Raider": 195, "The Lord of the Rings: Gollum": 404,
    "Mount & Blade II: Bannerlord": 611, "NBA 2K23": 648, "Portal 2": 680,
    "Surgeon Simulator": 963, "Noita": 1007, "A Way Out": 1107,
    "Undertale": 1153, "Battlefield 2042": 1203, "Goat Simulator": 1253,
    "Cities: Skylines": 1288, "Dark Souls III": 1344, "Europa Universalis IV": 1346,
    "Tavern Master": 1350, "Elden Ring": 1440, "Satisfactory": 1458,
    "Democracy 3": 1492, "Doki Doki Literature Club!": 1692,
    "Euro Truck Simulator 2": 1806, "Warsim: The Realm of Aslona": 1975,
    "Rocket League": 1983, "Redfall": 2089, "Starfield": 2097,
    "Final Fantasy XIV Online": 2115, "The Day Before": 2327,
    "Disco Elysium": 2596, "Cuphead": 2623, "Left 4 Dead 2": 2844,
    "Darkest Dungeon": 2902, "Path of Exile": 2929, "Rust": 3066,
    "Stardew Valley": 3252, "Persona 5 Royal": 3341, "Cyberpunk 2077": 3747,
    "Hollow Knight": 3955, "BioShock Infinite": 3989,
    "What Remains of Edith Finch": 4221, "Garry's Mod": 4413,
    "Papers, Please": 4585, "No Man's Sky": 4792, "Baldur's Gate 3": 5002,
    "Phasmophobia": 5612, "Helldivers 2": 5752,
    "Mass Effect Legendary Edition": 5802, "Overwatch 2": 5850,
    "Fallout 4": 5898, "Wasteland 3": 6194, "VVVVVV": 6869,
}


def main() -> None:
    pet = runpy.run_path(str(PROBES / "pruning_evidence_table.py"))
    records, surface, traps, ugc = (
        pet["records"], pet["surface"], pet["TRAPS"], pet["UGC"])
    n_pins = len(pet["order"])

    probed = collections.Counter()
    mentions = collections.Counter()  # (game, pin) -> count
    for r in records:
        probed[r["game"]] += 1
        for a in r["aspects"]:
            label = a["aspect"]
            if (r["game"], label) in traps or label in ugc:
                continue
            pin = surface.get(label)
            if pin:
                mentions[(r["game"], pin)] += 1

    games = sorted(set(probed) & set(SUPPLY))
    missing = set(SUPPLY) - set(probed)
    print(f"games with probe rates: {len(games)}  "
          f"(probed reviews/game: min {min(probed[g] for g in games)}, "
          f"median {statistics.median(probed[g] for g in games)}, "
          f"max {max(probed[g] for g in games)})")
    if missing:
        print(f"supply games without probe coverage (skipped): {sorted(missing)}")

    print(f"\nPins clearing the floor (>= {FLOOR} expected mentions) per game, "
          f"of {n_pins} pinned aspects:")
    print(f"{'slice':>8} | {'min':>4} {'p25':>4} {'median':>6} {'p75':>4} {'max':>4}"
          f" | games at census (slice >= supply)")
    for cand in CANDIDATES:
        live = []
        censused = 0
        for g in games:
            n = SUPPLY[g] if cand == "census" else min(cand, SUPPLY[g])
            if n >= SUPPLY[g]:
                censused += 1
            cleared = sum(
                1 for pin in pet["order"]
                if mentions[(g, pin)] / probed[g] * n >= FLOOR)
            live.append(cleared)
        q = statistics.quantiles(live, n=4)
        print(f"{str(cand):>8} | {min(live):>4} {q[0]:>4.0f} "
              f"{statistics.median(live):>6.0f} {q[2]:>4.0f} {max(live):>4}"
              f" | {censused}/{len(games)}")

    print("\nPer-game detail at 1000 vs census (pins clearing floor):")
    print(f"{'game':<34}{'supply':>7}{'@1000':>7}{'@census':>9}")
    for g in sorted(games, key=lambda g: SUPPLY[g]):
        def cleared_at(n: int) -> int:
            return sum(1 for pin in pet["order"]
                       if mentions[(g, pin)] / probed[g] * n >= FLOOR)
        print(f"{g[:32]:<34}{SUPPLY[g]:>7}"
              f"{cleared_at(min(1000, SUPPLY[g])):>7}{cleared_at(SUPPLY[g]):>9}")


if __name__ == "__main__":
    main()
