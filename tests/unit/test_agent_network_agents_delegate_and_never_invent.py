# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""§11: the rest of the agent network — news, voice, notification, data.

## The rule every department in this codebase already follows

**A handler delegates. It never computes a plausible-looking answer itself.**
Where the underlying call cannot be made — a missing dependency, an
unconfigured feed, a manager that was never constructed — the handler returns
`available: False` and the reason. It never returns a number it did not get.
That rule is why `ai/departments/research.py` exists in the shape it does, and
the four added here follow it or they are worse than nothing: an agent that
invents a freshness reading is an agent that reports a dead feed as healthy.

## Two rules specific to these four

**A dry run must not fire.** The notification agent can ask "what would happen
to this?" — and asking must not deliver anything, must not consume the
operator's rate budget, and must not mark a condition as already-seen. An agent
that tested a notification by sending it would be a spam generator with a
review process.

**The voice agent reports whether a key is configured, never the key.** The
providers behind `api/voice.py` are configured with secrets, and "is
ElevenLabs available" is answerable without any of them crossing into an agent
result that lands in memory and gets fenced back into a model.

## A registry correction

`agents.system` claimed to be live on `ai.departments.platform_engineering`,
whose four actions are `scan_secrets`, `run_tests`, `propose_fix` and
`check_broken_imports` — code, debugging and architecture. That is §11's
**Development** agent, described by a row that was still marked planned, while
the System agent's own remit (infrastructure, services, resources, failures)
had no agent at all. Two rows were pointing at one module; the tests below pin
the corrected mapping.

These fail on the pre-fix tree: the four departments do not exist there.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

NEW = ("news_intelligence", "voice_interface", "notification_ops", "data_ops")


# ── they exist, and they are agents rather than modules ───────────────────────


def test_the_four_agents_the_specification_names_are_departments():
    """§11 asks for an agent network. In this codebase an agent is a Department
    with actions on the bus — a loose module is not one, however good it is."""
    from ai.departments import DEPARTMENTS

    for key in NEW:
        assert key in DEPARTMENTS, f"{key} is not a department"


def test_every_new_action_is_read_only():
    """None of these four can act. A voice agent that could speak unprompted or
    a notification agent that could notify is a different risk tier and a
    different review."""
    from ai.departments import DEPARTMENTS
    from core.ai_tool_permissions import ToolRisk

    for key in NEW:
        for action in DEPARTMENTS[key].actions:
            assert action.risk is ToolRisk.READ_ONLY, f"{action.name} is {action.risk}"


def test_every_new_action_has_a_handler():
    """A declared action with no handler is refused by the bus rather than
    returning a successful no-op — which is right, but four agents of nothing
    but declarations would be four agents that cannot do anything."""
    from ai.departments import DEPARTMENTS

    for key in NEW:
        for action in DEPARTMENTS[key].actions:
            assert action.handler is not None, f"{action.name} has no handler"


def test_the_new_actions_reach_the_permission_registry_and_the_bus():
    """One table drives the directory, the permission registry and the bus.
    An action permitted and uncallable, or callable and unpermitted, is the
    defect that table exists to prevent."""
    from ai.departments import build_tool_bus, permission_registry

    registry = permission_registry()
    bus = build_tool_bus()
    from ai.departments import DEPARTMENTS

    for key in NEW:
        for action in DEPARTMENTS[key].actions:
            # `review` rather than a lookup: it asserts the tool is registered
            # AND that a read-only action is actually permitted without an
            # approval, which is the property that matters.
            verdict = registry.review(action.name)
            assert verdict.allowed, f"{action.name}: {verdict.reason_codes}"
            assert action.name in bus._tools, f"{action.name} is not registered on the bus"


# ── they delegate, and say so when they cannot ────────────────────────────────


def test_an_unavailable_feed_is_reported_not_invented():
    """The rule the whole file rests on. An agent that returns a freshness
    number it did not measure reports a dead feed as healthy."""
    from ai.departments import data_ops

    result = data_ops.feed_health(engine=_raising("no quality engine in this process"))
    assert result["available"] is False
    assert "no quality engine" in result["reason"]
    # And nothing that could be mistaken for a reading.
    for forbidden in ("sources", "stale", "latency_ms", "confidence"):
        assert forbidden not in result


def test_an_unavailable_news_manager_is_reported_not_invented():
    from ai.departments import news_intelligence

    result = news_intelligence.fetch_headlines(manager=_raising("news manager was never constructed"))
    assert result["available"] is False
    assert "headlines" not in result


