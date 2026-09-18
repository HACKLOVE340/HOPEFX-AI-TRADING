# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Submitted strategy code is contained before it is approved for sale.

`ai/sandbox/` had ZERO production callers. Nothing ran code through it. The
only thing standing in front of strategy source submitted by a stranger was
`StrategyAuditor._check_forbidden_imports`, whose own docstring says what it is:

    **A filter, not containment.** A static check on adversarial source can
    always be worked around... Real containment is `ai/sandbox/`, which runs
    code under rlimits with no network and a scrubbed environment.

The code named the containment it needed and nothing routed to it. This is the
route: `run_audit` now executes the submission under the sandbox, and a
candidate that will not run contained does not pass the audit.

**The static screen stays.** It is not replaced, and that is deliberate — the
sandbox's own `run()` calls it as a pre-filter so an obvious payload is refused
before a process is spawned at all. Defence in depth means both, and the
sandbox's containment guarantees are tested with the screen off precisely so
neither is load-bearing alone.

**A sandbox that cannot run is a failed check, not a skipped one.** If the
runner is unavailable — no `resource` module, a platform that cannot fork — the
audit fails the submission rather than passing it. "We could not contain this"
must never resolve to "approved for sale".
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from monetization.marketplace_submission import AuditStatus, StrategyAuditor, StrategySubmission

pytestmark = pytest.mark.unit


SAFE_CODE = """
def generate_signal(bar):
    return "hold"
"""

HOSTILE_CODE = """
__import__('os').system('echo pwned')
"""


def a_submission(code: str) -> StrategySubmission:
    return StrategySubmission(
        submission_id="sub-1",
        creator_id="creator-1",
        name="Test Strategy",
        description=(
            "A strategy submitted for audit, with a description long enough to "
            "satisfy the minimum-length gate that the auditor also applies."
        ),
        strategy_code=code,
        backtest_results={"sharpe_ratio": 2.0, "max_drawdown": 0.1, "total_trades": 250},
        price_monthly=49.0,
        price_yearly=490.0,
        category="trend",
        tags=["xauusd"],
    )


# ── the sandbox is actually consulted ────────────────────────────────────────


def test_the_audit_runs_the_code_through_the_sandbox():
    """Zero production callers is the defect. This is the caller."""
    with patch("ai.sandbox.runner.run") as sandbox_run:
        sandbox_run.return_value = type(
            "R", (), {"ok": True, "stdout": "", "stderr": "", "reason_codes": (), "duration_ms": 1.0}
        )()
        StrategyAuditor().run_audit(a_submission(SAFE_CODE))
    assert sandbox_run.called, "the auditor approved code without ever containing it"


def test_the_report_carries_a_containment_check():
    report = StrategyAuditor().run_audit(a_submission(SAFE_CODE))
    names = {c.name for c in report.checks}
    assert "containment_check" in names, names


# ── a candidate that will not run contained does not pass ────────────────────


def test_hostile_code_fails_the_audit():
    report = StrategyAuditor().run_audit(a_submission(HOSTILE_CODE))
    assert report.status is AuditStatus.FAILED
    assert not report.passed


def test_a_sandbox_refusal_fails_the_audit():
    with patch("ai.sandbox.runner.run") as sandbox_run:
        sandbox_run.return_value = type(
            "R",
            (),
            {"ok": False, "stdout": "", "stderr": "blocked", "reason_codes": ("net_blocked",), "duration_ms": 1.0},
        )()
        report = StrategyAuditor().run_audit(a_submission(SAFE_CODE))
    assert report.status is AuditStatus.FAILED
    containment = next(c for c in report.checks if c.name == "containment_check")
    assert containment.passed is False


def test_an_unavailable_sandbox_fails_the_submission_rather_than_passing_it():
    """ "We could not contain this" must never resolve to "approved for sale"."""
    with patch("ai.sandbox.runner.run", side_effect=RuntimeError("cannot fork")):
        report = StrategyAuditor().run_audit(a_submission(SAFE_CODE))
    containment = next(c for c in report.checks if c.name == "containment_check")
    assert containment.passed is False
    assert report.status is AuditStatus.FAILED


# ── the static screen is not replaced ────────────────────────────────────────


def test_the_static_screen_still_runs():
    """Defence in depth: neither layer is load-bearing alone."""
    report = StrategyAuditor().run_audit(a_submission(HOSTILE_CODE))
    names = {c.name for c in report.checks}
    assert "security_check" in names
    security = next(c for c in report.checks if c.name == "security_check")
    assert security.passed is False


def test_clean_code_that_contains_cleanly_still_passes():
    """A gate that refuses everything is an outage, not a control."""
    with patch("ai.sandbox.runner.run") as sandbox_run:
        sandbox_run.return_value = type(
            "R", (), {"ok": True, "stdout": "", "stderr": "", "reason_codes": (), "duration_ms": 1.0}
        )()
        report = StrategyAuditor().run_audit(a_submission(SAFE_CODE))
    assert report.status is AuditStatus.PASSED, [(c.name, c.message) for c in report.checks if not c.passed]


# ── the containment is real, not mocked ──────────────────────────────────────


@pytest.mark.slow
def test_the_real_sandbox_refuses_a_network_call():
    """Executed, not mocked. The screen is off so containment alone is proved."""
    from ai.sandbox import runner

    result = runner.run(
        "import socket; socket.socket().connect(('1.1.1.1', 80))",
        prefilter=False,
        timeout_s=10.0,
    )
    assert result.ok is False


@pytest.mark.slow
def test_the_real_sandbox_runs_harmless_code():
    from ai.sandbox import runner

    result = runner.run("print('ok')", prefilter=False, timeout_s=10.0)
    assert result.ok is True
    assert "ok" in result.stdout
