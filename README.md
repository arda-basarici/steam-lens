# steam-lens

**What do players actually like and dislike about a game — and is its review score
telling the truth right now?**

SteamLens will be a deployed web app that answers this by *reading* Steam reviews the
way an analyst would: type a game, watch an AI investigate its reviews live, get a
structured report — aspect-level strengths and weaknesses with verbatim quotes as
receipts, review-timeline events detected and explained, and the system's own measured
error rate published inside the product.

> **Status: pre-build.** The vision is fixed (2026-07-07) after a structured design
> deliberation; the system design and first milestone are next. Nothing to run yet —
> this README grows with the build and will never claim ahead of it.

## What it will do

- **Aspect report** — strengths/weaknesses by aspect (combat, story, performance, …),
  every claim carrying its evidence count and expandable verbatim quotes.
- **Event investigation** — anomalies in the review timeline ("negative spike, Nov
  2024") detected statistically and explained by targeted reading of that window's
  reviews, verified against the game's public update history.
- **A live, narrated analysis** — cold requests stream the investigation as it runs;
  hypotheses are labeled as hypotheses and promoted only after checks pass.
- **A trust panel** — sample provenance, language coverage, and the system's own
  offline-measured accuracy, scoped honestly. The evaluation methodology (human-anchored
  gold set, calibrated LLM judge, mechanical quote-grounding) is a first-class artifact
  of the project, not an afterthought.

## What it deliberately is not

Not vanilla sentiment scoring; not fake-review accusations (unverifiable — cut by
design); not a notebook with a URL — live runtime analysis on real Steam data is the
product's identity.

## Deeper

[VISION](VISION.md) — the fixed vision: product, milestones, decisions ·
[DESIGN](DESIGN.md) — the living decisions narrative ·
[ARCHITECTURE](ARCHITECTURE.md) — the structure, growing with the build

## License

Code is released under the [MIT License](LICENSE). Steam review content fetched or
quoted by the app belongs to its respective authors and Valve — it is analyzed and
excerpted as evidence, not redistributed under this license. Generated reports are
LLM-derived analyses of that content, provided as-is; their reliability is what the
product's own published error rate measures.
