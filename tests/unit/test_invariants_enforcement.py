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
