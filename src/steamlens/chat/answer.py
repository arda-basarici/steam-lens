"""The answer step's shell — one model call, and a ladder for a faulty answer.

The step turns what a turn found into a ``Reply``: the statements the chat
says next, each with the game it offers, the wants it speaks to and the
excerpts it cites. It writes every reply, whatever the turn: suggestions
from the candidates' material, a question from the pick call's decision to
ask, the finding that nothing fits, and an answer about one game. The
prompt and the validation are pure and live in ``core.answer``; this module
makes the call and decides what a faulty answer costs.

The ladder is the understand step's and the pick step's. A valid answer is
used as it stands. An answer with any fault gets one corrective retry that
names the faults, which is a new question at temperature 0 and so a real
second call. If faults remain, what can be read is kept: a statement about a
game the turn does not name is removed, an offer that cannot be one is read
as none, a cite that was never issued and a want the request does not have
are dropped, and the rest of the reply stands; when the retry itself fails
the first answer is salvaged the same way. An answer that leaves no
statement after the retry ends the turn with a fixed reply.

There is one round, and it is the only one the answer call gets. The faults
it names today are the ones that keep an answer from being read as a record
over the turn's material. Whether a readable reply keeps the chat's rules
is the check's question, and its objections belong in this same round
beside the parse's faults, so a turn's answer is called twice at most.

A reply that offers more games than a reply may is not on the ladder. The
games past the cap are cut in the model's own order and counted, with no
retry spent on them.

Provider trouble is not retried here. The client already retried what a
retry can absorb, and a generation cut off at temperature 0 would be cut off
again. The spend cap refusing the call and provider trouble that outlasted
the client's retries end the turn as unavailable. A permanent rejection is a
configuration fault and propagates.

The step rides the labeler's model until the example conversations and the
development cases say otherwise; the route below is the one place that says
so.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Final

from steamlens.contracts import (
    Answer,
    AnswerBasis,
    AnswerOutcome,
    ChatMessage,
    LlmRequest,
    LlmStage,
    MetricEvent,
    PlayerRequest,
    Sink,
    StageKind,
)
from steamlens.core.answer import (
    ParsedAnswer,
    build_answer_prompt,
    corrective_answer_prompt,
    parse_answer_response,
)
from steamlens.dispatch import narrate
from steamlens.dispatch.census_arm import MODEL_ID, PROVIDER
from steamlens.llm_client import (
    AtCapacityError,
    GenerationIncompleteError,
    LlmClient,
    LlmUnavailableError,
    Route,
)

ANSWER_STAGE: Final = "chat.answer"

# A reply runs to about 150 words, a few hundred tokens with the JSON around
# its statements; the cap is headroom. An answer that reaches it is cut off
# and ends the turn.
_OUTPUT_CAP: Final = 2_048


def answer_route() -> Route:
    """The answer dial: the labeler's model, temperature 0, thinking off.

    A caller hands it to the client it builds as the ``ANSWER`` route.
    Moving the step to another model is this one edit.
    """
    return Route(
        provider=PROVIDER,
        model=MODEL_ID,
        max_output_tokens=_OUTPUT_CAP,
        params={"temperature": 0, "thinking": {"type": "disabled"}},
    )


def answer(
    client: LlmClient,
    conversation: Sequence[ChatMessage],
    request: PlayerRequest,
    basis: AnswerBasis,
    titles: Mapping[int, str],
    sink: Sink,
) -> Answer:
    """Write one turn's reply from ``basis``, walking the ladder on a faulty answer.

    ``conversation`` ends with the player's latest message and ``request``
    is the reading of it. ``basis`` is what the turn found: the candidates'
    material, the library's standing on the wants when nothing fits, the
    pick call's decision to ask, or one game's material. ``titles`` maps
    each library game's app id to its title. Every rung narrates, and
    faults, salvages, cuts and unreadable answers are journalled as metrics.

    The result always says how it was reached. A caller answers with a fixed
    text when it holds no reply.

    Raises ``ValueError`` when a chat message offered a game ``titles`` does
    not hold.
    """
    prompt = build_answer_prompt(conversation, request, basis, titles)
    first = _attempt(client, prompt, request, basis, sink)
    if isinstance(first, Answer):
        return first
    if not first.faults:
        return _replied(AnswerOutcome.ANSWERED, first, sink)

    _count(sink, "answer_faults", len(first.faults))
    narrate(
        sink, ANSWER_STAGE, StageKind.WARN,
        f"the answer had {len(first.faults)} faults — corrective retry",
    )
    second = _attempt(
        client, corrective_answer_prompt(prompt, first.faults), request, basis, sink
    )
    if isinstance(second, ParsedAnswer):
        if not second.faults:
            narrate(sink, ANSWER_STAGE, StageKind.DONE, "the corrective retry read cleanly")
            return _replied(AnswerOutcome.RETRIED, second, sink)
        _count(sink, "answer_faults", len(second.faults))

    for parsed in (second, first):
        if isinstance(parsed, ParsedAnswer) and parsed.reply is not None:
            _count(sink, "answer_salvaged", len(parsed.faults))
            narrate(
                sink, ANSWER_STAGE, StageKind.WARN,
                f"{len(parsed.faults)} faults still standing — the reply is kept without"
                " what was faulty",
            )
            return _replied(AnswerOutcome.SALVAGED, parsed, sink)
    if isinstance(second, Answer):
        return second
    _count(sink, "answer_unreadable", 1)
    narrate(
        sink, ANSWER_STAGE, StageKind.WARN,
        "the answer held no reply after the retry — fixed reply",
    )
    return Answer(AnswerOutcome.UNREADABLE, None, second.faults)


def _replied(outcome: AnswerOutcome, parsed: ParsedAnswer, sink: Sink) -> Answer:
    """The step's result for an answer that holds a reply, with any cut journalled."""
    if parsed.cut:
        _count(sink, "answer_cut", parsed.cut)
        narrate(
            sink, ANSWER_STAGE, StageKind.WARN,
            f"the reply offered {parsed.cut} more games than a reply may — cut from the"
            " end of its own order",
        )
    return Answer(outcome, parsed.reply, parsed.faults)


def _attempt(
    client: LlmClient, prompt: str, request: PlayerRequest, basis: AnswerBasis, sink: Sink
) -> ParsedAnswer | Answer:
    """One call, validated; an ``Answer`` when the call itself failed.

    Catches exactly what ends a turn with a fixed reply: the spend cap
    refusing, provider trouble that outlasted the client's retries, and a
    generation that did not finish. Anything else is a bug and propagates.
    """
    try:
        response = client.complete(LlmRequest(stage=LlmStage.ANSWER, prompt=prompt))
    except (AtCapacityError, LlmUnavailableError) as error:
        narrate(sink, ANSWER_STAGE, StageKind.WARN, f"the answer call failed: {error}")
        _count(sink, "answer_unavailable", 1)
        return Answer(AnswerOutcome.UNAVAILABLE, None, (str(error),))
    except GenerationIncompleteError as error:
        narrate(sink, ANSWER_STAGE, StageKind.WARN, f"the generation did not finish: {error}")
        _count(sink, "answer_unreadable", 1)
        return Answer(
            AnswerOutcome.UNREADABLE, None, (f"the generation did not finish: {error}",)
        )
    return parse_answer_response(response.text, request, basis)


def _count(sink: Sink, name: str, value: int) -> None:
    sink.emit(MetricEvent(stage=ANSWER_STAGE, name=name, value=float(value), unit="count"))
