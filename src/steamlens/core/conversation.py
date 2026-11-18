"""A conversation as a model reads it: one block of data, the same for every step.

Two of the chat's steps read the conversation. The understand step fills
the request from it, and the answer step writes a reply that has to follow
what was said. Both get it the same way, so it is rendered once here.

The conversation is the player's text and the chat's earlier replies, and
the player's half is typed by whoever opens the tab. It crosses into a
prompt as one line of JSON inside a delimited block that the prompt
introduces as data and never instructions.

A reply that offered games carries them as a numbered list with the
library's exact titles, written by code from the message's record. "The
second one" is read against that list and never against the reply's prose,
where a game mentioned and turned down can come first.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from steamlens.contracts import ChatMessage


def render_conversation(conversation: Sequence[ChatMessage], titles: Mapping[int, str]) -> str:
    """The conversation as one line of JSON, with "<" written as its escape.

    With "<" escaped, no message can spell the tag that closes the data
    block and follow it with text that reads as instructions; the JSON still
    decodes to the same characters.

    A message that offered games lists them under "offered", numbered from
    one in the order offered, each with its title from ``titles``, which
    maps a library game's app id to its title. Raises ``ValueError`` for an
    offered game ``titles`` does not hold, since the chat offers library
    games only.

    >>> from steamlens.contracts import ChatRole
    >>> render_conversation([ChatMessage(ChatRole.PLAYER, "a <b>calm</b> game")], {})
    '[{"role": "player", "text": "a \\\\u003cb>calm\\\\u003c/b> game"}]'
    """
    return json.dumps(
        [_message_row(message, titles) for message in conversation], ensure_ascii=False
    ).replace("<", "\\u003c")


def _message_row(message: ChatMessage, titles: Mapping[int, str]) -> dict[str, object]:
    row: dict[str, object] = {"role": message.role.value, "text": message.text}
    if not message.offered:
        return row
    unknown = [app_id for app_id in message.offered if app_id not in titles]
    if unknown:
        raise ValueError(
            f"a chat message offered the games {unknown}, which the library does not hold — "
            "the chat offers library games only, so the message or the library is wrong"
        )
    row["offered"] = [
        {"number": number, "title": titles[app_id]}
        for number, app_id in enumerate(message.offered, start=1)
    ]
    return row
