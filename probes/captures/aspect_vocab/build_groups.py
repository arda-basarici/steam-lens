import collections
import json
import sys

SRC = "extractions.jsonl"
OUT = "label_groups.json"

counts = collections.Counter()
with open(SRC, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        for a in rec.get("aspects", []):
            counts[a["aspect"]] += 1

ALL_LABELS = set(counts.keys())

# Explicit merge clusters (surface variants / clear synonyms only).
# Each inner list is a set of labels judged to be the same concept.
MERGE_CLUSTERS = [
    ["graphics", "visuals"],
    ["replayability", "replay value"],
    ["addictiveness", "addiction"],
    ["relaxation", "relaxing", "relaxing aspect", "relaxing gameplay", "chill"],
    ["dialogue", "dialogues"],
    ["player choices", "choices", "decisions"],
    ["bugs", "glitches", "bugs and glitches"],
    ["crashes", "game crashes"],
    ["performance", "current performance", "game performance"],
    ["multiplayer", "online multiplayer"],
    ["multiplayer with friends", "playing with friends"],
    ["competitive experience", "competitive play"],
    ["matchmaking", "matchmaking system"],
    ["bot crisis", "bots", "bots and deddosers"],
    ["story", "story plot", "narrative", "stories"],
    ["mod support", "modding support"],
    ["character creation", "character customization"],
    ["open world", "open-world"],
    ["map size", "world size"],
    ["content", "content amount"],
    ["side quests", "side missions", "side objectives"],
    ["optional content", "side content"],
    ["learning curve", "learning difficulty"],
    ["value for money", "value"],
    ["price", "cost"],
    ["farming", "farming gameplay"],
    ["farm life simulation", "farm simulation"],
    ["trading", "trading system"],
    ["truck driver life simulation", "truck life simulation", "trucking genre"],
    ["appeal to truck enthusiasts", "appeal to truck lovers"],
    ["driving experience", "driving"],
    ["gameplay loop", "core gameplay loop"],
    ["playstyles", "play styles", "multiple playstyles", "playstyle variety"],
    ["d&d experience", "dnd experience"],
    ["dnd mechanics", "dungeons and dragons integration"],
    ["music", "soundtrack"],
    ["radio feature", "radio", "radio station"],
    ["customer support", "developer support", "support"],
    ["epic games' management", "epic games' competence"],
    ["time consumption", "time investment", "time commitment", "time sink"],
    ["completion time", "game length", "game time"],
    ["stress", "stress level"],
    ["quality of life improvements", "quality-of-life updates"],
    ["updates", "patches", "post-launch improvements"],
    ["skill tree", "ability/combat trees"],
    ["cyberware mechanics", "cyberware system"],
    ["game progression", "progression system"],
    ["combat", "combat system", "combat mechanics"],
]

VAGUE_VERDICT_MEMBERS = [
    "basic game", "care and thought", "charm", "craftsmanship", "current state",
    "dedication", "detail", "developer dedication", "enjoyment", "excitement",
    "experience", "feel-good", "fun", "game", "game experience", "game originality",
    "game recommendation", "joy", "moments", "overall experience", "overall quality",
    "player experience", "polish", "shortcomings", "uniqueness", "vibe",
]

assigned = set()
groups = []

def canonical_for(members):
    max_c = max(counts[m] for m in members)
    top = sorted(m for m in members if counts[m] == max_c)
    return top[0]

for cluster in MERGE_CLUSTERS:
    for m in cluster:
        if m not in ALL_LABELS:
            print(f"ERROR: unknown label in cluster: {m!r}", file=sys.stderr)
            sys.exit(1)
        if m in assigned:
            print(f"ERROR: label assigned twice: {m!r}", file=sys.stderr)
            sys.exit(1)
        assigned.add(m)
    canon = canonical_for(cluster)
    groups.append({
        "canonical": canon,
        "members": sorted(cluster),
        "mentions": sum(counts[m] for m in cluster),
    })

# vague_verdict special group
for m in VAGUE_VERDICT_MEMBERS:
    if m not in ALL_LABELS:
        print(f"ERROR: unknown vague_verdict label: {m!r}", file=sys.stderr)
        sys.exit(1)
    if m in assigned:
        print(f"ERROR: vague_verdict label assigned twice: {m!r}", file=sys.stderr)
        sys.exit(1)
    assigned.add(m)
groups.append({
    "canonical": "vague_verdict",
    "members": sorted(VAGUE_VERDICT_MEMBERS),
    "mentions": sum(counts[m] for m in VAGUE_VERDICT_MEMBERS),
})

# everything else: singleton groups
remaining = ALL_LABELS - assigned
for m in sorted(remaining):
    groups.append({
        "canonical": m,
        "members": [m],
        "mentions": counts[m],
    })
    assigned.add(m)

# ---- verification ----
union = set()
total_mentions = 0
dup_found = False
seen_members = collections.Counter()
for g in groups:
    for m in g["members"]:
        seen_members[m] += 1
    union |= set(g["members"])
    total_mentions += g["mentions"]

dups = [m for m, c in seen_members.items() if c > 1]
if dups:
    print("DUPLICATE MEMBERS:", dups, file=sys.stderr)
    dup_found = True

missing = ALL_LABELS - union
extra = union - ALL_LABELS
if missing:
    print("MISSING LABELS:", missing, file=sys.stderr)
if extra:
    print("EXTRA UNKNOWN LABELS:", extra, file=sys.stderr)

if total_mentions != sum(counts.values()):
    print(
        f"MENTION COUNT MISMATCH: groups sum={total_mentions}, source sum={sum(counts.values())}",
        file=sys.stderr,
    )

# recompute mentions per group from counts (sanity, should match already)
for g in groups:
    recomputed = sum(counts[m] for m in g["members"])
    if recomputed != g["mentions"]:
        print(
            f"GROUP MENTION MISMATCH for {g['canonical']}: "
            f"stated {g['mentions']} vs recomputed {recomputed}",
            file=sys.stderr,
        )
        g["mentions"] = recomputed

ok = (not dups) and (not missing) and (not extra) and (total_mentions == sum(counts.values()))
print(f"distinct labels: {len(ALL_LABELS)}")
print(f"total mentions: {sum(counts.values())}")
print(f"groups: {len(groups)}")
print(f"union covers all labels, no dups, mention totals preserved: {ok}")

groups.sort(key=lambda g: (-g["mentions"], g["canonical"]))

output = {
    "provenance": {
        "method": "LLM grouping, conservative-merge rules, single pass",
        "grouped_by": "claude-sonnet subagent",
        "date": "2026-07-09",
        "status": "pending human review",
        "source": f"extractions.jsonl ({len(ALL_LABELS)} distinct labels "
        "expected; use actual count)",
    },
    "groups": groups,
}

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print(f"wrote {OUT}")
