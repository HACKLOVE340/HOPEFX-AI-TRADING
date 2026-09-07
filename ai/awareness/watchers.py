# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""What each department watches for on its own. Spec §2's `awareness/`.

The last of the four parts still typed `tuple[str, ...]` — "broker disconnect
detection", "live exposure vs rules", "strategy drift vs trained regime". Until
this, every department was purely reactive: it could answer a question an
operator asked and could not tell anyone that something had changed.

**An observation raises a PROPOSAL and never acts.** Spec §2 is explicit: every
department can recommend, and nothing places a trade, deploys code, rotates a
credential or changes a setting without passing the superadmin approval queue.
A watcher that could act would be the most dangerous thing in this codebase — it
would act on its own opinion with no human in the loop, on a schedule, at 3am.

That is enforced structurally rather than by convention: **this module does not
import the tool bus**, and `Observation` has no field that could express an
action. There is nothing to review for compliance because there is no way to
express the unsafe thing. `tests/unit/test_department_awareness.py` asserts both
properties so a later edit cannot quietly add the capability back.

**Watchers observe through the read actions that already exist.** A watcher does
not reach into the broker or the risk manager directly; it calls the same
read-only handlers the bus exposes. One source of truth, and a watcher can never
see more than an operator can.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

SEVERITIES = ("info", "warning", "critical")


@dataclass(frozen=True)
class Observation:
    """Something a department noticed. Deliberately inert.

    There is no `action`, `tool`, `execute`, `order` or `command` field, and
    there will not be one: an observation is a statement about the world, and
    the only thing that happens to it is that a human is asked about it.
    """

    department: str
    trigger: str
    severity: str
    summary: str
    detail: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f"severity {self.severity!r} is not one of {SEVERITIES}")
        if not self.summary.strip():
            raise ValueError("an observation needs a summary a human can read")

    def key(self) -> tuple[str, str]:
        """What makes two observations "the same open condition"."""
        return (self.department, self.trigger)


#: department -> {name: check}. A check returns an Observation or None.
_WATCHERS: dict[str, dict[str, Callable[[], Observation | None]]] = {}

#: Conditions currently raised, and at what severity. A watcher on a 60-second
#: loop would otherwise raise 1,440 proposals a day for one unchanged fact.
#: Cleared when the condition stops firing, so suppression never becomes
#: permanent blindness — and an escalation (warning -> critical) is new
#: information, so it raises again rather than being swallowed as a duplicate.
_OPEN: dict[tuple[str, str], str] = {}

#: Where a raised proposal goes. Set at startup; None means observations are
#: recorded in memory and nothing is queued, which is correct for a dev box.
_PROPOSAL_SINK: Callable[[dict[str, Any]], Any] | None = None


def set_proposal_sink(sink: Callable[[dict[str, Any]], Any] | None) -> None:
    global _PROPOSAL_SINK
    _PROPOSAL_SINK = sink


def register(department: str, name: str, check: Callable[[], Observation | None]) -> None:
    """Add a watcher. Replacing one by name is intentional and idempotent."""
    from ai.departments import DEPARTMENTS

    if department not in DEPARTMENTS:
        raise ValueError(f"unknown department {department!r}")
    _WATCHERS.setdefault(department, {})[name] = check


def registered() -> list[tuple[str, str]]:
    return [(department, name) for department, checks in _WATCHERS.items() for name in checks]


def run_all() -> list[Observation]:
    """Run every watcher once. Returns what fired this pass.

    A watcher that throws is logged at ERROR and skipped — one broken watcher
    must not blind the whole platform, and a watcher that has silently stopped
    watching is exactly the dead control this repository keeps finding.
    """
    fired: list[Observation] = []
    seen_this_pass: set[tuple[str, str]] = set()

    for department, checks in list(_WATCHERS.items()):
        for name, check in list(checks.items()):
            try:
                observation = check()
            except Exception:
                logger.exception(
                    "ai.awareness: watcher %s/%s failed — this department is not watching for it right now",
                    department,
                    name,
                )
                continue
            if observation is None:
                continue
            fired.append(observation)
            seen_this_pass.add(observation.key())
            _handle(observation)

    # Anything that was open and did not fire has cleared. Forgetting it here is
    # what lets the same condition raise again if it comes back.
    for key in [k for k in _OPEN if k not in seen_this_pass]:
        _OPEN.pop(key, None)

    return fired


def _handle(observation: Observation) -> None:
    """Record it, and raise a proposal if this is news."""
    _remember(observation)

    previous = _OPEN.get(observation.key())
    if previous == observation.severity:
        return  # same condition, same severity, already queued
    _OPEN[observation.key()] = observation.severity
    _raise_proposal(observation, escalated=previous is not None)
    _notify(observation)


