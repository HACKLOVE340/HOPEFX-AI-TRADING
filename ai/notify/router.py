# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The stateful half of §19: deduplication, rate limiting, and escalation.

`ai/notify/policy.py` decides everything that can be decided from the
notification and the settings alone. The three rules here need history — has
this been seen before, how many have gone out this minute, was the last one
acknowledged — so they live behind an object with the state in it.

## The floor is the first branch here too

`Router.route()` returns on `CRITICAL` before any of the three suppression paths
is reachable. It still *records* the critical, so escalation state stays
accurate, but nothing below the floor can hold it. Duplicating the check rather
than delegating it is deliberate: this is the one invariant in the module worth
stating twice, and a reader of `route()` must be able to see it without opening
another file.

## State is per operator

A flood from one operator must not silence another's alerts. This repository has
already shipped that defect once, in the AI job manager, where `snapshot()` and
`cancel()` were unscoped — so every dict here is keyed by operator first.

## Acknowledging is not the same as receiving

An escalation fires when an interrupting notice has gone unacknowledged for long
enough. Repeating it identically instead would train the operator to ignore it,
which is the failure mode a louder alarm exists to prevent.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from ai.notify.policy import CRITICAL_FLOOR_REASON, Decision, Notification, Policy, Severity, decide


@dataclass
class _Sent:
    severity: Severity
    at: datetime
    acknowledged: bool = False
    escalated: bool = False


class Router:
    """One process's notification history. Cheap, in memory, per operator."""

    def __init__(self) -> None:
        #: operator -> key -> what was last delivered for it.
        self._sent: dict[str, dict[str, _Sent]] = {}
        #: operator -> delivery timestamps, for the per-minute limit.
        self._recent: dict[str, deque[datetime]] = {}

    # ── the decision ─────────────────────────────────────────────────────────

    def route(
        self,
        notification: Notification,
        *,
        policy: Policy,
        now: datetime | None = None,
        wake_value: float | None = None,
    ) -> Decision:
        moment = now or datetime.now(UTC)
        operator = notification.operator
        history = self._sent.setdefault(operator, {})

        # ── the floor ────────────────────────────────────────────────────────
        # Recorded, so escalation state stays right, and returned immediately.
        # Nothing below this line can hold a critical.
        if notification.severity is Severity.CRITICAL:
            history[notification.key] = _Sent(severity=notification.severity, at=moment)
            self._record_delivery(operator, moment)
            return Decision(
                action="deliver",
                reason=CRITICAL_FLOOR_REASON,
                severity=notification.severity,
                key=notification.key,
            )

        previous = history.get(notification.key)

        # ── escalation, before deduplication ─────────────────────────────────
        # Checked first because a repeat of an unacknowledged interrupting
        # notice is exactly the case deduplication would swallow, and it is the
        # case that matters most.
        if (
            previous is not None
            and not previous.acknowledged
            and policy.escalate_after_s is not None
            and (moment - previous.at).total_seconds() >= policy.escalate_after_s
        ):
            raised = previous.severity.escalated()
            history[notification.key] = _Sent(severity=raised, at=moment, escalated=True)
            self._record_delivery(operator, moment)
            waited = int((moment - previous.at).total_seconds() // 60)
            return Decision(
                action="escalate",
                reason=(
                    f"You were told about {notification.key!r} {waited} minutes ago and have not "
                    f"acknowledged it, so it has been raised from {previous.severity.value} to "
                    f"{raised.value}. Repeating it unchanged would just teach you to ignore it."
                ),
                severity=raised,
                key=notification.key,
            )

        # ── deduplication ────────────────────────────────────────────────────
        # A severity INCREASE is news; the same or milder is not. Swallowing an
        # escalating condition as a duplicate is how a problem that is getting
        # worse goes unreported.
        if (
            previous is not None
            and (moment - previous.at).total_seconds() < policy.dedup_window_s
            and notification.severity.rank <= previous.severity.rank
        ):
            minutes = int((moment - previous.at).total_seconds() // 60)
            return Decision(
                action="suppress",
                reason=(
                    f"You have already been told about {notification.key!r} "
                    f"{'just now' if minutes == 0 else f'{minutes} minutes ago'}, at "
                    f"{previous.severity.value}. It is unchanged, so this repeat is being held."
                ),
                severity=notification.severity,
                key=notification.key,
            )

        # ── the settings ─────────────────────────────────────────────────────
        decision = decide(notification, policy=policy, now=moment, wake_value=wake_value)
        if decision.action != "deliver":
            return decision

        # ── anti-spam ────────────────────────────────────────────────────────
        # Last, so a rate limit can never pre-empt the reasons above. Applies to
        # deliveries only: a suppressed or deferred notice did not use the
        # operator's attention and must not consume the budget for one that would.
        if not self._within_rate(operator, moment, policy.max_per_minute):
            return Decision(
                action="suppress",
                reason=(
                    f"You have already had {policy.max_per_minute} non-critical notifications in "
                    "the last minute, which is the rate limit you set. This one is being held so "
                    "the important ones stay visible."
                ),
                severity=notification.severity,
                key=notification.key,
            )

        history[notification.key] = _Sent(severity=notification.severity, at=moment)
        self._record_delivery(operator, moment)
        return decision

    # ── acknowledgement ──────────────────────────────────────────────────────

    def acknowledge(self, key: str, *, operator: str) -> bool:
        """Mark a notification seen. Returns whether there was one to mark.

        Also clears the deduplication record: having acknowledged a condition,
        an operator is asking to be told if it happens again. Leaving the record
        in place would silence the recurrence for the rest of the window.
        """
        sent = self._sent.get(operator, {}).pop(key, None)
        if sent is None:
            return False
        sent.acknowledged = True
        return True

    def outstanding(self, *, operator: str) -> list[str]:
        """Keys delivered to this operator and not yet acknowledged."""
        return [key for key, sent in self._sent.get(operator, {}).items() if not sent.acknowledged]

    def reset(self) -> None:
        self._sent.clear()
        self._recent.clear()

    # ── internals ────────────────────────────────────────────────────────────

    def _record_delivery(self, operator: str, moment: datetime) -> None:
        self._recent.setdefault(operator, deque()).append(moment)

    def _within_rate(self, operator: str, moment: datetime, limit: int) -> bool:
        window = self._recent.setdefault(operator, deque())
        cutoff = moment - timedelta(minutes=1)
        while window and window[0] < cutoff:
            window.popleft()
        return len(window) < limit


__all__ = ["Router"]
