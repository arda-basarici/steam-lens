"""The Content-Security-Policy header — the XSS backstop on every HTML page.

The templates' first wall is Jinja autoescaping (review text is hostile input
by assumption); this header is the second, structural one: even if markup ever
slipped through an escaping gap, the browser refuses to execute anything the
policy doesn't name. The policy ratifies what the pages already do — external
same-origin scripts only, one stylesheet, self-hosted fonts, same-origin
fetch/SSE, images from Steam's CDN — and closes everything else.

The header lives app-side rather than with its sibling headers in the proxy's
Caddyfile because it carries a per-response **nonce**, which a static config
cannot mint. The nonce exists for exactly one consumer: Cloudflare's bot
detection injects an inline bootstrap script into proxied HTML, embedding
per-response values no hash could pin — but its injector reads the CSP
response header and stamps our nonce onto the scripts it injects
(developers.cloudflare.com/bots/reference/javascript-detections, 2026-08).
The app's own pages carry no inline scripts, so no template ever renders the
nonce; it rides the header alone.

Two deliberate allowances, both narrow:

- ``style-src-attr 'unsafe-inline'`` — the report's bar segments carry
  per-report percentage widths as ``style`` attributes. Attribute-level CSS
  cannot execute script and cannot use selectors (what CSS-exfiltration
  needs); injected ``<style>`` **elements**, the real CSS vector, stay blocked
  by ``style-src 'self'``.
- ``img-src`` admits Steam's asset CDN family by wildcard. Two image classes
  need it: the report's header capsule, whose URL *we* mint
  (``view.HEADER_ART_ORIGIN``; a test pins that origin inside the wildcard),
  and the search results' thumbnails, whose URLs arrive **verbatim from
  Steam's storesearch answer** — Valve serves those from several
  ``steamstatic.com`` hosts and may shift or regionalize them, so an
  exact-host allowance would break thumbnails silently. The widening is
  negligible: the domain is Valve's asset CDN wholesale.

Only ``text/html`` responses wear the header: the JSON surface's answers are
read programmatically, SSE frames are not documents, and the static mount's
files are subresources — a policy there would be dead weight on every
response.
"""

from __future__ import annotations

import secrets
from typing import Final

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

STEAM_CDN_FAMILY: Final = "https://*.steamstatic.com"
"""Valve's asset-CDN domain, allowed wholesale — see the module docstring's
``img-src`` rationale. Public so the render tests can pin the header-art
origin (``view.HEADER_ART_ORIGIN``) inside it."""

_POLICY: Final = "; ".join((
    "default-src 'none'",
    "script-src 'self' 'nonce-{nonce}'",
    "style-src 'self'",
    "style-src-attr 'unsafe-inline'",
    f"img-src 'self' {STEAM_CDN_FAMILY}",
    "font-src 'self'",
    "connect-src 'self'",
    "base-uri 'none'",
    "form-action 'self'",
    "frame-ancestors 'none'",
))
"""The policy pattern, ``{nonce}`` minted per response. ``default-src 'none'``
closes every directive not named; ``base-uri`` and ``form-action`` are the two
it does not govern, so they are explicit. ``frame-ancestors 'none'`` is the
modern successor to the proxy's interim ``X-Frame-Options: DENY``."""


def fresh_policy() -> str:
    """The policy carrying a newly minted nonce — one response's worth.

    Callers besides the middleware exist because Starlette's error middleware
    sits *outside* every user middleware: a 500 page sent by the app-wide
    exception handler never passes the stamper below, so that handler stamps
    its own response with this.
    """
    return _POLICY.format(nonce=secrets.token_urlsafe(16))


class ContentSecurityPolicy:
    """Stamp the policy, with a fresh nonce, onto HTML responses.

    A pure ASGI wrapper rather than Starlette's ``BaseHTTPMiddleware``
    deliberately: the wrapper touches only the ``http.response.start``
    message and never holds the body, so the live narration's SSE stream
    passes through exactly as the app sent it — ``BaseHTTPMiddleware``
    re-streams responses through a task group and is a documented hazard
    around long-lived streams and disconnect propagation.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def stamp(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                if headers.get("content-type", "").startswith("text/html"):
                    headers["Content-Security-Policy"] = fresh_policy()
            await send(message)

        await self.app(scope, receive, stamp)
