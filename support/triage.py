# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""Who answers a customer, and when a human must.

Owner requirement, 2026-09-10: a support surface where the AI engages, issues
reach a human, and the operator can watch in real time and take over — with
"different AI in different aspects of any question".

The specialists already existed. `ai/departments/` holds eleven of them, each
delegating to code that already exists and returning `available: False` rather
than a number it did not get. What was missing is the customer-facing flow
around them: nothing routed a question to a specialist, and nothing decided when
a person had to be involved.

This module is that decision, and only that decision. **It does not answer and
it cannot act** — no broker, no OMS, no mailer, no refund path. It says who
should handle a question and whether a human must. A test asserts the surface
stays free of `send`/`reply`/`execute`/`place_order`/`close_position`/`refund`,
because a triage module that could also reply is one edit away from replying to
something it should have escalated.

## The floor

This is a money-moving platform, so the dangerous failure is not a wrong answer
— it is a **confident** one on a question the AI should never have taken.

    Some categories always reach a human, whatever the AI's confidence.

Financial advice. Anything touching an account, a balance or a withdrawal. A
complaint. A legal or regulatory question. A suspected security incident.

Not "escalate when unsure": *always*. "Unsure" is a threshold, and a threshold
cannot catch the case that matters — an AI that is wrong and certain. This is
the same shape as `ai/notify/policy.py`'s rule that a CRITICAL notification is
never suppressed, and it is enforced the same way: the escalation decision
returns before any auto-answer path is reachable, and `TriageResult` carries no
field that could turn it off. An escalated result also carries
`suggested_reply=None`, so there is no draft for a UI to send by accident.

Two of these are worth spelling out because they are not obviously support
questions:

* **Financial advice** — "should I buy gold?" is regulated advice in most
  jurisdictions, and this platform is not licensed to give it. That is a legal
  exposure, not a quality one.
* **Security incident** — "someone logged into my account" needs a person
  within minutes, and an AI that answers it helpfully has delayed the response.

## Routing is declared, and unknown is not a guess

`DEPARTMENT_ROUTES` maps a category to a department that exists — a test asserts
every target is in `ai.departments.DEPARTMENTS`, because a route to a department
nobody built is a dead end discovered at 3am by a customer.

A question that matches nothing is **not** routed to a plausible default. It
goes to a human with `department=None`. Guessing "probably research" is Rule 2
at the support desk: an unmeasured value is absent, never best-case.

## Why keyword rules rather than a model, for now

The floor has to be auditable and deterministic. A regulator, or the owner,
must be able to read the list of things that always reach a person and check it
against what the code does. A model can be added *above* this layer to route
the remainder more cleverly; it must not be able to lower the floor, which is
why the floor is evaluated first and separately.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Final

logger = logging.getLogger(__name__)

__all__ = [
    "ALWAYS_HUMAN_RULES",
    "DEPARTMENT_ROUTES",
    "MIN_CONFIDENCE",
    "TriageResult",
    "check_floor",
    "triage",
]

#: Below this, the AI does not take the question even if nothing on the floor
#: matched. The floor is a floor, not a ceiling: uncertainty escalates too.
MIN_CONFIDENCE: Final = 0.55


@dataclass(frozen=True)
class _Rule:
    category: str
    reason: str
    pattern: re.Pattern[str]


def _rule(category: str, reason: str, *phrases: str) -> _Rule:
    joined = "|".join(phrases)
    return _Rule(category, reason, re.compile(joined, re.I))


