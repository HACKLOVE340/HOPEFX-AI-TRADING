# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""§22 telemetry: a metric is a real reading, or it is absent with a reason.

## The rule, and the instance of it already in this repository

**An unmeasured metric is absent, never zero.** A CPU gauge reading 0% because
the probe never ran is worse than no gauge at all: no gauge says "I do not
know", and 0% says "the machine is idle" — confidently, to somebody deciding
whether to start more work.

That is not hypothetical here. `infrastructure/metrics.py:update_system_metrics`
returns early when psutil is unavailable, leaving the gauge unset, and an unset
`Gauge` reads back its default. Measured before writing any of this:

    >>> m.PSUTIL_AVAILABLE = False
    >>> reg.update_system_metrics()
    >>> reg.get_collector("system_cpu_percent").get_value()
    0.0

The same registry's `get_all_metrics()` reports `None` for it, so the two
readers of one gauge disagree about whether the machine is idle or unknown.

## Absent is not the same as zero, and zero has to stay expressible

The fix is not "return None everywhere". A CPU genuinely at 0.0% must still be
reportable, and a `Reading` has to distinguish the two: `value=0.0` is a
measurement, `value=None` is not, and `None` without a reason is refused at
construction — because "absent" that cannot say why is just a different way of
telling somebody nothing.

## Two things §3 claimed exist and do not

The specification lists host telemetry and a "neural engine indicator" among
what the platform already has. Neither is in this repository. A decorative
neural-engine light — one that pulses regardless of whether any model is
reachable — would be the same lie as the zero gauge, so the indicator here is
bound to real state: which providers are configured, whether the last call
succeeded, what the breakers say.

These fail on the pre-fix tree: `ai.telemetry` does not exist there.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


# ── the Reading contract ──────────────────────────────────────────────────────


def test_a_real_zero_is_a_measurement():
    """The whole point: an idle CPU must still be reportable as idle."""
    from ai.telemetry.reading import measured

    reading = measured("cpu", 0.0, unit="%")
    assert reading.measured is True
    assert reading.value == 0.0
    assert reading.as_dict()["value"] == 0.0


def test_an_absent_reading_carries_no_value_and_a_reason():
    from ai.telemetry.reading import absent

    reading = absent("cpu", "psutil is not installed", unit="%")
    assert reading.measured is False
    assert reading.value is None
    assert reading.as_dict()["value"] is None
    assert reading.as_dict()["reason"] == "psutil is not installed"


def test_an_absent_reading_without_a_reason_is_refused():
    """ "I do not know" that cannot say why is a different way of saying nothing."""
    from ai.telemetry.reading import Reading

    with pytest.raises(ValueError):
        Reading(name="cpu", value=None, reason="")
    with pytest.raises(ValueError):
        Reading(name="cpu", value=None, reason="   ")


def test_a_measured_reading_cannot_also_carry_a_reason():
    """A value AND an excuse is two answers to one question."""
    from ai.telemetry.reading import Reading

    with pytest.raises(ValueError):
        Reading(name="cpu", value=12.0, reason="psutil is missing")


def test_a_reading_needs_a_name():
    from ai.telemetry.reading import Reading

    with pytest.raises(ValueError):
        Reading(name="  ", value=1.0)


def test_serialising_an_absent_reading_never_produces_a_zero():
    """The defect travels through JSON if the shape allows it to."""
    import json

    from ai.telemetry.reading import absent

    blob = json.dumps(absent("gpu_utilisation", "no GPU library is installed").as_dict())
    assert '"value": null' in blob
    assert '"value": 0' not in blob


# ── host telemetry ────────────────────────────────────────────────────────────


def test_cpu_is_measured_when_psutil_is_present():
    from ai.telemetry import host

    reading = host.cpu()
    assert reading.measured is True
    assert 0.0 <= reading.value <= 100.0
    assert reading.unit == "%"


def test_cpu_is_absent_with_a_reason_when_psutil_is_missing(monkeypatch):
    from ai.telemetry import host

    monkeypatch.setattr(host, "_psutil", lambda: None)
    reading = host.cpu()
    assert reading.measured is False
    assert "psutil" in reading.reason


