# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""§19: when the AI is allowed to interrupt you, and when it is not.

Every mechanism this section asks for is a way to **silence an alert**. Quiet
hours silence. Sleep mode silences. Deduplication silences. Anti-spam rate
limiting silences. Built without a floor, a notification policy is the most
direct route to weakening the kill switch this platform has — and it would do it
quietly, because a suppressed alert is indistinguishable from a condition that
never fired.

## The floor

**A critical notification is never suppressed and never deferred.** Not by quiet
hours, not by sleep mode, not by a hundred duplicates, not by a rate limit, and
not by any combination of them.

This is enforced structurally rather than by a check somewhere in the middle of
the decision: `decide()` and `Router.route()` both return on `CRITICAL` before
any suppression path is reachable, and `Policy` carries no field that could turn
that off. A test enumerates the settings and asserts the floor holds across all
of them, so a future setting that could hold a critical fails the moment it is
added.

## Deferred is not suppressed

Quiet hours hold a notification and say when it will arrive. An operator waking
at seven has to be able to find what happened at three, or quiet hours are a way
of losing information rather than of scheduling it.

## Every decision explains itself

§19 asks the AI to explain why an interruption occurred, and the same obligation
applies to a non-interruption. "Suppressed" is not an explanation; "you have
already been told about this within the last hour" is. An alert with no stated
reason teaches an operator to distrust all of them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

#: Ordered least to most severe. This is `AlertSeverity` in
#: `frontend/src/hub/presence.ts`, deliberately identical: two definitions of
#: "worth interrupting for" is one too many, and the frontend's is the one an
#: operator actually sees.
_ORDER = ("informational", "important", "high", "critical")

#: Hours of a day, for validating a quiet-hours window.
LAST_HOUR = 23


class Severity(str, Enum):
    INFORMATIONAL = "informational"
    IMPORTANT = "important"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return _ORDER.index(self.value)

    @property
    def interrupts(self) -> bool:
        """Whether this outranks a conversation in progress.

        The same line `presence.ts` draws with its INTERRUPTING set.
        """
        return self.rank >= Severity.HIGH.rank

    def escalated(self) -> Severity:
        """One step up, and no further than the top.

        One step, not straight to critical: escalation must not be a route by
        which an informational notice becomes an alarm that wakes somebody at
        three in the morning.
        """
        return Severity(_ORDER[min(self.rank + 1, len(_ORDER) - 1)])


@dataclass(frozen=True)
class Notification:
    """Something the platform wants to tell one operator."""

    key: str
    severity: Severity
    title: str
    body: str
    operator: str
    source: str = ""

    def __post_init__(self) -> None:
        if not self.key.strip():
            raise ValueError("a notification needs a key so it can be deduplicated")
        if not self.title.strip():
            raise ValueError("a notification needs a title a human can read")
        if not self.operator.strip():
            raise ValueError("a notification needs an operator; there is no broadcast channel here")


@dataclass(frozen=True)
class QuietHours:
    """A window in which non-critical notifications wait.

    `start_hour` and `end_hour` are in the operator's local time;
    `tz_offset_hours` says how that relates to UTC. Storing the offset rather
    than assuming UTC matters because 22:00-07:00 means the operator's night,
    and an operator seven hours from UTC would otherwise be woken at their
    dinner and left alone at three in the morning.
    """

    start_hour: int
    end_hour: int
    tz_offset_hours: float = 0.0

    def __post_init__(self) -> None:
        for name, value in (("start_hour", self.start_hour), ("end_hour", self.end_hour)):
            if not 0 <= value <= LAST_HOUR:
                raise ValueError(f"{name} must be an hour of the day, got {value}")

    def covers(self, when: datetime) -> bool:
        """Whether `when` falls inside the window.

        Handles a window crossing midnight, which is the normal case and the one
        a naive `start <= hour < end` gets wrong in both directions: it reports
        23:00 as outside a 22:00-07:00 night, and 12:00 as inside it.
        """
        hour = self._local(when).hour
        if self.start_hour == self.end_hour:
            return False
        if self.start_hour < self.end_hour:
            return self.start_hour <= hour < self.end_hour
        return hour >= self.start_hour or hour < self.end_hour

    def next_end(self, when: datetime) -> datetime:
        """When the window the operator is currently inside will end."""
        local = self._local(when)
        end = local.replace(hour=self.end_hour, minute=0, second=0, microsecond=0)
        if end <= local:
            end += timedelta(days=1)
        return end - timedelta(hours=self.tz_offset_hours)

    def _local(self, when: datetime) -> datetime:
        moment = when if when.tzinfo else when.replace(tzinfo=UTC)
        return moment.astimezone(UTC) + timedelta(hours=self.tz_offset_hours)


