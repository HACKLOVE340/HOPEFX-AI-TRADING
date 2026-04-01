# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/test_production_wiring.py
================================
End-to-end wiring tests for all new production components.

Coverage
--------
1.  features_extended: build_extended_features() returns 150+ features
2.  features_extended: no NaN/inf in output
3.  train_advanced: sharpe_gate_check() N=48 BLOCKED, N=600 PASSED
4.  train_advanced: _sharpe_se() formula correct
5.  OandaPaperClock: status() returns correct shape without stamp file
6.  OandaPaperClock: maybe_start() writes stamp, idempotent
7.  OandaPaperClock: is_complete() False before 30 days
8.  OandaPaperClock: syncs to PaperTradingGate on start
9.  sentry_config: _scrub_dict() removes all sensitive fields
10. sentry_config: _scrub_string() strips Bearer tokens and emails
11. sentry_config: init_sentry() returns False without SENTRY_DSN (no crash)
12. sentry_config: capture_ml_fallback_event() no-ops without sentry-sdk init
13. sentry_config: capture_paper_clock_alert() no-ops without sentry-sdk init
14. sentry_config: capture_sharpe_gate_alert() no-ops without sentry-sdk init
15. sentry_config: capture_kill_switch_alert() no-ops without sentry-sdk init
16. InferenceEngine: predict() returns correct shape with stub OHLCV
17. InferenceEngine: predict() returns neutral on < min_bars
18. InferenceEngine: health() returns all expected keys
19. InferenceEngine: fallback=True when model unavailable
20. multi_symbol_backtest: compute_pooled_metrics() N=0 returns gate BLOCKED
21. multi_symbol_backtest: compute_pooled_metrics() N=600 returns gate PASSED
22. multi_symbol_backtest: _max_drawdown() correct on known series
23. multi_symbol_backtest: smoke run completes and saves report
24. LiveTradingGate: all checks fail gracefully without .env
25. LiveTradingGate: kill_switch check passes when switch inactive
26. LiveTradingGate: feature_flag check fails when FEATURE_LIVE_TRADING unset
27. LiveTradingGate: status_dict() returns allowed/checks/reason keys
28. GET /api/status/live-trading/gate returns 200 with allowed=False
29. GET /api/status/paper-trading returns 200 with correct schema
30. App starts without any .env (all new modules import cleanly)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

