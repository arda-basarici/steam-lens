"""Decoding a model's answer when the answer is one JSON object.

The chat's steps each ask a model for one JSON object and nothing else, and
a model sometimes wraps it in a sentence or a code fence anyway. The
tolerance for that is the same for every such step, so it is written once
here. What the object has to hold is each step's own validation.
"""

from __future__ import annotations

import json
import re
from typing import Final

_FENCED_BLOCK: Final = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def decode_json_object(response_text: str) -> object:
    """The answer's JSON value, tolerating prose and a code fence around it.

    Strict decode first. Failing that, the first fenced block that decodes,
    then one JSON value decoded forward from each "{", so text after the
    object cannot defeat it. The tolerance is about where the payload sits;
    a root that is not an object still reaches the caller and fails there.
    Raises the strict attempt's ``JSONDecodeError`` when nothing decodes.

    >>> decode_json_object('Here it is: {"outcome": "ask"} Hope that helps.')
    {'outcome': 'ask'}
    >>> decode_json_object("[]")
    []
    """
    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        for block in _FENCED_BLOCK.findall(response_text):
            try:
                return json.loads(block)
            except json.JSONDecodeError:
                continue
        decoder = json.JSONDecoder()
        start = response_text.find("{")
        while start >= 0:
            try:
                value, _ = decoder.raw_decode(response_text, start)
            except json.JSONDecodeError:
                start = response_text.find("{", start + 1)
            else:
                return value
        raise
