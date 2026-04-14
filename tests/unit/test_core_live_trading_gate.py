# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_core_live_trading_gate.py
==========================================
Coverage tests for core/live_trading_gate.py.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

import core.live_trading_gate as gate_mod
from core.live_trading_gate import GateResult, LiveTradingGate, get_gate


# ── GateResult ────────────────────────────────────────────────────────────────


def test_gate_result_to_dict():
    r = GateResult(allowed=True, reason="", checks={"a": {"passed": True, "message": "ok"}})
    d = r.to_dict()
    assert d["allowed"] is True
    assert "checks" in d
    assert "checked_at" in d


def test_gate_result_blocked():
    r = GateResult(allowed=False, reason="[kill_switch] active")
    assert not r.allowed
    assert "kill_switch" in r.reason


# ── _check_kill_switch ────────────────────────────────────────────────────────


def test_kill_switch_blocks_when_active():
    g = LiveTradingGate()
    mock_ks_cls = MagicMock()
    mock_ks_cls.return_value.is_active.return_value = True
    mock_ks_cls.return_value.reason = "drawdown breach"
    with patch.object(gate_mod, "KillSwitch", mock_ks_cls):
        passed, msg = g._check_kill_switch()
    assert not passed


def test_kill_switch_passes_when_inactive():
    g = LiveTradingGate()
    mock_ks_cls = MagicMock()
    mock_ks_cls.return_value.is_active.return_value = False
    with patch.object(gate_mod, "KillSwitch", mock_ks_cls):
        passed, msg = g._check_kill_switch()
    assert passed


def test_kill_switch_blocks_when_unavailable():
    g = LiveTradingGate()
    with patch.object(gate_mod, "KillSwitch", None):
        passed, msg = g._check_kill_switch()
    assert not passed


# ── _check_paper_clock ────────────────────────────────────────────────────────


def test_paper_clock_passes_when_complete():
    g = LiveTradingGate()
    mock_clock_instance = MagicMock()
    mock_clock_instance.status.return_value = {
        "elapsed_days": 35.0,
        "complete": True,
        "remaining_days": 0.0,
        "environment": "practice",
    }
    mock_get_clock = MagicMock(return_value=mock_clock_instance)
    with patch.object(gate_mod, "get_clock", mock_get_clock):
        passed, msg = g._check_paper_clock()
    assert passed
    assert "35" in msg


def test_paper_clock_blocks_when_incomplete():
    g = LiveTradingGate()
    mock_clock_instance = MagicMock()
    mock_clock_instance.status.return_value = {
        "elapsed_days": 10.0,
        "complete": False,
        "remaining_days": 20.0,
        "environment": "practice",
    }
    mock_get_clock = MagicMock(return_value=mock_clock_instance)
    with patch.object(gate_mod, "get_clock", mock_get_clock):
        passed, msg = g._check_paper_clock()
    assert not passed


def test_paper_clock_blocks_when_unavailable():
    g = LiveTradingGate()
    with patch.object(gate_mod, "get_clock", None):
        passed, msg = g._check_paper_clock()
    assert not passed


def test_paper_clock_blocks_on_exception():
    g = LiveTradingGate()
    mock_get_clock = MagicMock(side_effect=RuntimeError("clock error"))
    with patch.object(gate_mod, "get_clock", mock_get_clock):
        passed, msg = g._check_paper_clock()
    assert not passed


# ── _check_oos_accuracy ───────────────────────────────────────────────────────


def test_oos_accuracy_passes_with_valid_meta(tmp_path):
    # Use the direct path: ROOT / "advanced_oos_meta.json"
    meta = {"oos_accuracy": 0.68, "p_value_binomial": 0.01, "oos_n": 800}
    (tmp_path / "advanced_oos_meta.json").write_text(json.dumps(meta))

    g = LiveTradingGate()
    with patch.object(gate_mod, "ROOT", tmp_path):
        passed, msg = g._check_oos_accuracy()
    assert passed
    assert "0.68" in msg


