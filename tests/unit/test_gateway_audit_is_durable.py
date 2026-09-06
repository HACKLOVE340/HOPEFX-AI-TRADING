# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The gateway audit trail must survive a restart.

`ai/gateway/audit.py` kept a Python list capped at 500 entries and nothing
else. Its own comment said "the durable sink is the config store via the
control plane" -- no code wrote there, so the sentence described a sink that
did not exist. Spec §6 requires an immutable audit trail and exportable
regulatory-grade audit logs; what shipped was a ring buffer that a process
restart erased, taking with it the record of every model call, its cost, and
who made it.

That is the `hopefx-dead-controls` shape in the observability layer: a control
that is documented accurately, believed, and not wired.

These tests fail on the pre-fix tree -- `set_durable_sink` and
`durable_sink_installed` do not exist there at all.
"""

from __future__ import annotations

import logging

import pytest

from ai.gateway import audit

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean():
    audit.reset_for_testing()
    yield
    audit.reset_for_testing()


def _record(**over):
    kwargs = {
        "operator": "owner",
        "role": "reasoning",
        "prompt": "what is the current drawdown",
        "attempts": [{"provider": "anthropic", "reason": "served"}],
        "served_by": "anthropic",
        "model": "claude-opus-5",
        "latency_ms": 12.5,
        "cost_usd": 0.0041,
        "tokens_in": 100,
        "tokens_out": 20,
    }
    kwargs.update(over)
    return audit.record_call(**kwargs)


def test_a_recorded_call_reaches_the_durable_sink():
    """The whole point: the record leaves the process."""
    written: list[dict] = []
    audit.set_durable_sink(written.append)

    _record()

    assert len(written) == 1, "record_call did not write to the durable sink"


def test_the_durable_record_carries_the_fingerprint_and_never_the_prompt():
    """Prompts carry positions, stop levels and occasionally credentials.

    The in-memory record already got this right. Persisting must not be the
    step that starts retaining prompt text -- a durable store is exactly where
    that would matter most.
    """
    written: list[dict] = []
    audit.set_durable_sink(written.append)

    # Not a credential — a representative trading prompt, which is the kind of
    # text that must never reach the durable store. detect-secrets scores it as
    # high-entropy; the gate firing here is the gate working.
    secret = "close my 3.5 lot XAUUSD short at 2411.20"  # pragma: allowlist secret
    _record(prompt=secret)

    blob = repr(written[0])
    assert secret not in blob, "the prompt text reached the durable sink"
    assert written[0]["prompt_sha256"] == audit.prompt_fingerprint(secret)


def test_a_sink_failure_does_not_fail_the_call_but_is_logged_loudly(caplog):
    """Audit must not take the platform down -- and must not vanish quietly.

    Swallowing the failure at DEBUG is how a control stops working without
    anyone noticing. The write is best-effort; the *evidence that it failed*
    is not.
    """

    def explode(_entry):
        raise RuntimeError("database is gone")

    audit.set_durable_sink(explode)

    with caplog.at_level(logging.ERROR):
        entry = _record()

    assert entry["operator"] == "owner", "a sink failure must not fail the call"
    assert any(r.levelno >= logging.ERROR for r in caplog.records), (
        "a failed durable audit write was not reported at ERROR"
    )


def test_the_in_memory_ring_still_serves_reads():
    """The fast read surface (`/ai-core/calls`) keeps working unchanged."""
    audit.set_durable_sink(lambda _e: None)
    _record()
    _record()
    assert len(audit.records()) == 2


def test_a_deployment_reports_whether_a_durable_sink_is_actually_installed():
    """The guard against this regressing into a dead control again.

    `durable_sink_installed()` is what the health surface asks. If a future
    refactor drops the wiring, this answers False and the operator can see it
    -- rather than the trail silently going back to being a ring buffer while
    the documentation still promises regulatory-grade export.
    """
    audit.reset_for_testing()
    assert audit.durable_sink_installed() is False

    audit.set_durable_sink(lambda _e: None)
    assert audit.durable_sink_installed() is True


def test_reset_for_testing_clears_the_sink_too():
    """Otherwise one test's fake sink silently receives another test's records."""
    audit.set_durable_sink(lambda _e: None)
    audit.reset_for_testing()
    assert audit.durable_sink_installed() is False


# ── the wiring ────────────────────────────────────────────────────────────────
# Everything above proves the seam works. These prove it is CONNECTED, which is
# the half that was missing last time: the cache, the tool bus and the sandbox
# were each built, tested and invoked by nothing.


def test_a_startup_factory_exists_and_is_registered():
    """A sink nothing installs is the defect this change exists to fix."""
    import core.startup_factories as F

    assert hasattr(F, "init_ai_audit_sink"), "no startup factory for the audit sink"

    src = __import__("pathlib").Path(F.__file__).read_text(encoding="utf-8")
    assert "F.init_ai_audit_sink" in src, "the factory is defined but never registered in the startup graph"


@pytest.mark.asyncio
async def test_the_factory_installs_a_sink_that_reaches_the_compliance_chain():
    """End to end, with a stand-in manager: record_call -> log_ai_call."""
    import core.startup_factories as F

    seen: list[dict] = []

    class _Manager:
        def log_ai_call(self, entry):
            seen.append(entry)

    class _State:
        compliance_manager = _Manager()

    await F.init_ai_audit_sink(_State())
    assert audit.durable_sink_installed() is True

    _record()
    assert len(seen) == 1
    assert seen[0]["model"] == "claude-opus-5"
    assert "prompt_sha256" in seen[0]


@pytest.mark.asyncio
async def test_a_missing_compliance_manager_is_reported_at_error(caplog):
    """Not installing the sink is a compliance-posture change. It is not quiet."""
    import core.startup_factories as F

    class _State:
        compliance_manager = None

    with caplog.at_level(logging.ERROR):
        result = await F.init_ai_audit_sink(_State())

    assert result is None
    assert audit.durable_sink_installed() is False
    assert any(r.levelno >= logging.ERROR for r in caplog.records), (
        "a deployment with no durable audit trail was not reported at ERROR"
    )


def test_the_compliance_manager_exposes_the_writer_the_factory_expects():
    """Guards the contract between the two modules."""
    from compliance.compliance_manager import ComplianceManager

    assert callable(getattr(ComplianceManager, "log_ai_call", None))