def _notify(observation: Observation) -> None:
    """Ask §19's policy whether to INTERRUPT somebody about this.

    A third channel, deliberately narrower than the two above it. `_remember`
    records what the department saw; `_raise_proposal` records what a human was
    asked about; this decides only whether to interrupt them now.

    It runs AFTER the proposal is queued and cannot affect it. That ordering is
    the safety property: a notification policy that could suppress a proposal
    would be one that can delete the audit record of a condition, whereas
    suppressing an interruption only means the operator reads it in the queue
    instead of being woken by it. Remove this function and every proposal is
    still queued exactly as before.

    Failure here is logged and swallowed for the same reason: a policy that
    cannot decide must not stop a condition being recorded.
    """
    try:
        from ai.notify.service import handle_observation

        handle_observation(observation)
    except Exception:
        logger.exception(
            "ai.awareness: notification policy failed for %s; the proposal was queued regardless",
            observation.trigger,
        )


def _remember(observation: Observation) -> None:
    """Every observation goes to memory, even a suppressed repeat.

    Memory is the record of what the department saw; the proposal queue is the
    record of what a human was asked about. Conflating them would either flood
    the queue or lose the history.
    """
    try:
        from ai.memory.store import remember

        remember(observation.department, "observation", asdict(observation))
    except Exception:
        logger.exception("ai.awareness: could not record observation %s", observation.trigger)


def _raise_proposal(observation: Observation, *, escalated: bool) -> None:
    """Ask a human. This is the only thing an observation ever causes."""
    if _PROPOSAL_SINK is None:
        logger.info(
            "ai.awareness: %s/%s fired (%s) with no proposal sink installed; recorded in memory only",
            observation.department,
            observation.trigger,
            observation.severity,
        )
        return

    title = f"[{observation.severity}] {observation.department}: {observation.trigger}"
    proposal = {
        "id": f"observation-{observation.department}-{observation.trigger}-{datetime.now(UTC).timestamp():.0f}",
        "title": f"{title} (escalated)" if escalated else title,
        # Its own kind, so an operator can tell a machine-noticed condition from
        # a change somebody proposed. It is also NOT "repair" or "upgrade", so
        # it never inherits the two-approver quorum meant for changes that act.
        "kind": "observation",
        "scope": observation.department,
        "reason": observation.summary,
        "changes": "None. This is an observation; no change has been prepared.",
        "evidence_ids": [],
        "rollback_plan": "Not applicable — nothing was changed.",
        "status": "pending",
        # Attributed to the department, never to a person. An operator reading
        # the queue has to be able to see that no human proposed this.
        "created_by": f"awareness:{observation.department}",
        "created_at": datetime.now(UTC).isoformat(),
        "detail": observation.detail,
        "severity": observation.severity,
    }
    try:
        _PROPOSAL_SINK(proposal)
    except Exception:
        logger.exception("ai.awareness: could not queue a proposal for %s", observation.trigger)


# ── the default watchers ──────────────────────────────────────────────────────
# Each observes through a read-only department handler rather than reaching into
# the broker or the risk manager directly, so a watcher can never see more than
# an operator can and there is one source of truth per fact.


def _watch_broker_connection() -> Observation | None:
    """Spec §4: broker disconnect detection."""
    from ai.departments import markets_execution

    status = markets_execution.query_broker_status()
    if status.get("available"):
        return None
    return Observation(
        department="markets_execution",
        trigger="broker_unavailable",
        severity="critical",
        summary="The broker connection is not available. Orders cannot be placed or reconciled.",
        detail={"reason": status.get("reason", "unknown")},
    )


def _watch_drawdown() -> Observation | None:
    """Spec §4: live exposure vs rules."""
    from ai.departments import risk_compliance

    status = risk_compliance.check_drawdown()
    if not status.get("available"):
        return None
    if status.get("passed", True):
        return None
    return Observation(
        department="risk_compliance",
        trigger="drawdown_limit_breached",
        severity="critical",
        summary=f"Drawdown check is failing: {status.get('reason') or 'limit breached'}.",
        detail={k: v for k, v in status.items() if k != "available"},
    )


def _watch_regime_shift() -> Observation | None:
    """Spec §4: strategy drift vs trained regime."""
    from ai.departments import research

    regime = research.score_regime()
    if not regime.get("available"):
        return None
    name = str(regime.get("regime", "")).lower()
    if "high_vol" not in name and "crisis" not in name:
        return None
    return Observation(
        department="research_intelligence",
        trigger="volatility_regime_shift",
        severity="warning",
        summary=f"Market regime is {regime.get('regime')}; the production model was trained on a different one.",
        detail=dict(regime),
    )