def test_oos_accuracy_passes_via_ml_dir(tmp_path):
    meta = {"oos_accuracy": 0.70, "p_value_binomial": 0.02, "oos_n": 900}
    ml_dir = tmp_path / "ml" / "saved_models"
    ml_dir.mkdir(parents=True)
    (ml_dir / "advanced_oos_meta.json").write_text(json.dumps(meta))

    g = LiveTradingGate()
    with patch.object(gate_mod, "ROOT", tmp_path):
        passed, msg = g._check_oos_accuracy()
    assert passed


def test_oos_accuracy_blocks_low_accuracy(tmp_path):
    meta = {"oos_accuracy": 0.50, "p_value_binomial": 0.01, "oos_n": 800}
    (tmp_path / "advanced_oos_meta.json").write_text(json.dumps(meta))

    g = LiveTradingGate()
    with patch.object(gate_mod, "ROOT", tmp_path):
        passed, msg = g._check_oos_accuracy()
    assert not passed


def test_oos_accuracy_blocks_high_pvalue(tmp_path):
    meta = {"oos_accuracy": 0.70, "p_value_binomial": 0.10, "oos_n": 800}
    (tmp_path / "advanced_oos_meta.json").write_text(json.dumps(meta))

    g = LiveTradingGate()
    with patch.object(gate_mod, "ROOT", tmp_path):
        passed, msg = g._check_oos_accuracy()
    assert not passed


def test_oos_accuracy_blocks_when_no_file(tmp_path):
    g = LiveTradingGate()
    with patch.object(gate_mod, "ROOT", tmp_path):
        passed, msg = g._check_oos_accuracy()
    assert not passed


# ── _check_sharpe_gate ────────────────────────────────────────────────────────


def test_sharpe_gate_passes_with_report(tmp_path):
    report = {
        "pooled": {
            "n_total_trades": 700,
            "sharpe_gate_passed": True,
            "pooled_sharpe_se": 0.08,
            "pooled_sharpe": 1.5,
        }
    }
    results_dir = tmp_path / "backtest" / "results"
    results_dir.mkdir(parents=True)
    (results_dir / "multi_symbol_report.json").write_text(json.dumps(report))

    g = LiveTradingGate()
    with patch.object(gate_mod, "ROOT", tmp_path):
        passed, msg = g._check_sharpe_gate()
    assert passed


def test_sharpe_gate_blocks_when_not_passed(tmp_path):
    report = {
        "pooled": {
            "n_total_trades": 300,
            "sharpe_gate_passed": False,
            "pooled_sharpe_se": 0.20,
            "pooled_sharpe": 0.8,
        }
    }
    results_dir = tmp_path / "backtest" / "results"
    results_dir.mkdir(parents=True)
    (results_dir / "multi_symbol_report.json").write_text(json.dumps(report))

    g = LiveTradingGate()
    with patch.object(gate_mod, "ROOT", tmp_path):
        passed, msg = g._check_sharpe_gate()
    assert not passed


def test_sharpe_gate_blocks_no_pooled_section(tmp_path):
    report = {"summary": "no pooled key"}
    results_dir = tmp_path / "backtest" / "results"
    results_dir.mkdir(parents=True)
    (results_dir / "multi_symbol_report.json").write_text(json.dumps(report))

    g = LiveTradingGate()
    with patch.object(gate_mod, "ROOT", tmp_path):
        passed, msg = g._check_sharpe_gate()
    assert not passed


def test_sharpe_gate_falls_back_to_oos_meta(tmp_path):
    meta = {
        "sharpe_gate_authoritative": {
            "gate_passed": True,
            "pooled_n_trades": 650,
            "pooled_sharpe_se": 0.09,
            "message": "all good",
        }
    }
    ml_dir = tmp_path / "ml" / "saved_models"
    ml_dir.mkdir(parents=True)
    (ml_dir / "advanced_oos_meta.json").write_text(json.dumps(meta))

    g = LiveTradingGate()
    with patch.object(gate_mod, "ROOT", tmp_path):
        passed, msg = g._check_sharpe_gate()
    assert passed