def test_a_result_that_is_available_carries_what_it_measured():
    from ai.departments import data_ops

    class _Engine:
        @staticmethod
        def get_source_health():
            return {"oanda": {"stale": False, "confidence": 0.98}}

    result = data_ops.feed_health(engine=lambda: _Engine())
    assert result["available"] is True
    assert result["sources"]["oanda"]["confidence"] == 0.98


# ── the dry run must not fire ─────────────────────────────────────────────────


def test_evaluating_a_notification_delivers_nothing():
    """An agent that tested a notification by sending it would be a spam
    generator with a review process."""
    from ai.departments import notification_ops
    from ai.notify import service

    service.reset_for_testing()
    verdict = notification_ops.evaluate_notification(
        operator="owner", key="drawdown", severity="critical", title="t", body="b"
    )
    assert verdict["available"] is True
    assert verdict["action"] == "deliver"
    assert service.inbox_for("owner") == [], "the dry run delivered a notification"


def test_a_dry_run_does_not_spend_the_rate_budget():
    """Otherwise asking "would this get through?" ten times makes the eleventh
    real notification fail."""
    from ai.departments import notification_ops
    from ai.notify import Notification, Policy, Severity, service

    service.reset_for_testing()
    service.set_policy("owner", Policy(operator="owner", max_per_minute=2))
    for _ in range(10):
        notification_ops.evaluate_notification(operator="owner", key="k", severity="informational", title="t", body="b")
    real = service.submit(
        Notification(key="real", severity=Severity.INFORMATIONAL, title="t", body="b", operator="owner")
    )
    assert real.action == "deliver"


def test_a_dry_run_does_not_mark_a_condition_as_already_seen():
    """Deduplication is state. A dry run that wrote to it would silence the
    real notification it was asked about."""
    from ai.departments import notification_ops
    from ai.notify import Notification, Severity, service

    service.reset_for_testing()
    notification_ops.evaluate_notification(operator="owner", key="drawdown", severity="high", title="t", body="b")
    real = service.submit(Notification(key="drawdown", severity=Severity.HIGH, title="t", body="b", operator="owner"))
    assert real.action == "deliver", "the dry run deduplicated the real notification"


def test_the_notification_agent_reads_only_the_operator_it_was_asked_about():
    from ai.departments import notification_ops
    from ai.notify import Notification, Severity, service

    service.reset_for_testing()
    service.submit(Notification(key="k", severity=Severity.HIGH, title="t", body="b", operator="alice"))
    assert notification_ops.pending_notifications(operator="bob")["notifications"] == []


# ── the voice agent must not carry a secret ───────────────────────────────────


def test_the_voice_agent_reports_configuration_never_credentials():
    """ "Is ElevenLabs available" is answerable without a key crossing into an
    agent result that lands in memory and gets fenced back into a model."""
    from ai.departments import voice_interface

    result = voice_interface.voice_status(keys=lambda: {"elevenlabs": "sk-super-secret-value", "openai": ""})
    blob = repr(result)
    assert "sk-super-secret-value" not in blob
    assert result["providers"]["elevenlabs"] is True
    assert result["providers"]["openai"] is False


def test_the_voice_agent_describes_the_turn_rules_it_actually_enforces():
    """§11 asks for turn management. Reporting rules nothing implements would be
    a description of a different system."""
    from ai.departments import voice_interface

    rules = voice_interface.turn_policy()
    assert rules["available"] is True
    assert "barge" in repr(rules).lower()


# ── the registry correction ───────────────────────────────────────────────────


def test_the_development_agent_is_the_one_that_audits_code():
    """`platform_engineering` scans secrets, runs tests and checks imports.
    That is §11's Development agent — code, debugging, architecture."""
    from ai.hub.capabilities import REGISTRY

    development = next(c for c in REGISTRY if c.id == "agents.development")
    assert development.state == "live"
    assert "platform_engineering" in development.evidence


def test_the_system_agent_is_not_claimed_on_the_development_agents_evidence():
    """Two rows pointing at one module is how a section reports twelve agents
    and has eleven. The System agent's remit — infrastructure, services,
    resources, failures — is not what `platform_engineering` does."""
    from ai.hub.capabilities import REGISTRY

    system = next(c for c in REGISTRY if c.id == "agents.system")
    assert system.state != "live", "agents.system still claims to be built"
    assert "platform_engineering" not in system.evidence


