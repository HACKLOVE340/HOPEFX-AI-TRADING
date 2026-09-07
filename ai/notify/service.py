# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The process-wide notification service: settings, inbox, and the watcher bridge.

`policy.py` and `router.py` decide. This is where a decision reaches somebody.

## The proposal queue is not touched

`ai/awareness/watchers.py` already separates two things: `_remember` records
what a department saw, and `_raise_proposal` records what a human was asked
about. This adds a third, narrower channel — whether to *interrupt* — and
deliberately changes neither of the first two.

That separation is the safety property. A notification policy that could
suppress a proposal would be a policy that can delete the audit record of a
condition; suppressing an interruption only means the operator reads it in the
queue instead of being woken by it. If this module were removed entirely,
every proposal would still be queued exactly as before.

## Severity mapping is explicit, and only one thing maps to critical

The watchers speak `info | warning | critical`; §19 speaks four severities. A
mapping that quietly promoted `warning` to something interrupting would put an
alarm on regime shifts; one that demoted `critical` would silence a broker
disconnect. The table is written out so both mistakes are visible.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from ai.notify.policy import Alarm, Decision, Notification, Policy, Severity, Watch
from ai.notify.router import Router

logger = logging.getLogger(__name__)

#: Watcher severity -> notification severity. Only `critical` reaches critical.
OBSERVATION_SEVERITY: dict[str, Severity] = {
    "info": Severity.INFORMATIONAL,
    # Deliberately non-interrupting. A regime-shift warning is worth reading,
    # not worth waking somebody for, and `Severity.HIGH` would do the latter.
    "warning": Severity.IMPORTANT,
    "critical": Severity.CRITICAL,
}

#: How many delivered notifications an operator's inbox keeps. A session that
#: ran for a week would otherwise grow without limit.
MAX_INBOX = 200


@dataclass
class Delivered:
    notification: Notification
    decision: Decision
    at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.notification.key,
            "title": self.notification.title,
            "body": self.notification.body,
            "source": self.notification.source,
            "at": self.at,
            **self.decision.as_dict(),
        }


@dataclass
class _Operator:
    policy: Policy
    watches: list[Watch] = field(default_factory=list)
    alarms: list[Alarm] = field(default_factory=list)
    inbox: list[Delivered] = field(default_factory=list)
    deferred: list[Delivered] = field(default_factory=list)


_ROUTER = Router()
_OPERATORS: dict[str, _Operator] = {}


def _operator(name: str) -> _Operator:
    if name not in _OPERATORS:
        _OPERATORS[name] = _Operator(policy=Policy(operator=name))
    return _OPERATORS[name]


def policy_for(operator: str) -> Policy:
    return _operator(operator).policy


def set_policy(operator: str, policy: Policy) -> Policy:
    _operator(operator).policy = policy
    return policy


def add_watch(watch: Watch, *, wake: bool = False) -> Watch:
    """Register a watch, optionally as a wake condition.

    `wake` is a separate argument rather than a field on `Watch` because it is a
    statement about the operator's availability, not about the condition: the
    same threshold can be worth a notification during the day and worth being
    woken for at night, and the operator decides which.

    Without this parameter `Policy.wake_conditions` was settable only from
    Python — a §19 capability with no route to it, which is the same as not
    having it.
    """
    who = _operator(watch.operator)
    who.watches.append(watch)
    if wake:
        who.policy = replace(who.policy, wake_conditions=(*who.policy.wake_conditions, watch))
    return watch


def wake_conditions_for(operator: str) -> list[Watch]:
    return list(_operator(operator).policy.wake_conditions)


def watches_for(operator: str) -> list[Watch]:
    """Only this operator's. There is no listing that spans operators here."""
    return list(_operator(operator).watches)


def add_alarm(alarm: Alarm) -> Alarm:
    _operator(alarm.operator).alarms.append(alarm)
    return alarm


def alarms_for(operator: str) -> list[Alarm]:
    return list(_operator(operator).alarms)


def submit(notification: Notification, *, now: datetime | None = None, wake_value: float | None = None) -> Decision:
    """Put one notification through the policy and file the outcome.

    Deferred notifications are kept, not dropped: an operator waking at seven
    has to be able to find what happened at three, or quiet hours are a way of
    losing information rather than of scheduling it.
    """
    who = _operator(notification.operator)
    decision = _ROUTER.route(notification, policy=who.policy, now=now, wake_value=wake_value)
    record = Delivered(notification=notification, decision=decision)

    if decision.action in ("deliver", "escalate"):
        who.inbox.append(record)
        del who.inbox[:-MAX_INBOX]
    elif decision.action == "defer":
        who.deferred.append(record)
        del who.deferred[:-MAX_INBOX]

    return decision


