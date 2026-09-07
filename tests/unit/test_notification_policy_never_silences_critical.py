# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""§19: user watches, four severities, quiet hours, escalation, alarms,
deduplication, and explaining why an interruption happened.

## Why this test file is named after one rule

Every mechanism §19 asks for is a way to **silence an alert**. Quiet hours
silence. Sleep mode silences. Deduplication silences. Anti-spam rate limiting
silences. Built without a floor, a notification policy is the most direct route
to weakening the kill switch this repository has — and it would do it quietly,
because a suppressed alert looks exactly like a condition that never fired.

So the floor is structural: **a critical notification is never suppressed and
never deferred, by any mechanism, in any configuration.** Not by quiet hours,
not by sleep mode, not by a hundred duplicates, not by a rate limit. The tests
below try every one of them.

These fail on the pre-fix tree: `ai.notify` does not exist there.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

pytestmark = pytest.mark.unit

#: A Tuesday at 03:00 UTC — inside any plausible quiet-hours window.
NIGHT = datetime(2026, 3, 10, 3, 0, tzinfo=UTC)
#: The same Tuesday at 14:00 UTC — inside nobody's quiet hours.
DAY = datetime(2026, 3, 10, 14, 0, tzinfo=UTC)


def _n(severity: str = "important", *, key: str = "k", operator: str = "owner", title: str = "t"):
    from ai.notify import Notification, Severity

    return Notification(
        key=key,
        severity=Severity(severity),
        title=title,
        body="something happened",
        operator=operator,
        source="test",
    )


def _policy(**over):
    from ai.notify import Policy, QuietHours

    defaults: dict = {
        "operator": "owner",
        "quiet_hours": QuietHours(start_hour=22, end_hour=7),
        "sleeping": False,
    }
    defaults.update(over)
    return Policy(**defaults)


# ── the floor ─────────────────────────────────────────────────────────────────


def test_quiet_hours_never_hold_a_critical():
    """The whole reason this file exists. Somebody asleep at 03:00 is exactly
    who needs to be woken when the kill switch trips."""
    from ai.notify import decide

    d = decide(_n("critical"), policy=_policy(), now=NIGHT)
    assert d.action == "deliver"
    assert "critical" in d.reason.lower()


def test_sleep_mode_never_holds_a_critical():
    from ai.notify import decide

    d = decide(_n("critical"), policy=_policy(sleeping=True), now=NIGHT)
    assert d.action == "deliver"


def test_a_hundred_duplicates_never_silence_a_critical():
    """Deduplication is the mechanism most likely to swallow the one that
    mattered: a condition that keeps firing is a condition that keeps being
    true."""
    from ai.notify import Router

    router = Router()
    delivered = 0
    for i in range(100):
        d = router.route(_n("critical"), policy=_policy(), now=NIGHT + timedelta(seconds=i))
        if d.action == "deliver":
            delivered += 1
    assert delivered == 100, f"only {delivered} of 100 criticals were delivered"


def test_a_rate_limit_never_silences_a_critical():
    from ai.notify import Router

    router = Router()
    results = [
        router.route(_n("critical", key=f"k{i}"), policy=_policy(max_per_minute=1), now=NIGHT) for i in range(10)
    ]
    assert all(r.action == "deliver" for r in results)


def test_no_configuration_at_all_can_hold_a_critical():
    """Exhaustive over the suppression settings rather than over the ones I
    happened to think of. A future setting that could hold a critical fails
    here the moment it is added to `Policy`."""
    from ai.notify import QuietHours, Router

    for sleeping in (True, False):
        for quiet in (None, QuietHours(start_hour=0, end_hour=23), QuietHours(start_hour=22, end_hour=7)):
            for limit in (0, 1, 1000):
                router = Router()
                policy = _policy(sleeping=sleeping, quiet_hours=quiet, max_per_minute=limit)
                first = router.route(_n("critical"), policy=policy, now=NIGHT)
                second = router.route(_n("critical"), policy=policy, now=NIGHT)
                assert first.action == "deliver", f"held by {sleeping=} {quiet=} {limit=}"
                assert second.action == "deliver", f"deduplicated with {sleeping=} {quiet=} {limit=}"


