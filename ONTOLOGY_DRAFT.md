# Aspect ontology — v1 working draft (codebook)

**Status: DRAFT — under Arda's review. Not ratified, not loaded by code.**

This file is the single-source codebook for the v1 pinned aspect ontology. At
ratification it converts to the versioned artifact (TOML under
`src/steamlens/ontology/`) that loads into `AspectOntology`; both the classify
prompt (compact render: definition + aliases + do-not line) and the gold-set
labeling instructions (full render, with examples) derive from it. Edit here;
nothing downstream consumes this file yet.

Authored by Arda 2026-07-10 over the aspect-vocabulary probe's grouped labels
(`probes/captures/aspect_vocab/label_groups.json`, 313 groups / 704 mentions /
500 reviews / 5 genre-diverse games); detail pass (examples, probe evidence,
boundary fixes) by Claude the same day. Probe lines read "≈N · G games" —
approximate merged mentions and game spread; "—" means not observed in the
probe (the entry is argued from domain generality, not evidence).

---

## Open decisions before ratification

1. **Every row costs gold coverage.** 55 pinned aspects × ~20 recruited gold
   reviews ≈ 1,100+ reviews in the enriched strata, and every row gets a
   certified number. Rows that exist mainly as routing targets (e.g. `camera`,
   `animation`) still pass the crisp-boundary bar — but check each against the
   product bar: "do I want SteamLens to answer with a number here?" Arda prunes
   the list before ratification.
   **Constraint when demoting:** a "Do not label when → use X" reference
   requires X to stay pinned; demoting a row to candidate means rewriting the
   neighbors that point at it (the loader will validate references).

## Settled 2026-07-10 (Arda's rulings)

- **Romance is NOT a characters alias — it stays unpinned.** An alias would
  fold romance mentions into the `characters` statistic irreversibly; the
  intent is romance in the stories, not the numbers. Romance-systems talk is
  recorded as a CANDIDATE label at runtime and in gold labeling.
- **Immersion stays dropped as a label.** Bare "immersive/immersion" praise
  routes to `atmosphere` (sensory pull) or `world` (believability), per those
  entries.
- **`vibe` dropped from atmosphere aliases** — it collides with the
  vague-verdict pile; bare "good vibes" with no referent stays a no-label
  verdict.

## Changes applied in the detail pass (audit me)

