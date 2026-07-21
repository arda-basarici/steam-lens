"""Reads the aspect-vocabulary captures and prints the shape the ontology decision needs.

Companion to aspect_vocab_probe.py (which produced probes/captures/aspect_vocab/).
Two passes: first exact-match on the raw labels the model emitted (the ungroomed
distribution — a hard lower bound on coverage, since surface variants split counts),
then, when the reviewed label_groups.json mapping exists, the same statistics after
canonical grouping — the decision-grade view. The raw pass stays in the output so the
distance between the two is visible: that gap IS the normalization burden a hybrid
ontology would carry.

The three questions, from the framing handoff: how many labels cover ~90% of mentions
(coverage curve); do top labels recur across genres (cross-game overlap); is the tail
game-specific vocabulary or noise (tail composition).

Run: python probes/aspect_vocab_analysis.py
"""
from __future__ import annotations

import collections
import json
import random
from pathlib import Path

CAPTURE_DIR = Path(__file__).resolve().parent / "captures" / "aspect_vocab"
CAPTURES = CAPTURE_DIR / "extractions.jsonl"
GROUPS = CAPTURE_DIR / "label_groups.json"


def load_records() -> list[dict]:
    """All captured per-review extraction records, as written by the probe."""
    with CAPTURES.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def mention_counts(records: list[dict]) -> collections.Counter:
    """Raw label -> total mention count across all reviews."""
    counts = collections.Counter()
    for r in records:
        for a in r["aspects"]:
            counts[a["aspect"]] += 1
    return counts


def coverage_at(counts: collections.Counter, k: int) -> float:
    """Share of all mentions covered by the k most frequent labels."""
    total = sum(counts.values())
    return sum(n for _, n in counts.most_common(k)) / total if total else 0.0


def main() -> None:
    records = load_records()
    by_game: dict[str, list[dict]] = collections.defaultdict(list)
    for r in records:
        by_game[r["game"]].append(r)

    overall = mention_counts(records)
    total_mentions = sum(overall.values())
    zero_share = sum(1 for r in records if not r["aspects"]) / len(records)

    print(f"{len(records)} reviews | {total_mentions} aspect mentions | "
          f"{len(overall)} distinct raw labels | zero-aspect reviews: {zero_share:.0%}\n")

    print("coverage curve (overall, raw exact-match):")
    for k in (5, 10, 15, 20, 30, 50, 75, 100):
        print(f"  top {k:>3}: {coverage_at(overall, k):>5.1%}")

    print("\nper-game: mentions | distinct | top-15 coverage | top 8 labels")
    game_counts = {g: mention_counts(rs) for g, rs in by_game.items()}
    for game, counts in game_counts.items():
        top8 = ", ".join(f"{label}({n})" for label, n in counts.most_common(8))
        print(f"  {game}: {sum(counts.values())} | {len(counts)} | "
              f"{coverage_at(counts, 15):.0%}\n      {top8}")

    n_games_per_label = collections.Counter()
    for counts in game_counts.values():
        for label in counts:
            n_games_per_label[label] += 1
    shared = [label for label, n in n_games_per_label.items() if n >= 3]
    shared_mentions = sum(overall[label] for label in shared)
    single = [label for label, n in n_games_per_label.items() if n == 1]
    single_mentions = sum(overall[label] for label in single)
    print(f"\ncross-game: {len(shared)} labels appear in >=3 of 5 games "
          f"({shared_mentions/total_mentions:.0%} of mentions); "
          f"{len(single)} labels in exactly 1 game "
          f"({single_mentions/total_mentions:.0%} of mentions)")
    print(f"  shared labels: {', '.join(sorted(shared))}")

    once = [label for label, n in overall.items() if n == 1]
    print(f"\ntail: {len(once)} labels mentioned exactly once "
          f"({len(once)/len(overall):.0%} of vocabulary). sample of 25:")
    print("  " + ", ".join(random.Random(0).sample(once, min(25, len(once)))))

    if GROUPS.exists():
        print_grouped_shape(records, by_game)
    else:
        print("\n(no label_groups.json yet — grouped shape skipped)")


def load_group_map() -> tuple[dict[str, str], dict]:
    """raw label -> canonical group name, plus the file's provenance block."""
    data = json.loads(GROUPS.read_text(encoding="utf-8"))
    mapping = {}
    for g in data["groups"]:
        for member in g["members"]:
            mapping[member] = g["canonical"]
    return mapping, data.get("provenance", {})


def print_grouped_shape(records: list[dict], by_game: dict[str, list[dict]]) -> None:
    """The decision-grade view: the same statistics after canonical grouping.

    vague_verdict is excluded from coverage — it is extraction noise, not an aspect,
    and letting it pad the head of the curve would flatter whichever ontology wins.
    Its share is reported separately so the exclusion is visible, not silent.
    """
    mapping, provenance = load_group_map()
    print(f"\n=== grouped shape (mapping: {provenance.get('grouped_by', '?')}, "
          f"status: {provenance.get('status', '?')}) ===")

    def grouped_counts(recs: list[dict]) -> tuple[collections.Counter, int]:
        counts, vague = collections.Counter(), 0
        for r in recs:
            for a in r["aspects"]:
                canonical = mapping.get(a["aspect"], a["aspect"])
                if canonical == "vague_verdict":
                    vague += 1
                else:
                    counts[canonical] += 1
        return counts, vague

    overall, vague = grouped_counts(records)
    total = sum(overall.values())
    print(f"{total} aspect mentions after grouping | {len(overall)} groups | "
          f"vague_verdict absorbed {vague} mentions (excluded from coverage)\n")

    print("coverage curve (grouped):")
    for k in (5, 10, 15, 20, 30, 50):
        cum = sum(n for _, n in overall.most_common(k)) / total if total else 0
        print(f"  top {k:>3}: {cum:>5.1%}")

    print("\ntop 20 groups overall: "
          + ", ".join(f"{label}({n})" for label, n in overall.most_common(20)))

    game_counts = {g: grouped_counts(rs)[0] for g, rs in by_game.items()}
    n_games = collections.Counter()
    for counts in game_counts.values():
        for label in counts:
            n_games[label] += 1
    shared = [label for label, n in n_games.items() if n >= 3]
    single = [label for label, n in n_games.items() if n == 1]
    print(f"\ncross-game (grouped): {len(shared)} groups in >=3 of 5 games "
          f"({sum(overall[label] for label in shared)/total:.0%} of mentions); "
          f"{len(single)} groups in exactly 1 game "
          f"({sum(overall[label] for label in single)/total:.0%} of mentions)")


if __name__ == "__main__":
    main()
