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

There is one round, and it is the only one the answer call gets. Two kinds
of fault share it. The parse's are the ones that keep an answer from being
read as a record over the turn's material. The check's (``core.check``) are
the rules a readable record still has to keep: a cite fetched for the game
it is used for, a conflict with a must named and cited, a miss spoken to,
no numeral and no quote. Both are named in the one retry, so a turn's
answer is called twice at most. What the check still objects to after it
is removed by the smallest unit it is in, a cite, a statement or a game,
and the rest of the reply stands. A reply that offered games and has none
left after that, or no statement left, is withheld: the turn ends with a
fixed reply and its own outcome, since a readable answer that was not
shown is a different thing to count than a broken one.

Three of the check's rules cost nothing and do not ask for the retry by
themselves: relayed wording, a working word and length. They are named in
a retry that runs for another reason and are recorded either way. Every
objection is journalled by its rule and by how it ended.

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

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Final

from steamlens.contracts import (
    Answer,
    AnswerBasis,
    AnswerOutcome,
    CandidatesMaterial,
    ChatMessage,
    LlmRequest,
    LlmStage,
    MetricEvent,
    PlayerRequest,
    Reply,
    SettledObjection,
    Sink,
    StageKind,
)
from steamlens.core.answer import (
    ParsedAnswer,
    build_answer_prompt,
    corrective_answer_prompt,
    parse_answer_response,
)
from steamlens.core.check import (
    Enforced,
    Raised,
    check_reply,
    enforce,
    settle,
    turn_evidence,
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
    faults, objections, salvages, cuts and unreadable answers are journalled
    as metrics.

    The result always says how it was reached, and carries what the check
    objected to with how each objection ended. A caller answers with a
    fixed text when it holds no reply.

    Raises ``ValueError`` when a chat message offered a game ``titles`` does
    not hold.
    """
    prompt = build_answer_prompt(conversation, request, basis, titles)
    turn = turn_evidence(request, basis, conversation, titles)
    first = _attempt(client, prompt, request, basis, sink)
    if isinstance(first, Answer):
        return first
    raised = check_reply(first.reply, turn) if first.reply is not None else ()
    if first.reply is not None and not first.faults and not _asks_for_retry(raised):
        standing = Enforced(first.reply, (), tuple(found.objection for found in raised))
        return _replied(
            AnswerOutcome.ANSWERED, first.reply, (), settle(standing), first.cut, basis, sink
        )

    named = (*first.faults, *(found.objection.words for found in raised))
    _count(sink, "answer_faults", len(named))
    narrate(
        sink, ANSWER_STAGE, StageKind.WARN,
        f"the answer had {len(named)} faults — corrective retry",
    )
    second = _attempt(client, corrective_answer_prompt(prompt, named), request, basis, sink)
    retried = tuple(found.objection for found in raised)
    offered_before = first.reply.offered if first.reply is not None else ()
    if isinstance(second, ParsedAnswer):
        again = check_reply(second.reply, turn) if second.reply is not None else ()
        if second.reply is not None and not second.faults and not _asks_for_retry(again):
            narrate(sink, ANSWER_STAGE, StageKind.DONE, "the corrective retry read cleanly")
            standing = Enforced(second.reply, (), tuple(found.objection for found in again))
            objections = settle(
                standing, retried=retried, offered_before=offered_before,
                offered_after=second.reply.offered,
            )
            return _replied(
                AnswerOutcome.RETRIED, second.reply, (), objections, second.cut, basis, sink
            )
        _count(
            sink, "answer_faults",
            len(second.faults) + sum(found.asks_for_retry for found in again),
        )

    withheld: Answer | None = None
    for parsed, corrected in ((second, retried), (first, ())):
        if not isinstance(parsed, ParsedAnswer) or parsed.reply is None:
            continue
        enforced = enforce(parsed.reply, turn)
        objections = settle(
            enforced, retried=corrected, offered_before=offered_before,
            offered_after=parsed.reply.offered,
        )
        faults = (*parsed.faults, *(objection.words for objection in enforced.removed))
        if enforced.reply is None:
            withheld = withheld or Answer(AnswerOutcome.WITHHELD, None, faults, objections)
            continue
        _count(sink, "answer_salvaged", len(faults))
        narrate(
            sink, ANSWER_STAGE, StageKind.WARN,
            f"{len(faults)} faults still standing — the reply is kept without"
            " what was faulty",
        )
        return _replied(
            AnswerOutcome.SALVAGED, enforced.reply, faults, objections, parsed.cut, basis, sink
        )
    if withheld is not None:
        _count(sink, "answer_withheld", 1)
        _count_objections(sink, withheld.objections)
        narrate(
            sink, ANSWER_STAGE, StageKind.WARN,
            "the check removed what the answer offered — fixed reply",
        )
        return withheld
    if isinstance(second, Answer):
        return second
    _count(sink, "answer_unreadable", 1)
    narrate(
        sink, ANSWER_STAGE, StageKind.WARN,
        "the answer held no reply after the retry — fixed reply",
    )
    return Answer(AnswerOutcome.UNREADABLE, None, second.faults)


def _asks_for_retry(raised: Sequence[Raised]) -> bool:
    return any(found.asks_for_retry for found in raised)


def _replied(
    outcome: AnswerOutcome,
    reply: Reply,
    faults: tuple[str, ...],
    objections: tuple[SettledObjection, ...],
    cut: int,
    basis: AnswerBasis,
    sink: Sink,
) -> Answer:
    """The step's result for a turn that holds a reply, with what there is to count journalled.

    Beside the cut and the objections, two things a later stage rules on
    are counted on a turn that had candidates: a reply that offers none of
    them, and the offered games no statement cites a review for.
    """
    if cut:
        _count(sink, "answer_cut", cut)
        narrate(
            sink, ANSWER_STAGE, StageKind.WARN,
            f"the reply offered {cut} more games than a reply may — cut from the"
            " end of its own order",
        )
    _count_objections(sink, objections)
    if isinstance(basis, CandidatesMaterial):
        cited = {statement.game for statement in reply.statements if statement.cites}
        uncited = sum(game not in cited for game in reply.offered)
        if not reply.offered:
            _count(sink, "answer_no_offer", 1)
        if uncited:
            _count(sink, "answer_uncited_offers", uncited)
    return Answer(outcome, reply, faults, objections)


def _count_objections(sink: Sink, objections: Sequence[SettledObjection]) -> None:
    """One count for each rule and ending, such as ``check_numeral_removed``."""
    ended = Counter(
        f"check_{settled.objection.rule.value}_{settled.rung.value}".replace("-", "_")
        for settled in objections
    )
    for name, count in sorted(ended.items()):
        _count(sink, name, count)


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
