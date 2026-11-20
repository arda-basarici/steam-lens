"""Behavioral claims on the chat's page — what is served before the script runs.

The claims: the page serves at its address with the script wired and the
message box limited to the route's own length; it is unlisted, so it asks
search engines to leave it out, carries no share card, and no page of the
site links to it; a screen reader's region is present from first paint; it
wears the content policy like every page; an app composed without the chat
has no such page; and the script sends nothing of the conversation but the
identifier and the new message, and never reads a reply as markup.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response

from steamlens.serve.web import attach_web

_STATIC_DIR = (
    Path(__file__).resolve().parent.parent / "src" / "steamlens" / "serve" / "web" / "static"
)


def _app(*, max_chars: int | None = 1_000) -> FastAPI:
    app = FastAPI()
    attach_web(
        app, lambda _: None, lambda _: False,
        load_report_cards=lambda: (), chat_message_max_chars=max_chars,
    )
    return app


def _get(app: FastAPI, path: str) -> Response:
    async def fetch() -> Response:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(path, headers={"accept": "text/html"})

    return asyncio.run(asyncio.wait_for(fetch(), timeout=10.0))


def test_the_page_serves_with_its_script_and_the_routes_own_message_length() -> None:
    page = _get(_app(max_chars=640), "/chat")
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert '<script src="/static/chat.js?v=' in page.text
    assert 'maxlength="640"' in page.text
    assert '<label for="chat-input" class="visually-hidden">' in page.text


def test_the_page_is_unlisted() -> None:
    """Search engines are asked to leave it out, it has no share card, and
    no page of the site points a visitor to it."""
    app = _app()
    page = _get(app, "/chat").text
    assert '<meta name="robots" content="noindex, nofollow">' in page
    assert "og:title" not in page
    for path in ("/", "/reports", "/chat", "/no-such-page"):
        assert 'href="/chat' not in _get(app, path).text, path


def test_a_screen_readers_region_is_present_from_first_paint() -> None:
    """A region inserted later is announced unreliably, so it is in the
    served page and the script only feeds it."""
    page = _get(_app(), "/chat").text
    assert '<p id="chat-announce" class="visually-hidden" role="status">' in page


def test_the_page_wears_the_content_policy() -> None:
    policy = _get(_app(), "/chat").headers["content-security-policy"]
    assert "default-src 'none'" in policy
    assert "connect-src 'self'" in policy


def test_an_app_composed_without_the_chat_has_no_such_page() -> None:
    assert _get(_app(max_chars=None), "/chat").status_code == 404


def test_the_script_sends_only_the_message_and_the_identifier_and_reads_no_markup() -> None:
    """The server keeps the conversation, so the request's body is the two
    fields and nothing the page has on screen. A reply is a model's text
    written from reviews: it lands as text."""
    script = (_STATIC_DIR / "chat.js").read_text(encoding="utf-8")
    assert "JSON.stringify({ message: text, conversation })" in script
    assert script.count("fetch(") == 1
    for needle in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
        assert needle not in script, needle
    assert "localStorage" not in script and "sessionStorage" not in script
    assert "document.cookie" not in script


def test_a_game_a_reply_only_speaks_of_is_labelled_apart_only_beside_offered_games() -> None:
    """On a turn about one game there is no offered row, and its report
    labelled "also mentioned" reads as an aside (seen on the first trial in
    a browser). The label is kept for a game set aside next to suggestions."""
    script = (_STATIC_DIR / "chat.js").read_text(encoding="utf-8")
    assert 'turn.offered.length > 0 ? "also mentioned" : "reports"' in script
