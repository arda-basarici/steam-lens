"""Census-wide prevalence of checklist-template reviews, and whether they empty production out.

Usage:
    uv run python probes/template_review_prevalence.py

Read-only follow-up to the 2026-07-23 deep read's discovered failure mode:
Steam's "---{ Graphics }--- ☐/☑" template format got an empty production
envelope where the judge extracted 8 aspects (No Man's Sky review 225371476).
This probe measures how much census that shape actually holds — reviews
matching the template signature (a ``---{`` header or a run of ballot-box
characters), and the production-empty rate among matches vs the census
baseline. The outcome routes to a codebook/prompt note for ontology v3 or a
classify-v2 wording batch, not a live fix.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # the signature chars beat cp1252 consoles

REPO = Path(__file__).resolve().parent.parent
PROD = ("deepseek-v4-flash", "classify-v1", "v2")

HEADER_SIGNATURE = "---{"
BALLOT_CHARS = "☐☑☒"  # ☐ ☑ ☒
BALLOT_FLOOR = 3
"""One stray checkbox is quotation; three is a checklist."""


def is_template(text: str) -> bool:
    return HEADER_SIGNATURE in text or sum(text.count(c) for c in BALLOT_CHARS) >= BALLOT_FLOOR


conn = sqlite3.connect(f"file:{(REPO / 'data/steamlens.sqlite3').as_posix()}?mode=ro", uri=True)
rows = conn.execute(
    "SELECT c.review_id, r.app_id, r.text, COUNT(m.id) AS n_mentions"
    " FROM classifications c"
    " JOIN reviews r ON r.review_id = c.review_id"
    " LEFT JOIN mentions m ON m.classification_id = c.id"
    " WHERE c.model_version=? AND c.prompt_version=? AND c.ontology_version=?"
    " GROUP BY c.id",
    PROD,
).fetchall()

census = len(rows)
census_empty = sum(1 for _, _, _, n in rows if n == 0)
matches = [(rid, app_id, str(text), n) for rid, app_id, text, n in rows if is_template(str(text))]
match_empty = [(rid, app_id, text, n) for rid, app_id, text, n in matches if n == 0]

print(f"census envelopes under {'/'.join(PROD)}: {census:,}")
print(f"  production-empty baseline: {census_empty:,} ({census_empty / census:.1%})")
print(f"template matches ('{HEADER_SIGNATURE}' or >={BALLOT_FLOOR} of {BALLOT_CHARS}): "
      f"{len(matches):,} ({len(matches) / census:.2%} of census)")
if matches:
    share = len(match_empty) / len(matches)
    print(f"  production-empty among matches: {len(match_empty):,} ({share:.1%})"
          f" — {share / (census_empty / census):.1f}x the baseline")

print("\n== production-empty template exemplars (longest first, top 10) ==")
for rid, app_id, text, _ in sorted(match_empty, key=lambda r: -len(r[2]))[:10]:
    snippet = " ".join(text.split())[:100]
    print(f"  {rid} · app {app_id} · {len(text):>5} chars · {snippet}…")

conn.close()
