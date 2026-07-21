"""Per-game corpus counts for the survey-slice-size ruling.

Counts, per corpus game: total reviews, English reviews, and English reviews that
survive the Unicode-honest emptiness test (drop category-C chars + whitespace before
checking — the gold draw's lesson, INSTRUCTIONS ruling 26). The English-nonempty
column is the real supply the survey slice draws from (the pipeline's English-first
filter). Output: one table sorted ascending by that column, plus supply-vs-target
summary lines for candidate per-game slice sizes.
"""

import json
import unicodedata
from pathlib import Path

CORPUS = Path("C:/Users/ardab/Desktop/projects/steam-reviews/data")
CANDIDATE_TARGETS = [500, 1000, 2000, 3000]


def is_nonempty(text: str) -> bool:
    stripped = "".join(
        ch for ch in text if not unicodedata.category(ch).startswith("C")
    ).strip()
    return bool(stripped)


def main() -> None:
    with open(CORPUS / "game_list.json", encoding="utf-8") as f:
        game_list = json.load(f)["games"]
    names = {str(g["app_id"]): g["name"] for g in game_list}

    rows = []
    for path in sorted((CORPUS / "raw" / "reviews").glob("*_reviews.jsonl")):
        appid = path.name.split("_")[0]
        total = english = english_nonempty = 0
        with open(path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                rec = json.loads(line)
                total += 1
                if rec.get("language") == "english":
                    english += 1
                    if is_nonempty(rec.get("review") or ""):
                        english_nonempty += 1
        rows.append((names.get(appid, "?"), appid, total, english, english_nonempty))

    rows.sort(key=lambda r: r[4])

    print(f"{'game':<42}{'appid':>9}{'total':>9}{'english':>9}{'en-nonempty':>13}")
    for name, appid, total, english, nonempty in rows:
        print(f"{name[:40]:<42}{appid:>9}{total:>9}{english:>9}{nonempty:>13}")

    grand = [sum(r[i] for r in rows) for i in (2, 3, 4)]
    print(f"\n{'TOTAL (50 games)':<42}{'':>9}{grand[0]:>9}{grand[1]:>9}{grand[2]:>13}")

    usable = [r for r in rows if r[1] != "730"]
    supply = [r[4] for r in usable]
    print(f"\nUsable games (CS2 excluded): {len(usable)}, "
          f"English-nonempty supply: {sum(supply)}")
    for target in CANDIDATE_TARGETS:
        short = [(n, s) for (n, _, _, _, s) in usable for s in [s] if s < target]
        drawn = sum(min(s, target) for s in supply)
        print(f"\n  target {target}/game -> total labels {drawn:>7}  "
              f"games short of target: {len(short)}")
        for name, s in short:
            print(f"    short: {name[:38]:<40} supply {s:>6} (census, {s/target:.0%} of target)")


if __name__ == "__main__":
    main()
