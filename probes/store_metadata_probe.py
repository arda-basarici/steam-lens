"""Store metadata probe (2026-11-14): what do appdetails and the store page's tag
block answer for the fields the recommender chat needs, and where do they fail?

The recommender chat's hard filters (a racing game, co-op, runs on Mac) read
store metadata the report job has so far thrown away: it keeps the name and
header art from appdetails and nothing else. Before a storage shape or a parse
contract is written, this probe pins the wire truth on a handful of library
games picked to hit the awkward cases. Per question:

- appdetails shape: are ``genres``, ``categories``, ``platforms``,
  ``release_date`` and ``short_description`` present on every game, and typed
  the same way on each? What does ``release_date.date`` look like at the
  production parameters (``cc=us``, ``l=english``), and what does an early
  access game say? Is ``required_age`` an integer or a string?
- appdetails edges: does a game that is no longer sold still answer with data?
  Is the answer still filed under a related app's id for games with DLC (the
  tolerance the parse already carries)?
- the tag block: the store page embeds the community tags with their vote
  counts in an ``InitAppTagModal(...)`` call. Is the call on every page, how
  many tags does it hold, and what fields does a tag carry?
- tag-block edges: what does the page answer for a mature-content game without
  cookies (a redirect to the age check, or a 200 that holds a gate instead of
  the page), and do the age cookies get the real page? What does the page
  answer for a game that is no longer sold?
- robots.txt: is ``/app/`` open to automated reads at all?

Probe-grade: sequential, stdout-narrated, raw requests at the politeness floor
(about thirty requests). Redirects are recorded, never followed. The capture
embeds each appdetails body whole and each page's tag call text, since the
parse tests will be written against those bytes; whole pages are not kept.

Result (2026-11-14, from a laptop, generic User-Agent, thirteen games): every
appdetails answer carried all five fields, filed under the requested id, and
every store page answered HTTP 200 with a tag call of exactly twenty tags,
sorted by count. What the parse has to know:

- ``genres`` rows carry the id as a string (``"9"`` Racing), ``categories``
  rows as an integer. Two category ids can share one description (DualSense
  Controller Support is 57 and 58), so descriptions are not unique keys.
- ``required_age`` is the integer ``0`` on ungated games and the string
  ``"17"`` on DOOM Eternal and Grand Theft Auto V Enhanced.
- ``release_date.date`` reads ``"Sep 17, 2020"`` at these parameters. A game
  in early access carries the genre row ``{"id": "70", "description": "Early
  Access"}`` and its early access launch date (Lethal Company, Solasta II). A
  game that has left early access carries its full release date: Palworld
  reads Jul 9, 2026, and 534 of its 607 stored reviews are older than that.
- The two games believed no longer sold (FIFA 22, Marvel's Avengers) answer
  with full data and a full tag block. They differ from the rest in having no
  ``price_overview`` while ``is_free`` is false. No game in the library lacks a
  store record, so the no-record case was not probed.
- The mature-content pages came back whole without cookies: the real title,
  twenty tags, no gate markup, no redirect. The cookie path never ran.
- A tag row is ``{tagid, name, count, browseable}``; one row (Solasta II's
  Early Access tag) had no ``browseable`` key. Counts do not track the size of
  the game: Backseat, with 72 stored reviews, shows counts of 421 to 521.
- robots.txt disallows nothing under ``/app/`` or ``/api/``.

Limits: one address, one day. The age gate and regional availability depend
on where the request comes from, so the missing gate is a reading for this
address and has not been taken from the serving host. The appdetails answers
filed under a DLC's id, seen on Darkest Dungeon in 2026-09, did not occur.

The User-Agent defaults to a generic string. Pass ``--production-ua`` to send
the door's own named one, which is the reading that matters if the two differ
(the store throttles some default library agents).

Run: python probes/store_metadata_probe.py [--production-ua]
Writes: probes/captures/store_metadata_<utc>.json
"""

import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from steamlens.steam_client import SteamClientConfig

CAPTURES = Path(__file__).parent / "captures"
SLEEP_S = 1.5
GENERIC_UA = "Mozilla/5.0 (compatible; metadata-probe)"

APPDETAILS_URL = "https://store.steampowered.com/api/appdetails"
STORE_PAGE_URL = "https://store.steampowered.com/app/{app_id}/"
ROBOTS_URL = "https://store.steampowered.com/robots.txt"

# The cookies a browser holds after passing the birthday form and the
# mature-content warning. A fixed 1990 birthday; no account, no session.
AGE_COOKIES = {
    "birthtime": "631152001",
    "lastagecheckage": "1-January-1990",
    "wants_mature_content": "1",
    "mature_content": "1",
}

