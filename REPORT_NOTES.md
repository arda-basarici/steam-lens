# Report notes — SteamLens

Raw material for milestone reports and posts: decision narratives distilled at the
moment they happen, so the reports can tell the story without excavating chat logs.
Append-only, newest first. Each entry is a self-contained story with its date and the
decisions it feeds.

---

## 2026-07-19 — The sizing question wasn't answered, it was deleted: half the corpus was never labelable, so the survey became a census

*The survey-slice-size ruling between the provider bake-off's close (C0) and the
corpus-labeling buy (C1) — extraction+eval (M1). Feeds: the M1 report/post's
methodology section (how the survey was sized, sampling-vs-census framing) and the
cost story.*

The question on the table was how many reviews per game the label buy should cover.
The standing recommendation — ~1,000 per game, undecided — had been drafted when
labeling looked like a ~$25 decision under paid-Gemini economics, and it carried one
named gate: check the per-game minimums in the corpus before locking the number. The
check ran today (`probes/survey_supply_counts.py`) and came back with something much
bigger than a minimum: the labelable pool is not the corpus. Of the 298,553-review
headline, only 135,260 — about 45% — survive the pipeline's own entry conditions,
the English-first filter plus the Unicode-honest emptiness test from the gold draw's
lesson. Per-game supply runs from 195 (Shadow of the Tomb Raider) through a median
around 2,100 to 6,869 (VVVVVV).

That number collapsed both premises of a ruling that had felt settled for three
days. "The full corpus is never labeled" (the 2026-07-16 provider-strategy session)
had been reasoned as roughly six times the spend for numbers the aggregate would
refuse to certify — but the six-times figure assumed the 298K denominator, and the
spend assumed Gemini prices. With the real denominator at 135K and DeepSeek
v4-flash's true cache-adjusted cost (the C0 captures' measured splits,
`probes/captures/bakeoff/bakeoff.sqlite3`), labeling *everything usable* prices at
roughly $3–6 — only 2.9× the 1,000-per-game sample it was meant to avoid. Arda's
ruling: census the usable pool. The satisfying part, for the report, is that the
sizing question never got an answer — it got deleted, and it took two sub-problems
with it: no shortfall policy needed for small games (every game is simply taken
whole), and no cap on the sampling study (M2), which re-folds these stored labels
under simulated draws and now has complete freedom to simulate any policy at any
size, forever, for zero additional spend.

A companion ruling landed the same day, from Arda's natural next question — don't we
filter the useless reviews before paying for them? No, deliberately: an empty aspect
list is the certified classifier's own verdict and a measured product quantity (the
gold set's zero-aspect share is 49.2%), while any usefulness heuristic is an
unvalidated second classifier standing in front of the one the bake-off spent a week
certifying — "runs bad" is eight characters and a genuine performance mention. The
economics don't even argue: the codebook prompt dominates cost and bills at ~98% off
via DeepSeek's cache, and the store's content-keyed label cache already makes the
verbatim copy-pasted meme reviews cost once across the whole corpus.

One instrument lesson rode along: the floor-clearance projection built to rank the
candidate sizes (`probes/floor_clearance_projection.py`, rates from the B1 pruning
captures) returned *identical* results at every candidate — not because size doesn't
matter, but because 100-review-per-game probes cannot resolve mention rates under
~1%, so every aspect the probe could see already cleared the evidence floor at the
smallest candidate. The instrument saturated exactly where the decision lived; the
census made its verdict moot, but the lesson stands for any future
probe-sized-to-question mismatch.

Figure: the supply-vs-headline story — per-game bars of raw corpus vs
English-nonempty supply (regenerates from `probes/survey_supply_counts.py`), with
the cost-per-candidate table (500/1k/2k/3k/census) as the companion panel.

## 2026-07-19 — The eyeball read failed its own significance test, and the ruling came out more honest for it

*The provider bake-off's (C0) closing session — extraction+eval (M1). The decision
record is DESIGN.md's three C0 entries dated 2026-07-19 (envelope amendments · the
paired read + N-freeze · the ruling); this is the story. Feeds: the M1 report/post's
methodology section (the bake-off story, the measurement-honesty thread), and the
cost story wherever the report talks money.*

The bake-off closed today on DeepSeek v4-flash at ten reviews per request, and the
most reportable thing about the closure is that the winning argument had to survive a
correction first. Arda came in leaning DeepSeek — "deepseek looks behind gemini
models, but when we consider error bands, they overlap heavily" — and the lean was
right, but the reasoning under it turned out to be wrong in an instructive way. The
comparison table's confidence intervals (3 Flash n20 F1 .801 [.756–.840] vs v4-flash
n20 .767 [.717–.812], `probes/captures/bakeoff/TABLE.md`) do overlap heavily. But
every run in that table scores the *same* 250 gold reviews, and separate intervals on
shared data overstate the uncertainty of a gap — review difficulty is shared, not
independent. A paired bootstrap (each resample draws one set of review indices and
scores both runs on it — `paired_bootstrap_ci` in the evals core, exposed as
`--compare` in `probes/bakeoff_table.py`, 10,000 resamples, seed 20260718) reversed
the eyeball read at matched batch size: the Gemini 3 Flash gap is real, F1 +0.034
[+0.002, +0.067], driven by recall. The same test then closed the loop in DeepSeek's
favor: against v4-flash at its *best* batch size, the gap collapses to
indistinguishable (+0.025 [−0.004, +0.055]). So the ruling's honest sentence — the
one recorded in DESIGN — is not "they're the same": 3 Flash is measurably better at
matched N, the gap vanishes at the frozen N, and it costs ~12× more. The transferable
lesson is cheap to state and easy to forget: on a shared benchmark, "the error bars
overlap" is not a significance test, and the paired version can flip the call in
either direction — here it did both in one afternoon.

The batch-size freeze got the full-curve treatment because DeepSeek is the one
candidate with no quota wall to ration measurements. The four-point ladder
(`probes/captures/bakeoff/deepseek-v4-flash/{n5,n10,n20,n50}/`, every run 250/250
with zero parse failures) came out .746 / .776 / .767 / .762 — a peak at n10 with
two-sided paired evidence: n10 beats n5 on F1 (+0.029 [+0.009, +0.052]; below the
peak, precision decays — the same over-extraction pattern flash-lite's ladder showed
at n5) and beats n50 on recall (+0.042 [+0.013, +0.073] — the depth-dilution
direction every ladder showed). What makes N=10 a pure quality call is that the other
two axes washed out. Cost: the true, cache-adjusted numbers (computed from the
provider bodies persisted in `probes/captures/bakeoff/bakeoff.sqlite3` — DeepSeek's
usage reports the cache hit/miss split) put a 250-review measurement at $0.0072 at
n10 (91.3% cache-hit; the ~6.5k-token codebook re-sent per request bills at ~98% off,
so the repeats are nearly free and n10 is *cheaper* than n20 despite 3.7× the prompt
tokens), survey extrapolation ≈ $1.4 at any N on the ladder. Time: sequential wall
time spreads 3.9–6.2 hours across the ladder at survey scale, but DeepSeek's envelope
is concurrency-only (2,500 concurrent requests, no rate or daily caps), so any
concurrency in the C1 driver collapses the difference. This also closed the honesty
rider from yesterday's batch-size amendment on the best possible terms: the free-tier
request quotas that had motivated maximizing N don't bind a paid concurrency-only
winner, and the freeze went to the measured quality peak, not the operational ceiling.

