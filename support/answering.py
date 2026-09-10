# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""The support AI answers from facts it was given, or says it cannot.

`support.triage` picks a department. `support.tickets` records the conversation
and refuses the transitions the AI must not make. Neither produces a reply.
This is the layer that does, and most of its design is what it refuses to do.

## Three refusals

**It never answers an escalated ticket, and never calls the model for one.**
The floor sent that ticket to a person. Drafting a reply anyway puts a
plausible answer in front of an operator who is about to paste it, which
converts a refusal into a suggestion. The check runs before anything is spent.

**No reachable model means no answer.** Not a canned fallback, not a templated
"we are looking into it". A deployment with no gateway leg gets
`available=False` and the ticket goes to a person. A desk that invents a reply
while the AI is down is worse than one that admits it is down, because the
customer cannot tell the difference — the same argument that keeps
`ai/gateway/chain.py` from promoting a local runtime it has not probed.

**A fact the department could not measure is stated as unavailable, never
dropped.** Dropping it hands the model a gap to fill. `ai/departments/` already
returns `available: False` rather than a number it did not get; this carries
that into the prompt as `not measured`.

**Where the facts come from.** `support.facts` measures them from the routed
department's own read-only actions — an allowlist, not a risk-tier filter,
because READ_ONLY describes what an action does to the platform and says nothing
about whether its output may reach a hosted model. Passing `facts=` explicitly
skips gathering: the caller measured it, and the caller is the authority.

## "Different AI in different aspects"

`DEPARTMENT_BRIEFS` is the owner's request made auditable: one brief per
department, each with its own scope and its own limits, and a test asserts they
differ from one another — one prompt with a name substituted into it is not a
team of specialists.

Every brief is composed with `NO_INVENTED_FIGURES`, and a test reads the built
prompt rather than trusting that the composition step ran.

## What this module cannot do

It composes a prompt, calls the gateway, and returns what came back. It does
not send, resolve, or act, and it holds no broker, OMS or payment path. A test
asserts the surface stays free of `send`/`execute`/`place_order`/
`close_position`/`refund`/`resolve`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Final

from support.triage import triage

logger = logging.getLogger(__name__)

__all__ = [
    "Answer",
    "DEPARTMENT_BRIEFS",
    "NO_INVENTED_FIGURES",
    "answer_question",
]

#: The sentence every brief is composed with. Named and exported so a test can
#: assert it reached the built prompt rather than trusting the composition.
NO_INVENTED_FIGURES: Final = (
    "State no figure, price, balance, order id, timestamp or account detail that is not "
    "in the FACTS block above. If the facts do not cover the question, say plainly that "
    "you do not have that information and that a member of the team will follow up."
)

#: One brief per department. Each carries its own scope and its own limits —
#: a test asserts no two are identical, because one prompt with a name
#: substituted into it is not a team of specialists.
DEPARTMENT_BRIEFS: Final[dict[str, str]] = {
    "research_intelligence": (
        "You are HOPEFX's Research & Intelligence support specialist. You explain how "
        "backtesting, strategies, indicators and performance statistics work in this "
        "platform: what a walk-forward run does, what Sharpe and Sortino mean here, why a "
        "backtest and a live run can differ. You never interpret a result as a prediction "
        "and you never suggest a trade."
    ),
    "markets_execution": (
        "You are HOPEFX's Markets & Execution support specialist. You explain order types, "
        "fills, partial fills, slippage, spread and broker connectivity, and how the "
        "platform routes an order. You never state the status of a specific order unless it "
        "appears in the facts, and you never place, amend or cancel anything — the platform "
        "gives you no way to, and implying otherwise leaves a customer waiting."
    ),
    "risk_compliance": (
        "You are HOPEFX's Risk & Compliance support specialist. You explain drawdown limits, "
        "margin, exposure, position sizing, the kill switch and prop-firm rules as this "
        "platform implements them. When a limit has refused something, explain the rule "
        "rather than how to get around it. You never advise on whether a level is right for "
        "someone's account — that is a licensed activity this platform does not hold."
    ),
    "data_ops": (
        "You are HOPEFX's Data Operations support specialist. You explain market-data feeds, "
        "ticks, quotes, candles, staleness and what the platform does when a feed degrades. "
        "You never state a current price: prices reach customers through the feed, not "
        "through support, and a price quoted in a support reply is stale the moment it is "
        "written."
    ),
    "system_ops": (
        "You are HOPEFX's System Operations support specialist. You handle slowness, errors, "
        "failed page loads, timeouts and outages: what is known, what a customer can try, and "
        "what has been escalated to engineering. You never promise a fix time you were not "
        "given."
    ),
    "news_intelligence": (
        "You are HOPEFX's News & Sentiment support specialist. You explain where the "
        "platform's news and sentiment signals come from, how they are scored and how they "
        "reach the dashboard. You never characterise the market's direction, and you never "
        "turn a sentiment score into a suggestion to act."
    ),
    "notification_ops": (
        "You are HOPEFX's Notifications support specialist. You explain alerts, delivery "
        "channels, quiet hours, and why a particular notification did or did not arrive. "
        "When a customer wants an alert turned off, explain what it warns about first — some "
        "alerts exist because ignoring them has cost money."
    ),
    "platform_engineering": (
        "You are HOPEFX's Account & Platform support specialist. You handle sign-in, "
        "two-factor authentication, profile settings, the trade journal and where things are "
        "in the interface. You explain how to do things; you never make an account change on "
        "a customer's behalf and you never ask for a password, a one-time code or an API key."
    ),
}

