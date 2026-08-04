# Holdout pass notes — rulings and process

Labeled 2026-08-04/05 by Arda under frozen codebook v2. This file records the
pass-internal rulings (interpretations within v2, checked against gold's case
law before adoption — a ruling contradicting gold precedent would be annotator
drift; none did) and the review process, for the M2 report's disclosure.

## Process

Batch-of-10 cadence, the gold-workbook rhythm: Arda labeled blind to machine
labels; Claude ran a mechanical gate per batch (grammar, verbatim evidence,
sentiment vocabulary, pinned-label resolution, candidate sweep) and a
substantive second read against codebook v2 only — production labels stayed
unconsulted until the pass completed. Flags were resolved by Arda's ruling;
Arda holds the final call on every mention. Same assist-and-adjudicate shape
gold's manifest records.

One disclosed exception to the sheet's game-name blindness: review 219726663's
"og vs remaster" referent was resolved through the draw's provenance (app id →
Goat Simulator, the original) because every label in the review turned on
which product it sat on. Provenance, not machine labels — the blind held.

## Rulings (chronological)

1. Friends-play-grounded enjoyment → `multiplayer` when the with-friends
   condition grounds the evaluation; companionship narration stays zero.
   (Gold precedent ×2: "fun with friends", "Better with friends".)
2. `community` skipped for review-bomber rants — reported third-party upset
   is not the reviewer's evaluation (Arda's ruling, reviews 49959123 /
   49952215).
3. `adaptation` as the deliberate unified candidate token for
   fidelity-to-source praise, overriding exact reviewer wording (recurrence
   signal; the promotion loop clusters candidates anyway).
4. rng-unfairness → `balance` when the mechanism is named (gold precedent ×2);
   affectionate rng warnings ("BEWARE THE RNG GOD") → `balance / neutral`.
5. Terse accusations with no named mechanism stay zero ("Rigged 100%").
6. Third-party companies (Epic-the-store in a Borderlands review) are not
   `developer_conduct` — the label means the people/company behind the game.
7. Reviewer-folded enumerations decompose to the claim, not the contributors
   ("every play is different due to characters, expansions and endings" →
   `replayability`, not three labels on one span).
8. Anticipation is not evaluation ("looking forward to the rest of the DLC" →
   nothing).
9. Boycott-by-implication is not evaluation (review 49965833's "because of
   gearbox's actions" stays zero; an explicit charge like "2K doesnt give a
   ♥♥♥♥" labels).
10. Update-superseded reviews label the current verdict; the quoted original
    is historical context (review 13526406, per the codebook's update rule).

## Candidate tokens minted

`adaptation` (×10, the board-game-port cluster) · `QoL` (×1) ·
`single-player` (×1).

## Run of record

`holdout-20260804T215600Z-c0edb01a` (journaled in the census store's
eval_runs; mirrored in `agreement.json` beside this file).
