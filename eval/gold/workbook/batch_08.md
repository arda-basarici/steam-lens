# Gold workbook — batch 08 of 25

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

## 1 · review 226252662
- [x] reviewed

```text
melhor jogo
```

SKIP: non_english
> assist flag: non_english — keep the SKIP line, or delete it and keep/write the labels

## 2 · review 224930619
- [x] reviewed

```text
Very unique vibes. Haven't experienced anything like it.
```

- unique / positive / "Very unique vibes. Haven't experienced anything like it."

## 3 · review 225497493
- [x] reviewed

```text
this game cool but bugs is not cool
```

- bugs / negative / "this game cool but bugs is not cool"

## 4 · review 227376136
- [x] reviewed

```text
Genuinely I loved this game best co op game ive played. I love the part when Leo and Vincent fought at the end to the death, and the whole time vincent was an undercover cop. We fought buy guns to the death and PICK LEO he is way better.
```

- multiplayer / positive / "best co op game ive played"
- story / positive / "I love the part when Leo and Vincent fought at the end to the death, and the whole time vincent was an undercover cop."
> assist note: "PICK LEO he is way better" names no clear codebook property (character quality vs. mechanical balance are both plausible) — left unlabeled per the ambiguous-referent rule.

## 5 · review 225161629
- [x] reviewed

```text
Monika is very nice and not at all evil 😁😁😁
```

- characters / positive / "Monika is very nice and not at all evil"
> assist note: Labeled literally per the text-alone evidence horizon; outside fandom knowledge about this character could suggest irony, but nothing in the text itself signals it.

## 6 · review 216776318
- [x] reviewed

```text
Amazing.
```

Zero mentions.

## 7 · review 226188026
- [x] reviewed

```text
yes very nice, give me l4d3 ♥♥♥♥♥♥♥♥♥
```

Zero mentions.

## 8 · review 214841803
- [x] reviewed

```text
So much content... Stash Tabs are a game changer and great aesthetically + they carry over to POE2.
```

- content_amount / positive / "So much content"
- ui / positive / "Stash Tabs are a game changer"
- art_style / positive / "great aesthetically"
> assist note: Two judgment calls: Stash Tabs routed to `ui` (inventory tooling) rather than a candidate; "carry over to POE2" minted as its own candidate — both worth a second look.

## 9 · review 220544384
- [x] reviewed

```text
cant even play the game with a controller, it just locks all input when i connect
```

- controls / negative / "cant even play the game with a controller, it just locks all input when i connect"
> assist note: Routed to `controls` (controller support) rather than `bugs`, since the complaint is specifically about controller input; could go either way.

## 10 · review 224830431
- [x] reviewed

```text
Fun and goofy game, highly recommend playing with the steam work shop.
```

- mods / positive / "highly recommend playing with the steam work shop."