#: Categories that ALWAYS reach a human. Order matters only for which reason is
#: reported; membership is what decides, and every one of these escalates.
ALWAYS_HUMAN_RULES: Final[tuple[_Rule, ...]] = (
    _rule(
        "security_incident",
        "A suspected security incident needs a person within minutes; an AI that "
        "answers it helpfully has delayed the response.",
        r"\bhacked?\b",
        r"\bstolen\b",
        r"\bunauthoris(?:ed|ed)\b",
        r"\bunauthorized\b",
        r"someone (?:else )?(?:has )?(?:logged|signed) in",
        r"\bcompromis(?:ed|e)\b",
        r"\bphish",
        r"api key was",
        r"\bbreach\b",
    ),
    _rule(
        "legal_or_complaint",
        "A complaint or legal notice is a person's job from the first message; an "
        "AI reply on the record can become the platform's position.",
        r"\blegal action\b",
        r"\blawyer\b",
        r"\bsolicitor\b",
        r"\bsue\b",
        r"\bsuing\b",
        r"\bregulator\b",
        r"\bombudsman\b",
        r"\bcomplain(?:t|ing|ts)?\b",
        r"\breporting you\b",
        r"\bfraud\b",
        r"money is missing",
        r"\bscam\b",
    ),
    _rule(
        "financial_advice",
        "This platform is not licensed to give financial advice. Recommending a "
        "trade is a regulatory exposure, not a quality problem.",
        r"should i (?:buy|sell|short|long|invest|hold)",
        r"what should i (?:buy|invest|trade)",
        r"\bis .{0,30}going (?:up|down)\b",
        r"will .{0,30}(?:rise|fall|crash|moon)",
        r"\bgive me a (?:tip|signal|recommendation)\b",
        r"what.{0,10}(?:do you|would you) recommend",
        r"\bbest (?:coin|stock|pair|asset) to\b",
    ),
    _rule(
        "account_or_money",
        "Anything that moves money or changes an account is a human action here; "
        "the AI has no path to it and must not imply that it does.",
        r"\bwithdraw",
        r"\bdeposit\b",
        r"\brefund\b",
        r"\bchargeback\b",
        r"close my (?:account|position)",
        r"delete my account",
        r"\bpayout\b",
        r"transfer (?:my|the) (?:balance|funds|money)",
        r"cancel my subscription",
        r"place (?:an?|the) (?:order|trade) for me",
        r"\bclose (?:my|the) (?:trade|position)\b",
    ),
)

#: Category -> the department that owns it. Every value must exist in
#: `ai.departments.DEPARTMENTS`; a test asserts it.
DEPARTMENT_ROUTES: Final[dict[str, str]] = {
    "backtesting_or_strategy": "research_intelligence",
    "orders_or_execution": "markets_execution",
    "risk_or_limits": "risk_compliance",
    "market_data": "data_ops",
    "platform_or_performance": "system_ops",
    "news_or_sentiment": "news_intelligence",
    "notifications": "notification_ops",
    "account_settings": "platform_engineering",
}

_CATEGORY_RULES: Final[tuple[_Rule, ...]] = (
    _rule(
        "orders_or_execution",
        "",
        r"\border\b",
        r"\bfill\b",
        r"\brejected\b",
        r"\bbroker\b",
        r"\bslippage\b",
        r"\bexecution\b",
        r"\bspread\b",
        r"\bpartial(?:ly)? filled\b",
    ),
    _rule(
        "risk_or_limits",
        "",
        r"\bdrawdown\b",
        r"\brisk limit",
        r"\bmargin\b",
        r"\bexposure\b",
        r"\bposition siz",
        r"\bkill switch\b",
        r"\bprop firm\b",
        r"\blot size\b",
    ),
    _rule(
        "market_data",
        "",
        r"\bprice feed\b",
        r"\bfeed\b",
        r"\btick\b",
        r"\bquote\b",
        r"\bfrozen\b",
        r"\bstale\b",
        r"\bdata (?:is|looks|seems)\b",
        r"\bcandle",
    ),
    _rule(
        "backtesting_or_strategy",
        "",
        r"\bbacktest",
        r"\bstrateg",
        r"\btimeframe",
        r"\bwalk[- ]forward\b",
        r"\bindicator\b",
        r"\boptimis|optimiz",
        r"\bsharpe\b",
        r"\bsortino\b",
    ),
    _rule(
        "news_or_sentiment",
        "",
        r"\bnews\b",
        r"\bsentiment\b",
        r"\bheadline",
        r"\bgeopolitic",
        r"\beconomic calendar\b",
    ),
    _rule(
        "notifications",
        "",
        r"\bnotification",
        r"\balert",
        r"\bemail me\b",
        r"\bquiet hours\b",
        r"\bpush\b",
    ),
    _rule(
        "platform_or_performance",
        "",
        r"\bslow\b",
        r"\bloading\b",
        r"\bcrash",
        r"\berror (?:page|message)\b",
        r"\bdashboard\b",
        r"\btimed? out\b",
        r"\bdowntime\b",
        r"\bbug\b",
    ),
    _rule(
        "account_settings",
        "",
        r"\btwo[- ]factor\b",
        r"\b2fa\b",
        r"\bpassword\b",
        r"\bemail address\b",
        r"\blog ?in\b",
        r"\bsettings?\b",
        r"\bprofile\b",
        r"\btrade journal\b",
        r"\bhow do i\b",
        r"\bwhere (?:do|can) i (?:find|see)\b",
        r"\bwhat does .{0,40}mean\b",
    ),
)


