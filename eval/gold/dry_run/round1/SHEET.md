# Gold instructions — dry-run acceptance test

**Rules of the run.** Label the reviews below using `eval/gold/INSTRUCTIONS.md`
and nothing else — no pilot captures, no chat, no codebook TOML. Work top to
bottom; note the rough time per review. The friction notes are the point of
this exercise: every place you had to reread, guess, or wish the doc said
more is a finding, even if you resolved it yourself.

**Recording a mention** — one bullet per mention, in this shape:

    - `aspect_label` / sentiment / "verbatim evidence" (or: no usable span)

A zero-mention review gets the single line `Zero mentions.` instead.

---

## Review 1 — Helldivers 2 (review id `226339924`)

```text
I sincerely wish the developers have the same strong connection with their penis as I have with other players' lobby.

To be more clear: I had to change four ways of connection/routing in order to play. I'm just tired of solving connection problems every time I just want to hang out with my friends. It's NOT my problem that you can't set up netcode.

UPD: Solving problems with connecting to this game has caused problems connecting to other games. Many thanks to the developers and their servers for a stable connection, and most importantly, a quick and timely solution to the players' questions :)
```

### Labels

servers_netcode / negative / It's NOT my problem that you can't set up netcode.

### Friction notes

"none" about the document. about review, I did not understand the first sentence before reading the rest of the review.

one thing ı have noticed, we didnt discuss much about the updates, but reviews contains updates and they can change the direction of the reviews and they should be treated carefully.

---

## Review 2 — Disco Elysium (review id `225522093`)

```text
Although I enjoyed the game less than I imagined, and was a little tired of it at the end, I can still say that this is one of the most creative, weird and unique games I've ever played.

I don't think I'll ever forget its characters and atmosphere.
```

### Labels

(your mention bullets here)

### Friction notes

I see we dont have label for being creative / unique.

Although I enjoyed the game less than I imagined, and was a little tired of it at the end, : this part is about the mood, doesnt mention any aspect. it is negative but no aspect.

however this part : "I can still say that this is one of the most creative, weird and unique games I've ever played." is positive about being creative and being unique but ı couldnt label it.

the review can discuss being creative and unique about certain aspects:
art, sountrack, gameplay etc. then we should label accordin to that aspect. but if the review saying being creative and unique in general we may need a label about this. Or these can go to candidate section.

---

## Review 3 — Euro Truck Simulator 2 (review id `227200917`)

```text
Strangely addictive, while this isn't the total Microsoft Flight Simulator level recreation of the European countries and road networks I would have liked, it gives a really good rendering, and feels surprisingly realistic.  The trucks handle well, there are accidents, weather conditions and live radio stations that all add to the immersion.  If your idea of fun is trucking, then this may be hard to beat.  This game seems to have vast amounts of DLC but honestly the base game is plenty for a casual like me who enjoys just dipping in to do a hauling job from time to time.
```

### Labels

addictiveness / positive / strangely addictive
realism / positive / feels suprisingly realistic
atmosphere / positive / The trucks handle well, there are accidents, weather conditions and live radio stations that all add to the immersion.
dlc / neutr / This game seems to have vast amounts of DLC

### Friction notes

ı wasnt sure about the realism, is it talking about graphics, it say rendering few words ago, but it doesnt sound like graphics. Also the following statement also start talking about the world.
if the review doesnt say, "that all add to the immersion", I could use the world tag. there can be a friction between atmosphere-world and realism.

"This game seems to have vast amounts of DLC".
clear dlc tag, but the following sentiment isnt about the dlcs. it is about the vanilla game, again we can consider for a tag for this purposes.
or content_amount can be used here, but when we say content amount in the tag, are we including dlcs ? or are we saying this game has a lot of content even without the dlcs

---

## Overall

*(Filled after the review discussion, 2026-07-16. The per-review sections
above are Arda's unaided pass, preserved untouched — they are the acceptance
evidence.)*

**Doc verdict: READY** — accepted after five rulings the pass surfaced were
settled interview-mode and applied to INSTRUCTIONS.md (§9 ledger entries
8–12): memorable-X routes to the named aspects · concessive comparisons are
not charges · UPD/EDIT text folds like ordinary text (trajectory parked to
the investigator track, stream IDEAS.md) · the independently-evaluated test
for reviewer-folded enumerations · ambiguous referents fold, never mint.
Also applied: a quality-type candidate worked example (§7 ex. 9, the Disco
Elysium line), base-vs-DLC content scoping, copy-paste-only evidence
emphasis. Two boundary rulings queued as v2 TOML wording candidates
(FIXLOG): until then, human-vs-machine disagreement there is expected.

**Consensus labels** (post-discussion; diffs from the unaided pass noted):

- Review 1 — `servers_netcode` / negative; **+** `developer_conduct` /
  negative (the sarcastic UPD mock-thanks — missed unaided).
- Review 2 — candidate `creative` / positive (reached in the friction notes,
  not committed unaided); `characters` / positive **+** `atmosphere` /
  positive (last line — missed by oversight, not by doc gap); opening clause
  = no mention (verdict-grade).
- Review 3 — `addictiveness` / positive; `realism` / positive ("rendering"
  folds in as rendition-of-Europe, per the ambiguous-referent ruling);
  **+** `physics` / positive ("the trucks handle well" — the
  independently-evaluated test); `atmosphere` / positive (the immersion
  fold, enumerated contributors as evidence); **+** `content_amount` /
  positive ("the base game is plenty" — missed unaided); `dlc` / neutral.

**Process finding:** one evidence quote drifted under retyping
("suprisingly") — for the real pass, evidence is copy-paste only, and the
assist pre-annotation makes that the default (accepting a pre-filled span
beats typing one).