def _watch_broken_imports() -> Observation | None:
    """Spec §4: commits touching security-sensitive files / CI failure patterns.

    Broken imports are the measurable half of that: `gate_broken_imports`
    already knows what is deliberately broken, and anything beyond its baseline
    is a real regression.
    """
    from ai.departments import platform_engineering

    result = platform_engineering.check_broken_imports()
    if not result.get("available"):
        return None
    broken = result.get("broken") or []
    if not broken:
        return None
    return Observation(
        department="platform_engineering",
        trigger="broken_imports_detected",
        severity="warning",
        summary=f"{len(broken)} import(s) do not resolve.",
        # Bounded: an observation is a summary for a human, not a full report.
        # The department's own action returns everything on request.
        detail={"count": len(broken), "sample": broken[:5]},
    )


def _watch_feed_staleness() -> Observation | None:
    """Spec §11 data agent: a source the quality engine has marked stale.

    Stale is not the same as absent. When the engine cannot be reached at all
    this returns None — an unavailable check is not a finding, and raising one
    would mean every process without a quality engine reports a stale feed.
    """
    from ai.departments import data_ops

    result = data_ops.stale_sources()
    if not result.get("available"):
        return None
    stale = result.get("stale") or []
    if not stale:
        return None
    return Observation(
        department="data_ops",
        trigger="feed_stale",
        severity="critical",
        summary=(
            f"{', '.join(stale)} {'is' if len(stale) == 1 else 'are'} stale. Prices from a stale "
            "source are the wrong prices, and everything downstream assumes freshness was checked."
        ),
        detail={"stale": stale, "checked": result.get("checked", [])},
    )


def _watch_voice_providers() -> Observation | None:
    """Spec §11 voice agent: no synthesis provider configured.

    `info`, not a warning. Web Speech in the browser is a real fallback, so this
    is a note about identity — the AI sounds like a different person on every
    machine — rather than a fault.
    """
    from ai.departments import voice_interface

    status = voice_interface.voice_status()
    if not status.get("available"):
        return None
    providers = status.get("providers") or {}
    if any(providers.values()):
        return None
    return Observation(
        department="voice_interface",
        trigger="no_voice_provider",
        severity="info",
        summary=(
            "No speech provider is configured, so synthesis falls back to whatever voice the "
            "operating system provides — the AI has no consistent voice of its own."
        ),
        detail={"providers": providers},
    )


def _watch_unacknowledged_escalation() -> Observation | None:
    """Spec §11 notification agent: an interrupting notice nobody acknowledged.

    Deliberately scoped to `owner`. There is no listing here that spans
    operators, for the same reason the notification endpoints have none: one
    operator's unacknowledged alert is not another's business, and a watcher
    that enumerated everybody would be the cross-operator leak rebuilt as a
    background task.
    """
    from ai.departments import notification_ops

    pending = notification_ops.pending_notifications(operator="owner")
    if not pending.get("available"):
        return None
    outstanding = pending.get("unacknowledged") or []
    if not outstanding:
        return None
    return Observation(
        department="notification_ops",
        trigger="escalation_unacknowledged",
        severity="warning",
        summary=(
            f"{len(outstanding)} notification(s) delivered and not acknowledged. Unacknowledged is "
            "not the same as unseen, but it is the only signal there is."
        ),
        detail={"keys": outstanding[:10]},
    )


def _watch_news_feed_silence() -> Observation | None:
    """Spec §11 news agent: the headline feed has produced nothing.

    A quiet feed and a dead feed look identical from downstream, which is the
    reason to say something. Only raised when the manager is reachable and
    returns nothing — an unreachable manager is `available: False` and produces
    no observation, because nobody measured silence.
    """
    from ai.departments import news_intelligence

    result = news_intelligence.fetch_headlines(limit=1)
    if not result.get("available"):
        return None
    if result.get("headlines"):
        return None
    return Observation(
        department="news_intelligence",
        trigger="news_feed_silent",
        severity="info",
        summary=(
            "The headline feed is reachable and has returned nothing. A quiet feed and a stopped "
            "feed look the same from downstream, so this is worth noticing rather than assuming."
        ),
        detail={},
    )


#: Above this a host reading counts as pressure. Chosen to sit above
#: `frameBudget.ts`'s CPU_HIGH of 85 so the plane degrades its own rendering
#: first and only escalates to a proposal when that was not enough — two alarms
#: at the same threshold is one alarm and one duplicate.
_HOST_PRESSURE_PERCENT = 90.0