def test_a_probe_that_raises_is_absent_and_names_the_failure(monkeypatch):
    from ai.telemetry import host

    class _Broken:
        def cpu_percent(self, interval=None):
            raise OSError("/proc is not mounted")

    monkeypatch.setattr(host, "_psutil", lambda: _Broken())
    reading = host.cpu()
    assert reading.measured is False
    assert "OSError" in reading.reason


def test_memory_and_disk_report_the_same_way():
    from ai.telemetry import host

    for reading in (host.memory(), host.disk()):
        assert reading.measured is True
        assert reading.unit == "%"


def test_no_gpu_library_is_different_from_no_gpu(monkeypatch):
    """ "I cannot look" and "I looked and there are none" are different answers,
    and only one of them means the machine has no accelerator."""
    from ai.telemetry import host

    monkeypatch.setattr(host, "_nvml", lambda: None)
    result = host.gpu()
    assert result["detectable"] is False
    assert "install" in result["reason"] or "not installed" in result["reason"]
    assert result["devices"] == []


def test_a_detectable_host_with_no_cards_says_zero_devices(monkeypatch):
    from ai.telemetry import host

    class _Nvml:
        def nvmlDeviceGetCount(self):
            return 0

    monkeypatch.setattr(host, "_nvml", lambda: _Nvml())
    result = host.gpu()
    assert result["detectable"] is True
    assert result["devices"] == []
    assert result["reason"] == ""


def test_the_host_snapshot_lists_what_it_could_not_measure(monkeypatch):
    from ai.telemetry import host

    monkeypatch.setattr(host, "_psutil", lambda: None)
    snap = host.snapshot()
    assert set(snap["unmeasured"]) >= {"cpu", "memory", "disk"}
    assert all(snap["readings"][n]["value"] is None for n in ("cpu", "memory", "disk"))


# ── agent health ──────────────────────────────────────────────────────────────


def test_agent_health_reports_a_row_per_department():
    from ai.telemetry import agents
    from ai.departments import DEPARTMENTS

    report = agents.agent_health()
    assert set(report["departments"]) == set(DEPARTMENTS)


def test_a_department_with_no_implemented_action_is_named_as_such():
    """A department that exists and can do nothing is not a healthy department."""
    from ai.telemetry import agents

    report = agents.agent_health()
    for key, row in report["departments"].items():
        assert "implemented" in row, key
        assert isinstance(row["implemented"], int)
        assert row["status"] in {"ready", "declared_only"}


def test_agent_health_says_when_the_watchers_have_never_run(monkeypatch):
    """ "No observations" and "the watcher has not started" look identical on a
    screen, and only one of them is a problem."""
    from ai.telemetry import agents

    report = agents.agent_health(watcher_runs=0)
    assert report["awareness"]["measured"] is False
    assert "never run" in report["awareness"]["reason"]


def test_agent_health_reports_the_job_pool_from_the_runner_not_from_a_guess():
    from ai.telemetry import agents
    from ai.jobs.runner import JobRunner

    runner = JobRunner(max_concurrent=3)
    try:
        report = agents.agent_health(runner=runner)
        assert report["jobs"]["max_concurrent"] == 3
        assert report["jobs"]["running"] == 0
    finally:
        runner.shutdown()


def test_agent_health_without_a_runner_says_so_rather_than_reporting_zero():
    from ai.telemetry import agents

    report = agents.agent_health(runner=None)
    assert report["jobs"]["measured"] is False
    assert report["jobs"]["reason"]


# ── security events ───────────────────────────────────────────────────────────


def test_security_events_counts_refusals_from_the_tool_bus():
    from ai.departments import build_tool_bus
    from ai.telemetry import security
    from ai.tools.bus import ToolDenied

    bus = build_tool_bus()
    with pytest.raises(ToolDenied):
        bus.invoke("markets_execution.place_order", operator="owner")

    report = security.security_events(tool_bus=bus)
    assert report["tool_denials"]["measured"] is True
    assert report["tool_denials"]["value"] >= 1


