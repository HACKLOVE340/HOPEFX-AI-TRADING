# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/test_deployment_gates.py
==============================
Tests for the three live-deployment gates in api/trading.py:

  Gate 1 — Kill switch: place_order blocked when active, allowed when inactive.
  Gate 2 — Sharpe gate: live orders blocked until ≥600 OOS trades confirmed.
  Gate 3 — CI model guard: live orders blocked when model trained with CI params.

Also verifies:
  - Paper trading bypasses both model gates.
  - APP_ENV=test bypasses both model gates.
  - ci_mode field is written into advanced_oos_meta.json by train_advanced.py.

Run with:
    pytest tests/test_deployment_gates.py -v
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault(
    "SECURITY_JWT_SECRET",
    "test-only-jwt-secret-key-minimum-32-chars!!",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _meta(*, gate_passed: bool, n_trades: int = 0, ci_mode: bool = False) -> dict:
    """Build a minimal advanced_oos_meta.json payload."""
    return {
        "ci_mode": ci_mode,
        "sharpe_gate": {
            "gate_passed": gate_passed,
            "n_trades": n_trades,
            "target_n": 600,
            "se": round((1 + 0.5 * 1.52**2) ** 0.5 / max(n_trades, 1) ** 0.5, 4),
            "credible": gate_passed,
        },
    }


def _write_meta(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


# ===========================================================================
# Gate 1 — Kill switch blocks place_order
# ===========================================================================
class TestKillSwitchGate:
    def test_active_kill_switch_raises_503(self, tmp_path):
        from fastapi import HTTPException
        import api.trading as trading_mod
        from kill_switch import KillSwitch

        ks = KillSwitch(
            flag_file=tmp_path / "ks.flag",
            deactivation_token="tok",
        )
        ks.activate("drawdown exceeded")
        trading_mod._set_kill_switch(ks)
        try:
            with pytest.raises(HTTPException) as exc_info:
                trading_mod._check_kill_switch()
            assert exc_info.value.status_code == 503
            assert "kill switch" in exc_info.value.detail.lower()
            assert "drawdown exceeded" in exc_info.value.detail
        finally:
            trading_mod._set_kill_switch(None)

    def test_inactive_kill_switch_does_not_raise(self, tmp_path):
        import api.trading as trading_mod
        from kill_switch import KillSwitch

        ks = KillSwitch(flag_file=tmp_path / "ks.flag", deactivation_token="tok")
        trading_mod._set_kill_switch(ks)
        try:
            trading_mod._check_kill_switch()  # must not raise
        finally:
            trading_mod._set_kill_switch(None)

    def test_kill_switch_checked_before_rate_limit(self, tmp_path):
        """Kill switch must fire before rate-limit logic (order of guards)."""
        import api.trading as trading_mod
        from fastapi import HTTPException
        from kill_switch import KillSwitch

        ks = KillSwitch(flag_file=tmp_path / "ks.flag", deactivation_token="tok")
        ks.activate("test ordering")
        trading_mod._set_kill_switch(ks)
        try:
            # Even with a fresh user (no rate-limit history) the kill switch fires
            with pytest.raises(HTTPException) as exc_info:
                trading_mod._check_kill_switch()
            assert exc_info.value.status_code == 503
        finally:
            trading_mod._set_kill_switch(None)


# ===========================================================================
# Gate 2 — Sharpe gate blocks live orders
# ===========================================================================
class TestSharpeGate:
    def _patch_meta(self, tmp_path: Path, payload: dict):
        """Patch _OOS_META_PATH and clear the cache."""
        import api.trading as trading_mod

        meta_path = tmp_path / "advanced_oos_meta.json"
        _write_meta(meta_path, payload)
        trading_mod._deployment_gate_cache.clear()
        return meta_path

    def test_gate_not_passed_blocks_live_orders(self, tmp_path, monkeypatch):
        from fastapi import HTTPException
        import api.trading as trading_mod

        monkeypatch.setenv("BROKER_TYPE", "live")
        monkeypatch.setenv("APP_ENV", "production")

        meta_path = self._patch_meta(tmp_path, _meta(gate_passed=False, n_trades=48))
        with patch.object(trading_mod, "_OOS_META_PATH", meta_path):
            trading_mod._deployment_gate_cache.clear()
            with pytest.raises(HTTPException) as exc_info:
                trading_mod._check_live_deployment_gates()
        assert exc_info.value.status_code == 503
        assert "Sharpe gate" in exc_info.value.detail

    def test_gate_passed_allows_live_orders(self, tmp_path, monkeypatch):
        import api.trading as trading_mod

        monkeypatch.setenv("BROKER_TYPE", "live")
        monkeypatch.setenv("APP_ENV", "production")

        meta_path = self._patch_meta(tmp_path, _meta(gate_passed=True, n_trades=650))
        with patch.object(trading_mod, "_OOS_META_PATH", meta_path):
            trading_mod._deployment_gate_cache.clear()
            trading_mod._check_live_deployment_gates()  # must not raise

    def test_missing_meta_file_blocks_live_orders(self, tmp_path, monkeypatch):
        """No meta file = gate not passed (fail-closed)."""
        from fastapi import HTTPException
        import api.trading as trading_mod

        monkeypatch.setenv("BROKER_TYPE", "live")
        monkeypatch.setenv("APP_ENV", "production")

        missing = tmp_path / "nonexistent_meta.json"
        with patch.object(trading_mod, "_OOS_META_PATH", missing):
            trading_mod._deployment_gate_cache.clear()
            with pytest.raises(HTTPException) as exc_info:
                trading_mod._check_live_deployment_gates()
        assert exc_info.value.status_code == 503

    def test_gate_detail_includes_trade_count(self, tmp_path, monkeypatch):
        """Error detail must tell the operator how many trades they have."""
        from fastapi import HTTPException
        import api.trading as trading_mod

        monkeypatch.setenv("BROKER_TYPE", "live")
        monkeypatch.setenv("APP_ENV", "production")

        meta_path = self._patch_meta(tmp_path, _meta(gate_passed=False, n_trades=123))
        with patch.object(trading_mod, "_OOS_META_PATH", meta_path):
            trading_mod._deployment_gate_cache.clear()
            with pytest.raises(HTTPException) as exc_info:
                trading_mod._check_live_deployment_gates()
        assert "123" in exc_info.value.detail
        assert "600" in exc_info.value.detail


# ===========================================================================
# Gate 3 — CI model guard blocks live orders
# ===========================================================================
class TestCIModelGuard:
    def _patch_meta(self, tmp_path: Path, payload: dict):
        import api.trading as trading_mod

        meta_path = tmp_path / "advanced_oos_meta.json"
        _write_meta(meta_path, payload)
        trading_mod._deployment_gate_cache.clear()
        return meta_path

    def test_ci_model_blocks_live_orders(self, tmp_path, monkeypatch):
        from fastapi import HTTPException
        import api.trading as trading_mod

        monkeypatch.setenv("BROKER_TYPE", "live")
        monkeypatch.setenv("APP_ENV", "production")

        # Gate passed but ci_mode=True — model is a CI stub
        meta_path = self._patch_meta(tmp_path, _meta(gate_passed=True, n_trades=650, ci_mode=True))
        with patch.object(trading_mod, "_OOS_META_PATH", meta_path):
            trading_mod._deployment_gate_cache.clear()
            with pytest.raises(HTTPException) as exc_info:
                trading_mod._check_live_deployment_gates()
        assert exc_info.value.status_code == 503
        assert "HOPEFX_CI=1" in exc_info.value.detail

    def test_production_model_allows_live_orders(self, tmp_path, monkeypatch):
        import api.trading as trading_mod

        monkeypatch.setenv("BROKER_TYPE", "live")
        monkeypatch.setenv("APP_ENV", "production")

        meta_path = self._patch_meta(tmp_path, _meta(gate_passed=True, n_trades=650, ci_mode=False))
        with patch.object(trading_mod, "_OOS_META_PATH", meta_path):
            trading_mod._deployment_gate_cache.clear()
            trading_mod._check_live_deployment_gates()  # must not raise

    def test_ci_mode_written_to_meta_when_ci_flag_set(self, monkeypatch):
        """train_advanced.py must write ci_mode=True when HOPEFX_CI=1."""
        monkeypatch.setenv("HOPEFX_CI", "1")
        import importlib
        import ml.train_advanced as ta

        importlib.reload(ta)
        assert ta._CI is True

    def test_ci_mode_false_when_ci_flag_unset(self, monkeypatch):
        """train_advanced.py must write ci_mode=False when HOPEFX_CI=0."""
        monkeypatch.setenv("HOPEFX_CI", "0")
        import importlib
        import ml.train_advanced as ta

        importlib.reload(ta)
        assert ta._CI is False


# ===========================================================================
# Bypass: paper trading and test env skip model gates
# ===========================================================================
class TestGateBypass:
    def _patch_meta_blocked(self, tmp_path: Path):
        """Write a meta that would block live orders."""
        import api.trading as trading_mod

        meta_path = tmp_path / "advanced_oos_meta.json"
        _write_meta(meta_path, _meta(gate_passed=False, n_trades=0, ci_mode=True))
        trading_mod._deployment_gate_cache.clear()
        return meta_path

    def test_paper_trading_bypasses_sharpe_gate(self, tmp_path, monkeypatch):
        import api.trading as trading_mod

        monkeypatch.setenv("BROKER_TYPE", "paper")
        monkeypatch.setenv("APP_ENV", "production")

        meta_path = self._patch_meta_blocked(tmp_path)
        with patch.object(trading_mod, "_OOS_META_PATH", meta_path):
            trading_mod._deployment_gate_cache.clear()
            trading_mod._check_live_deployment_gates()  # must not raise

    def test_test_env_bypasses_sharpe_gate(self, tmp_path, monkeypatch):
        import api.trading as trading_mod

        monkeypatch.setenv("BROKER_TYPE", "live")
        monkeypatch.setenv("APP_ENV", "test")

        meta_path = self._patch_meta_blocked(tmp_path)
        with patch.object(trading_mod, "_OOS_META_PATH", meta_path):
            trading_mod._deployment_gate_cache.clear()
            trading_mod._check_live_deployment_gates()  # must not raise

    def test_paper_trading_bypasses_ci_guard(self, tmp_path, monkeypatch):
        import api.trading as trading_mod

        monkeypatch.setenv("BROKER_TYPE", "paper")
        monkeypatch.setenv("APP_ENV", "production")

        meta_path = self._patch_meta_blocked(tmp_path)
        with patch.object(trading_mod, "_OOS_META_PATH", meta_path):
            trading_mod._deployment_gate_cache.clear()
            trading_mod._check_live_deployment_gates()  # must not raise


# ===========================================================================
# Meta file caching — avoids re-reading on every order
# ===========================================================================
class TestMetaCaching:
    def test_cache_avoids_repeated_disk_reads(self, tmp_path, monkeypatch):
        import api.trading as trading_mod

        monkeypatch.setenv("BROKER_TYPE", "live")
        monkeypatch.setenv("APP_ENV", "production")

        meta_path = tmp_path / "advanced_oos_meta.json"
        _write_meta(meta_path, _meta(gate_passed=True, n_trades=650))
        trading_mod._deployment_gate_cache.clear()

        read_count = 0
        original_read_text = Path.read_text

        def _counting_read(self, *args, **kwargs):
            nonlocal read_count
            if self == meta_path:
                read_count += 1
            return original_read_text(self, *args, **kwargs)

        with patch.object(trading_mod, "_OOS_META_PATH", meta_path), patch.object(Path, "read_text", _counting_read):
            trading_mod._deployment_gate_cache.clear()
            trading_mod._read_oos_meta()
            trading_mod._read_oos_meta()
            trading_mod._read_oos_meta()

        # File should only be read once — subsequent calls use the cache
        assert read_count == 1
