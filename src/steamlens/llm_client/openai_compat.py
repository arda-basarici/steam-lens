"""The OpenAI-compatible adapter — four vendors behind one implementation.

Groq, Mistral, DeepSeek, and local Ollama all speak the same
``/chat/completions`` dialect, so the seam gets one adapter parameterized by
base URL rather than four near-copies: the composition root constructs one
entry per vendor and registers each under its own name. The known vendors'
roots live here as documented constants.

Two wire conventions differ from Gemini and are normalized here, only here.
The generation ceiling travels as ``max_tokens`` — the one name every compat
vendor accepts (``max_completion_tokens`` is OpenAI-proper's rename, not
reliably served by the compat crowd). And the usage report is *nested, not
disjoint*: ``completion_tokens`` already includes any reasoning tokens, with
``completion_tokens_details.reasoning_tokens`` as a subset — so the parser
subtracts to recover the contract's disjoint output/thinking split; passing
both through unchanged would bill thinking twice at the output rate.

The API key travels only in the ``Authorization`` header, bound by closure at
composition — and only when one is given at all: a local Ollama endpoint wants
no auth, so an empty key sends no header rather than a fake credential.
"""

from __future__ import annotations

import json
from typing import cast

import httpx

from steamlens.contracts import FinishReason, LlmResponse, TokenUsage
from steamlens.llm_client.errors import (
    LlmConfigError,
    ProviderPermanentError,
    ProviderTransientError,
)
from steamlens.llm_client.registry import ProviderEntry, ProviderPayload
from steamlens.llm_client.wire import as_dict, as_int, as_list, as_str

# The known vendors' OpenAI-compatible roots — facts of the landscape, importable
# by the composition root so base URLs are never retyped at wiring sites.
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
MISTRAL_BASE_URL = "https://api.mistral.ai/v1"
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
OLLAMA_BASE_URL = "http://localhost:11434/v1"

_TRANSIENT_STATUSES = frozenset({429, 500, 502, 503, 504})

# The compat dialect's vocabulary, normalized. ``model_length`` is Mistral's
# context-cap variant of ``length``; anything unlisted (``tool_calls``, future
# additions) falls to OTHER — surfaced, never guessed into a clean stop.
_FINISH_REASONS: dict[str, FinishReason] = {
    "stop": FinishReason.STOP,
    "length": FinishReason.LENGTH,
    "model_length": FinishReason.LENGTH,
    "content_filter": FinishReason.REFUSAL,
}

# The typed fields' body keys — each has exactly one home, so a params claim on
# any of them is a config contradiction, not a silent override.
_RESERVED_PARAM_KEYS = frozenset({"model", "messages", "max_tokens"})


def build_payload(
    *, model: str, prompt: str, max_output_tokens: int, params: dict[str, object]
) -> ProviderPayload:
    """The chat-completions body: one user message, params spread in beside it.

    ``params`` is the route's opaque block in the dialect's own top-level
    vocabulary (``temperature``, ``response_format``, ...) — OpenAI-compat
    keeps generation knobs as siblings of ``messages``, not nested under a
    config object. The route's typed fields land as ``model`` and
    ``max_tokens``; a params key claiming any reserved body key fails loud.
    Unlike Gemini, ``model`` rides in the body — which also puts it inside the
    payload the cache key hashes, harmlessly (the key already pairs payload
    with model).
    """
    claimed = _RESERVED_PARAM_KEYS & params.keys()
    if claimed:
        raise LlmConfigError(
            f"route params must not carry {sorted(claimed)}; "
            "set the typed route fields (model, max_output_tokens) instead"
        )
    return {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_output_tokens,
        **params,
    }


def parse_response(raw: str) -> LlmResponse:
    """Normalize one raw chat-completions body — pure, so cache hits re-parse identically.

    The usage split subtracts: on this wire ``completion_tokens`` includes
    reasoning, so output is ``completion_tokens`` minus
    ``completion_tokens_details.reasoning_tokens`` and the reasoning lands as
    the contract's ``thinking_tokens`` — recovering the disjoint split the
    ledger prices. A provider reporting no details block reads as an explicit
    reasoning 0. ``model`` is the provider-reported resolved name; an empty
    string records that the provider did not report one. A null ``content``
    (some vendors' filtered-response shape) reads as empty text; a body with
    no choices normalizes to a refusal with no text; a body that is not a
    JSON object at all fails loud.
    """
    parsed: object = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ProviderPermanentError(
            f"openai-compat body is not a JSON object: {type(parsed).__name__}"
        )
    data = cast(dict[str, object], parsed)
    usage_raw = as_dict(data.get("usage"))
    completion = as_int(usage_raw.get("completion_tokens"))
    details = as_dict(usage_raw.get("completion_tokens_details"))
    reasoning = as_int(details.get("reasoning_tokens"))
    usage = TokenUsage(
        prompt_tokens=as_int(usage_raw.get("prompt_tokens")),
        output_tokens=completion - reasoning,
        thinking_tokens=reasoning,
    )
    model_version = as_str(data.get("model"))
    choices = as_list(data.get("choices"))
    if not choices:
        return LlmResponse(
            text="", model_version=model_version, finish_reason=FinishReason.REFUSAL, usage=usage
        )
    choice = as_dict(choices[0])
    text = as_str(as_dict(choice.get("message")).get("content"))
    finish = _FINISH_REASONS.get(as_str(choice.get("finish_reason")), FinishReason.OTHER)
    return LlmResponse(text=text, model_version=model_version, finish_reason=finish, usage=usage)


def openai_compat_entry(
    api_key: str,
    *,
    base_url: str,
    timeout_s: float = 120.0,
    transport: httpx.BaseTransport | None = None,
) -> ProviderEntry:
    """One configured chat-completions vendor entry, ready for the registry.

    The composition root reads the key from the environment and calls this once
    per vendor — ``base_url`` picks which one (the module's ``*_BASE_URL``
    constants for the known four), and both bind into ``send``'s closure. An
    empty ``api_key`` sends no Authorization header at all — the local-Ollama
    case, where a fake credential would only obscure. ``transport`` is the test
    seam: an ``httpx.MockTransport`` serves canned wire fixtures with no
    network. The one ``httpx.Client`` is shared across calls (connection
    pooling) and is thread-safe under the caller pool. Error messages name the
    base URL, never the key — four vendors share this code, so "which door
    failed" must be readable from the message alone.
    """
    http = httpx.Client(timeout=timeout_s, transport=transport)
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    url = f"{base_url.rstrip('/')}/chat/completions"

    def send(*, model: str, payload: ProviderPayload) -> str:
        """POST to chat/completions; transient trouble raises retryable, the rest for keeps.

        ``model`` is accepted per the ``SendRequest`` contract but already
        rides in the body, placed there by ``build_payload``.
        """
        try:
            resp = http.post(url, headers=headers, json=payload)
        except httpx.TransportError as exc:
            raise ProviderTransientError(
                f"openai-compat ({base_url}) transport failure: {exc!r}"
            ) from exc
        if resp.status_code in _TRANSIENT_STATUSES:
            raise ProviderTransientError(
                f"openai-compat ({base_url}) HTTP {resp.status_code}: {resp.text[:200]}"
            )
        if resp.is_error:
            raise ProviderPermanentError(
                f"openai-compat ({base_url}) HTTP {resp.status_code}: {resp.text[:500]}"
            )
        return resp.text

    return ProviderEntry(build_payload=build_payload, send=send, parse=parse_response)