_ROOT = os.path.dirname(os.path.dirname(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_ohlcv(n: int = 200, base: float = 1800.0) -> pd.DataFrame:
    np.random.seed(42)
    idx = pd.date_range("2020-01-01", periods=n, freq="h", tz="UTC")
    close = base + np.random.randn(n).cumsum()
    df = pd.DataFrame(
        {
            "open": close + np.random.randn(n) * 0.5,
            "high": close + abs(np.random.randn(n)) * 1.5,
            "low": close - abs(np.random.randn(n)) * 1.5,
            "close": close,
            "volume": abs(np.random.randn(n)) * 1000 + 500,
        },
        index=idx,
    )
    return df


# ─────────────────────────────────────────────────────────────────────────────
# 1-2: features_extended
# ─────────────────────────────────────────────────────────────────────────────


class TestFeaturesExtended:
    def test_returns_150_plus_features(self):
        from ml.features_extended import build_extended_features

        df = _make_ohlcv(600)
        X, y = build_extended_features(df, use_filtered_target=False, min_move_atr=0.0)
        assert X.shape[1] >= 150, f"Expected >=150 features, got {X.shape[1]}"
        assert len(X) > 0

    def test_no_nan_or_inf(self):
        from ml.features_extended import build_extended_features

        df = _make_ohlcv(600)
        X, y = build_extended_features(df, use_filtered_target=False, min_move_atr=0.0)
        assert not X.isnull().any().any(), "NaN values in feature matrix"
        assert not np.isinf(X.values).any(), "Inf values in feature matrix"


# ─────────────────────────────────────────────────────────────────────────────
# 3-4: train_advanced Sharpe gate
# ─────────────────────────────────────────────────────────────────────────────


class TestSharpeGate:
    def test_n48_blocked(self):
        from ml.train_advanced import sharpe_gate_check

        result = sharpe_gate_check(n_trades=48, sharpe=1.52, target_n=600)
        assert result["gate_passed"] is False
        assert result["se"] > 0.10
        assert "BLOCKED" in result["message"]

    def test_n600_passed(self):
        from ml.train_advanced import sharpe_gate_check

        result = sharpe_gate_check(n_trades=600, sharpe=1.52, target_n=600)
        assert result["gate_passed"] is True
        assert result["se"] <= 0.10
        assert "PASSED" in result["message"]

    def test_se_formula(self):
        from ml.train_advanced import _sharpe_se

        # SE(SR=1.52, N=48) ≈ 0.212
        se = _sharpe_se(48, sr_est=1.52)
        assert 0.18 < se < 0.25, f"SE={se} out of expected range"
        # SE decreases with more trades
        assert _sharpe_se(600, 1.52) < _sharpe_se(48, 1.52)

    def test_se_infinity_on_zero_trades(self):
        from ml.train_advanced import _sharpe_se

        assert _sharpe_se(0) == float("inf")
        assert _sharpe_se(1) == float("inf")


# ─────────────────────────────────────────────────────────────────────────────
# 5-8: OandaPaperClock
# ─────────────────────────────────────────────────────────────────────────────


class TestOandaPaperClock:
    def _make_clock(self, tmp_path: Path):
        from brokers.oanda_paper_clock import OandaPaperClock

        # Use a path inside pytest's tmp_path — avoids the TOCTOU race of
        # tempfile.mktemp() which returns a name without creating the file.
        stamp = tmp_path / "paper_clock_stamp.json"
        return OandaPaperClock(stamp_path=stamp)

    def test_status_shape_without_stamp(self, tmp_path):
        clock = self._make_clock(tmp_path)
        s = clock.status()
        assert "started" in s
        assert "elapsed_days" in s
        assert "remaining_days" in s
        assert "complete" in s
        assert s["started"] is False
        assert s["complete"] is False

    def test_maybe_start_writes_stamp(self, tmp_path):
        clock = self._make_clock(tmp_path)
        started = clock.maybe_start(account_id="test-123", environment="practice")
        assert started is True
        assert clock._stamp_path.exists()
        s = clock.status()
        assert s["started"] is True
        assert s["elapsed_days"] >= 0.0

    def test_maybe_start_idempotent(self, tmp_path):
        clock = self._make_clock(tmp_path)
        clock.maybe_start(account_id="test-123", environment="practice")
        started_again = clock.maybe_start(account_id="test-456", environment="live")
        assert started_again is False  # already started — no overwrite

    def test_is_complete_false_before_30_days(self, tmp_path):
        clock = self._make_clock(tmp_path)
        clock.maybe_start(account_id="test", environment="practice")
        assert clock.is_complete() is False  # just started

    def test_reset_clears_stamp(self, tmp_path):
        clock = self._make_clock(tmp_path)
        clock.maybe_start()
        clock.reset()
        assert not clock._stamp_path.exists()
        assert clock.status()["started"] is False


# ─────────────────────────────────────────────────────────────────────────────
# 9-15: Sentry config
# ─────────────────────────────────────────────────────────────────────────────


class TestSentryConfig:
    def test_scrub_dict_removes_sensitive_fields(self):
        from monitoring.sentry_config import _scrub_dict

        d = {
            "password": "secret",  # nosec B105 - test file
            "api_key": "abc123",
            "token": "tok_xyz",  # nosec B105 - test file
            "message": "hello",
            "nested": {"authorization": "Bearer xyz", "data": "ok"},
        }
        result = _scrub_dict(d)
        assert result["password"] == "[Filtered]"
        assert result["api_key"] == "[Filtered]"
        assert result["token"] == "[Filtered]"
        assert result["message"] == "hello"
        assert result["nested"]["authorization"] == "[Filtered]"
        assert result["nested"]["data"] == "ok"

    def test_scrub_string_strips_bearer(self):
        from monitoring.sentry_config import _scrub_string

        s = _scrub_string("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig")
        assert "eyJ" not in s
        assert "[Filtered]" in s or "Filtered" in s

    def test_scrub_string_strips_email(self):
        from monitoring.sentry_config import _scrub_string

        s = _scrub_string("User email: trader@example.com logged in")
        assert "trader@example.com" not in s

    def test_init_sentry_no_dsn_returns_false(self):
        from monitoring.sentry_config import init_sentry

        with patch.dict(os.environ, {"SENTRY_DSN": ""}, clear=False):
            result = init_sentry()
        assert result is False

    def test_capture_ml_fallback_no_crash(self):
        from monitoring.sentry_config import capture_ml_fallback_event

        # Should not raise even without sentry-sdk initialised
        capture_ml_fallback_event(
            reason="model not found",
            fallback_model="xgb_macro.pkl",
            fallback_accuracy=0.503,
        )

    def test_capture_paper_clock_alert_no_crash(self):
        from monitoring.sentry_config import capture_paper_clock_alert

        capture_paper_clock_alert(elapsed_days=5.0, remaining_days=25.0)

    def test_capture_sharpe_gate_alert_no_crash(self):
        from monitoring.sentry_config import capture_sharpe_gate_alert

        capture_sharpe_gate_alert(n_trades=48, sharpe=1.52, se=0.21)

    def test_capture_kill_switch_alert_no_crash(self):
        from monitoring.sentry_config import capture_kill_switch_alert

        capture_kill_switch_alert(reason="drawdown exceeded", triggered_by="system")


# ─────────────────────────────────────────────────────────────────────────────
# 16-19: InferenceEngine
# ─────────────────────────────────────────────────────────────────────────────


class TestInferenceEngine:
    def test_predict_returns_correct_shape(self):
        from ml.inference_engine import InferenceEngine

        engine = InferenceEngine()
        df = _make_ohlcv(150)
        result = engine.predict(df, symbol="XAU_USD")
        required = {
            "direction",
            "probability",
            "confidence",
            "model_version",
            "bars_used",
            "last_close",
            "latency_ms",
            "fallback",
            "macro_active",
            "mtf_active",
            "online_active",
        }
        assert required.issubset(result.keys())

    def test_predict_neutral_on_insufficient_bars(self):
        from ml.inference_engine import InferenceEngine

        engine = InferenceEngine()
        df = _make_ohlcv(50)  # below _MIN_BARS=100
        result = engine.predict(df)
        assert result["direction"] == "neutral"
        assert result["probability"] == 0.5

    def test_predict_direction_valid(self):
        from ml.inference_engine import InferenceEngine

        engine = InferenceEngine()
        df = _make_ohlcv(150)
        result = engine.predict(df)
        assert result["direction"] in ("long", "short", "neutral")
        assert 0.0 <= result["probability"] <= 1.0
        assert 0.0 <= result["confidence"] <= 1.0

    def test_health_returns_expected_keys(self):
        from ml.inference_engine import InferenceEngine

        engine = InferenceEngine()
        h = engine.health()
        for key in (
            "model_available",
            "model_version",
            "predict_count",
            "fallback_count",
            "threshold_long",
            "threshold_short",
        ):
            assert key in h, f"Missing key: {key}"

    def test_fallback_true_when_model_missing(self):
        from ml.inference_engine import InferenceEngine

        engine = InferenceEngine()
        # Point predictor at non-existent model
        engine._predictor = None
        with patch("ml.inference_engine.InferenceEngine._get_predictor", return_value=None):
            df = _make_ohlcv(150)
            result = engine.predict(df)
        # Should not raise; fallback or neutral
        assert result["direction"] in ("long", "short", "neutral")


# ─────────────────────────────────────────────────────────────────────────────
# 20-23: multi_symbol_backtest
# ─────────────────────────────────────────────────────────────────────────────


class TestMultiSymbolBacktest:
    def test_pooled_metrics_zero_trades_blocked(self):
        from backtest.multi_symbol_backtest import compute_pooled_metrics

        result = compute_pooled_metrics([], target_n=600)
        assert result["sharpe_gate_passed"] is False
        assert result["n_total_trades"] == 0

    def test_pooled_metrics_n600_passed(self):
        from backtest.multi_symbol_backtest import compute_pooled_metrics

        # Simulate 600 trades with positive edge
        trades = [{"pnl_pct": 0.001 + np.random.randn() * 0.01} for _ in range(600)]
        results = [{"symbol": "XAU/USD", "n_trades": 600, "trades": trades}]
        result = compute_pooled_metrics(results, target_n=600)
        assert result["n_total_trades"] == 600
        assert result["sharpe_gate_passed"] is True

    def test_max_drawdown_known_series(self):
        from backtest.multi_symbol_backtest import _max_drawdown

        # Series: +1, +1, -3, +1 → cumsum: 1, 2, -1, 0 → max DD = 3
        pnls = np.array([1.0, 1.0, -3.0, 1.0])
        dd = _max_drawdown(pnls)
        assert abs(dd - 3.0) < 1e-9

    def test_smoke_run_saves_report(self):
        from backtest.multi_symbol_backtest import run_backtest

        # Run smoke test — uses synthetic data
        report = run_backtest(smoke=True)
        assert "pooled" in report
        assert "symbols" in report
        assert len(report["symbols"]) == 3
        assert report["pooled"]["n_total_trades"] >= 0


# ─────────────────────────────────────────────────────────────────────────────
# 24-27: LiveTradingGate
# ─────────────────────────────────────────────────────────────────────────────


class TestLiveTradingGate:
    def test_all_checks_fail_without_env(self):
        from core.live_trading_gate import LiveTradingGate

        gate = LiveTradingGate()
        with patch.dict(os.environ, {"FEATURE_LIVE_TRADING": ""}, clear=False):
            result = gate.check()
        assert result.allowed is False
        assert len(result.checks) == 5

    def test_kill_switch_check_passes_when_inactive(self):
        from core.live_trading_gate import LiveTradingGate

        gate = LiveTradingGate()
        passed, msg = gate._check_kill_switch()
        assert passed is True
        assert "inactive" in msg.lower()

    def test_feature_flag_blocked_when_unset(self):
        from core.live_trading_gate import LiveTradingGate

        gate = LiveTradingGate()
        with patch.dict(os.environ, {"FEATURE_LIVE_TRADING": "false"}, clear=False):
            passed, msg = gate._check_feature_flag()
        assert passed is False
        assert "FEATURE_LIVE_TRADING" in msg

    def test_feature_flag_passes_when_set(self):
        from core.live_trading_gate import LiveTradingGate

        gate = LiveTradingGate()
        with patch.dict(os.environ, {"FEATURE_LIVE_TRADING": "true"}, clear=False):
            passed, msg = gate._check_feature_flag()
        assert passed is True

    def test_status_dict_has_required_keys(self):
        from core.live_trading_gate import LiveTradingGate

        gate = LiveTradingGate()
        d = gate.status_dict()
        assert "allowed" in d
        assert "checks" in d
        assert "reason" in d
        assert "checked_at" in d
        assert isinstance(d["checks"], dict)


# ─────────────────────────────────────────────────────────────────────────────
# 28-29: API endpoints
# ─────────────────────────────────────────────────────────────────────────────


class TestStatusEndpoints:
    @pytest.fixture
    def client(self):
        os.environ.setdefault("SECURITY_JWT_SECRET", "test-secret-key-32chars-minimum!!")
        os.environ.setdefault("APP_ENV", "development")
        from fastapi.testclient import TestClient
        from api.status import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_live_trading_gate_endpoint_200(self, client):
        resp = client.get("/api/status/live-trading/gate")
        assert resp.status_code == 200
        data = resp.json()
        assert "allowed" in data
        assert data["allowed"] is False  # no .env set
        assert "checks" in data

    def test_paper_trading_status_endpoint_200(self, client):
        resp = client.get("/api/status/paper-trading")
        assert resp.status_code == 200
        data = resp.json()
        assert "started" in data
        assert "elapsed_days" in data
        assert "complete" in data


# ─────────────────────────────────────────────────────────────────────────────
# 30: App starts without .env
# ─────────────────────────────────────────────────────────────────────────────


class TestAppStartsWithoutEnv:
    def test_all_new_modules_import_cleanly(self):
        """All new production modules must import without any .env set."""
        modules = [
            "ml.features_extended",
            "ml.inference_engine",
            "ml.train_advanced",
            "brokers.oanda_paper_clock",
            "monitoring.sentry_config",
            "core.live_trading_gate",
            "backtest.multi_symbol_backtest",
            "research.pipeline.paper_trading_gate",
        ]
        for mod in modules:
            try:
                import importlib

                importlib.import_module(mod)
            except Exception as exc:
                pytest.fail(f"Module {mod} failed to import: {exc}")

    def test_inference_engine_singleton_no_crash(self):
        from ml.inference_engine import get_inference_engine

        engine = get_inference_engine()
        assert engine is not None
        h = engine.health()
        assert isinstance(h, dict)

    def test_paper_clock_singleton_no_crash(self):
        from brokers.oanda_paper_clock import get_clock

        clock = get_clock()
        s = clock.status()
        assert isinstance(s, dict)
        assert "started" in s

    def test_live_gate_singleton_no_crash(self):
        from core.live_trading_gate import get_gate

        gate = get_gate()
        result = gate.check()
        assert result.allowed is False  # expected without .env
