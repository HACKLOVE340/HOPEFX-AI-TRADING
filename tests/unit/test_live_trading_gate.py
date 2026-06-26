# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/unit/test_live_trading_gate.py
=====================================
Deep unit tests for core/live_trading_gate.py covering every gate check,
the master ``check()`` aggregation, ``require_open`` decorator, and the
``get_gate()`` singleton factory.

Coverage targets:
- ``_check_kill_switch()`` — inactive, active, unavailable
- ``_check_paper_clock()`` — complete, incomplete, unavailable
- ``_check_oos_accuracy()`` — passes, accuracy too low, p-value too high,
  nested structure, no file
- ``_check_sharpe_gate()`` — live report path (pass/block/no-pooled),
  authoritative meta path, extended meta path, oos-meta fallback, no file
- ``_check_feature_flag()`` — enabled, disabled
- ``check()`` — all pass, first failure propagated, all checks still run,
  exception inside a check handled gracefully
- ``require_open`` decorator — raises when gate blocked, passes when open
- ``status_dict()`` — shape validation
- ``GateResult.to_dict()``
- ``get_gate()`` singleton returns same instance
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.live_trading_gate import GateResult, LiveTradingGate, get_gate


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _gate() -> LiveTradingGate:
    """Fresh gate instance for each test (no shared state)."""
    return LiveTradingGate()


def _all_pass_gate(tmp_path: Path) -> LiveTradingGate:
    """
    Return a gate whose every check passes by patching external dependencies.
    """
    gate = _gate()
    gate._check_kill_switch = lambda: (True, "Kill-switch inactive")
    gate._check_paper_clock = lambda: (True, "Paper clock complete: 35.0 days elapsed")
    gate._check_oos_accuracy = lambda: (True, "OOS accuracy 0.65 (p=0.01, n=300)")
    gate._check_sharpe_gate = lambda: (True, "Sharpe gate passed: N=700 trades, SE=0.07")
    gate._check_feature_flag = lambda: (True, "FEATURE_LIVE_TRADING=true")
    return gate


# ─────────────────────────────────────────────────────────────────────────────
# GateResult
# ─────────────────────────────────────────────────────────────────────────────


class TestGateResult:
    def test_to_dict_shape(self):
        gr = GateResult(allowed=True, checks={"k": {"passed": True, "message": "OK"}})
        d = gr.to_dict()
        assert "allowed" in d
        assert "reason" in d
        assert "checked_at" in d
        assert "checks" in d

    def test_to_dict_allowed_false(self):
        gr = GateResult(allowed=False, reason="[kill_switch] active")
        assert gr.to_dict()["allowed"] is False

    def test_default_reason_is_empty(self):
        gr = GateResult(allowed=True)
        assert gr.reason == ""

    def test_checks_default_is_new_dict(self):
        gr1 = GateResult(allowed=True)
        gr2 = GateResult(allowed=True)
        gr1.checks["x"] = {}
        assert "x" not in gr2.checks


# ─────────────────────────────────────────────────────────────────────────────
# _check_kill_switch
# ─────────────────────────────────────────────────────────────────────────────


class TestCheckKillSwitch:
    def test_passes_when_inactive(self):
        gate = _gate()
        ks = MagicMock()
        ks.is_active.return_value = False
        ks.reason = ""
        with patch("core.live_trading_gate.KillSwitch", return_value=ks):
            passed, msg = gate._check_kill_switch()
        assert passed is True
        assert "inactive" in msg.lower()

    def test_blocks_when_active(self):
        gate = _gate()
        ks = MagicMock()
        ks.is_active.return_value = True
        ks.reason = "drawdown exceeded"
        with patch("core.live_trading_gate.KillSwitch", return_value=ks):
            passed, msg = gate._check_kill_switch()
        assert passed is False
        assert "ACTIVE" in msg

    def test_blocks_when_unavailable(self):
        gate = _gate()
        with patch.dict("sys.modules", {"kill_switch": None}):
            passed, _ = gate._check_kill_switch()
        assert passed is False


# ─────────────────────────────────────────────────────────────────────────────
# _check_paper_clock
# ─────────────────────────────────────────────────────────────────────────────