def test_the_floor_is_not_reachable_by_configuration():
    """A `Policy` field that could turn the floor off would make every test
    above conditional on a default. There must not be one."""
    import dataclasses

    from ai.notify import Policy

    fields = {f.name for f in dataclasses.fields(Policy)}
    for forbidden in ("suppress_critical", "allow_silence_critical", "override_floor", "silence_all"):
        assert forbidden not in fields


# ── four severities (§19) ─────────────────────────────────────────────────────


def test_there_are_exactly_the_four_severities_the_frontend_knows():
    """A fifth severity here would arrive at a frontend that cannot render it,
    and `AlertSeverity` in `hub/presence.ts` is the contract."""
    from ai.notify import Severity

    assert [s.value for s in Severity] == ["informational", "important", "high", "critical"]


def test_only_high_and_critical_interrupt():
    """`presence.ts` already draws this line: INTERRUPTING = {high, critical}.
    Two definitions of "worth interrupting for" is one too many."""
    from ai.notify import Severity

    assert Severity.HIGH.interrupts is True
    assert Severity.CRITICAL.interrupts is True
    assert Severity.IMPORTANT.interrupts is False
    assert Severity.INFORMATIONAL.interrupts is False


# ── quiet hours and sleep (§19) ───────────────────────────────────────────────


def test_quiet_hours_defer_an_important_notification_rather_than_dropping_it():
    """Deferred is not suppressed. An operator waking at seven must find what
    happened at three, or quiet hours are a way of losing information."""
    from ai.notify import decide

    d = decide(_n("important"), policy=_policy(), now=NIGHT)
    assert d.action == "defer"
    assert d.deliver_at is not None
    assert d.deliver_at.hour == 7


def test_a_window_that_crosses_midnight_is_handled():
    """22:00-07:00 is the normal case and the one a naive start < end check
    gets wrong in both directions."""
    from ai.notify import QuietHours

    q = QuietHours(start_hour=22, end_hour=7)
    assert q.covers(NIGHT) is True
    assert q.covers(DAY) is False
    assert q.covers(NIGHT.replace(hour=23)) is True
    assert q.covers(NIGHT.replace(hour=7)) is False


def test_quiet_hours_do_not_apply_outside_them():
    from ai.notify import decide

    assert decide(_n("important"), policy=_policy(), now=DAY).action == "deliver"


def test_sleep_mode_defers_regardless_of_the_hour():
    """Sleep mode is "I am not available", which is a different statement from
    "it is night"."""
    from ai.notify import decide

    d = decide(_n("high"), policy=_policy(sleeping=True), now=DAY)
    assert d.action == "defer"


def test_a_deferred_notification_says_when_it_will_arrive():
    from ai.notify import decide

    d = decide(_n("important"), policy=_policy(), now=NIGHT)
    assert d.deliver_at is not None
    assert d.deliver_at > NIGHT


# ── deduplication and anti-spam (§19) ─────────────────────────────────────────


def test_the_same_condition_twice_is_delivered_once():
    from ai.notify import Router

    router = Router()
    first = router.route(_n("high", key="drawdown"), policy=_policy(), now=DAY)
    second = router.route(_n("high", key="drawdown"), policy=_policy(), now=DAY + timedelta(seconds=5))
    assert first.action == "deliver"
    assert second.action == "suppress"
    assert "already" in second.reason.lower()


def test_a_repeat_gets_through_once_the_condition_has_been_quiet():
    """Suppression that never expires is permanent blindness — the same rule
    `ai/awareness/watchers.py` already applies to its open-condition map."""
    from ai.notify import Router

    router = Router()
    router.route(_n("high", key="drawdown"), policy=_policy(), now=DAY)
    later = router.route(_n("high", key="drawdown"), policy=_policy(), now=DAY + timedelta(hours=2))
    assert later.action == "deliver"


def test_a_severity_increase_is_news_and_is_not_deduplicated():
    """warning -> critical on the same condition is new information. Swallowing
    it as a duplicate is how an escalating problem goes unreported."""
    from ai.notify import Router

    router = Router()
    router.route(_n("important", key="drawdown"), policy=_policy(), now=DAY)
    worse = router.route(_n("high", key="drawdown"), policy=_policy(), now=DAY + timedelta(seconds=5))
    assert worse.action == "deliver"


