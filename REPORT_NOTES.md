# Report notes — SteamLens

Raw material for milestone reports and posts: decision narratives distilled at the
moment they happen, so the reports can tell the story without excavating chat logs.
Append-only, newest first. Each entry is a self-contained story with its date and the
decisions it feeds.

---

## 2026-07-09 — The corpus dodged a bullet it never knew was fired

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
