# Gold workbook — batch 23 of 25

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

## 1 · review 222607347
- [x] reviewed

```text
It was a great adventure!
```

Zero mentions.

## 2 · review 36486070
- [x] reviewed

```text
10/10 Would sacrifice peasants to the demon lord again.
This game is awesome it's very complex text based kingdom management simulation. Don't let ASCII graphics scare you away because it has its' own kind of charm. The only thing I would like is Linux port...
```

- gameplay / neutral / "it's very complex text based kingdom management simulation"
- art_style / positive / "Don't let ASCII graphics scare you away because it has its' own kind of charm."
- platform_access / negative / "The only thing I would like is Linux port..."

## 3 · review 227382482
- [x] reviewed

```text
Steam pestered me for a review. Here you go.
```

Zero mentions.

## 4 · review 169565216
- [x] reviewed

```text
I met an Oh Snake and he said "Oh"
So all in all I'd say it's a good game.
```

Zero mentions.

## 5 · review 220792840
- [x] reviewed

```text
This game was fun, but I found the research and quest aspects to be broken. I played for 14 hours before I unlocked the garden, but it didn't expand my buildable area- I had already made all that into Inn, duh! So I didn't make a garden. Many of the researches were very so-so- rewards, with some being just seemingly nothing or confusing.  When you hire a new person they are assigned permanently to the new kitchen or bar you built, great, but also assigned to every floor??? Ahhh!

All in all, I enjoyed this game. I think it is find for achievement hunting, look at my blue ribbon, wooo~! But I think it was a grind and not super fun to get there. I felt like once I got to 10 hours I had built my tavern and really enjoyed it, but there was little to do. Money piled up, workers started making 100 gold a day, I had like 300 researchers before I realized the hard stop of needing guests to come in. Then I deleted half my hotel rooms and made more tables.

In the end, I think they wanted a balanced game and it sort of isn't. All the same, I enjoyed it and it was easy to play. There were very few "ugh ERMAHGERD" moments with the building- everything can snap into place, etc. 

there was a lot of attention to certain details, which was so funny to me- like the people in the bathroom get pixelated. So respectful! I laughed. This game is cute, you'll like it.
```

- progression / negative / "I found the research and quest aspects to be broken"
- quest_design / negative / "I found the research and quest aspects to be broken"
- bugs / mixed / "they are assigned permanently to the new kitchen or bar you built, great, but also assigned to every floor??? Ahhh!"
- achievements / neutral / "I think it is find for achievement hunting, look at my blue ribbon, wooo~!"
- grind / negative / "it was a grind and not super fun to get there"
- content_amount / negative / "there was little to do"
- balance / negative / "I think they wanted a balanced game and it sort of isn't"
- learning_curve / positive / "it was easy to play"
- art_style / positive / "This game is cute"
> assist note: Borderline candidates: 'achievement hunting' (lukewarm 'find for X, look at my blue ribbon' framing) and 'attention to certain details' (a quirky Easter-egg-style detail, not a clear codebook home) -- flag if either should be dropped or folded elsewhere. Kept the building-snapping praise ('everything can snap into place') folded into the existing gameplay mention rather than minting a duplicate.

## 6 · review 138730335
- [x] reviewed

```text
Super fun game that plays like a mix of Xcom and Fallout. The combat and squad building/RPG elements are quite fun, as is the overall gameplay. Music and sound are top notch and usually appropriate for the mood. Some of the characters in the game are quite wild and most quests and places you come across are pretty interesting. The story is good, but unfortunately the writing is very poor. Plot points sometimes disappear, results of some dialogue choices make no logical sense, and apparently there's never any way to change any outcome, as if once something happens, it's final and no one will ever think of a solution around it. Factions are almost entirely useless, as there's only a few and once you do a few quests with them, they're largely forgotten until the end game credits. Kinda wish there was more content and quests with existing factions/cities that would trigger as you progressed into the game, instead of things being left behind once done. Also wish your squad mates had more dialogue with each other, as the few times Lucia or Kwon added commentary during the game, it was very welcome.
```

- gameplay / positive / "The combat and squad building/RPG elements are quite fun, as is the overall gameplay."
- combat / positive / "The combat and squad building/RPG elements are quite fun, as is the overall gameplay."
- build_variety / positive / "The combat and squad building/RPG elements are quite fun, as is the overall gameplay."
- music / positive / "Music and sound are top notch and usually appropriate for the mood."
- sound_design / positive / "Music and sound are top notch and usually appropriate for the mood."
- characters / positive / "Some of the characters in the game are quite wild"
- quest_design / positive / "most quests and places you come across are pretty interesting"
- world / positive / "most quests and places you come across are pretty interesting"
- story / positive / "The story is good"
- writing / negative / "the writing is very poor"
- player_choice / negative / "results of some dialogue choices make no logical sense, and apparently there's never any way to change any outcome, as if once something happens, it's final and no one will ever think of a solution around it."
- factions / negative / "Factions are almost entirely useless, as there's only a few and once you do a few quests with them, they're largely forgotten until the end game credits."
- content_amount / negative / "Kinda wish there was more content and quests with existing factions/cities that would trigger as you progressed into the game, instead of things being left behind once done."
> assist note: Several judgment calls: merged the 'wild characters' praise with the closing wish for more squadmate banter into one mixed `characters` mention rather than two; 'places you come across' routed to `world` (could arguably be `level_design`); 'Factions' kept as its own candidate rather than folded into `quest_design`/`content_amount` since factions-as-a-system has no clean pinned home. Flag any of these if they should route differently.

## 7 · review 225290527
- [x] reviewed

```text
i have lost all the braincells i previously owned by swinging a big hammer and sending my entire body into the enemy team and making it out with zero consequences because of a cat who can carry a solid 100kg of drunk german man
```

Zero mentions.
> assist note: No explicit evaluative adjective ('fun'/'cool'/etc.) -- labeled physics/positive on the strength of the anecdote's tone (absurd, forgiving physics played for delighted disbelief). Flag if implicit-tone anecdotes like this shouldn't count as a mention.

## 8 · review 227136117
- [x] reviewed

```text
Yep
```

Zero mentions.

## 9 · review 227797096
- [x] reviewed

```text
👍
```

Zero mentions.

## 10 · review 227352339
- [x] reviewed

```text
My favorite game and very influential to me
```

- emotional_impact / positive / "very influential to me"