class TestCheckPaperClock:
    def _mock_clock(self, complete: bool, elapsed: float = 35.0) -> MagicMock:
        clock = MagicMock()
        clock.status.return_value = {
            "complete": complete,
            "elapsed_days": elapsed,
            "remaining_days": max(0, 30.0 - elapsed),
            "environment": "practice",
        }
        return clock

    def test_passes_when_complete(self):
        gate = _gate()
        clock = self._mock_clock(complete=True, elapsed=35.0)
        with patch("core.live_trading_gate.get_clock", return_value=clock):
            passed, msg = gate._check_paper_clock()
        assert passed is True
        assert "complete" in msg.lower()

    def test_blocks_when_incomplete(self):
        gate = _gate()
        clock = self._mock_clock(complete=False, elapsed=10.0)
        with (
            patch("core.live_trading_gate.get_clock", return_value=clock),
            patch.dict("sys.modules", {"monitoring.sentry_config": MagicMock()}),
        ):
            passed, msg = gate._check_paper_clock()
        assert passed is False
        assert "incomplete" in msg.lower() or "remaining" in msg.lower()

    def test_blocks_when_unavailable(self):
        gate = _gate()
        # Patch the name bound in the gate's namespace, not sys.modules: get_clock
        # is imported at module load, so once live_trading_gate has been imported
        # (as it has by the full suite) patching sys.modules no longer affects it.
        with patch("core.live_trading_gate.get_clock", None):
            passed, _ = gate._check_paper_clock()
        assert passed is False


# ─────────────────────────────────────────────────────────────────────────────
# _check_oos_accuracy
# ─────────────────────────────────────────────────────────────────────────────


class TestCheckOosAccuracy:
    def _write_meta(self, tmp_path: Path, accuracy: float, p_value: float, n: int = 300) -> Path:
        meta = {
            "oos_accuracy": accuracy,
            "oos_p_value": p_value,
            "oos_n": n,
        }
        p = tmp_path / "advanced_oos_meta.json"
        p.write_text(json.dumps(meta))
        return p

    def test_passes_when_accuracy_and_pvalue_ok(self, tmp_path):
        gate = _gate()
        self._write_meta(tmp_path, accuracy=0.65, p_value=0.01)
        with patch("core.live_trading_gate.ROOT", tmp_path):
            passed, msg = gate._check_oos_accuracy()
        assert passed is True
        assert "0.65" in msg

    def test_blocks_when_accuracy_too_low(self, tmp_path):
        gate = _gate()
        self._write_meta(tmp_path, accuracy=0.52, p_value=0.01)
        with patch("core.live_trading_gate.ROOT", tmp_path):
            passed, msg = gate._check_oos_accuracy()
        assert passed is False
        assert "accuracy" in msg.lower()

    def test_blocks_when_pvalue_too_high(self, tmp_path):
        gate = _gate()
        self._write_meta(tmp_path, accuracy=0.65, p_value=0.10)
        with patch("core.live_trading_gate.ROOT", tmp_path):
            passed, msg = gate._check_oos_accuracy()
        assert passed is False
        assert "p-value" in msg.lower() or "not statistically" in msg.lower()

    def test_blocks_when_no_meta_file(self, tmp_path):
        gate = _gate()
        with patch("core.live_trading_gate.ROOT", tmp_path):
            passed, msg = gate._check_oos_accuracy()
        assert passed is False
        assert "not found" in msg.lower()

    def test_handles_nested_oos_structure(self, tmp_path):
        """Training report wraps OOS data under 'oos' key."""
        gate = _gate()
        meta = {"oos": {"oos_accuracy": 0.68, "oos_p_value": 0.02, "oos_n": 400}}
        p = tmp_path / "advanced_oos_meta.json"
        p.write_text(json.dumps(meta))
        with patch("core.live_trading_gate.ROOT", tmp_path):
            passed, _ = gate._check_oos_accuracy()
        assert passed is True


# ─────────────────────────────────────────────────────────────────────────────
# _check_sharpe_gate
# ─────────────────────────────────────────────────────────────────────────────


