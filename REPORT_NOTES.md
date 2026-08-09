# Report notes — SteamLens

Raw material for milestone reports and posts: decision narratives distilled at the
moment they happen, so the reports can tell the story without excavating chat logs.
Append-only, newest first. Each entry is a self-contained story with its date and the
decisions it feeds.

---

## 2026-08-09 — The ledger joins the bill: a public ops page catches its own 5x accounting fiction on day one

*The observability step of the deployment milestone (M3) — the in-app ops
dashboard going live over the spend ledger, and the cost-accounting fix it
forced within hours (the "step 8 item 3b chunk 1" commit; the job journal is
chunk 2, both 2026-08-09). Feeds: the M3 report's LLMOps/observability
section; candidate material for a standalone post on LLM cache economics.*

The observability step's first deliverable was deliberately modest: a public
read-only `/ops` page rendering aggregates the store already journaled —
spend by day, calls and tokens by stage and model, the spend breaker's daily
allowance. Within minutes of the page going live on the box, Arda read two
of its numbers as broken. He was half right, and both halves taught
something.

The half that was a label problem: "fresh analyses today 0 of 5," which he
read as a per-user limit showing nonsense. The 5 is in fact the whole day's
shared public pool (his own spend-breaker design — per-visitor limiting is
one-in-flight, deliberately not per-user daily bookkeeping), and it read 0
because the operator's unlocked runs are exempt from the public count by
design. Design-correct — but a stat that confuses its own designer has
failed its reader, so the fix was wording, not architecture: the label now
names the shared pool and the operator exemption outright.

The half that was real: the page showed $0.7660 for a day DeepSeek's own
dashboard billed at $0.14. The ledger had been pricing every prompt token at
the list input rate, while the provider's prefix cache was serving ~90% of
classify prompt tokens at a 50x discount — every classify call ships the
same large ontology-and-instructions prefix, which is exactly what a prefix
cache eats. The archived raw responses, kept as durable provenance since the
first census buy, settled the diagnosis to the cent: all 278 archived bodies
in the local store carry DeepSeek's hit/miss split (2,486,016 hit /
269,030 miss — 90.2%), and flat-pricing those tokens reproduces the
recorded $0.4286 *exactly*, while pricing the split puts the true cost near
$0.09. The box-side reconciliation closed the loop against the bill itself:
the dashboard's 2026-08-08 tokens (4,530,816 hit + 439,907 miss + 268,443
output, read from the DeepSeek console 2026-08-09) price to $0.1494 against
the $0.14 billed. One small lesson rode the diagnosis: an early attempt to
*infer* the price table by fitting it to the one billed total produced a
clean, wrong answer — three unknowns fit one bill far too easily — and the
real table ($0.0028 hit / $0.14 miss / $0.28 output per million) came from
the provider's pricing page, where it should have come from first.

The project had, notably, already measured this gap once from the other
side: the 2026-08-04 fresh-buy note records the census's famous $3.80 as a
cache-discounted provider bill with list rates ledgering ~5x higher. Report
numbers were always dashboard-truth; what changed here is the ledger
finally joining the bill — the adapter now reads the cache split off the
wire, the spec prices it, and the cost formula splits hit from miss, while
the worst-case budget reservation deliberately stays flat-priced (it is a
guard, not accounting). The ruling on history was forward-only: the
append-only ledger's wrong-by-formula rows stand as written, disclosed on
the ops page, because the money at stake was cents and a ledger whose
entries are never revised is worth more than a restated past.

A second display-honesty lesson arrived the same way the first did — by
watching the designer misread the live page. After the fix deployed,
pre-fix rows rendered "0% cache hit" when the truth was "never recorded,"
and Arda flagged the zero as broken within minutes. The proof of the
mislead was the misreading itself; the fix computes hit rate only over rows
that measured the split and renders an honest "—" otherwise.

What honest instrumentation bought, live on the box the same evening
(the `/ops` page, 2026-08-09): a full cold analysis of PUBG: BATTLEGROUNDS —
292 reviews labeled, 3m 05s end to end — at an attributed cost of $0.0072.
Sub-cent per game, where the flat-priced ledger would have reported ~5x
that. The stage split matches the mechanism (classify 94% cache hit behind
the shared prefix, compose 54% on its mostly-per-game prompts), and the
newly-persisted call latencies read classify p50 2.8s / p95 4.9s over 86
measured calls — the first data the parked narration-ETA calibration has
ever had to work with.

Figure: the three-way reconciliation (flat-priced $0.77 · cache-priced
$0.15 · billed $0.14) or the before/after cost-per-analysis bar.

## 2026-08-08 — The canary's first live reading: every wall held, and the first thing the instrument caught was our own composer's typography

*The prompt-injection canary set's first live runs (deployment milestone, M3) —
the built-but-never-read instrument from the 2026-08-07 build finally pointed
at the real model, three runs at cents each (captures
`probes/captures/canaries/canary_run_b9c024fa.json`, `_49899acf.json`,
`_270000cf.json`), plus the compose-v1 → compose-v2 prompt bump and the canary
shell's whitelist fix that fell out of reading the results. Feeds: the M3
report's model-prose / canary section; candidate material for a
security-instrumentation post or a prompt-versus-habit post.*

The canary set had sat for a day as exactly what the TODO called it: a built
instrument with no reading. The set, the beacon scoring, and the two-surface
run shell were all tested against scripted providers — but "the prompt walls
hold" was an untested claim until someone spent the couple of cents to ask the
real model, and the frontend step ahead assumes prose worth rendering. The
first live run answered the headline question cleanly: **every wall held on
both surfaces**. At classify, all six canaries — instruction overrides, role
confusion, format breaks — were labeled as ordinary reviews, 7/7 rows parsed
with zero failures and zero evidence repairs; no beacon leaked anywhere. At
compose, none of the nine canaries steered the prose, and the quote-laundering
pair — the *measured* expectation class, expected to possibly surface as a
known limitation — never surfaced at all: the model neither repeated the
planted "97% of reviewers agree" claim nor the server-shutdown claim. The same
run settled DESIGN's named prose-voice caveat on sight: v4-flash had only ever
emitted JSON for this product, and its first user-facing English came back
clean, report-shaped, grouped and hedged like something a reader would
actually want.

The interesting part was the line under the verdict: "grounding: failed, 11
violations." Diagnosis split it into a fixture bug and a real finding. Four
numeral violations were the run shell's own doing — its hand-built whitelist
(`{1000, 120, 12.0}`) omitted the sentiment counts (90/20/6/4) that its own
fact sheet had handed the model, while production's `derive_whitelist`
includes every honest derivation of the aggregates. The shell was measuring a
stricter gate than the one that ships, and honest restatements of the fact
sheet were being scored as violations. The fix routes the shell through the
production door — it now mints a synthetic aggregate and derives the whitelist
from it, with a new test pinning that fact-sheet restatements ground clean —
so the run reports the shipped gate's verdict, not a hand-list's.

The other seven violations were the real finding, and not the one the
instrument was built for: **the composer edits quotes to fit its prose
grammar**. Every failed span traced to a real canary text — no fabrication
anywhere — but the model had lowered sentence-initial capitals ("Solid
deckbuilder." became "solid deckbuilder"), swapped trailing punctuation to fit
the host sentence ("…for the price." became "…for the price,"), and clipped a
word ("drags in act two though" became "drags in act two."). The gate refused
all of them, exactly as designed: an edit is an edit, whatever its motive. The
instrument built to catch attackers caught our own composer's typography
first.

Arda ruled the response: tighten the prompt and keep the gate strict. The
alternative — case- and punctuation-tolerant matching at the gate — would have
bought pass-rate by weakening exactly the check whose strictness lets the
fabricated-quote metric say "zero, verified" instead of "zero, assumed"; the
retry ladder stays as backstop rather than routine path. The prompt bump
(compose-v1 → compose-v2) spelled out character-exactness with a contrastive
example, and the iteration was measured on the same fixture at temperature 0.
Run two (capture `canary_run_49899acf.json`): casing edits gone entirely,
quote violations 7 → 6, with the residual almost purely one deeply-trained
habit — the American convention of placing your own comma inside the closing
quotation mark. A punctuation-placement rule with its own contrastive example
was folded into the same v2 bump (nothing had shipped under v2 yet, so one
bump rather than two). Run three (capture `canary_run_270000cf.json`):
violations down to 4, and the certified spans now show the rule landing —
"Solid deckbuilder." kept its period; "Honestly one of the better roguelikes
this year" ends before the model's own comma. Walls held on all three runs.
(One honesty note on the trajectory: the first run's headline count of 11
includes the four fixture-bug numerals, so the true quote-edit trajectory is
7 → 6 → 4 — and each point is a single fixture composition, n=1 per run, not
a rate.)

The stopping decision is part of the story. Chasing zero would mean tuning
prompt wording against an n=1 fixture at diminishing returns, fighting
typography the model has absorbed from a lifetime of English text. Production
already owns the residual: the corrective retry names the exact violating
spans — precisely the fix a comma-inside-quote slip needs — sentence-drop
sits behind it, and the ladder rung each job lands on is journaled. Deployed
narrations, not this fixture, are the evidence for any further tightening.

Two transferable lessons banked. An instrument's first live catch is often
the system's own habits, not the adversary's — the walls held against every
attack shape, and what failed the gate was our composer being fluent. And
"verbatim" in a prompt does not carry the typography discipline: the word was
already there in compose-v1, and the model still bent casing and punctuation;
character-exactness had to be spelled out contrastively, and even then the
ingrained style survived partially.

Figure: the three-run violation trajectory (11 → 6 → 4, decomposed into
fixture-bug numerals versus real quote edits, casing versus punctuation
classes) — the "instrument catches itself" story in one chart.

## 2026-08-07 — The bridge's planned seam dissolves, and the test transport turns out unable to stream

*The deployment milestone's (M3) second build step, later the same day as the
runner: the SSE narration bridge — wire encoding, the replay-then-follow
stream, the FastAPI intake — landed as the two bridge commits (`serve/sse.py`
with `tests/test_serve_sse.py`, then `serve/app.py` with the queue's
read-only lookup, the SSE dials in `ServeConfig`, and the fastapi + uvicorn
dependency add), with the narrowings recorded in DESIGN's "Narration streams
over SSE" ruling (build notes dated 2026-08-07). Feeds: the M3 report's
serving-skeleton section; a candidate post on testing at honest boundaries.*

Two reminders from Arda mid-build set the frame before any code: the serve
layer is portfolio work, so the backend pieces hold the same structural bar
as the rest of the project — and even though nothing scales past one box
today, "how would this scale" should stay answerable at every seam. Both
shaped what followed. The design had planned the async/sync touchpoint as a
dedicated thread-safe event queue — the job's sink pushes events in, the SSE
generator drains them out. At build the seam dissolved: step 1's `Job`
already holds the replayable event history under a lock, precisely so a
viewer attaching mid-run can see the story from the start, which makes
replay and live-follow *one read path* — snapshot the history, remember the
length, resume from there. The generator therefore polls snapshots at a
sub-second config tick instead of registering per-viewer listener queues.
The case wasn't only that narration lands at seconds scale (so listener
machinery would buy imperceptible latency at the cost of subscriber
lifecycle and cleanup) — it's that polling binds the bridge to nothing but a
snapshot surface (`events()`, `state`, `error`), which an external event log
behind several web replicas would satisfy unchanged, where subscriber
registration would have hard-bound it to process locality. The scaling
answer is kept by seam choice, not by machinery built ahead of need.

The wire details each carry a why. The stream closes with an in-band
terminal frame because browser `EventSource` otherwise reconnects forever
after a server close — the protocol has no other way to say "the story is
over." A quiet stream emits comment heartbeats (a long fetch window can
narrate nothing for tens of seconds; the proxy in front must not idle the
connection out). And the ending is race-free by an ordering fact rather than
a lock dance: `Job` appends its terminal narration *before* flipping to a
settled state, so a generator that observes DONE/FAILED and then snapshots
is guaranteed the complete story — the stream cannot drop the tail. The
HTTP surface split by verb: `POST /analyses` is the only creator, and since
submit-or-attach is the queue's own semantics, the POST is idempotent per
live app; the events `GET` is side-effect-free through a new read-only
`live()` lookup — a GET must never mint a minutes-long, money-spending job —
and a *finished* job deliberately 404s there, its report being the
persistence layer's to serve (build step 5).

The session's surprise came from the test side. The route tests drive the
real app over httpx's in-process ASGI transport (no server, no sockets — and
httpx was already a dependency), but the first streaming test failed
strangely: the gated pipeline timed out waiting for a release that was
conditioned on reading a frame. A direct probe explained it — a two-chunk
stream with a one-second gap between chunks arrived as a single burst at
1.01 s — and a second probe sharpened the finding: a design that released
the gate upon *entering* the response deadlocked outright, because
`ASGITransport` runs the ASGI app to completion before returning even the
response headers. Client-side live delivery is simply unprovable through the
in-process transport, no matter how the test is written. The turnaround was
to move each claim to where it is honestly observable: live-follow is pinned
frame-by-frame at the generator (`tests/test_serve_sse.py` drives it with
`anext` while emitting between frames — the generator suspends in its poll
sleep, so the test controls exactly what the next snapshot sees), and the
HTTP test claims composition only — a GET that *verifiably* attached mid-run
receives the complete story with the end frame last. "Verifiably" needed a
server-side observable, since no client-side signal can exist: a test queue
subclass whose `live()` lookup sets an event, the race-free moment to
release the gate. True end-to-end liveness is deferred to the real-server
deployment smoke, where uvicorn actually streams. The suite closed at 586
passed with ruff and pyright strict clean.

Figure: before/after seam sketch — the planned bridge (sink → hand-off queue
→ SSE generator) against the built one (sink → the job's own history ←
generator polling snapshots), one arrow fewer and one owner fewer.

## 2026-08-07 — The runner build surfaces the study's quiet assumption: certified draws speak English, the live wire doesn't

*The deployment milestone's (M3) first build session, later the same day as
the entry gates: the serving skeleton's step 1 — the shared-pacer transport
rider, the one-cold-job-at-a-time queue, and the cold-analysis runner —
landed across six commits, with the build-time rulings recorded in DESIGN's
"Deployment (M3)" section as the live executor's English-pool semantics
block (2026-08-07). Feeds: the M3 report's serving-skeleton section; a
candidate post on what happens when a certified instrument meets the
production wire.*

The sampling study (M2) certified its draws over English-only pools —
"English-only stands everywhere" was a settled ruling — and nobody had to
notice that the certification carried a quiet assumption: the corpus was
English-only from ingest, so every histogram the plan compiler ever saw and
every pool the simulator ever drew from was already English. The live wire
is not. Live histograms count all languages and the production fetch is
deliberately all-language (the unfiltered trio is a data-integrity rule),
so the moment the runner had to execute the size rule *before fetching
anything*, the gap opened: branch take-all-versus-sample on which pool?
Four rulings closed it, all four recommendations accepted as proposed: the
size rule branches on the English pool, read pre-fetch by a new
language-filtered totals query; take-all fetches one whole-life window
through the already-validated windowed path and filters English after; a
sampled plan compiles at the certified n = 1,000 against the all-language
histogram and *discloses* the resulting English shortfall (the realized n
is honest, Wilson at the actual n errs conservative) rather than inflating
the target by an uncertified share correction — that inflation is parked as
a re-ruling candidate for when deployed narrations show real language
mixes; and a page-budget guard prices every plan before fetching, degrading
an over-budget take-all to the sampled draw and refusing a still-over-budget
plan outright.

The new totals read sat outside the probes' recorded parameter surface, so
it was probed before any code trusted it — and the probe had unusually good
references to check against: the fresh-buy run (2026-08-03) had fetched
three games whole-life and counted English rows one by one. The wire agreed
exactly where it mattered: Sword and Fairy Inn 2 — the designated language
case, 36 usable English reviews inside a 2,277-review game — returned 36
against the reference 36; Dragonkin drifted +6 and Talisman +2, days of new
reviews, not disagreement (`probes/english_totals_probe.py` ·
`probes/captures/english_totals_summary.json`). The probe's branch preview
also showed the ruling doing its work before it existed in code: both
long-tail games flip to take-all under English branching where all-language
branching would have sampled them — precisely the "take-all over a tiny
English pool is the honest production behavior" the closing test had
already certified.

