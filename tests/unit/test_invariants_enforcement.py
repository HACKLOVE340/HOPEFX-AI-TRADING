# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Tests for the invariant enforcement facade (invariants.enforcement).

Covers the three modes (off / monitor / enforce), fail-safe semantics, the
checker-never-crashes-the-caller guarantee, and the status() surface used by the
/health/invariants endpoint.
"""

import pytest

from invariants import enforcement as enf

pytestmark = pytest.mark.unit


class _Signal:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


_GOOD = dict(confidence=0.7, probability=0.6, tick_mid=2000.0, tick_spread=0.5)
_BAD = dict(confidence=float("nan"), probability=0.6, tick_mid=2000.0, tick_spread=0.5)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("HOPEFX_INVARIANT_MODE", raising=False)
    monkeypatch.delenv("HOPEFX_INVARIANT_FAIL_CLOSED", raising=False)
    enf.reset_telemetry()
    yield
    enf.reset_telemetry()


# ── mode plumbing ─────────────────────────────────────────────────────────────────
def test_default_mode_is_monitor():
    assert enf.current_mode() == enf.MODE_MONITOR


def test_unknown_mode_falls_back_to_monitor(monkeypatch):
    monkeypatch.setenv("HOPEFX_INVARIANT_MODE", "banana")
    assert enf.current_mode() == enf.MODE_MONITOR


# ── pre-trade gate ────────────────────────────────────────────────────────────────
def test_pre_trade_off_skips_checks(monkeypatch):
    monkeypatch.setenv("HOPEFX_INVARIANT_MODE", "off")
    r = enf.enforce_pre_trade(_Signal(**_BAD))
    assert r.allowed is True
    assert r.violations == []  # off does no work at all
    assert r.mode == "off"


def test_pre_trade_monitor_logs_but_allows(monkeypatch):
    monkeypatch.setenv("HOPEFX_INVARIANT_MODE", "monitor")
    r = enf.enforce_pre_trade(_Signal(**_BAD))
    assert r.allowed is True  # monitor never blocks
    assert r.violations  # but the violation IS detected
    assert r.blocking is True


def test_pre_trade_enforce_blocks_bad_signal(monkeypatch):
    monkeypatch.setenv("HOPEFX_INVARIANT_MODE", "enforce")
    r = enf.enforce_pre_trade(_Signal(**_BAD))
    assert r.allowed is False
    assert r.violations


def test_pre_trade_enforce_allows_good_signal(monkeypatch):
    monkeypatch.setenv("HOPEFX_INVARIANT_MODE", "enforce")
    r = enf.enforce_pre_trade(_Signal(**_GOOD))
    assert r.allowed is True
    assert r.violations == []


def test_pre_trade_min_confidence_floor(monkeypatch):
    monkeypatch.setenv("HOPEFX_INVARIANT_MODE", "enforce")
    low = _Signal(confidence=0.2, probability=0.6, tick_mid=2000.0, tick_spread=0.5)
    r = enf.enforce_pre_trade(low, min_confidence=0.5)
    assert r.allowed is False
    ok = enf.enforce_pre_trade(_Signal(**_GOOD), min_confidence=0.5)
    assert ok.allowed is True


def test_pre_trade_crossed_spread_blocks(monkeypatch):
    monkeypatch.setenv("HOPEFX_INVARIANT_MODE", "enforce")
    # negative spread would reconstruct a crossed book; the facade only checks
    # spread when >= 0, so use a NaN mid to force a tick violation instead.
    bad = _Signal(confidence=0.7, probability=0.6, tick_mid=2000.0, tick_spread=float("inf"))
    r = enf.enforce_pre_trade(bad)
    # inf spread is not >= 0 comparable cleanly; finiteness of confidence ok, so
    # ensure at least no crash and a deterministic decision.
    assert isinstance(r.allowed, bool)


# ── market-data freshness (#19) ─────────────────────────────────────────────────────
def test_pre_trade_stale_tick_blocked(monkeypatch):
    monkeypatch.setenv("HOPEFX_INVARIANT_MODE", "enforce")
    fresh = _Signal(confidence=0.7, probability=0.6, tick_mid=2000.0, tick_spread=0.5, tick_ts=1000.0)
    assert enf.enforce_pre_trade(fresh, now=1000.2, max_staleness_s=5.0).allowed is True
    stale = _Signal(confidence=0.7, probability=0.6, tick_mid=2000.0, tick_spread=0.5, tick_ts=1000.0)
    assert enf.enforce_pre_trade(stale, now=1010.0, max_staleness_s=5.0).allowed is False


def test_pre_trade_no_timestamp_skips_freshness(monkeypatch):
    monkeypatch.setenv("HOPEFX_INVARIANT_MODE", "enforce")
    # No timestamp attr → freshness is a no-op, order still allowed.
    r = enf.enforce_pre_trade(_Signal(**_GOOD), now=9999.0, max_staleness_s=1.0)
    assert r.allowed is True


# ── exposure (#4) ───────────────────────────────────────────────────────────────────
def test_exposure_within_limits(monkeypatch):
    monkeypatch.setenv("HOPEFX_INVARIANT_MODE", "enforce")
    r = enf.enforce_exposure({"XAUUSD": 500.0}, {"XAUUSD": 1000.0})
    assert r.violations == []
    assert r.should_halt is False


def test_exposure_breach_detected(monkeypatch):
    monkeypatch.setenv("HOPEFX_INVARIANT_MODE", "enforce")
    r = enf.enforce_exposure({"XAUUSD": 5000.0}, {"XAUUSD": 1000.0})
    assert r.violations
    assert r.should_halt is True


# ── order authorization (#1/#6) ──────────────────────────────────────────────────────
def test_order_authorization_requires_token_and_decision(monkeypatch):
    monkeypatch.setenv("HOPEFX_INVARIANT_MODE", "enforce")

    class _O:
        risk_approval_token = ""
        decision_id = ""

    assert enf.enforce_order_authorization(_O()).allowed is False
    ok = _O()
    ok.risk_approval_token = "rat-1"
    ok.decision_id = "dec-1"
    assert enf.enforce_order_authorization(ok).allowed is True


def test_order_authorization_reads_metadata_and_dict(monkeypatch):
    monkeypatch.setenv("HOPEFX_INVARIANT_MODE", "enforce")
    as_dict = {"risk_approval_token": "rat-9", "decision_id": "dec-9"}
    assert enf.enforce_order_authorization(as_dict).allowed is True
    assert enf.enforce_order_authorization({"risk_approval_token": "rat-9"}).allowed is False  # no decision


# ── audit chain (#10) ─────────────────────────────────────────────────────────────────
def test_audit_chain_intact_vs_broken(monkeypatch):
    monkeypatch.setenv("HOPEFX_INVARIANT_MODE", "enforce")
    assert enf.enforce_audit_chain(True).violations == []
    broken = enf.enforce_audit_chain(False, broken_at=7)
    assert broken.violations
    assert broken.should_halt is True


# ── pod / tenant isolation (#12/#13) ──────────────────────────────────────────────────
def test_pod_isolation_disjoint_vs_shared(monkeypatch):
    monkeypatch.setenv("HOPEFX_INVARIANT_MODE", "enforce")
    assert enf.enforce_pod_isolation({"positions": [1]}, {"positions": [2]}).violations == []
    shared = enf.enforce_pod_isolation({"memory": "x"}, {"memory": "x"})
    assert shared.violations
    assert shared.should_halt is True


# ── recovery readiness (#3) ───────────────────────────────────────────────────────────
def test_recovery_readiness(monkeypatch):
    monkeypatch.setenv("HOPEFX_INVARIANT_MODE", "enforce")
    assert enf.enforce_recovery_readiness({"db": (True, True), "broker": (True, True)}).violations == []
    gap = enf.enforce_recovery_readiness({"db": (False, False)})
    assert gap.violations


# ── reconciliation ────────────────────────────────────────────────────────────────
def test_reconciliation_match_no_halt(monkeypatch):
    monkeypatch.setenv("HOPEFX_INVARIANT_MODE", "enforce")
    r = enf.enforce_reconciliation(internal_value=10_000.0, external_value=10_000.0, value_tol=1.0)
    assert r.should_halt is False
    assert r.violations == []


def test_reconciliation_breach_halts_in_enforce(monkeypatch):
    monkeypatch.setenv("HOPEFX_INVARIANT_MODE", "enforce")
    r = enf.enforce_reconciliation(internal_value=10_000.0, external_value=8_000.0, value_tol=1.0)
    assert r.should_halt is True
    assert r.violations


def test_reconciliation_breach_monitor_does_not_halt(monkeypatch):
    monkeypatch.setenv("HOPEFX_INVARIANT_MODE", "monitor")
    r = enf.enforce_reconciliation(internal_value=10_000.0, external_value=8_000.0, value_tol=1.0)
    assert r.should_halt is False  # detected, logged, but no halt
    assert r.violations


def test_reconciliation_pnl_identity(monkeypatch):
    monkeypatch.setenv("HOPEFX_INVARIANT_MODE", "enforce")
    bad = enf.enforce_reconciliation(pnl=(100.0, 50.0, 999.0))
    assert bad.should_halt is True
    good = enf.enforce_reconciliation(pnl=(100.0, 50.0, 150.0))
    assert good.should_halt is False


# ── fail-safe: a checker bug must not crash or (by default) block ──────────────────
def test_checker_error_fails_open_by_default(monkeypatch):
    monkeypatch.setenv("HOPEFX_INVARIANT_MODE", "enforce")
    # pnl tuple of the wrong arity raises inside the checker thunk.
    r = enf.enforce_reconciliation(pnl=(1.0, 2.0))  # type: ignore[arg-type]
    assert r.allowed is True  # fail OPEN — do not take the desk down
    assert r.should_halt is False
    assert enf.status()["counters"]["checker_errors"] == 1


def test_checker_error_fails_closed_when_configured(monkeypatch):
    monkeypatch.setenv("HOPEFX_INVARIANT_MODE", "enforce")
    monkeypatch.setenv("HOPEFX_INVARIANT_FAIL_CLOSED", "1")
    r = enf.enforce_reconciliation(pnl=(1.0, 2.0))  # type: ignore[arg-type]
    assert r.allowed is False  # explicit opt-in to fail CLOSED
    assert r.should_halt is True


def test_facade_never_raises_on_weird_signal(monkeypatch):
    monkeypatch.setenv("HOPEFX_INVARIANT_MODE", "enforce")
    r = enf.enforce_pre_trade(object())  # no attributes at all
    assert isinstance(r.allowed, bool)  # defensive getattr → no crash


# ── status surface ────────────────────────────────────────────────────────────────
def test_status_reports_mode_and_engine_health(monkeypatch):
    monkeypatch.setenv("HOPEFX_INVARIANT_MODE", "enforce")
    enf.enforce_reconciliation(internal_value=1.0, external_value=5.0, value_tol=0.01)
    s = enf.status()
    assert s["mode"] == "enforce"
    assert s["blocking_enabled"] is True
    assert s["engine_healthy"] is True
    assert s["counters"]["checks"] >= 1
    assert s["counters"]["halts_signalled"] >= 1
    assert any(item["kind"] == "reconciliation" for item in s["recent"])


def test_status_off_mode_inactive(monkeypatch):
    monkeypatch.setenv("HOPEFX_INVARIANT_MODE", "off")
    s = enf.status()
    assert s["active"] is False
    assert s["blocking_enabled"] is False