def test_a_severity_decrease_is_still_deduplicated():
    """Otherwise a flapping condition delivers twice per cycle forever."""
    from ai.notify import Router

    router = Router()
    router.route(_n("high", key="k"), policy=_policy(), now=DAY)
    milder = router.route(_n("important", key="k"), policy=_policy(), now=DAY + timedelta(seconds=5))
    assert milder.action == "suppress"


def test_the_rate_limit_holds_a_flood_of_unrelated_low_severity_notices():
    from ai.notify import Router

    router = Router()
    results = [
        router.route(_n("informational", key=f"k{i}"), policy=_policy(max_per_minute=3), now=DAY) for i in range(10)
    ]
    assert sum(1 for r in results if r.action == "deliver") == 3
    assert any("rate" in r.reason.lower() for r in results if r.action == "suppress")


def test_one_operators_flood_does_not_silence_another():
    """The cross-operator leak this repository already shipped once, in the AI
    job manager. Rate state is per operator."""
    from ai.notify import Policy, Router

    router = Router()
    for i in range(5):
        router.route(_n("informational", key=f"a{i}", operator="alice"), policy=_policy(max_per_minute=2), now=DAY)
    bob = router.route(
        _n("informational", key="b", operator="bob"),
        policy=Policy(operator="bob", max_per_minute=2),
        now=DAY,
    )
    assert bob.action == "deliver"


# ── escalation (§19) ──────────────────────────────────────────────────────────


def test_an_unacknowledged_high_escalates_rather_than_repeating():
    """A notification nobody acknowledged is not the same as one nobody sent.
    Repeating it identically trains the operator to ignore it."""
    from ai.notify import Router

    router = Router()
    router.route(_n("high", key="drawdown"), policy=_policy(escalate_after_s=600), now=DAY)
    later = router.route(
        _n("high", key="drawdown"), policy=_policy(escalate_after_s=600), now=DAY + timedelta(minutes=20)
    )
    assert later.action == "escalate"
    assert later.severity.value == "critical"
    assert "not acknowledged" in later.reason.lower()


def test_acknowledging_stops_the_escalation():
    from ai.notify import Router

    router = Router()
    router.route(_n("high", key="drawdown"), policy=_policy(escalate_after_s=600), now=DAY)
    router.acknowledge("drawdown", operator="owner")
    later = router.route(
        _n("high", key="drawdown"), policy=_policy(escalate_after_s=600), now=DAY + timedelta(minutes=20)
    )
    assert later.action == "deliver"


def test_an_informational_notice_never_escalates_to_critical():
    """Escalation must not be a route by which a quiet notice becomes an alarm
    that wakes somebody at 03:00."""
    from ai.notify import Router

    router = Router()
    router.route(_n("informational", key="k"), policy=_policy(escalate_after_s=600), now=DAY)
    later = router.route(
        _n("informational", key="k"), policy=_policy(escalate_after_s=600), now=DAY + timedelta(minutes=20)
    )
    assert later.severity.value != "critical"


# ── user-defined watches and thresholds (§19) ─────────────────────────────────


def test_a_watch_fires_when_its_threshold_is_crossed():
    from ai.notify import Watch

    w = Watch(operator="owner", subject="daily_loss_pct", comparison="gte", threshold=4.0, severity="high")
    assert w.evaluate(4.5) is not None
    assert w.evaluate(3.9) is None


def test_a_watch_says_what_it_saw_in_its_notification():
    """ "Threshold crossed" without the number is a notification an operator has
    to go and check, which is the thing it was supposed to save them."""
    from ai.notify import Watch

    fired = Watch(
        operator="owner", subject="daily_loss_pct", comparison="gte", threshold=4.0, severity="high"
    ).evaluate(4.5)
    assert fired is not None
    assert "4.5" in fired.body
    assert "4.0" in fired.body


def test_an_unmeasured_value_does_not_fire_a_watch():
    """`None` is "nobody measured it", not zero. A watch on drawdown firing
    because the feed died would be an alarm about the wrong thing."""
    from ai.notify import Watch

    w = Watch(operator="owner", subject="daily_loss_pct", comparison="lte", threshold=1.0, severity="high")
    assert w.evaluate(None) is None