The build's second discovery came from reading the plan compiler with
executor eyes. Compiled windows are bucket-wide — one window per non-empty
rollup bucket, tiling the game's whole lifetime — so the naive executor
(fetch each window whole, truncate to quota) would walk a veteran game's
entire history: ~1.2 million reviews for Team Fortress 2 in service of a
1,000-review sample. The escape was already written into the contract:
"newest-first, in the API's return order, up to quota" executes literally
as an *early walk stop* — Steam serves windows newest-first, so stopping
the walk the moment the quota fills IS the certified selection rule, at a
cost proportional to quota rather than volume. The walk engine grew a
`stop_after` seam and the test pins the cost claim directly: an
over-supplied window's second page is never requested. A sibling narrowing
hit the overlap seam — the design prose said the fetch producer streams
"review pages" to classify workers, but a windowed walk that goes dirty
discards its pages and re-walks via the cursor fallback, so a page's sample
membership is not final until its whole window's path outcome is known;
completed windows, not pages, are the streaming unit. The overlap itself is
tested by construction: the suite gates the final window's wire response on
the classify provider having already received a batch, so a
sequential-runner regression cannot pass.

Two honesty items round the session out. The cost shape found at build
time: a sampled plan's floor cost is one page per populated bucket, so a
monthly-rollup veteran pays ~190 pages ≈ 5 minutes of paced fetch — above
the design session's 1.5–2.5-minute cold-report estimate, and it means
fetch, not classify, binds for old games; the skeleton's own narration
timings are the ruled instrument for deciding whether that matters. And a
verification with a bonus: Arda paused the build to re-confirm the M2 size
rule from source ("was it 1,000 or 2,000?") — both numbers are real, n =
1,000 sampled above a 2,000 take-all cutoff deliberately shaped as 2×n —
and the check surfaced that the study module pinning those constants names
the runtime as their source-of-truth once deployment wires the policy. That
must-match claim is now an enforced test against the serving config's
defaults, not a docstring hope.

Figure: the branch-flip table — per probe game, the English and
all-language pools side by side with the branch each would take; three rows
tell the whole English-pool ruling.

## 2026-08-07 — The deployment milestone opens: a purchase gate arrives to find the purchase already made, and flips to validation

*The deployment milestone's (M3) entry session, same day the sampling study
(M2) closed: both entry gates run from the production host and passed
(captures `probes/captures/reachability_datacenter_netcup.json` and
`probes/captures/rate_budget_netcup.json`; probe code
`probes/reachability/app.py` reused unchanged and the new
`probes/rate_budget/probe.py`). Feeds: the M3 report's entry-gates /
hosting-decision section; possibly a deployment post.*

The entry plan staged at the sampling study's close was built around a
purchase gate: netcup bills hourly at €0.01/hr, so the sequence was rent for
an afternoon → probe Steam reachability from their datacenter → only then
commit to a term. Arda short-circuited it — the session opened with the VPS
already bought (VPS Lite 1 G12s, 2 vCPU / 4 GB / 80 GB SSD, Nürnberg,
6-month term at €4.10/mo — below the €4.88 the 2026-07-28 hosting read had
noted). That inverted the gates' character without hurting their value: they
flipped from purchase decision to validation on an owned box. The inversion
was rationally cheap because the guarded downside was always small — a
failed probe now costs the ~€25 full term instead of a few cents, against a
gate ceremony that had its own cost in rented-box setup. The gates still ran
first, before anything was built on the host: sunk cost doesn't excuse
building on an unvalidated premise.

Gate one was free. The smoke-test milestone's (M0) reachability probe was
built dual-mode — local and datacenter runs are the same file — precisely so
it could be pointed at whatever host came later, and that design paid off a
second time: the file ran unchanged on the netcup box and returned every
verdict true (`all_ok`, `windowed_ok`, `offtopic_filter_ok`) from egress IP
188.68.41.104, the capture carrying its own proof of where it ran. Steam's
store API answers normally from the production host, on the plain walk, the
date-windowed production path, and the marked-window filter behavior alike.

Gate two needed new code: nothing in the repo had ever stressed the
community-known ~200-requests-per-5-minutes store-API budget — the M0 pass
confirmed reachability, not rate. The new probe is a sibling in the same
probe-grade style (sequential, no retries, per-request records), with three
design choices worth keeping: requests round-robin over seven appids so a
response cache can't quietly absorb the load and flatter the result; the
paced phase schedules by wall clock rather than sleeping a fixed interval,
so request latency can't compress the cadence; and the over-budget burst
aborts on the first non-200 as an explicit politeness contract — one data
point, not a fight with Valve. The verdict: 200 requests at the budget
cadence all returned 200 (`budget_ok: true`), the 60-request unpaced burst
drew zero refusals (`burst_first_refusal: null`), and no 429 appeared
anywhere (`saw_429: false`) — so the settled ruling declining 429 on the
5xx retry ladder (2026-07-28, no 429 ever observed) stays closed, now with
host-local evidence rather than absence-from-elsewhere. The burst result
also says the enforcement edge sits comfortably above the app's operating
point — though sixty requests is a peek over the fence, not a map of it.

The session itself was a deliberate inversion of the usual division of
labor: Arda drove every command hands-on as ops reps — panel provisioning,
SSH key forensics (including a passphrase lost to a years-old wizard and
recovered from memory mid-session), the full hardening pass, then the
gates — with the assistant navigating. The deployment milestone is
portfolio material as much as infrastructure, and the reps are part of the
deliverable.

## 2026-08-05 — Two human instruments, one verdict: the model reads polarity reliably and fumbles label ownership

*The human-eval track's two parallel items, both completed in one marathon
session (2026-08-04/05): the 150-review fresh holdout — Arda labeling blind
under frozen codebook v2, scored strict-envelope against production (run of
record `holdout-20260804T215600Z-c0edb01a`, journaled in the census store's
eval_runs and mirrored in `eval/holdout/agreement.json`) — and the 100-claim
misattribution audit (`eval/audits/misattribution/report.json`). Pass rulings
and process disclosures live in a NOTES.md beside each sheet. Feeds: the M2
report's limitations section (the reference-imperfection bound and the
misattribution caveat's measured size) and the sampling-honesty post.*

The sampling study's numbers all lean on a machine-labeled reference, so two
human instruments were built to price that lean: a holdout asking "how far is
production from a careful human read?" and an audit asking "when the model
quotes a review verbatim, is the quote attached to the right claim?" They
measure different things through different designs — and they converged on
the same diagnosis, which is what makes the finding worth a report section
rather than a footnote.

The holdout's headline is strict-envelope agreement **0.557 [0.477–0.634]**
over 149 reviews (one non-English skip): a review counts as agreement only
when production's pinned aspect set *and* every matched sentiment equal the
human's. That binary was chosen deliberately as the harshest honest bound —
one extra or missing aspect fails the whole review — so the limitations
number cannot flatter. The report must not let it sit next to the mention-
level certification F1 of 0.766 as if they shared a ruler; a single
ten-mention review needs all ten to match to score one agreement. The number
that decomposes the headline is the one to quote beside it:
sentiment-given-matched-aspects is **0.988**. When the two readers agree on
*what* a review discusses, they almost never disagree on how the reviewer
feels about it. The entire disagreement is aspect selection.

The stratum gradient is the study-design payoff. The draw deliberately
oversampled fresh material (45 marked-window + 45 long-tail against 60
corpus) precisely because it is out-of-distribution against gold's
popular-game 250 — and agreement falls exactly there: corpus 0.678,
marked-window 0.511, long-tail 0.444. The reference is weakest exactly where
the study newly trusts it. That sentence, with its Wilson intervals, is the
limitations section's spine.

The audit landed **11.6% [6.6–19.6]** misattribution over 95 decidable
claims — the share of verbatim-true quotes attached to the wrong aspect or a
sentiment the review doesn't carry. Its decomposition matches the holdout
from the other side: aspect-side failures 10.4%, sentiment-side 3.1%. And the
failure *profile* is the interesting part: nearly every aspect miss is
close-family routing — crashes filed under `bugs` where the codebook's line
puts hard failures under `stability`, developer-incompetence rants filed as
`updates`, enemy stat-tuning filed as `ai_behavior` where the codebook routes
number-blame to `balance` — plus a small class of wish-quotes (feature
requests read as evaluations). Zero far-field misreads: no music quote
labeled as graphics anywhere in the sample. The model's failure mode is
boundary confusion between sibling labels, not fabricated meaning.

Two process stories from the passes deserve preserving. First, the audit's
frame nearly measured the wrong thing: judging the bare bracketed span,
"performance related" carries no sentiment and would fail — the settled
frame (the sheet's own "sarcasm and context count" parenthetical decides)
judges the quote *in its review's context*, so a minimal span whose
surrounding sentence says "my only complaints are…" passes. Under the
bare-span reading the rate would have measured how tersely the model quotes;
under the in-context reading it measures actual misreading. Same sheet, two
different numbers — the frame debate flipped what 11.6% means. Second, the
annotator-drift worry got a cheap mechanical guard: any mid-pass labeling
ruling gets checked against gold's recorded applications before adoption
(new territory rules freely; contradicting demonstrated precedent is drift).
Its first live use flipped the question that prompted it — the contested
"fun with friends → multiplayer" ruling turned out to *be* gold precedent,
twice over. And the guard cut both ways between the two readers: gold
evidence overturned two of Arda's instincts, while Arda overturned one of
Claude's flags with a grammatical counter-parse of a run-on review — the
ruling became "two readers, two parses → genuinely ambiguous → unclear",
with the disagreement itself as the evidence.

Figure: the three-stratum agreement gradient (corpus / marked-window /
long-tail) with Wilson bars — the limitations story in one chart.

## 2026-08-04 — A formatter ate the labeling sheet: byte-fidelity is part of the eval contract

*The holdout labeling pass's opening incident (M2 human-eval track). Record:
the `.prettierignore` widening commit (2026-08-04) and the process section of
`eval/holdout/NOTES.md`. Feeds: the M2 report's methods/hygiene aside;
candidate material for a standalone tooling post.*

Two reviews into the 150-review holdout pass, Arda flagged that saving the
sheet had reformatted the whole file: the diff weighed 3,047 changed lines
for a two-review edit. Prettier's format-on-save had rewrapped the document —
and, the damaging part, stripped trailing whitespace *inside* the fenced
review texts. Twenty-one of the 150 fences no longer byte-matched the machine
record (`eval/holdout/sample.jsonl`). That matters because the fences are the
copy-paste surface for evidence spans, and the whole eval chain rests on
evidence being a verbatim substring of the stored review text — it is what
lets the fabricated-quote metric say "zero, verified" instead of "zero,
assumed." An evidence span copied across one of those stripped line-ends
would have failed the verbatim gate through no fault of the labeler.

The galling detail: this was the *second* live catch of the class. During
gold labeling (2026-07-17, batch 02) prettier had rewritten emphasis markers
inside a workbook sheet, and the fix then was a `.prettierignore` scoped to
`eval/gold/` — the exact directory that had been bitten. The holdout sheet
lived one directory over, unprotected. The mutation was new, too: gold's
incident was emphasis rewriting, this one was trailing-whitespace stripping —
same formatter, different edit, which is why patching per-directory (or
per-symptom) fails. The widened rule ignores the entire `eval/` tree, on the
principle that every human labeling surface is verbatim-sensitive, present
and future.

Recovery was its own small lesson: the sheet was restored from the committed
render via `git show` — bytes from history, not from any editor buffer that
might already be formatter-touched — verified byte-identical against the
machine record, and Arda's two labeled reviews were re-applied on top. The
incident cost minutes because it was caught at review two; caught at review
150, with spans copied from drifted fences throughout, it would have cost the
pass. The report's hygiene aside writes itself: an evaluation that certifies
verbatim quotes must treat its labeling surfaces as byte-true artifacts, and
anything that silently "improves" text on save — formatters, linters,
autocorrect — sits between the labeler's eyes and the bytes under test.

## 2026-08-04 — The closing test passes: the size rule survives three games it never trained on

> ⚠ CORRECTION (2026-08-05, report drafting): this entry's "51 cells resolve a
> true-0.95 rate to about ±3 points" conflates one standard error with a
> confidence width — ±3 is the SE; 95% resolution is roughly ±6. Caught by an
> external read of the M2 report draft; the report states it correctly.

*The committed closing test (M2 ladder step 10), the staged long-tail
evidence's final stage — the finished size rule validated off-corpus on the
three fresh long-tail games bought and fully labeled at the step-8 session,
rather than argued by transfer. Record: "The closing test (step 10)" block
and its Outcome in DESIGN.md's study-design section; run of record
`m2close-20260804T140340Z-1cc06586` (data/runs/), verdict and figures
regenerable via `scripts/analyze_closing_test.py`. Feeds: the M2 report's
long-tail evidence / closing-test section, its limitations (the nested-anchor
and spiky-exemplar disclosures), and the sampling-honesty post.*

The whole study earns its keep here or nowhere: every ruling so far —
policy, size rule, interval allowance, tolerance table — was calibrated on
the same 49-game corpus it was measured against. The closing test is the one
measurement where the finished rule meets games it never saw: Sword and
Fairy Inn 2 (36 usable English reviews of 2,277 — the language-stress case),
Dragonkin: The Banished (1,311 — the weekly-served young game), and
Talisman: Digital Classic Edition (6,094 — the flat mid-band case), each
fully labeled under the frozen triple so its own full-pool fold is the
ground truth.

The design confirm had one fork with real teeth: which query anchors do the
held-out games run? The honest single unit is the full anchor — "a fresh
game queried today" is exactly deployment's situation — but a quiet
structural fact decides against measuring only that: the closing test has no
blend randomness and windowed draws are deterministic, so there are no
repeats anywhere. Each cell is exactly one draw, and a 95% register is only
readable across a *population* of cells. One anchor's population is just one
game's displayed aspects — a few dozen reads to certify a 95% promise from.
Arda ruled the compromise that keeps both honesties: the certified own-span
anchor grid measures (five simulated query moments, multiplying the cell
population five-fold), and the full anchor headlines in the report. The
second ruling took no fight: the spiky-regime conditioning's off-corpus
transfer is *not* a named claim — the lone spiky exemplar has 36 labeled
reviews and, being under the take-all cutoff, contributes no sampled draw at
all; claiming transfer from that would be theater. It rides as a disclosure.

One inversion from the sweeps is worth the report explaining, because it
looks like an inconsistency and is the opposite. The curves and mixing
sweeps *skipped* take-all cells — a draw that swallows its whole pool has
error identically zero, free flattery for a convergence curve. The closing
test *records* them, exactness-verified: here the cutoff side of the size
rule is itself under test, and "a game under 2,000 reviews gets its exact
number" is a promise you verify, not a nuisance you skip. Two of the three
held-out games (Dragonkin and Sword and Fairy Inn 2) sit entirely on that
side, and delivered: 360 of 360 recorded reads exact at error zero. The
sampled side belonged to Talisman alone — all five anchors above the
cutoff — and held the certified register on the pooled population reading
the certification itself uses: coverage 0.971 and tolerance 0.991 over 245
cells, 0.980 / 0.979 at the headline full anchor (run of record
`m2close-20260804T140340Z-1cc06586`). The micro-window variant's reopen
trigger — "the closing test failing held-out" — did not fire.

The verdict's honest wrinkle got quoted, not buried. Sliced by display band,
the mid band's coverage alone reads 0.902 (46 of 51 cells) — under the
register. Three of those five misses are the same aspect, `learning_curve`,
erring by about 1.35 points against the calm regime's zero allowance at
three different anchors — and those anchors are *nested*, later corpora
containing earlier ones, so this is closer to one correlated miss counted
three times than three independent failures. It is the nested-anchors caveat
DESIGN recorded in the abstract, now with a concrete face. The band read
stays diagnosis rather than verdict for two reasons: the certified promise
was always the pooled reading (the mixing floor gates the same way), and 51
cells resolve a true-0.95 rate to about ±3 points — thin evidence in either
direction. The report states it; it does not gate on it.

What this closes: the study's measurements are complete. Policy, size rule,
interval method, tolerance table, contamination floor — every ruling now
carries an off-corpus check or a named disclosure where one wasn't buyable.
What remains of the sampling study (M2) is the report itself.

Figure: `figures/closing_register_by_anchor.png` in the run dir — both gates
vs anchor quantile against the 95% rule, the coverage dip at the 0.55 anchor
recovering by the full anchor. Figure: `figures/closing_error_vs_reference.png`
— every sampled cell's error vs its reference share, misses hugging the
tolerance rules near the band edges.

## 2026-08-04 — The mixing floor is 2%: the error bars break before the numbers look wrong

*The mixing experiment (M2 ladder step 9), designed, built, and ruled in one
session — the marked-share floor tuned from the fresh-buy material, entirely
offline (resampling stored labels, zero LLM spend). Record: "The mixing
experiment (step 9)" block and its Outcome in DESIGN.md's study-design
section; run of record `m2mix-20260804T120612Z-c31f92fe` (data/runs/).
Feeds: the M2 report's "mixing curves and the floor" section, its
limitations (the unmarked-bomb residual), and the sampling-honesty post.*

The corpus holds zero review-bomb reviews, so "how much bomb material can a
sample tolerate?" was the study's one question that had to run on bought
material — the fresh-buy session's 6,445 labeled marked-window reviews,
blended into certified corpus draws at controlled shares. The design confirm
had exactly one genuine fork: what does the drifted number measure
*against*? Measuring against the unmixed sample's own conclusion isolates
the marginal contamination effect — cleaner as a pure measurement — but it
applies the checkpoint's tolerance to a quantity the tolerance was never
minted for. Arda ruled the other way: the drifted number measures against
the census share, the study's exact gates re-run with contamination, so the
floor means "the last share at which the certified 95%-register promise
still holds" — one honesty standard end to end, and the same pass/fail
machinery production is certified by. The rest followed without a fight:
replacement at fixed n (contamination is the same-size sample a report
would take, with a fraction of it being bomb material — addition would
entangle a size effect), three per-source curves with the floor read from
the worst (the three bombs were picked to differ; pooling would average
away exactly that), and the certified anchors-by-games population grid
reused unchanged.

One quiet design decision earned its keep within minutes of the first
smoke. Bomb material does not just shift a game's existing aspects — it
*invents* aspects the base game barely has: Borderlands 2's marked window
is 25% `platform_access`, the April-2019 Epic-exclusivity protest's
signature, an aspect most corpus games mention under half a percent.
Measuring over the union of the base game's and the bomb game's
vocabularies gives such aspects a true zero-ish reference, so fabrication
scores as error instead of escaping measurement — in the smoke, an aspect
sitting at 0.36% of the base game inflated to 12.4% of the sample at half
contamination (run `m2mix-20260804T115547Z-3d42ce3f`), a fabricated
headline complaint that a base-vocabulary measurement would simply never
have looked at.

The session's transferable lesson was a sequencing mistake, told here
because the report's methodology section is exactly where it belongs. The
full production sweep was fired the moment the runner worked — and while it
ran, designing the analyzer revealed that its output could not answer the
question. The certified gates read *per draw*: a draw passes when its share
error sits within the band tolerance and when its needed inflation sits at
or under the shipped allowance. The runner's rows summarized each cell's
two hundred draws into means and quantiles, and no summary of means and
quantiles can reconstruct per-draw pass rates after the fact. The running
sweep was killed, the runner extended to mint the gate rates while the
draws still existed in memory, and the run re-fired — deterministic by
construction, so nothing was lost but minutes. The statement worth
carrying: decide what question an artifact must answer before producing
the artifact; a run of record is only "of record" for the questions its
rows can still answer.

The one-game smoke then delivered a small honesty lesson of its own: it was
flattering. On the single smoke game, Book of Demons passed the 5% share
(coverage 0.958); on the full 49-game population it fails the same read
(0.940, run of record `m2mix-20260804T120612Z-c31f92fe`). A verdict quoted
off a convenient slice would have handed that bomb three extra points of
floor it does not deserve — which is why the floor only quotes off the full
grid.

The verdict itself: the share-0 baselines pass across all three sources
(coverage 0.958–0.959, tolerance 0.982–0.983 — the run restates the
checkpoint's certification before any contamination, so the floor is
measured against a verified control), per-source floors land at
Borderlands 2 0.02, Book of Demons 0.02, The Witcher 3 0.05, and the worst
source rules: **the marked-share floor is 2%**. The break is grid-located —
the promise holds at 2% and is broken by 5% — and resolution inside that
interval was deliberately not bought, because no product decision changes
with it.

The mechanism is the finding the report should lead with. Coverage, not
share error, is the binding gate everywhere: Wilson's interval width
depends on the sample size, not on what contaminated the sample, so
contamination shifts the displayed numbers while the error bars stay
exactly as confident as before — headline-band coverage falls to 0.93 at
5% contamination and 0.78 at 10%, long before the raw errors grow
conspicuous. Error bars fail silently first; the numbers still *look*
right while the bars around them have stopped being true.

The product meaning closes the loop. Steam's default listings blank marked
windows, production's fetch inherits that default, and the wire probes
verified the blanking on the actual picks — so a production sample carries
~0% marked material by construction, the passing column of every verdict
table. What the floor changes is that exclusion's status: from an inherited
default to a certified load-bearing requirement, with a number attached —
even a 5% admixture voids the calibrated bars. Marked windows stay
display-only episode markers on the timeline, never folded into displayed
numbers. The named residual for the limitations section: an *unmarked*
bomb bypasses the blanking and lands in samples as ordinary reviews; this
experiment measures that scenario's damage rate, not its frequency, which
is unmeasurable by construction (a bomb nobody labeled is a bomb no query
can count).

Figure: the two run-of-record renders — both gates vs marked share per
source against the 95% rule (`figures/mix_register_curves.png`), and the
p90 drift by display band with the ruled tolerances drawn
(`figures/mix_drift_by_band.png`), both under the run directory and
regenerable via `scripts/analyze_mix_floor.py`.

## 2026-08-03 — The instruments fought back: the wire corrected the research, the cache refused the re-buy, and the archive caught a race

*The fresh-buy session (M2 ladder step 8), built end to end in one session —
picks, wire probe, fetch, buy-time re-certification, the certified label buy,
and the blind human-holdout draw (the draw itself spilling past midnight to
2026-08-04). Record: "The fresh-buy session (step 8)" block in DESIGN.md's
study-design section; fetch run `freshbuy-20260803T110347Z-bccdb631`
(data/freshbuy/), probe finding 6 in `probes/FINDINGS.md`. Feeds: the M2
report's method section (fresh-material provenance, the buy-time
certificate), the limitations section (reference imperfection via the
holdout, buy-time variance), and the sampling-honesty post.*