def test_security_events_without_a_bus_reports_absent_not_zero():
    """Zero denials and no audit trail are different, and one is reassuring."""
    from ai.telemetry import security

    report = security.security_events(tool_bus=None)
    assert report["tool_denials"]["measured"] is False
    assert report["tool_denials"]["value"] is None
    assert report["tool_denials"]["reason"]


def test_security_events_reports_registered_credentials_being_watched_for():
    from ai.telemetry import security

    report = security.security_events(tool_bus=None)
    assert report["output_guardrail"]["measured"] is True


# ── the neural engine indicator, bound to real state ──────────────────────────


def test_the_indicator_is_offline_when_no_provider_is_configured():
    """§3 claims this exists. It did not, and a decorative one that pulses
    whatever the model layer is doing would be the zero gauge again."""
    from ai.telemetry import neural

    state = neural.neural_engine(providers=frozenset())
    assert state["status"] == "offline"
    assert state["providers"] == []
    assert "no provider" in state["reason"]


def test_the_indicator_is_ready_when_a_provider_is_configured():
    from ai.telemetry import neural

    state = neural.neural_engine(providers=frozenset({"anthropic"}))
    assert state["status"] == "ready"
    assert state["providers"] == ["anthropic"]


def test_the_indicator_reports_degraded_when_a_breaker_is_open():
    from ai.telemetry import neural

    state = neural.neural_engine(
        providers=frozenset({"anthropic", "openai"}),
        open_breakers=("openai",),
    )
    assert state["status"] == "degraded"
    assert state["open_breakers"] == ["openai"]


def test_every_provider_broken_is_offline_not_degraded():
    from ai.telemetry import neural

    state = neural.neural_engine(providers=frozenset({"anthropic"}), open_breakers=("anthropic",))
    assert state["status"] == "offline"


def test_the_indicator_never_invents_activity_it_has_not_seen():
    from ai.telemetry import neural

    state = neural.neural_engine(providers=frozenset({"anthropic"}), last_success_at=None)
    assert state["last_success_at"] is None
    assert "no successful call" in state["reason"]


# ── the snapshot as a whole ───────────────────────────────────────────────────


def test_the_snapshot_separates_what_it_measured_from_what_it_could_not(monkeypatch):
    from ai.telemetry import host, snapshot

    monkeypatch.setattr(host, "_psutil", lambda: None)
    snap = snapshot()
    assert snap["unmeasured"], "nothing was reported as unmeasured while psutil was absent"
    for name in snap["unmeasured"]:
        assert snap["unmeasured"][name], f"{name} is unmeasured with no reason"


def test_no_value_in_the_snapshot_is_a_stand_in_for_a_failed_probe(monkeypatch):
    from ai.telemetry import host, snapshot

    monkeypatch.setattr(host, "_psutil", lambda: None)
    snap = snapshot()
    for name, reading in snap["host"]["readings"].items():
        if reading["value"] is None:
            assert reading["reason"], name
        else:
            assert not reading["reason"], f"{name} has both a value and an excuse"


# ── the read surface ──────────────────────────────────────────────────────────


def test_the_telemetry_endpoint_is_read_only_and_classified():
    from ai.policy import roles

    assert roles.capability_for("ai_core_telemetry") is not None, (
        "an endpoint with no row has no declared authorization, and capability_for returning None is a refusal"
    )
    assert roles.capability_for("ai_core_telemetry").tier == roles.VIEW


def test_the_page_still_reads_no_endpoint_that_can_mutate():
    """The AI Core router is GET/HEAD only, and telemetry must not change that."""
    from api import ai_core

    for route in ai_core.router.routes:
        methods = set(getattr(route, "methods", set()))
        assert methods <= {"GET", "HEAD"}, f"{route.path} allows {methods}"


# ── the registry ──────────────────────────────────────────────────────────────


def test_the_phase_c_rows_are_live_and_their_evidence_resolves():
    from ai.hub import capabilities

    assert capabilities.verify().discrepancies == ()
    rows = {c.id: c for c in capabilities.REGISTRY}
    for row in (
        "telemetry.host",
        "telemetry.agent_health",
        "telemetry.security_events",
        "telemetry.no_decorative_values",
        "legacy.neural_engine",
    ):
        assert rows[row].state == "live", f"{row} is {rows[row].state}"