@dataclass(frozen=True)
class TriageResult:
    """Who should answer, and whether a person must.

    There is no field that can turn `needs_human` off after the fact, and an
    escalated result carries `suggested_reply=None` so no UI can send a draft
    for a ticket that was meant for a person.
    """

    category: str | None
    department: str | None
    needs_human: bool
    escalation_reason: str | None
    confidence: float
    matched_on: str | None
    suggested_reply: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "department": self.department,
            "needs_human": self.needs_human,
            "escalation_reason": self.escalation_reason,
            "confidence": self.confidence,
            "matched_on": self.matched_on,
            "suggested_reply": self.suggested_reply,
        }


def _first_match(text: str, rules: tuple[_Rule, ...]) -> tuple[_Rule, str] | None:
    for rule in rules:
        m = rule.pattern.search(text)
        if m:
            return rule, m.group(0)
    return None


def check_floor(question: str, *, confidence: float = 1.0) -> TriageResult | None:
    """The floor alone: an escalation, or `None` if nothing on it matched.

    Separate from `triage` because **a follow-up message in an open thread must
    be checked against the floor and nothing else.**

    Routing is already decided for a thread. Re-running the whole of `triage` on
    a second turn asks it to categorise *"that did not work"* or *"ok thanks"* in
    isolation — those match no category, hit the unroutable branch, and escalate.
    That was measured, not reasoned about: a reopen test failed with
    `awaiting_operator` where it expected `open`, which means every conversation
    would have escalated on its second turn and the operator queue would have
    filled with people saying "thanks".

    The unroutable-is-a-human rule exists to stop *routing a guess*. On a
    follow-up there is nothing to route, so it has no work to do. The floor is
    the safety property, and it applies to every message forever.
    """
    text = (question or "").strip()
    if not text:
        return None

    hit = _first_match(text, ALWAYS_HUMAN_RULES)
    if hit is None:
        return None

    rule, matched = hit
    logger.info("support triage: escalating (%s) on %r", rule.category, matched)
    return TriageResult(
        category=rule.category,
        department=None,
        needs_human=True,
        escalation_reason=rule.reason,
        confidence=confidence,
        matched_on=matched,
        suggested_reply=None,
    )


def triage(question: str, *, confidence: float = 1.0) -> TriageResult:
    """Decide who handles `question`, and whether a human must.

    `confidence` is the caller's confidence in its own understanding of the
    question — from a classifier, or 1.0 when there is no classifier. It can
    only ever *raise* the chance of escalation: the floor is evaluated first and
    a high confidence cannot clear it.
    """
    text = (question or "").strip()
    if not text:
        return TriageResult(
            category=None,
            department=None,
            needs_human=True,
            escalation_reason="An empty message cannot be routed; a person should look.",
            confidence=confidence,
            matched_on=None,
        )

    # ── The floor. Evaluated first, and it returns. ──────────────────────────
    floored = check_floor(text, confidence=confidence)
    if floored is not None:
        return floored

    # ── Routing to a specialist ─────────────────────────────────────────────
    routed = _first_match(text, _CATEGORY_RULES)
    if routed is None:
        # Unknown is not "probably research". A guess here sends a customer to a
        # specialist who cannot help and buries the ticket.
        return TriageResult(
            category=None,
            department=None,
            needs_human=True,
            escalation_reason="Nothing matched a known category — routing this would be a guess.",
            confidence=confidence,
            matched_on=None,
        )

    rule, matched = routed
    department = DEPARTMENT_ROUTES.get(rule.category)
    if department is None:
        # A category with no department is a configuration error, not a reason
        # to improvise.
        logger.error("support triage: category %r has no department route", rule.category)
        return TriageResult(
            category=rule.category,
            department=None,
            needs_human=True,
            escalation_reason=f"Category {rule.category!r} has no department configured.",
            confidence=confidence,
            matched_on=matched,
        )

    if confidence < MIN_CONFIDENCE:
        return TriageResult(
            category=rule.category,
            department=department,
            needs_human=True,
            escalation_reason=(
                f"Understanding of the question is low ({confidence:.2f} < {MIN_CONFIDENCE}); a person should read it."
            ),
            confidence=confidence,
            matched_on=matched,
        )

    return TriageResult(
        category=rule.category,
        department=department,
        needs_human=False,
        escalation_reason=None,
        confidence=confidence,
        matched_on=matched,
    )
