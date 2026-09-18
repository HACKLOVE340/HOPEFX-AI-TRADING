# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""What a support answer is allowed to know.

`support.answering` composes a FACTS block and tells the model to state no
figure that is not in it. Nothing filled that block: every reply came from the
department brief alone, so the strictest half of the design was carrying the
whole thing. This is the gatherer, and its entire design is a refusal list.

## READ_ONLY is not the same as "safe to put in a prompt"

The obvious implementation is "call every implemented READ_ONLY action that
needs no arguments". Measured against the real registry, that calls:

    platform_engineering.scan_secrets      -> secret-scanner findings
    platform_engineering.walk_code         -> source
    platform_engineering.run_tests         -> the test suite, per support ticket
    research_intelligence.run_backtest     -> a backtest, per support ticket
    markets_execution.shadow_place_order   -> a simulated order

The first two are the serious ones. Their output would be pasted into a prompt
sent to a **third-party model**, so a rule that looks like a safety tier would
have been a credential-disclosure path.

**The risk tier describes what an action does to the platform. It says nothing
about what its output is, and the output is what travels.** That distinction is
why this is an allowlist and not a filter over `ToolRisk.READ_ONLY`.

## Rule 2 at the fact boundary

A handler that raises, returns something unrenderable, or answers with more
text than anyone will read contributes `None` — never a plausible substitute.
`answering._render_facts` prints `None` as `not measured`, so the model is told
the gap exists rather than left to fill it. Same rule `ai/departments/` already
follows by returning `available: False` instead of a number it did not get.

## Arguments are never invented

Only `operator` is passed, and only because it is this caller's real identity —
the same `support_desk` string `answering` already spends its budget under.
Actions needing a `key`, a size or a symbol are not called at all: making one up
to fill a fact block is fabricating the input to a measurement.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Final

logger = logging.getLogger(__name__)

__all__ = ["SUPPORT_FACTS", "FACT_OPERATOR", "gather_facts"]

#: The identity this desk measures under. Real, not invented: `answering` spends
#: its model budget under the same name.
FACT_OPERATOR: Final = "support_desk"

#: Per department, the facts a customer answer may use.
#:
#: An allowlist rather than a risk-tier filter — see the module docstring. Every
#: entry is asserted by test to exist, be implemented, be READ_ONLY and need no
#: approval; the dangerous exclusions are asserted by name, so dropping one back
#: in is a deliberate act rather than a diff nobody reads.
SUPPORT_FACTS: Final[dict[str, tuple[str, ...]]] = {
    # "why was my order rejected" — connectivity is the answer more often than not.
    "markets_execution": ("query_broker_status",),
    # "what is my drawdown limit" — the live number, not the documented one.
    "risk_compliance": ("check_drawdown",),
    # "the price feed looks frozen" — this is the question, measured.
    "data_ops": ("feed_health", "stale_sources"),
    # "why is the dashboard slow" — what is actually degraded right now.
    "system_ops": ("service_health", "recent_failures"),
    # `news_intelligence` declares nothing. `score_geopolitical_risk` takes the
    # text to score, and this desk will not invent it — called bare it answers
    # `nothing to score: 'text' was empty` for every ticket forever. A fact that
    # can never be measured is noise in the prompt and a control that can never
    # fire; measured 2026-09-10 by running the gatherer against the real
    # registry, which is how it was found.
    "news_intelligence": (),
    "research_intelligence": ("score_regime",),
    # Deliberately empty. Platform Engineering answers "how do I enable 2FA",
    # where no measurement helps — and its implemented actions are precisely
    # the ones whose output must never reach a hosted model.
    "platform_engineering": (),
    # Deliberately empty: every action needs a `key` this desk would have to
    # invent, and notification questions are answered from the brief.
    "notification_ops": (),
}

#: Total wall-clock budget for one ticket's fact gathering. A customer is
#: waiting; a department that is slow contributes "not measured" rather than
#: holding the reply.
_BUDGET_S: Final = 4.0

#: Longest rendered fact. Prompt tokens are billed, and a 200 KB value is not a
#: fact anyone reads.
_MAX_RENDERED: Final = 2_000


def _call_action(department: str, action: str) -> Any:
    """Invoke one department handler. The single seam the tests patch."""
    import inspect

    from ai.departments import DEPARTMENTS

    dept = DEPARTMENTS[department]
    handler = next((a.handler for a in dept.actions if a.name == f"{department}.{action}"), None)
    if handler is None:
        raise LookupError(f"{department}.{action} has no handler")

    # Only `operator`, and only because it is this caller's real identity.
    params = inspect.signature(handler).parameters
    return handler(operator=FACT_OPERATOR) if "operator" in params else handler()


def _coerce(value: Any) -> str:
    """Stringify the few types that are genuinely values, and refuse the rest.

    NOT `default=str`. That was the first version, and it makes *everything*
    serialisable: a bare `object()` becomes `"<object object at 0x7f...>"`, so
    the unrenderable check passed and a memory address was going to be handed
    to a hosted model as a measurement. A test caught it.

    A timestamp and a `Decimal` are facts and are worth converting. An arbitrary
    object is not a fact, and pretending otherwise is exactly the substitution
    this module exists to prevent.
    """
    import datetime as _dt
    from decimal import Decimal

    if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"{type(value).__name__} is not a fact")


def _renderable(value: Any) -> Any | None:
    """The value if it can safely reach a prompt, else `None`.

    Two ways a value fails: it does not serialise (an object with no meaningful
    text is not a measurement), or it is too large to be one.
    """
    try:
        text = json.dumps(value, default=_coerce, sort_keys=True)
    except (TypeError, ValueError):
        return None
    if len(text) > _MAX_RENDERED:
        return None
    return value


def gather_facts(department: str | None, *, budget_s: float = _BUDGET_S) -> dict[str, Any]:
    """Measure what this department can contribute, or record that it could not.

    Never raises: a fact block is an improvement to an answer, not a
    precondition for one.
    """
    if not department:
        return {}
    allowed = SUPPORT_FACTS.get(department)
    if not allowed:
        return {}

    started = time.monotonic()
    facts: dict[str, Any] = {}
    for action in allowed:
        if time.monotonic() - started > budget_s:
            # Absent, and explicitly so. A key silently missing would let the
            # model assume the department had nothing to say.
            logger.error("support facts: budget of %.1fs spent before %s.%s", budget_s, department, action)
            facts[action] = None
            continue
        try:
            value = _call_action(department, action)
        except Exception as exc:
            # ERROR, not DEBUG: a gatherer that quietly returns nothing looks
            # exactly like a system with nothing to report (F248).
            logger.error("support facts: %s.%s failed: %s", department, action, exc)
            facts[action] = None
            continue
        rendered = _renderable(value)
        if rendered is None and value is not None:
            logger.error("support facts: %s.%s returned a value that cannot reach a prompt", department, action)
        facts[action] = rendered
    return facts