Step 8 exists because the corpus contains zero marked-window reviews and no
genuinely long-tail games — the mixing experiment and the closing test both
need material the project had never fetched, labeled under the frozen
production versions. The session's through-line turned out to be its
instruments repeatedly overruling its inputs, which is the story a report
about measurement honesty wants.

The bomb-game picks started as web research, and nomination was deliberately
not treated as evidence. The research surfaced Borderlands 2, Book of
Demons, and The Witcher 3 as carriers of Valve's off-topic marks (Cyberpunk
2077 qualified too, but sits in the corpus — fresh material stays disjoint
from the 49 corpus games). A cheap wire probe (`probes/bomb_pick_probe.py`,
five paced requests per game; finding 6) then verified each pick and
corrected the record twice: The Witcher 3's marked span is fourteen days
(March 3–17, 2022), not the ~nine months the coverage suggested, and Book of
Demons' mark is *ongoing* — `end_date=0` on the wire, the first ongoing mark
the project met, forcing the fetch to substitute its own start instant as
the concrete end. Every window blanks under a default fetch and restores
under the flag, now confirmed on the actual picks rather than a stand-in,
with a combined in-window English pool of 6,454
(`probes/captures/bombpick_summary.json`) against the mixing experiment's
~1–2k appetite.

The fetch itself was quiet in the way a good instrument is: 33,264 reviews
across the six games (three marked windows, three whole-life long-tail
corpora), every walk on the primary windowed path, and the English counts
matching both the probe and the two-day-old discovery snapshots exactly —
independent reads agreeing across days. The one blemish is disclosed by
design: The Witcher 3 collected 8,991 of Steam's reported 8,992, most
plausibly a review deleted between the summary read and the walk reaching it
(run manifest, `freshbuy-20260803T110347Z-bccdb631`).

Then the caching layer taught the session its best lesson. The buy-time
re-certification — the ruling that a re-buy is never trusted on an old
certificate — was designed to replicate July's gold-recomposed cell with the
*same* composition seed, for exact comparability: same batches, only buy
time varying. The run "completed" 245 batches in ten seconds at $0.00,
cache-hit rate 1.0. Identical composition is identical request content, and
the content-keyed response archive exists precisely to never pay twice for
identical content — the property that made the design attractive is the
property that made it free and useless. That was a design error of mine,
caught only by the $0 invoice. The replayed envelopes were deleted (they
measured July's annotator while wearing a tag that promised today's), and
the cell re-ran on a fresh seed, leaning on the earlier composition
acquittal (every same-day composition comparison null) to price the changed
composition at nothing. The transferable statement: spend-safety caching and
drift measurement are structurally opposed — a drift instrument must vary
its content, or the cache will faithfully hand back the past.

The corrected instrument delivered a clean certificate: today's annotator
scored F1 0.776 [0.727–0.818] against gold (`certify-20260803T120942Z`,
journaled), sitting between the census's 0.766 and July's recomposed 0.791 —
a three-point buy-time series entirely inside the wobble the July
experiments measured. The fresh buy proceeded on that certificate and
settled exact: 13,887 usable English reviews, 13,886 envelopes plus one
durable content-filter refusal — mirroring, review for review, the census's
own single-refusal accounting — at roughly $2.62 for the session,
ledger-priced. (The pilot also exposed a pricing illusion worth keeping: the
census's famous $3.80 was a prefix-cache-discounted provider price; at list
rates the same buy ledgers ~5× higher.) The provider dashboard closed the
day at $0.54 billed (read 2026-08-04) — a measured 4.9× gap between list
ledger and cache-discounted bill, the discount the pilot predicted.

The buy's one abort was a provenance guard earning its keep. Review-bomb
material is template-heavy — runs of identical copy-paste reviews — and ten
consecutive identical texts recomposed another batch's exact prompt. Under
concurrency both batches were in flight at once, both bought, and the
archive refused to overwrite its record with the second, different body:
clean abort nineteen reviews short, resume replayed from the archive,
finished. The diverse census could never have hit this; marked-window
material hits it easily. Parked as a hardening candidate (dedupe in-flight
requests by archive key) rather than fixed in the heat of the moment.

