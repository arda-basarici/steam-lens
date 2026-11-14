"""Review search probe (2026-11-14): what does keyword search over the stored
samples cost, and how well does a clustering term identify a kind of game?

The recommender chat nominates games for wants the aspect vocabulary cannot
express ("a roguelike") by searching the stored reviews: a term nominates a
game when it clusters, counted as a share of that game's sampled reviews.
Before an index is added to the serving database, this probe prices one and
reads the clustering on real data. Per question:

- the pool: how many stored reviews belong to the newest report's sample of a
  game, the pool the chat is allowed to search?
- the index: how long does a full-text index over that pool take to build,
  and how large is it, with the text stored in it and as an index only?
- clustering: for a handful of kind-of-game terms, what share of each game's
  sample matches, and how does a share threshold agree with the community
  tags captured from the store? The tags are an incomplete reference: a page
  shows at most twenty, so a game without the tag is not a "no".
- the query matters: ``rogue*`` against the spelled-out roguelike forms shows
  what a careless term does (a rogue is also a character class).

SQLite's FTS5 with its default tokenizer: case-folded, split on punctuation,
no stemming, so "co-op" is the phrase ``co op`` and "racing" does not match
"race". Each term's query below is written by hand to cover its spellings.

Read-only on the database copy. The index is built in a temporary file and
deleted. No request leaves the machine.

Result (2026-11-14, a copy of the serving database taken that evening: 115
games, 60,514 reviews in the newest samples, SQLite 3.49.1):

- The index is cheap. It builds in about a second and takes 12 MB as an index
  only, 33 MB with the text stored in it, beside 18 M characters of review
  text. Thirteen term reads took 0.03 s together.
- A kind-of-game word that reviewers use as a word clusters cleanly. At a 2%
  share with at least three hits, "roguelike" finds 8 of the 10 tagged games,
  "metroidvania" 3 of 4, "racing" 3 of 5, "city builder" 4 of 10 and
  "turn-based" 11 of 15, with no untagged game nominated for the first four
  and one for the last.
- The query's wording decides the false nominations. ``rogue*`` nominates 2
  untagged games at 2% and 6 at 1%, where the spelled-out forms nominate
  none: a rogue is also a character class.
- The defining game of a kind is not described by the word. The two Dark
  Souls games read 1.6% and 1.5% on "souls-like" while Lies of P reads 31.2%.
- Store features are rarely said in reviews. "Open world" finds 16 of 50
  tagged games at 2% and "co-op" 7 of 38, so search cannot stand in for the
  store's own categories, and for traits only a tag carries it finds a
  minority.
- A word that also names a part of many games does not separate. "Puzzle"
  nominates 8 untagged games at 2%; the tagged games' median share is 9.4%
  and the untagged games' highest is 6.4%, so no single threshold serves
  every term.
- "Grind" appears in 98 of 115 games, from 18.1% of Graveyard Keeper's sample
  down. A low share is the common case and says nothing by itself.
- Four samples hold more members than their report counted (Fallout 4: 711
  members, 565 counted); the difference is members without a label under the
  report's versions. The index here holds only the counted reviews, so a
  share's denominator is the report's own sample size.

Limits: the tags are an incomplete reference, so "untagged nominated" mixes
wrong nominations with games that fit and lack the tag in their top twenty
(Dragon's Dogma on "souls-like", SILENT HILL 2 on "puzzle"). The queries were
written by hand for this read. One library, one day.

Run: python probes/review_search_probe.py <path to a serving database copy>
"""

import sqlite3
import statistics
import sys
import tempfile
import time
from pathlib import Path

THRESHOLDS = (0.01, 0.02, 0.03, 0.05)
MIN_HITS = 3

# (label, FTS5 query, substrings that mark a matching store tag; None = no reference)
TERMS = (
    ("roguelike", 'roguelike OR roguelikes OR roguelite OR roguelites OR "rogue like" '
                  'OR "rogue lite"', ("rogue",)),
    ("rogue* (careless)", "rogue*", ("rogue",)),
    ("souls-like", 'soulslike OR soulslikes OR "souls like" OR soulsborne', ("souls-like",)),
    ("metroidvania", "metroidvania*", ("metroidvania",)),
    ("racing", "racing", ("racing",)),
    ("open world", '"open world"', ("open world",)),
    ("turn-based", '"turn based"', ("turn-based",)),
    ("co-op", 'coop OR "co op" OR cooperative', ("co-op",)),
    ("horror", "horror", ("horror",)),
    ("city builder", '"city builder" OR "city builders" OR "city building" OR citybuilder',
     ("city builder",)),
    ("stealth", "stealth", ("stealth",)),
    ("puzzle", "puzzle OR puzzles", ("puzzle",)),
    ("grind (no tag reference)", "grind OR grindy OR grinding", None),
)


def newest_samples(con: sqlite3.Connection) -> dict[int, tuple[str, str, int]]:
    """Each game's newest report: app id -> (run id, name, sample size)."""
    rows = con.execute("""
        select app_id, run_id, game_name, sample_size from reports r
        where created_at = (select max(created_at) from reports where app_id = r.app_id)
    """).fetchall()
    return {app_id: (run_id, name, size) for app_id, run_id, name, size in rows}