The closure itself was a set of deliberate exits rather than finished rows, and the
report should own that. The two remaining free-tier completions (Gemini 2.5 Flash
n50, nemotron's last 3 reviews) were skipped by decision — both rows belong to
non-contenders that could only decorate the table below the leader, and the
output-ceiling raise (another of the day's fixes: the day-one formula truncated dense
batches at five providers, cut exactly at the cap; the new one derives from measured
worst-case demand) had invalidated their cheap cache-warm reruns anyway. Ollama
closed unwired as a value exit: the serverless argument (a labeler living on a local
GPU can't serve the eventual live path) had always limited local to the one-time
survey batch, and a $1.4 survey floor collapsed the remaining pitch to "save a dollar
against 8B-quantized quality risk plus a wiring session." And a
Gemini-free-until-quota-then-DeepSeek fallback hybrid — Arda's own floated idea — was
rejected on measurement integrity: free quotas would have labeled under 1% of the
pool while making every per-game aggregate a mix of two error profiles, and the judge
(D2) calibrates against one labeler. The savings ceiling was the ~$1.4 it competed
with. Provider fallback re-enters at deployment (M3) as an availability question,
where it belongs.

Figure: the v4-flash dilution curve (F1 vs N with CIs, peak at n10) beside the
paired-gap chart (matched-N vs best-vs-best, CI bars against zero) — the two panels
tell the whole ruling; data regenerates from `probes/bakeoff_table.py` and
`--compare`.

*The provider bake-off (C0) of extraction+eval (M1) — the scorer/runner build
session, one day after the protocol froze. The amendment is DESIGN.md's "C0
bake-off: the scorer/runner design + the batch-size amendment" entry
(2026-07-18). Feeds: the M1 report/post's methodology section (the bake-off
story), and the eventual C0 ruling record.*

The protocol was one day old when one of its frozen clauses failed contact
with reality — and the failure is more instructive than the clause. "Batch
size held at the B4 pilot's values" was written as a parity rule: every
candidate labels reviews in same-sized batches, so the comparison stays clean.
But the pilot had only ever measured N≤5, and when the build session proposed
N=5 as "the measured value," Arda pushed back on production grounds: free
tiers cap daily *requests*, so at five reviews per request the ~50k-review
survey buy is ~10,000 requests — weeks of grinding against a 250–500
requests/day quota — while N=50 cuts it to ~1,000. The challenge escalated
across three exchanges (probe N experimentally → probe high Ns, 20/50 → why
pick one N at all?) and the endpoint reframed the rule entirely: batch size
moved from the parity column to the part-of-the-product column, joining
structured output. Each candidate now runs at its own N = min(envelope max,
dilution ceiling) — envelope max computed from the provider's own token caps
(the output ceiling binds long before context windows do: at ~120 output
tokens per review, an 8k-output model tops out near N≈60), dilution ceiling
established by an N-probe that no longer picks a winner but maps the
quality-vs-N curve, on two structurally different free models (Gemini 2.5
Flash and Groq Llama 3.3 70B — two, so the ceiling isn't quietly tuned to one
vendor's comfort). The amendment carries an honesty rider in DESIGN: the
free-tier request quota is what motivated maximizing N, so if the survey buy
ends up on a paid tier — where request quotas stop binding — the record shows
high N was an operational choice, not a quality-driven one. The transferable
lesson: a parity rule is only as good as the range it was measured over, and
"held constant" quietly becomes "held at an untested value" when the constant
came from a pilot that never probed the production regime.

The session's second story cost nothing and calibrated everything. The
protocol had already promised a reference line — the gold-assist model scored
against the final gold it helped draft — and the new scorer made it real
within minutes of existing: claude-sonnet-5's assist drafts against Arda's
adjudicated gold land at precision 0.857 [0.815–0.894], recall 0.970
[0.950–0.987], F1 0.910 [0.880–0.934], sentiment accuracy 0.920 [0.889–0.951]
(the persisted drafts in `eval/gold/assist/raw` scored by
`probes/bakeoff_table.py`, 95% bootstrap CIs from 10,000 resamples over the
250 gold reviews, seed 20260718; table at `probes/captures/bakeoff/TABLE.md`).
The asymmetry is the readable part: recall 0.97 means Arda added almost
nothing the assist had missed, while precision 0.857 means he corrected away
roughly one in seven of its claims — adjudication was mostly deletion and
repair, not discovery. That number pair is now the field's ceiling: a
free-tier candidate approaching F1 0.9 is performing at the level of the
frontier model that drafted the gold itself. The diagnostics cohere with the
story (assist zero-share 44.8% against gold's 49.2% base rate; candidate
emission 4.8% against gold's 5.1%; 7 of gold's 11 candidate labels
independently emitted), which is quiet evidence the scorer's definitions are
measuring what they claim to.

One definition got sharpened by its own test. The gold mint's headline said
"11 candidates," and the scorer's real-artifact round-trip test — which
re-resolves every gold label through the same normalization index the
candidates will face — failed with 18. Not drift: the mint counted 11
*distinct labels* (the `candidate_labels` list in
`eval/gold/gold_manifest.json`) across 18 mention *instances*. The
consequence is small but real: the protocol's candidate-emission reference
("gold's ~3%") is actually 18/351 ≈ 5.1% of mentions, and the comparison
table now says so. A test that failed by disagreeing with a summary statistic,
and was wrong *because the statistic's units were ambiguous*, is exactly what
the round-trip test exists to catch — the cheap version of a measurement
dispute happening before any money moved.

[PRELIMINARY — one request, five reviews] The first live smoke
(gemini-2.5-flash, N=5, `probes/captures/bakeoff/gemini-flash/n5/`) previewed
the bake-off's expected dynamics in miniature: solid overlap with gold on the
obvious aspects, two gold labels missed, a handful over-extracted, and — most
telling — both of the review's hard-won `mixed` sentiment rulings flattened
to `negative`, precisely the directional failure the frozen metrics keep
precision and recall separate to expose. Three of five reviews needed an
evidence-quote repair (the verbatim check nulled a sloppy quote while keeping
its mention), flagged as a per-candidate watch item for the scored runs.

The session closed by measuring where the input tokens actually go, and the
answer reframes the whole cost conversation: the fixed classify prompt is
~7.2k tokens, and 88.2% of it is the codebook — the 51-aspect contract
rendered full-fidelity (measured on section-character shares over the real v1
ontology artifact; token shares are approximate but the dominance is robust,
and the derivation is a rerunnable one-liner over `core/classify`'s render
functions). Chained with the batch arithmetic, at N=20 roughly 78 of every
100 input tokens are codebook; even at N=50 it's ~63%. The reviews — the
data — are a rounding error next to the contract for reading them: we ship a
6,300-token rulebook with every 50 reviews. The day's provider geography had
already demonstrated the consequence live, before the number existed: Groq's
free tier suffocated because its token walls are codebook-sized (a single
request couldn't fit the rulebook for the 8B and both gpt-oss models —
rejected before generating a token), while the same measurement explains why
prefix caching is disproportionately valuable here — the prompt was built
stable-prefix/variable-suffix from day one, and a provider that discounts
cached prefixes (DeepSeek's 98%-off cache-hit input pricing, from the
landscape scan) prices the codebook mass at nearly zero on every request
after the first.

Arda's directive, verbatim in spirit: we need to find a way to reduce the
codebook problem. The pre-registered compact rendering (decision surface
only — definition + label_when + do_not_label_when — pre-registered in
DESIGN's classify-prompt entry as both cost fallback and first prompt
experiment) now has its price tag: it competes against an 88%-of-prompt
payload, an estimated ~60% token reduction if quality holds (estimate
contingent on the compact rendering's actual rendered size), and "does a
leaner rule set beat a muddier context" stays a measurable question for the
judge phase (D2), not an arguable one. Two unexplored directions in the same
family, parked: aspect-subset routing (send only the categories plausibly
present in a batch), and distilling the eventual survey labels into an
embedding-based student classifier — discussed this session and scoped as a
deployment-latency play (M3), explicitly not a bake-off candidate, because
embeddings do similarity and the codebook's hard cases are rule-following.

By day's end the table held 18 full-slice captures across 9 models and 4
providers. A late entrant proved the pool-widening worth it: Tencent's
Hunyuan 3 (a free OpenRouter route) landed fourth at F1 0.759 (N=20) with
the field's most faithful candidate-emission rate — 5.0% against gold's
5.1%, where every other candidate either dumps or dries up. And the tokens
in/out column added to the comparison table turned out to double as a
fragility signal: recovery retries visibly inflate a candidate's bill —
Hunyuan's N=20 run cost 248k prompt tokens against Gemini 3 Flash's 106k for
the same 250 reviews, the difference being ~21 extra codebook-carrying
requests its parse failures needed (`probes/captures/bakeoff/TABLE.md`,
regenerated with the token column).

Figure: the quality-vs-N curve from the N-probe (once run) — the empirical
justification the batch-size amendment is betting on; the final comparison
table with the assist reference line drawn as a horizontal band the
candidates are read against; and an input-token composition bar (codebook vs
rules vs format vs reviews, per batch size) — the single image that makes
the codebook problem legible.

## 2026-07-17 — The bake-off protocol: the scan dissolved its own cost question, and the gold set retired its own proxy

*The provider bake-off (C0) of extraction+eval (M1) — landscape scan + protocol
design, the six-fork discussion recorded as DESIGN.md's operational-decisions
entry of 2026-07-17. Feeds: the M1 report/post's methodology section (how the
survey labeler was chosen by measurement), and possibly a standalone "choosing
an LLM vendor by measurement" piece.*

The bake-off was framed with "cost per 1k reviews" as one of its headline
metrics — and the first real thing the protocol session did was measure that
metric into irrelevance. A four-way landscape scan (Gemini, Mistral,
Groq+Cerebras, DeepSeek+OpenAI, each verified live against official docs where
possible, 2026-07-17), anchored on the classify pilot's measured prompt shape
(~7.3k shared prompt tokens per batch call, ~100 marginal input tokens per
review — the B4 pilot capture; output assumed ~100/review), put every realistic
candidate under ~$20 for the *full* ~50k-review survey buy, before the 50%
batch discounts that turn out to be near-universal. The cheapest row (Mistral
Nemo) labels a thousand reviews for about a cent. So the provider choice
stopped being an economics question and became a pure quality question —
agreement against the gold set — with cost demoted to tiebreak. Free tiers
cover the 250-review gold slice almost everywhere, so even the measurement
round is roughly free. Two candidates fell out at the table: Cerebras (a hard
5-requests-per-minute free ceiling, batch only as an enterprise product, and a
headline speed that sells latency — a non-goal for a batch labeling job) and
OpenAI (no free tier, nothing distinctive at its price). Arda ruled
free-tiers-first for round one; paid tiers re-enter only as a throughput
upgrade for a winner, or as tier escalation if nobody proves buyable. A small
scan footnote worth keeping: an aggregator listed Mistral's free tier at "2
requests per minute," and Arda suspected the unit itself — per second, not per
minute. Mistral's own help page confirmed the API's limits are stated in
requests per *second* (exact numbers hidden in the account console), which
flips that tier from the pool's slowest to plausibly one of its fastest. The
aggregator-sourced cells are flagged for spot-check before anything binds.

The protocol's most report-worthy move is a metric being retired by the
instrument that superseded it. Zero-share honesty — how often a labeler
honestly says "this review mentions nothing" — was the bake-off's named metric
because it was the *only* honesty proxy available when the cheap Gemini tier
(flash-lite) was caught over-extracting during ontology calibration (31%
zero-share vs flash's 62%, the calibration entry in `ONTOLOGY_PRUNING.md`) —
measured, at the time, with no gold set in existence. With gold now defining
the true base rate (49.2% of the 250 gold reviews carry zero pinned mentions),
mention-level precision/recall prices the same dishonesty directionally:
fabrication bleeds precision, timidity bleeds recall. So zero-share was demoted
to a diagnostic — the readable summary of the story, no longer the score. The
same subsumption argument settled the free-form candidate slot: slot
discipline is auto-priced by the pairing (forcing a pinned label where gold
ruled candidate is an automatic precision hit; cowardly routing of real
aspects into the candidate slot is a recall hit), so candidates stay out of
the score entirely — gold's n=11 couldn't support a metric anyway — with a
candidate-emission-rate diagnostic (against gold's ~3%) watching the one
loophole, dump-everything-into-candidates. The frozen metric set: pinned-slot
mention-level precision/recall/F1 (always reported separately — the known
failure mode is directional), flat sentiment accuracy on matched pairs only,
and a single hard gate at 2% unrecoverable parse failures, with failed
reviews scoring as empty predictions rather than being excluded — exclusion
would flatter exactly the providers that fail most.

The decision rule produced the session's one genuine negotiation. Claude
proposed a fully pre-committed lexicographic ladder (rank on F1, error-bar
ties escalate through sentiment accuracy → variance probe → cost) as a guard
against post-hoc rationalization. Arda pushed back: he wants the full results
table in front of him, then he rules. The resolution kept the part of
pre-commitment that actually does the guarding — the metrics were frozen
before any run exists, and the eventual ruling must land in DESIGN with its
recorded why — while dropping the ranking machinery. The distinction that
settled it: pre-registration protects hypothesis tests; a procurement-style
choice over already-frozen metrics is honest as judgment, provided the
rationale is recorded. Two pieces of information ride with the results table
in place of rules: a reference line — the gold-assist model's own F1 against
final gold, computable for free from the persisted assist drafts
(`eval/gold/assist/`), banned from competing but calibrating what "good"
looks like for the field — and a standing no-buy exit: the bake-off may
conclude nobody is buyable, and the recorded outcome is then tier escalation,
never buy-the-least-bad. One parity rule with teeth rounds out the protocol:
the classify prompt runs verbatim for every candidate, no per-model tuning —
tuned prompts would measure our tuning effort, not the models — while
structured output is deliberately *non*-parity (each candidate's best native
mechanism, recorded per row), because schema enforcement is part of the
product being bought and flattening to the weakest mode would erase exactly
what the parse-failure gate exists to measure.

Runs will land in `probes/captures/bakeoff/<provider>/` with per-run
manifests; headline numbers carry 95% bootstrap CIs resampled over reviews.

Figure: the provider comparison table (cost per 1k reviews vs free-tier
coverage vs schema support); later, the bake-off results table with CIs
against the assist-model reference line.

## 2026-07-17 — The gold pass starts interrogating the ontology: two kinds of mixed, and the pins that are secretly dispositions

*The gold adjudication pass (D1) of extraction+eval (M1), ~45 of 250 reviews in,
nine residual rulings landed (`eval/gold/INSTRUCTIONS.md` §9, entries 20–29, all
dated 2026-07-17). Feeds: the M1 report/post's ontology section and the v2
roadmap; the parkings live in `ONTOLOGY_PRUNING.md`'s post-ratification section.*

Labeling real reviews against the ratified ontology did something the design
sessions couldn't: it made the ontology explain its own shape, twice, both times
because Arda refused to accept an answer that was technically correct but felt
wrong.

The first refusal came at a Bannerlord review (batch 5) that praises field
battles and criticizes siege control — one `combat` pin, both charges present,
so the contract says `mixed`. Arda's objection: our aspects are umbrellas, and
calling this mixed "feels off," because nobody in that review is ambivalent
about anything. Pulling on that thread separated two generating processes the
`mixed` value conflates: **true ambivalence** (one referent, both charges —
"fun but repetitive") and **umbrella collision** (two sub-referents with clean,
opposite polarities, collapsed by pin granularity — battles great, sieges
clunky). Downstream, `combat: 30% mixed` cannot distinguish "players are torn
about combat" from "players love battles and hate sieges," which are very
different product insights. Worse, the strain is structurally invisible to the
promotion path: a siege complaint has an honest pinned home, so it never enters
the candidate pool — umbrella pressure leaves no candidate-stratum trace at
all. What it does leave is a signature: **per-pin mixed-share**, especially
within-review mixed, which is now parked as the v2 diagnostic instrument — a
pin whose mixed-rate runs hot at survey scale is a split candidate (combat →
field battles / sieges), and the split then has to earn its place by the same
clustering bar every pin faced. The write-time policy deliberately stays
mixed-plus-verbatim-spans: under collision that is the information-preserving
record (the spans carry which sub-thing each charge hit, so read time can
decompose), whereas forcing the dominant polarity deletes the minority charge
irreversibly. When the granularity is wrong, record more structure, not less.

The second refusal came at a one-line review ("Plot twist so hard I had to sit
in silence after," batch 5): Arda challenged `emotional_impact` as structurally
suspect — "it is always the result, always the effect of something; it is not a
property of the game." The resolution that held: it records a **dispositional
property** — like fragility in a glass that hasn't broken, the game's capacity
to affect, evidenced by player reactions. "I cried twice" isn't recorded as the
reviewer's state; it's evidence that this is a game that makes people cry. That
lens exposed a family the ontology holds without saying so: intrinsic-design
pins (combat, level_design, servers_netcode) versus experiential-disposition
pins. Arda's own placement of the boundary is worth preserving: addictiveness
and relaxation are pure dispositions, but difficulty and learning_curve are in
his reading design-anchored (tuning numbers and onboarding structures exist in
the game itself) — a spectrum rather than a binary, and his framing. The lens
also deepened an existing ruling: memorable-X routing (effect attributed to a
named aspect → that aspect wins) is really the disposition *localizing* — "the
story moved me" claims the story is moving — while unattributed effect-talk
falls back to `emotional_impact`, the whole-game disposition bucket. Which is
exactly the fallback architecture the codebook already declares twice
(`gameplay` for play-talk, `multiplayer` for online-talk); effect-talk had a
fallback too, it just hadn't been named as one. Rule 1's boundary restates
cleanly in the same vocabulary: a reaction that characterizes the game labels;
autobiography where the game is a prop ("I was depressed and this helped")
claims no generalizable disposition and doesn't.

The v2 watchlist as it stands after today (all parked with evidence and reopen
conditions in `ONTOLOGY_PRUNING.md`): **fun_factor** — addition candidate; must
pass per-game clustering once the fun-talk ruling (§9 entry 24) makes
anchored-vs-bare fun measurable for the first time. **achievements** — declined
at v1, reconsideration queued on gold-pass candidate evidence (`achievements`,
`achievement hunting`). **uniqueness/creativity** — addition candidate from the
accumulating quality-candidate cluster (originality ×2, unique, and a
typo-preserved "vreatice"). **The mixed-share instrument** — the umbrella-strain
detector above. And Arda's open consideration [PRELIMINARY — his instinct, not
a decision]: whether pure-disposition pins belong in the pinned set at all,
against the counterpoint that v2 changes ride the clustering evidence bar, not
ontological classification — a disposition that clusters where the number
matters (relaxation on cozy games) mints exactly the number its buyers come
for.

Figure: the two-kinds-of-mixed diagram — one referent with both charges vs. two
sub-referents with clean polarities under one umbrella pin — is a natural
before/after for the ontology section.

## 2026-07-16 — The dry run catches its own answer key, and the fold that felt wrong turns out to be the other track's story

*The gold-set (D1) acceptance-test arc of extraction+eval (M1): the labeling
instructions' dry run, run the same day the drafting interview closed. Feeds: the
M1 report/post's gold-set methodology section.*

The dry run nearly began by grading against a published answer key. The plan on
record said "Arda labels 2–3 dev-slice reviews from the doc alone" — but between
writing that plan and executing it, all six dev-slice reviews had become the
instructions document's own worked examples, answers printed in section 7. The
catch is worth keeping because it names a general trap: material a document
*teaches from* is disqualified as material to *test* that document, and exclusion
lists compound quietly. The fix drew three fresh reviews instead — seeded
(seed 20260716, rule and ids in `eval/gold/dry_run/round1/manifest.json`), one each from
Helldivers 2, Disco Elysium, and Euro Truck Simulator 2, games deliberately outside
the worked-example pair so the doc got tested on vocabulary its examples don't
cover — and those three ids joined the gold-exclusion ledger for exactly the
dev-slice reason: the instructions were about to be iterated against them.

The draw landed almost uncannily ruling-shaped reviews — a sarcastic servers rant
ending in a mock-thanks "UPD:", a lukewarm-vs-mixed Disco Elysium opening followed
by "I'll never forget its characters and atmosphere" (a coordination of exactly
the shape Arda's counterexample had exposed the day the instructions were
drafted), and a dense ETS2 paragraph packing five or six routing decisions into
four sentences. Honesty requires noting this was seeded luck, mostly — though the
draw's 200–2,000-character window deliberately biased toward aspect-bearing text,
since bare verdicts test nothing the worked examples hadn't.

The unaided pass held where it mattered most: the sarcasm did not flip Arda's
polarity, and the addictiveness/realism/dlc routing came out clean. The misses
concentrated almost entirely in **multi-label recall** — second and third mentions
left unlabeled (a sarcastic developer-conduct jab inside the UPD, a "really good
rendering," a "base game is plenty") — rather than in wrong routing, which is the
better failure mode to have: the codebook's boundaries held; the discipline of
sweeping a review for *every* evaluated property is what needs the assist model's
help. One small drift earned a process rule: an evidence quote retyped by hand
came out "suprisingly" where the review says "surprisingly" — a fabricated span by
the eval's own strict definition. Copy-paste-only was already a doc line; it is
now a workflow rule, and the assist pre-annotation makes it the default (accepting
a pre-filled span beats typing one).

Five rulings came out of the pass, settled interview-mode and applied to the
instructions the moment each landed (the §9 ledger, entries 8–12). Memorability
attributed to named aspects routes to those aspects, with `emotional_impact`
reserved for effect-talk naming no subsystem. Concessive comparisons are not
charges — "isn't the total Microsoft Flight Simulator level recreation I would
have liked, but feels surprisingly realistic" stays positive; this one was Arda
correcting the assistant's mixed-leaning read, and the correction generalized
cleanly. Reviewer-folded enumerations got the **independently-evaluated test**,
and it was fought to its final shape from both sides: Arda held that bare
enumerated contributors ("there are accidents, weather conditions and live radio
stations") stay inside the immersion mention as evidence — correct — and conceded
after pushback that "the trucks handle well" carries its own polarity claim and
mints its own mention. Ambiguous referents ("rendering": image quality, or
rendition-of-Europe?) fold into the adjacent mention context supports, never
minting a separate one. And review updates fold like ordinary text.

That last ruling carried the entry's real story. Folding an UPD reversal ("was
broken; UPD: fixed, great now") into `mixed` felt wrong to Arda — it erases which
way the reviewer *moved* — and the discomfort dissolved only when the trajectory
was recognized as belonging to the other track entirely. The fold deliberately
discards a story, and it must: the survey track mints numbers, and the two-track
rule forbids numbers from carrying stories. "Which reviews were edited after the
patch, and did they flip?" is investigation-track material — and Steam hands the
signal over structurally (`timestamp_updated` vs `timestamp_created` on every
review row), no UPD-marker parsing required. The idea is parked in the stream's
IDEAS.md as an investigator (M4) lens. What looked like a labeling-rule
disagreement was actually the architecture explaining itself.

One asymmetry stays open by design: two of the boundary rulings (memorable-X and
base-vs-DLC content scoping) live only in the human wrapper for now, because the
codebook section is generated from the content-hash-pinned ontology TOML — the
machine sees them at the v2 wording batch (the FIXLOG carries the list). Until
then, human-vs-machine disagreement on those two boundaries is *expected*, and
the eval reader should charge it to the version skew, not the classifier.

The document came out accepted: status flipped to dry-run-accepted, version
de-drafted to `gold-instructions-v1`, and the acceptance record — Arda's unaided
pass preserved untouched, with the post-discussion consensus labels and their
diffs beside it — lives in `eval/gold/dry_run/round1/SHEET.md` (committed same day).
Twelve rulings stood behind the instructions at that close: seven from the
drafting interview, five from the dry run. The acceptance held for roughly one
exchange.

**The continuation, same day: the test becomes a protocol, and the stopping rule
turns out to be the wrong shape.** Arda asked whether one round was enough, and
the honest answer turned the acceptance test into an iterated protocol: rounds
2–4, each drawing three fresh seeded reviews from codebook regions earlier
rounds left untested (round 2: Overwatch 2 / Hollow Knight / The Day Before;
round 3: NBA 2K23 / Darkest Dungeon / No Man's Sky; round 4: Undertale / Path of
Exile / Rust — seeds 20260717–19), under an explicit convergence rule: a round
settling zero new rulings declares the document converged.

Round 2's best finding was an accident. The Hollow Knight draw came out Spanish
despite the corpus row claiming `language=english` — the Steam language field is
reviewer-selected, and there is now corpus evidence that it lies. The
non-English skip-and-redraw rule got exercised for real rather than
hypothetically, and a design constraint fell out: the real gold draw must be a
seeded **ordered** sample, because a skip needs a defined "next," and per-game
random choice has none. The round's three rulings (ledger 13–15): trailer /
marketing misrepresentation routes to `developer_conduct` — "broken promises"
was already its alias, no new label needed — with the rider that a summary
genre-verdict over a complaint list ("wasn't really a survival game") stays
unlabeled; in-game dupe exploits are `bugs`, never monetization, cheating only
when other players wield them; and absence routes to the owning pin ("no melee
weapons" → `combat`), the candidate path serving systems with no pin ("a weird
exfil system").

Round 3 produced the arc's most consequential ruling, and Arda walked into it
through his own honesty. He labeled Darkest Dungeon's "Visuals and audio 10/10"
as `art_style` — correct about the game, whose hand-drawn 2D style is celebrated
— then asked in his own friction note how a model could possibly distinguish
that. It can't: `build_classify_prompt` receives review texts only, no game
name, no app id. So the **evidence horizon** was ruled text-alone for both
annotators — world knowledge may resolve vocabulary ("dupe" means duplication
glitch) but never referents — and the generic visuals-praise corrected to
`graphics`. His follow-up probe (couldn't the model deduce the game from its
batch-mates?) hardened into a design stance worth quoting in the report: batch
composition is an accident of the pipeline, not evidence — a label must be a
function of (review text, codebook) alone, or the same review labels
differently across runs and both reproducibility and the classify cache die.
The round's other ruling: a single-player mode gated behind decommissionable
servers is `platform_access` (the DRM/login-required family), `developer_conduct`
joining only where conduct is separately charged ("but wow, this is egregiously
scummy").

Round 4 added two more, one of them Arda's routing prevailing over the
assistant's recommendation — credit runs both directions in this arc: "the
constant cycle of nerfs" charges the update *practice*, not the resulting build
variety, and the assistant conceded on the document's own
label-the-concrete-cause precedent. Generalized as **pattern vs. state**: a
charge against the post-launch pattern → `updates`; a charge against the
resulting state → the affected system's label. The other: **anecdotes are not a
category**. The Rust review — a raider finds the reviewer destitute, rebuilds
his base, gifts him 5k scrap, leaves "a cool little note" — mints zero
mentions, because nothing in it evaluates a game property; an anecdote
*carrying* an explicit evaluation labels normally, the story serving as
evidence.

Then the convergence story, which is the part the report should tell. The
ruling rate ran **5 → 3 → 2 → 2** and stopped decaying — and reading the
*kinds* explained why. Structural rules (sentiment vocabulary, evidence policy,
the folds) never moved after round 1. What kept arriving was additive routing
precedents, roughly two per round — and at three reviews per round against a
~50-label boundary space, those are effectively inexhaustible. The zero-ruling
criterion was wrong-shaped, not the document unstable. Ruled (Arda,
2026-07-16): retire the criterion, declare the instructions **GOLD-READY**, and
route residual precedents through the channel the real pass already owns —
every assist-vs-annotator disagreement or flagged uncertainty triggers the same
one-question mini-interview the rounds ran, new precedents append to the ledger
dated, and structural rules are frozen: changing one forces an
instructions-version bump and an explicit relabel decision, taken deliberately
or not at all. The transferable lesson, stated for reuse: a stopping rule
should measure the risk it guards against — here, relabeling-forcing changes —
not the raw count of findings.

One running gag earned a serious conclusion. Four rounds produced four
*distinct* evidence-transfer defects — a retyped "suprisingly," an editor
silently collapsing a double space, a stitch joining two spans with a rewritten
question mark, a stitch across paragraphs — human span-transfer failed a new
way every single round. The real pass pre-fills evidence spans via the assist
model and Arda adjudicates; he never transcribes.

Provenance: the full ledger is INSTRUCTIONS.md §9 (nineteen rulings); the four
acceptance records — unaided passes preserved, consensus diffs beside them —
are `eval/gold/dry_run/round<N>/SHEET.md`; draw seeds 20260716–20260719; the
residual channel is INSTRUCTIONS §8. Committed by Arda 2026-07-16.

Figure: the unaided-vs-consensus label diff as a small table — reviews down
the side, mentions across, misses marked by kind (recall vs routing) — is the
natural visual for "what a dry run buys" in the methodology section. Its
companion is the ruling-rate curve (5 → 3 → 2 → 2) annotated by kind,
structural vs routing — the argument for retiring the convergence criterion,
drawn.

## 2026-07-16 — The provider question inverts the roadmap: gold first, then the bake-off, then the buy

*The provider-strategy discussion opening the C1 (corpus-labeling driver) arc of
extraction+eval (M1); it resequenced the roadmap so the hand-labeled gold slice
(D1-lite) now precedes both the provider choice and the first label buy. Feeds:
the M1 report's methodology/eval section (provider choice as a measured decision,
model-per-stage tiering) and likely an M1 post arc of its own.*

The session was heading for the corpus-labeling driver when Arda stopped it with a
sharper question: aren't we near the point where the LLM provider effectively
fixes — where optimizations start accreting around whichever model we run — and is
Gemini 2.5-flash actually the one to marry? The discussion's first job was locating
where that hardening really lives, and the answer split cleanly in two. Not in the
code: the provider seam was built for swappability — the per-stage routing table is
config data, a provider is three protocol-typed callables, and the entire Gemini
adapter is 152 lines (`src/steamlens/llm_client/`). The lock-in lives in **data
gravity**: bought labels key to the model that produced them, calibration knowledge
(the bare-verdict-filter measurement, the trailing-JSON quirk handling) is
per-model, and every prompt refinement tunes to whichever model runs it. After the
first paid corpus run, switching stops being a config edit and becomes
relabel-plus-recalibrate.

Two facts keep the door open long enough to choose deliberately. The gold set is
hand-labeled, so the expensive evaluation infrastructure — gold plus the judge
calibrated to it — is provider-neutral by construction and never binds to a vendor.
And today's switching cost is only a ~$25 relabel [PRELIMINARY — estimated from
B4's measured pilot numbers (7,295-token prompt prefix per batch call, ~100 tokens
marginal per review; `probes/captures/classify_pilot/`) under a ~20-review batch
assumption and from-memory pricing; firms up when the bake-off runs live]. Cheap —
but the calibration and tuning knowledge compounds quietly, which is why the moment
to question the provider was now.

That reframing inverted the task order. The original roadmap labeled first (C1) and
evaluated later (D1/D2); but a hand-labeled gold slice built *first* turns the
provider choice from a vibe into a measurement — every candidate model runs the
same slice for roughly $1–3 and is scored against gold on agreement, zero-aspect
base rate, parse failures, refusals, and cost. The TODO's existing flash-lite pilot
note (free 500 requests/day against its measured weaker bare-verdict filter, 31%
vs 62% zero-share on identical reviews — the calibration entry in
`ONTOLOGY_PRUNING.md`) turned out to be this idea in miniature; the session
generalized it into a full provider bake-off, candidates to include the generous
free tiers on the fast-inference hosts (Groq/Cerebras-class) and possibly the
self-hosted 8B column from the design doc's tier table.

Arda's second idea folded in naturally: tier the models per task — ultra-fast/cheap
models for bulk labeling if they prove good enough, stronger models where they
earn their cost. The design doc already anticipates exactly this (the LLM tier is
decided per stage, not globally; the judge is always a stronger model than the one
it grades; routing is per-stage data), so the idea landed as sharpening rather
than change, and the sharpening is worth keeping: for batch labeling, latency is
irrelevant — the fast hosts' real draw is their free tiers and cost — while
latency starts mattering at deployment (M3), when a user is waiting on a report.
The two-track rule adds the elegant closing note: the report writer never mints a
number (aggregation is deterministic code), so a writer model's failure mode is
style and faithfulness, not wrong statistics — and the planned fabricated-quote
and numeric-grounding metrics check precisely that. The writer is a swappable
luxury; the labeler is the correctness anchor, which is why the labeler gets the
bake-off.

> ⚠ SUPERSEDED (this scope ruling only) by the 2026-07-19 census entry — both
> premises collapsed: the labelable pool measured 135K not 298K, and v4-flash's
> true cost priced the census at ~$3–6, not ~6× a $25 buy.

One scope ruling from the same discussion belongs in the record: the full corpus
(298,553 reviews) is deliberately *not* labeled. Certified numbers fold only the
fixed survey stratum (the two-track rule), so labels outside it mint nothing —
full-corpus labeling would buy roughly six times the spend for numbers the
aggregate would refuse to certify. The label buy targets a fixed per-game survey
slice, sized at the bake-off's end.

Figure: the bake-off scoreboard, once it exists — candidates × (gold agreement,
zero-share, parse failures, cost per 1k reviews) — is the natural table/chart for
the M1 report's provider-choice section.

## 2026-07-15 — The pruning pass measures the whole corpus in one night, and the priors lose

*The codebook pruning session for extraction+eval (M1), task B1's final tail —
ratification landed the same night (`v1.toml` at `version = "v1"`, 51 pins; every
ruling with evidence and reopen conditions in `ONTOLOGY_PRUNING.md`). Feeds: the M1
post's methodology story (evidence-driven codebook pruning; prior-vs-measurement), a
deployment-milestone (M3) design section (how reports present candidate-talk), and
the C1 cost-estimate session (the flash-lite lane note in the stream TODO).*

The pass opened on a known weakness: the aspect-vocabulary probe behind the codebook
covered five games, and the slate's genre skew starved exactly the rows under
question — no souls-like for camera, no competitive shooter for matchmaking, no
broken launch for stability. The plan was one gap-slate extension. Arda pushed it
further twice — first "go through 5 other games, make this data stronger," then,
when quota walls appeared, "continue adding until we hit the limit" — and the
extension snowballed into something the plan never promised: corpus-complete
evidence, all 49 usable games, ~4,900 reviews, ~7,500 extracted mentions, in one
night (captures in `probes/captures/aspect_vocab_ext/` and `aspect_vocab_lite/`;
label→pin mapping in `probes/pruning_evidence_table.py`).

The enabling discovery is worth the report on its own: free-tier quotas are
per-model. The pinned instrument (gemini-2.5-flash) hit its hard 20-requests/day
wall mid-run — but Arda, reading the AI Studio quota dashboard, spotted
gemini-3.1-flash-lite sitting at 500/day, and that turned a projected week of
daily drip into a 90-minute sweep. The methodological price was paid up front
rather than discovered later: a different model is a different instrument, so the
lite run opened with a calibration game the pinned instrument had already measured
(Elden Ring, identical task and pool). The calibration caught a real defect —
flash-lite's bare-verdict filter is much weaker (31% zero-aspect share vs flash's
62%; the excess is vague labels like "overall experience" that flash correctly
refuses) — and also showed the defect self-corrects for existence-counting, since
vague labels map to no pinned aspect and the real-aspect readings tracked flash
(~91 vs 88 mapped-relevant mentions on the same 100 reviews). Two instrument
hardenings rode along, both fail-loud-then-tolerate: a first-JSON-value parse that
discards flash-lite's occasional trailing output *visibly*, and
connection-error backoff after the home router's DNS twice flaked on exactly one
hostname. The instrument files carry the full record.

Then the priors started losing. The session's first recommendation — keep the
whole "genre-critical, probe-zero" class on faith, because the probe's five games
couldn't have surfaced them — died against its own targeted test: camera produced
zero mentions in 100 Elden Ring reviews, then one mention in ~1,900 (Dark Souls
III), across the two souls-likes where camera complaints are supposedly canonical.
Grind fell harder, and more instructively: "one of gaming's most common
complaints" by prior — an outside model reviewing a stale copy of the codebook
confidently demanded it be pinned — measured 15 mentions in 4,900 reviews and
never more than 2 in any single game, *including* Path of Exile, FFXIV, and
Darkest Dungeon, the grindiest games the corpus holds. The recommendation on grind
honestly flip-flopped (demote → toss-up → demote) as evidence arrived; Arda ruled
the drop. Meanwhile the same targeted tests rescued rows the skew had starved:
physics (~11 mentions the moment Goat Simulator / Garry's Mod / Surgeon Simulator
were sampled), pacing (Persona 5 Royal, Disco Elysium), ui (EU4, Democracy 3),
sound_design, level_design. Matchmaking crystallized the demotion criterion the
whole pass ended up running on: 16 mentions corpus-wide *but 11 of them in
Overwatch 2 alone* — the question is never corpus frequency, it's whether the talk
clusters on the games where the certified number matters.

The criterion earned its one caveat when Arda challenged servers_netcode — the
session's only keep-ruling that survived a real attack. The honest count looked
demotable: ~21 mentions, one genuine cluster (FFXIV's DDoS era), and Helldivers 2 —
the most famous server-meltdown launch on Steam — gave zero. But that zero is the
tell, not the verdict: a uniform-lifetime sample dilutes an event to nothing, and
the product samples *windows*. The same night's Phasmophobia capture demonstrated
the mechanism live — its sample happened to land mid update-backlash, and `updates`
exploded to 41-of-43 negative. Event-shaped aspects cluster in time, not just in
genre; judging them against uniform probes optimizes for a sampling design the
product doesn't use. Ruled keep, and the time-axis caveat went into the ledger's
criterion.

Endgame: 55 → 51 pins (camera, accessibility, localization, grind demoted — each
entry in `ONTOLOGY_PRUNING.md` records the merge alternatives considered and the
concrete condition that would reopen it), the corpus's addition candidates
(puzzles at 23 mentions/8 games the strongest) deliberately declined under the
genre-mechanics policy, and ratification the same night. One more artifact came
out of a side question — "can we generate a mock report, so I can imagine what
we're getting?" — answered with real probe data rather than lorem ipsum:
`mocks/phasmophobia_aspect_report_mock.html` renders the Phasmophobia sample as
the product's two-track page (sentiment-by-aspect bars over an evidence floor,
quote-grounded aspect cards, an uncertified "what else players talk about" section,
an investigation-track placeholder). Building it surfaced a real M3 design fork:
candidate-talk in reports must stay qualitative, because "players frequently
mention grind (negative-leaning)" smuggles an uncertified number through the back
door. The two-track rule turns out to constrain prose, not just tables.

Figure: the starved-rows before/after table (original 5-game counts → corpus-complete
counts, rescued vs demoted) — or the mock report's sentiment-by-aspect chart, which
is already built.

## 2026-07-14 — Serving the same report twice is the honest option, not the lazy one

*The closing Q&A of the store-layer (B5) design session, extraction+eval (M1) — a
product-level interrogation of the caching design rather than a build decision. Feeds:
the deployment milestone (M3) report's caching/freshness section, the sampling study's
(M2) framing, and a portfolio-vs-product post angle.*

Both turns of this story started from Arda's questions. The first exposed a naming
trap worth keeping for the report: the phrase "client-side caching" suggests the
user's browser, but in this codebase `llm_client` and `steam_client` are *API
clients* — backend modules that are clients *of* Gemini and *of* Steam — so every
cache in the design is server-side. What Arda wished the system had ("cache the
reviews on the backend, so different users searching popular games get reports
without going to Steam") turned out to be the committed architecture already: fetched
reviews persist in the store's reviews table, and a report cache serves repeat
queries — the cold path's stage 2 is literally "cache check → fresh `ReportDocument`
or miss" (ARCHITECTURE, the life-of-a-request table). The wish and the design agreed;
only the word "client" stood between them.

The second question had real teeth: if a user runs the same game twice, do they get a
report over exactly the same reviews? "This feels a bit wrong." The design's answer is
yes within a freshness window — and the defense is worth the report because it runs
through two different layers that are easy to conflate. The classify cache and the
label pool exist for *cost correctness* and carry no staleness question at all: the
same review under the same model/prompt/ontology versions is the same answer, so
re-paying for it is simply waste — bought labels are never re-bought (the
"never-re-paid" invariant from the LLM-client build). The report cache is where
staleness lives, and it is governed by a freshness rule plus a disclosure: the trust
panel states the report's age. Serving a cached report inside that window is
deliberate on two grounds. Cost: the cold path is the expensive path, and re-running
it per click would burn the budget caps the LLM client enforces. And statistical
honesty, the less obvious ground: the displayed numbers carry error bars, and two
fresh samples drawn hours apart would jitter *within* those bars while reading as "the
game changed" — a stable sample with a disclosed timestamp is more honest than numbers
that shuffle on refresh. The failure mode actually worth fearing is presenting a stale
report as current, and that dies by disclosure, not by re-fetching.

The keeper, though, is Arda's product counterfactual: in a real product — not a
portfolio piece — he'd grow the review pool additively, each run fetching more, every
report a little better than the last. The analysis that followed sharpened it into a
clean trade. The content-keyed cache makes additive growth *economical* — each
increment pays only for genuinely new reviews, the pool absorbs the rest — so cost is
not the obstacle. The real price is the estimator: an opportunistically accumulated
pool is a mixture over fetch moments, and a percentage folded over it estimates
nothing well-defined — no reference period, no known inclusion probabilities. A real
product absorbs that with dated strata, rolling windows, or weighted estimation —
genuine methodology work, and exactly the terrain the sampling study (M2) exists to
map. So the trade reads: fixed-sample plus disclosed age buys a defensible error bar
with minimal machinery; the accumulating pool buys ever-improving reports at the price
of a weighting scheme someone must design and defend. SteamLens picks the first side
because its thesis is honest numbers on a portfolio budget; a funded product could
justifiably pick the second — same trade, different side.

## 2026-07-13 — The labeling LLM on trial: overkill in tier, not in kind

*The prompt-design session for extraction+eval (M1), task B4 (`core/classify`) — the
six prompt/parse rulings landed in DESIGN's two `core/classify` operational-decisions
entries; this is the narrative around them. Feeds: the milestone report's methodology
section (why an LLM reads the reviews; the prompt-design decisions), and a possible
post-M1 optimization chapter (distillation).*

Mid-session, Arda put the whole approach on trial: the LLM was supposed to be the
storyteller — the final report, the narration — so why is one also labeling reviews in
the middle? Isn't that overkill for a mid-step? The cheaper alternatives got an honest
hearing and each died on evidence already in hand. A keyword/alias lexicon dies on the
probe's own data: the review vocabulary is flat and game-specific (top-15 grouped
labels cover only 28% of mentions, half of all mentions are single-game vocabulary —
probes/FINDINGS.md §6), so a lexicon misses "runs like a slideshow on my 3080" and can
never emit a free-form candidate, killing the emergent stratum by construction. A
trained classifier — the standard pre-LLM answer for what NLP calls aspect-based
sentiment analysis — dies on a chicken-and-egg: it needs thousands of labeled examples
that don't exist, and the ~250-review gold set can't be spent on training because it is
the eval anchor. Embedding similarity is a worse LLM, not a cheaper equivalent: no
sarcasm, no per-aspect sentiment, no candidates, and 55 per-label thresholds to
calibrate. The deeper answer is thesis-level: the labeling step is not plumbing that
happens to use an LLM — it is *the object M1 evaluates*. The gold set, the judge, the
agreement numbers, the fabricated-quote rate all measure this step; remove the LLM
from labeling and M1's deliverable doesn't get cheaper, it disappears. Where the
overkill instinct is right is *tier*, not *kind* — whether a small or self-hosted
model suffices for classification is already scheduled for measurement (the per-stage
tier decision at M1 exit, from the cost/quality table).

The trial birthed an idea rather than a reversal. Arda's proposal: if the LLM
annotates, use a *stronger* teacher offline to generate training data and distill a
student classifier for runtime — the canonical LLM-as-annotator + knowledge-distillation
pattern, independently reinvented. It survives scrutiny as a post-M1 candidate with
teeth: C1's corpus labels double as a free training set (an unplanned dividend of the
label-pool design), but a fixed-head student structurally loses the two things the
product sells — free-form candidates and verbatim evidence spans — and the teacher
must be *measured* before distilling, because the training data's quality is exactly
the teacher's gold-set error, compounded at scale. Its real rival is the local 8B
model behind the same seam, which pitches the same free inference with zero training
pipeline. Parked in the stream's IDEAS.md with its graduation trigger: the M1-exit
cost table landing in the corner where local quality disappoints and API cost stings.

The batching fork produced the session's turnaround, and the credit is Arda's. The
initial recommendation was one review per call, argued mostly from the cache: batching
would coarsen the content-keyed classify cache to whole batches and break the
"bought labels never re-paid" promise. Arda pushed back — batch size will obviously
need tuning, so why fix it at one? — and walking the layers under the push-back showed
the cache argument was substantially phantom: the never-re-paid promise actually lives
in the *label pool*, which keys per review (review, model, prompt version, ontology
version), so a driver that selects only unlabeled reviews before composing batches
re-buys nothing regardless of batch composition. The raw-response cache only ever owed
re-parseability. The ruling flipped to batch-native with size as config, one prompt
version serving every batch size. The same architecture then paid again at the failure
-policy fork: at temperature 0, re-asking an identical failed request re-buys the
identical wrong answer (and the cache would return it without even spending), so any
retry must vary the request — and failed reviews re-entering the driver's
unlabeled-selection loop regroup into *fresh* batches, which is exactly that variation,
for free. No corrective prompting exists anywhere in the system.

Two smaller finds worth the report's margins. First, a silent-and-fatal near-miss in
the structured-output ruling: Gemini's constrained decoding takes a response schema,
and the tempting move — encode the aspect field as an enum of the 55 pinned labels for
maximum enforcement — would have structurally forbidden the model from ever emitting a
free-form candidate, killing the emergent stratum at the decoding level with zero
error surfacing anywhere. The aspect field stays a free string (normalize resolves
pinned-vs-candidate deterministically); sentiment is the closed enum. Second, Arda's
question about when ontology edits stop being free moved a deadline: the free-edit
window was framed as closing when gold labeling (D1) starts, but bought labels and the
classify cache key to the ontology *content hash* — so the first paid corpus run (C1)
is an equal cost lock, the window closes at whichever comes first, and the pruning
pass must precede C1 or the corpus gets labeled against rows about to be demoted
(TODO resequenced accordingly).

## 2026-07-10 — Synonyms are not sub-concepts, and the gold set almost certified itself

*The ontology-authoring story from extraction+eval (M1), task B1 — plus the gold-set
methodology settled early, ahead of its own task. Feeds: the milestone report's ontology
and evaluation-design sections.*

The first candidate core came out of the probe data looking tidy: twenty-two labels,
each with a fat synonym list, covering two-thirds of all probe mentions. Arda read six
rows and found the flaw: `lore` was listed as a synonym of `story`, `voice acting`
under `audio`, `romance options` under `characters`, `immersion` pooled with `open
world`. Those aren't synonyms — they're distinct concepts folded together to
concentrate evidence. The distinction matters because the two failure directions are
asymmetric in this architecture: folding is *irreversible* (the label pool stores
mentions under the pinned label, keyed by ontology version — once a lore mention is
written down as `story`, no later analysis recovers it), while not-pinning is nearly
free (the candidate slot preserves an unpinned aspect's identity at runtime, and the
promotion path can pin it next version with real evidence). The rule that survived:
synonyms are surface forms of the *same* concept, nothing else; a distinct concept
earns its own slot or stays a candidate. No umbrella labels.

The same asymmetry, priced out, flipped the size instinct. The draft had assumed a
small core; the argument for generosity won: a pinned aspect that most games never
mention costs nothing at display (the classifier only labels what reviews say; the
evidence floor hides what's below threshold) but pays fully for the games where it
carries half the conversation — voice acting was the motivating case. And promoting
later isn't free: a version bump invalidates the content-keyed classify cache, so
pinning a crisp concept now is cheaper than promoting it after the corpus run. What
actually bounds the vocabulary isn't a number — it's that near-neighbor labels degrade
labeling consistency (the narrative cluster can only be sliced so thin before nobody
routes `story`/`writing`/`lore` the same way twice), and that rare pins ship with weak
certification. The bar that replaced "keep it small": crisp boundary, plausibly
load-bearing for some real class of games, no near-duplicates — landing the draft
near fifty pins instead of twenty.

The evaluation design then nearly ate its own anchor. The tempting scale move — let a
frontier model write a ten-thousand-review gold set — died on circularity: a gold set
authored by a model measures model-model agreement, not correctness, and frontier
models share systematic blind spots (Steam irony, mixed sentiment) that more examples
measure more precisely without ever seeing. The shape that survived keeps the human
anchor and buys the scale legitimately: diverse strong models pre-label, the human
ratifies everything (verification being several times cheaper than annotation),
disagreements get adjudicated, unanimous labels get audited at a sampled rate — and
the eval's reach beyond the human core comes from the LLM-judge, calibrated against
that core with stated error. Arda independently invented enriched stratified
sampling — recruit ~20 reviews per aspect so every pinned label has gold coverage —
and supplied its own correctness condition: a recruited review must carry *all* its
labels, not just the one that recruited it, or correct classifier output scores as
false positives. Two amendments made it sound: annotate each review exhaustively once
at recruitment (not re-reviewing the pool per aspect), and keep a randomly-sampled
core alongside the enriched strata — retrieval finds the findable mentions, and only
a random core can certify the corpus-level numbers and the empty-output behavior that
the fabrication metric lives on, since nearly half of real reviews carry no aspect at
all.

One structural addition closed the session's design work: child tags — proposed as a
way to make big aspects distinguishable — entered not as labels but as a routing rule.
An `includes` list per aspect ("progression *includes* endgame progression, pacing,
reworks — always label the parent") teaches the classifier and the gold labeler where
an aspect's edges are without fragmenting the numbers across taxonomy levels; any real
hierarchy gets *derived* from accumulated spans at v2, a measurement instead of a
guess. And the ratification itself was re-scoped honestly: the vocabulary is a
v1-draft with a designed revision point — writing the gold-set instructions is the
best boundary test there is, and the lock-in only becomes expensive after the corpus
labeling run pins the cache to a version.

## 2026-07-09 — The vocabulary decided itself, and the instrument kept changing under us

*The aspect-ontology decision story plus the free-tier field report, from
extraction+eval (M1) week 1. Feeds: the milestone report's ontology section and its
cost-table sidebar.*

The plan was simple: run open extraction over 500 reviews, see if a dozen labels
cover 90% of what players talk about. The answer arrived emphatically negative —
but the run itself became a story first. The probe burned through three models in
an afternoon: the newest Flash turned out to be quota-gated to 20 free requests
total (learned mid-run, from the error body, not the docs); its sibling
*out-thought its own output budget* — 7,865 hidden reasoning tokens on one
10-review batch, starving the JSON it was supposed to write; the workhorse that
finished the job was the previous generation with thinking switched off. Three
durable lessons rode along: the quota dashboard beats every third-party doc;
thinking tokens are billed output, so a model's sticker price understates its real
per-request cost; and per-model daily quotas make "the free API tier" a per-model
claim, not a provider-level one.

The vocabulary itself: 406 distinct labels for 704 mentions, and honest merging
collapsed them only to 313 — the flat curve was never surface-form noise. Half of
all mentions live in vocabulary unique to a single game: truck-sim players talk
about `realism` and `scenery`, farmers about `coziness`, Cyberpunk players about
`dlc` and `night city believability`. A fixed set would flatten exactly the
specificity this product sells. The ruling — hybrid with a fixed core — came with
its mechanics argued from first principles in conversation before anyone noticed
they were re-deriving the design doc's hybrid option: a pinned, versioned
vocabulary for the numbers; a candidate slot at runtime for what doesn't fit;
emergent aspects counted and shown, disclosed as uncalibrated; promotion into the
core offline, gated, version-bumped. Include-and-disclose, the house pattern,
third appearance.

*The data-trust story from the extraction+eval milestone's (M1) entry probes. Feeds:
that milestone's report section on validating inherited data, and the standing
"trust no raw data" theme.*

The design panel left a debt: the 298k-review corpus inherited from the prior
steam-reviews pipeline was fetched with Steam's defaults, and the smoke tests had
shown the default *windowed* listing silently blanks entire Valve-marked review-bomb
windows — legitimate reviews included. Was the corpus full of holes exactly where
events live?

The refetch said: five of the fifty corpus games carry marked windows, every one
showing thousands of recommendations in the histogram — and not one window overlaps
its game's corpus coverage. Zero of 298,553 corpus reviews fall inside a marked
window. Clean verdict, but for an uncomfortable reason: the corpus is clean by
*coverage geometry* — the capped recent-first walk simply never reached back far
enough to meet a bomb — not because the fetch was safe.

So the probe asked the sharper question the corpus couldn't answer: does a plain
default cursor walk — the corpus's exact request shape — actually skip marked
windows? Europa Universalis IV's window (Feb–Mar 2025) was recent enough to test
directly. The walk saw 7,597 reviews across 76 pages, sailed straight past the
window's start date, and returned **zero** reviews from inside it — while the same
window, fetched with `filter_offtopic_activity=0`, holds 1,892. Nothing in the
payload signals the omission: no gap marker, no short page, no count mismatch you
could notice without already knowing the window exists.

The narrative worth a report paragraph: the corpus was one calendar accident away
from silently missing the exact periods the product exists to explain, and no
validation *of the corpus itself* would have caught it — the holes only show against
an external reference (the histogram's `past_events`). "Trust no raw data" usually
means validating what arrived; this was about validating what *didn't arrive*.
Unfiltered fetching is now a data-integrity requirement, proven, not a design
preference.

## 2026-07-09 — Four designs argued; the criticism was the product

*The system-flow design story. Feeds: the extraction+eval milestone's (M1) report on
methodology, and a possible standalone post on adversarial design panels.*

The system flow — module boundaries, seams, data contracts — was settled through a
design panel: four proposals written blind to each other, each from a different framing
(smallest-thing-that-ships, contracts-that-never-refactor, failure-modes-backward, and
established-practice-with-provenance), then four adversarial critics with one job each:
break the design in front of them.

The blind convergence was itself a result. All four proposals independently produced
the same four-strata skeleton, the same two-door sampler seam, and — most strikingly —
the same answer to the open policy question (Valve-marked review-bomb windows count in
the numbers, disclosed, never silently excluded), each from different reasoning that
reinforced rather than repeated the others.

The adversarial round then did what convergence cannot: every single proposal claimed
its numbers-vs-stories separation was "structurally impossible" to violate, and every
single critic found a concrete bypass. The honest claim that survived is
defense-in-depth plus auditability — several independent walls and an audit trail, with
"impossible" banned from the docs. The critics also found a gap no proposal saw: the
system verifies quotes mechanically but nothing verified *numbers inside LLM-phrased
prose* — a phrasing model could write "roughly 40%" over a 27% aggregate and pass every
check. Numeric grounding (the quote-verification move, applied to numerals) entered the
design from criticism, not from any designer. And the panel's single best catch was
fatal-by-tracing: one design put the sampling policy inside the Steam client, which
would have meant the sampling study certifies a simulation while production runs a
reimplementation — a certified tolerance describing code that never ships.

The lesson worth a report paragraph: independent generation reveals what is *natural*
(four framings, one skeleton), but only adversarial reading reveals what is *true* —
and the best decisions in the final design (read-time derivation of bomb-window
membership, the label pool keyed by content instead of by sample, the numeric grounder)
came from neither proposals nor critics alone but from the collision. A design that has
not been attacked is a hypothesis wearing production clothes.

## 2026-07-09 — The free-host premise died during a smoke test

*The infrastructure story from the smoke-test milestone (M0). Feeds: the deployment
milestone's (M3) hosting decision and its report's "assumptions that didn't survive
contact" section.*

The smoke-test milestone's headline question was whether Steam answers API calls from
datacenter IPs — and the test vehicle was to be a hello-world container on HF Spaces,
the milestone frame's candidate free host. The vehicle never launched: the
create-Space form (2026-07-09) revealed that compute Spaces — Gradio and Docker
alike — now sit behind the PRO plan ($9/mo); only Static Spaces remain free. The
"free host" the deployment plan leaned on had been repriced out of existence between
the vision being written and the first probe being deployed.

Two consequences, both cheap because they arrived this early. The probe re-routed to
a GitHub Actions runner — same probe code, a datacenter IP all the same, zero cost.
And the hosting fork (HF Spaces vs. cheap VPS) rebalanced: with HF at $9/mo, the
~$5/mo VPS is now the cheaper option *and* the stronger DevOps story, inverting the
original cost-vs-control trade. The decision still lands in the deployment
milestone's design, but on corrected numbers.

The lesson worth a report paragraph: a verified assumption has a shelf life when it
describes someone else's pricing page. Platform terms are a live dependency, and the
smoke-test milestone earned its keep here by catching environment drift — not just
API shapes — before a single line of product code existed.

*The runtime-design story behind the two-track engine and the narrated investigation.
Feeds: M3/M4 reports, the launch post, and a possible standalone post (captured in the
content stream's idea backlog).*

The problem arrived in layers, each one closing a door:

**No database.** The product promise is live analysis of any game, but there is no
direct access to Steam's review corpus — only a public API. Analyzing *all* reviews of
a large game at request time is out of the question, so the first idea was classical:
**sample**. A few hundred well-chosen reviews should carry the aspect signal of a
quarter million.

**The API resists sampling.** Verification against the live API (2026-07-07) showed the
access surface is narrow: sequential cursor pagination only — no random access — at
roughly 200 requests per 5 minutes, with an intermittent short-batch bug and a
cursor-loop bug on the helpfulness sort. What survives is *stratified* access: filters
by recency, polarity, language — and an undocumented pair of date-window parameters
(the mechanism behind the store page's own graph) that allows jumping to a time window.
A defensible sample exists, but it is a *constructed* one, whose bias must be measured
rather than assumed away — which turned a limitation into a study (the sampling-honesty
milestone).

**The LLM resists speed.** Honest evidence counts ("criticized in 214 of 800 sampled
reviews") require classifying every sampled review individually — dozens of LLM calls
per analysis. On free-tier rate limits that is minutes, not seconds. The latency could
be bought down with a paid tier, but a deeper product problem remained hiding behind it.

**Fixed samples can't explain anomalies.** The feature that distinguishes the product —
"there's a spike in March; what happened?" — is structurally unreachable from any fixed
representative sample: 500 reviews of a 200k-review game contain perhaps a dozen from
the spike. No sampling policy fixes this; the sample is representative precisely by not
over-weighting March.

**The move that resolved all four at once: an agentic investigation loop, narrated
live.** Instead of one sample and one synthesis, the system works in rounds — a broad
survey first, then targeted pulls steered by what it found: a spike in the timeline
becomes a hypothesis, the date-window parameters fetch that month's reviews, and the
explanation is confirmed or withheld based on what they actually say. The runtime
narrates every step to the user — hypotheses labeled as hypotheses, findings promoted
only after their check passes. The narration converts the latency problem into the
product's most distinctive feature (a watchable investigation instead of a spinner),
the targeted rounds solve the anomaly-explanation problem, the windowed parameters find
their load-bearing use, and the sampling constraint stays honest because of one
structural rule: **numbers come only from the fixed survey sample; stories come from
the investigation; the two never mix.** Without that rule the adaptive loop would
poison the statistics it sits beside — adaptive sampling hunts the unusual by design,
so its fetches must never feed the percentages.

The general lesson, worth a report paragraph and possibly a post of its own: design
moves that solve one problem are routine; when constraints compound, the search should
be for the single move that collapses several — and its telltale is that it needs a
guard (here, the two-track rule) to keep its power from corrupting the rest of the
system.
