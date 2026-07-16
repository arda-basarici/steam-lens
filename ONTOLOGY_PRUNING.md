# Ontology pruning ledger — the B1 pass (v1-draft → v1)

**RATIFIED 2026-07-15** — `version = "v1"`, 51 pins, all tests green. The pass ran
in one session: interview-mode rulings over corpus-complete evidence (49 games,
~4,900 reviews, ~7,500 mentions; flash + calibrated flash-lite instruments).
Demoted: camera, accessibility, localization, grind. Challenged and kept:
servers_netcode. Additions considered and declined: puzzles, save system,
achievements, humor. This ledger is now the pass's closed record; reopen
conditions per entry still stand and fire at a version bump, not an edit.

Working ledger for the pruning pass, opened 2026-07-15. Every demotion is recorded
with its evidence, the merge alternatives considered, and the concrete condition
that would reverse it — so drip evidence arriving later (the extension probe walks
the remaining corpus at 20 requests/day) can be tested against each ruling instead
of silently superseding it. Distills into DESIGN.md at ratification; until then this
file is the single place a pruning decision lives.

**The demotion criterion, final form** (settled 2026-07-15 when "candidates can
carry it qualitatively" was probed as a reason to drop more): the question is
never "could the report cover this without a number" — that is true of every
aspect and, followed through, deletes the product (the certified numbers ARE the
product; a pin also buys aggregation under one label and D1/D2 certification,
which free-form candidates structurally can't have). The question is "does the
talk CLUSTER on the games where the number matters." Demote when it clusters
nowhere (camera 1/4,900; grind never >2 per game); keep when corpus-wide-thin
rows spike exactly in their genre (matchmaking: 16 total but 11 in Overwatch 2
alone — that survey sample mints the number its buyers come for).

Process: interview mode — evidence table presented, one aspect per question, Arda
rules, the edit lands in `src/steamlens/ontology/v1.toml` immediately and
`uv run pytest -q` re-validates. Evidence = open-extraction mention counts
(probes/captures/aspect_vocab/ + aspect_vocab_ext/), conservatively hand-mapped onto
the pinned labels; counts are floors. The bar: "pin = I want a certified number
here," priced honestly — a pin costs ~130 prompt tokens per batch call forever plus
classifier routing burden; C2's evidence floor already hides thin aggregates from
display, so display clutter is never the reason.

## Demoted (talk flows to candidate-space via normalize unless noted)

### camera — demoted 2026-07-15
- **Evidence:** 0 mentions in 1,200 reviews / 12 games — including the targeted
  test, 100 Elden Ring reviews (souls-likes being the genre where camera is the
  canonical complaint).
- **Second-instrument check (same day):** the flash-lite run replicated the Elden
  Ring zero, and Dark Souls III produced camera(1) — the first mention in ~1,900
  reviews (~0.05%). A near-zero, not a perfect zero; nowhere near reopening.
- **Merge alternative considered:** fold into `controls` (widen its definition to
  cover view/camera feel). Rejected: with zero observed talk there is nothing to
  merge — widening would muddy `controls` for no gain. Candidate-space is the
  honest home.
- **Neighbor rewrites:** none needed (no other row routed to it).
- **Reopens if:** Dark Souls III (queued first in the drip) or later corpus games
  surface a real camera cluster, or production candidates accumulate camera-talk.

### accessibility — demoted 2026-07-15
- **Evidence:** 2 mentions in ~1,600 reviews ("arachnophobia settings" PoE,
  "accessibility" FFXIV). At that rate no game clears the evidence floor — the pin
  paid tokens for a number that would never display.
- **Merge alternative considered:** fold into `ui` (options/settings surface).
  Rejected: near-zero talk, and accessibility is a values-signal, not an interface
  quality — a muddying merge. Corpus limitation noted honestly: no
  accessibility-flagship title (e.g. TLOU-class) exists in the 50 games.
- **Neighbor rewrites:** `localization`'s do_not_label_when (subtitle presentation
  options) → candidate-space. (That row was itself demoted next.)
- **Reopens if:** production candidates cluster accessibility-talk on some game, or
  the corpus gains a title whose review discourse is accessibility-heavy.

### localization — demoted 2026-07-15
- **Evidence:** 1 mention in ~1,600 ("russian voiceover") — but starved BY
  CONSTRUCTION: the pipeline is English-only per DESIGN's evaluation scope, and
  localization complaints concentrate in non-English reviews.
- **The deciding argument** (beyond rarity): a certified localization number
  measured only on English reviews samples exactly the population least affected —
  a systematic bias the certified-number promise can't carry. Pipeline-scope
  demotion, NOT a judgment that localization doesn't matter.
- **Merge alternative considered:** none sensible — no neighbor means "language
  support."
- **Neighbor rewrites:** `voice_acting`'s do_not_label_when (which languages are
  voiced) → candidate-space with the English-only rationale inline.
- **Reopens if:** SteamLens goes multilingual — re-pinning belongs in that version
  bump, not before.

## Open questions (ruling pending)