_FALLBACK_BRIEF: Final = (
    "You are a HOPEFX support specialist. Answer only from the facts given, and hand the "
    "conversation to a person when they do not cover the question."
)


@dataclass(frozen=True)
class Answer:
    """A reply, or a stated reason there is none.

    `available=False` with `text=None` is the only shape a failure takes. There
    is no variant carrying a placeholder reply, because a placeholder is
    indistinguishable from an answer once it is in a chat window.
    """

    available: bool
    text: str | None = None
    department: str | None = None
    provider: str | None = None
    model: str | None = None
    needs_human: bool = False
    unavailable_reason: str | None = None
    facts: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "text": self.text,
            "department": self.department,
            "provider": self.provider,
            "model": self.model,
            "needs_human": self.needs_human,
            "unavailable_reason": self.unavailable_reason,
            "facts": dict(self.facts),
        }


def _render_facts(facts: dict[str, Any] | None) -> str:
    """Render the fact block, stating the unmeasured rather than omitting it.

    A `None` becomes `not measured`. Dropping the key would leave the model a
    gap it is very willing to fill — the same reason `ai/departments/` returns
    `available: False` instead of a plausible number.
    """
    if not facts:
        return "(none supplied — you have no platform data for this customer)"
    lines = []
    for key in sorted(facts):
        value = facts[key]
        lines.append(f"- {key}: " + ("not measured" if value is None else repr(value)))
    return "\n".join(lines)


def _build_prompt(question: str, *, department: str, facts: dict[str, Any] | None) -> str:
    brief = DEPARTMENT_BRIEFS.get(department, _FALLBACK_BRIEF)
    return (
        f"{brief}\n\n"
        "You are replying to a customer of a live trading platform. Be brief, concrete and "
        "plain. Do not greet at length, do not apologise repeatedly, and do not speculate.\n\n"
        f"FACTS (everything the platform measured for this ticket):\n{_render_facts(facts)}\n\n"
        f"{NO_INVENTED_FIGURES}\n\n"
        f"CUSTOMER QUESTION:\n{question}\n\n"
        "Your reply:"
    )


def _call_gateway(*, prompt: str, operator: str, timeout_s: float) -> Any:
    """The single seam where a model is reached.

    One function so the tests patch a boundary rather than a vendor, and so
    every refusal above it is exercised against the real composition path.
    """
    from ai.gateway.client import GatewayClient, ModelRequest

    return GatewayClient().call_sync(
        ModelRequest(role="fast", prompt=prompt, timeout_s=timeout_s),
        operator=operator,
    )


def _gather(department: str) -> dict[str, Any]:
    """Measure what this department can contribute. The single fact seam.

    Separate from `support.facts.gather_facts` only so the tests patch a
    boundary in this module rather than reaching into another one — the call is
    a straight delegation.
    """
    from support.facts import gather_facts

    return gather_facts(department)


def answer_question(
    question: str,
    *,
    facts: dict[str, Any] | None = None,
    operator: str = "support_desk",
    timeout_s: float = 20.0,
) -> Answer:
    """Draft a reply, or state why there is none. Never both, never neither."""
    decision = triage(question)

    if decision.needs_human:
        # Before any spend, and before any model sees the question. A drafted
        # reply on an escalated ticket is a suggestion wearing a refusal's
        # clothes.
        return Answer(
            available=False,
            needs_human=True,
            department=decision.department,
            unavailable_reason=(decision.escalation_reason or "This question is handled by a person."),
        )

    if decision.department is None:
        # Unroutable. Answering it with a generalist is the guess triage
        # already declined to make.
        return Answer(
            available=False,
            needs_human=True,
            unavailable_reason="No department owns this question; a person should read it.",
        )

    # `None` means "go and find out"; `{}` is a caller deciding there are no
    # facts. Conflating them would make a deliberate empty block indistinguishable
    # from an unmeasured one — the distinction this module exists to keep.
    if facts is None:
        try:
            facts = _gather(decision.department)
        except Exception as exc:
            # The facts improve an answer; they are not a precondition for one.
            # A broken registry must not take the support desk down with it —
            # and the prompt still says "none supplied", so the model is told
            # it has nothing rather than left to assume.
            logger.error("support: fact gathering failed for %s: %s", decision.department, exc)
            facts = {}

    prompt = _build_prompt(question, department=decision.department, facts=facts)

    try:
        response = _call_gateway(prompt=prompt, operator=operator, timeout_s=timeout_s)
    except Exception as exc:
        # Deliberately broad: a budget refusal, a timeout, a dead vendor and a
        # transport error all mean the same thing to a customer — there is no
        # AI answer right now — and each must reach a person rather than a
        # narrower handler that lets one class through as a reply.
        # Logged at ERROR, not DEBUG: an AI support desk that has silently
        # stopped answering looks exactly like one with no tickets.
        logger.error("support: no AI answer available (%s: %s)", type(exc).__name__, exc)
        return Answer(
            available=False,
            needs_human=True,
            department=decision.department,
            unavailable_reason=f"The support AI is unavailable ({type(exc).__name__}).",
            facts=dict(facts or {}),
        )

    text = (getattr(response, "text", "") or "").strip()
    if not text:
        # A blank completion is a failure that looks like a success.
        logger.error("support: model returned an empty reply for %s", decision.department)
        return Answer(
            available=False,
            needs_human=True,
            department=decision.department,
            unavailable_reason="The support AI returned an empty reply.",
            facts=dict(facts or {}),
        )

    return Answer(
        available=True,
        text=text,
        department=decision.department,
        provider=getattr(response, "provider", None),
        model=getattr(response, "model", None),
        needs_human=False,
        facts=dict(facts or {}),
    )
