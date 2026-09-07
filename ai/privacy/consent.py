# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Whether the AI may watch, listen, or remember. One place, asked every time.

## Authorisation is not consent

`api/safe_agent_platform.py:vision_interpret` was described in the registry as
gated, and it was: `Depends(_admin)` plus a rate limit. That answers "may this
ROLE call this endpoint". It never asks whether the person in front of the
camera agreed to be looked at. Those are different questions, and the second one
had nowhere to live.

## Default denied, and the default is the whole design

A sensor with no consent record is refused, with a reason. The alternative —
permitted until somebody objects — means the first frame is taken before anyone
was asked, and there is no way to un-take it.

## Unreadable means refuse

Everywhere else in this codebase an unmeasured thing is REPORTED as absent
rather than guessed at; `ai/telemetry/reading.py` carries that argument at
length. Here the question is not "what is true" but "was I permitted", and a
system that cannot read its permissions and proceeds anyway does not have any.
The same inversion `ai/improve/cycle.py`'s kill switch makes.

## A session grant that outlives the session is not one

It is a permanent grant with a reassuring label, which is worse than an honest
permanent grant because the operator believes something false about it. Expiry
is checked on every read, never assumed from when the record was written.

## Revocation is recorded, not erased

"They never consented" and "they consented and withdrew it" are different facts.
An audit trail that cannot tell them apart is not an audit trail.

## Keyed by operator first

The precedent is a P0 in `ai/jobs/runner.py`, where scoping applied at the read
meant anything that forgot it leaked. Here forgetting it would mean one admin
turning on another admin's camera.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Final

logger = logging.getLogger(__name__)

#: What consent can be asked about. An unknown sensor is refused rather than
#: defaulted: a name nobody recognises must not become a permission nobody
#: reviewed.
SENSORS: Final[tuple[str, ...]] = ("camera", "microphone", "memory")

#: How consent may be scoped.
SCOPES: Final[tuple[str, ...]] = ("session", "until_revoked")

#: How long a session-scoped grant lasts. Deliberately short: the point of the
#: scope is that walking away ends it.
SESSION_SECONDS: Final[float] = 4 * 3600.0


@dataclass(frozen=True)
class Decision:
    """Whether a sensor may be used, and why not when it may not."""

    allowed: bool
    sensor: str
    #: Always populated on a refusal. A refusal an operator cannot act on is
    #: one they will route around.
    reason: str = ""


@dataclass
class _Record:
    granted: bool
    scope: str
    at: float
    revoked_at: float | None = None


class _MemoryStore:
    """The process-local default. Operator first, deliberately."""

    def __init__(self) -> None:
        self._by_operator: dict[str, dict[str, _Record]] = {}
        self._lock = threading.RLock()

    def read(self, operator: str, sensor: str) -> _Record | None:
        with self._lock:
            return self._by_operator.get(operator, {}).get(sensor)

    def write(self, operator: str, sensor: str, record: _Record) -> None:
        with self._lock:
            self._by_operator.setdefault(operator, {})[sensor] = record

    def sensors(self, operator: str) -> dict[str, _Record]:
        with self._lock:
            return dict(self._by_operator.get(operator, {}))


_STORE: Any = _MemoryStore()


def set_store(store: Any) -> None:
    """Replace the backing store. A durable one belongs here in deployment."""
    global _STORE
    _STORE = store


def reset_for_testing() -> None:
    global _STORE
    _STORE = _MemoryStore()


def _require_sensor(sensor: str) -> None:
    if sensor not in SENSORS:
        raise ValueError(f"unknown sensor {sensor!r}; expected one of {', '.join(SENSORS)}")


def grant(operator: str, sensor: str, *, scope: str = "session", now: float | None = None) -> Decision:
    """Record that `operator` permits `sensor`, for `scope`."""
    if not operator or not operator.strip():
        raise ValueError("consent belongs to an operator; an unscoped grant permits everybody")
    _require_sensor(sensor)
    if scope not in SCOPES:
        raise ValueError(f"unknown consent scope {scope!r}; expected one of {', '.join(SCOPES)}")

    moment = now if now is not None else time.time()
    _STORE.write(operator, sensor, _Record(granted=True, scope=scope, at=moment))
    logger.info("ai.privacy: %s granted %s (%s)", operator, sensor, scope)
    return Decision(allowed=True, sensor=sensor)


def revoke(operator: str, sensor: str, *, now: float | None = None) -> bool:
    """Withdraw consent. Returns whether there was any to withdraw.

    The record is kept and marked revoked rather than deleted: "never
    consented" and "consented and withdrew it" are different facts.
    """
    _require_sensor(sensor)
    existing = _STORE.read(operator, sensor)
    if existing is None or not existing.granted:
        return False
    moment = now if now is not None else time.time()
    _STORE.write(
        operator,
        sensor,
        _Record(granted=False, scope=existing.scope, at=existing.at, revoked_at=moment),
    )
    logger.info("ai.privacy: %s revoked %s", operator, sensor)
    return True


def revoke_all(operator: str, *, now: float | None = None) -> tuple[str, ...]:
    """Stop everything at once. Returns what was actually revoked."""
    return tuple(sorted(sensor for sensor in SENSORS if revoke(operator, sensor, now=now)))


def check(operator: str, sensor: str, *, now: float | None = None) -> Decision:
    """Whether `sensor` may be used for `operator` right now.

    Never raises. A caller that has to wrap this in a try block will eventually
    wrap it in one that swallows.
    """
    if sensor not in SENSORS:
        return Decision(allowed=False, sensor=sensor, reason=f"no consent: {sensor!r} is not a sensor this asks about")

    try:
        record = _STORE.read(operator, sensor)
    except Exception as exc:
        # Refuse, not report. A system that cannot read its permissions and
        # proceeds anyway does not have any.
        logger.error("ai.privacy: consent for %s could not be read: %s", sensor, exc)
        return Decision(
            allowed=False,
            sensor=sensor,
            reason=(
                f"consent for {sensor} could not be read ({type(exc).__name__}), "
                "and an unreadable permission is not a granted one"
            ),
        )

    if record is None:
        return Decision(allowed=False, sensor=sensor, reason=f"no consent has been given for {sensor}")
    if not record.granted:
        return Decision(allowed=False, sensor=sensor, reason=f"consent for {sensor} was withdrawn")

    if record.scope == "session":
        moment = now if now is not None else time.time()
        if moment - record.at > SESSION_SECONDS:
            return Decision(
                allowed=False,
                sensor=sensor,
                reason=f"consent for {sensor} was granted for this session only and has expired",
            )

    return Decision(allowed=True, sensor=sensor)


def snapshot(operator: str) -> dict[str, dict[str, Any]]:
    """Every sensor and its current state, for the operator's own review.

    Lists all of `SENSORS`, including ones never granted: a control panel that
    only shows what was turned on cannot be used to check that something is off.
    """
    try:
        records = _STORE.sensors(operator)
    except Exception as exc:
        logger.error("ai.privacy: snapshot for %s failed: %s", operator, exc)
        records = {}

    out: dict[str, dict[str, Any]] = {}
    for sensor in SENSORS:
        record = records.get(sensor)
        out[sensor] = {
            "granted": bool(record and record.granted),
            "scope": record.scope if record else "",
            "at": record.at if record else None,
            "revoked_at": record.revoked_at if record else None,
        }
    return out