### grind — demoted 2026-07-15 (ruled after the full corpus)
- **Final evidence:** 15 mentions / ~4,900 reviews (~0.3%) across 11 games — the
  broadest THIN row: the word trickles everywhere, clusters nowhere (Darkest
  Dungeon, the corpus's grindiest game, gave 2). No game's grind number would ever
  clear the evidence floor.
- **Ruling (Arda):** demote rather than merge into `progression` — candidates keep
  recording the trickle with reviewer wording; a real cluster in production
  promotes it back at a version bump. Understanding confirmed at the ruling:
  candidates are recorded from day one but carry no certified number until pinned;
  bought labels stay keyed to the old ontology version (re-labeling is a re-buy).
- **Neighbor rewrites:** `progression` and `game_length` now route
  repetition-as-required-effort to candidate-space explicitly.
- **Reopens if:** production candidates cluster grind-talk on some game
  (MMO/live-service reviews at survey scale are the likely place).

### The evidence trail below is the pre-ruling record:
(kept for the reasoning history — the softening from "demote" to "toss-up" and why)

### grind — recommendation SOFTENED to genuine toss-up (2026-07-15, second instrument)
- **Evidence:** a persistent trickle, not a zero — ~9 mentions in ~1,900 reviews
  (~0.5%) spread across genres: orig(1), BF2042(1), Phasmophobia(1), FFXIV(1),
  DS3 grinding(1) + achievement grinding(2), Goat Simulator grind(2). The targeted
  genre tests still came back near-empty (Path of Exile 0/100, FFXIV 1/100), and
  ~0.5% ≈ 2 mentions on a 400-review survey — under any sane evidence floor.
- **Why this differs from camera:** camera-talk essentially doesn't exist
  (1/1,900); grind-talk exists everywhere, thinly. Demotion is still defensible on
  floor-clearance; keep is defensible on ubiquity-in-trace; the merge keeps a home:
- **Merge alternative (the live one):** widen `progression` to own
  repetition-as-required-effort ("grind wall" → progression, negative). Preserves a
  pinned home and a certified number that includes tedium; the price is a muddier
  `progression` (design quality and tedium mixed in one aggregate).
- **Structural cost of plain demotion:** two neighbors route INTO grind
  (`progression`, `game_length`) — both rewrite to candidate-space.
- **Reopens if:** Darkest Dungeon (in the lite sweep) or production candidates show
  a real cluster.

### Second-instrument calibration (2026-07-15) — how lite evidence is read
gemini-2.5-flash-lite is closed to new keys; gemini-3.1-flash-lite (15 RPM /
500 RPD free) ran instead, capturing to `probes/captures/aspect_vocab_lite/`.
Calibration on Elden Ring vs the flash capture: lite has a weaker bare-verdict
filter (zero-share 31% vs 62%; excess = vague labels like "overall experience",
"game") — but those labels never map to a pinned aspect, so the conservative
mapping discards them, and the REAL-aspect readings track flash closely (~91 vs 88
mapped-relevant mentions, same head vocabulary). Ruling: lite counts are valid for
existence-testing through the same mapping; lite-sourced evidence is flagged by
instrument; counts are never presented as same-instrument continuations of flash.
Both demotion-critical zeros (camera, grind) replicated on the second instrument.

### Full-corpus resolution (2026-07-15, late session) — every held row RESCUED
The lite sweep completed the whole usable corpus the same night (49 games, ~4,900
reviews, ~6,900 mentions; flash 12 games + lite 38, ER overlap as calibration).
Each held row got its genre test and cleared it — all keep, evidence-backed:
- **pacing — ~31 across 17 games** (Disco Elysium 4, Tavern Master 4, Persona 5
  Royal 3, DDLC 3): recurs everywhere story-shaped; the `story`→`pacing` routing
  boundary stands.
- **physics — ~14** (Goat Simulator, Garry's Mod, Surgeon Simulator delivered ~11
  in one pass): the balance/matchmaking rescue pattern — starved only until its
  genre got sampled.
- **ui — ~30 across 21 games** (user interface: EU4 3, Warsim 2; ui: Democracy 3
  ×3, Persona, Disco…): universal row confirmed.
- **sound_design — ~30 across 20 games** (audio 13, sound design 7, sound effects
  3): the music/sound pair stands.
- **level_design — ~26 across 17 games** (level design 16: VVVVVV 4, Gollum 3,
  DS3 2, Hollow Knight 2; map design 5). Mapping note: VVVVVV's "level editor /
  user levels" cluster (~6) is user-generated-content talk — NOT mapped here.
- Watch-list rows all confirmed by their genre tests: writing ~85/21 games (Disco
  13), player_choice ~32/13 (Mass Effect, Wasteland 3, Undertale), voice_acting
  ~30/15 (Gollum 8 — negative sentiment lives in a real cluster), emotional_impact
  26/11 (Edith Finch 7, DDLC 7), realism ~20/11 (Democracy 3 ×6 — policy realism),
  relaxation ~24/8 (excluding Darkest Dungeon's "stress mechanic" ×5, which is a
  game system, not player relaxation — mapping trap logged).

## Addition candidates surfaced by the full corpus — RULED 2026-07-15: none pinned
The completeness scan (high-frequency labels with no pinned home, vague mass and
surface variants excluded) left four genuine clusters:
- **puzzles — ~23 across 8 games** (Portal 2, Hollow Knight, Noita, …): the
  strongest case. Same evidence magnitude as ui/pacing, which kept their pins —
  consistency argued a `puzzle_design` pin; the genre-mechanics policy
  (farming/fishing/driving stayed candidates) argued against.
- **save system — 13 across 9 games**: cross-genre technical/design aspect,
  currently homeless.
- **achievements — 16 across 15 games**: completionism talk; broadest spread of
  the four.
- **humor — 19 across 5 games**: partially covered (`writing` owns jokes); Goat
  Simulator-style situational comedy is not writing.
Genre-concentrated clusters staying candidates per policy: platforming (13/3
games), stealth (13/3), plus the long game-specific tail.

**Ruling (Arda, same exchange as grind):** puzzles NOT pinned — the genre-mechanics
policy holds for all four clusters; they live in candidate-space and promote at a
version bump if production data clusters. Understanding settled at the ruling:
candidate mentions carry wording + per-mention sentiment + provenance, so
"players talk about X, here's how they feel" is answerable from the pool — but
whether/how reports SURFACE candidates is an open compose-stage (M3) design fork,
constrained by two-track honesty: no smuggled numbers ("frequently",
"negative-leaning"); qualitative shapes (example quotes, explicitly uncertified
topic lists) are the candidates' report form if any.

### servers_netcode — challenged and KEPT 2026-07-15 (Arda proposed dropping; ruled keep)
- **Honest evidence:** ~21/9 games with exactly ONE real cluster (FFXIV ~8, an
  actual DDoS-wave era); Helldivers 2 — the most famous server-meltdown launch —
  gave ZERO in its uniform sample; Rust marginal.
- **Why keep anyway:** the row is EVENT-SHAPED, and uniform-lifetime probes
  systematically dilute event-shaped rows (Helldivers' server hell was two weeks
  of its lifetime). The product samples WINDOWS; a window during an outage is
  wall-to-wall server talk — Phasmophobia's update-backlash sample (updates: 43)
  demonstrates the mechanism. Also: three neighbors route online-infra pain here
  (performance, matchmaking, multiplayer) — demotion would certify offline
  stutter while uncertifying online lag, the same player pain split by
  architecture.
- **Lesson recorded:** the clustering criterion needs a time-axis caveat —
  event-shaped aspects (servers, updates, stability-at-launch) cluster in TIME,
  not just in genre; judge them against windowed sampling, not uniform probes.

## Watch list (keeps its pin; drip could still surprise)
- `player_choice`, `writing`, `voice_acting`, `emotional_impact`, `realism`,
  `relaxation` — strong-or-moderate on the original slate but untested by the
  extension games so far; their genre tests (Disco Elysium, Undertale, Mass Effect
  LE, Edith Finch, DDLC) are queued in the drip.
- Emergent unpinned cluster to watch: **early-access-state** (~7 mentions,
  Phasmophobia) — currently splits between `updates` and candidates; a pin proposal
  needs more than one game's evidence.
- Mapping trap recorded: Satisfactory's "optimization" = factory optimization (the
  play activity), NOT runtime performance — conservative mapping keeps it out of
  `performance`.