def test_sharpe_gate_blocks_when_no_files(tmp_path):
    g = LiveTradingGate()
    with patch.object(gate_mod, "ROOT", tmp_path):
        passed, msg = g._check_sharpe_gate()
    assert not passed


# ── _check_feature_flag ───────────────────────────────────────────────────────


def test_feature_flag_blocks_when_not_set(monkeypatch):
    monkeypatch.setenv("FEATURE_LIVE_TRADING", "false")
    g = LiveTradingGate()
    passed, msg = g._check_feature_flag()
    assert not passed


def test_feature_flag_passes_when_set(monkeypatch):
    monkeypatch.setenv("FEATURE_LIVE_TRADING", "true")
    g = LiveTradingGate()
    passed, msg = g._check_feature_flag()
    assert passed


# ── check() — master gate ─────────────────────────────────────────────────────


def test_check_blocked_when_kill_switch_active():
    g = LiveTradingGate()
    g._check_kill_switch = lambda: (False, "kill switch active")
    g._check_paper_clock = lambda: (True, "ok")
    g._check_oos_accuracy = lambda: (True, "ok")
    g._check_sharpe_gate = lambda: (True, "ok")
    g._check_feature_flag = lambda: (True, "ok")
    result = g.check()
    assert not result.allowed
    assert "kill_switch" in result.reason


def test_check_allowed_when_all_pass():
    g = LiveTradingGate()
    g._check_kill_switch = lambda: (True, "ok")
    g._check_paper_clock = lambda: (True, "ok")
    g._check_oos_accuracy = lambda: (True, "ok")
    g._check_sharpe_gate = lambda: (True, "ok")
    g._check_feature_flag = lambda: (True, "ok")
    result = g.check()
    assert result.allowed
    assert result.reason == ""


def test_check_all_checks_evaluated_even_after_first_failure():
    g = LiveTradingGate()
    g._check_kill_switch = lambda: (False, "ks blocked")
    g._check_paper_clock = lambda: (False, "paper blocked")
    g._check_oos_accuracy = lambda: (True, "ok")
    g._check_sharpe_gate = lambda: (True, "ok")
    g._check_feature_flag = lambda: (False, "flag off")
    result = g.check()
    assert not result.allowed
    assert len(result.checks) == 5


def test_check_handles_exception_in_check_fn():
    g = LiveTradingGate()

    def _boom():
        raise RuntimeError("unexpected")

    g._check_kill_switch = _boom
    g._check_paper_clock = lambda: (True, "ok")
    g._check_oos_accuracy = lambda: (True, "ok")
    g._check_sharpe_gate = lambda: (True, "ok")
    g._check_feature_flag = lambda: (True, "ok")
    result = g.check()
    assert not result.allowed
    assert "Check error" in result.checks["kill_switch"]["message"]


# ── require_open decorator ────────────────────────────────────────────────────


def test_require_open_allows_when_gate_open():
    g = LiveTradingGate()
    g.check = lambda: GateResult(allowed=True)

    @g.require_open
    def _trade():
        return "executed"

    assert _trade() == "executed"


def test_require_open_blocks_when_gate_closed():
    g = LiveTradingGate()
    g.check = lambda: GateResult(allowed=False, reason="blocked")

    @g.require_open
    def _trade():
        return "executed"

    with pytest.raises(RuntimeError, match="BLOCKED"):
        _trade()


# ── status_dict ───────────────────────────────────────────────────────────────


def test_status_dict_returns_dict():
    g = LiveTradingGate()
    g.check = lambda: GateResult(allowed=False, reason="test", checks={})
    d = g.status_dict()
    assert isinstance(d, dict)
    assert "allowed" in d


# ── get_gate singleton ────────────────────────────────────────────────────────


def test_get_gate_returns_singleton():
    gate_mod._gate = None
    g1 = get_gate()
    g2 = get_gate()
    assert g1 is g2
    gate_mod._gate = None