def _raising(reason: str):
    """A dependency getter that fails the way an unconfigured one does."""

    def _get():
        raise RuntimeError(reason)

    return _get


# ── each new department actually notices something ────────────────────────────


def test_every_new_department_has_a_watcher():
    """A department that declares an awareness trigger and registers no watcher
    notices nothing. The existing suite already asserts this across the board —
    and it caught exactly this when the four were added, before they had any."""
    from ai.awareness.watchers import install_default_watchers, registered, reset_for_testing
    from ai.departments import DEPARTMENTS

    reset_for_testing()
    install_default_watchers()
    covered = {department for department, _ in registered()}
    try:
        for key in NEW:
            assert key in covered, f"{key} declares awareness {DEPARTMENTS[key].awareness} and watches nothing"
    finally:
        reset_for_testing()


def test_an_unavailable_check_raises_no_observation():
    """An unavailable check is not a finding. A watcher that raised one would
    have every process without a quality engine reporting a stale feed —
    "nobody looked" rendered as "something is wrong"."""
    from ai.awareness import watchers

    assert watchers._watch_feed_staleness() is None
    assert watchers._watch_news_feed_silence() is None


def test_the_new_watchers_survive_a_run_with_no_live_services():
    """CI has no feed, no news manager, no notification history. Nothing may
    throw — a watcher that raises takes the whole awareness pass with it."""
    from ai.awareness.watchers import install_default_watchers, reset_for_testing, run_all

    reset_for_testing()
    install_default_watchers()
    try:
        run_all()
    finally:
        reset_for_testing()


def test_the_escalation_watcher_does_not_enumerate_every_operator():
    """A watcher that listed everybody's unacknowledged alerts would be the
    cross-operator leak rebuilt as a background task."""
    import inspect

    from ai.awareness import watchers

    source = inspect.getsource(watchers._watch_unacknowledged_escalation)
    assert 'operator="owner"' in source
    for forbidden in ("_OPERATORS", "for operator in", ".keys()"):
        assert forbidden not in source


# ── the bus hands over the AUTHENTICATED operator, not a claimed one ──────────


def test_an_operator_scoped_action_is_callable_through_the_bus():
    """It was not. `evaluate_notification(operator=...)` collided with
    `ToolBus.invoke`'s own `operator` argument, so the action was permitted,
    registered and uncallable — the "callable and unpermitted, or permitted and
    uncallable" defect the department table exists to prevent. Direct-handler
    tests could not see it; only going through the bus could."""
    from ai.departments import build_tool_bus

    bus = build_tool_bus()
    result = bus.invoke(
        "notification_ops.evaluate_notification",
        operator="owner",
        allowed_actions={"notification_ops.evaluate_notification"},
        key="drawdown",
        severity="critical",
    )
    assert result.value["available"] is True
    assert result.value["dry_run"] is True


def test_an_agent_cannot_ask_about_another_operators_notifications():
    """The operator reaches the handler from the bus's authenticated argument,
    never from tool parameters — so there is no way to name somebody else."""
    from ai.departments import build_tool_bus
    from ai.notify import Notification, Severity, service

    service.reset_for_testing()
    service.submit(Notification(key="k", severity=Severity.HIGH, title="t", body="b", operator="alice"))

    bus = build_tool_bus()
    as_bob = bus.invoke(
        "notification_ops.pending_notifications",
        operator="bob",
        allowed_actions={"notification_ops.pending_notifications"},
    )
    assert as_bob.value["notifications"] == []

    as_alice = bus.invoke(
        "notification_ops.pending_notifications",
        operator="alice",
        allowed_actions={"notification_ops.pending_notifications"},
    )
    assert len(as_alice.value["notifications"]) == 1
    service.reset_for_testing()


def test_only_handlers_that_asked_for_the_operator_receive_it():
    """Passing it to everything would break the eight `recall_memory` handlers,
    which declare an explicit keyword-only signature with no `**kwargs`."""
    from ai.departments import build_tool_bus

    bus = build_tool_bus()
    wants = {name for name, registered in bus._tools.items() if registered.wants_operator}
    assert "notification_ops.pending_notifications" in wants
    assert not any(name.endswith(".recall_memory") for name in wants)

    # And the ones that did not ask still work.
    result = bus.invoke(
        "research_intelligence.recall_memory",
        operator="owner",
        allowed_actions={"research_intelligence.recall_memory"},
    )
    assert result.allowed is True
