# Gold-set labeling instructions

**Status: GOLD-READY (2026-07-16) — nineteen rulings: seven at the drafting
interview, twelve across four dry-run rounds (unaided passes + consensus
records in `dry_run/round<N>/SHEET.md`). The zero-new-rulings convergence
criterion was retired after round 4 (ruling rate 5 → 3 → 2 → 2: structural
rules stable since round 1; routing precedents are additive and effectively
inexhaustible at 3-review sampling) in favor of the residual-rulings channel
(section 8). Next: the seeded gold draw, then assist pre-annotation.**

| | |
|---|---|
| Instructions version | `gold-instructions-v1` |
| Ontology | `v1` — content hash `481d86add78b92e4fd108b389375954fd7285fa0b0985e7222aefc959ca01ebe` |
| Drafted | 2026-07-16 |
| Annotator of record | Arda (assist model pre-annotates; every label is Arda-reviewed) |

## 1. Purpose and scope

This document is the contract for hand-labeling the gold set — the small,
human-certified reference the rest of M1 leans on. Gold labels serve three
consumers, in order of arrival:

1. **The provider bake-off**: every candidate labeling model is scored against
   gold, so the choice of the production labeler is a measured decision.
2. **Judge calibration (D2)**: the LLM judge is tuned until it agrees with gold,
   then extends gold's authority over unlabeled data.
3. **Classifier evaluation**: the certified agreement numbers in the M1 report.

The design call this document exists to honor (recorded in `core/classify`'s
module docstring): **the human annotator and the machine annotator work from one
contract.** The codebook section below is *generated from the same source the
machine reads* (`src/steamlens/ontology/v1.toml`, rendered by the same code that
builds the classify prompt). An agreement number is only clean when both sides
read the same instructions — so this file never hand-edits the codebook; it
wraps the human-only process around it.

## 2. The unit of labeling

You label one review at a time. A review yields **zero or more aspect
mentions**. Each mention records:

- **aspect** — a codebook label (snake_case, e.g. `combat`), or, when the
  review evaluates a genuine aspect with no honest home in the codebook, the
  reviewer's own short wording for it (1–3 words, e.g. `photo mode`). Never
  force-fit a mention into a nearly-right label. You do not declare
  pinned-vs-candidate — that resolves deterministically from the label string
  downstream (`core/normalize`), same as for the machine.
- **sentiment** — this mention's polarity: `positive`, `negative`, `mixed`, or
  `neutral`. Per mention, independent of the review's thumbs-up/down and of the
  other mentions.
- **evidence** — a short **verbatim** quote from the review text supporting the
  mention. Include it only when a clean supporting span exists; omit it
  otherwise. Never invent, trim inside words, or paraphrase a quote.

**A review with zero mentions is a first-class answer, not a failure** — in the
pilot roughly half of reviews carry no aspect commentary at all.

One review counts once per aspect: if the reviewer praises the combat in three
places, that is one `combat` mention. If the same aspect is evaluated with
conflicting polarity in one review ("combat is great early, terrible late"),
record one mention with sentiment `mixed` — both charges present is exactly
that value's meaning.

**Review updates fold the same way** (ruled 2026-07-16, dry run): an
`UPD:`/`EDIT:` section is ordinary review text. An update that reverses the
verdict on an aspect ("servers were broken; UPD: fixed, great now") gives
that aspect both charges → `mixed`. The trajectory itself — which way the
reviewer moved — is investigation-track material, never gold's; Steam's
`timestamp_updated` field carries that signal structurally.

## 3. The decision procedure

For each review, in order:

1. **Is anything evaluated at all?** An aspect is a property of the game or the
   experience around it — never the reviewer's life or state. Bare verdicts
   ("masterpiece", "10/10", "trash"), jokes, memes, playtime screenshots-in-text,
   and comparisons that name no property → zero mentions.
