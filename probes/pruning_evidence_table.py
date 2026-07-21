"""Corpus-complete evidence table for the pruned codebook (B1 pruning pass).

Maps every extracted label across all three captures onto the 51 pinned aspects:
tier 1 = the codebook's own surface (label + aliases, case/underscore-normalized);
tier 2 = variants validated by hand during the 2026-07-15 pruning session.
Known traps are excluded explicitly. Everything unmapped stays candidate/vague —
counts are floors by construction.
"""
import collections
import json
import tomllib
from pathlib import Path

PROBES = Path(__file__).resolve().parent
ONTO = PROBES.parent / "src" / "steamlens" / "ontology" / "v1.toml"

with ONTO.open("rb") as f:
    onto = tomllib.load(f)

surface: dict[str, str] = {}
category_of: dict[str, str] = {}
order: list[str] = []
for a in onto["aspects"]:
    label = a["label"]
    order.append(label)
    category_of[label] = a["category"]
    surface[label.replace("_", " ")] = label
    for alias in a["aliases"]:
        surface[alias.lower()] = label

EXTRAS = {
    "gameplay": ["game mechanics", "gameplay mechanics", "core gameplay", "general gameplay",
                 "gameplay experience", "sandbox gameplay", "casual gameplay", "ghost hunting",
                 "ghost hunting experience", "automation", "factory building"],
    "combat": ["bosses", "boss fights", "boss design", "gun play", "guns", "melee combat",
               "turn-based combat", "tactical combat", "combat mechanics", "3d combat", "sniping"],
    "controls": ["steering wheel support", "steering turning ratio", "movement mechanics",
                 "movement targeting", "attack targeting"],
    "difficulty": ["game difficulty", "mastery difficulty", "combat difficulty",
                   "death consequences"],
    "learning_curve": ["tutorial", "new player experience", "beginner friendliness",
                       "ease of entry", "learnability", "gameplay understanding",
                       "game complexity", "explanations for new things", "novice network"],
    "progression": ["game progression", "level system", "level up system", "perks",
                    "job system", "end game gear", "level cap", "end game", "endgame content",
                    "early game", "leveling speed"],
    "balance": ["hero balancing", "game balance", "character balance", "new character balancing",
                "job system balance", "balancing"],
    "player_choice": ["choices", "choice system", "player choices", "moral choices",
                      "choice mechanics", "faction choices", "choices impact",
                      "consequences of mistakes", "personality choices", "story choices"],
    "exploration": ["discoverability", "cavern exploration", "adventure and exploration"],
    "level_design": ["level linearity", "levels", "plane levels", "dungeon design",
                     "ambulance level", "map layout"],
    "quest_design": ["quests", "questlines", "fetch quests", "dungeoning content", "ncpd missions",
                     "mission execution", "side quest quality"],
    "build_variety": ["playstyles", "character builds", "build density", "build creation",
                      "build crafting", "duo builds", "ways to play", "classes", "multi-classing",
                      "starting classes", "classes/jobs", "weapon variety"],
    "replayability": ["game longevity", "long-term playability", "long-term mmo"],
    "ai_behavior": ["ai", "enemy ai", "npc behavior", "ghost behavior", "ghost tells",
                    "ghost evasion", "ghost mechanics", "bot play in breakthrough"],
    "physics": ["game physics", "physics engine", "ragdolls", "ragdoll physics",
                "source engine physics", "car hitboxes"],
    "story": ["storytelling", "storyline", "storylines", "endings", "main story",
              "base game story", "phantom liberty story", "post-arr story",
              "a realm reborn story", "adventure story", "story content", "story progression"],
    "writing": ["dialogue", "dialogues", "dialog", "character writing", "prose", "exposition",
                "npc dialogue", "dialogue system", "dialogue trees", "dialogue options",
                "dialogue interactions"],
    "lore": ["corporate history", "lore integration", "world history"],
    "characters": ["character development", "companions", "cast", "origin characters",
                   "protagonist (v)", "character (johnny)"],
    "voice_acting": ["voice performances", "voice work", "narration", "narrator",
                     "keanu reeves acting", "male v actor"],
    "emotional_impact": ["emotional impact", "overall message", "social impact", "personal impact"],
    "graphics": ["game visuals", "texture quality", "texture pop-in", "visual fidelity"],
    "art_style": ["art style", "cyberpunk style", "design and style", "game style"],
    "animation": ["character animations", "facial animations", "tool animations",
                  "smudge animation", "new animations", "animations and models",
                  "character models"],
    "music": ["ost", "custom music", "music listening"],
    "sound_design": ["sound design", "sound", "sound effects", "ambient sound", "sound direction",
                     "music and sounds", "sound and music", "dying sounds", "weapon sounds",
                     "random sounds", "speech recognition", "spirit box voice recognition"],
    "atmosphere": ["immersion", "scare factor", "spookiness", "suspense", "jumpscares",
                   "world immersion", "city immersiveness"],
    "world": ["open world", "world building", "map size", "night city detail",
              "night city believability",
              "night city life", "city detail", "city completeness", "city emptiness",
              "world emptiness", "europe setting", "environment depth", "npc life"],
    "realism": ["historical accuracy", "policy realism", "space realism", "combat realism",
                "simulation quality", "farm life simulation", "truck driver life simulation",
                "driving experience"],
    "performance": ["pc performance", "system performance", "gameplay smoothness",
                    "loading screens", "frame rate", "game lag", "game performance",
                    "performance on low spec pc", "performance on low-end devices",
                    "pc requirements", "system requirements", "launch performance"],
    "stability": ["crashes", "game crashes", "game stability", "technical stability",
                  "launch issues", "save corrupted"],
    "bugs": ["glitches", "game errors", "graphical glitches", "graphical issues",
             "glitches and bugs", "ghost bugs", "quest issues", "clunky issues",
             "item jitter", "sound desync", "jankiness", "update bugs", "post-update bugs",
             "buggy updates", "raiju light glitch"],
    "ui": ["user interface", "interfaces", "ui clarity", "ui design", "ui transition",
           "combat ui", "upgrade interface", "main menu", "mutator menu", "settings",
           "notifications", "quest journal", "ability hotbar"],
    "servers_netcode": ["server stability", "server issues", "server outages", "ddos attacks",
                        "ping discrepancies", "networking", "online lobbies", "joining games",
                        "internet disconnection", "rubberbanding"],
    "platform_access": ["secure boot requirement", "secureboot requirement", "linux support",
                        "linux compatibility", "mac support", "epic games account requirement",
                        "account linking", "account system", "account connection", "account login",
                        "login process", "login issues", "login system", "login layer",
                        "steam launcher", "square enix account", "phone number requirement",
                        "vr mode", "vr support", "vr gameplay", "platform availability",
                        "mobile version", "pc version", "multi-platform experience",
                        "kernel-level anticheat", "privacy and security", "security features",
                        "security checks", "code registration", "cd keys", "product keys",
                        "purchase requirements", "purchase method", "registration",
                        "installation", "installation time", "download time", "install size",
                        "uninstall process", "game exit functionality"],
    "content_amount": ["game content", "content volume", "content quantity", "side content",
                       "content depth", "optional content", "game modes", "maps", "new maps",
                       "number of maps", "new content", "new ghosts", "ghost types", "raids",
                       "collectables", "minigames"],
    "game_length": ["game length", "playtime", "gameplay time", "time consumption",
                    "time spent", "job length", "game size", "main story quest length",
                    "story progression time"],
    "price_value": ["pricing", "game value", "value for money", "dlc price", "worth the price"],
    "monetization": ["lootboxes", "battlepass", "free to play", "free to play model",
                     "skin prices", "skin quality", "shop skins", "subscription cost",
                     "payment model", "stash tabs", "crates and keys", "company greed",
                     "customization prices", "cosmetics cost", "free trial", "drops",
                     "shop updates"],
    "dlc": ["dlc content", "expansions", "phantom liberty dlc", "phantom liberty dlc content",
            "phantom liberty dlc ending", "phantom liberty dlc integration",
            "phantom liberty weapons", "heavensward expansion", "current expansion (dawntrail)"],
    "customization": ["character customization", "glamour system", "glamour dresser", "housing",
                      "customisability", "customization options", "customization concept",
                      "truck customization", "world customization", "character options",
                      "player customization", "custom character models", "cosmetic additions",
                      "cosmetics availability", "cosmetics variety"],
    "updates": ["game updates", "update quality", "update", "recent update", "new update",
                "latest update", "newest update", "most recent update", "developer updates",
                "update frequency", "update speed", "update readiness", "update significance",
                "content updates", "free content updates", "content drops", "release cycles",
                "2.0 update", "alan wake update", "animation update", "character update",
                "character customization update", "player character update",
                "new cosmetics update", "anniversary update", "quality of life improvements",
                "evolution", "evolution over years", "future updates", "fixes",
                "expansions and updates", "league content", "mirage league"],
    "developer_conduct": ["developers", "developer", "developer support", "customer service",
                          "developer communication", "developer competence",
                          "developer accountability", "developer attitude", "developer care",
                          "developer responsiveness", "developer responsiveness to community",
                          "developer engagement", "developer attention", "developer management",
                          "developer output", "developer playtesting", "developer design decisions",
                          "developer studio", "developer turnaround", "dev updates",
                          "blizzard employees", "epic games' management", "customer focus",
                          "respect for player time", "battlenet support", "technical support",
                          "community feedback", "community support", "refund process", "refunds",
                          "marketing accuracy", "scandal", "release complaints", "playtesting"],
    "mods": ["modding support", "modding community", "community mods", "mod dependency",
             "mod support"],
    "community": ["chat community", "lobby toxicity", "player communication", "trolls",
                  "player reporting", "free company system", "social influence"],
    "cheating": ["anti-cheat measures", "bot crisis", "spinbotter"],
    "multiplayer": ["playing with friends", "co-op experience", "multiplayer experience",
                    "multiplayer functionality", "multiplayer interaction",
                    "multiplayer with friends",
                    "social experience", "social aspect", "social connection", "solo play",
                    "single player", "single-player", "single player experience",
                    "single-player experience", "playing solo", "playing with randoms",
                    "enjoyment with friends/family", "max players", "team coordination",
                    "team quality", "teammates", "other players"],
    "matchmaking": ["matchmaking imbalance", "match balancing mechanics", "matching system",
                    "ranking system", "competitive suspension", "skill gap"],
    "relaxation": ["relaxing gameplay", "relaxing aspect", "stress relief", "comfort",
                   "visual comfort", "therapeutic", "escapism", "anger outlet", "time-pass"],
    "addictiveness": ["arpg itch", "time killer", "impact on life", "one more run"],
    "pacing": ["narrative pacing", "combat pacing", "gameplay pace"],
}
for target, variants in EXTRAS.items():
    for v in variants:
        surface.setdefault(v, target)