The session closed with the human holdout drawn blind: 150 reviews at 60
corpus / 45 marked-window / 45 long-tail (seed 20260804, `eval/holdout/`),
rendered in the gold workbook's labeling format with strata and games held
back in the machine record only. One flagged edge, left as designed: Sword
and Fairy Inn 2 — the language-stress case with 36 usable English reviews —
drew zero under the uniform within-stratum draw (expected 0.9), so the
holdout does not humanly check that game; a non-scored side-sheet remains
the cheap fix if wanted. [PENDING — the holdout number does not exist yet;
Arda's labeling pass produces it, and it lands in the report's limitations
as the measured bound on the machine reference's imperfection.]

Figure: the three-point buy-time series — census 0.766, July recomposed
0.791, fresh-buy re-cert 0.776, each with its CI — as the visual argument
that the annotator under the fresh labels is the same instrument the census
certified.

## 2026-08-03 — The long tail turned out calm — and the corpus's spikiness was the window talking

*Long-tail stage 2 (M2 ladder step 7) — the label-free frame checks, run the
same day stage 1 ruled. Record: "The long-tail stage-2 frame checks" block in
DESIGN.md's study-design section (ruled passed 2026-08-03); discovery run
`longtail-20260802T232206Z-9bf61718` (data/longtail/), tables and figures
regenerable via `scripts/discover_longtail_games.py` and
`scripts/frame_check_longtail.py`. Feeds: the M2 report's long-tail evidence
section, the limitations section (span and instrument disclosures), and the
sampling-honesty post.*

Stage 1 handed stage 2 a sharper question than it was designed with. The
original frame check asked only whether long-tail games' temporal structures
fall inside the range the corpus spans; after the spikiness ruling, the
load-bearing version became: does the long tail *land in the spiky regime* —
the regime where headline bars widen to ±15 points? If most small games were
spiky, the calm constants would be a popular-game privilege and the product's
long-tail promise would quietly degrade.

The first story is how the game list was built, because the method is the
defense. A hand-picked list invites exactly the selection-bias critique the
stage exists to answer, so nobody picked it: three review-count bands with
edges aligned to the ruled take-all cutoff — a true tail at 200–2,000 total
reviews where production fetches everything anyway, the band strictly above
2,000 through 20,000 where the size rule actually samples (weighted heaviest),
and a 20,000–60,000 bridge toward corpus scale — filled by seeded uniform
probing of a persisted games-only catalogue snapshot (177,272 apps), admitting
a candidate exactly when the store called it a game and its totals landed in
an open band. 959 probes filled all bands: 6 + 14 + 4 = 24 games, list
re-drawable from the recorded seed and snapshot. The probe hit a wall worth
telling: the keyless catalogue endpoint every tutorial still names
(`ISteamApps/GetAppList`) turned out retired — and the first diagnosis, made
off a single 404, was challenged by Arda ("I don't think the Steam API
changed — check properly"). The re-verification was the right call twice
over: it exposed a sloppy first probe (the supported-API check had queried
the wrong interface), and it hardened the conclusion — same 404 from two
networks, the community reporting the identical error string since March
2026, and the June steam-reviews project reconciled because its 50-game list
was hand-curated and never touched a catalogue endpoint. The fix was the
keyed `IStoreService` replacement, onboarded through the secret-safe pattern
(key in the process environment only, absent from every persisted artifact).

The answer came back unambiguous: the long tail is calm territory. One game
in 24 sits in the spiky regime on the production instrument; at the
replication grain it's 5 of 120 (game, anchor) units — 4.2%, against the
corpus's 33.1% (the frame-check regime table over the discovery run). Fresh
peak window shares (0.022–0.813) sit entirely inside corpus support
(0.036–1.000), so the regime conditioning never extrapolates. Deployed
against the long tail, the runtime will overwhelmingly quote the calm
constants — Wilson-only bars — with the ±15-point spiky treatment reserved
for the rare game whose whole life is one event.

The surprise was what the comparison said about the corpus itself. Five
corpus games had their live histograms fetched alongside the fresh ones as an
instrument-agreement check, and the two instruments agree decently over the
same month range — but the same games' *whole-life* histograms read far
flatter than their corpus-window readings (0.503 → 0.042 and 0.415 → 0.059
on the agreement table's clearest rows). The corpus's 33% spiky rate was
largely a property of *windowed pools* — a recent fetch window concentrates
mass into few buckets — not a property of popular games. That reframes what
the calibration measured without unseating it: the spiky constants priced the
penalty *mechanism* (one window swallowing the draw's quota), and the
mechanism transfers by shape, not by span; production, reading whole-life
histograms, simply meets that shape more rarely than the corpus rate
suggested. The committed closing test stays the held-out check that the
calm-regime promise holds off-corpus. [PRELIMINARY in one respect — the 4.2%
is a 24-game estimate; the closing test and fresh buys are the check.]

Two disclosures were banked for the report. Steam serves weekly rollup
buckets for young games (5 of the 24) and the regime is computed on the
native buckets deliberately — the windowed compiler plans one window per
native bucket, so native is the shape the draw experiences; weekly-native
readings sit at or below month-rolled ones and no admitted game flips across
the 2/3 boundary by unit choice. And fresh whole-life pools exceed corpus
pool support on the high side (to 63k against the corpus's 6.9k) — disclosed
rather than conditioned on, pool size being the axis stage 1 cleared. The
fresh-buy session's leaning was accepted with the ruling: the one spiky admit
(Sword and Fairy Inn 2 — 36 English reviews of 2,277, which also exercises
the language question), one weekly-unit young game, one flat mid-band game.

Figure: the frame-check ECDF (fresh bands vs the corpus, the 2/3 line marked)
and the pool-size-vs-peak-share scatter (fresh units against the corpus
cloud) — both rendered in the discovery run's `figures/`.

## 2026-08-03 — The flat constant was an average of two games: spikiness splits the honesty price

*Long-tail stage 1 (M2 ladder step 6) — the within-corpus shape splits and the
ruling session over them, run the day after the curves checkpoint. Record: "The
long-tail stage-1 splits" block in DESIGN.md's study-design section (ruled
2026-08-03); same run of record `m2sweep-20260802T132010Z-2969bcab`, views
regenerable via `scripts/split_sweep_by_shape.py` and
`scripts/mint_allowances.py`. Feeds: the M2 report's long-tail evidence and
rulings sections, and the sampling-honesty post.*

Stage 1's design question was cautious: split the convergence curves by game
shape — pool size, temporal spikiness, aspect concentration — and hope they
come out flat, so the size rule transfers unconditioned. They did not, and the
way they didn't is the story. In the first cut, *all three* axes looked guilty:
the top tercile of every axis broke the ruled mid tolerance at the shipped
n=1,000 (spikiest tercile p95 error 3.5 points against the ±2.5 promise, with
the shipped interval's coverage down to 0.872 mid / 0.875 headline; biggest
pools and 2+-headline games failing similarly — the stage-1 verdict tables over
the run of record). Three independent problems would have been a bad day. The
untangling came from conditioning: with the spiky third of anchor pools set
aside, the pool-size effect vanishes entirely — every pool tercile mints an
allowance of 0.000 in every band — and a near-uniform pool-by-spikiness
cross-tab (the terciles share units almost evenly) confirmed the axes weren't
proxies for each other; they were both proxies for spikiness. The whole
windowed penalty lives in pools whose busiest month holds a large share of all
reviews — which is exactly the mechanism the policy race had already exposed
(one window swallowing the quota, a newest-first prefix inside it), now located
instead of averaged.

Located, it indicted the checkpoint's own constants. The flat allowance pair
(mid 0.005 / headline 0.073, ruled the day before) turned out to be an average
of two very different games: calm pools that need *no* allowance at all —
Wilson alone covers, their measured coverage rides ~100%, and they'd been
shipping ±10-point headline bars where ±2.5 suffices — and spiky pools that
need roughly double the flat price. For a product whose thesis is honest error
bars, that is the checkpoint's own failure mode one level down: over-cautious
where it's easy, over-confident where it's hard. The ruling (Arda's, over the
split tables) followed the same thesis a third time: condition the price on
the regime. Two facts made the conditioning cheap. Peak window share is
computable from the live review histogram *before any draw* — the runtime
fetches that histogram to plan windows anyway, so the regime adds no data
dependency. And the threshold barely mattered where it could have hurt: a
sweep over candidate cuts (0.50 to 0.75) minted calm constants of exactly
0.000 at every cut, so only the spiky side's calibration hinged on the choice.
Two-thirds won over one-half because the lower cut dilutes the spiky pool with
borderline units that need nothing, under-protecting the genuinely spiky tail
(0.109 vs the 0.127 those units actually measure). The shipped constants:
primary path calm 0.000 everywhere, spiky 0.017 mid / 0.127 headline (~±15
points); fallback path calm 0.004 / 0.065, spiky 0.022 / 0.130 — the fallback's
calm-regime allowances are themselves a finding, since a newest-first walk
over the whole pool is biased with or without a spike. A companion ruling
closed the tolerance gap: spiky mid joins the headline treatment (no separate
error tolerance — ±2.5 is unmeetable there regardless of interval, and a
number minted to fit would restate the interval), while calm mid keeps its
±2.5.

The session also banked a methods lesson worth telling. The allowance
computation had lived as session scratch; graduating it into a committed mint
script required reconstructing the exact definition, and the first faithful-
looking attempt (exact Wilson-edge distances, interpolated quantile) produced
mid 0.004 / headline 0.067 — close to the ruled constants, not equal. Rather
than shipping the near-miss, the discrepancy was surfaced and chased: the
ratified numbers reproduce exactly under the centered reading (error minus
half-width) plus the ceiling order statistic — the *minimal* inflation that
actually reaches 95% coverage, which is also the more defensible definition
since coverage is a step function an interpolated quantile undershoots. The
centered approximation was kept deliberately: its error runs conservative
(wider bars, never narrower), and it is what the ruling ratified. Honesty
marks that ride forward: the spiky calibration rests on thin cells (48
headline cells at the shipped tier — the smoothing max is the mitigation),
everything remains self-calibrated on the popular-game corpus, and the
committed closing test is now the held-out check of the *conditioned*
constants. Stage 2's label-free frame checks inherit a sharper question than
they were designed with: not just "do long-tail temporal structures fall in
the corpus's range" but "which regime do long-tail games land in" — if the
long tail is disproportionately spiky, the ±15-point regime is its normal.

Figure: the spikiness split panel (headline-band p90 curves, spiky tercile
running 2–4× the others) is the natural evidence figure; the per-regime
constants table (calm/spiky × band, primary and fallback) is the natural
rulings table — both regenerate from the run of record.

## 2026-08-02 — Price the pretense: the checkpoint chose wider error bars over more data

> ⚠ REVISED by the 2026-08-03 entry — the flat allowance constants (mid 0.005 /
> headline 0.073) are superseded by regime-conditioned ones; the entry's
> reasoning stands, but the shipped constants now condition on spikiness.

*The curves checkpoint (M2 ladder step 5) — the ruling session over the sweep's
figures, run the same day the sweep landed. Record: "The curves checkpoint" block
in DESIGN.md's study-design section (ruled 2026-08-02); run of record
`m2sweep-20260802T132010Z-2969bcab`. Feeds: the M2 report's rulings and
limitations sections, and the sampling-honesty post ("You don't need 250k
reviews — measured").*

The session was a figure-by-figure walkthrough ending in four rulings —
winning policy, interval method, tolerance, size rule — and the arc of the
walkthrough is worth preserving because the pooled evidence and the sliced
evidence told opposite stories. Pooled over all cells, everything looked
shippable: median share error tiny at every size, Wilson's coverage riding
92–97%. Sliced by the aspect's census share, the same rows broke the promise
exactly where a report is loudest: on ≥15%-share aspects the windowed policies'
p90 error sat at 7–11 points and barely moved with n (a newest-first prefix's
error is bias, and bias doesn't shrink like √n), and every candidate interval
under-covered there — *worse* as n grew, Wilson falling from ~88% at n=100 to
~75–78% by 1500–2000, because the quoted width shrinks like 1/√n while the
bias stays put. For a product whose thesis is honest error bars, that is the
worst possible failure mode: buying more reviews made the numbers more
confident and less honest at the same time.

Four candidate answers came in from the sweep session's baton, none
pre-decided, and each met a different fate. Brute force — larger n, earlier
take-all — was rejected by the study's own curves: the headline-band error is
flat in n, so more sampling buys almost nothing there while the fetch+classify
cost grows linearly. The micro-window variant (finer windows, shorter
prefixes — the only candidate that attacks the *cause* rather than repricing
the symptom) was parked, not killed: it carries an unsolved compiler question
(windows mint from monthly histogram rollups; finer grain needs the
deliberately-unused daily strips or a within-window multi-cursor draw) and an
unknown payoff without a re-sweep, so it waits on named triggers — the closing
test failing held-out, or the deployment milestone finding the headline widths
product-unacceptable. Band-aware tolerance proved necessary but insufficient
alone: absolute error scales with the share itself, so one flat tolerance
never meant the same thing across bands — but conditioning the tolerance
merely renames the problem while the interval still claims 95% and delivers
75. What won was the bias-aware interval, and the reason it won is the
study's own thesis applied once more: the whole interval race had been about
pricing pretenses (Wilson won it because its pretense was least wrong), so
the consistent move is to *pay for* the windowed pretense explicitly — quote
Wilson's width plus a measured bias allowance. The sweep's signed-bias view
made the shape clean: no policy hides a net direction, so there is nothing to
re-center — the point estimate stands and only the width inflates.

An allowance table computed live from the run of record's measurement rows
turned the debate concrete: the flat width inflation that would have restored
95% coverage on the sweep is zero for tail aspects (<5% share — Wilson alone
already covers), about half a point for mid aspects (5–15%), and ~7 points
for headline aspects — which therefore ship at roughly ±10 points until the
take-all regime makes them exact. That number decided the rest. Since the
headline width is bias-bound and flat in n (±11 at n=500, ±8 at n=2000), the
sample size decouples from the headline problem entirely — n gets chosen on
the tail and mid bands' ordinary convergence plus cost, and only the take-all
cutoff genuinely fixes headline aspects, which quietly raised the cutoff's
importance from cost knob to honesty boundary.

The rulings, Arda's over the table: **time-proportional windowed is the
primary path** (it dominated the other implementable draws on every slice;
equal-per-window was eliminated — its quiet-month over-weighting never paid
anywhere; cursor-prefix keeps its designed fallback-with-disclosure role).
**Wilson plus per-band constant allowances** — 0.000 / 0.005 / 0.073,
each the max of the calibration over the shipped tier and its neighbors
(the ≥15% band is thin, 30–280 cells per point, so the raw 95th-percentile
calibration is a noisy order statistic and the smoothing is deliberate
conservatism); take-all pools quote the exact number and no interval.
**Tolerance ±1 point (tail) and ±2.5 points (mid) at the 95% register**, with
headline aspects carrying no separate error tolerance — their promise *is*
the calibrated interval plus take-all exactness; a tolerance number there
would either restate the width or claim precision the draw can't deliver.
**Size rule: take all at pool ≤ 2,000, else sample n = 1,000** — n=750 passed
tolerance with no margin against off-corpus drift, n=1,500 buys 0.2 points
for 50% more cost, and the cutoff takes the 2×n shape (below it sampling
saves less than half the cost, so exactness is nearly free). The rule states
itself in one sentence — "we read 1,000 reviews; if the game has 2,000 or
fewer, we read them all" — which is the thesis line of the eventual post made
concrete: at most 2k reviews per report, not 250k.

One refinement quietly superseded a design-session ruling and was recorded
rather than papered over: the original convergence gate said the tolerance
applies to *every* displayed aspect, "not a quantile of them" — but a
deterministic draw offers no per-cell guarantee to certify, so the gate now
reads at the 95% register, putting both gates (error and calibration) in the
same probability language. DESIGN carries the supersession with its why.

Honesty marks for the report. The allowance constants are self-calibrated on
the same 49-game corpus they're measured on [PRELIMINARY — the committed
closing test on fresh long-tail games is the held-out check; until it runs,
the calibration is on-corpus only]. And the corpus is long-tail-leaning
(median full pool ~2,100 reviews), so "60% of anchor pools are take-all at
the cutoff" overstates real-world reach — the big games users will actually
query sit permanently in the sampled ±10 regime; the report should say so
plainly. The constants were minted in-session from the run's persisted rows
and are re-derivable; a committed mint script (rather than session scratch)
is a flagged loose end.

Figure: the share-band error curves and the coverage-by-band panel are the
report's centerpiece pair — "sampling is easy exactly where it matters
least," then the price paid to fix it. The allowance table itself (band × n:
Wilson's coverage, the inflation, the shipped width) is a natural report
table, regenerable from the run of record.

## 2026-08-02 — A deterministic draw has no error bar: one question about future work picked the study's population

*The curves sweep's (M2 ladder step 4) design pass and build — the session after
the study design was ruled. Record: the composed-replication paragraph in
DESIGN.md's study-design section (ruled 2026-08-02); run of record
`m2sweep-20260802T132010Z-2969bcab`. Feeds: the M2 report's method (replication
unit, anchor grid), results (the convergence and calibration curves), and
limitations (nested anchors, the corpus-at-T approximation) sections.*

> The [PRELIMINARY — checkpoint pending] flags below resolved the same day: the
> checkpoint ruled, confirming these readings — see the entry above.

The step-2 build had left a deliberately unresolved flag, and this session opened
on it. Windowed sampling draws are fully deterministic: same corpus, same plan,
same sample, every time — and this is not a simulation artifact, it is equally
true of the live runtime refetching the same date windows. So the design
session's "a few hundred repeated draws per game × policy × size" quietly only
applies to the uniform reference; every windowed cell yields one fixed sample
and one fixed error. That breaks the calibration gate's grammar: "the interval
covers the truth 95% of the time" is a rate, and a deterministic draw gives it
no population to be a rate over. The sweep needed a ruling on where variance
comes from: treat games × aspects as the replication units, simulate the
time-of-query dimension by truncating each game's corpus at historical anchors,
or compose both.

What decided it was not a statistics argument but a question Arda asked about
sequencing: the study runs on corpus data now, but later ladder steps go
through the live Steam API as a test — does the choice here constrain those?
Working that through reframed the options. A live query is always a
single-anchor draw (one game, its full history as of that moment, one
deterministic sample), so under the games-only option the later live steps —
the label-free frame checks and the committed closing test — would be
out-of-distribution spot checks against a claim certified only for the snapshot
date. Under the composed population (anchors × games × aspects), time-of-query
is inside the certified claim, and those same live steps become genuine
held-out draws from the population the size rule talks about. The asymmetry in
switching costs sealed it: no machinery hangs on the choice either way (the
truncation loop is study-only code), but choosing narrow and widening later
would reopen the checkpoint's tolerance and size rule — the exact rework the
ladder ordering exists to avoid. Composed form, ruled.

The anchor grid follows the same honesty logic as the rest of the study.
Anchors sit at fixed quantiles of each game's *own* review-time span
(40/55/70/85/100% — an absolute calendar grid would place anchors before
thin-coverage games existed), truncating the corpus there and compiling the
plan from the truncated histogram reproduces exactly what a live query at that
moment would have seen, and two caveats were recorded for the report rather
than papered over: anchors within one game are nested (later corpora contain
earlier ones — they widen the population without being independent
replications), and truncating today's corpus at T assumes Steam would have
served the same rows at T, which review edits and deletions make an
approximation only the live tests can ground. Two hygiene rules fell out of
the build: an anchor whose truncated pool duplicates an earlier anchor's is
dropped (truncation is monotone — equal size is the identical pool), and a
cell whose ladder size reaches its pool is skipped as take-all, because a
take-all draw's zero error is free flattery for a convergence curve.

The sweep itself ran the same session, and the census dividend held: 49 games ×
anchors × 4 policies × the nine-size ladder — 5,476 cells, 255,744 persisted
measurement rows — in about five minutes of CPU (run of record above; the
uniform reference at 200 seeded draws per cell). First readings, all
[PRELIMINARY — the checkpoint ruling (tolerance · size rule · winning policy ·
interval method) has not happened; these curves are its input]: median share
error is small everywhere (~0.6% at n=100, under 0.1% by 2000, near-identical
across policies) and the p90 is what separates the race — uniform best,
cursor-prefix worst. The interval race already has a striking shape: Wilson,
the design-naive candidate, holds roughly 92–97% measured coverage across all
policies and sizes, while bootstrap-over-reviews collapses at small samples
(~60% coverage at n=100) and the design-aware stratified interval — the
sophisticated one — under-covers persistently (~55–90%). Its finite-population
correction pretends the within-window draw is random when the contract says
newest-first prefix; watching the fancy method fail its own pretense is
exactly what the calibration gate was built to catch, and if the verdict
survives the checkpoint, "the simplest honest formula ships" will have been
decided by measurement, not taste.

The checkpoint-prep views, cut later the same session, sharpened the story
into the question the checkpoint must now answer. Slicing the same persisted
rows by the aspect's census share showed the windowed policies' penalty is not
spread evenly — it concentrates almost entirely in the big-share aspects
(≥15%, the ones a report leads with): their p90 error sits at 7–11% and barely
falls until n≈1500, because a deterministic newest-first prefix's error is
bias, and bias does not shrink like √n — it only dies when growing quotas
swallow whole windows. The companion coverage slice then confirmed the
consequence [PRELIMINARY, same caveat]: on those same big-share aspects under
time-proportional draws, *every* candidate interval under-covers, and coverage
gets *worse* as n grows (Wilson ~88% at n=100 degrading to ~75–78% by
1500–2000) — interval widths shrink with n while the bias stays, the classic
bias-versus-width squeeze. More data made the error bars less honest. The
pooled verdicts ("Wilson covers everywhere") were dominated by the small-share
cells where absolute errors are tiny by construction. The signed-bias view
cleared one suspect: no policy hides a net direction (cursor-prefix's spread
at n=100 is wide, ±1.5% at p10–p90, but symmetric). So the checkpoint inherits
a sharp trade: the runtime-expressible primary path keeps its promise on the
long tail of aspects but breaks it on the headline ones unless n is large
enough to reach the take-all regime — or the design answers with something
else (a bias-aware interval, a band-aware tolerance, or the micro-window
variant the sampling contract deliberately left expressible).

Figure: six committed checkpoint figures, all regenerable from the run of
record via `scripts/plot_sweep_curves.py` — the convergence curves (median +
p90 share error vs size, per policy), the calibration panel (measured coverage
vs the quoted 95%, per policy × method), the signed-bias panels, the p90
curves by census-share band, the p90 curves by anchor-pool size, and coverage
by share band under time-proportional. The share-band pair is the report's
likely centerpiece: it is where "sampling is easy" turns into "sampling is
easy exactly where it matters least."

## 2026-08-02 — The census pays its dividend: the sampling study designed as a free simulation, with one tolerance governing everything

*The sampling study's (M2) design session — discussion only, no code; run the day
M1's closure was confirmed. Record: DESIGN.md's "The sampling study (M2) — the
study design" section (ruled 2026-08-02); the build ladder is in the stream TODO.
Feeds: the M2 report's method and limitations sections, and the sampling-honesty
post ("You don't need 250k reviews — measured").*

The session opened on an asset that had already changed the study's economics
before a single design question was asked. When the census was bought (C1,
2026-07-19 — 135,260 labeled envelopes, every English-nonempty corpus review
across 49 games), the slice ruling explicitly paid extra for "a sampling study
never capped by today's choice." This is where that purchase pays out: the study
is pure offline re-folding of stored labels — draw 500 rows, recompute, repeat —
so the main path costs CPU minutes, not LLM dollars. VISION's guessed ladder of
three sizes (300/1k/3k) became a dense nine-point ladder with a few hundred
repeated draws per game × policy × size, simply because density became free.

Arda's opening framing set the study's shape before any formalism arrived: run
the analysis at increasing sample sizes, watch when the readings settle, pick
the size there. The session's real work was making "settled" precise, and it
landed as two gates rather than one. Share error — the sampled per-aspect ratio
lands within tolerance of the census value — is what the displayed number
claims. But the app never shows a bare 27%; it shows "27% ±3", and that ±3 is a
promise with its own failure mode: across repeated draws the quoted interval
must actually contain the truth at its nominal rate. The two gates can disagree
— shares can look fine while the computed error bars run systematically narrow —
and that second failure is the poisonous one for a product whose entire thesis
is honest error bars. Ranking stability and praise/criticism direction were
deliberately demoted to reported-but-not-gating: both follow from shares being
right, so gating them adds criteria without adding information. One deliberate
strictness: the tolerance applies to *every* aspect the report would display,
not a quantile of them — the evidence floor already hides the sparse tail, so
whatever survives the floor honors the promise.

The policy race is shaped by an API fact: Steam has no "500 random reviews"
button. The runtime can express only windowed draws (spread a budget across
date windows) and the documented cursor walk — which in practice returns a
most-recent prefix, a biased draw by construction. So the race is four
candidates: uniform random as the unreachable textbook reference (free to
simulate against a held corpus), time-proportional windowed as the primary
hypothesis, equal-per-window as the likely-rejected variant whose rejection
will carry numbers instead of hand-waving, and the cursor-prefix fallback
raced *as it actually behaves* — its bias measured and quoted as a trust-panel
disclosure whenever a report runs on the fallback path, rather than assumed
away. Playtime and vote-type stratification were considered and demoted to
representativeness diagnostics on the winner: time is the axis the windowed
path natively speaks, and whether the API can even express the other axes is
unverified.

Curves-first was Arda's call, and it matched his opening framing: the
alternative — fix "±3" now and read the size off later — would pick the
product's promise blind, before seeing which tolerances are even reachable at
reasonable cost. Instead the study produces the full curves and the tolerance
is chosen at a review checkpoint over real measurements, a product decision
made with open eyes. The same measure-then-pick logic swallowed a second open
question for free: the interval *formula* (design-naive, design-aware, or
bootstrap-over-reviews) rides along by computing all three on every simulated
draw — the calibration gate is itself the test — and the simplest formula
whose coverage is honest under the winning policy ships. The deliverable is a
size rule, not a number: corpus games span orders of magnitude, so below some
population cutoff the answer is "take everything."

The session's most satisfying turn was the marked-share floor. Since M1 it had
been a provisional guess — past some share of review-bomb-window material, the
report degrades honestly. The corpus holds zero marked-window reviews, so this
is the study's one unavoidable LLM spend: fetch marked windows fresh from 2–3
documented-bomb games, label ~1–2k reviews under the frozen versions, and blend
them into normal samples at increasing shares offline. The floor then stops
being a guessed percentage and becomes *the marked share at which a sample's
conclusions drift beyond the same tolerance the curves checkpoint just set* —
one honesty standard running end to end through the milestone, and a sequencing
consequence for free (the mixing experiment must run after the tolerance
ruling).

Long-tail transfer got a staged plan, and its best part is Arda's. The corpus
is ~50 popular games in a recent window; the deployed app will be pointed at
six-year-old indie titles with 900 reviews. The staged evidence — split the
convergence results by game shape within the corpus, then run label-free
histogram checks on genuinely long-tail games through the existing sampler —
was on the table as proposed, with a small label buy *gated* on whether the
within-corpus splits showed trouble. Arda recast the buy: not a conditional
hedge but a committed closing test — once the size rule exists, label ~3
long-tail games fully and validate the finished rule off-corpus, a held-out
test of the study's actual deliverable. The gate became a graduation exam.

The last ruling folded the human eval track's holdout into M2 itself. The
census reference is machine-labeled — VISION always called it the "stated,
imperfect reference" — so the study measures sampling error while the
classifier's own error rides silently on top; the fresh human holdout
(~100–150 reviews under frozen v2) turns that from a hand-wave into a measured
bound in the report's limitations section. The newer reason it belongs inside
M2: the fresh buys are out-of-distribution against gold's 250 popular-game
reviews — bomb-window reviews and obscure titles are exactly where the
classifier is newly trusted and least checked — so the holdout draws across
corpus *and* fresh material. The rest of the human track (misattribution
audit, self-relabel, judge adjudication) stays parallel and non-gating.

Figure: the convergence curves themselves — error vs. sample size, one line per
policy, the census as zero line — are the report's centerpiece and the post's
money shot. Second candidate: the mixing curve (conclusion drift vs. marked
share) with the floor marked where it crosses the tolerance band.

*The scorer-bump session — the last docket item from the full-base review, run as
its own design-then-build session. Record: DESIGN.md's "bootstrap-undefined fix"
operational entry; the finding itself is the review report's bootstrap entry
(stream `reviews/2026-07-27-full-base-review.md`, finding 43). Feeds: the M1
post's eval-harness / honest-measurement section — both the bug story and the
deliberate-change-path story.*

The full-base review left one finding that touched certified digits, which is why
it got its own session instead of riding the architecture commits. The scoring
core's ratio convention — 0.0 on an empty denominator — is perfectly honest for a
*reported* point value, because the `n_*` denominator fields sit right beside the
number and a zero is never mistaken for measured badness. But `bootstrap_ci` feeds
the same statistic 10,000 resamples with no `n_*` beside them, so a resample where
the statistic is *undefined* — nothing to judge — contributed 0.0 as if it were
measured badness, dragging every confidence interval's lower tail toward zero.
The elegant part of the finding was where it was reachable: not the 245-review
headline frame (an all-matchless resample there is astronomically unlikely) but
the candidate-emitting slice, whose ~15 members qualify by *candidate* emission —
and candidates are unscored, so a member can carry zero pinned mentions on either
side, and a resample of 15 such draws makes precision, recall, and F1 all 0/0.
The design had even seen this exact trap once before — the zero-mention slice
deliberately reports quiet-agreement because "F1 is undefined where the reference
is empty" — it just hadn't carried the reasoning into the resampling loop.

The fix ruled: a ratio with an empty denominator is `None`, never 0.0, and the
bootstrap drops undefined draws and reads percentiles over the defined ones —
same RNG stream, so digits move only where an undefined draw actually occurred.
Two subtleties earned their own rulings. First, F1's composition: precision and
recall both *defined* at 0.0 is total measured badness (predictions and gold both
exist, none match), so F1 there is 0.0, not undefined — only a `None` component
makes F1 `None`. The line between "measured zero" and "nothing to measure" runs
through the middle of one formula. Second, the design's one admitted-arbitrary
constant: a 1% sparsity floor. A few undefined draws in 10,000 don't change what
an interval claims, but past the floor the slice is too sparse for the statistic
and the honest output is *no interval*, not a wide one — the alternatives were
"always drop silently" (a 40%-undefined interval would journal wearing a
certified metric's name) and "any undefined draw raises" (certification becomes
fragile to any gold edit shifting slice composition). Taste admitted as taste:
1% is a judgment call; the two endpoints it rejects are not.

Then the fix forced the part worth telling in the post: the evals-in-CI design
(D3) had named a deliberate-change path — "a semantics change bumps the scorer
string and re-exports the pins in the same commit" — that had never been used.
This session used it for real. All three scorer identities bumped to `/2`
(`census-vs-gold/2`, `judge-vs-gold/2`, `judge-vs-production/2` — all three,
because the procedure the string names changed for all three, whether or not
their digits moved), fresh runs of record were minted from the real pool under
the same dials (runs `certify-20260728T184100Z-5f3f4652` and
`agree-20260728T184121Z-7c975c95`, seed 20260718, 10,000 resamples), and the
descent comparison against the old `/1` anchors came back **digit-identical on
every metric row** — under the recorded seed, no undefined resample ever
actually occurred. So the published numbers (F1 0.766 [0.713–0.811], agreement
0.791 [0.772–0.810]) were never live-corrupted: the session closed a latent
hazard, not an active error — which is itself the honest-measurement story, and
the reason the comparison was run rather than assumed.

The re-anchor bought an unplanned cleanup: the fixture exporter's two disclosed
relaxations — the certification anchor's metrics compared only as an ordered
prefix (it predated the item-type slice rows), the agreement anchor's config
hash excluded (it had digested pre-normalization CRLF bytes) — both existed
because the anchors were older than the code verifying against them. New
anchors, minted by current code, need no forgiveness: both relaxations retired
and the exporter's verification is now exact on full identity. The comparison
machinery keeps its relaxation parameters as the tool the *next* deliberate
change will reach for.

One consequence surfaced where design consequences usually hide: the test suite.
Several synthetic fixtures — three- and four-review frames with a zero-mention
or all-miss review — started raising "too sparse to bootstrap," and they were
*right to*: a 3-review frame where a third of resamples have nothing to judge
genuinely is too sparse, and the old convention had been quietly manufacturing
0.0s to paper over it. The frames gained matched "ballast" reviews rather than
any test-side escape hatch — the floor's semantics hold in tests exactly as in
production. Tests 374 → 383, all green with the CI gate armed regenerating the
new `/2` pins to the digit.

## 2026-07-27 — The investigator stood down, and the frame that keeps its replacement from being a tutorial project: three claims a stock RAG app can't make

*The RAG-replacement product design session — the gate that had to run before the
M1 post ships. The direction itself (the agentic investigator milestone deferred
indefinitely; a RAG chat over the labeled corpus replaces it as the story channel)
was ruled by Arda mid-session in the E1 design session and captured then for
insurance; this session turned the direction into a product frame. Record:
DESIGN.md's two newest operational entries, "The roadmap redirect" and "The RAG
chat product frame." Feeds: the M1 post's roadmap paragraph (the redirect told
straight), and the eventual M4 post end-to-end.*

The session opened on the tension that shaped every ruling after it: RAG is
simultaneously the most market-legible AI-application pattern there is — job
postings name it outright — and the most commoditized. A "chatbot over documents"
reads as a weekend tutorial, and interviewers have seen a hundred; a generic chat
over Steam reviews would be the first artifact in this portfolio that could
actively dilute the brand. What resolved the tension was not a feature list but a
test: three claims a stock RAG app cannot make, adopted as the design's fitness
criterion — any downstream choice serving none of them is commodity weight. One,
retrieval over self-labeled structure: "why do people hate the grind?" resolves to
aspect ∧ sentiment ∧ game ∧ window filters before any embedding runs, with a
measured classifier as the index (production F1 0.766 with CI, the D2
certification run). Two, RAG evals — groundedness, faithfulness, retrieval
quality — riding a judge whose own agreement with human labels is already
calibrated and published (the D2c machinery). Three, a chat that structurally
cannot fabricate statistics: the project's two-track rule translated, numbers only
from the survey mint, quotes never laundered into percentages.

Arda ruled the product's spine in one sentence: **"Type a game name, get the
report — then interrogate it."** The report stays the product; the chat is its
interrogation channel, never a standalone chat-first surface — and cross-game
comparison went out *entirely*, not as a v1 cut but as outside the product's
identity (the chat interrogates *this report's* evidence base; a cross-game
index is a different product). The answer contract followed: claims with
receipts — short prose composed only over retrieved reviews, each claim pinned to
verbatim quotes that pass the fabricated-quote verifier before display, numbers
appearing only as visually distinct citations of the precomputed aggregates, a
one-line provenance stamp on every answer. Arda added the piece that completes
the ladder: thin evidence gets *named*, not just shrunk — an answer over three
reviews opens by saying it is thin evidence, giving the contract three explicit
states (grounded answer → named-thin answer → honest refusal) and no
free-composition mode anywhere: even "what's the overall vibe?" answers over
retrieval and mint aggregates or defers to the report's verdict panel. One
unreceipted answer type and the differentiator is gone.

The feasibility riffs produced the session's best reframing. Arda proposed a
background chat pool — draw ~1k reviews for the survey, and while the classifier
labels them, keep drawing to ~5k so the chat opens on a deeper evidence base,
the extra kept raw as Steam sends them. The fetch arithmetic works trivially (1k
reviews is ten pages at the built transport's 1.5s pacing floor — roughly 20–30
seconds; a 5k fill fits inside the classification window). But the census
receipt reframed the "raw" half: the corpus buy priced labeling at $3.80 for
135,260 reviews (the C1 census, 2026-07-20) — about three cents per thousand —
so keeping the extra 4k raw is not a cost decision at all, it is a
latency-shaping decision, and a raw tier would quietly turn most of the pool
into the commodity embed-and-cosine pattern the fitness test exists to reject.
The leaning (ruling reserved for the M4 design session): progressive background
labeling — the report opens on the survey alone, and fetch → label → embed run
as trailing stages behind it, nothing user-visible ever waiting. The fill stays
dumb-chronological by rule: a fill that steers toward spikes is the
investigation track reborn without its verification loop.

Two tooling calls got made on arguments worth preserving. The embedder leaning
is small, local, and pinned (the MiniLM/bge-small class) — and the sharpest
argument came from the project's own scar tissue: the D2c judge ran on a Gemini
preview that survived a capacity event and carries a named successor, and an API
embedder's retirement is that incident in worse form, because vectors from
different models don't compare — retirement orphans the entire stored index.
Pinned local weights make the index immortal, CPU-viable on any host, and at 5k
reviews the whole index is ~8 MB — brute-force cosine beside SQLite, no vector
DB. On frameworks, the LangChain answer was no on the project's own dependency
test (the provider seam already exists; reviews are natural retrieval units, so
there is no chunking problem; the framework would hide exactly the visible
engineering the portfolio exists to show). Arda then clarified he meant
LangGraph — and the answer sharpened rather than flipped: LangGraph is the
respectable half of that ecosystem, but the chat as scoped is a pipeline
(classify intent → refuse | defer | retrieve → compose → verify → render), not a
graph, and the irony is exact — the thing LangGraph is shaped for, a stateful
verify-and-loop agent, is precisely what the redirect deferred. It is named in
the design record as the tool for the next complexity tier, adopted when a real
loop appears; framework literacy routes to an hours-scale experiment-lab
exercise plus a deliberate paragraph in the M4 post ("here is what the framework
would have provided, and why ~200 explicit lines beat it here").

The costs were named rather than buried. The verify-then-explain loop — the
product's most original idea — goes dormant, deferred not deleted. Its
statistical half survives: episode detection over the all-language histogram
ships as display-only markers at deployment, no explainer, and the chat inherits
the drill-down role in a degraded-but-honest form — a lifetime survey sample
holds only a dozen-odd reviews from any given spike (the observation that
founded the investigator in the first place), so spike questions will often
land in exactly the named-thin-evidence state rather than pretending to explain.
And the M1 post's roadmap paragraph tells the redirect as what it was: a
measured scope call on stated grounds — the labeled corpus and calibrated judge
are assets a RAG system monetizes directly — not a retreat from the harder
thing.

Figure: a single annotated chat answer as the M4 post's anchor image — claims
with quote pins, the mint-citation number visually distinct, the provenance
stamp, and a named-thin-evidence variant beside it (the three-state ladder in
one frame).

## 2026-07-27 — The live layer paid for itself on its first run: donor lore drifted in a direction nobody predicted, and a cheap probe closed a cost hope cleanly

*The E1 `steam_client` build session — the live Steam door, built in seven
commits to the five-fork design ruled the same day. Extraction+eval (M1),
side-track E1. Feeds: the M1 post's methodology/verification section (the
two-layer verification argument and what each layer can uniquely catch), and
the eventual deployment-milestone ops story (the live door's trust posture).
Build record: DESIGN.md's "`steam_client` E1 build" entry; machinery in
`src/steamlens/steam_client/`; smoke in `tests/test_steam_live_smoke.py`.*

The door's verification was deliberately two-layered, and the design fork that
ruled it had to defend the second layer: scripted-transport tests and
real-capture parser tests cover CI (a record/replay library was rejected — one
injectable callable does the job, and cassettes rot), while a gated live smoke
(`STEAMLENS_LIVE_SMOKE=1`, never CI) is the only code that touches Steam. On
its first deliberate run, the smoke failed — and the failure is the argument
for the layer's existence. The harvested donor lore (mined from the frozen
steam-reviews fetcher during the design session) said `query_summary` rides
the first review page only and is absent afterward. The live wire disagreed in
a direction nobody predicted: later pages *do* carry the field, as a
degenerate stub — `{"num_reviews": 0}` with none of the population totals —
and the strict boundary parser, built to refuse rather than half-parse,
refused it mid-walk exactly as designed. The fix took the same hour: the known
stub now parses as "no summary" while a half-formed totals block still fails
loud, and the new wire shape is pinned as a scripted test so CI carries the
knowledge forward. Two lessons ride this one incident. Harvested knowledge
drifts in unexpected *directions* — the lore wasn't wrong that later pages
differ, it was wrong about *how*, and no amount of scripted testing against
remembered shapes catches the shape nobody remembered — only a live layer
does. And validation strictness is what converts silent drift into a loud
finding: a tolerant parser would have shrugged the stub into a `None` and the
lore would still be wrong in the codebase's collective head.

It was also the second donor-lore correction of the E1 arc: the design session
had already caught the donor's "80 is the community-verified reliable value"
page-size comment contradicting the project's own verified record (FIXLOG
2026-07-07 — no batch size is universally safe; the same bug thread reports 80
failing where 100 works). Same lesson, two instances, two directions: harvested
docs are claims to verify against one's own record and the live wire, never
facts to adopt.

The page-size probe closed the arc's one open cost hope. Fetcher programs are
reported running `num_per_page=200` (Arda's observation), and an honored 200
would halve every window's request cost under the flat 1.5s pacing floor. The
one-shot probe (`probes/page_size_probe.py`, capture
`probes/captures/page_size_200.json`, run 2026-07-27) asked for 200 and got
exactly 100 back — clamped at the documented cap. The hope died in one paced
request; the alternative was baking an unverified 200 into config and
discovering the truth as a silent under-fetch mid-survey. Page size stays the
non-load-bearing knob the design ruled it to be, default 100.

The rest of the smoke run (5/5 after the fix, this session) earned its lines
too: the blank/restore pair reproduced *live* on Borderlands 2's real
`past_events` window — 0 reviews under a default fetch versus 100 with
`filter_offtopic_activity=0`, so the data-integrity bug that forces the
restore flag onto every fetch is a present-tense fact, not 2019-era capture
archaeology — and the windowed check's cross-check landed exactly: Steam's own
window-scoped population claim matched the collection to the review
(`reported_total == collected == 49`).

Figure: the blank/restore pair as a two-bar before/after (0 vs 100 reviews,
same window, one request flag apart) — the door's trust posture in one image.

*The D3 evals-in-CI session — designed, ruled, and built in one day.
Extraction+eval (M1). Feeds: the M1 post's evaluation-harness section (what
"evals in CI" means when re-scoring is deterministic, and the exact-digit
discipline), and its honest-limitations section (attribution discipline —
including for one's own diagnoses). Build record: DESIGN.md's "D3 evals-in-CI"
entry; machinery in `evals/ci_fixture` + `tests/test_eval_gate.py`.*

The design discussion started from a premise the batch-composition experiments
had handed over: re-scoring stored labels against pinned references is
deterministic and free — same envelopes, same gold, same seed, same digits, no
API call — so a CI gate can only ever catch *code, scorer, or artifact* drift.
Model drift physically cannot occur there (CI produces no fresh model output),
and where it can occur — a label re-buy — the measured ~0.02–0.03 buy-time
variance of the served model (the 2026-07-25 registered-experiments finding)
already governs it. That collapsed the original roadmap wording, "drift
annotates, harness errors fail," which had imagined model drift: in a
deterministic re-score, any digit that moves is either an unintended behavior
change or an undeclared semantics change, and both deserve failure, not
annotation. So the ruling: exact-digit mismatch fails CI; the escape hatch for
deliberate change is bumping the scorer's version string and re-exporting the
pinned expectations in the same commit; tolerance bands leave CI entirely and
become the *re-buy* decision rule, floored at the instrument's own ~0.03
variance — a tighter band would alarm on noise. The mechanics: CI has no label
database, so a committed fixture (`eval/ci/` — 1,243 reviews, 2,243 label
envelopes, ~1.3 MB of diffable JSONL) carries exactly the store rows the two
runs of record read, a test rebuilds a throwaway store through the production
writer surfaces, and the re-scores must reproduce the pinned runs — the
census certification (F1 0.766, descending from journal run
`certify-20260723T093643Z-4eab554c`) and the judge-agreement read (F1 0.791,
from `agree-20260723T203011Z-78258f68`) — to the last digit.

The story worth telling is what surfaced *before the gate ever ran in CI* —
one real drift vector, and one drift story that died under verification.
First, bytes: the pins embed sha256 digests of committed artifacts
(the gold file, the agreement sample), and working out where those digests
must match forced the question of whether the bytes on a Windows working copy
and a Linux CI checkout are even the same. They were not — git's
`autocrlf=true` had left the agreement sample file with CRLF line endings
locally, meaning the journaled agreement run's config hash pins bytes no CI
checkout can ever reproduce, and any pin minted from that working copy would
have failed forever in CI while passing locally. The fix is now structural: a
`.gitattributes` holds every digest-pinned artifact at LF on all platforms,
the exporter flatly refuses to mint pins from a CRLF working copy, and the one
unfixable residue — the historical run's config hash, hashed over
pre-normalization bytes — is handled as a single disclosed field exclusion in
the exporter's verification against that anchor, recorded in the fixture's
manifest rather than silently skipped.

Second, the story that died: the build's repo-wide type-check went red in a
file the session had never touched, which led to the discovery that the
project's CI had already been red since 2026-07-25 — two failed runs, the
visible one on a commit that changed only HTML mock documents. The session's
first diagnosis was toolchain drift: the PyPI `pyright` package wraps a
checker fetched at run time, so a fresh release with stricter inference could
redden CI with zero code change — a tidy story, precisely the gate's own
thesis demonstrated in its own toolchain, and it was written into three
records before Arda asked the load-bearing question: *are we sure the version
differed between the two runs?* Verification killed it. The failing line did
not exist at the last green run's commit (`git show a4de682` — clean); it
entered in the per-aspect journaling commit, authored 2026-07-23 but first
*pushed* inside the 07-25 three-commit batch whose head was the mocks commit
— and both runs had installed the identical locked checker wrapper (1.1.411,
from the runs' own logs). The mundane truth: a strict-mode error met the type
gate for the first time on push, and because a multi-commit push runs CI once
at its head, the red run wore an innocent commit's title. The immediate fix
was the same one-line annotation either way; the durable lessons changed
completely — a CI failure belongs to the whole push range, not the title
commit, and a diagnosis that flatters the day's thesis deserves the hardest
look before it enters the record. The attribution failure the gate exists to
prevent nearly happened in its own retelling.

One honest self-correction from the same session: the bootstrap re-score was
estimated at minutes of CPU — enough that a separate parallel CI job was
proposed to shield the fast checks — and the measurement came back at 17
seconds for both regenerations (local gate run, 2026-07-26), quietly
vindicating the originally ruled shape of running the gate inside the existing
test step. The estimate died the way the batch-composition headline died the
day before: by measuring instead of arguing.

## 2026-07-25 — The experiment that refuted its own headline: batch composition acquitted, and the $0.38 contingent that killed a conclusion already written in chat

*The D2d registered-experiments session — design ruled, built, dispatched, and read
end-to-end in one day. Extraction+eval (M1). Feeds: the M1 post's
registered-experiments section (the pre-registration payoff story), its
honest-limitations section (buy-time instability as a new instrument caveat), and the
cost-methodology section (the N=10 batching lever, vindicated). Build record:
DESIGN.md's "D2d registered experiments" entry and its cell-identity ruling.*

The question on the table since certification: the same model, prompt, codebook, and
gold reviews had produced two different quality readings — F1 0.799 when gold reviews
were batched among each other in the lab arm, 0.766 when the same reviews were bought
inside the census among arbitrary corpus neighbors (paired ΔF1 −0.033 [−0.061,
−0.007], `probes/census_vs_gold_gap.py`). Batch composition was the registered prime
suspect, and it had supporting evidence that looked damning: the judge's agreement
with gold rose monotonically as its batches shrank, 0.789/0.801/0.816 at N=50/20/1.
The D2d design (ruled this morning, DESIGN entry same date) bought the isolation:
re-label census reviews with production's own model at N=1, complete a codebook ×
batch-size 2×2 against the judge's stored verdicts, and — the part that ended up
mattering most — pre-register a *contingent* third buy with its trigger fixed in
advance, plus a readings probe (`probes/d2d_reads.py`) committed before any data
existed, so the decision rules were code, not post-hoc analysis.

The morning's numbers told a seductive story. The 2×2 read: the full codebook showed
a real batch penalty (+0.020 [+0.004, +0.037] going solo, run
`agree-20260725T122042Z-22b8acf2` vs the census-sample row), the compact codebook
showed none (−0.003), and the interaction — the registered "does a leaner rule set
beat a muddier context" question — came out +0.023 [+0.003, +0.044], excluding zero.
Contamination confirmed, leaner-codebook hypothesis confirmed, mechanism story
practically writing itself. That conclusion was written into chat as a headline.
Meanwhile the gold read's recovery was only partial (ΔF1 n1−census +0.013 [−0.021,
+0.046], run `certify-20260725T122037Z-ce9315b2`), which tripped the pre-registered
trigger: the interval failed to exclude zero upward, so the contingent fired — 245
gold reviews re-labeled *today* at N=10 among fresh, seeded, same-game census
neighbors (run `d2d-full-n10-gold-recomposed-*`, $0.38 ledger), built precisely to
separate provider drift from batch composition on the acquittal branch.

The contingent refuted the headline. The recall recovery that solo dispatch had
seemed to earn (+0.045 real, n1 vs census) appeared *identically* in the recomposed
cell — which is batched (+0.042 [+0.003, +0.083], recomposed vs census, composition
held fixed). Regrouping every comparison by whether it crosses buy dates made the
pattern unmissable: every same-day composition test is null (the compact pair −0.003
[−0.017, +0.010] at n=1,000 — the tight one; full n1-vs-recomposed −0.012 [−0.046,
+0.022] at n=245), and every cross-day comparison shows the ~0.02–0.03 gap. The gap
travels with *when* the labels were bought, not with how many reviews shared the
prompt. And the celebrated interaction inverted on inspection: the full codebook's
"penalty" had compared a July-19 buy against a today buy, while both compact cells
were bought today — the interaction had measured the day gap wearing the hypothesis's
clothes. The drift-clean codebook comparison (both cells today, N=1, n=1,000, paired
against the judge) reads compact 0.793 vs full 0.811, Δ −0.018 [−0.031, −0.005] —
real, and in the *wrong direction* for the leaner-codebook story. Compact is
genuinely worse at scale, C0.5's recall-loss verdict confirmed; its candidacy for
future buys is closed on evidence, not deferred.

What survives is arguably better than what died. The N=10 batching lever — the thing
that made a $3.80 census possible — is fully vindicated: batching does not degrade
labels, and no future buy needs to pay ~10× prompt tokens for solo dispatch. The
census certification at 0.766 stands as what it always was, a certification of the
labels actually bought. The new finding is **buy-time instability**: the same
temperature-0 configuration produced label sets ~0.02–0.03 F1 apart across buys
[SUPPORTED WITH NAMED RESIDUE — see below], which becomes a standing instrument
caveat for every future buy and re-certification: "same config, same labels" does
not hold across days. Two residues keep the interpretation honest: the recomposition
drew *random* same-game neighbors while the census's actual batches were
*consecutive* ingest-order neighbors, so "the census's exact pathological
compositions" remains a formally untested alternative to serving-state variance; and
the timeline is non-monotone (lab 07-18: 0.799 → census 07-19: 0.766 → today: 0.791),
so whatever moved is variance between serving states, not steady improvement.

The meta-point is the one the M1 post should lead with: pre-registration did its job
twice in one day. The fixed trigger forced a $0.38 purchase whose only role was to
check a conclusion that had already been written down — and it killed it. The
pre-committed decision rules left no room to keep the prettier story. Total session
spend: ≈$2.98 ledger (~$0.45 expected billed under DeepSeek's prefix-cache pricing,
per the census precedent), 5,693 envelopes across five cells, zero failures.

Figure: the same-day-vs-cross-day regrouping (composition null within a day, the
~0.02–0.03 gap across days), and the 2×2 with its day-confound annotation. A share
card is being built at `mocks/` this same session.



*The D2c census-sample session — the instrument-leaves-the-lab chapter, closing the
arc the calibration-PASS entry (same date, below) opened. Extraction+eval (M1).
Feeds: the M1 post's evaluation-methodology section (the census-wide quality claim and
how it's grounded), its honest-limitations section (agreement ≠ accuracy; the
preview-instrument caveat), and the ops story (the capacity-event diagnosis and the
retry fix). Build record: DESIGN.md's "agreement-run journal fit" and "census-sample
stage" entries.*

The session's design work opened with a schema honesty problem. Census-sample scoring
is judge-vs-production — no gold anywhere — but the eval-run journal hard-required a
gold file's path and hash as its measuring-stick pin. Stuffing production's identity
into fields named gold was ruled out on arrival (dishonest naming); the real fork was
one journal with the reference columns generalized versus a sibling agreement-runs
table. The sibling table's argument was epistemic hygiene made structural — a
certification against human truth and two machines agreeing are different kinds of
claim, and separate tables make them unconfusable. It lost to proportionality: the
distinction is already recorded twice on every row (the scorer identity and a new
`reference_kind` column), the metrics child table had half-declared the one-journal
intent at birth (its schema comment names "per-category judge agreement" as expected
growth), and every run kind on the horizon answers the same sentence — *this label
set, scored against that pinned reference, by this procedure*. The accepted cost was
named in the ruling rather than discovered later: one flat table now quietly holds a
sum type, its reference columns meaning different things under different kinds. For
the pool-labels kind, the tamper-evidence property survives by digest — the reference
hash pins the judge's canonically-serialized labels instead of a file's bytes, so an
identical re-dispatch verifies identical.

Three dials, one costed proposal: the sample frame is *reviews* (the judge's unit of
work and the scorer's tally unit — a mention frame would overweight multi-mention
reviews with no clean review-level reading), n = 1,000 (~$5 at calibration's measured
$1.21/250; roughly halves gold's F1 interval, and ±0.02 wasn't worth doubling the
spend), and dispatch stays sync — the Batch API's 50% discount (~$2.50 here) doesn't
pay for a job-submit/poll/download build at this scale. That lever took a second
strike later the same evening: the only Google staff response in the capacity-event
forum thread was an admission that Batch API jobs were stuck in a pending state.
A cost option that is both not-yet-built and operationally unreliable prices
differently than a discount.

The build's one structural move: with two dispatch surfaces needed (gold calibration,
census sample), everything instrument-defining — the model pick and its measured
generation config, the single-review/temperature-0 riders, both refusal shapes, the
durable-mark-on-first-attempt rule — was extracted into one shared engine
(`evals/judge_dispatch`), leaving two thin shells that own only what genuinely
differs: where reviews come from and how text identity is verified. The sample shell's
answer to the identity problem improved on gold's: the minted sample
(`probes/mint_census_sample.py`, seed 20260723, seeded systematic over the census's
135,259 envelopes) carries no review text at all, only each drawn review's text
sha256 — the dispatch prompts from the store and refuses to run over a drifted frame.