# (app id, library name, why this game). The "why" is the hypothesis the
# probe tests, not a fact: whether a game is delisted or gated is read here.
GAMES = (
    (1145360, "Hades", "baseline; store genres known to be coarse"),
    (588650, "Dead Cells", "the roguelike reference for grading review search"),
    (1846380, "Need for Speed Unbound", "a racing game, the defining-requirement example"),
    (413150, "Stardew Valley", "co-op categories; Mac and Linux platforms"),
    (782330, "DOOM Eternal", "mature content: the age gate"),
    (3240220, "Grand Theft Auto V Enhanced", "mature content, a second gate reading"),
    (1506830, "FIFA 22", "believed no longer sold"),
    (997070, "Marvel's Avengers", "believed no longer sold since 2023"),
    (262060, "Darkest Dungeon", "appdetails filed under a DLC's id since 2026-09"),
    (1623730, "Palworld", "left early access: which date does release_date hold?"),
    (1966720, "Lethal Company", "believed in early access: the genre flag and the date"),
    (2975950, "Solasta II", "believed in early access, a second reading"),
    (3098050, "Backseat", "a small game, 72 stored reviews: fewer than twenty tags?"),
)

TAG_CALL = re.compile(r"InitAppTagModal\(\s*(\d+)\s*,\s*(\[.*?\])\s*,", re.DOTALL)
TITLE = re.compile(r"<title>(.*?)</title>", re.DOTALL)
GATE_MARKERS = ("agegate_birthday_selector", "app_agegate", "contentcheck_desc_ctn",
                "agecheck")
FIELDS = ("genres", "categories", "platforms", "release_date", "short_description")


def get(client: httpx.Client, url: str, **kwargs) -> httpx.Response:
    """One request at the politeness floor; redirects come back as answers."""
    response = client.get(url, **kwargs)
    time.sleep(SLEEP_S)
    return response


def descriptions(items: object) -> list[str]:
    """The ``description`` of each ``{id, description}`` row, or a type note."""
    if not isinstance(items, list):
        return [f"<{type(items).__name__}>"]
    return [str(item.get("description")) if isinstance(item, dict) else repr(item)
            for item in items]


def probe_appdetails(client: httpx.Client, app_id: int) -> dict:
    response = get(client, APPDETAILS_URL, params={"appids": app_id, "cc": "us", "l": "english"})
    report: dict = {"status": response.status_code}
    if response.status_code != 200:
        print(f"  appdetails: HTTP {response.status_code}")
        return report
    body = response.json()
    report["body"] = body
    report["answer_keys"] = sorted(body) if isinstance(body, dict) else None
    entry = body.get(str(app_id)) if isinstance(body, dict) else None
    if entry is None and isinstance(body, dict) and len(body) == 1:
        (entry,) = body.values()
    report["filed_under_requested_id"] = isinstance(body, dict) and str(app_id) in body
    report["success"] = bool(entry and entry.get("success"))
    data = entry.get("data") if isinstance(entry, dict) else None
    if not isinstance(data, dict):
        print(f"  appdetails: keys={report['answer_keys']} success={report['success']} NO DATA")
        return report

    release = data.get("release_date")
    required_age = data.get("required_age")
    report.update({
        "inner_app_id": data.get("steam_appid"),
        "type": data.get("type"),
        "fields_present": {field: field in data for field in FIELDS},
        "genres": descriptions(data.get("genres")),
        "categories": descriptions(data.get("categories")),
        "platforms": data.get("platforms"),
        "release_date": release,
        "required_age": required_age,
        "required_age_type": type(required_age).__name__,
        "short_description_chars": len(data.get("short_description") or ""),
        "has_content_descriptors": "content_descriptors" in data,
        "has_price_overview": "price_overview" in data,
        "is_free": data.get("is_free"),
    })
    print(f"  appdetails: filed under requested id={report['filed_under_requested_id']} "
          f"(keys {report['answer_keys']}) type={report['type']!r}")
    print(f"    genres:     {report['genres']}")
    print(f"    categories: {report['categories']}")
    print(f"    platforms:  {report['platforms']}")
    print(f"    release:    {release}")
    print(f"    required_age={required_age!r} ({report['required_age_type']}) "
          f"price_overview={report['has_price_overview']} is_free={report['is_free']} "
          f"short_description={report['short_description_chars']} chars")
    missing = [field for field, present in report["fields_present"].items() if not present]
    if missing:
        print(f"    MISSING FIELDS: {missing}")
    return report