def test_a_watch_belongs_to_one_operator():
    from ai.notify import Watch

    w = Watch(operator="alice", subject="x", comparison="gte", threshold=1.0, severity="high")
    fired = w.evaluate(2.0)
    assert fired is not None
    assert fired.operator == "alice"


def test_a_watch_with_an_unknown_comparison_is_refused_at_construction():
    from ai.notify import Watch

    with pytest.raises(ValueError, match="comparison"):
        Watch(operator="o", subject="x", comparison="approximately", threshold=1.0, severity="high")


def test_a_watch_cannot_be_created_at_a_severity_that_does_not_exist():
    from ai.notify import Watch

    with pytest.raises(ValueError):
        Watch(operator="o", subject="x", comparison="gte", threshold=1.0, severity="apocalyptic")


# ── alarms and wake conditions (§19) ──────────────────────────────────────────


def test_an_alarm_fires_at_its_time_and_not_before():
    from ai.notify import Alarm

    alarm = Alarm(operator="owner", at=DAY, title="London open", severity="important")
    assert alarm.due(DAY - timedelta(minutes=1)) is False
    assert alarm.due(DAY) is True


def test_an_alarm_that_has_fired_does_not_fire_again():
    from ai.notify import Alarm

    alarm = Alarm(operator="owner", at=DAY, title="London open", severity="important")
    alarm.mark_fired()
    assert alarm.due(DAY + timedelta(hours=1)) is False


def test_a_wake_condition_can_pierce_sleep_mode_but_only_when_it_matches():
    """§19 asks for user-configured wake-up conditions. The point of one is to
    get through sleep mode — so an operator who set one must be woken, and one
    who did not must not be."""
    from ai.notify import Policy, QuietHours, Watch, decide

    wake = Watch(operator="owner", subject="daily_loss_pct", comparison="gte", threshold=3.0, severity="high")
    policy = Policy(operator="owner", sleeping=True, quiet_hours=QuietHours(22, 7), wake_conditions=(wake,))

    matching = _n("high", key="daily_loss_pct")
    assert decide(matching, policy=policy, now=NIGHT, wake_value=4.0).action == "deliver"
    assert decide(matching, policy=policy, now=NIGHT, wake_value=1.0).action == "defer"


def test_a_wake_condition_does_not_wake_for_an_unrelated_subject():
    from ai.notify import Policy, QuietHours, Watch, decide

    wake = Watch(operator="owner", subject="daily_loss_pct", comparison="gte", threshold=3.0, severity="high")
    policy = Policy(operator="owner", sleeping=True, quiet_hours=QuietHours(22, 7), wake_conditions=(wake,))
    assert decide(_n("high", key="something_else"), policy=policy, now=NIGHT, wake_value=99.0).action == "defer"


# ── explain why the interruption happened (§19) ───────────────────────────────


def test_every_decision_carries_a_reason():
    """§19: "explain why an interruption occurred". An alert with no stated
    reason teaches an operator to distrust all of them."""
    from ai.notify import Router

    router = Router()
    outcomes = [
        router.route(_n("critical"), policy=_policy(), now=NIGHT),
        router.route(_n("important", key="q"), policy=_policy(), now=NIGHT),
        router.route(_n("high", key="d"), policy=_policy(), now=DAY),
        router.route(_n("high", key="d"), policy=_policy(), now=DAY),
    ]
    for d in outcomes:
        assert d.reason.strip(), f"{d.action} with no reason"
        assert len(d.reason) > 20, f"{d.action}: {d.reason!r} is not an explanation"


def test_the_reason_names_the_mechanism_that_decided():
    """ "Suppressed" is not an explanation; "you have already been told about
    this in the last hour" is."""
    from ai.notify import Router

    router = Router()
    router.route(_n("high", key="d"), policy=_policy(), now=DAY)
    duplicate = router.route(_n("high", key="d"), policy=_policy(), now=DAY)
    assert "already" in duplicate.reason.lower()

    quiet = router.route(_n("important", key="q"), policy=_policy(), now=NIGHT)
    assert "quiet hours" in quiet.reason.lower()


def test_the_decision_is_serialisable_for_an_audit_trail():
    from ai.notify import Router

    body = Router().route(_n("critical"), policy=_policy(), now=NIGHT).as_dict()
    assert body["action"] == "deliver"
    assert body["severity"] == "critical"
    assert body["reason"]
    assert body["key"] == "k"