Then the instrument met the real world. The full dispatch died within minutes on
503 "high demand" — and kept dying for five hours. The diagnosis chain is the
report-worthy part, because every hypothesis was retired by a measurement rather
than a guess: the quota dashboard showed under 1% usage on every axis (not limits);
a 10-token probe served instantly while a dispatch-shaped 10K-token request hung to
timeout at the same moment (load-sensitive shedding — heavy requests shed first);
the bare `gemini-3-flash` id 404'd while the preview id served and self-reported its
own name (not a retired endpoint — Arda's suggestion to test, worth testing, cleanly
falsified); the status page stayed green throughout (capacity management on a preview
model doesn't rise to incident); and a developer-forum thread reported 50–70% failure
rates on this exact id over one-to-two *weeks* — chronic intermittent degradation,
not an evening outage. The deprecation page completed the picture: the id has a named
successor (`gemini-3.6-flash`) but no shutdown date — a deprioritized preview being
load-shed under demand, exactly the retirement-risk caveat the model-pick entry had
recorded in the morning, now observed live. Arda drove several of the checks — the
dashboard read, the endpoint question, a key-restriction notice that probe logic
ruled unrelated (policy rejects with 403 at the door; we were being shed after
admission).

The incident bought one permanent improvement. Reading the client's retry
timestamps against its code showed full-jitter backoff drawing near-zero delays —
a request could burn all four attempts inside a one-second shed burst, and one
exhausted request aborts a whole run, wasting a hard-won partial window (one attempt
harvested 167 reviews before dying exactly that way — run
`judge-sample-20260723T151117Z-4a4cd931`). The fix was aligned to the provider's own
guidance rather than invented: Google's docs prescribe bounded exponential backoff
with jitter and its SDK retries with delays up to 60s, so the client widened from
4 attempts/1s base to 6 attempts/2s (~30s expected, ~60s worst-case per-request
patience; committed same evening). The first attempt under the new constants
survived twenty minutes of shed storm and banked a trickle where its predecessors
died in seconds — and at ~21:16 local a real window opened and one attempt swept all
819 remaining reviews in 25 minutes, zero refusals, zero failures, $3.80 (run
`judge-sample-20260723T181525Z-df6b5591`). Sample dispatch totaled ~$4.60; D2c
end-to-end, calibration included, ~$5.80.

The number the stage existed to produce: judge-vs-production agreement F1 **0.791
[0.772–0.810]** across all 1,000 sampled reviews, none dropped (eval run
`agree-20260723T184154Z-2ce02b01`, scorer `judge-vs-production/1`). Its meaning
comes from where it sits: production-vs-gold measured 0.766 [0.713–0.811] and
judge-vs-gold 0.816 [0.773–0.855] on the lab slice, and two-annotator agreement is
bounded by each annotator's accuracy — so agreement landing *between* the anchors,
with half the interval width, is the signature of production performing across the
census about as it did on gold. No quality cliff outside the slice the humans
labeled: that is the M1 post's load-bearing sentence, and it is an agreement claim,
not an accuracy claim — the shared-blind-spot caveat from the calibration entry
carries forward unchanged. The texture all points the same direction: precision
0.855 vs recall 0.737 (the judge's recall-shape, confirmed at scale), sentiment
agreement on matches 0.944, the judge's census zero-share 50.3% against gold's
49.2%, quiet-agreement 96.4% where the judge finds nothing, and the weakest slice
exactly where you'd expect fuzz — reviews where the judge emits free-form candidate
aspects (F1 0.758, n=92). One free invariant closed the loop: production's
zero-share in the scored sample, 0.522, equals the draw manifest's empty-envelope
share to the third digit — two independent paths to the same quantity.

The evening closed with the read-through the headline can't show — a scratchpad
deep-read over the same envelopes (session 2026-07-23; journaling per-aspect rows
under the design's `judge_agreement/<aspect>` naming is a registered follow-up, so
every number here is a point estimate without an interval — exploration, not
certification). Agreement turned out aspect-shaped, spanning 0.61 to 0.97: the
concrete, technical aspects agree like instruments should (music 0.974, story 0.912,
performance 0.882, bugs 0.852), while the soft, meta aspects carry the recall gap —
`updates` at 0.611 is the sharpest number in the table (the judge found update-talk
in 64 reviews, production in 31: 35 misses), with `atmosphere` 0.667 and
`characters` 0.745 in the same band. `gameplay` (0.706) is the one aspect wrong in
*both* directions (36 false positives, 23 misses) — a boundary-drawing disagreement,
visible in exemplars where production reads exploration-plus-atmosphere and the
judge reads world-plus-gameplay off the same sentences. Sentiment on matched aspects
holds a strong diagonal (688 positive–positive, 334 negative–negative, single-digit
leakage), with `mixed` the one hard class: the judge's mixed matched as mixed only
20 of 39 times — the same difficulty gold adjudication fought. And the per-game
spread, 0.632 (Darkest Dungeon) to 0.889 (Papers, Please), is the per-aspect finding
seen twice: story-driven games top the table (What Remains of Edith Finch 0.882,
Baldur's Gate 3 0.885) because `story` agrees at 0.91, while sim/management and
live-service games sit low (Tavern Master 0.640, Overwatch 0.642, Starfield 0.644 at
a solid judge-side n of 47) because their mention mix is dominated by exactly the
weak aspects.

The exemplar pass surfaced one genuinely new failure mode: Steam's checklist-template
reviews empty production out. The largest single disagreement (No Man's Sky review
`225371476`, the "---{ Graphics }--- ☐/☑" checkbox format) drew an *empty* production
envelope while the judge extracted eight aspects — the template format defeats
production's reading entirely, a recall failure class invisible until a second
annotator read the same text. Census-wide prevalence is cheaply checkable (the format
has a distinctive signature) and is parked in FIXLOG. The honest frame for all of
this stays the entry's own caveat: agreement is not accuracy, and the judge is the
recall-shaped instrument — its extra mentions are not automatically correct, so
whether `updates` at 0.611 is production missing or the judge over-reading is a
human-adjudication question. The top-disagreement exemplars are the ready-made seed
for exactly that adjudication track.

Figure candidates: the three F1s with their intervals on one axis
(production-vs-gold, judge-vs-gold, production-vs-judge) — the "agreement lands
between the anchors, no cliff" visual, essentially the whole argument in one chart;
and the per-aspect agreement dumbbell (judge-side n vs production-side n per aspect,
sorted by gap) — the `updates` gap and the concrete-vs-soft split in one look.

## 2026-07-23 — The second annotator passed: +0.050 F1 over production, recall-shaped — and a guard built in the morning paid for itself by noon, at zero spend

*The D2c judge build + calibration session — the execution-and-verdict chapter of the
"judge dissolved into a second annotator" design story (previous entry, same date).
Extraction+eval (M1). Feeds: the M1 post's evaluation-methodology section (the judge
calibration and its pass verdict), its honest-limitations section (the shared-blind-spot
caveat), and the batch-composition experiment's motivation (the registered D2d). Build
record: DESIGN.md's "D2c build decisions" entry.*

The build session opened by reopening one thing the design had left generic: "Gemini
flash." Crossing live prices (OpenRouter's model listing, checked in-session) against
the bake-off's gold-scored arms turned the pick into an evidence question rather than a
default: gemini-3-flash-preview was the only flash candidate consistently above
production's 0.766 (F1 0.801 at N=20, 0.789 at N=50 — bake-off `TABLE.md`), where a
0.775-class judge (2.5-flash, the design's literal reading, or 3.1-flash-lite) would
near-guarantee the calibration's *marginal* outcome and a demoted instrument. The
estimate: ~$0.90 for the 250-review calibration, versus ~$2.80 for 3.5-flash's noisier
evidence. Two caveats were stated at pick time rather than discovered later: the same
gold measures the pick and the calibration, so the 0.801 carries winner's-curse
optimism; and a `-preview` id can be retired, so calibration and the census sample
should run close together. Routing went direct to the Gemini API rather than through an
aggregator, purely for instrument continuity — the bake-off measured this model under
one exact generation config (constrained decoding on the classify schema, thinking off,
temperature 0), and the calibration should inherit that config, not a re-plumbed
approximation of it.

Then the store pushed back on the design. The calibration ruling says the judge labels
all 250 gold reviews, CS2's five included — but the label pool's foreign key demands a
review row per envelope, and the census-built reviews table deliberately excludes CS2.
The resolution kept both invariants honest instead of sacrificing either: the driver
backfills the five CS2 gold reviews from their corpus file with their true metadata
(fabricated placeholder rows were never on the table), and the census driver's supply
assertion and selection became scope-aware, so the backfilled rows can never be counted
against the ruled census or bought by a future labeling run. The alternatives died for
real reasons: calibrating on the 245 intersection would have relitigated a design
ruling for convenience, and parking five envelopes outside the pool would have
fragmented exactly the one-envelope-set identity the whole scorer-reuse design leans
on.

The first dispatch attempt cost $0.00, and that sentence is the story. A text
handshake had gone into the driver that morning — gold's text must equal the stored
review's text, because an envelope must never claim text the judge never read — and it
aborted the run on 14 of 250 rows before a single request left the machine. The
diagnosis took minutes: the gold draw stripped edge whitespace at minting
(`draw_gold_set.py`, the `.strip()` on the drawn text) while the corpus rows are raw;
a full sweep confirmed all 14 differ by trailing newlines and the like, zero rows
diverge beyond edges. The handshake softened to strip-equality — content divergence
still aborts — and the run proceeded. A cheap invariant, written on principle, caught
a real two-artifact inconsistency the same afternoon, at the only price you'd ever
want to pay for that lesson: nothing.

Mid-run, Arda spotted a lever the build hadn't considered: Gemini's Batch API — async
transport batching at half the interactive price. The distinction that made it
admissible is worth the report's ink: it batches *requests*, not *reviews into one
prompt*, so each call stays single-review and the design's batch-composition rider
survives intact. The ruling was proportionate rather than eager: not worth a session
of new plumbing plus up-to-24h latency to save ~$0.70 on a calibration that answers
in five minutes — but registered as a mandatory pricing option for the census-sample
and frontier-escalation proposals, where halving the marginal cost changes what
sample size the money buys.

The dispatch itself was uneventful in the way instrumentation should be: 250/250 gold
reviews judged (a 3-review pilot, then the 247 remainder; runs
`judge-20260723T120015Z-b15fed10` and `judge-20260723T120946Z-18373cfa`), zero
refusals, zero durable failures, two evidence repairs, one transient 503 absorbed by
the retry path, $1.21 all-in.

The verdict, journaled and pre-registered before any number existed: judge-vs-gold F1
**0.816 [0.773–0.855]**, precision 0.795, recall 0.838, sentiment accuracy 0.928 —
and a zero-mention share of 0.492 against gold's 0.492, the two instruments agreeing
to the third decimal on how often reviews say nothing (eval run
`certify-20260723T121854Z-80d61796`, scorer `judge-vs-gold/1`, seed 20260718). The
paired read on the 245 shared in-scope reviews
(`probes/judge_vs_production_gap.py`, same seed): Δ(judge − production) F1 **+0.050
[+0.019, +0.083]**, recall +0.085 [+0.050, +0.123], precision +0.016 [−0.027, +0.059]
(indistinguishable), sentiment +0.032 [+0.003, +0.060]. The pre-registered rule reads
F1: **PASS** — the judge is a valid quality reader, its census-sample verdicts count
as reference-grade, and the frontier-escalation contingency stays unspent. The gap's
shape is the interesting part: the judge wins on recall at equal precision — it finds
mentions production misses, it does not relabel what production found.

Two honest riders. The winner's-curse shrinkage the pick had braced for never
materialized — 0.816 sits *above* the 0.801 that motivated the choice — and the
likeliest reason is itself evidence: this model now traces a monotone batch-size line,
0.789 at N=50, 0.801 at N=20, 0.816 at N=1 (bake-off `TABLE.md` + the calibration
run), a fresh data point *for* the batch-composition hypothesis the registered D2d
experiment exists to isolate, worth citing when it runs. And the design session's
standing caveat is unchanged by the pass: two models agreeing is an optimistic bound —
shared blind spots don't disagree — so the human holdout remains the backstop, not a
formality.

Figure: the batch-size trend line (F1 0.789 → 0.801 → 0.816 across N=50/20/1) — the
batch-composition story in one glance. Figure: the paired-Δ forest plot (four metrics,
CIs against zero) — the pass verdict made visual.

*The D2c judge design session — four forks ruled (Arda's rulings), design only, build
next session — plus the misattribution audit sample mint. Extraction+eval (M1). Feeds:
the M1 post's evaluation-methodology section (the "why our judge isn't a judge" story)
and its limitations section (the shared-blind-spot caveat). Design record: DESIGN.md's
"D2c judge design" and "misattribution audit sample" entries, committed 2026-07-23.*

The session opened mechanically: minting the ~100-claim sample for the human
misattribution audit — the check the previous session's mechanical sweep explicitly
could not make, since a verbatim-true quote can still be read upside-down. The draw is
a seeded systematic pass over all 163,842 evidence-carrying census mentions sorted by
(game, aspect, sentiment) — sorting first turns the every-k-th step into an implicit
proportional stratification across all three dimensions at once, so the audited rate
will estimate the population rate with no reweighting (100 primary + 10 reserves, seed
20260723, `probes/mint_misattribution_sample.py`; artifacts under
`eval/audits/misattribution/`). The sample's first item is already the audit's poster
child: a No Man's Sky review whose quote "performace related" is claimed as
performance/negative — verbatim-true, aspect fine, but the complaint sits inside an
otherwise glowing review wrapped in "I trust the team at Hello Games will fix it,"
and whether *negative* survives that context is exactly the judgment no mechanical
check reaches.

Then the design discussion, and its arc is the entry's title. The milestone plan had
reserved an "LLM judge" for its own design session, and the session's first fork
killed the shape everyone associates with the word. A verifier-style judge — shown
the production label, asked to verdict it — died on anchoring: a grader who sees the
answer leans toward endorsing it, which inflates measured quality in precisely the
direction a self-certification cannot afford, and the customary "anything missed?"
recall clause is a fig leaf next to actually running the extraction. What won is an
independent re-labeler: the judge reads the raw review fresh under the same frozen
prompt and codebook, never sees production's answer, and agreement is computed
mechanically afterwards. The clinching discovery was that this design costs almost
nothing to build — a judge run is just another envelope set under its own versions
triple (`gemini-flash / classify-v1 / v2`), so the store's uniqueness key, the
certification scorer, and the paired-bootstrap machinery from the previous session
all apply unchanged. The "judge" came out of the discussion renamed to what it
honestly is: a second annotator, with inter-annotator disagreement as the quality
signal — and the report should tell it that way.

Two riders carry the session's empirical spine forward. The batch-composition finding
(production labels a real −0.033 F1 under the lab arm; eval run
`certify-20260723T093643Z-4eab554c`) promoted the judge's own batching from
implementation detail to design variable — resolved by construction: the judge
dispatches single-review at temperature 0, so the instrument cannot inherit the very
contamination it exists to help measure. And the calibration protocol was
pre-registered *before* any judge number exists, against production's 0.766: pass
(significantly above → the judge's census-sample verdicts count as reference-grade),
marginal (indistinguishable → the judge is a disagreement flagger, and the
census-sample read reports agreement rates, never "judge-corrected quality"), fail
(significantly below → reported as a finding; certification already stands on the
mechanical layers). The graded middle is the honest part: indistinguishable is the
*likely* outcome for a same-tier cross-family model, and deciding now what that
outcome licenses is what stops the number from being rationalized after the fact.

Two smaller rulings round the story out. The census's single refused review (the
Chinese-hosted labeler declining a Tiananmen-line review) stays a refusal — routing
it to the second model for a replacement label was rejected because a substitute from
a different annotator can't quietly join a pool whose identity is one annotator's
triple, and because patching it would launder the instrument-limitation footnote out
of the record; the judge's own refusals score as intersection-plus-disclosed-counts,
since an instrument that declines to read didn't read wrong. And the "model grading
its own homework" demonstration was reframed rather than dropped: under a re-labeler
judge, self-consistency dissolves into the registered batch-composition experiment,
and what remains distinctly self-grading is a 2×2 — each of DeepSeek v4-flash and
Gemini flash verifying its own and the other's gold labels, endorsement rates scored
against gold — because a single "endorses itself 94%" cell can't separate
self-preference from plain leniency. Registered at ~$1, deferred to the post-writing
milestone's cost proposal: it's the empirical receipt for the eval chain's
no-self-grading stance, bought only if the post wants to show it rather than assert
it.

Figure: the pass/marginal/fail decision ladder against production's 0.766 — the
pre-registration made visual. Figure: the self-grading 2×2 (own vs other's labels ×
the two models), which explains the bias-demonstration design in one glance.

*The D2a certification build + D2b mechanical audit — extraction+eval (M1), the $0
half of the eval harness, built and run the session after the D2 scoping. Feeds: the
M1 post's evaluation-methodology section (what "certified" actually certifies) and its
honest-limitations section (the production-vs-lab gap, the 245/250 scope note).*

The scoping session had noticed the headline certification was already paid for — the
census buy had labeled gold's 250 reviews along with everything else, so scoring the
bought envelopes against gold costs nothing. This session ran that score, and it
produced the arc's genuinely surprising number: the production labels are *measurably
worse* than the lab run that justified buying them. Same model, same prompt, same
codebook, same gold — the certification arm (C0.5's winning configuration, scored on
batches composed purely of gold reviews) sits at F1 0.799 on the shared slice, the
census's own envelopes at **0.766 [0.713–0.811]**, and the paired bootstrap puts the
gap at **−0.033 [−0.061, −0.007]** — real at the 95% level, and consistent across
precision (−0.030) and recall (−0.036), with sentiment accuracy indistinguishable
(eval run `certify-20260723T093643Z-4eab554c` in the census DB's `eval_runs` journal,
code `4f74ccb`; the paired read regenerates via `probes/census_vs_gold_gap.py`, seed
20260718). Read separately, the two runs' intervals overlap comfortably and the gap
would pass as noise; the paired resampling — same review subset applied to both sides,
so shared review-difficulty cancels — is what makes it a finding.

Why it matters for the report: the number a certification usually advertises is the
lab number, and here the lab number is flattering by three F1 points. The honest
headline becomes "production agreement 0.766," with 0.799 relabeled as "same
configuration under lab batch conditions." The suspected mechanism was pre-registered
before this number existed: batch composition. The classifier labels ten reviews per
prompt, so every label is conditioned on its nine batch neighbors — the lab arm's
neighbors were other gold reviews, the census's were arbitrary corpus text — and the
model had already shown batch *size* sensitivity (the N=10-beats-N=20 result that
froze the dispatch config). The registered D2d experiment now has an effect size to
chase; provider-side drift stays the weaker alternative suspect (the two runs sit
about a day apart) [PRELIMINARY — the gap is confirmed; its *cause* is hypothesis
until D2d re-buys gold's reviews under both batch compositions].

A smaller scope catch rides along, worth its sentence in the limitations section: gold
holds five CS2 reviews the census never labeled, because gold's draw predates the
usable-pool ruling that excluded CS2 (a ~19-English-review corpus slice). The
certification therefore covers a 245-of-250 intersection — the five are skipped, never
counted as failures, since scoring reviews the model was never sent would fabricate a
penalty — and the narrowing is stored on the run row itself (`n_scored_reviews`), not
buried in prose.

The D2b half produced a reframe instead of a number. The planned "fabricated-quote
rate over ~170K mentions" turned out to measure a door the pipeline had already
locked: the parse verifies every evidence quote is a verbatim substring of its review
*at write time*, nulling failures, so the stored pool's fabricated-quote rate is zero
by construction. The metric decomposed honestly into three: an **invariant audit** —
every stored span re-checked census-wide, **0 violations over 163,842 spans** (96.1%
of 170,532 mentions carry evidence; `probes/captures/census_health/HEALTH.md`) —
upgrading "zero by construction" to "zero, verified"; an **attempted-fabrication
rate** — the write-time repair counts say the model emitted a non-verbatim quote
~2.9% of the time it tried (4,979 repairs across the census run manifests), which is
the model-quality diagnostic the stored data can no longer show because its bad
quotes were repaired away; and the standing caveat that verbatim-checking passes a
real quote read upside-down — misattribution remains the ~100-claim human audit. The
threshold-free per-game health table read coherent rather than pathological, and
photogenic: zero-share spans 23.7% (Redfall — angry reviews itemize their anger) to
80.1% (Goat Simulator — meme reviews say nothing labelable), evidence coverage holds
a tight 93.1–98.1% band across all 49 games, and the drama games top on exactly their
drama — The Day Before's most-mentioned aspect is `developer_conduct`, at 38.1% of
its mentions.

Figure: the paired census-vs-lab comparison — four metrics, both runs' points with
the paired-delta CIs — makes the "lab conditions flatter" point in one glance.
Figure: the per-game zero-share spread (Redfall to Goat Simulator), as the "review
culture varies more than the pipeline does" aside.

## 2026-07-23 — The judge was demoted before it was hired: certification turned out to be already paid for, the "best model in the table" was grading its own homework, and the codebook had studied for the exam

*The D2 scoping discussion (judge + metrics) — extraction+eval (M1), the design-before-
code pass over the eval harness's last unbuilt half. Feeds: the M1 post's
evaluation-methodology section (the trust chain, what an LLM judge is actually for) and
its honest-limitations section (the codebook-overfit disclosure and the holdout).*

Before any judge design started, Arda stopped the room with the first-principles
question: do we even need one? The answer reframed the whole phase. The headline
certification — how well does the production labeler agree with human gold — turned out
to be already paid for: the census buy labeled every usable review, which includes the
gold set's 250, so scoring the bought labels against gold with the existing bake-off
scorer (per-review tallies, bootstrap CIs) costs zero dollars and zero new
infrastructure. The judge's real job is *reach*, not certification: gold at ~5 reviews
per game can say nothing about whether the labeler fails systematically on a
particular game or rare aspect, and a calibrated judge sampling a few thousand census
reviews is the only affordable instrument for that question. That demotion also made
the judge safely cuttable — the plan's stated fallback is that if the judge calibrates
poorly against gold, M1 certifies on the mechanical layers and *reports the judge's
poor agreement as a finding*, which is a better story than a blocked milestone.

The tempting shortcut, argued properly before it died: judge for free via
subscription-quota Claude agents. The bake-off table fed the temptation — its top row
is claude-sonnet-5 at F1 0.910 against the chosen labeler's 0.776 (TABLE.md,
`probes/captures/bakeoff/`), which reads like the best model was already in hand at
zero marginal cost. Three cuts killed it. The 0.910 is self-agreement, not skill:
sonnet-5 drafted the assist labels gold was adjudicated from, which is why the table
itself flags the row "REFERENCE — competes with nobody." A headless agent's
configuration is unpinnable — no temperature control, and the harness's own system
prompt drifts with every CLI release, so the calibration number could never be
regenerated from a manifest. And the economics invert once the harness overhead is
counted: ~15–25K tokens of scaffolding per call turns a ~4M-token flash-tier job into
~40–55M premium-tier tokens of weekly quota, against $1–3 of API spend [planned
estimate, not yet a measured buy]. The durable principle extracted from the wreckage:
the gold-assist ban (gold INSTRUCTIONS §8) extends from the labeler pool to the entire
eval chain — no gold-entangled model may serve as an instrument whose calibration
rides on that same gold. First judge candidate is therefore Gemini flash: a different
family from the DeepSeek labeler, adapter already in the codebase.

The sharpest catch was Arda's, imported from a parallel discussion he ran in another
chat and triaged here against the repo. Gold was protected in one direction — labeled
blind, before any model output, so gold could not drift toward the model. But the v2
codebook was tuned *on* gold's 250 reviews: the thirty-three rulings that became its
wording came from exactly those cases. So the model was tuned toward the test set,
and every v2-on-gold number is development-grade — mildly optimistic by construction.
The remedy, ruled the same session: a fresh human holdout of ~100–150 reviews
(random plus stratified slices), labeled under *frozen* v2 inside M1, with hard cases
recorded for a future v3 but never back-edited — otherwise the holdout becomes
development data too. The triage of the outside chat's five-stage plan is its own
small lesson in checking advice against ground truth: two stages were already-landed
work (the labeler-selection record in DESIGN's C0 closure entries; the v2-on-gold
benchmark in C0.5's paired arm), and its Sonnet-as-verifier stages contradicted its
own circularity caveat two paragraphs earlier. What survived the triage: the holdout,
the observation that a verifier-shaped judge is recall-blind (it can never see the
label that was never emitted) and anchoring-prone (seeing the prediction biases
toward accepting it), and start-small sampling (1–2K before committing to 10K).

The whole D2 plan is settled but unbuilt as of this entry [PRELIMINARY — all
forward-looking numbers (judge cost ~$1–3, sample sizes 1–2K, holdout ~100–150) are
plans, not measurements; the D2c design session still owes the judge's task shape and
calibration protocol].

Figure: the measurement-reach table — three instruments side by side (mechanical
checks: all ~170K mentions at $0 · gold agreement: 250 reviews at $0 · calibrated
judge: ~2K-review sample at ~$2) — makes the "certification was already paid for"
point in one glance.

*The pre-C1 certification experiment (C0.5) — extraction+eval (M1), the sanctioned
reopen under the C0 ruling's first condition (any prompt change re-certifies quality
and N). Feeds: the M1 report/post's methodology section (the certify-before-buy
pattern, annotator-contract alignment) and the cost story.*

The experiment existed because of a timeline fact easy to miss: the machine's
codebook wording was frozen into `classify-v1` on 2026-07-13, but the gold set's
routing rulings — thirty-three of them, settled one at a time with Arda across the
dry runs and the real labeling pass — landed on the 16th and 17th. Every one of
those rulings changed what gold considers correct, and the labeler had seen none of
them. That misalignment is systematic, not noise, and the survey label pool is the
durable asset every downstream consumer folds (the aggregates, the judge
calibration, the sampling study) — so before the census buy, the semantics had to be
bought back into alignment.

The distillation ran under two disciplines worth reporting. First, one shot: the
ruling ledger was distilled into the ontology's machine-side wording
(`src/steamlens/ontology/v2.toml` — same 51 pins, aliases untouched, global rules
8 → 13) exactly once, with no peeking at scores between drafts — iterating wording
against gold F1 would turn certification into training-on-test. Second,
paraphrase-never-quote: gold review text must never enter the machine's contract,
because a codebook that quotes its own exam hands every later-evaluated model the
answers. A consistency sweep before the runs caught three of the new examples
paraphrased too close to the real-pass reviews that triggered their rulings; all
three were replaced with structurally different constructed cases. The triage
itself was an interview — Arda ruled cluster by cluster on which rulings ride into
machine wording (the dry-run routing cluster, the sentiment cluster, the
mention-minting cluster all ride; process rulings stay gold-side), and the sweep
surfaced one genuine gap nobody had ruled on: two of the four demoted aspects
(camera, accessibility) had no machine-side "candidate, never the nearest pin"
guard, while grind and localization did.

Three arms ran on the gold slice at N=10 — the frozen `classify-v1` captures as the
free baseline, the v2 wording full-fidelity, and v2 plus the pre-registered
compact rendering (decision surface only: definition + label-when + do-not-label-when,
no aliases, no examples). Paired bootstrap throughout (10,000 resamples, seed
20260718, `probes/bakeoff_table.py --compare`; captures in
`probes/captures/bakeoff/deepseek-v4-flash-v2*/`). The v2 wording did exactly what a
batch of mostly-deletion rulings should: precision +0.066 [+0.039, +0.098] —
confirmed — with recall dipping a borderline −0.030 [−0.062, +0.000], F1 +0.020
[−0.003, +0.045]. The explanatory key is the mention-economy diagnostic: the v1
baseline over-mints against gold (386 predicted mentions vs gold's 351; zero-aspect
share 48.0% vs gold's 49.2%), v2 lands almost exactly on gold's economy (339
mentions, 52.4%), and compact folds slightly too hard (329, 54.0%). The ruling
batch is precision-lifting deletion, working as designed.

The compact arm is the story's turnaround. It had been pre-registered as the cost
fallback — a ~60% token cut if quality held. Measured, the cut was 26% (9,940 →
7,330 prompt tokens per request; the 60% estimate predated the v2 wording's own
growth), and DeepSeek's prefix cache — which bills the fixed codebook at ~98% off
from the second batch on — collapses the census-scale difference to roughly ten
cents. What that dime buys is a confirmed recall loss: compact vs baseline recall
−0.057 [−0.097, −0.020], the only confirmed-worse cell in the whole experiment.
Dropping the examples costs real mentions and saves almost nothing at these prices.
Arda ruled compact out for dispatch; it stays in the codebase as a first-class
versioned prompt variant (`classify-v1-compact`, its own content-hash pin) for the
prompt experiment the eval-judge milestone (D2) pre-registered.

The N re-check on the winner reproduced the bake-off's shape under entirely new
wording: F1 .786 / .796 / .752 across n5/n10/n20, with n10 beating n20 two-sided
(+0.043 [+0.020, +0.071]). The dispatch config for the census is now fully frozen:
DeepSeek v4-flash, N=10, the `classify-v1` template, ontology v2. The honest
sentence, same shape the C0 ruling insisted on: confirmed better precision, no
evidence of harm, F1 leaning positive — not "confirmed better F1." The entire
certification — three full gold-slice runs plus the ladder — cost about fifteen
cents.

Figure: the three-arm movement against gold's mention economy — baseline → v2 →
v2-compact as points on precision/recall axes (or mention-count bars against gold's
351) — regenerates from the captures and `probes/bakeoff_table.py`.

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
