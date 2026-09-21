# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Memory — §11's memory agent: retrieval and governance, read side only.

§16's tiers, knowledge graph and right to be forgotten landed in Phase 3.7.
What was staged is the agent: something `ai/agent/loop.py` can ask "what do we
know about this operator" without reaching into `ai/memory/` directly.

## It reads and it may not forget

`ai/memory/governance.py:forget` exists and this module does not call it. That
is the point of the department rather than an omission.

The right to be forgotten is the operator's. An agent holding it is a memory
hole with a permission tier: a model mid-loop deciding that some history is no
longer relevant, erasing it, and leaving the person whose history it was with no
way to know it happened. Deletion needs a human who meant it, which is what the
governance API's own callers provide.

`correct` is out for the same reason and one more: an agent that can edit a
memory can edit the memory of what it was told, and then the audit trail and
the thing being audited are the same writer.

`describe_retention` is how this department serves §16's right — it says what
is kept, for how long, and how to have it removed. Telling somebody how to
exercise a right is not exercising it for them.

## Recall is scoped to the operator who asked, keyed not filtered

The precedent is a P0 in `ai/jobs/runner.py`, where one operator's prompt and
the model's answer could reach another operator's screen: the scoping was
applied at the read, so anything that forgot to apply it leaked. `ai/memory/
tiers.py` keys by operator, so a call that forgets the argument finds nothing
rather than finding everybody — and this module never passes an operator it was
not given.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

#: How many entries one recall may return. A model prompt has a budget, and an
#: unbounded recall is how a long-lived operator's history becomes the whole
#: context window.
RECALL_LIMIT = 50


def _unavailable(reason: str) -> dict[str, Any]:
    return {"available": False, "reason": reason}


def recall_memory(*, operator: str, kind: str | None = None, **_: Any) -> dict[str, Any]:
    """One operator's memory, across the tiers, bounded."""
    if not operator or not operator.strip():
        # Not a default and not everybody's memory. An unscoped recall is the
        # P0 above with a longer reach.
        return _unavailable("a recall needs an operator; an unscoped one would read everybody's memory")

    try:
        from ai.memory import tiers
    except Exception as exc:  # pragma: no cover
        return _unavailable(f"the memory package could not be imported: {type(exc).__name__}")

    try:
        by_tier = tiers.recall_all(operator=operator)
    except Exception as exc:
        logger.warning("memory_ops: recall failed: %s", exc)
        return _unavailable(f"memory could not be read: {type(exc).__name__}")

    trimmed: dict[str, list[dict[str, Any]]] = {}
    dropped = 0
    for tier, entries in by_tier.items():
        selected = [e for e in entries if kind is None or e.get("kind") == kind]
        if len(selected) > RECALL_LIMIT:
            dropped += len(selected) - RECALL_LIMIT
            selected = selected[-RECALL_LIMIT:]
        trimmed[tier] = selected

    return {
        "available": True,
        "operator": operator,
        "tiers": trimmed,
        # Stated. A truncated recall that looked complete would have the model
        # reason from a history it believes is all of it.
        "dropped_by_limit": dropped,
        "limit_per_tier": RECALL_LIMIT,
    }


def memory_health(*, operator: str, **_: Any) -> dict[str, Any]:
    """How much is held, and whether it will survive a restart.

    Durability is reported rather than assumed: an in-process store answering
    the same questions as a durable one is the difference between a memory and
    a cache, and only one of them is what an operator thinks they have.
    """
    if not operator or not operator.strip():
        return _unavailable("memory health is per operator; an unscoped count is nobody's")

    out: dict[str, Any] = {"available": True, "operator": operator}

    try:
        from ai.memory import tiers

        out["per_tier"] = tiers.stats(operator=operator)
    except Exception as exc:
        out["per_tier"] = {}
        out["per_tier_reason"] = f"tier counts could not be read: {type(exc).__name__}"

    try:
        from ai.memory import store

        out["durable"] = bool(store.backend_is_durable())
        out["department_store"] = store.stats()
    except Exception as exc:
        # Not False. "We could not tell" and "it is not durable" are different
        # facts, and the second is the one an operator would act on.
        out["durable"] = None
        out["durable_reason"] = f"backend durability could not be read: {type(exc).__name__}"

    return out


def describe_retention(*, operator: str, **_: Any) -> dict[str, Any]:
    """What is kept, for how long, and how to have it forgotten.

    Read-only by construction: it names the route to erasure and does not take
    it. See the module docstring for why an agent must not hold that.
    """
    if not operator or not operator.strip():
        return _unavailable("retention is described per operator")

    tier_names: tuple[str, ...] = ()
    try:
        from ai.memory import tiers as tier_module

        tier_names = tuple(getattr(tier_module, "TIERS", ()) or ())
    except Exception as exc:  # pragma: no cover
        logger.debug("memory_ops: tier names unavailable: %s", exc)

    return {
        "available": True,
        "operator": operator,
        "tiers": tier_names,
        "right_to_be_forgotten": (
            "Everything held for this operator can be erased on request. This agent cannot do it: "
            "erasure is the operator's right and needs a human who meant it, so it runs through "
            "ai/memory/governance.py:forget from an authenticated request, never from a model's tool loop."
        ),
        "what_this_agent_can_do": ("recall_memory", "memory_health", "describe_retention"),
        "what_this_agent_cannot_do": ("forget", "correct", "approve a long-term memory"),
    }


__all__ = ["RECALL_LIMIT", "describe_retention", "memory_health", "recall_memory"]