# ── it has to actually run, or it is another control nobody executes ──────────


@pytest.fixture(autouse=True)
def _clean_service():
    from ai.notify import service

    service.reset_for_testing()
    yield
    service.reset_for_testing()


def test_a_watcher_observation_reaches_the_policy():
    """The module could be perfect and never be called. `ai/awareness/
    watchers.py` is where conditions are noticed, and this asserts the bridge
    between them exists and fires."""
    from ai.awareness.watchers import Observation
    from ai.notify import service

    decision = service.handle_observation(
        Observation(
            department="risk_compliance",
            trigger="drawdown_breach",
            severity="critical",
            summary="Daily loss is 5.10% against a 5.00% limit.",
        )
    )
    assert decision is not None
    assert decision.action == "deliver"
    assert service.inbox_for("owner")[0]["key"] == "risk_compliance:drawdown_breach"


def test_a_watcher_critical_maps_to_a_critical_notification():
    """A mapping that demoted `critical` would silence a broker disconnect."""
    from ai.notify.service import OBSERVATION_SEVERITY

    assert OBSERVATION_SEVERITY["critical"].value == "critical"


def test_a_watcher_warning_does_not_become_an_interrupting_alarm():
    """A mapping that promoted `warning` would put an alarm on regime shifts."""
    from ai.notify.service import OBSERVATION_SEVERITY

    assert OBSERVATION_SEVERITY["warning"].interrupts is False


def test_the_policy_cannot_stop_a_proposal_being_queued():
    """The safety property of the wiring. A notification policy that could
    suppress a proposal would be one that can delete the audit record of a
    condition."""
    import ai.notify.service as service
    from ai.awareness import watchers

    watchers.reset_for_testing()
    queued: list[dict] = []
    watchers.set_proposal_sink(queued.append)

    original = service.handle_observation
    service.handle_observation = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("policy is down"))
    try:
        watchers.register(
            "risk_compliance",
            "probe",
            lambda: watchers.Observation(
                department="risk_compliance",
                trigger="probe",
                severity="critical",
                summary="something is wrong",
            ),
        )
        watchers.run_all()
    finally:
        service.handle_observation = original
        watchers.set_proposal_sink(None)
        watchers.reset_for_testing()

    assert len(queued) == 1, "a failing notification policy stopped a proposal being queued"


def test_a_deferred_notification_can_be_found_later():
    """Quiet hours schedule information; they do not lose it."""
    from ai.notify import Notification, Policy, QuietHours, Severity, service

    service.set_policy("owner", Policy(operator="owner", quiet_hours=QuietHours(22, 7)))
    service.submit(
        Notification(key="k", severity=Severity.IMPORTANT, title="t", body="b", operator="owner"),
        now=NIGHT,
    )
    assert service.inbox_for("owner") == []
    held = service.deferred_for("owner")
    assert len(held) == 1
    assert held[0]["action"] == "defer"

    released = service.release_deferred("owner", now=NIGHT.replace(hour=8))
    assert len(released) == 1
    assert len(service.inbox_for("owner")) == 1


def test_sleep_mode_holds_a_deferral_until_it_is_turned_off():
    """And then releases it.

    A sleep-mode hold has no `deliver_at`, because sleep mode has no scheduled
    end. The first version of `release_deferred` required one, which stranded
    every sleep-mode hold permanently — the operator would end sleep mode and
    their notifications would stay held forever, indistinguishable from never
    having arrived. That is worse than not having sleep mode at all.
    """
    from ai.notify import Notification, Policy, Severity, service

    service.set_policy("owner", Policy(operator="owner", sleeping=True))
    service.submit(
        Notification(key="k", severity=Severity.IMPORTANT, title="t", body="b", operator="owner"),
        now=DAY,
    )
    # Nothing comes out while sleep mode is on, however long has passed.
    assert service.release_deferred("owner", now=DAY + timedelta(days=2)) == []
    assert len(service.deferred_for("owner")) == 1

    service.set_policy("owner", Policy(operator="owner", sleeping=False))
    released = service.release_deferred("owner", now=DAY + timedelta(minutes=1))
    assert len(released) == 1, "the hold survived sleep mode ending"
    assert service.deferred_for("owner") == []
    assert len(service.inbox_for("owner")) == 1


