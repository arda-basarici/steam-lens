# Gold instructions — dry-run acceptance test (round 4)

**Rules of the run.** Label the reviews below using `eval/gold/INSTRUCTIONS.md`
and nothing else — no pilot captures, no chat, no codebook TOML. Work top to
bottom; note the rough time per review. The friction notes are the point of
this exercise: every place you had to reread, guess, or wish the doc said
more is a finding, even if you resolved it yourself.

**Recording a mention** — one bullet per mention, in this shape:

    - `aspect_label` / sentiment / "verbatim evidence" (or: no usable span)

Evidence is **copy-pasted, never retyped** (a round-1 finding). A zero-mention
review gets the single line `Zero mentions.` instead.

---

## Review 1 — Undertale (review id `227194693`)

```text
i love undertale and deltarune but at the part where dino kids supposed to help you up the ledge in chapter 1 he wasnt there please help meh tobyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy

























































































































good game doh
```

### Labels

(your mention bullets here)

### Friction notes

I dont see any aspect mentioned here. can be talking about a bug, but not clear. and we dont take good game it self directly.

---

## Review 2 — Path of Exile (review id `219829651`)

```text
One of the greatest ARPGs I have played and its in my top 5 greatest games of all time. HOWEVER, due to having a job, responsibilities, relationships etc. this game is no longer for me and I am not the target audience anymore. The game has a staggering amount of systems and interactions that it requires a massive knowledge of it to be successful and be rewarded.
This game is not for the casual gamer if you are thinking to do any of the end game bosses as you need to have a guide from content creators and grind for the currency needed to power up your build. The game has an amazing endgame map system that changes every few years and a lot of content to explore/farm. The devs do listen and lately been adding QoL improvements.
The constant cycle of nerfs however IMO have decreased viable builds and sometimes it depends if the new gems/skills they introduce every new league is busted. I have enjoyed my time with this game but I will move on to POE 2/D4 as at least for now its approachable for casuals.

TLDR: If you want a game to no life and be rewarded with your time invested with a steep learning curve then this game is for you. If you are a casual then be prepared to miss out on endgame activities unless you devote more time.
```

### Labels

exploration / positive / The game has an amazing endgame map system that changes every few years and a lot of content to explore/farm.

learning_curve / mixed / The game has a staggering amount of systems and interactions that it requires a massive knowledge of it to be successful and be rewarded. If you want a game to no life and be rewarded with your time invested with a steep learning curve then this game is for you. If you are a casual then be prepared to miss out on endgame activities unless you devote more time.

developer_conduct / positive / The devs do listen and lately been adding QoL improvements.

updates / negative / The constant cycle of nerfs however IMO have decreased viable builds and sometimes it depends if the new gems/skills they introduce every new league is busted.

### Friction notes

I said learning curve mixed, because review repeats many time it is not for me, it say not for casual players but you can like it many times.

---

## Review 3 — Rust (review id `226948562`)

```text
Some guy just offline raided me, saw i had nothing to my name, then promptly reconstructed the base. He sorted everything i had and gave me 5k scrap. Even left me a cool little note. (i lost all the scrap to a pack of wolves 30 seconds later).
```

### Labels

(your mention bullets here)

### Friction notes

this is an anectode about the game, there is no review in it.

---

## Overall

*(Filled after the review discussion, 2026-07-16. The per-review sections
above are Arda's unaided pass, preserved untouched.)*

**Doc verdict: GOLD-READY — and the convergence criterion retired.** The
round produced two new rulings (INSTRUCTIONS §9 entries 18–19: pattern vs.
state — Arda's routing over the recommendation — and anecdotes-are-not-a-
category), making the cross-round rate 5 → 3 → 2 → 2: structural rules have
not moved since round 1, while routing precedents arrive at a steady ~2 per
round — additive, narrow, forcing no relabeling. Read: at 3-review sampling
of a ~50-label boundary space, zero-ruling rounds are likely unreachable —
the criterion was wrong-shaped, not the doc unstable. Ruled (Arda,
2026-07-16): stop the rounds, declare gold-ready, and route residual
precedents through the real pass's built-in channel — assist-vs-annotator
disagreements and flagged uncertainty trigger the same mini-interview, new
precedents append to §3/§9 dated, and any precedent touching already-labeled
items triggers a targeted pattern recheck.

**Consensus labels** (post-discussion; diffs from the unaided pass noted):

- Review 1 (Undertale) — **+** `bugs` / negative ("at the part where dino
  kids supposed to help you up the ledge in chapter 1 he wasnt there" — a
  concrete malfunction description; the help-plea wrapper doesn't unmake a
  bug report). The two bare verdicts correctly drew nothing unaided.
- Review 2 (Path of Exile) — `updates` / negative (Arda's pattern-vs-state
  routing, ruling 18; evidence trimmed to its own sentence);
  `learning_curve` / mixed (evidence re-cut to the TLDR pair — the unaided
  span stitched paragraph 1 to the TLDR, the round's evidence defect);
  `developer_conduct` / positive (unaided — the positive register, clean);
  **+** `level_design` / positive + `content_amount` / positive (the
  endgame-map sentence, two properties, shared span; replaces unaided
  `exploration`); **+** candidate `grind` / negative (the currency-grind
  clause — §5's demoted list, missed unaided).
- Review 3 (Rust) — **zero mentions** (unaided call upheld; became ruling
  19: anecdotes are not a category, the ordinary test applies).

**Process finding:** fourth round, fourth evidence-transfer defect (stitch
across paragraphs) — the assist-pre-fill decision is beyond revisiting.
Sheet-discipline nit: zero-mention reviews should carry the literal line
"Zero mentions." rather than an untouched placeholder (rounds 1 and 4 left
placeholders that read as unfinished work).