def inbox_for(operator: str) -> list[dict[str, Any]]:
    return [d.as_dict() for d in _operator(operator).inbox]


def deferred_for(operator: str) -> list[dict[str, Any]]:
    return [d.as_dict() for d in _operator(operator).deferred]


def release_deferred(operator: str, *, now: datetime | None = None) -> list[dict[str, Any]]:
    """Move anything whose hold has expired into the inbox.

    Two kinds of hold, released differently:

    * A **quiet-hours** hold has a `deliver_at`, and is released when that time
      passes.
    * A **sleep-mode** hold has none, because sleep mode has no scheduled end.
      It is released when the operator ends sleep mode.

    The first version of this required a `deliver_at`, which stranded every
    sleep-mode hold permanently: the operator would turn sleep mode off and
    their held notifications would stay held forever. That is worse than not
    having sleep mode, because it loses information the policy promised to keep,
    and it would have looked like the notifications never arrived at all.
    """
    moment = now or datetime.now(UTC)
    who = _operator(operator)
    if who.policy.sleeping:
        # Nothing is released while sleep mode is on, whatever its deliver_at
        # says: the operator has said they are not available.
        return []

    still_held: list[Delivered] = []
    released: list[Delivered] = []
    for record in who.deferred:
        due = record.decision.deliver_at
        if due is None or moment >= due:
            released.append(record)
        else:
            still_held.append(record)
    who.deferred = still_held
    who.inbox.extend(released)
    del who.inbox[:-MAX_INBOX]
    return [r.as_dict() for r in released]


def acknowledge(key: str, *, operator: str) -> bool:
    return _ROUTER.acknowledge(key, operator=operator)


def outstanding(operator: str) -> list[str]:
    return _ROUTER.outstanding(operator=operator)


def check_watches(operator: str, readings: dict[str, float | None], *, now: datetime | None = None) -> list[Decision]:
    """Evaluate this operator's watches against a set of readings.

    A reading of `None` is "nobody measured it" and fires nothing — a watch on
    drawdown firing because the feed died would send the operator looking for a
    loss that did not happen.
    """
    out: list[Decision] = []
    for watch in _operator(operator).watches:
        fired = watch.evaluate(readings.get(watch.subject))
        if fired is not None:
            out.append(submit(fired, now=now, wake_value=readings.get(watch.subject)))
    return out


def due_alarms(operator: str, *, now: datetime | None = None) -> list[Decision]:
    moment = now or datetime.now(UTC)
    out: list[Decision] = []
    for alarm in _operator(operator).alarms:
        if alarm.due(moment):
            alarm.mark_fired()
            out.append(submit(alarm.as_notification(), now=moment))
    return out


def handle_observation(observation: Any, *, operator: str = "owner", now: datetime | None = None) -> Decision | None:
    """Bridge a watcher observation into the notification policy.

    Returns the decision, or None when the observation could not be mapped —
    which is logged rather than swallowed, because an unmapped severity means a
    condition nobody will be told about.
    """
    severity = OBSERVATION_SEVERITY.get(getattr(observation, "severity", ""))
    if severity is None:
        logger.warning(
            "ai.notify: observation %r has severity %r with no mapping; nobody will be notified",
            getattr(observation, "trigger", "?"),
            getattr(observation, "severity", "?"),
        )
        return None

    return submit(
        Notification(
            key=f"{observation.department}:{observation.trigger}",
            severity=severity,
            title=f"{observation.department}: {observation.trigger}",
            body=observation.summary,
            operator=operator,
            source="watcher",
        ),
        now=now,
    )


def reset_for_testing() -> None:
    _ROUTER.reset()
    _OPERATORS.clear()


__all__ = [
    "MAX_INBOX",
    "OBSERVATION_SEVERITY",
    "Delivered",
    "acknowledge",
    "add_alarm",
    "add_watch",
    "alarms_for",
    "check_watches",
    "deferred_for",
    "due_alarms",
    "handle_observation",
    "inbox_for",
    "outstanding",
    "policy_for",
    "release_deferred",
    "reset_for_testing",
    "set_policy",
    "submit",
    "wake_conditions_for",
    "watches_for",
]