def _watch_host_pressure() -> Observation | None:
    """Spec §11 system agent: the machine is running out of something.

    §22's rule decides the None cases here, and it decides them twice. A probe
    that could not run returns None — an unavailable check is not a finding,
    and treating an unmeasured CPU as a busy one would raise a resource alarm
    on every deployment without psutil. A probe that ran and read low also
    returns None, which is the ordinary case.

    So the only thing that fires is a reading that exists and is high.
    """
    from ai.departments import system_ops

    result = system_ops.host_resources(operator="owner")
    if not result.get("available"):
        return None

    pressured: dict[str, float] = {}
    for name, reading in (result.get("readings") or {}).items():
        if not isinstance(reading, dict) or not reading.get("measured"):
            continue
        value = reading.get("value")
        if isinstance(value, (int, float)) and value >= _HOST_PRESSURE_PERCENT:
            pressured[name] = float(value)
    if not pressured:
        return None

    worst = max(pressured, key=lambda k: pressured[k])
    return Observation(
        department="system_ops",
        trigger="resource_pressure",
        severity="warning",
        summary=(
            f"{worst} is at {pressured[worst]:.0f}%. A machine this close to its limit drops frames "
            "and times out model calls, and both look like the platform being slow rather than full."
        ),
        detail={"readings": pressured},
    )


def _watch_camera_consent_withdrawn() -> Observation | None:
    """Spec §11 vision agent: vision is configured and consent is not held.

    `info`, not a warning, and deliberately so. Consent withheld is the
    CORRECT state, not a fault — the point of noticing it is that a model
    asked to look at something will be refused, and the refusal should not
    read to an operator as the feature being broken.
    """
    from ai.departments import vision_ops

    status = vision_ops.vision_status(operator="owner")
    if not status.get("available"):
        return None
    if not status.get("vendor_configured"):
        # Nothing to consent to. Reporting withheld consent for a capability
        # that cannot run would be an alarm about a hypothetical.
        return None
    if status.get("camera_consent"):
        return None
    return Observation(
        department="vision_ops",
        trigger="camera_consent_withdrawn",
        severity="info",
        summary=(
            "Vision is configured and camera consent is not held, so any request to look at "
            "something will be refused. That is the gate working, not a fault."
        ),
        detail={"consent_reason": status.get("consent_reason", "")},
    )


def _watch_memory_not_durable() -> Observation | None:
    """Spec §11 memory agent: memory will not survive a restart.

    `durable` is tri-state on purpose. None means the backend could not be
    read, and that is not the same as "not durable" — one is a question and the
    other is an answer. Only a measured False fires.
    """
    from ai.departments import memory_ops

    health = memory_ops.memory_health(operator="owner")
    if not health.get("available"):
        return None
    durable = health.get("durable")
    if durable is None or durable:
        return None
    return Observation(
        department="memory_ops",
        trigger="memory_not_durable",
        severity="warning",
        summary=(
            "Department memory is in-process only, so everything it holds is lost on restart. "
            "An operator who has been told the AI remembers them has been told something that "
            "stops being true at the next deploy."
        ),
        detail={"department_store": health.get("department_store", {})},
    )


def install_default_watchers() -> None:
    """Register one watcher per department, for the triggers spec §4 names."""
    register("markets_execution", "broker_connection", _watch_broker_connection)
    register("risk_compliance", "drawdown", _watch_drawdown)
    register("research_intelligence", "regime_shift", _watch_regime_shift)
    register("platform_engineering", "broken_imports", _watch_broken_imports)
    # Cluster B (§11). Each department declares an awareness trigger, and a
    # department that declares one without registering a watcher notices
    # nothing — `test_every_department_has_at_least_one_watcher` is what
    # catches that, and it caught exactly this when the four were added.
    register("data_ops", "feed_stale", _watch_feed_staleness)
    register("voice_interface", "no_voice_provider", _watch_voice_providers)
    register("notification_ops", "escalation_unacknowledged", _watch_unacknowledged_escalation)
    register("news_intelligence", "news_feed_silent", _watch_news_feed_silence)
    # Cluster C (§11). Same rule: a declared awareness trigger with no watcher
    # behind it is a department that notices nothing, and the test above is
    # what catches it — it caught exactly this when these three were added.
    register("system_ops", "resource_pressure", _watch_host_pressure)
    register("vision_ops", "camera_consent_withdrawn", _watch_camera_consent_withdrawn)
    register("memory_ops", "memory_not_durable", _watch_memory_not_durable)


def reset_for_testing() -> None:
    _WATCHERS.clear()
    _OPEN.clear()
    set_proposal_sink(None)


__all__ = [
    "SEVERITIES",
    "Observation",
    "install_default_watchers",
    "register",
    "registered",
    "reset_for_testing",
    "run_all",
    "set_proposal_sink",
]