# The reviews a report's numbers were counted over: the sample's members that
# hold a label under the report's own versions. A few samples hold members
# without one, and those are outside the report's sample size.
SAMPLE_REVIEWS = """
    select v.text from reports r
    join sample_members m on m.run_id = r.run_id
    join classifications c on c.review_id = m.review_id
        and c.model_version = r.model_version
        and c.prompt_version = r.prompt_version
        and c.ontology_version = r.ontology_version
    join reviews v on v.review_id = m.review_id
    where r.run_id = ?
"""


def build_index(
    con: sqlite3.Connection, scratch: Path, samples: dict, *, keep_text: bool
) -> tuple[float, int]:
    """A full-text index over the newest samples' reviews, in ``scratch``.

    Returns the build time in seconds and the number of reviews indexed.
    """
    index = sqlite3.connect(scratch)
    content = "" if keep_text else ", content=''"
    index.execute(f"create virtual table review_index using fts5(text, app_id unindexed{content})")
    started = time.perf_counter()
    for app_id, (run_id, _, _) in samples.items():
        rows = con.execute(SAMPLE_REVIEWS, (run_id,)).fetchall()
        index.executemany(
            "insert into review_index (text, app_id) values (?, ?)",
            ((text, app_id) for (text,) in rows),
        )
    index.commit()
    elapsed = time.perf_counter() - started
    indexed = index.execute("select count(*) from review_index").fetchone()[0]
    index.close()
    return elapsed, indexed


def tagged_games(con: sqlite3.Connection, needles: tuple[str, ...]) -> set[int]:
    """Games whose captured tag block holds a tag containing any needle."""
    clause = " or ".join("lower(name) like ?" for _ in needles)
    rows = con.execute(
        f"select distinct app_id from storefront_tags where {clause}",
        [f"%{needle}%" for needle in needles],
    ).fetchall()
    return {app_id for (app_id,) in rows}


def read_term(index, con, samples, label, query, needles) -> None:
    hits = dict(index.execute(
        "select app_id, count(*) from review_index where review_index match ? group by app_id",
        (query,),
    ).fetchall())
    shares = {app: hits.get(app, 0) / size for app, (_, _, size) in samples.items()}
    tagged = tagged_games(con, needles) & set(samples) if needles else None
    print(f"\n=== {label}: {query}")
    print(f"  games with any hit: {sum(1 for h in hits.values() if h)} of {len(samples)}; "
          f"reviews matched: {sum(hits.values()):,}")
    if tagged is not None:
        with_tag = sorted(shares[app] for app in tagged)
        without = sorted(shares[app] for app in samples if app not in tagged)
        print(f"  tagged games: {len(tagged)}; their share: "
              + (f"min {with_tag[0]:.1%}, median {statistics.median(with_tag):.1%}, "
                 f"max {with_tag[-1]:.1%}" if with_tag else "none tagged"))
        print(f"  untagged games: {len(without)}; their share: median "
              f"{statistics.median(without):.1%}, max {without[-1]:.1%}")
        print(f"  {'threshold':>9} {'tagged found':>13} {'untagged nominated':>19}")
        for threshold in THRESHOLDS:
            nominated = {app for app in samples
                         if shares[app] >= threshold and hits.get(app, 0) >= MIN_HITS}
            print(f"  {threshold:>9.0%} {len(nominated & tagged):>6} of {len(tagged):<4} "
                  f"{len(nominated - tagged):>19}")
    print("  top games by share:")
    for app in sorted(samples, key=lambda a: -shares[a])[:8]:
        if not hits.get(app):
            break
        mark = "" if tagged is None else ("  [tagged]" if app in tagged else "  [no tag]")
        print(f"    {shares[app]:>6.1%}  {hits[app]:>4} of {samples[app][2]:<5} "
              f"{samples[app][1][:40]}{mark}")


def main() -> None:
    con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
    samples = newest_samples(con)
    stored = con.execute("select count(*) from reviews").fetchone()[0]
    members = sum(
        con.execute("select count(*) from sample_members where run_id = ?", (run_id,))
        .fetchone()[0]
        for run_id, _, _ in samples.values()
    )
    declared = sum(size for _, _, size in samples.values())
    print(f"sqlite {sqlite3.sqlite_version}; {len(samples)} games")
    print(f"stored reviews: {stored:,}; members of the newest samples: {members:,}; "
          f"sample sizes on the reports sum to {declared:,}")

    with tempfile.TemporaryDirectory() as folder:
        full, bare = Path(folder) / "full.db", Path(folder) / "bare.db"
        full_s, indexed = build_index(con, full, samples, keep_text=True)
        bare_s, _ = build_index(con, bare, samples, keep_text=False)
        print(f"reviews indexed (labelled members of the newest samples): {indexed:,}")
        chars = con.execute("select sum(length(text)) from reviews").fetchone()[0]
        print(f"\n== the index (review text in the database: {chars / 1e6:.1f} M characters) ==")
        print(f"  with the text stored in it: {full.stat().st_size / 1e6:.1f} MB, "
              f"built in {full_s:.1f} s")
        print(f"  index only:                 {bare.stat().st_size / 1e6:.1f} MB, "
              f"built in {bare_s:.1f} s")
        index = sqlite3.connect(full)
        started = time.perf_counter()
        for label, query, needles in TERMS:
            read_term(index, con, samples, label, query, needles)
        print(f"\nall {len(TERMS)} term reads together: {time.perf_counter() - started:.2f} s")
        index.close()


if __name__ == "__main__":
    main()