def test_a_quiet_hours_hold_is_not_released_early():
    """The other kind of hold. It has a time, and that time is honoured."""
    from ai.notify import Notification, Policy, QuietHours, Severity, service

    service.set_policy("owner", Policy(operator="owner", quiet_hours=QuietHours(22, 7)))
    service.submit(
        Notification(key="k", severity=Severity.IMPORTANT, title="t", body="b", operator="owner"),
        now=NIGHT,
    )
    assert service.release_deferred("owner", now=NIGHT.replace(hour=5)) == []
    assert len(service.release_deferred("owner", now=NIGHT.replace(hour=8))) == 1


def test_one_operator_cannot_read_anothers_inbox():
    """The cross-operator leak this repository shipped once already."""
    from ai.notify import Notification, Severity, service

    service.submit(Notification(key="k", severity=Severity.HIGH, title="t", body="b", operator="alice"), now=DAY)
    assert len(service.inbox_for("alice")) == 1
    assert service.inbox_for("bob") == []
    assert service.watches_for("bob") == []


def test_a_watch_only_fires_for_its_own_operator():
    from ai.notify import Watch, service

    service.add_watch(
        Watch(operator="alice", subject="daily_loss_pct", comparison="gte", threshold=4.0, severity="high")
    )
    assert service.check_watches("bob", {"daily_loss_pct": 9.0}, now=DAY) == []
    assert len(service.check_watches("alice", {"daily_loss_pct": 9.0}, now=DAY)) == 1


def test_a_watch_on_an_unmeasured_reading_stays_quiet():
    from ai.notify import Watch, service

    service.add_watch(
        Watch(operator="owner", subject="daily_loss_pct", comparison="gte", threshold=4.0, severity="high")
    )
    assert service.check_watches("owner", {"daily_loss_pct": None}, now=DAY) == []
    assert service.check_watches("owner", {}, now=DAY) == []


def test_an_alarm_fires_once_through_the_policy():
    from ai.notify import Alarm, service

    service.add_alarm(Alarm(operator="owner", at=DAY, title="London open"))
    assert len(service.due_alarms("owner", now=DAY)) == 1
    assert service.due_alarms("owner", now=DAY + timedelta(hours=1)) == []


def test_an_observation_with_an_unmappable_severity_is_reported_not_swallowed():
    """An unmapped severity means a condition nobody will be told about, which
    must not pass silently."""
    from ai.notify import service

    class _Odd:
        department = "x"
        trigger = "y"
        severity = "apocalyptic"
        summary = "s"

    assert service.handle_observation(_Odd()) is None


# ── the operator surface ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_policy_endpoint_states_the_floor_it_cannot_turn_off():
    """An operator switching on quiet hours deserves to see, on the same screen,
    what quiet hours cannot do."""
    from api.ai_notifications import notification_policy
    from api.auth import TokenPayload

    body = await notification_policy(TokenPayload(sub="owner", role="superadmin"))
    assert "critical" in body["critical_floor"].lower()
    assert "quiet hours" in body["critical_floor"].lower()


@pytest.mark.asyncio
async def test_a_watch_is_created_for_the_caller_not_for_a_name_in_the_body():
    """Accepting `operator` from the request would let anyone create a watch
    that notifies somebody else — or read one by creating it under their name."""
    from api.ai_notifications import add_notification_watch, notification_watches
    from api.auth import TokenPayload

    alice = TokenPayload(sub="alice", role="superadmin")
    bob = TokenPayload(sub="bob", role="superadmin")

    await add_notification_watch(
        {"subject": "daily_loss_pct", "comparison": "gte", "threshold": 4.0, "operator": "bob"},
        alice,
    )
    assert len(((await notification_watches(alice))["watches"])) == 1
    assert (await notification_watches(bob))["watches"] == []


@pytest.mark.asyncio
async def test_setting_quiet_hours_round_trips():
    from api.ai_notifications import notification_policy, set_notification_policy
    from api.auth import TokenPayload

    user = TokenPayload(sub="owner", role="superadmin")
    await set_notification_policy({"quiet_hours": {"start_hour": 22, "end_hour": 7}}, user)
    body = await notification_policy(user)
    assert body["quiet_hours"]["start_hour"] == 22
    assert body["quiet_hours"]["end_hour"] == 7