@dataclass(frozen=True)
class Watch:
    """A condition one operator asked to be told about.

    Also serves as a wake condition (§19): the same shape answers "tell me when
    this happens" and "wake me if this happens", and having two would let them
    disagree about what "drawdown above 4%" means.
    """

    operator: str
    subject: str
    comparison: str
    threshold: float
    severity: str

    COMPARISONS = ("gte", "gt", "lte", "lt", "eq", "ne")

    def __post_init__(self) -> None:
        if self.comparison not in self.COMPARISONS:
            raise ValueError(f"comparison {self.comparison!r} is not one of {self.COMPARISONS}")
        # Constructing the Severity validates it, and a watch at a severity that
        # does not exist would fire into nothing.
        Severity(self.severity)
        if not self.subject.strip():
            raise ValueError("a watch needs a subject")
        if not self.operator.strip():
            raise ValueError("a watch belongs to one operator")

    def matches(self, value: float | None) -> bool:
        """Whether the threshold is crossed.

        `None` is "nobody measured it", never zero. A watch on drawdown firing
        because the feed died would be an alarm about the wrong thing, and the
        operator would go looking for a loss that did not happen.
        """
        if value is None:
            return False
        return {
            "gte": value >= self.threshold,
            "gt": value > self.threshold,
            "lte": value <= self.threshold,
            "lt": value < self.threshold,
            "eq": value == self.threshold,
            "ne": value != self.threshold,
        }[self.comparison]

    def evaluate(self, value: float | None) -> Notification | None:
        """The notification this watch would raise, or None."""
        if not self.matches(value):
            return None
        return Notification(
            key=self.subject,
            severity=Severity(self.severity),
            title=f"{self.subject} {self.comparison} {self.threshold}",
            # The number, not just the fact of a crossing. "Threshold crossed"
            # without it is a notification the operator has to go and check,
            # which is the work it was supposed to save them.
            body=f"{self.subject} is {value}, against your threshold of {self.threshold} ({self.comparison}).",
            operator=self.operator,
            source="watch",
        )


@dataclass
class Alarm:
    """A time the operator asked to be told about (§19 alarm scheduling)."""

    operator: str
    at: datetime
    title: str
    severity: str = "important"
    fired: bool = False

    def __post_init__(self) -> None:
        Severity(self.severity)
        if self.at.tzinfo is None:
            raise ValueError("an alarm's time must be timezone-aware")

    def due(self, now: datetime) -> bool:
        return not self.fired and now >= self.at

    def mark_fired(self) -> None:
        self.fired = True

    def as_notification(self) -> Notification:
        return Notification(
            key=f"alarm:{self.title}",
            severity=Severity(self.severity),
            title=self.title,
            body=f"Alarm set for {self.at.isoformat()}.",
            operator=self.operator,
            source="alarm",
        )


#: How long the same condition stays deduplicated. An hour, because a condition
#: that is still true an hour later is worth mentioning again — and suppression
#: that never expires is permanent blindness, the failure `ai/awareness/
#: watchers.py` already guards against with its open-condition map.
DEDUP_WINDOW_S = 3600.0