def read_page(client: httpx.Client, app_id: int, cookies: dict[str, str] | None) -> dict:
    """One store-page read: status, redirect target, gate markers, the tag call."""
    response = get(client, STORE_PAGE_URL.format(app_id=app_id),
                   params={"l": "english"}, cookies=cookies)
    html = response.text if response.status_code == 200 else ""
    match = TAG_CALL.search(html)
    tags = json.loads(match.group(2)) if match else None
    title = TITLE.search(html)
    return {
        "status": response.status_code,
        "location": response.headers.get("location"),
        "html_chars": len(html),
        "title": title.group(1).strip() if title else None,
        "gate_markers": [marker for marker in GATE_MARKERS if marker in html],
        "tag_call_app_id": int(match.group(1)) if match else None,
        "tag_call_text": match.group(0) if match else None,
        "tags": tags,
        "tag_key_sets": sorted({tuple(sorted(tag)) for tag in tags}) if tags else None,
    }


def narrate_page(label: str, page: dict) -> None:
    tags = page["tags"]
    print(f"  page ({label}): HTTP {page['status']}"
          + (f" -> {page['location']}" if page["location"] else "")
          + (f" gate markers {page['gate_markers']}" if page["gate_markers"] else "")
          + (f" title {page['title']!r} ({page['html_chars']:,} chars)" if page["title"] else ""))
    if tags is None:
        print("    no tag call found")
        return
    print(f"    {len(tags)} tags, key sets {page['tag_key_sets']}")
    print("    top 8: " + ", ".join(f"{tag.get('name')} ({tag.get('count')})" for tag in tags[:8]))
    print("    last:  " + ", ".join(f"{tag.get('name')} ({tag.get('count')})" for tag in tags[-2:]))


def probe_tags(client: httpx.Client, app_id: int) -> dict:
    """The tag block without cookies, then with the age cookies if that failed."""
    bare = read_page(client, app_id, cookies=None)
    narrate_page("no cookies", bare)
    report = {"no_cookies": bare, "with_age_cookies": None}
    if bare["tags"] is None:
        with_cookies = read_page(client, app_id, cookies=AGE_COOKIES)
        narrate_page("age cookies", with_cookies)
        report["with_age_cookies"] = with_cookies
    return report


def probe_robots(client: httpx.Client) -> dict:
    response = get(client, ROBOTS_URL)
    lines = response.text.splitlines() if response.status_code == 200 else []
    rules = [line.strip() for line in lines
             if line.strip().lower().startswith(("user-agent", "disallow", "allow"))]
    print(f"\n=== robots.txt: HTTP {response.status_code}, {len(rules)} rules ===")
    for rule in rules:
        print(f"  {rule}")
    return {"status": response.status_code, "rules": rules}


def summarize(reports: list[dict]) -> None:
    print("\n=== summary ===")
    print(f"{'game':<28} {'details':<8} {'genres':>6} {'cats':>5} {'mac':>4} "
          f"{'page':>5} {'tags':>5} {'cookie page':>11} {'cookie tags':>11}")
    for report in reports:
        details, tags = report["appdetails"], report["tags"]
        bare, gated = tags["no_cookies"], tags["with_age_cookies"]
        platforms = details.get("platforms") or {}
        print(f"{report['name'][:27]:<28} "
              f"{'data' if details.get('success') else 'NO DATA':<8} "
              f"{len(details.get('genres') or []):>6} {len(details.get('categories') or []):>5} "
              f"{'yes' if platforms.get('mac') else 'no':>4} "
              f"{bare['status']:>5} {len(bare['tags']) if bare['tags'] else '-':>5} "
              f"{gated['status'] if gated else '-':>11} "
              f"{(len(gated['tags']) if gated['tags'] else '-') if gated else '-':>11}")


def main() -> None:
    production_ua = "--production-ua" in sys.argv[1:]
    user_agent = SteamClientConfig().user_agent if production_ua else GENERIC_UA
    captured_at = datetime.now(UTC)
    print(f"store metadata probe, {captured_at:%Y-%m-%d %H:%M:%SZ}, "
          f"user agent: {'the door default' if production_ua else 'generic'}")

    with httpx.Client(headers={"User-Agent": user_agent}, timeout=30,
                      follow_redirects=False) as client:
        robots = probe_robots(client)
        reports = []
        for app_id, name, why in GAMES:
            print(f"\n=== {name} ({app_id}): {why} ===")
            reports.append({
                "app_id": app_id, "name": name, "why": why,
                "appdetails": probe_appdetails(client, app_id),
                "tags": probe_tags(client, app_id),
            })

    summarize(reports)
    CAPTURES.mkdir(exist_ok=True)
    capture = CAPTURES / f"store_metadata_{captured_at:%Y%m%dT%H%M%SZ}.json"
    capture.write_text(json.dumps({
        "captured_at": captured_at.isoformat(),
        "user_agent": "door default" if production_ua else GENERIC_UA,
        "robots": robots,
        "games": reports,
    }, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\ncapture: {capture.relative_to(CAPTURES.parent.parent)}")


if __name__ == "__main__":
    main()