# Traps: (game, label) pairs that must NOT map despite matching a surface form.
TRAPS = {
    ("Satisfactory", "optimization"),          # factory optimization = the play activity
    ("Darkest Dungeon", "stress mechanic"),    # a game system, not player relaxation
    ("Darkest Dungeon", "stress management"),
    ("Euro Truck Simulator 2", "stress level"),
    ("NBA 2K23", "menu music"),
}
UGC = {"level editor", "user levels", "level creation"}  # VVVVVV user-generated content

def load(path):
    return [json.loads(line) for line in open(path, encoding="utf-8")]

def load_all_records():
    records = load(PROBES / "captures/aspect_vocab_lite/extractions.jsonl")
    records += [r for r in load(PROBES / "captures/aspect_vocab_ext/extractions.jsonl")
                if r["game"] != "Elden Ring"]
    records += load(PROBES / "captures/aspect_vocab/extractions.jsonl")
    return records

records = load_all_records()
counts = collections.Counter()
games_of = collections.defaultdict(set)
mapped_mentions = 0
total_mentions = 0
candidate_counts = collections.Counter()
for r in records:
    for a in r["aspects"]:
        total_mentions += 1
        label = a["aspect"]
        if (r["game"], label) in TRAPS or label in UGC:
            candidate_counts[label] += 1
            continue
        target = surface.get(label)
        if target:
            counts[target] += 1
            games_of[target].add(r["game"])
            mapped_mentions += 1
        else:
            candidate_counts[label] += 1

n_games = len({r["game"] for r in records})
print(f"{len(records)} reviews | {n_games} games | {total_mentions} mentions | "
      f"{mapped_mentions} mapped to pins ({mapped_mentions/total_mentions:.0%}), "
      f"rest = candidates + vague\n")
print("| # | Aspect | Mentions | Games |")
print("|---|---|---|---|")
current_cat = None
for i, label in enumerate(order, start=1):
    if category_of[label] != current_cat:
        current_cat = category_of[label]
        print(f"| | **{current_cat}** | | |")
    print(f"| {i} | {label} | {counts[label]} | {len(games_of[label])} |")

print("\ntop 25 unmapped (candidate-space + vague):")
for cand, n in candidate_counts.most_common(25):
    print(f"  {n:3d}  {cand}")
