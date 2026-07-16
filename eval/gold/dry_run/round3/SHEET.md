# Gold instructions — dry-run acceptance test (round 3)

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

## Review 1 — NBA 2K23 (review id `189121108`)

```text
I understand that the online servers for these games can’t stay up forever. That’s a fact I can accept and live with. But why in the hell is MyCareer, a single-player game mode where you and only you are playing against CPU players, an online game mode? Why can’t we continue to play a SINGLE-PLAYER GAME MODE after the servers get decommissioned?

I guess on the bright side, MyLeague is still available to play. But wow, this is egregiously scummy.
```

### Labels

developer_conduct / negative / Why can’t we continue to play a SINGLE-PLAYER GAME MODE after the servers get decommissioned. this is egregiously scummy.

### Friction notes

I am aware of the situation the reviewer talking about here. I have experience on this. this is not a directly server issue, but ı wasnt sure how to label this.

---

## Review 2 — Darkest Dungeon (review id `225419924`)

```text
Visuals and audio 10/10 - by far the most immersive game I’ve ever played.
Gameplay is also great — it’s very strategic, not only during battles but also when managing the Hamlet. RNG can sometimes screw you over, so the whole game is about minimizing the chances of that happening. Even simple encounters can be dangerous, so you always have to be careful.
```

### Labels

art_style / positive / Visuals and audio 10/10.
sound_design / positive / Visuals and audio 10/10.
gameplay / positive / Gameplay is also great
atmosphere / positive / by far the most immersive game I’ve ever played.

rng / neutral / RNG can sometimes screw you over, so the whole game is about minimizing the chances of that happening.
difficulty / neutral / Even simple encounters can be dangerous, so you always have to be careful.
strategy / positive / it’s very strategic, not only during battles but also when managing the Hamlet.

### Friction notes

RNG can sometimes screw you over, so the whole game is about minimizing the chances of that happening. Even simple encounters can be dangerous, so you always have to be careful. - this is commentary over rng / diffulcuty but not negative, or it doesnt praise.

visuals doesnt mean grahpics here, but ı know that because ı know the game, it has characteristic 2d art style. I m not sure how model can distinguish this type of reviews.

---

## Review 3 — No Man's Sky (review id `223074927`)

```text
Every year I see that this game has had huge major updates and then I will play and find out all the content is more of a sidequest than anything, which would be fine if this game had decent content outside of that.

It's overused at this point but when people say a mile wide and an inch deep they really mean it.

I individually like how there is base building and power systems and automation and exploration but most of the time it is just a chore to get through.

It feels like doing anything in the game is just a side project, I explore the world and make bases and then all I have is more bases and systems seen (this is my favorite part of the game though).

I automate gathering a resource and all I have is infinite of that resource that I never really needed much of anyway.

I smuggle contraband and make more money than I'll ever use in like less than an hour.

I find and upgrade ships and freighters and never use them.
```

### Labels

updates / negative / Every year I see that this game has had huge major updates and then I will play and find out all the content is more of a sidequest than anything, which would be fine if this game had decent content outside of that.

content_amount / mixed / when people say a mile wide and an inch deep they really mean it.

gameplay / mixed / I individually like how there is base building and power systems and automation and exploration but most of the time it is just a chore to get through.

automation / mixed / I automate gathering a resource and all I have is infinite of that resource that I never really needed much of anyway.

### Friction notes

content_amount mixed maybe negative, it is hard to pinpoint a evidence, almost all of the review is about this issue actaully.

---

## Overall

*(Filled after the review discussion, 2026-07-16. The per-review sections
above are Arda's unaided pass, preserved untouched.)*

**Doc verdict: NOT YET CONVERGED — two new rulings** (INSTRUCTIONS §9
entries 16–17: always-online gating → `platform_access` with
`developer_conduct` only when conduct is separately charged · the evidence
horizon is the text alone — world knowledge resolves vocabulary, never
referents). Round 4 follows per the convergence rule. Also this round: the
never-stitch rule promoted from the `mixed`-only bullet to the general
evidence rule (a placement fix, evidenced by the round's stitched-evidence
slip), and two clean *applications* of existing rules settled in discussion
(the `strategy` elaboration folds into `gameplay` per anti-stacking; the
litany tail gets its own mentions per the independently-evaluated test).
Ruling trend across rounds: 5 structural → 3 routing → 2 (one routing, one
foundational) — converging, not converged.

**Consensus labels** (post-discussion; diffs from the unaided pass noted):

- Review 1 (NBA 2K23) — `platform_access` / negative (ruling 16 — the miss
  Arda's own friction note was sensing) **+** `developer_conduct` / negative
  (kept; evidence re-cut to the single span "But wow, this is egregiously
  scummy." — the unaided evidence stitched two spans and rewrote a "?",
  which the eval would score as fabrication).
- Review 2 (Darkest Dungeon) — `graphics` / positive (was `art_style`
  unaided — corrected by the evidence-horizon ruling: the text says generic
  visuals-praise; the game's celebrated 2D style is annotator knowledge the
  machine never sees); `sound_design` / positive; `gameplay` / positive
  (the separate `strategy` candidate folded back in — the dash elaborates
  one evaluation, anti-stacking); `atmosphere` / positive; candidate `rng` /
  neutral; `difficulty` / neutral.
- Review 3 (No Man's Sky) — `updates` / negative; `content_amount` / mixed;
  `gameplay` / mixed; candidate `automation` / mixed (all unaided — the
  automation fold was the round-2 fold rule executed well);
  **+** `balance` / negative (trivial economy), `progression` / negative
  (pointless upgrades), `exploration` / mixed (favorite part + pointless
  outcome) — the litany tail under the independently-evaluated test.

**Process finding:** third round, third evidence-transfer defect (retype →
space-collapse → stitch/rewrite). The pattern is now beyond doubt: human
span-transfer fails in a new way each time; the real pass pre-fills spans
via the assist and Arda adjudicates, never transcribes.