@dataclass(frozen=True)
class Policy:
    """One operator's notification settings.

    Carries no field that can hold a critical. That is the point: a
    `suppress_critical` flag would make every floor test conditional on a
    default, and defaults change.
    """

    operator: str
    quiet_hours: QuietHours | None = None
    sleeping: bool = False
    #: Non-interrupting notices allowed through per minute. 0 means none.
    max_per_minute: int = 20
    #: Seconds after which an unacknowledged interrupting notice escalates one
    #: step. None disables escalation.
    escalate_after_s: float | None = None
    dedup_window_s: float = DEDUP_WINDOW_S
    #: Conditions that pierce sleep mode and quiet hours (§19).
    wake_conditions: tuple[Watch, ...] = ()


@dataclass(frozen=True)
class Decision:
    """What happens to one notification, and why."""

    action: str  # deliver | defer | suppress | escalate
    reason: str
    severity: Severity
    key: str
    deliver_at: datetime | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "reason": self.reason,
            "severity": self.severity.value,
            "key": self.key,
            "deliver_at": self.deliver_at.isoformat() if self.deliver_at else None,
        }


#: The one sentence that must be true of every critical, in every configuration.
CRITICAL_FLOOR_REASON = (
    "This is critical. Quiet hours, sleep mode, deduplication and rate limits do "
    "not apply to a critical notification, by design — a suppressed alert is "
    "indistinguishable from a condition that never fired."
)


def decide(
    notification: Notification,
    *,
    policy: Policy,
    now: datetime | None = None,
    wake_value: float | None = None,
) -> Decision:
    """The stateless half: the floor, wake conditions, sleep, and quiet hours.

    Deduplication, rate limiting and escalation need history and live in
    `Router`. Keeping the two apart means every rule here is testable by calling
    a function, and the floor is the first branch in both.
    """
    moment = now or datetime.now(UTC)

    # ── the floor ────────────────────────────────────────────────────────────
    # First, before anything that could hold it. Nothing below this line is
    # reachable for a critical.
    if notification.severity is Severity.CRITICAL:
        return Decision(
            action="deliver",
            reason=CRITICAL_FLOOR_REASON,
            severity=notification.severity,
            key=notification.key,
        )

    # A wake condition the operator set themselves, matching this subject.
    for watch in policy.wake_conditions:
        if watch.subject == notification.key and watch.matches(wake_value):
            return Decision(
                action="deliver",
                reason=(
                    f"You asked to be woken when {watch.subject} is {watch.comparison} "
                    f"{watch.threshold}; it is {wake_value}."
                ),
                severity=notification.severity,
                key=notification.key,
            )

    if policy.sleeping:
        # No deliver_at: sleep mode has no scheduled end, and inventing one
        # would promise a delivery time nobody set.
        return Decision(
            action="defer",
            reason=(
                "Sleep mode is on, so this is being held until you end it. Only a critical "
                "notification, or a wake condition you set yourself, gets through."
            ),
            severity=notification.severity,
            key=notification.key,
        )

    if policy.quiet_hours and policy.quiet_hours.covers(moment):
        end = policy.quiet_hours.next_end(moment)
        return Decision(
            action="defer",
            reason=(
                f"It is inside your quiet hours ({policy.quiet_hours.start_hour:02d}:00-"
                f"{policy.quiet_hours.end_hour:02d}:00), so this is held until {end.isoformat()}. "
                "It is not discarded."
            ),
            severity=notification.severity,
            key=notification.key,
            deliver_at=end,
        )

    return Decision(
        action="deliver",
        reason=(
            f"Nothing is holding this back: it is outside your quiet hours, sleep mode is off, "
            f"and this is the first {notification.key!r} notice in the current window."
        ),
        severity=notification.severity,
        key=notification.key,
    )


__all__ = [
    "CRITICAL_FLOOR_REASON",
    "DEDUP_WINDOW_S",
    "Alarm",
    "Decision",
    "Notification",
    "Policy",
    "QuietHours",
    "Severity",
    "Watch",
    "decide",
]