class TestCheckSharpeGate:
    def _write_report(self, tmp_path: Path, gate_passed: bool, n: int = 700, se: float = 0.07) -> Path:
        """Write a multi_symbol_report.json under tmp_path/backtest/results/."""
        report_dir = tmp_path / "backtest" / "results"
        report_dir.mkdir(parents=True)
        report = {
            "pooled": {
                "sharpe_gate_passed": gate_passed,
                "n_total_trades": n,
                "pooled_sharpe_se": se,
                "pooled_sharpe": 1.5,
            }
        }
        p = report_dir / "multi_symbol_report.json"
        p.write_text(json.dumps(report))
        return p

    def test_passes_via_live_report(self, tmp_path):
        gate = _gate()
        self._write_report(tmp_path, gate_passed=True)
        with patch("core.live_trading_gate.ROOT", tmp_path):
            passed, msg = gate._check_sharpe_gate()
        assert passed is True
        assert "N=700" in msg

    def test_blocks_via_live_report_gate_not_passed(self, tmp_path):
        gate = _gate()
        self._write_report(tmp_path, gate_passed=False, n=100, se=0.5)
        with (
            patch("core.live_trading_gate.ROOT", tmp_path),
            patch.dict("sys.modules", {"monitoring.sentry_config": MagicMock()}),
        ):
            passed, msg = gate._check_sharpe_gate()
        assert passed is False
        assert "BLOCKED" in msg

    def test_blocks_when_report_has_no_pooled_section(self, tmp_path):
        gate = _gate()
        report_dir = tmp_path / "backtest" / "results"
        report_dir.mkdir(parents=True)
        p = report_dir / "multi_symbol_report.json"
        p.write_text(json.dumps({"meta": {}}))  # no 'pooled' key
        with (
            patch("core.live_trading_gate.ROOT", tmp_path),
            patch.dict("sys.modules", {"monitoring.sentry_config": MagicMock()}),
        ):
            passed, _ = gate._check_sharpe_gate()
        assert passed is False

    def test_passes_via_authoritative_meta(self, tmp_path):
        gate = _gate()
        meta = {
            "sharpe_gate_authoritative": {
                "gate_passed": True,
                "pooled_n_trades": 700,
                "pooled_sharpe_se": 0.08,
                "message": "all good",
            }
        }
        meta_path = tmp_path / "ml" / "saved_models"
        meta_path.mkdir(parents=True)
        (meta_path / "advanced_oos_meta.json").write_text(json.dumps(meta))
        with patch("core.live_trading_gate.ROOT", tmp_path):
            passed, msg = gate._check_sharpe_gate()
        assert passed is True
        assert "authoritative" in msg

    def test_blocks_via_authoritative_meta_gate_false(self, tmp_path):
        gate = _gate()
        meta = {
            "sharpe_gate_authoritative": {
                "gate_passed": False,
                "pooled_n_trades": 200,
                "pooled_sharpe_se": 0.30,
                "message": "insufficient trades",
            }
        }
        meta_path = tmp_path / "ml" / "saved_models"
        meta_path.mkdir(parents=True)
        (meta_path / "advanced_oos_meta.json").write_text(json.dumps(meta))
        with patch("core.live_trading_gate.ROOT", tmp_path):
            passed, _ = gate._check_sharpe_gate()
        assert passed is False

    def test_blocks_when_no_files(self, tmp_path):
        gate = _gate()
        with patch("core.live_trading_gate.ROOT", tmp_path):
            passed, msg = gate._check_sharpe_gate()
        assert passed is False
        assert "no backtest" in msg.lower() or "not found" in msg.lower()


# ─────────────────────────────────────────────────────────────────────────────
# _check_feature_flag
# ─────────────────────────────────────────────────────────────────────────────


class TestCheckFeatureFlag:
    def test_passes_when_enabled(self):
        gate = _gate()
        with patch.dict(os.environ, {"FEATURE_LIVE_TRADING": "true"}):
            passed, _ = gate._check_feature_flag()
        assert passed is True

    def test_blocks_when_disabled(self):
        gate = _gate()
        with patch.dict(os.environ, {"FEATURE_LIVE_TRADING": "false"}):
            passed, _ = gate._check_feature_flag()
        assert passed is False

    def test_blocks_when_unset(self):
        gate = _gate()
        env = {k: v for k, v in os.environ.items() if k != "FEATURE_LIVE_TRADING"}
        with patch.dict(os.environ, env, clear=True):
            passed, _ = gate._check_feature_flag()
        assert passed is False

    def test_case_insensitive_true(self):
        gate = _gate()
        with patch.dict(os.environ, {"FEATURE_LIVE_TRADING": "TRUE"}):
            passed, _ = gate._check_feature_flag()
        assert passed is True