- Moved **"game feel"** from `gameplay` aliases → `controls` (it collided with
  controls' "movement feel"; game-feel talk is responsiveness/feedback talk).
- Moved **"difficulty spike"** from `difficulty` aliases → `balance` (spikes
  are tuning complaints; `balance`'s definition already claimed them).
- Split the **"subtitles"** collision: translation/existence → `localization`;
  size/readability options → `accessibility`. Do-not lines added both ways.
- Added the **jank boundary**: broken motion → `animation`; broken behavior →
  `bugs`.
- Added **"time sink"** to `game_length` aliases with boundaries vs `grind`
  (forced repetition) and `addictiveness` (voluntary pull). Probe had 6
  mentions · 3 games of time-sink talk.
- Added the **dubbed-audio boundary** to `voice_acting`: performance quality →
  `voice_acting`; which languages are voiced/translated → `localization`.
- Added examples throughout (negative examples in the dense neighborhoods),
  probe-evidence lines, and boundary notes. No entry deleted, none added.

## Near-neighbor stress-test fixes (2026-07-10, second pass — audit me)

Mechanical audit (55 labels): no duplicate aliases across entries, no dangling
"use `X`" references. One shadowing bug + four semantic double-claims fixed:

- **`performance` alias removed from `voice_acting`** (→ "voice performance").
  The bare alias shadowed the `performance` label — a raw "performance" mention
  would have normalized to voice acting instead of runtime performance.
- **`pacing` now owns ALL pacing-talk.** `story`'s definition had claimed
  "pacing of the narrative" while `pacing` claimed "story beats" — both entries
  deflected the boundary at each other. Rule: `story` = what happens, `pacing`
  = how it flows, narrative or play alike.
- **Fear/feeling boundary settled:** `atmosphere` = the mood the game
  *sustains* (property of presentation); `emotional_impact` = the player being
  *affected* ("it genuinely scared/moved me"). Cross do-nots added both ways.
- **Believability boundary settled** (wording per Arda): `world` = internally
  *consistent/coherent*, lived-in as a fictional place; `realism` = fidelity to
  *real life* (simulation, history). Cross do-nots added both ways.
- **Refined per Arda (same day):** `realism` is *cross-cutting* — the evaluated
  property is trueness-to-life whatever it attaches to (visuals, mechanics,
  behavior), fantasy settings included; "realistic graphics" routes to
  `realism`, plain visual praise to `graphics`. `world` widened to whole-world
  evaluations ("beautiful/impressive world") — gains `scenery`/`landscapes`
  aliases (the probe's ETS2 vocabulary); the *place* being beautiful → `world`,
  image quality → `graphics`, art direction → `art_style`. Also widened to
  *liveliness* — an inhabited world where life goes on around the player
  (Night City, a living city); NPC behavior *quality* stays `ai_behavior`,
  the world feeling alive is `world`.
- **System-feel rule added to `controls`:** "combat feels clunky" labels
  `combat`, not `controls` — `controls` is input in general, not the feel of a
  named system.
- Minor: `grind`'s label-when made sentiment-neutral ("satisfying grind"
  counts); `content_amount`↔`quest_design` volume-vs-structure do-nots added;
  ambiguous alias "text" dropped from `writing`; "settings menu / options menu"
  added to `ui`.

## Global labeling rules (apply to every entry)

- **Aspect, not mood.** An aspect is a property of the game or the experience
  around it — never the reviewer's life or state ("I was depressed and this
  helped" → no label unless a game property is evaluated).
- **Bare verdicts get no label.** "Masterpiece", "10/10", "trash" with no
  subject → zero aspects. A zero-aspect review is a first-class result
  (~46% of reviews in the probe).
- **Multi-label is normal.** Label every distinct aspect a review evaluates;
  one clause can only carry one label — pick the most specific that fits.
- **Child-shaped mentions take the parent.** The aliases and "label when"
  lines route; sub-flavors ("endgame progression") are never their own label.
- **Not listed ≠ not recorded.** A genuine aspect with no pinned home is a
  CANDIDATE: keep the reviewer's own wording as a free-form label. Never
  force-fit into the nearest pinned label.
- **Sentiment attaches per mention** (pos / neg / mixed), independent of the
  review's thumbs-up.
- Labels are `snake_case` identifiers; display names are a downstream concern.
- Category headers below are organizational only — never classification targets.

---

## 1. Play

### 1. gameplay

**Definition:** Moment-to-moment play and core mechanics, when no more specific label applies.
**Aliases:** gameplay loop, core mechanics, mechanics.
**Label when:** The reviewer evaluates the basic act of playing.
**Do not label when:** They mention combat, controls, progression, level design, or another specific system — use that label. `gameplay` is the fallback for play-talk, not an extra label on top of a specific one.
**Examples:**
- "The gameplay is fun but gets repetitive." → `gameplay`
- "Shooting feels punchy and the bosses are great." → `combat`, **not** `gameplay`
**Probe:** ≈30 · 5 games.

### 2. combat

**Definition:** Fighting systems, encounters, weapons, abilities, enemies as combat opponents.
**Aliases:** fighting, combat system, gunplay, melee, battles, encounters.
**Label when:** The review evaluates fighting or combat encounters.
**Do not label when:** The complaint is about enemy intelligence specifically — use `ai_behavior`. Unfair tuning of weapons/classes — use `balance`.
**Examples:**
- "Turn-based combat with real tactical depth." → `combat`
- "Enemies just stand there while you shoot them." → `ai_behavior`, **not** `combat`
**Probe:** ≈12 · 3 games.

### 3. controls

**Definition:** Input feel, responsiveness, handling, keybinds, controller support.
**Aliases:** handling, input, responsiveness, keybinds, controller support, movement feel, game feel.
**Label when:** The reviewer talks about how it feels to control the game — input in general.
**Do not label when:** The issue is menus/HUD — use `ui`. "Vehicle handling" as simulation behavior — use `physics`. The clunky/smooth *feel of a named system* ("combat feels clunky") — label that system; `controls` is for input generally, not system feel.
**Examples:**
- "Controls are floaty and the deadzone settings don't help." → `controls`
- "Inventory is a nightmare to navigate." → `ui`, **not** `controls`
**Probe:** ≈3 · 2 games.

### 4. camera

**Definition:** Camera movement, perspective, lock-on camera, visibility, FOV, camera-caused discomfort.
**Aliases:** camera angle, lock-on, field of view, FOV, perspective, motion sickness.
**Label when:** The camera itself is praised or criticized.
**Do not label when:** The issue is general controls unless the camera is clearly the cause.
**Examples:**
- "The camera fights you in every boss arena." → `camera`
**Probe:** — (domain-argued; routing target for a canonical complaint).

### 5. difficulty

**Definition:** How hard the game is after the player understands it.
**Aliases:** challenge, hard, easy, difficulty options.
**Label when:** The reviewer evaluates challenge level.
**Do not label when:** The issue is learning/onboarding — use `learning_curve`. Unfair tuning or spikes — use `balance`.
**Examples:**
- "Brutally hard but always fair." → `difficulty`
- "Act 3 suddenly triples the enemy damage for no reason." → `balance`, **not** `difficulty`
**Probe:** ≈8 · 4 games.

### 6. learning_curve

**Definition:** How easy or hard it is to learn, understand, or get into the game.
**Aliases:** onboarding, tutorials, beginner friendly, hard to get into, confusing at first.
**Label when:** The review focuses on entry friction or learning.
**Do not label when:** The game is simply hard — use `difficulty`.
**Examples:**
- "Takes 20 hours before it clicks; the tutorial explains nothing." → `learning_curve`
**Probe:** ≈5 · 3 games.

### 7. progression

**Definition:** Advancement systems: leveling, unlocks, skill trees, perks, gear progression, ranks. Includes endgame progression and pacing of advancement.
**Aliases:** leveling, unlocks, skill tree, perks, advancement, progression system.
**Label when:** The review evaluates how the player advances.
**Do not label when:** The issue is repetitive effort required to progress — use `grind`.
**Examples:**
- "The skill tree actually changes how you play." → `progression`
- "You repeat the same three missions to level anything." → `grind`, **not** `progression`
**Probe:** ≈12 · 4 games.

### 8. grind

**Definition:** Repetitive busywork or excessive repetition required to advance, unlock, earn, or complete.
**Aliases:** grindy, grinding, repetitive farming, chore, tedious progression.
**Label when:** The reviewer evaluates repetition as required effort — criticism or praise ("satisfying grind" counts; sentiment carries the polarity).
**Do not label when:** They only say the game is long — use `game_length`. The repetition is enjoyed/voluntary ("can't stop doing runs") — use `addictiveness`.
**Examples:**
- "Everything past level 30 is a grind wall." → `grind`
**Probe:** ≈1 · 1 game (canonical Steam vocabulary; thin in the probe).

### 9. balance

**Definition:** Fairness and tuning of mechanics, weapons, classes, enemies, economy, difficulty spikes, or progression.
**Aliases:** balancing, overpowered, underpowered, nerf, buff, unfair, broken meta, difficulty spike.
**Label when:** The review says something is unfair, overtuned, undertuned, or poorly balanced.
**Do not label when:** They only say the game is hard — use `difficulty`.
**Examples:**
- "One weapon type invalidates every other build." → `balance`
**Probe:** — (domain-argued; core vocabulary for competitive and RPG genres).

### 10. player_choice

**Definition:** Whether choices matter; agency, consequences, branching decisions.
**Aliases:** player agency, choices matter, consequences, dialogue choices, branching.
**Label when:** The reviewer evaluates meaningful decisions or lack of them.
**Do not label when:** They are talking about builds/playstyles — use `build_variety`.
**Examples:**
- "Your choices genuinely change act two." → `player_choice`
- "So many viable ways to build your character." → `build_variety`, **not** `player_choice`
**Probe:** ≈12 · 3 games.

### 11. exploration

**Definition:** Discovering places, secrets, routes, locations, hidden content.
**Aliases:** discovery, secrets, open world exploration, roaming, exploration rewards.
**Label when:** The player evaluates the act/reward of exploring.
**Do not label when:** The issue is the map/level structure itself — use `level_design`.
**Examples:**
- "Every cave hides something worth finding." → `exploration`
**Probe:** ≈4 · 2 games.

### 12. level_design

**Definition:** Layout and structure of levels, maps, dungeons, arenas, routes, spaces.
**Aliases:** map design, level layout, dungeon design, arena design, stage design.
**Label when:** The review evaluates authored spaces.
**Do not label when:** They only say they like discovering things — use `exploration`. The world as setting/content — use `world`.
**Examples:**
- "Interconnected maps that loop back on themselves brilliantly." → `level_design`
**Probe:** ≈1 · 1 game.

### 13. quest_design

**Definition:** Quality, structure, variety, and objectives of quests or missions.
**Aliases:** missions, quests, side quests, objectives, tasks, mission design.
**Label when:** The review evaluates quest/mission structure.
**Do not label when:** The review evaluates plot — use `story`. Sheer volume of quests/things to do — use `content_amount`.
**Examples:**
- "Side quests are all fetch-and-return filler." → `quest_design`
- "The main questline's twist floored me." → `story`, **not** `quest_design`
**Probe:** ≈5 · 2 games.

### 14. build_variety

**Definition:** Variety of viable builds, playstyles, classes, strategies, weapons, or approaches.
**Aliases:** playstyle variety, build diversity, class variety, different ways to play.
**Label when:** The review evaluates whether players can approach the game in different ways.
**Do not label when:** It is only about cosmetic customization — use `customization`.
**Examples:**
- "Stealth, guns-blazing, or full netrunner — all viable." → `build_variety`
**Probe:** ≈8 · 3 games (absorbs the probe's `playstyles` group).

### 15. replayability

**Definition:** Whether the game rewards replaying or returning after completion/failure.
**Aliases:** replay value, longevity, repeat runs, replayable, keeps me coming back.
**Label when:** The review evaluates long-term return value.
**Do not label when:** The review says the game is addictive in a psychological-pull sense — use `addictiveness`.
**Examples:**
- "Three playthroughs and I'm still finding new content." → `replayability`
- "One more run turns into 3 a.m. every night." → `addictiveness`, **not** `replayability`
**Probe:** ≈20 · 4 games.

### 16. ai_behavior

**Definition:** Quality of enemy, NPC, teammate, or bot behavior.
**Aliases:** enemy AI, NPC behavior, bot teammates, companion AI, pathfinding.
**Label when:** The review evaluates non-player behavior.
**Do not label when:** "Bots" means cheaters/fake players in online matches — use `cheating` or `multiplayer`.
**Examples:**
- "NPCs walk into walls and forget you exist." → `ai_behavior`
**Probe:** ≈3 · 2 games.

### 17. physics

**Definition:** Physical simulation, collisions, movement physics, vehicle handling, object interactions.
**Aliases:** physics, collision, ragdoll, vehicle handling, simulation, floaty movement.
**Label when:** The review evaluates simulation/physical behavior.
**Do not label when:** "Handling" just means input feel — use `controls`.
**Examples:**
- "Ball physics are pixel-perfect and predictable." → `physics`
**Probe:** ≈4 · 2 games.

## 2. Narrative

### 18. story

**Definition:** Plot, narrative arc, major events, ending.
**Aliases:** narrative, plot, ending, final act, story arc.
**Label when:** The reviewer evaluates what happens in the story.
**Do not label when:** The issue is prose/dialogue quality — use `writing`. Rhythm/momentum complaints, narrative or play alike ("drags", "rushed") — use `pacing`, which owns all pacing-talk.
**Examples:**
- "The ending recontextualizes the whole game." → `story`
- "The plot is fine but every line of dialogue is cringe." → `writing` (and `story` only if the plot is separately evaluated)
**Probe:** ≈25 · 3 games.

### 19. writing

**Definition:** Quality of prose, dialogue, script, jokes, lines, text, or written delivery.
**Aliases:** dialogue, script, writing quality, jokes.
**Label when:** The reviewer evaluates how the story/dialogue is written.
**Do not label when:** They evaluate the plot itself — use `story`. Voice performance — use `voice_acting`.
**Examples:**
- "Sharpest dialogue I've read in years." → `writing`
**Probe:** ≈7 · 2 games.

### 20. lore

**Definition:** World backstory, history, mythology, setting background.
**Aliases:** lore, backstory, world history, mythos, codex.
**Label when:** The review evaluates background knowledge/world history.
**Do not label when:** They evaluate the explorable world itself — use `world`.
**Examples:**
- "The codex entries are better than most novels." → `lore`
**Probe:** ≈5 · 3 games.

### 21. characters

**Definition:** Cast depth, likability, development, companions, relationships.
**Aliases:** character development, companions, cast, relationships.
**Label when:** The reviewer evaluates characters as people/entities.
**Do not label when:** They evaluate voice performance — use `voice_acting`.
A romance-*systems* evaluation (options, dating mechanics) is deliberately
unpinned — record it as a CANDIDATE (`romance`), not as `characters`.
**Examples:**
- "Every companion feels like a real person." → `characters`
- "The romance options are the best part." → CANDIDATE `romance`, **not** `characters`
**Probe:** ≈17 · 4 games (the probe's `romance` group, ≈5 · 3, stays candidate
by ruling — see Settled above).

### 22. voice_acting

**Definition:** Voice performance quality.
**Aliases:** voiceover, voice acting, VA, voice performance, narration voice.
**Label when:** The review evaluates spoken performance.
**Do not label when:** They evaluate the written dialogue — use `writing`. Which languages are voiced/subtitled — use `localization`.
**Examples:**
- "The lead actor carries every scene." → `voice_acting`
**Probe:** ≈4 · 2 games.

### 23. emotional_impact

**Definition:** Whether the game is moving, memorable, scary, sad, powerful, or emotionally affecting.
**Aliases:** emotional depth, moving, heartbreaking, memorable, powerful, touching.
**Label when:** The review emphasizes emotional effect on the player — it scared, moved, or stayed with them.
**Do not label when:** The game *sustains* a scary/tense/cozy mood as a property of its presentation — use `atmosphere` (`atmosphere` = the mood the game holds; `emotional_impact` = the player being affected). The feeling is calm/stress while playing — use `relaxation`.
**Examples:**
- "I cried twice and I'm not ashamed." → `emotional_impact`
**Probe:** ≈3 · 3 games.

## 3. Presentation & world

### 24. graphics

**Definition:** Visual fidelity and technical image quality.
**Aliases:** visuals, visual quality, textures, lighting, resolution, fidelity.
**Label when:** The review evaluates technical visual quality.
**Do not label when:** They evaluate aesthetic identity — use `art_style`.
**Examples:**
- "Textures pop in and the lighting is last-gen." → `graphics`
- "It's not photorealistic, but the watercolor look is gorgeous." → `art_style`, **not** `graphics`
**Probe:** ≈17 · 5 games.

### 25. art_style

**Definition:** Art direction, aesthetic identity, visual taste, style coherence.
**Aliases:** aesthetic, artwork, art direction, visual style, stylized.
**Label when:** The review evaluates how the game looks artistically.
**Do not label when:** They talk about raw fidelity — use `graphics`.
**Examples:**
- "The neon-noir aesthetic never gets old." → `art_style`
**Probe:** ≈4 · 3 games.

### 26. animation

**Definition:** Character, combat, facial, movement, or environmental animation quality.
**Aliases:** animations, facial animation, movement animation, janky animation.
**Label when:** The review evaluates motion/animation.
**Do not label when:** The issue is control responsiveness — use `controls`. "Jank" as broken behavior — use `bugs`; janky *motion* belongs here.
**Examples:**
- "Facial animations are stiff in every cutscene." → `animation`
**Probe:** ≈1 · 1 game.

### 27. music

**Definition:** Music and soundtrack.
**Aliases:** soundtrack, OST, score, tracks, music.
**Label when:** The review evaluates music.
**Do not label when:** The review evaluates sound effects/audio feedback — use `sound_design`.
**Examples:**
- "The OST alone is worth the price." → `music`
**Probe:** ≈7 · 4 games.

### 28. sound_design

**Definition:** Non-music audio: sound effects, ambience, audio feedback, mixing, impact sounds.
**Aliases:** audio, SFX, sound effects, ambience, weapon sounds, footsteps, audio feedback.
**Label when:** The review evaluates sound that is not mainly music.
**Do not label when:** The review evaluates soundtrack/OST — use `music`.
**Examples:**
- "Every weapon sounds like it means it." → `sound_design`
**Probe:** ≈1 · 1 game.

### 29. atmosphere

**Definition:** Mood, tone, tension, coziness, horror feeling, general sensory mood.
**Aliases:** atmosphere, mood, tone, ambiance, immersive atmosphere, immersive.
**Label when:** The review evaluates the feeling the game sustains. Bare "immersion" praise about being pulled in routes here (settled ruling — see top).
**Do not label when:** "Immersion" is broken by bugs/performance/UI — label the concrete cause. Bare "good vibes" with no referent is a vague verdict — no label. Believability of the world as a place — use `world`. "It genuinely scared/moved me" as personal effect — use `emotional_impact`.
**Examples:**
- "The fog, the music cues, the dread — the mood never breaks." → `atmosphere`
**Probe:** ≈12 · 3 games (including the probe's `immersion` group).

### 30. world

**Definition:** The built world or setting as content and as a whole: places, setting identity, world density, world coherence, world beauty/impressiveness, and world liveliness — an inhabited world where life visibly goes on around the player.
**Aliases:** setting, world, worldbuilding, world design, world feels alive, living world, empty world, scenery, landscapes.
**Label when:** The review evaluates the world/setting itself — its internal consistency and lived-in coherence *as a fictional place*, the world as a whole ("beautiful world", "impressive world"), or how alive/inhabited it feels (city life, NPCs living their own lives, things happening without the player).
**Do not label when:** They evaluate backstory/history — use `lore`. Authored level layouts — use `level_design`. Fidelity to *real life* (accurate simulation, historical accuracy) — use `realism`. Rendering/image quality — use `graphics`; art direction — use `art_style`; the world as a *place* being beautiful routes here. The *quality of NPC behavior itself* (dumb, broken, robotic NPCs) — use `ai_behavior`; the world feeling alive as an overall property routes here.
**Examples:**
- "Night City feels alive in a way no open world has." → `world`
- "Driving through the Alps at sunset is breathtaking." → `world`, **not** `graphics`
- "NPCs teleport and forget you in two seconds." → `ai_behavior`, **not** `world`
**Probe:** ≈12 · 5 games.

### 31. realism

**Definition:** How realistic or true-to-life something is — visuals, animations, mechanics, behavior, simulation, or the experience as a whole. Cross-cutting: applies inside fantastical settings too (realistic lighting in a fantasy world counts).
**Aliases:** realistic, realism, authenticity, simulation realism, historically accurate, realistic graphics, lifelike.
**Label when:** The evaluated *property* is realisticness/trueness to life, whatever it attaches to — graphics, mechanics, world behavior.
**Do not label when:** They evaluate physics mechanics specifically — use `physics`. Internal consistency/coherence of a *fictional* world as a lived-in place — use `world`. Visual quality praised without realism being the point ("looks amazing") — use `graphics`.
**Examples:**
- "The routes, the tolls, the fatigue rules — it's the real job." → `realism`
- "Rain on the windshield looks absolutely real." → `realism`, **not** `graphics`
**Probe:** ≈7 · 3 games.

## 4. Technical

### 32. performance

**Definition:** Runtime smoothness and optimization: FPS, stutter, loading, hardware demands.
**Aliases:** optimization, FPS, frame rate, stutter, loading times, runs well, runs poorly.
**Label when:** The review evaluates how well the game runs.
**Do not label when:** The game crashes/freezes — use `stability`. Online lag/desync — use `servers_netcode`.
**Examples:**
- "Constant stutter on a 4080 is embarrassing." → `performance`
- "Crashes to desktop every hour." → `stability`, **not** `performance`
**Probe:** ≈10 · 4 games.

### 33. stability

**Definition:** Crashes, freezes, save corruption, launch failures, hard technical failures.
**Aliases:** crash, freeze, softlock, save corrupted, won't launch, black screen.
**Label when:** The review describes severe failure states.
**Do not label when:** It is a non-fatal glitch or broken quest — use `bugs`.
**Examples:**
- "Lost a 40-hour save to corruption." → `stability`
**Probe:** ≈3 · 2 games.

### 34. bugs

**Definition:** Broken behavior: glitches, broken quests, broken mechanics, visual bugs, scripting errors.
**Aliases:** bug, glitch, broken quest, broken mechanic, jank, bugged.
**Label when:** The game behaves incorrectly but not necessarily as a hard crash/freeze.
**Do not label when:** It is mainly low FPS/stutter — use `performance`. Broken *motion* specifically — use `animation`.
**Examples:**
- "The quest marker points at a door that never opens." → `bugs`
**Probe:** ≈12 · 4 games.

### 35. ui

**Definition:** Menus, HUD, inventory screens, readability, navigation, interface friction.
**Aliases:** UI, UX, menus, HUD, interface, inventory UI, readability, menu navigation, settings menu, options menu.
**Label when:** The review evaluates interface design.
**Do not label when:** The review evaluates input responsiveness — use `controls`.
**Examples:**
- "Four submenus to change one setting." → `ui`
**Probe:** ≈2 · 1 game.

### 36. servers_netcode

**Definition:** Online technical quality: servers, lag, disconnects, desync, netcode, online stability.
**Aliases:** servers, netcode, lag, ping, desync, disconnects, rubberbanding.
**Label when:** The review evaluates online infrastructure/connection quality.
**Do not label when:** The issue is bad player matching — use `matchmaking`.
**Examples:**
- "Desync decides more matches than skill does." → `servers_netcode`
**Probe:** ≈2 · 2 games.

### 37. platform_access

**Definition:** Ports, launchers, account requirements, DRM, Steam Deck/Linux support, region/platform access.
**Aliases:** port, launcher, account requirement, DRM, Steam Deck, Linux, console port, login required.
**Label when:** The review criticizes access/friction outside the core game itself.
**Do not label when:** The issue is pricing by region — usually `price_value` (regional pricing events are the investigator's territory, not the ontology's).
**Examples:**
- "Forcing a third-party account on a paid game is insulting." → `platform_access`
**Probe:** ≈8 · 4 games.

### 38. localization

**Definition:** Translation quality, subtitles, language support, regional text/audio support.
**Aliases:** translation, subtitles, language support, localization, machine translation, dubbed audio.
**Label when:** The review evaluates language/translation support — including which languages get voiced audio or subtitles at all.
**Do not label when:** The issue is general writing quality in the original language — use `writing`. Subtitle *options* (size, readability) — use `accessibility`.
**Examples:**
- "The Turkish translation reads like machine output." → `localization`
**Probe:** ≈1 · 1 game.

### 39. accessibility

**Definition:** Options that affect whether different players can comfortably play.
**Aliases:** accessibility, colorblind mode, remapping, font size, subtitle options, motion blur, accessibility options.
**Label when:** The review evaluates accessibility or comfort options.
**Do not label when:** It only says the game is easy/hard — use `difficulty`. Subtitle translation/existence — use `localization`.
**Examples:**
- "No colorblind mode in a color-coded puzzle game." → `accessibility`
**Probe:** — (domain-argued).

## 5. Content & value

### 40. content_amount

**Definition:** Volume of things to do: modes, quests, maps, items, activities, variety of content.
**Aliases:** amount of content, content, lots to do, lack of content, content variety.
**Label when:** The review evaluates how much content exists.
**Do not label when:** It only discusses hours to finish — use `game_length`. Quality/structure of the quests rather than their volume — use `quest_design`.
**Examples:**
- "A hundred hours in and the activity list keeps growing." → `content_amount`
**Probe:** ≈8 · 4 games.

### 41. game_length

**Definition:** Time to finish, total hours, campaign length, short/long duration.
**Aliases:** length, campaign length, hours, too short, too long, completion time, time sink.
**Label when:** The review evaluates duration or the time the game demands.
**Do not label when:** The issue is repetitive required work — use `grind`. The hours pile up because of voluntary pull — use `addictiveness`.
**Examples:**
- "Twelve hours and the credits rolled. At full price." → `game_length`
**Probe:** ≈13 · 4 games (includes the probe's `time consumption` group).

### 42. price_value

**Definition:** Whether the game is worth the asking price.
**Aliases:** price, value, worth it, not worth, sale, full price, overpriced.
**Label when:** The reviewer evaluates value-for-money.
**Do not label when:** The issue is microtransactions or the monetization model — use `monetization`.
**Examples:**
- "Even at full price this is a steal." → `price_value`
- "The game is fine; the $20 skins are not." → `monetization`, **not** `price_value`
**Probe:** ≈10 · 4 games.

### 43. monetization

**Definition:** How the game charges beyond purchase: MTX, loot boxes, battle pass, F2P economy, pay-to-win.
**Aliases:** microtransactions, MTX, loot boxes, crates, battle pass, pay to win, F2P model.
**Label when:** The review evaluates monetization systems.
**Do not label when:** It only says the base price is too high — use `price_value`.
**Examples:**
- "Battle pass FOMO in a full-priced game." → `monetization`
**Probe:** ≈5 · 3 games.

### 44. dlc

**Definition:** DLC quality, DLC policy, expansions, missing content sold separately.
**Aliases:** DLC, expansion, season pass, paid content, downloadable content.
**Label when:** The review evaluates DLC specifically.
**Do not label when:** The issue is general microtransactions — use `monetization`.
**Examples:**
- "The expansion is better than the base game." → `dlc`
**Probe:** ≈6 · 2 games.

### 45. customization

**Definition:** Appearance, identity, character creation, cosmetic personalization, personalization systems.
**Aliases:** customization, character creation, cosmetics, skins, outfits, personalization.
**Label when:** The review evaluates customization options.
**Do not label when:** It evaluates build/playstyle options — use `build_variety`.
**Examples:**
- "Spent two hours in the character creator alone." → `customization`
**Probe:** ≈7 · 4 games.

## 6. Live & meta

### 46. updates

**Definition:** Post-launch patches, content cadence, update quality, support over time.
**Aliases:** updates, patches, roadmap, post-launch support, dev updates, abandoned.
**Label when:** The review evaluates how the game changed or was maintained after launch.
**Do not label when:** It evaluates the developer's ethics/communication directly — use `developer_conduct`.
**Examples:**
- "Two years of free updates and it keeps getting better." → `updates`
**Probe:** ≈8 · 4 games.

### 47. developer_conduct

**Definition:** Studio/publisher behavior, communication, trust, moderation, support attitude, promises.
**Aliases:** developers, publisher, communication, customer support, dev behavior, broken promises.
**Label when:** The review evaluates the people/company behind the game.
**Do not label when:** The issue is only patch cadence — use `updates`.
**Examples:**
- "They promised mod tools for three years and went silent." → `developer_conduct`
**Probe:** ≈10 · 4 games (includes the probe's `customer support` group).

### 48. mods

**Definition:** Mod support, workshop support, modding ecosystem, mod compatibility.
**Aliases:** mods, modding, workshop, Steam Workshop, mod support, community mods.
**Label when:** The review evaluates modding.
**Do not label when:** The review only talks about community behavior — use `community`.
**Examples:**
- "The workshop scene keeps this game alive." → `mods`
**Probe:** ≈9 · 3 games.

### 49. community

**Definition:** Player-base character: friendliness, toxicity, helpfulness, culture.
**Aliases:** community, player base, toxic, friendly players, helpful community.
**Label when:** The review evaluates the social character of players.
**Do not label when:** The issue is cheaters/hackers — use `cheating`.
**Examples:**
- "Most toxic ranked community I've ever met." → `community`
**Probe:** ≈6 · 3 games.

### 50. cheating

**Definition:** Integrity of online play: cheaters, hackers, bots, smurfs, anti-cheat failure.
**Aliases:** cheaters, hackers, bots, smurfs, anti-cheat, exploiters.
**Label when:** The review evaluates unfair online play integrity.
**Do not label when:** "Bots" means NPC/enemy AI — use `ai_behavior`.
**Examples:**
- "Every lobby has a spinbotter; the anti-cheat is asleep." → `cheating`
**Probe:** ≈7 · 3 games.

### 51. multiplayer

**Definition:** General online, PvP, co-op, social, or multiplayer experience.
**Aliases:** online, co-op, PvP, multiplayer, friends, party play.
**Label when:** The review evaluates the multiplayer experience broadly.
**Do not label when:** The issue is specifically matchmaking, cheating, or servers — use those labels. Like `gameplay`, this is a fallback, not an extra label.
**Examples:**
- "With three friends this is the best co-op on Steam." → `multiplayer`
**Probe:** ≈11 · 3 games.

### 52. matchmaking

**Definition:** Player pairing quality, rank balance, queue quality, skill matching.
**Aliases:** matchmaking, queue, ranked match, skill-based matchmaking, SBMM, unbalanced teams.
**Label when:** The review evaluates how players are matched.
**Do not label when:** The issue is server lag/disconnects — use `servers_netcode`.
**Examples:**
- "Every match is a stomp in one direction or the other." → `matchmaking`
**Probe:** ≈2 · 1 game.

## 7. Feel / player experience

### 53. relaxation

**Definition:** Whether the game feels relaxing, cozy, stressful, calming, or tense to play.
**Aliases:** chill, cozy, relaxing, stressful, calming, comfort game.
**Label when:** The review evaluates stress/comfort level.
**Do not label when:** "Vibe" refers more to horror/mood/world tone — use `atmosphere`.
**Examples:**
- "My comfort game after work; nothing ever rushes you." → `relaxation`
**Probe:** ≈25 · 4 games.

### 54. addictiveness

**Definition:** The pull to keep playing; one-more-run/session quality.
**Aliases:** addictive, one more run, hooked, can't stop playing, compulsive.
**Label when:** The review evaluates the game's pull or habit-forming quality.
**Do not label when:** The review evaluates objective replay content — use `replayability`.
**Examples:**
- "'One quick match' cost me a weekend." → `addictiveness`
**Probe:** ≈10 · 5 games.

### 55. pacing

**Definition:** Distribution of action, downtime, story beats, repetition, escalation, and momentum.
**Aliases:** pacing, slow, dragged, rushed, padding, momentum, too much downtime.
**Label when:** The review evaluates rhythm/flow over time — of play or of the narrative. `pacing` owns all pacing-talk; `story` keeps what happens, `pacing` keeps how it flows.
**Do not label when:** The complaint is only that the game is long — use `game_length`.
**Examples:**
- "The middle third drags with padding missions." → `pacing`
**Probe:** ≈1 · 1 game.
