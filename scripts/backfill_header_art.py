"""Backfill ``reports.header_image`` from Steam's appdetails answers, in place.

The one-off repair behind the 2026-08-20 header-art capture (schema step 8):
reports minted before it carry NULL and render through the legacy
identity-minted URL pattern, which quietly stopped resolving for newer
titles — their assets live only under a per-game content-hash path segment
the pattern cannot guess, so those library cards and og:image tags showed
broken images. This script resolves each pre-capture game once against the
same endpoint, params, pacing floor, and user agent as the app's Steam door
(one request per distinct app, ~1.5 s apart) and stores the ``header_image``
URL verbatim, exactly as a fresh job would. It bypasses the ``steam_client``
package deliberately: the shipped image carries ``src`` only, and the repair
precedent (the reprice, the candidate fold) is stdlib-only scripts the box's
system Python runs against the live database.

A game the store no longer answers for (delisted) stays NULL honestly and
keeps the fallback rendering. Dry-run by default and prints the whole plan,
``--apply`` writes it. Take a file snapshot first (the previous repairs'
precedent: ``serve-pre-<name>-<date>.db``).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
import urllib.parse
import urllib.request
from pathlib import Path

_APPDETAILS_URL = "https://store.steampowered.com/api/appdetails"
_PACING_FLOOR_S = 1.5  # the door's SteamClientConfig.pacing_floor_s, mirrored
_USER_AGENT = "steam-lens/0.1 (+https://github.com/arda-basarici)"


def fetch_header_image(app_id: int) -> str | None:
    """Steam's header-art URL for ``app_id``, or None when the store offers none.

    The same soft/loud split as the door's parser: no-data and a missing or
    empty field answer None (art is garnish), while a malformed response
    fails loud — a wire surprise should stop the repair, not blank a row.
    """
    params = urllib.parse.urlencode({"appids": app_id, "cc": "us", "l": "english"})
    request = urllib.request.Request(
        f"{_APPDETAILS_URL}?{params}", headers={"User-Agent": _USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    entry = payload.get(str(app_id))
    if not isinstance(entry, dict) or not entry.get("success") or "data" not in entry:
        return None
    data = entry["data"]
    if not isinstance(data, dict):
        raise SystemExit(f"appdetails[{app_id}]: data is not an object")
    header_image = data.get("header_image")
    if header_image is not None and not isinstance(header_image, str):
        raise SystemExit(f"appdetails[{app_id}]: header_image is not a string")
    return header_image or None


def pending_games(conn: sqlite3.Connection) -> list[tuple[int, str]]:
    """The distinct games whose report rows still carry no stored art."""
    rows = conn.execute(
        "SELECT app_id, max(game_name) FROM reports"
        " WHERE header_image IS NULL GROUP BY app_id ORDER BY app_id"
    ).fetchall()
    return [(int(app_id), str(name)) for app_id, name in rows]


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", help="write (default: plan only)")
    args = parser.parse_args()
    conn = sqlite3.connect(args.db)
    games = pending_games(conn)
    print(f"games with un-captured header art: {len(games)}")
    if not args.apply:
        for app_id, name in games:
            print(f"  {app_id}: {name}")
        print("dry run: pass --apply to resolve and write")
        return
    resolved = 0
    for position, (app_id, name) in enumerate(games):
        if position:
            time.sleep(_PACING_FLOOR_S)
        url = fetch_header_image(app_id)
        if url is None:
            print(f"  {app_id}: {name} — store offers no art, row stays NULL")
            continue
        with conn:
            changed = conn.execute(
                "UPDATE reports SET header_image = ? WHERE app_id = ?"
                " AND header_image IS NULL",
                (url, app_id),
            ).rowcount
        resolved += 1
        print(f"  {app_id}: {name} — {url} ({changed} row(s))")
    left = conn.execute(
        "SELECT count(*) FROM reports WHERE header_image IS NULL"
    ).fetchone()[0]
    print(f"written; {resolved} game(s) resolved, report rows still NULL: {left}")


if __name__ == "__main__":
    main()
