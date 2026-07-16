# Gold instructions — dry-run acceptance test (round 2)

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

## Review 1 — Overwatch 2 (review id `225883828`)

```text
No controller aim assist on PC,  uninstalled. Can't even compete when these sweaty kbm players have insane movement and a whole damn arm to aim with. Idk why so hard to just have controller go against controller with aim assist and kbm go against kbm and have an option to play against kbm as a controller player without aim assist. I shouldn't have to buy a console to get aim assist what a joke..
```

### Labels

controls / negative / No controller aim assist on PC, uninstalled.
matchmaking / negative / Idk why so hard to just have controller go against controller with aim assist and kbm go against kbm and have an option to play against kbm as a controller player without aim assist.

### Friction notes

I think matchmaking is clear here, but I am not sure if the model can extract it from the review.

---

## Review 2 — Hollow Knight (review id `225144321`)

```text
Creo que lo he terminado alrededor de 4 veces y de ves en cuando sigo regresando a el.

Definitivamente el mejor metroidvania para mi.

Amo el ultimo DLC que nos da la oportunidad de vencer nuevamente a cada uno de los jefes.
```

### Labels

(your mention bullets here)

### Friction notes

not english

---

## Review 3 — The Day Before (review id `153482587`)

```text
Had no mantle, 90% of buildings couldn't enter, looting didn't seem satisfying, had a weird exfil system and didn't look like half of what the trailers had shown, 2 zombies on the entire map, no melee weapons, can dupe infinite money, wasn't really a survival game.
```

### Labels

world / negative / 2 zombies on the entire map
exploration / negative / 90% of buildings couldn't enter
combat / negative / no melee weapons

looting / negative / looting didn't seem satisfying (candidate)

### Friction notes

can dupe infinite money , ı am not sure if the reviewer talking about in game money or monetizaiton.

wasn't really a survival game. had a weird exfil system and didn't look like half of what the trailers had shown

we can maybe consider adding a label about , how game is faithful to its marketing / its title, announced genre.

---

## Overall

*(Filled after the review discussion, 2026-07-16. The per-review sections
above are Arda's unaided pass, preserved untouched.)*

**Doc verdict: NOT YET CONVERGED — three new rulings** (INSTRUCTIONS §9
entries 13–15: marketing fidelity → `developer_conduct` with the
summary-genre-verdict rider · in-game exploits → `bugs` · absence routes to
the owning pin, no pin → candidate). By the convergence rule, a round 3
follows. Character shift worth noting: round 1's five rulings were
structural (folds, evidence policy, sentiment boundaries); round 2's three
are routing precedents — narrower, cheaper, example-like. The doc's
*mechanics* held unaided: a candidate committed correctly (`looting`,
worked-example-7 pattern — round 1's fix validated), the non-English skip
rule applied correctly (review 2), zero format friction.

**Consensus labels** (post-discussion; diffs from the unaided pass noted):

- Review 1 (Overwatch 2) — `controls` / negative + `matchmaking` / negative
  (unaided pass accepted as-is; friction note was a classifier-capability
  question, not a doc gap).
- Review 2 (Hollow Knight) — **skipped, non-English** per §8; the corpus row
  claims `language=english` while the text is Spanish → the Steam language
  field is reviewer-selected and unreliable; skip logged in this round's
  manifest. Design consequence recorded: the real gold draw must be a seeded
  *ordered* sample (skips need a defined "next"), not per-game `rng.choice`.
- Review 3 (The Day Before) — `world` / negative; `exploration` / negative;
  `combat` / negative; candidate `looting` / negative (all unaided);
  **+** `developer_conduct` / negative (trailers — ruling 13);
  **+** `bugs` / negative ("can dupe infinite money" — ruling 14);
  **+** candidate `exfil system` / negative and `gameplay` / negative
  ("had no mantle") — ruling 15; "wasn't really a survival game" stays
  unlabeled (summary verdict, ruling 13's rider).

**Process finding:** paste-then-editor-normalization collapsed a double
space in an evidence span — hand-transfer of spans is unreliable even when
copy-pasted; in the real pass, spans are assist-pre-filled and Arda
accepts/corrects, never transcribes.