2. **For each evaluated property, pick the most specific codebook label that
   fits — one evaluated property, one label.** The unit is the property, never
   the grammar: multi-label per review is normal (label every distinct property
   the reviewer evaluates), and a single clause naming two properties ("the
   graphics and soundtrack are beautiful") yields two mentions — `graphics` and
   `music`, both free to quote the same span as evidence. What one property can
   never do is carry two labels: "shooting feels punchy" is `combat`, never
   `combat` + `gameplay` stacked on the same evaluation — the specific label
   wins, because a stacked evaluation would count twice in the aggregates. (And
   the reverse fold: one property praised in three places is still one mention
   — section 2's collapse rule.) The codebook's `label_when` /
   `do_not_label_when` lines are the routing table — when in doubt, read the
   neighbor label they point to before deciding.
3. **No honest home?** Record a candidate with the reviewer's own wording —
   **exactly as written, typos included** (ruled 2026-07-16: "ship bilding"
   stays "ship bilding"). The write path stays exact on both sides of the
   agreement measurement; any typo-clustering the eval needs happens once, on
   the read/scoring side, applied equally to gold and machine output. Demoted
   aspects (section 5) are candidates *by ruling* — never route them to the
   nearest pin.
4. **Attach sentiment per mention.** Neutral is real: a factual mention with no
   polarity ("it has cloud saves") is `neutral`, never forced into a polarity
   and never dropped.
5. **Quote evidence whenever a usable span exists** (ruled 2026-07-16 —
   stricter than the machine's contract, deliberately: the machine's evidence
   is optional because a mandatory quote pushes a model to fabricate one, and
   that failure mode doesn't apply to a human). Copy-paste verbatim — never
   retype (the dry run caught a retyped quote silently drifting to
   "suprisingly"); omit only when the mention is genuinely diffuse (e.g.
   sarcasm spread across the whole review). **Evidence is one continuous
   span, for every mention** — never stitch two spans into one string (dry
   run round 3 caught a two-span join with a rewritten "?" — the joined
   string isn't in the review, which is the eval's definition of
   fabrication). The rule was first stated for `mixed` below; it is general. Evidence is verification material, never an agreement target — the
   machine omitting evidence where gold has one is not scored as a miss.

   **Evidence for `mixed` mentions** (ruled 2026-07-16): evidence is one
   continuous span (the `AspectMention` contract — a single optional string),
   so:
   - Default: the **shortest continuous span containing both charges** —
     "combat is great early but terrible late" quotes whole.
   - When the charges sit far apart (a long review praises early-game combat,
     then paragraphs later criticizes its endgame repetitiveness), the
     containing span balloons into half the review — instead quote the
     **clearer single charge** and accept partial support: for a `mixed`
     mention, evidence for one side is honest.
   - **Never stitch** spans with "…" — the joined string isn't in the review,
     and gold must not contain what the eval counts as fabrication elsewhere.

**Routing rulings from the dry run** (2026-07-16; the machine's TOML picks
these up at the v2 wording batch — see FIXLOG):

- **Memorability attributed to named aspects.** "I don't think I'll ever
  forget its characters and atmosphere" → `characters` / positive +
  `atmosphere` / positive — the named aspects win, with the memorability as
  the polarity carrier. `emotional_impact` is for effect-talk that names no
  subsystem ("this game will stay with me forever").
- **Base-game-vs-DLC content scoping.** "The base game is plenty" evaluates
  content volume → `content_amount` / positive, even when said in a DLC
  discussion; the DLC-policy observation itself is a separate `dlc` mention.
- **Reviewer-folded enumerations.** "The trucks handle well, there are
  accidents, weather conditions and live radio stations that all add to the
  immersion" — the **independently-evaluated test**: a contributor gets its
  own mention only when it carries its own polarity claim. "The trucks handle
  well" evaluates handling → its own mention (`physics`, per the codebook's
  vehicle-handling routing). The bare enumerated contributors (accidents,
  weather, radio) are evaluated only *through* the immersion claim — no
  mentions of their own; they live inside the folded mention's evidence
  (`atmosphere`).
- **Ambiguous referents.** When a phrase supports two readings ("it gives a
  really good rendering" — image quality, or a good rendition of Europe's
  roads?), the surrounding context decides; genuinely undecidable → fold it
  into the adjacent mention it most plausibly supports rather than minting a
  separate mention. In the dry-run review the recreation-of-Europe context
  reads "rendering" as rendition → it supports the `realism` mention, not a
  separate `graphics`.
- **Marketing fidelity** (round 2, 2026-07-16). "Didn't look like half of
  what the trailers had shown" — misrepresentation vs. trailers/marketing is
  a trust charge with a pinned home: `developer_conduct` / negative ("broken
  promises" is in its aliases). No new label; if marketing-fidelity recurs as
  its own cluster in the candidate pool, that's the ordinary promotion path.
  Rider: a summary genre-verdict over a list of concrete complaints ("wasn't
  really a survival game") is the reviewer's conclusion, not a distinct
  evaluated property — unlabeled.
- **In-game exploits** (round 2, 2026-07-16). "Can dupe infinite money" — a
  duplication glitch is a broken mechanic the game permits → `bugs` /
  negative. `cheating` only when the charge is other players wielding
  exploits online; `monetization` never (no real money involved).
- **Absence routes to the owning pin** (round 2, 2026-07-16). A complaint
  that a thing is missing is an evaluation of the system that owns it: "no
  melee weapons" → `combat`; "had no mantle" (a missing vault/climb move) →
  `gameplay`. When the missing thing's system has no pin, the candidate path
  applies as usual: "had a weird exfil system" → candidate `exfil system` /
  negative (worked example 7's pattern).
- **Always-online gating and server decommission** (round 3, 2026-07-16). A
  single-player mode unplayable without online servers is an *access*
  charge → `platform_access` / negative (the DRM / login-required family) —
  not `servers_netcode` (nothing wrong with the connection) and not
  `developer_conduct` by default. `developer_conduct` joins as a second
  mention only when conduct is separately charged ("but wow, this is
  egregiously scummy") — the same concrete-system + conduct pairing as the
  sarcastic mock-thanks case.
- **Anecdotes are not a category** (round 4, 2026-07-16). A narrative
  review gets the ordinary test — no special anecdote rule in either
  direction. Pure narration evaluating no game property → zero mentions
  (the Rust raid story: "cool" praises another player's note, not the
  player-base's character as a property). But an anecdote *carrying* an
  explicit evaluation labels normally: "the community is amazing —
  yesterday a raider rebuilt my base" → `community` / positive, the story
  serving as evidence.
- **Pattern vs. state** (round 4, 2026-07-16, Arda's routing). A charge
  against the post-launch *pattern* ("the constant cycle of nerfs … every
  new league") → `updates` — the practice is the evaluated target, per the
  label-the-concrete-cause precedent in `atmosphere`'s routing. A charge
  against the resulting *state* ("too few viable builds now" → 
  `build_variety`; "after the patch it stutters constantly" →
  `performance`) → the affected system's label.
- **External help vs. the game's own onboarding** (2026-07-17, real pass —
  the first residual ruling; Arda's routing over the assist and the
  recommendation). Tutorials, tips, guides, wikis "out there" — help made by
  players outside the game — evaluate the community's helpfulness →
  `community` ("helpful community" is in its aliases). `learning_curve`
  keeps the game's own entry friction: in-game tutorials and onboarding, how
  hard the game itself is to get into or understand. A learnability claim
  resting entirely on external help ("possible even if you aren't the best
  at games — so many tutorials and tips out there") routes to `community`;
  `learning_curve` joins only when the game's own approachability is
  separately evaluated.
- **`characters` means the authored cast** (2026-07-17, real pass, Arda's
  ruling). Named or central characters, companions, protagonists,
  antagonists — the people the game authors *as people* (the pin's own
  vocabulary: cast, development, companions, relationships). Generic
  NPC-population talk is not `characters`: behavior quality → `ai_behavior`
  ("NPCs walk into walls"); the world feeling inhabited → `world` ("NPCs
  living their own lives"); an unspecified "the NPCs are good" naming no
  property → the ambiguous-referent path (fold into an adjacent mention or
  drop). Trigger case: "the talking people are good" in a 30-minute first
  impression — dropped as undecidable once cast-reading was excluded.
- **Wayfinding and lost-talk** (2026-07-17, real pass, Arda's routing table
  — chosen over an inferred-entry-framing variant because every branch
  requires an explicit trigger in the text). Top-down, first match wins:
  - Named layout or spatial cause → `level_design`
  - Named map, marker, waypoint, or HUD cause → `ui`
  - Named objective, mission, or quest instruction cause → `quest_design`
  - Explicit onboarding or early-learning framing ("at first," "when I
    started," "the beginning was confusing," "hard to get into") →
    `learning_curve`
  - No branch fires → the ambiguous-referent path: fold into the adjacent
    mention it most plausibly supports, or drop. Trigger case: "sometimes
    you don't have a clue where to go" (30-minute review, no cause, no
    entry framing — "sometimes" states recurrence, not onboarding) →
    dropped.
- **Discount advice is not a value charge** (2026-07-17, real pass, Arda's
  ruling). Steam's frequent-sale culture makes "get it on a discount"
  purchase-*timing* advice, not a worth indictment — the negative inference
  is unsafe. Bare wait-for-sale advice → `price_value` / **neutral**
  (value-domain talk with no polarity; section 4 forbids forcing or
  dropping it). An explicit worth-charge decides polarity as usual: "not
  worth full price" / "overpriced" → negative; "worth every penny" /
  "a great purchase this sale" → positive; and surrounding context can
  still supply the charge (the ordinary context rule). Trigger case: "Fun
  game, should be acquired during discount" → `price_value` / neutral.
- **`gameplay` is the mechanics, not the pastime** (2026-07-17, real pass,
  Arda's ruling — supersedes worked example 4's original answer). `gameplay`
  labels when the play *system* is the evaluated subject — core loop,
  mechanics, moment-to-moment structure — signaled by a system-noun or a
  named play activity: "the gameplay is fun," "the core loop gets stale,"
  "managing the customers and stock levels was very enjoyable."
  Enjoyment-of-playing with no system named is a bare verdict **whether or
  not it is anchored to playing**: "fun game," "it was fun," "fun to play,"
  "I enjoyed playing" → zero mentions (rule 2) — the verdict axis already
  has a home in the thumbs, and an aspect number that counts unattributed
  enjoyment restates the recommendation rate. "Fun" stays an ordinary
  polarity carrier on any named property ("combat is fun" → `combat`).
  Experiential adjectives with their own pins keep their homes ("relaxing
  to play" → `relaxation`, "can't stop playing" → `addictiveness`): the
  asymmetry is principled — relaxation names a specific mood property;
  fun-enjoyment is the verdict itself. Related: `fun_factor` as a possible
  v2 pin is parked in ONTOLOGY_PRUNING.md with today's evidence.
- **Worth-talk routes by its frame** (2026-07-17, real pass, Arda's ruling —
  clarifies the discount-advice ruling's "explicit worth-charge" leg).
  `price_value` requires worth-talk that evaluates value-for-money in a
  monetary or purchase frame: "not worth full price," "worth every penny,"
  "worth getting," "$32 more than it should be." Two look-alikes stay out:
  (1) bare "not worth it" in an effort/time/hassle context is the
  reviewer's summary conclusion over their complaints — unlabeled, per the
  summary-verdict rider of the marketing-fidelity ruling ("EA's stupid
  decisions make it not worth it in the long run" caps an access rant the
  way "wasn't really a survival game" capped its list); (2) money-rhetoric
  capping another system's failure ("I'm literally unable to play… so It's
  a waste of money," "Refunded") is consequence talk — the mention belongs
  to the failing system, and worked example 7 already treats "Refunded"
  this way. Test: does the claim weigh price against content, or restate a
  complaint/conclusion in money words?
- **Price-conditional endorsements are `mixed`** (2026-07-17, real pass,
  Arda's ruling). "Worth it *if* it's on a discount / at $X" asserts worth
  inside the condition and withholds it outside — the restriction is a
  stated position on full price, so both charges are present →
  `price_value` / mixed ("probably still worth the price if its on a
  discount" in a 5/10 review). The neighbors it must not blur into: bare
  discount advice with no worth-language stays neutral (the discount-advice
  ruling); an unconditional worth-charge keeps its polarity; a concessive
  comparison to an external ideal stays one-charged (section 4) — a
  concession frames, a price-conditional partitions. The explicit two-half
  form ("buy on sale, don't bother paying 40 bucks") is mixed by the plain
  both-charges test.
- **Candidate labels name the property, not the charge** (2026-07-17, real
  pass, Arda's ruling — closing a gap the exact-wording rule doesn't cover:
  it fixes the words' *source*, not the span boundary). From the reviewer's
  own words, the label is the noun-core naming the evaluated property;
  modifiers that carry the evaluation stay in sentiment and evidence —
  "crazy amount of miss-able achievements … suck" → candidate
  `achievements` / negative (a label like `missable achievements` bakes the
  charge in, the candidate-space version of a pin called `clunky_combat`).
  Modifiers that *constitute* the property stay: "photo mode," "exfil
  system," "achievement hunting" (the hunting is the evaluated activity).
  Quality-candidates are untouched (worked example 9): `creative` has no
  noun-core because the quality is the property. Test: if deleting the
  modifier deletes the complaint, it's evaluation — out of the label.
  Noun-core labels also cluster better at promotion review.
- **Hardness routes by its stated source** (2026-07-17, real pass, Arda's
  framing — the wayfinding table's shape applied to difficulty-talk).
  Reviewers rarely evaluate the *amount* of challenge; they evaluate where
  it comes from, and the stated source picks the label, polarity from the
  charge: demands real strategy/tactics → `combat` or the named system
  (often praise); enemy smarts → `ai_behavior`; number tuning — damage
  sponges, "10x health," "your damage is just low," spikes → `balance`;
  punishing authored spaces → `level_design`; entry hardness with
  onboarding framing → `learning_curve` (its own rule). A bare
  challenge-level claim with no stated source stays `difficulty`, sentiment
  as charged — and hard-as-praise is real: "it's hard, that's the point" is
  `difficulty` / positive, "I was never challenged" is `difficulty` /
  negative. This unifies routing the codebook already does piecemeal
  (balance's difficulty-spike alias, ai_behavior's dumb-enemies example);
  nothing previously decided changes.
- **The evidence horizon: text alone** (round 3, 2026-07-16). Label from the
  review text and nothing else — the machine's horizon is the human's
  horizon (`build_classify_prompt` receives texts only; no game name, no app
  id). World knowledge may resolve *vocabulary* ("dupe" = duplication
  glitch) but never *referents*: knowing a game is celebrated for its 2D art
  must not turn generic "Visuals and audio 10/10" into `art_style` — the
  text says generic visuals-praise → `graphics`. Labels are a function of
  (review text, codebook) only — batch-mates and game identity are
  accidents, not evidence. If eval disagreements ever cluster on
  style-vs-fidelity, game-aware context is a deliberate v2 experiment added
  to *both* sides of the contract, never a gold-side shortcut.

## 4. Sentiment vocabulary

The four values and their boundaries (source: ontology global rule 6 and the
`Sentiment` contract):

- `positive` / `negative` — the mention carries one polarity.
- `mixed` — *this mention* carries both charges ("fun but repetitive" about one
  aspect; or conflicting evaluations of one aspect across the review, folded).
- `neutral` — factual, no polarity ("it has cloud saves"); **and lukewarm
  aspect verdicts** ("the story is okay, I guess") — ruled 2026-07-16: lukewarm
  is not `mixed`, because `mixed` means both charges are actually present, and
  "okay"-talk carries neither. The gradient to watch: a hedge ("…, I guess")
  makes neutrality unambiguous; a bare "combat is fine" sits nearer the
  boundary but still routes `neutral` unless surrounding context supplies a
  real charge in either direction.

**Sarcasm and irony** (ruled 2026-07-16): label the evaluated aspect with the
**intended** sentiment, quoting evidence as written. "10/10 servers, crashed
only twice a minute" → `servers_netcode` / negative. The inversion runs both
ways — mock-negative praise is real too: "yeah the game is too bad, I can't
drop it after 1000 hours" → positive. So sarcasm is never a mechanical
flip-to-negative; read what the reviewer means. These are deliberately kept in
gold — sarcasm is where classifier quality gaps concentrate, so gold must
contain the cases that expose them.

**Concessive comparisons are not charges** (ruled 2026-07-16, dry run):
"while this isn't the total Microsoft Flight Simulator level recreation I
would have liked, it … feels surprisingly realistic" carries one real charge
— the positive. A tempered expectation ("not as much as I'd hoped, but…") is
framing, not a negative evaluation; `mixed` requires both charges actually
present (section 2's meaning), never a concession plus praise.

## 5. Negative space — what does NOT get a pin

Two distinct kinds, treated differently:

**No label at all** (not even a candidate):
- Bare verdicts, however emphatic ("best game ever", "GAM IS GUD!").
- Reviewer's life/state with no game property evaluated ("I was depressed and
  this helped").
- Pure comparisons with no property named ("better than GTA V").
- Vague vibes with no referent ("good vibes").

**Candidate, never the nearest pin** — the four demoted-by-ruling aspects
(evidence and reopen conditions in `ONTOLOGY_PRUNING.md`):
- **camera** — view/camera feel talk. Not `controls`.
- **accessibility** — accessibility options/settings talk. Not `ui`.
- **localization** — language support, translation, which languages are voiced.
  Not `voice_acting` (pipeline-scope demotion: English-only sampling).
- **grind** — repetitive-required-effort complaints. Not `progression`, not
  `game_length` ("the complaint is repetitive required work rather than sheer
  duration").

Record these as candidates with the reviewer's wording, sentiment attached, like
any candidate.

## 6. The codebook

*Generated from `v1.toml` (ontology `v1`, hash above) by the same renderer the
classify prompt uses (`scripts/render_gold_codebook.py`). Regenerate on any
ontology version bump — never hand-edit this section.*

<!-- CODEBOOK_RENDER_START -->
*Ontology `v1`, content hash `481d86add78b92e4fd108b389375954fd7285fa0b0985e7222aefc959ca01ebe`.*

Global rules:

1. Aspect, not mood. An aspect is a property of the game or the experience around it — never the reviewer's life or state ("I was depressed and this helped" → no label unless a game property is evaluated).
2. Bare verdicts get no label. "Masterpiece", "10/10", "trash" with no subject → zero aspects. A zero-aspect review is a first-class result (~46% of reviews in the probe).
3. Multi-label is normal. Label every distinct aspect a review evaluates; one clause can only carry one label — pick the most specific that fits.
4. Child-shaped mentions take the parent. The aliases and "label when" lines route; sub-flavors ("endgame progression") are never their own label.
5. Not listed ≠ not recorded. A genuine aspect with no pinned home is a CANDIDATE: keep the reviewer's own wording as a free-form label. Never force-fit into the nearest pinned label.
6. Sentiment attaches per mention (positive / negative / mixed / neutral), independent of the review's thumbs-up. Neutral is a real outcome: a factual mention with no polarity ("it has cloud saves") is recorded as neutral, never forced into a polarity and never dropped.
7. Labels are snake_case identifiers; display names are a downstream concern.
8. Categories are organizational only — never classification targets.

## play

### gameplay
Definition: Moment-to-moment play and core mechanics, when no more specific label applies.
Also known as: gameplay loop, core mechanics, mechanics
Label when: The reviewer evaluates the basic act of playing.
Do not label when: They mention combat, controls, progression, level design, or another specific system — use that label. `gameplay` is the fallback for play-talk, not an extra label on top of a specific one.
Examples:
- "The gameplay is fun but gets repetitive." → `gameplay`
- "Shooting feels punchy and the bosses are great." → `combat`, not `gameplay`

### combat
Definition: Fighting systems, encounters, weapons, abilities, enemies as combat opponents.
Also known as: fighting, combat system, gunplay, melee, battles, encounters
Label when: The review evaluates fighting or combat encounters.
Do not label when: The complaint is about enemy intelligence specifically — use `ai_behavior`. Unfair tuning of weapons/classes — use `balance`.
Examples:
- "Turn-based combat with real tactical depth." → `combat`
- "Enemies just stand there while you shoot them." → `ai_behavior`, not `combat`

### controls
Definition: Input feel, responsiveness, handling, keybinds, controller support.
Also known as: handling, input, responsiveness, keybinds, controller support, movement feel, game feel
Label when: The reviewer talks about how it feels to control the game — input in general.
Do not label when: The issue is menus/HUD — use `ui`. "Vehicle handling" as simulation behavior — use `physics`. The clunky/smooth feel of a named system ("combat feels clunky") — label that system; `controls` is for input generally, not system feel.
Examples:
- "Controls are floaty and the deadzone settings don't help." → `controls`
- "Inventory is a nightmare to navigate." → `ui`, not `controls`

### difficulty
Definition: How hard the game is after the player understands it.
Also known as: challenge, hard, easy, difficulty options
Label when: The reviewer evaluates challenge level.
Do not label when: The issue is learning/onboarding — use `learning_curve`. Unfair tuning or spikes — use `balance`.
Examples:
- "Brutally hard but always fair." → `difficulty`
- "Act 3 suddenly triples the enemy damage for no reason." → `balance`, not `difficulty`

### learning_curve
Definition: How easy or hard it is to learn, understand, or get into the game.
Also known as: onboarding, tutorials, beginner friendly, hard to get into, confusing at first
Label when: The review focuses on entry friction or learning.
Do not label when: The game is simply hard — use `difficulty`.
Examples:
- "Takes 20 hours before it clicks; the tutorial explains nothing." → `learning_curve`

### progression
Definition: Advancement systems: leveling, unlocks, skill trees, perks, gear progression, ranks. Includes endgame progression and pacing of advancement.
Also known as: leveling, unlocks, skill tree, perks, advancement, progression system
Label when: The review evaluates how the player advances.
Do not label when: The complaint is purely the repetitive effort required to progress ("grind wall") — grind talk is deliberately unpinned; record it as a CANDIDATE, keeping the reviewer's wording.
Examples:
- "The skill tree actually changes how you play." → `progression`
- "You repeat the same three missions to level anything." → CANDIDATE (grind), not `progression`

### balance
Definition: Fairness and tuning of mechanics, weapons, classes, enemies, economy, difficulty spikes, or progression.
Also known as: balancing, overpowered, underpowered, nerf, buff, unfair, broken meta, difficulty spike
Label when: The review says something is unfair, overtuned, undertuned, or poorly balanced.
Do not label when: They only say the game is hard — use `difficulty`.
Examples:
- "One weapon type invalidates every other build." → `balance`

### player_choice
Definition: Whether choices matter; agency, consequences, branching decisions.
Also known as: player agency, choices matter, consequences, dialogue choices, branching
Label when: The reviewer evaluates meaningful decisions or lack of them.
Do not label when: They are talking about builds/playstyles — use `build_variety`.
Examples:
- "Your choices genuinely change act two." → `player_choice`
- "So many viable ways to build your character." → `build_variety`, not `player_choice`

### exploration
Definition: Discovering places, secrets, routes, locations, hidden content.
Also known as: discovery, secrets, open world exploration, roaming, exploration rewards
Label when: The player evaluates the act/reward of exploring.
Do not label when: The issue is the map/level structure itself — use `level_design`.
Examples:
- "Every cave hides something worth finding." → `exploration`

### level_design
Definition: Layout and structure of levels, maps, dungeons, arenas, routes, spaces.
Also known as: map design, level layout, dungeon design, arena design, stage design
Label when: The review evaluates authored spaces.
Do not label when: They only say they like discovering things — use `exploration`. The world as setting/content — use `world`.
Examples:
- "Interconnected maps that loop back on themselves brilliantly." → `level_design`

### quest_design
Definition: Quality, structure, variety, and objectives of quests or missions.
Also known as: missions, quests, side quests, objectives, tasks, mission design
Label when: The review evaluates quest/mission structure.
Do not label when: The review evaluates plot — use `story`. Sheer volume of quests/things to do — use `content_amount`.
Examples:
- "Side quests are all fetch-and-return filler." → `quest_design`
- "The main questline's twist floored me." → `story`, not `quest_design`

### build_variety
Definition: Variety of viable builds, playstyles, classes, strategies, weapons, or approaches.
Also known as: playstyle variety, build diversity, class variety, different ways to play
Label when: The review evaluates whether players can approach the game in different ways.
Do not label when: It is only about cosmetic customization — use `customization`.
Examples:
- "Stealth, guns-blazing, or full netrunner — all viable." → `build_variety`

### replayability
Definition: Whether the game rewards replaying or returning after completion/failure.
Also known as: replay value, longevity, repeat runs, replayable, keeps me coming back
Label when: The review evaluates long-term return value.
Do not label when: The review says the game is addictive in a psychological-pull sense — use `addictiveness`.
Examples:
- "Three playthroughs and I'm still finding new content." → `replayability`
- "One more run turns into 3 a.m. every night." → `addictiveness`, not `replayability`

### ai_behavior
Definition: Quality of enemy, NPC, teammate, or bot behavior.
Also known as: enemy AI, NPC behavior, bot teammates, companion AI, pathfinding
Label when: The review evaluates non-player behavior.
Do not label when: "Bots" means cheaters/fake players in online matches — use `cheating` or `multiplayer`.
Examples:
- "NPCs walk into walls and forget you exist." → `ai_behavior`

### physics
Definition: Physical simulation, collisions, movement physics, vehicle handling, object interactions.
Also known as: physics, collision, ragdoll, vehicle handling, simulation, floaty movement
Label when: The review evaluates simulation/physical behavior.
Do not label when: "Handling" just means input feel — use `controls`.
Examples:
- "Ball physics are pixel-perfect and predictable." → `physics`

## narrative

### story
Definition: Plot, narrative arc, major events, ending.
Also known as: narrative, plot, ending, final act, story arc
Label when: The reviewer evaluates what happens in the story.
Do not label when: The issue is prose/dialogue quality — use `writing`. Rhythm/momentum complaints, narrative or play alike ("drags", "rushed") — use `pacing`, which owns all pacing-talk.
Examples:
- "The ending recontextualizes the whole game." → `story`
- "The plot is fine but every line of dialogue is cringe." → `writing` (and `story` only if the plot is separately evaluated)

### writing
Definition: Quality of prose, dialogue, script, jokes, lines, text, or written delivery.
Also known as: dialogue, script, writing quality, jokes
Label when: The reviewer evaluates how the story/dialogue is written.
Do not label when: They evaluate the plot itself — use `story`. Voice performance — use `voice_acting`.
Examples:
- "Sharpest dialogue I've read in years." → `writing`

### lore
Definition: World backstory, history, mythology, setting background.
Also known as: lore, backstory, world history, mythos, codex
Label when: The review evaluates background knowledge/world history.
Do not label when: They evaluate the explorable world itself — use `world`.
Examples:
- "The codex entries are better than most novels." → `lore`

### characters
Definition: Cast depth, likability, development, companions, relationships.
Also known as: character development, companions, cast, relationships
Label when: The reviewer evaluates characters as people/entities.
Do not label when: They evaluate voice performance — use `voice_acting`. A romance-systems evaluation (options, dating mechanics) is deliberately unpinned — record it as a CANDIDATE (romance), not as `characters`.
Examples:
- "Every companion feels like a real person." → `characters`
- "The romance options are the best part." → CANDIDATE romance, not `characters`

### voice_acting
Definition: Voice performance quality.
Also known as: voiceover, voice acting, VA, voice performance, narration voice
Label when: The review evaluates spoken performance.
Do not label when: They evaluate the written dialogue — use `writing`. Language/translation support (which languages are voiced/subtitled, translation quality) is deliberately unpinned while the pipeline is English-only — record as a CANDIDATE.
Examples:
- "The lead actor carries every scene." → `voice_acting`

### emotional_impact
Definition: Whether the game is moving, memorable, scary, sad, powerful, or emotionally affecting.
Also known as: emotional depth, moving, heartbreaking, memorable, powerful, touching
Label when: The review emphasizes emotional effect on the player — it scared, moved, or stayed with them.
Do not label when: The game sustains a scary/tense/cozy mood as a property of its presentation — use `atmosphere` (`atmosphere` = the mood the game holds; `emotional_impact` = the player being affected). The feeling is calm/stress while playing — use `relaxation`.
Examples:
- "I cried twice and I'm not ashamed." → `emotional_impact`

## presentation_world

### graphics
Definition: Visual fidelity and technical image quality.
Also known as: visuals, visual quality, textures, lighting, resolution, fidelity
Label when: The review evaluates technical visual quality.
Do not label when: They evaluate aesthetic identity — use `art_style`.
Examples:
- "Textures pop in and the lighting is last-gen." → `graphics`
- "It's not photorealistic, but the watercolor look is gorgeous." → `art_style`, not `graphics`

### art_style
Definition: Art direction, aesthetic identity, visual taste, style coherence.
Also known as: aesthetic, artwork, art direction, visual style, stylized
Label when: The review evaluates how the game looks artistically.
Do not label when: They talk about raw fidelity — use `graphics`.
Examples:
- "The neon-noir aesthetic never gets old." → `art_style`

### animation
Definition: Character, combat, facial, movement, or environmental animation quality.
Also known as: animations, facial animation, movement animation, janky animation
Label when: The review evaluates motion/animation.
Do not label when: The issue is control responsiveness — use `controls`. "Jank" as broken behavior — use `bugs`; janky motion belongs here.
Examples:
- "Facial animations are stiff in every cutscene." → `animation`

### music
Definition: Music and soundtrack.
Also known as: soundtrack, OST, score, tracks, music
Label when: The review evaluates music.
Do not label when: The review evaluates sound effects/audio feedback — use `sound_design`.
Examples:
- "The OST alone is worth the price." → `music`

### sound_design
Definition: Non-music audio: sound effects, ambience, audio feedback, mixing, impact sounds.
Also known as: audio, SFX, sound effects, ambience, weapon sounds, footsteps, audio feedback
Label when: The review evaluates sound that is not mainly music.
Do not label when: The review evaluates soundtrack/OST — use `music`.
Examples:
- "Every weapon sounds like it means it." → `sound_design`

### atmosphere
Definition: Mood, tone, tension, coziness, horror feeling, general sensory mood.
Also known as: atmosphere, mood, tone, ambiance, immersive atmosphere, immersive
Label when: The review evaluates the feeling the game sustains. Bare "immersion" praise about being pulled in routes here (settled ruling, 2026-07-10).
Do not label when: "Immersion" is broken by bugs/performance/UI — label the concrete cause. Bare "good vibes" with no referent is a vague verdict — no label. Believability of the world as a place — use `world`. "It genuinely scared/moved me" as personal effect — use `emotional_impact`.
Examples:
- "The fog, the music cues, the dread — the mood never breaks." → `atmosphere`

### world
Definition: The built world or setting as content and as a whole: places, setting identity, world density, world coherence, world beauty/impressiveness, and world liveliness — an inhabited world where life visibly goes on around the player.
Also known as: setting, world, worldbuilding, world design, world feels alive, living world, empty world, scenery, landscapes
Label when: The review evaluates the world/setting itself — its internal consistency and lived-in coherence as a fictional place, the world as a whole ("beautiful world", "impressive world"), or how alive/inhabited it feels (city life, NPCs living their own lives, things happening without the player).
Do not label when: They evaluate backstory/history — use `lore`. Authored level layouts — use `level_design`. Fidelity to real life (accurate simulation, historical accuracy) — use `realism`. Rendering/image quality — use `graphics`; art direction — use `art_style`; the world as a place being beautiful routes here. The quality of NPC behavior itself (dumb, broken, robotic NPCs) — use `ai_behavior`; the world feeling alive as an overall property routes here.
Examples:
- "Night City feels alive in a way no open world has." → `world`
- "Driving through the Alps at sunset is breathtaking." → `world`, not `graphics`
- "NPCs teleport and forget you in two seconds." → `ai_behavior`, not `world`

### realism
Definition: How realistic or true-to-life something is — visuals, animations, mechanics, behavior, simulation, or the experience as a whole. Cross-cutting: applies inside fantastical settings too (realistic lighting in a fantasy world counts).
Also known as: realistic, realism, authenticity, simulation realism, historically accurate, realistic graphics, lifelike
Label when: The evaluated property is realisticness/trueness to life, whatever it attaches to — graphics, mechanics, world behavior.
Do not label when: They evaluate physics mechanics specifically — use `physics`. Internal consistency/coherence of a fictional world as a lived-in place — use `world`. Visual quality praised without realism being the point ("looks amazing") — use `graphics`.
Examples:
- "The routes, the tolls, the fatigue rules — it's the real job." → `realism`
- "Rain on the windshield looks absolutely real." → `realism`, not `graphics`

## technical

### performance
Definition: Runtime smoothness and optimization: FPS, stutter, loading, hardware demands.
Also known as: optimization, FPS, frame rate, stutter, loading times, runs well, runs poorly
Label when: The review evaluates how well the game runs.
Do not label when: The game crashes/freezes — use `stability`. Online lag/desync — use `servers_netcode`.
Examples:
- "Constant stutter on a 4080 is embarrassing." → `performance`
- "Crashes to desktop every hour." → `stability`, not `performance`

### stability
Definition: Crashes, freezes, save corruption, launch failures, hard technical failures.
Also known as: crash, freeze, softlock, save corrupted, won't launch, black screen
Label when: The review describes severe failure states.
Do not label when: It is a non-fatal glitch or broken quest — use `bugs`.
Examples:
- "Lost a 40-hour save to corruption." → `stability`

### bugs
Definition: Broken behavior: glitches, broken quests, broken mechanics, visual bugs, scripting errors.
Also known as: bug, glitch, broken quest, broken mechanic, jank, bugged
Label when: The game behaves incorrectly but not necessarily as a hard crash/freeze.
Do not label when: It is mainly low FPS/stutter — use `performance`. Broken motion specifically — use `animation`.
Examples:
- "The quest marker points at a door that never opens." → `bugs`

### ui
Definition: Menus, HUD, inventory screens, readability, navigation, interface friction.
Also known as: UI, UX, menus, HUD, interface, inventory UI, readability, menu navigation, settings menu, options menu
Label when: The review evaluates interface design.
Do not label when: The review evaluates input responsiveness — use `controls`.
Examples:
- "Four submenus to change one setting." → `ui`

### servers_netcode
Definition: Online technical quality: servers, lag, disconnects, desync, netcode, online stability.
Also known as: servers, netcode, lag, ping, desync, disconnects, rubberbanding
Label when: The review evaluates online infrastructure/connection quality.
Do not label when: The issue is bad player matching — use `matchmaking`.
Examples:
- "Desync decides more matches than skill does." → `servers_netcode`

### platform_access
Definition: Ports, launchers, account requirements, DRM, Steam Deck/Linux support, region/platform access.
Also known as: port, launcher, account requirement, DRM, Steam Deck, Linux, console port, login required
Label when: The review criticizes access/friction outside the core game itself.
Do not label when: The issue is pricing by region — usually `price_value` (regional pricing events are the investigator's territory, not the ontology's).
Examples:
- "Forcing a third-party account on a paid game is insulting." → `platform_access`

## content_value

### content_amount
Definition: Volume of things to do: modes, quests, maps, items, activities, variety of content.
Also known as: amount of content, content, lots to do, lack of content, content variety
Label when: The review evaluates how much content exists.
Do not label when: It only discusses hours to finish — use `game_length`. Quality/structure of the quests rather than their volume — use `quest_design`.
Examples:
- "A hundred hours in and the activity list keeps growing." → `content_amount`

### game_length
Definition: Time to finish, total hours, campaign length, short/long duration.
Also known as: length, campaign length, hours, too short, too long, completion time, time sink
Label when: The review evaluates duration or the time the game demands.
Do not label when: The complaint is repetitive required work rather than sheer duration — grind talk is deliberately unpinned; record it as a CANDIDATE. The hours pile up because of voluntary pull — use `addictiveness`.
Examples:
- "Twelve hours and the credits rolled. At full price." → `game_length`

### price_value
Definition: Whether the game is worth the asking price.
Also known as: price, value, worth it, not worth, sale, full price, overpriced
Label when: The reviewer evaluates value-for-money.
Do not label when: The issue is microtransactions or the monetization model — use `monetization`.
Examples:
- "Even at full price this is a steal." → `price_value`
- "The game is fine; the $20 skins are not." → `monetization`, not `price_value`

### monetization
Definition: How the game charges beyond purchase: MTX, loot boxes, battle pass, F2P economy, pay-to-win.
Also known as: microtransactions, MTX, loot boxes, crates, battle pass, pay to win, F2P model
Label when: The review evaluates monetization systems.
Do not label when: It only says the base price is too high — use `price_value`.
Examples:
- "Battle pass FOMO in a full-priced game." → `monetization`

### dlc
Definition: DLC quality, DLC policy, expansions, missing content sold separately.
Also known as: DLC, expansion, season pass, paid content, downloadable content
Label when: The review evaluates DLC specifically.
Do not label when: The issue is general microtransactions — use `monetization`.
Examples:
- "The expansion is better than the base game." → `dlc`

### customization
Definition: Appearance, identity, character creation, cosmetic personalization, personalization systems.
Also known as: customization, character creation, cosmetics, skins, outfits, personalization
Label when: The review evaluates customization options.
Do not label when: It evaluates build/playstyle options — use `build_variety`.
Examples:
- "Spent two hours in the character creator alone." → `customization`

## live_meta

### updates
Definition: Post-launch patches, content cadence, update quality, support over time.
Also known as: updates, patches, roadmap, post-launch support, dev updates, abandoned
Label when: The review evaluates how the game changed or was maintained after launch.
Do not label when: It evaluates the developer's ethics/communication directly — use `developer_conduct`.
Examples:
- "Two years of free updates and it keeps getting better." → `updates`

### developer_conduct
Definition: Studio/publisher behavior, communication, trust, moderation, support attitude, promises.
Also known as: developers, publisher, communication, customer support, dev behavior, broken promises
Label when: The review evaluates the people/company behind the game.
Do not label when: The issue is only patch cadence — use `updates`.
Examples:
- "They promised mod tools for three years and went silent." → `developer_conduct`

### mods
Definition: Mod support, workshop support, modding ecosystem, mod compatibility.
Also known as: mods, modding, workshop, Steam Workshop, mod support, community mods
Label when: The review evaluates modding.
Do not label when: The review only talks about community behavior — use `community`.
Examples:
- "The workshop scene keeps this game alive." → `mods`

### community
Definition: Player-base character: friendliness, toxicity, helpfulness, culture.
Also known as: community, player base, toxic, friendly players, helpful community
Label when: The review evaluates the social character of players.
Do not label when: The issue is cheaters/hackers — use `cheating`.
Examples:
- "Most toxic ranked community I've ever met." → `community`

### cheating
Definition: Integrity of online play: cheaters, hackers, bots, smurfs, anti-cheat failure.
Also known as: cheaters, hackers, bots, smurfs, anti-cheat, exploiters
Label when: The review evaluates unfair online play integrity.
Do not label when: "Bots" means NPC/enemy AI — use `ai_behavior`.
Examples:
- "Every lobby has a spinbotter; the anti-cheat is asleep." → `cheating`

### multiplayer
Definition: General online, PvP, co-op, social, or multiplayer experience.
Also known as: online, co-op, PvP, multiplayer, friends, party play
Label when: The review evaluates the multiplayer experience broadly.
Do not label when: The issue is specifically matchmaking, cheating, or servers — use those labels. Like `gameplay`, this is a fallback, not an extra label.
Examples:
- "With three friends this is the best co-op on Steam." → `multiplayer`

### matchmaking
Definition: Player pairing quality, rank balance, queue quality, skill matching.
Also known as: matchmaking, queue, ranked match, skill-based matchmaking, SBMM, unbalanced teams
Label when: The review evaluates how players are matched.
Do not label when: The issue is server lag/disconnects — use `servers_netcode`.
Examples:
- "Every match is a stomp in one direction or the other." → `matchmaking`

## player_experience

### relaxation
Definition: Whether the game feels relaxing, cozy, stressful, calming, or tense to play.
Also known as: chill, cozy, relaxing, stressful, calming, comfort game
Label when: The review evaluates stress/comfort level.
Do not label when: "Vibe" refers more to horror/mood/world tone — use `atmosphere`.
Examples:
- "My comfort game after work; nothing ever rushes you." → `relaxation`

### addictiveness
Definition: The pull to keep playing; one-more-run/session quality.
Also known as: addictive, one more run, hooked, can't stop playing, compulsive
Label when: The review evaluates the game's pull or habit-forming quality.
Do not label when: The review evaluates objective replay content — use `replayability`.
Examples:
- "'One quick match' cost me a weekend." → `addictiveness`

### pacing
Definition: Distribution of action, downtime, story beats, repetition, escalation, and momentum.
Also known as: pacing, slow, dragged, rushed, padding, momentum, too much downtime
Label when: The review evaluates rhythm/flow over time — of play or of the narrative. `pacing` owns all pacing-talk; `story` keeps what happens, `pacing` keeps how it flows.
Do not label when: The complaint is only that the game is long — use `game_length`.
Examples:
- "The middle third drags with padding missions." → `pacing`
<!-- CODEBOOK_RENDER_END -->

## 7. Worked examples

Real reviews from the B4 pilot dev slice (Stardew Valley, Cyberpunk 2077 —
these six review ids are excluded from the gold set, so they can teach here
without leaking into it).

1. `"best game ever"` → **zero mentions.** Bare verdict, no property evaluated.
2. `"farm"` → **zero mentions.** A word, not an evaluation.
3. `"GAM IS GUD!"` → **zero mentions.** Bare verdict.
4. `"I play this game pretty often, its extremely fun and relaxing to play
   before bed :)"` → one mention:
   - `relaxation` / positive / evidence: "relaxing to play before bed"
   ("Its extremely fun" is enjoyment-of-playing with no system named — a
   bare verdict under the gameplay-is-the-mechanics ruling (section 3,
   2026-07-17; this example originally carried a `gameplay` mention, and
   the v1 machine still labels it that way until the v2 wording batch —
   expected disagreement, not a defect. "Relaxing" keeps its mention:
   it names a pinned experiential property.)
5. `"great game and great story"` → one mention: `story` / positive /
   evidence: "great story". ("Great game" alone is a bare verdict — it adds no
   second mention.)
6. `"Way much better than back when I played GTA SA and GTA V. It has the same
   level such as Red dead redemption 2."` → **zero mentions.** Comparative
   praise naming no property of *this* game.

And two crafted contrast cases:

7. *"Shooting feels punchy but the loot system killed it for me. Refunded."*
   → `combat` / positive / "Shooting feels punchy"; and a mention for the loot
   complaint — most specific honest home (`progression` if it's about gear
   advancement; a candidate like `loot system` if it isn't). "Refunded" alone
   is verdict, not aspect.
8. *"The photo mode is fantastic, I spent hours composing shots with it."*
   → candidate `photo mode` / positive. Genuine aspect, no pinned home.
9. *"I can still say that this is one of the most creative, weird and unique
   games I've ever played."* (dry-run slice, Disco Elysium — gold-excluded
   like the dev slice, so it can teach here) → candidate `creative` /
   positive. **A candidate can be a quality, not just a feature**: originality
   is a genuinely evaluated property with no pinned home. Contrast the bare
   verdict: "best game ever" names no property; "most creative I've played"
   names one. (Added after the dry run, where the feature-only example left
   this path feeling unlicensed.)

## 8. Process and provenance

**The assist workflow.** A strong assist model pre-annotates each gold review
using *these same instructions*; Arda reviews every label — accept, correct, or
delete — and adds what the assist missed. The final label is Arda's in every
case. Corrections are marked so assist-vs-final disagreement stays measurable
(it is a free estimate of how hard the task is).

**Assist-model exclusion.** The assist model is named in the gold set's
provenance record and is **banned from the provider bake-off's candidate pool**
— a candidate scored against labels it helped write would inherit its own
biases as ground truth.

**The residual-rulings channel** (ruled 2026-07-16, replacing the dry-run
convergence criterion). During the real pass, an assist-vs-annotator
disagreement or a flagged uncertainty triggers the same one-question
mini-interview the dry runs ran; a new precedent lands in section 3's
routing rulings and section 9's ledger, dated. A precedent that could
change an already-labeled item triggers a **targeted recheck of that
pattern only** — never a blanket relabel; structural rules (sentiment
vocabulary, evidence policy, the fold) are frozen — a structural change
would invalidate prior labels and therefore forces an explicit
instructions-version bump and a full relabel decision, taken deliberately
or not at all.

**Dev-slice exclusion.** The six B4 pilot review ids
(`probes/captures/classify_pilot/dev_slice.json`) never enter the gold set.

**Dry-run exclusion.** The dry-run acceptance-test reviews — **every round's
manifest**, at `eval/gold/dry_run/round<N>/manifest.json`
(`gold_excluded_ids()` in `scripts/draw_gold_dry_run.py` collects them all
plus the dev slice) — likewise never enter the gold set: this document is acceptance-tested, and
possibly revised, against them; same leakage logic as the dev slice. (Drawn
fresh 2026-07-16: the dev slice couldn't serve as dry-run material once its
six reviews became section 7's worked examples — answers printed in the doc.
Rounds repeat under the convergence rule: a round settling zero new rulings
means the doc has converged.)

**Non-English skip-and-redraw** (ruled 2026-07-16). The pipeline is
English-only by recorded scope, so gold's population is English reviews —
stated, not silent: a non-English review in the draw is skipped, replaced by
the next review in the seeded draw order, and the skip is logged in the draw
manifest. Boundary: a mostly-English review with stray non-English tokens or
gamer-universal fragments ("gg ez") stays in — skip only when the evaluative
content itself is unreadable.

**Effectively-empty skip** (ruled 2026-07-17, real pass). A review whose
text carries no visible characters — Unicode format characters or
whitespace only — is skipped with cause `empty_text`, same mechanism as the
non-English skip. This is not a new population decision: the draw's
eligibility already excludes empty text ("with nothing to read there is
nothing to label"); a U+200E-only review slipped that filter because plain
`strip()` doesn't remove format characters. The near-empty stay in: a
review with any visible content ("g", ".", "👍") is natural-mix noise and
labels honestly (usually zero mentions).

**Every gold record carries:** review id + app id, **the review text itself**
(ruled 2026-07-16: gold is self-contained — evals must run in CI, which never
sees the corpus; texts are public Steam posts, republished here with full
provenance), the mention list, the instructions version, the ontology version +
content hash, annotator, assist model name, and the date of the labeling pass.

## 9. Open rulings — the interview agenda

Contested rules deliberately not decided in this draft; each gets settled
one-at-a-time with Arda, and the ruling lands back in the section it belongs to:

1. ~~Lukewarm verdicts about an aspect~~ — **RULED 2026-07-16: `neutral`**
   (applied in section 4).
2. ~~Sarcasm/irony~~ — **RULED 2026-07-16: intended sentiment, both
   directions** (applied in section 4).
3. ~~Candidate wording normalization~~ — **RULED 2026-07-16: exact reviewer
   wording, typos included** (applied in section 3).
4. ~~Evidence-span policy for humans~~ — **RULED 2026-07-16: quote whenever a
   usable span exists** (applied in section 3).
5. ~~Non-English reviews in the draw~~ — **RULED 2026-07-16: skip-and-redraw,
   logged, with the mostly-English boundary** (applied in section 8).
6. ~~Gold record storage~~ — **RULED 2026-07-16: self-contained, texts
   committed with provenance** (applied in section 8).
8. ~~Memorability attributed to named aspects~~ — **RULED 2026-07-16 (dry
   run): the named aspects win; `emotional_impact` only when no subsystem is
   named** (applied in section 3; TOML wording rides the v2 batch).
9. ~~Concessive comparisons~~ — **RULED 2026-07-16 (dry run): not a charge —
   the praised side's polarity stands** (applied in section 4).
10. ~~UPD/EDIT review updates~~ — **RULED 2026-07-16 (dry run): fold like
    ordinary text — reversal → `mixed`** (applied in section 2). The
    trajectory instinct (do updated reviews trend positive/negative/hold?)
    parked as investigator-track material in the stream's IDEAS.md.
11. ~~Reviewer-folded enumerations~~ — **RULED 2026-07-16 (dry run): the
    independently-evaluated test — a contributor with its own polarity claim
    gets its own mention; bare enumerated contributors stay inside the folded
    mention as evidence** (applied in section 3).
12. ~~Ambiguous referents~~ — **RULED 2026-07-16 (dry run): context decides;
    genuinely undecidable → fold into the adjacent mention it most plausibly
    supports, never mint a separate mention** (applied in section 3).
13. ~~Marketing fidelity~~ — **RULED 2026-07-16 (dry run round 2): trailer /
    marketing misrepresentation → `developer_conduct` (no new label; "broken
    promises" is its alias), and a summary genre-verdict over a complaint
    list stays unlabeled** (applied in section 3).
14. ~~In-game exploits~~ — **RULED 2026-07-16 (dry run round 2): "can dupe
    infinite money" → `bugs` (a permitted duplication glitch is a broken
    mechanic); `cheating` only for other players wielding exploits;
    `monetization` never** (applied in section 3).
15. ~~Absence complaints~~ — **RULED 2026-07-16 (dry run round 2): absence
    routes to the owning pin ("no melee weapons" → `combat`; "no mantle" →
    `gameplay`); no pin → the candidate path as usual ("weird exfil system"
    → candidate)** (applied in section 3).
16. ~~Always-online gating~~ — **RULED 2026-07-16 (dry run round 3):
    single-player gated behind decommissionable servers → `platform_access`;
    `developer_conduct` as a second mention only when conduct is separately
    charged** (applied in section 3).
17. ~~The evidence horizon~~ — **RULED 2026-07-16 (dry run round 3): text
    alone, both annotators — world knowledge resolves vocabulary, never
    referents; game-aware context only ever as a deliberate two-sided v2
    experiment** (applied in section 3).
18. ~~Pattern vs. state~~ — **RULED 2026-07-16 (dry run round 4, Arda's
    routing over the recommendation): charge against the post-launch
    pattern → `updates`; charge against the resulting state → the affected
    system** (applied in section 3).
19. ~~Anecdote reviews~~ — **RULED 2026-07-16 (dry run round 4): not a
    category — the ordinary test applies; pure narration with no evaluated
    game property → zero mentions, an anecdote carrying an explicit
    evaluation labels normally with the story as evidence** (applied in
    section 3).
20. ~~External help resources (guides, wikis, tutorials "out there")~~ —
    **RULED 2026-07-17 (real pass, the first residual ruling — Arda's
    routing over the assist and the recommendation): community-made help
    evaluates the community's helpfulness → `community`; `learning_curve`
    keeps the game's own onboarding/entry friction** (applied in section 3;
    machine-side wording rides the v2 batch). Draft-wide recheck at ruling
    time found no other affected mention (10 learning_curve/community
    drafts scanned, all correctly on their side of the boundary).
21. ~~`characters` scope: cast vs. NPC population~~ — **RULED 2026-07-17
    (real pass, Arda's ruling): `characters` is the authored cast (named/
    central figures, companions); generic NPC-population talk routes to
    `ai_behavior` (behavior), `world` (liveliness), or the ambiguous-
    referent path** (applied in section 3; machine-side wording rides the
    v2 batch). Draft-wide recheck at ruling time: 13 characters mentions
    scanned, all cast-shaped except the trigger case (dropped).
22. ~~Wayfinding complaints~~ — **RULED 2026-07-17 (real pass, Arda's
    routing table): named cause → its system (layout → `level_design`,
    map/markers → `ui`, objectives → `quest_design`); explicit onboarding
    framing → `learning_curve`; top-down, first match wins; no trigger →
    fold or drop** (applied in section 3; machine-side wording rides the
    v2 batch). Draft-wide recheck at ruling time: one wayfinding-shaped
    span in all drafts — the trigger case itself (dropped).
23. ~~Discount advice~~ — **RULED 2026-07-17 (real pass, Arda's ruling):
    bare wait-for-sale purchase-timing advice is not a negative value
    charge → `price_value` / neutral; explicit worth-charges keep their
    polarity; context can supply the charge** (applied in section 3;
    machine-side wording rides the v2 batch). Draft-wide recheck at ruling
    time: 15 price_value drafts, 5 sale-flavored — two bare-advice flips
    to neutral (batches 01, 05), two qualified charges left to
    adjudication (batches 03, 11), one already correct (batch 19).
24. ~~Fun-talk and `gameplay`'s scope~~ — **RULED 2026-07-17 (real pass,
    Arda's ruling, confirmed with costs named): `gameplay` requires the
    play system as evaluated subject (system-noun or named activity);
    enjoyment-of-playing with no system named is rule-2 negative space,
    anchored or not — "fun to play" included; "fun" remains a polarity
    carrier on named properties; pinned experiential adjectives keep their
    homes** (applied in section 3; worked example 4 rewritten — the one
    printed-answer change of the pass; machine-side wording rides the v2
    batch, and until then fun-flavored reviews are a KNOWN high-volume
    human-vs-machine gap that the bake-off report must name). Draft-wide
    recheck at ruling time: 42 gameplay drafts — ~24 bare-fun deletions,
    ~10 system-nouned keeps, ~6 judgment cases; the per-batch list is
    `eval/gold/workbook/RECHECK-ruling24.md`. Alternatives considered:
    fold-all-fun-into-gameplay (rejected: aggregate degenerates into the
    recommendation rate), surface-anchor rule "fun to play → gameplay"
    (rejected: the verb anchor attributes nothing — playing is the default
    consumption mode), new `fun_factor` pin (deferred to v2:
    ONTOLOGY_PRUNING.md holds the evidence and the reopen condition).
25. ~~"Worth it" outside a price frame~~ — **RULED 2026-07-17 (real pass,
    Arda's ruling): `price_value` needs a monetary/purchase frame weighing
    price against content; effort-context "not worth it" is a summary
    conclusion (unlabeled, the ruling-13 rider); money-rhetoric capping
    another system's failure ("waste of money" after "unable to play,"
    "Refunded") belongs to the failing system** (applied in section 3;
    machine-side wording rides the v2 batch). Draft-wide recheck at ruling
    time: all 15 price_value drafts monetary-framed — zero edits; the
    ruling ratifies review 225044464's no-add.
26. ~~Effectively-empty reviews in the draw~~ — **RULED 2026-07-17 (real
    pass, process ruling): visible-character emptiness (format chars /
    whitespace only) → skip with cause `empty_text`, consuming the game's
    next reserve like a non-English skip; near-empty visible content stays
    in the natural mix** (applied in section 8). Trigger: a U+200E-only
    review (batch 02); draw-wide scan found it to be the only one of 500
    drawn rows. Root defect (non-Unicode-aware emptiness test in the draw
    eligibility filter) parked in the stream FIXLOG for future draws and
    steam_client ingestion.
27. ~~Price-conditional endorsements~~ — **RULED 2026-07-17 (real pass,
    Arda's sentiment call): "worth it if discounted" partitions the price
    axis — both charges present → `price_value` / mixed; the hedge
    ("probably") is NOT the mixed-maker — hedges alone weaken or
    neutralize, only the conditional supplies the second charge;
    distinguished from bare advice (neutral), unconditional charges
    (their polarity), and concessive comparisons (one charge)** (applied
    in section 3; machine-side wording rides the v2 batch). Draft recheck
    at ruling time: one edit (batch 03 positive → mixed); batch 11's
    explicit form and batch 09's counterfactual already mixed; batch 19's
    discounted-purchase report stays positive.
28. ~~Candidate label extraction~~ — **RULED 2026-07-17 (real pass, Arda's
    ruling over the initial pushback): the candidate label is the
    reviewer's noun-core for the evaluated property; charge-carrying
    modifiers stay in sentiment/evidence ("missable achievements" →
    `achievements` / negative); property-constituting modifiers and bare
    quality-candidates stand** (applied in section 3; machine-side wording
    rides the v2 batch). Draft-wide recheck at ruling time: one edit (the
    trigger case); the other 14 candidate labels already conform.
29. ~~Difficulty-talk routing~~ — **RULED 2026-07-17 (real pass, Arda's
    framing): hardness with a stated source routes to the source's label
    (strategy → `combat`/named system, enemy smarts → `ai_behavior`,
    number tuning → `balance`, spaces → `level_design`, onboarding →
    `learning_curve`); bare level claims stay `difficulty` with honest
    polarity, hard-as-praise included** (applied in section 3;
    machine-side wording rides the v2 batch). Draft-wide recheck at
    ruling time: 12 difficulty/balance drafts, 10 conforming, 2 flagged
    to adjudication (batches 14, 23).

## 10. The slice — size and composition

Ruled 2026-07-16: **the natural mix, never distorted.** The zero/non-zero
boundary is the single most discriminating classifier behavior measured so far
(the bare-verdict filter: 62% vs 31% zero-share between two models on identical
reviews), and it is only measurable against gold that carries the population's
honest base rate (~half zero-aspect).

**Target size: ~250 reviews** (floor: 150). Larger than the original ~150
sketch on Arda's call: the zero-aspect half of a natural draw is
seconds-per-review to confirm, so a bigger draw costs far less effort than its
headline count suggests — and the aspect-bearing half is what buys mention-level
signal.

**The growth path** (never the first resort): if mention-level coverage proves
thin after the first pass, gold extends by a second, explicitly-marked
aspect-bearing stratum — the natural core stays untouched, and metrics that
need honest base rates use the natural core only.
7. ~~Zero-mention share of the slice~~ — **RULED 2026-07-16: natural mix,
   never distorted** (applied below in section 10).
