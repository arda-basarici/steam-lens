# Census health — the mechanical audit (D2b)

Generated 2026-07-23T09:44:18+00:00 · pool: deepseek-v4-flash / classify-v1 / v2 · fold: census/v2/49g-135259e/ed26574fd6fb · regenerate: `uv run python probes/census_health.py`

## The evidence invariant, verified

- stored evidence spans: 163,842 of 170,532 mentions (96.1% coverage)
- verbatim violations: **0** — the write-path invariant (non-verbatim quotes are repaired to null before storage), re-checked census-wide

## Attempted fabrication (write-time counts, from the run manifests)

- evidence repairs across the census dispatch: 4,979 (over 135,259 labeled reviews)
- approximate attempt base (stored spans + repairs): 168,821 → ~2.9% of attempted quotes were non-verbatim and were nulled at parse; the stored rate is 0% by construction
- approximate because repairs are counted per raw model row, before same-aspect rows collapse into one mention

## Per-game distribution health

No thresholds by design (ruled 2026-07-23): read the shape, flag by eye; tolerance bands are D3's decision.

| game | envelopes | zero-share | mentions/review | evidence cov | candidate share | top aspect (share) |
|---|---|---|---|---|---|---|
| VVVVVV | 6,869 | 36.5% | 1.76 | 97.1% | 2.0% | difficulty (19.2%) |
| Wasteland 3 | 6,194 | 36.5% | 2.24 | 96.2% | 2.5% | story (9.4%) |
| Fallout 4 | 5,898 | 51.5% | 1.19 | 95.7% | 4.7% | mods (10.5%) |
| Overwatch | 5,850 | 65.0% | 0.62 | 96.4% | 1.4% | developer_conduct (10.5%) |
| Mass Effect Legendary Edition | 5,802 | 47.9% | 1.59 | 95.7% | 2.0% | story (15.8%) |
| HELLDIVERS 2 | 5,752 | 39.7% | 1.67 | 96.0% | 2.8% | developer_conduct (16.1%) |
| Phasmophobia | 5,612 | 34.6% | 1.67 | 96.9% | 2.4% | updates (19.4%) |
| Baldur's Gate 3 | 5,002 | 55.8% | 1.24 | 94.5% | 2.9% | story (10.0%) |
| No Man's Sky | 4,792 | 44.9% | 1.41 | 96.3% | 6.4% | content_amount (10.9%) |
| Papers, Please | 4,585 | 68.0% | 0.76 | 95.6% | 2.5% | gameplay (17.1%) |
| Garry's Mod | 4,413 | 75.9% | 0.37 | 96.3% | 3.3% | mods (27.4%) |
| What Remains of Edith Finch | 4,221 | 30.7% | 1.74 | 97.3% | 1.7% | story (26.6%) |
| BioShock Infinite | 3,989 | 45.4% | 1.68 | 94.9% | 2.0% | story (21.2%) |
| Hollow Knight | 3,955 | 60.5% | 0.99 | 93.6% | 2.4% | difficulty (14.3%) |
| Cyberpunk 2077 | 3,747 | 54.0% | 1.50 | 95.7% | 2.3% | story (13.0%) |
| Persona 5 Royal | 3,341 | 61.7% | 1.19 | 94.1% | 3.4% | story (14.7%) |
| Stardew Valley | 3,252 | 57.5% | 0.86 | 95.0% | 6.0% | relaxation (21.4%) |
| Rust | 3,066 | 66.5% | 0.51 | 97.7% | 3.8% | addictiveness (13.9%) |
| Path of Exile | 2,929 | 57.0% | 0.96 | 96.6% | 5.5% | gameplay (10.0%) |
| Darkest Dungeon | 2,902 | 48.6% | 1.24 | 95.7% | 5.3% | difficulty (17.2%) |
| Left 4 Dead 2 | 2,843 | 73.4% | 0.47 | 97.4% | 1.8% | mods (21.8%) |
| Cuphead | 2,623 | 58.6% | 0.89 | 96.8% | 2.5% | difficulty (29.0%) |
| Disco Elysium - The Final Cut | 2,596 | 50.6% | 1.35 | 95.7% | 1.0% | story (12.9%) |
| The Day Before | 2,327 | 50.9% | 0.92 | 97.7% | 2.0% | developer_conduct (38.1%) |
| FINAL FANTASY XIV Online | 2,115 | 47.5% | 1.38 | 95.6% | 3.5% | story (11.9%) |
| Starfield | 2,097 | 30.6% | 2.43 | 94.9% | 7.3% | story (6.1%) |
| Redfall | 2,089 | 23.7% | 3.09 | 97.4% | 3.0% | price_value (9.4%) |
| Rocket League | 1,983 | 67.5% | 0.58 | 98.1% | 3.9% | platform_access (10.7%) |
| Warsim: The Realm of Aslona | 1,975 | 39.8% | 1.58 | 97.2% | 5.5% | gameplay (13.9%) |
| Euro Truck Simulator 2 | 1,806 | 61.4% | 0.76 | 95.0% | 2.1% | relaxation (15.1%) |
| Doki Doki Literature Club! | 1,692 | 69.4% | 0.51 | 97.2% | 5.8% | emotional_impact (19.6%) |
| Democracy 3 | 1,492 | 39.0% | 1.27 | 96.8% | 3.2% | gameplay (18.0%) |
| Satisfactory | 1,458 | 52.2% | 0.95 | 96.0% | 5.2% | addictiveness (18.3%) |
| ELDEN RING | 1,440 | 69.0% | 0.74 | 96.3% | 3.4% | difficulty (14.9%) |
| Tavern Master | 1,350 | 27.0% | 1.97 | 95.9% | 5.5% | gameplay (13.9%) |
| Europa Universalis IV | 1,346 | 59.1% | 0.78 | 97.6% | 2.3% | gameplay (14.1%) |
| DARK SOULS III | 1,344 | 67.3% | 0.86 | 96.5% | 6.1% | combat (13.0%) |
| Cities: Skylines | 1,288 | 50.9% | 1.01 | 97.2% | 3.8% | gameplay (13.7%) |
| Goat Simulator | 1,253 | 80.1% | 0.41 | 93.3% | 6.7% | gameplay (9.8%) |
| Battlefield 2042 | 1,203 | 48.7% | 1.10 | 96.8% | 2.9% | multiplayer (8.8%) |
| Undertale | 1,153 | 69.0% | 0.61 | 93.1% | 2.5% | story (17.7%) |
| A Way Out | 1,107 | 49.8% | 1.15 | 96.4% | 2.8% | story (25.3%) |
| Noita | 1,007 | 54.4% | 0.93 | 96.4% | 2.3% | difficulty (23.2%) |
| Surgeon Simulator | 963 | 65.8% | 0.65 | 94.9% | 5.4% | controls (24.8%) |
| Portal 2 | 680 | 70.3% | 0.67 | 95.8% | 8.2% | story (14.1%) |
| NBA 2K23 | 648 | 63.0% | 0.70 | 94.7% | 1.5% | platform_access (17.4%) |
| Mount & Blade II: Bannerlord | 611 | 48.4% | 1.25 | 96.6% | 6.2% | mods (13.1%) |
| The Lord of the Rings: Gollum | 404 | 36.1% | 2.57 | 95.6% | 5.9% | graphics (9.5%) |
| Shadow of the Tomb Raider: Definitive Edition | 195 | 39.5% | 2.27 | 95.7% | 7.7% | story (13.3%) |
| **all 49 games** | 135,259 | 51.6% | 1.26 | 96.1% | 3.2% | — |
