# Gold workbook — batch 09 of 25

Assist: `claude-sonnet-5` · instructions `gold-instructions-v1` · ontology `v1`

Your adjudication surface — edit THIS file; `assist/raw/` stays immutable.

- Flip `- [ ] reviewed` to `- [x] reviewed` on every review you finish
  (accepting as-is included). Compile refuses to mint gold while any box
  is unchecked.
- Mention line: `- aspect / sentiment / "verbatim evidence"` — evidence is
  COPY-PASTED from the text block above (a newline inside a span is written
  `\n`), or `(no span)` when no usable span exists.
- Zero mentions: the single line `Zero mentions.` — delete it if you add
  mentions; write it if you delete every mention.
- Skip (INSTRUCTIONS section 8): replace the mention lines with
  `SKIP: non_english`.
- `> assist note:` / `> assist flag:` lines are read-only context; keep or
  delete freely — the compiler ignores them.

---

## 1 · review 186382186
- [x] reviewed

```text
Many of the user-reviews for this game are [i] very [/i] positive, and e.g. emphasizes the emotional impact and wisdom of this game. I read some of those reviews and bought the game with 75% discount, which I think is a price worth the experience I had with the game. Had I payed the full price of the game, I would probably have been left with a feeling of disappointment. 

Nonetheless, I did enjoy playing the game! Very nice atmosphere and music. The story is okay, and it touches an important area of our existence, which is death. I think this game feels more like a movie compared to other story-rich games. 

I would recommend buying this game, but only on discount.
```

- price_value / mixed / "which I think is a price worth the experience I had with the game. Had I payed the full price of the game, I would probably have been left with a feeling of disappointment."
- atmosphere / positive / "Very nice atmosphere and music."
- music / positive / "Very nice atmosphere and music."
- story / neutral / "The story is okay, and it touches an important area of our existence, which is death."

## 2 · review 226429016
- [x] reviewed

```text
Fun and time consuming. Better with friends
```

- game_length / positive / "Fun and time consuming"
- multiplayer / positive / "Better with friends"
> assist note: "time consuming" read as positive game_length (paired with "Fun"); could plausibly be neutral instead — the polarity is inferred from context, not stated.

## 3 · review 226115611
- [x] reviewed

```text
bad game controlled by jews and israel
```

Zero mentions.

## 4 · review 43099636
- [x] reviewed

```text
Can't play as sweden, can't even install a mod for it because the mod is not available anymore. ♥♥♥♥ this game.
```

- mods / negative / "can't even install a mod for it because the mod is not available anymore"

## 5 · review 221616897
- [x] reviewed

```text
Fun! And Rage-Inducing! But mostly fun! 9/10
```

Zero mentions.

## 6 · review 223473987
- [x] reviewed

```text
10/10
Ten years of Rocket League and it’s still pure magic because nothing compares to the rush of a last second save or the high of a perfect goal and even the heartbreak of missing an open net is part of the endless joy that puts this game in my top five of all time despite me not even calling myself a gamer it’s just a decade of unmatched excitement that never ends
```

- replayability / positive / "Ten years of Rocket League and it’s still pure magic"
- emotional_impact / positive / "nothing compares to the rush of a last second save or the high of a perfect goal and even the heartbreak of missing an open net is part of the endless joy"
> assist note: Split into two mentions (longevity vs. moment-to-moment emotional highs); `addictiveness` is also plausible for either — judgment call.

## 7 · review 227741586
- [x] reviewed

```text
nice game
```

Zero mentions.

## 8 · review 196322285
- [x] reviewed

```text
i wish i could refund this game
```

Zero mentions.

## 9 · review 227698852
- [x] reviewed

```text
natsuki best girl
```

- characters / positive / "natsuki best girl"
> assist note: "best girl" names a specific character with a positive verdict, treated as a real (if minimal) characters mention rather than a bare verdict — borderline given how thin the evidence is.

## 10 · review 222298744
- [x] reviewed

```text
Addiction is this game. I have never been the same. 10/10 don't buy the second game
```

- addictiveness / positive / "Addiction is this game."