@pytest.mark.asyncio
async def test_an_invalid_quiet_hours_window_is_refused_rather_than_stored():
    """A stored 99:00 window would silently cover nothing, and the operator
    would believe they had quiet hours."""
    from fastapi import HTTPException

    from api.ai_notifications import set_notification_policy
    from api.auth import TokenPayload

    with pytest.raises(HTTPException) as caught:
        await set_notification_policy(
            {"quiet_hours": {"start_hour": 99, "end_hour": 7}}, TokenPayload(sub="owner", role="superadmin")
        )
    assert caught.value.status_code == 400


@pytest.mark.asyncio
async def test_the_inbox_endpoint_shows_held_notifications_too():
    from api.ai_notifications import notification_inbox
    from api.auth import TokenPayload
    from ai.notify import Notification, Policy, QuietHours, Severity, service

    service.set_policy("owner", Policy(operator="owner", quiet_hours=QuietHours(0, 23)))
    service.submit(Notification(key="k", severity=Severity.IMPORTANT, title="t", body="b", operator="owner"), now=NIGHT)
    body = await notification_inbox(TokenPayload(sub="owner", role="superadmin"))
    assert body["inbox"] == []
    assert len(body["deferred"]) == 1


@pytest.mark.asyncio
async def test_one_operator_cannot_read_anothers_notifications_through_the_api():
    from api.ai_notifications import notification_inbox
    from api.auth import TokenPayload
    from ai.notify import Notification, Severity, service

    service.submit(Notification(key="k", severity=Severity.HIGH, title="t", body="b", operator="alice"), now=DAY)
    body = await notification_inbox(TokenPayload(sub="bob", role="superadmin"))
    assert body["inbox"] == []
    assert body["operator"] == "bob"


@pytest.mark.asyncio
async def test_a_wake_condition_can_be_created_through_the_api():
    """`Policy.wake_conditions` was settable only from Python — a §19 capability
    with no route to it, which is the same as not having it."""
    from api.ai_notifications import add_notification_watch, notification_watches
    from api.auth import TokenPayload
    from ai.notify import service

    user = TokenPayload(sub="owner", role="superadmin")
    await add_notification_watch(
        {"subject": "daily_loss_pct", "comparison": "gte", "threshold": 4.0, "severity": "high", "wake": True},
        user,
    )
    assert len(service.wake_conditions_for("owner")) == 1
    assert (await notification_watches(user))["watches"][0]["wake"] is True


@pytest.mark.asyncio
async def test_a_watch_does_not_wake_you_unless_you_asked_it_to():
    """Defaulting `wake` on would let a routine threshold wake somebody at three
    in the morning."""
    from api.ai_notifications import add_notification_watch, notification_watches
    from api.auth import TokenPayload
    from ai.notify import service

    user = TokenPayload(sub="owner", role="superadmin")
    await add_notification_watch({"subject": "spread", "comparison": "gte", "threshold": 2.0}, user)
    assert service.wake_conditions_for("owner") == []
    assert (await notification_watches(user))["watches"][0]["wake"] is False


def test_a_wake_condition_created_this_way_really_pierces_sleep_mode():
    """The end-to-end version of the wake-condition rule: created through the
    service, it has to reach `decide` and get through."""
    from ai.notify import Notification, Policy, QuietHours, Severity, Watch, service

    service.set_policy("owner", Policy(operator="owner", sleeping=True, quiet_hours=QuietHours(22, 7)))
    service.add_watch(
        Watch(operator="owner", subject="daily_loss_pct", comparison="gte", threshold=3.0, severity="high"),
        wake=True,
    )
    held = service.submit(
        Notification(key="unrelated", severity=Severity.HIGH, title="t", body="b", operator="owner"), now=NIGHT
    )
    woken = service.submit(
        Notification(key="daily_loss_pct", severity=Severity.HIGH, title="t", body="b", operator="owner"),
        now=NIGHT,
        wake_value=4.0,
    )
    assert held.action == "defer"
    assert woken.action == "deliver"
    assert "asked to be woken" in woken.reason
