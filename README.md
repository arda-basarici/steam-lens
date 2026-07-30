# steam-lens

**What do players actually like and dislike about a game — and is its review score
telling the truth right now?**

SteamLens answers this by *reading* Steam reviews the way an analyst would: per-review
aspect classification with verbatim quotes as receipts, deterministic aggregation, and
the system's own measured error rate published beside every number. The LLM call is
deliberately the smallest part of the system — the work is the instrument built around
it: a human-anchored gold set, a calibrated judge, bootstrap CIs on every reported
number, and an eval harness that gates CI. The extraction and evaluation core is built
and measured: a 135,260-review census across 49 games, labeled end-to-end for $3.80,
certifies at **F1 0.766 [0.713–0.811]** against a human-labeled gold set — and an
independently calibrated LLM judge cross-checks that quality holds beyond the gold
set's reach.

> **Status: mid-build, evaluation-first.** The extraction + evaluation milestone is
> built and measured; the sampling study, the deployed web app, and the
> report-interrogation chat are the next milestones, in that order. Nothing is deployed
> yet — every claim below is measured, and the README never claims ahead of the build.

## Measured so far

- **Label quality: F1 0.766 [0.713–0.811]** for the production labels against a
  250-review gold set blind-labeled by hand *before* any model output existed
  (single annotator, disclosed; scored on the 245-review scope intersection).
- **The judge check holds off-gold:** a different-family LLM judge, calibrated first
  (F1 0.816 vs gold — paired Δ **+0.050 [+0.019, +0.083]** over production), agrees
  with production at **F1 0.791 [0.772–0.810]** on a 1,000-review census sample — no
  quality cliff outside the gold set.
- **Fabricated quotes: 0 in 163,842 stored evidence spans**, verified verbatim against
  their source reviews — because failing quotes are nulled at write time (~2.9% of
  attempted quotes needed that repair; the wrong-aspect misattribution rate is a
  separate human audit, in progress).
- **The labeler was chosen by measurement, not reputation:** a gold-set bake-off picked
  DeepSeek v4-flash at batch size 10 — a stronger candidate existed (+0.034 F1 at
  matched batch size) but at ~12× the cost, and the gap closes at the frozen
  production shape.
- Standing caveats, carried openly: one human annotator; the current codebook wording
  was tuned on the gold set, so v2-on-gold numbers are development-grade until a fresh
  holdout lands; labels re-certify after any re-buy (measured buy-time variance ~0.03).

## The engineering underneath

What separates this from prompt-and-parse, in the places a code reader will look:

- **Evals gate CI.** Both evaluation runs of record re-score deterministically in CI
  from a committed fixture; an exact-digit mismatch fails the build, and a deliberate
  semantics change must bump the scorer identity and re-export the pins in the same
  commit.
- **The judge is an instrument, not a vibe.** Different model family from the labeler
  (no self-preference), calibrated against human gold *before* use, under a
  pre-registered pass/marginal/fail rule — and it re-labels blind rather than grading
  answers it can see.
- **Statistical integrity is enforced by structure.** Displayed numbers can only come
  from the survey-origin labels: origin tags in the pool, an origin predicate in the
  store's fold, and a CI import-graph test that keeps the walls standing. Uncertainty
  is first-class — bootstrap CIs resampled at the review level, paired comparisons,
  and statistics that say "undefined" instead of a fake 0.0.
- **The seams are hand-built where the seam is the skill.** The provider client is raw
  httpx behind one typed seam (aggregator libraries and vendor SDKs rejected with
  recorded reasons); storage is SQLite with a hand-rolled migration runner and a
  content-addressed archive of raw provider output; every artifact carries its
  provenance (run id, code sha, config hash, version pins).
- **Boundaries sit where change is likely.** Swapping the LLM provider (another API,
  or a local model) is a config edit plus one adapter function behind the same seam.
  Everything Steam-specific lives in one door module and one versioned vocabulary
  artifact — the extraction/eval method itself is domain-generic, so pointing it at
  another review corpus (an app store, product reviews) means a new door and a new
  ontology, not a rewrite. Storage follows the same rule: callers see typed record
  surfaces, never SQL, so a different database engine would be a new implementation
  of that one module — nothing else in the codebase moves.
- **Cost decisions are experiments.** The labeler was picked by a frozen-metric
  bake-off; batch size froze on a measured quality peak; and when the census scored
  0.033 below the lab arm, pre-registered experiments isolated the cause (buy-time
  variance of the served model, not batch composition) instead of hand-waving it.

## What it is becoming

- **Aspect report** — strengths/weaknesses by aspect (combat, story, performance, …),
  every claim carrying its evidence count and expandable verbatim quotes.
- **Trust panel** — sample provenance, language coverage, and the published error rates
  above, scoped honestly inside the product.
- **Episode markers** — statistically detected anomalies on the review timeline,
  displayed without speculation.
- **Report-interrogation chat** — grounded RAG over the labeled reviews: answers quote
  retrieved reviews, numbers appear only as citations of the aggregate mint, and the
  ladder ends in honest refusal rather than free composition.

One rule holds everything together: every displayed number comes from a fixed survey
sample; stories quote retrieved reviews and never mint numbers.

## What it deliberately is not

Not vanilla sentiment scoring; not fake-review accusations (unverifiable — cut by
design); not cross-game comparison (the per-report frame is the product's identity);
not a notebook with a URL.

## Run it

```
uv sync                              # Python 3.13, uv-managed
uv run pytest                        # tests + doctests, incl. the eval gate:
                                     #   both eval runs of record re-score in CI
                                     #   from a committed fixture, exact-digit
uv run ruff check                    # lint gate
uv run python scripts/regen_docs.py  # regenerate the API reference (pdoc)
```

Everything above runs offline from committed artifacts. Label buying and judge runs
are deliberate, key-gated spends — never part of a clean-clone quickstart.

## Layout

| layer | modules | responsibility |
|---|---|---|
| contracts | `contracts` | frozen plain-data records + enums; imports nothing |
| vocabulary | `ontology` | the pinned aspect vocabulary, versioned (v1 ratified, v2 wording) |
| pure core | `core/normalize` · `core/classify` · `core/aggregate` | vocab resolution · prompt build/parse · the number mint |
| effect shells | `steam_client` · `llm_client` · `store` · `corpus` | the Steam door · the provider seam · SQLite/WAL · corpus files |
| run machinery | `dispatch` | shared batch/run engine the drivers compose |
| evals | `evals` | scoring core, certification, judge runs, the CI fixture |
| entry shells | `studies` · `scripts` | census labeling + aggregation drivers · gold tooling, docs regen |

`eval/` holds the versioned gold set and audit sheets; `probes/` holds one-shot
investigation scripts whose findings, not style, are the artifact.

## What it demonstrates

Evaluation-first LLM engineering: the measurement instrument was built, calibrated,
and pointed at the system before any UI existed — and it gates the build.

## Deeper

[VISION](VISION.md) — the frozen founding snapshot: product, milestones ·
[DESIGN](DESIGN.md) — the living decisions narrative ·
[ARCHITECTURE](ARCHITECTURE.md) — the structure, growing with the build

## License

Code is released under the [MIT License](LICENSE). Steam review content fetched or
quoted by the app belongs to its respective authors and Valve — it is analyzed and
excerpted as evidence, not redistributed under this license. Generated reports are
LLM-derived analyses of that content, provided as-is; their reliability is what the
product's own published error rate measures.