# ─────────────────────────────────────────────────────────────────────────────
# check() — master aggregation
# ─────────────────────────────────────────────────────────────────────────────


class TestCheckMaster:
    def test_all_pass_returns_allowed(self, tmp_path):
        gate = _all_pass_gate(tmp_path)
        result = gate.check()
        assert isinstance(result, GateResult)
        assert result.allowed is True
        assert result.reason == ""

    def test_all_checks_present_in_result(self, tmp_path):
        gate = _all_pass_gate(tmp_path)
        result = gate.check()
        assert "kill_switch" in result.checks
        assert "paper_clock" in result.checks
        assert "oos_accuracy" in result.checks
        assert "sharpe_gate" in result.checks
        assert "feature_flag" in result.checks

    def test_first_failure_becomes_reason(self, tmp_path):
        gate = _all_pass_gate(tmp_path)
        gate._check_kill_switch = lambda: (False, "Kill-switch ACTIVE: drawdown")
        result = gate.check()
        assert result.allowed is False
        assert "kill_switch" in result.reason

    def test_all_checks_still_run_even_after_failure(self, tmp_path):
        """check() always evaluates every check for the status dict."""
        gate = _all_pass_gate(tmp_path)
        gate._check_paper_clock = lambda: (False, "clock incomplete")
        result = gate.check()
        # All six checks must appear in result.checks (config_consistency,
        # kill_switch, paper_clock, oos_accuracy, sharpe_gate, feature_flag).
        assert len(result.checks) == 6

    def test_check_exception_handled_gracefully(self, tmp_path):
        gate = _all_pass_gate(tmp_path)
        gate._check_sharpe_gate = lambda: (_ for _ in ()).throw(RuntimeError("db down"))

        def _raises():
            raise RuntimeError("db down")

        gate._check_sharpe_gate = _raises
        result = gate.check()
        assert result.allowed is False
        assert result.checks["sharpe_gate"]["passed"] is False

    def test_multiple_failures_only_first_in_reason(self, tmp_path):
        gate = _all_pass_gate(tmp_path)
        gate._check_kill_switch = lambda: (False, "kill active")
        gate._check_paper_clock = lambda: (False, "clock incomplete")
        result = gate.check()
        assert "kill_switch" in result.reason  # first failure
        assert "paper_clock" not in result.reason


# ─────────────────────────────────────────────────────────────────────────────
# require_open decorator
# ─────────────────────────────────────────────────────────────────────────────


class TestRequireOpen:
    def test_calls_function_when_gate_open(self, tmp_path):
        gate = _all_pass_gate(tmp_path)
        called = []

        @gate.require_open
        def place_order(symbol):
            called.append(symbol)

        place_order("XAUUSD")
        assert called == ["XAUUSD"]

    def test_raises_when_gate_blocked(self, tmp_path):
        gate = _all_pass_gate(tmp_path)
        gate._check_feature_flag = lambda: (False, "FEATURE_LIVE_TRADING not set")

        @gate.require_open
        def place_order():
            pass  # pragma: no cover

        with pytest.raises(RuntimeError, match="BLOCKED"):
            place_order()

    def test_decorated_function_receives_args(self, tmp_path):
        gate = _all_pass_gate(tmp_path)
        results = []

        @gate.require_open
        def place_order(symbol, units=1):
            results.append((symbol, units))

        place_order("XAUUSD", units=2)
        assert results == [("XAUUSD", 2)]


# ─────────────────────────────────────────────────────────────────────────────
# status_dict / get_gate singleton
# ─────────────────────────────────────────────────────────────────────────────


class TestStatusDictAndSingleton:
    def test_status_dict_shape(self, tmp_path):
        gate = _all_pass_gate(tmp_path)
        d = gate.status_dict()
        assert "allowed" in d
        assert "reason" in d
        assert "checks" in d
        assert "checked_at" in d

    def test_get_gate_returns_live_trading_gate_instance(self):
        import core.live_trading_gate as mod

        # Reset singleton for clean test
        mod._gate = None
        instance = get_gate()
        assert isinstance(instance, LiveTradingGate)

    def test_get_gate_returns_same_instance_on_repeated_calls(self):
        import core.live_trading_gate as mod

        mod._gate = None
        g1 = get_gate()
        g2 = get_gate()
        assert g1 is g2
