# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Notification — §11's notification agent: severity, escalation, interruption.

The policy itself is `ai/notify/` (§19). This is the agent that can be *asked*
about it: what would happen to this, what is waiting, what are the settings.

## A dry run must not fire

`evaluate_notification` answers "what would the policy do with this?" and the
answer must cost nothing. An agent that tested a notification by sending it
would be a spam generator with a review process — and worse, three subtler
failures that all look like success:

* it would **deliver**, waking somebody for a question nobody asked;
* it would **spend the rate budget**, so asking ten times makes the eleventh
  real notification fail;
* it would **write the deduplication record**, silencing the real notification
  it was asked about.

So it calls `decide()` — the stateless half — and never `Router.route` or
`service.submit`, which are the two that keep state. That is a structural
guarantee rather than a promise: nothing reachable from here can write.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _unavailable(reason: str) -> dict[str, Any]:
    return {"available": False, "reason": reason}


def evaluate_notification(
    *,
    operator: str,
    key: str,
    severity: str = "important",
    title: str = "",
    body: str = "",
    **_: Any,
) -> dict[str, Any]:
    """What the policy WOULD do. Nothing is delivered, spent or recorded."""
    try:
        from ai.notify import Notification, Severity, decide
        from ai.notify import service

        # `decide`, never `submit` or `route`. The two that keep state are not
        # reachable from this function, so a dry run cannot become a real one by
        # a later edit that forgets which is which.
        verdict = decide(
            Notification(
                key=key,
                severity=Severity(severity),
                title=title or key,
                body=body,
                operator=operator,
                source="agent-dry-run",
            ),
            policy=service.policy_for(operator),
        )
    except Exception as exc:
        logger.info("ai.departments.notification: could not evaluate: %s", exc)
        return _unavailable(str(exc))

    return {
        "available": True,
        "dry_run": True,
        **verdict.as_dict(),
    }


def pending_notifications(*, operator: str, **_: Any) -> dict[str, Any]:
    """What this operator has been told, and what is being held for them.

    Scoped to the operator named by the caller and nothing wider. There is no
    listing here that spans operators, for the same reason the endpoint has
    none: one operator's alerts are not another's context.
    """
    try:
        from ai.notify import service

        return {
            "available": True,
            "notifications": service.inbox_for(operator),
            "deferred": service.deferred_for(operator),
            "unacknowledged": service.outstanding(operator),
        }
    except Exception as exc:
        logger.info("ai.departments.notification: inbox unreadable: %s", exc)
        return _unavailable(str(exc))


def describe_policy(*, operator: str, **_: Any) -> dict[str, Any]:
    """This operator's settings, and the floor no setting can turn off."""
    try:
        from ai.notify import CRITICAL_FLOOR_REASON
        from ai.notify import service

        policy = service.policy_for(operator)
        return {
            "available": True,
            "sleeping": policy.sleeping,
            "quiet_hours": (
                None
                if policy.quiet_hours is None
                else {"start_hour": policy.quiet_hours.start_hour, "end_hour": policy.quiet_hours.end_hour}
            ),
            "max_per_minute": policy.max_per_minute,
            "escalate_after_s": policy.escalate_after_s,
            # Reported alongside the settings, because an agent reasoning about
            # what will reach somebody has to know what cannot be held back.
            "critical_floor": CRITICAL_FLOOR_REASON,
        }
    except Exception as exc:
        logger.info("ai.departments.notification: policy unreadable: %s", exc)
        return _unavailable(str(exc))


__all__ = ["describe_policy", "evaluate_notification", "pending_notifications"]