## Evidence provenance
- Original probe: `probes/captures/aspect_vocab/` (5 games × 100, 2026-07-09).
- Extension: `probes/captures/aspect_vocab_ext/` (gap slate + FFXIV + Satisfactory
  so far; GAMES list in `probes/aspect_vocab_ext_probe.py` holds the full queued
  corpus with per-step rationale comments).
- Free-tier quota: 20 requests/day = ~6 games/day; resume makes the daily rerun a
  stateless drip (`python probes/aspect_vocab_ext_probe.py`).

---

## Post-ratification reopen candidates (fire at a version bump, never an edit)

### fun_factor — addition candidate for v2 (2026-07-17, from the gold pass)
- **Origin:** ruling 24 of the gold instructions (fun-talk and `gameplay`'s
  scope). Arda proposed a `fun_factor` pin for the industry-standard notion;
  deferred to v2 because a mid-pass pin addition breaks the hash-pinned v1
  contract on both sides (gold provenance + the classify prompt).
- **Evidence at parking time:** 28 of 42 `gameplay` assist drafts on the gold
  slice (250 reviews) were bare fun-talk — the single most common evaluative
  pattern in the natural mix. Counter-evidence: the aspect-vocab probes found
  fun/vague-verdict labels dominating the UNMAPPED mass corpus-wide — present
  everywhere, clustering nowhere, which is the demotion criterion's textbook
  fail (a near-uniform positive share restates the recommendation rate).
- **The v2 trial it must pass:** the same per-game clustering bar every pin
  faced, measured on anchored-vs-bare fun-talk separately — the ruling-24
  boundary makes that split measurable for the first time (gold now encodes
  it, and the candidate pool records bare-fun wording verbatim).
- **Reopens if:** survey-scale candidates show fun-talk clustering on specific
  games once bare verdicts are filtered, OR the M1 report's zero-share reading
  suggests the verdict axis carries per-game structure the thumbs miss.
