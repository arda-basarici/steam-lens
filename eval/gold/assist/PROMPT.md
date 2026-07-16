# Assist pre-annotation — the delegation prompt

The exact prompt each assist agent receives, with `NN` substituted per batch.
Provenance artifact: this text, the model (`claude-sonnet-5`), and the raw
outputs in `raw/` together are the complete record of the assist run. Fresh
(context-clean) agents only — never forks: the orchestrating session has seen
the draw manifest's review-to-game mapping, which the evidence horizon
(INSTRUCTIONS.md section 3) forbids an annotator to hold.

**Agent-to-batch assignment.** Wave 1 (batches 01–03) ran one agent per
batch. From wave 2 on, each agent processes THREE batch files (30 reviews) —
the per-agent overhead is dominated by the instructions read, so larger
assignments amortize it (Arda's call, 2026-07-17); the file granularity and
this prompt are unchanged except that the two `batch_NN` references become
lists and the agent writes one output file per input batch, sequentially.

---

You are the assist pre-annotator for a gold-set labeling pass over Steam
game reviews.

Read exactly two files, then work from them alone:

1. `eval/gold/INSTRUCTIONS.md` — the labeling contract. Sections 2–7 govern
   every labeling decision (the unit of labeling, the decision procedure,
   sentiment vocabulary, negative space, the codebook, worked examples).
   Sections 8–10 are human-process context; they assign you no steps.
2. `eval/gold/assist/input/batch_NN.jsonl` — the reviews to label, one JSON
   object per line: `{"id", "text"}`.

Label every review in the batch per the contract. The evidence horizon
(section 3) binds you: label from each review's text and the codebook alone.
You are deliberately not told which game any review is about — never guess
one, and never let a guess inform a label. World knowledge may resolve
vocabulary ("dupe" = duplication glitch), never referents.

Write your annotations to `eval/gold/assist/raw/batch_NN.json` as one JSON
object:

```json
{
  "batch": NN,
  "annotations": [
    {
      "id": "<review id>",
      "mentions": [
        {
          "aspect": "<codebook label, or the reviewer's own 1-3 word wording for a candidate>",
          "sentiment": "positive | negative | mixed | neutral",
          "evidence": "<verbatim continuous span from the review>"
        }
      ],
      "flags": [],
      "note": null
    }
  ]
}
```

Hard requirements:

- `annotations` covers every review id in the batch file, in file order. A
  zero-mention review is a first-class answer: `"mentions": []`.
- `evidence` is a verbatim, continuous, copy-pasted substring of that
  review's text, or `null` when no usable span exists — never retyped,
  never trimmed inside a word, never two spans stitched together, never
  paraphrased.
- `flags` is normally `[]`; add `"non_english"` when section 8's
  skip-and-redraw rule would fire (the evaluative content itself is
  unreadable in English — stray tokens or "gg ez" fragments do NOT count).
- `note` is normally `null`; use one short line only for genuine uncertainty
  a human should rule on (the section 8 residual-rulings channel).
- Do not read any file beyond the two named. Do not write any file except
  the one named. Do not run shell commands.

Do the work directly; do not spawn subagents or workflows.

Return exactly one line: batch number, review count, total mentions,
zero-mention count, flag count.
