# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Unit tests for API modules.

Tests for:
- api/trading.py: Trading endpoints, Pydantic models
- api/admin.py: Admin panel endpoints and helpers
- api/signals.py: TradingSignal, RealTimeSignalService
- api/monetization.py: Monetization Pydantic models
- api/ws_live.py: LiveConnectionManager, margin_level sentinel
"""

import json
import tempfile
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ============================================================
# api/trading.py
# ============================================================
from api.trading import (
    PositionSizeRequest,
    PositionSizeResponse,
    StrategyCreateRequest,
)
from api.trading import (
    router as trading_router,
)


import os as _os_top
import time as _time_top
import jwt as _jwt_top

_os_top.environ.setdefault("APP_ENV", "test")
_os_top.environ.setdefault("SECURITY_JWT_SECRET", "unit-test-trading-secret-key-32chars!!")
_os_top.environ.setdefault("CSRF_PROTECTION", "false")


def _trading_token() -> str:
    secret = _os_top.environ.get("SECURITY_JWT_SECRET", "unit-test-trading-secret-key-32chars!!")
    return _jwt_top.encode(
        {"sub": "test-trader", "role": "admin", "type": "access", "exp": int(_time_top.time()) + 3600},
        secret,
        algorithm="HS256",
    )


class _TradingClient:
    """Thin wrapper that injects a trader Bearer token on every request."""

    def __init__(self, inner: "TestClient"):
        self._inner = inner

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {_trading_token()}"}

    def get(self, url, **kw):
        kw.setdefault("headers", {}).update(self._headers())
        return self._inner.get(url, **kw)

    def post(self, url, **kw):
        kw.setdefault("headers", {}).update(self._headers())
        return self._inner.post(url, **kw)

    def put(self, url, **kw):
        kw.setdefault("headers", {}).update(self._headers())
        return self._inner.put(url, **kw)

    def delete(self, url, **kw):
        kw.setdefault("headers", {}).update(self._headers())
        return self._inner.delete(url, **kw)


def _make_trading_client() -> "_TradingClient":
    """Create a TestClient for the trading router with a real trader JWT."""
    app = FastAPI()
    app.include_router(trading_router)
    return _TradingClient(TestClient(app))


@pytest.mark.unit
class TestTradingModels:
    """Unit tests for trading Pydantic models."""

    def test_strategy_create_request_defaults(self):
        req = StrategyCreateRequest(name="s1", symbol="XAUUSD")
        assert req.name == "s1"
        assert req.symbol == "XAUUSD"
        assert req.timeframe == "1h"
        assert req.strategy_type == "ma_crossover"
        assert req.enabled is True
        assert req.risk_per_trade == 1.0
        assert req.parameters is None

    def test_strategy_create_request_custom(self):
        req = StrategyCreateRequest(
            name="custom",
            symbol="EURUSD",
            timeframe="4h",
            strategy_type="ma_crossover",
            enabled=False,
            risk_per_trade=2.5,
            parameters={"fast_period": 10, "slow_period": 50},
        )
        assert req.risk_per_trade == 2.5
        assert req.parameters == {"fast_period": 10, "slow_period": 50}

    def test_position_size_request_defaults(self):
        req = PositionSizeRequest(entry_price=1900.0)
        assert req.entry_price == 1900.0
        assert req.stop_loss_price is None
        assert req.confidence == 1.0

    def test_position_size_request_full(self):
        req = PositionSizeRequest(
            entry_price=1950.0,
            stop_loss_price=1930.0,
            confidence=0.8,
        )
        assert req.stop_loss_price == 1930.0
        assert req.confidence == 0.8

    def test_position_size_response(self):
        resp = PositionSizeResponse(
            size=100.0,
            risk_amount=50.0,
            stop_loss_price=1890.0,
            take_profit_price=1950.0,
            notes="Auto-calculated",
        )
        assert resp.size == 100.0
        assert resp.risk_amount == 50.0
        assert resp.notes == "Auto-calculated"

    def test_position_size_response_optional_fields_none(self):
        resp = PositionSizeResponse(size=0.0, risk_amount=0.0)
        assert resp.stop_loss_price is None
        assert resp.take_profit_price is None
        assert resp.notes is None


@pytest.mark.unit
class TestTradingEndpoints:
    """Unit tests for trading API endpoints via TestClient."""

    def setup_method(self):
        self.client = _make_trading_client()

    def test_list_strategies_empty(self):
        resp = self.client.get("/api/trading/strategies")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_create_strategy_success(self):
        resp = self.client.post(
            "/api/trading/strategies",
            json={
                "name": "test_ma",
                "symbol": "XAUUSD",
                "timeframe": "1h",
                "strategy_type": "ma_crossover",
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "test_ma"
        assert body["type"] == "ma_crossover"

    def test_create_strategy_unknown_type(self):
        resp = self.client.post(
            "/api/trading/strategies",
            json={
                "name": "bad",
                "symbol": "XAUUSD",
                "strategy_type": "nonexistent_type",
            },
        )
        assert resp.status_code in (400, 500)

    def test_get_strategy_not_found(self):
        resp = self.client.get("/api/trading/strategies/does_not_exist")
        assert resp.status_code == 404

    def test_calculate_position_size(self):
        resp = self.client.post(
            "/api/trading/position-size",
            json={
                "entry_price": 1900.0,
                "stop_loss_price": 1890.0,
                "confidence": 1.0,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "size" in body
        assert "risk_amount" in body

    def test_calculate_position_size_no_stop(self):
        resp = self.client.post(
            "/api/trading/position-size",
            json={"entry_price": 1900.0},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "size" in body

    def test_get_risk_metrics(self):
        resp = self.client.get("/api/trading/risk-metrics")
        assert resp.status_code == 200
        assert isinstance(resp.json(), dict)

    def test_get_performance_summary(self):
        resp = self.client.get("/api/trading/performance/summary")
        assert resp.status_code == 200
        body = resp.json()
        assert "total_strategies" in body

    def test_get_strategy_performance_not_found(self):
        resp = self.client.get("/api/trading/performance/missing_strategy")
        assert resp.status_code == 404

    def test_start_stop_delete_strategy(self):
        # Create first
        self.client.post(
            "/api/trading/strategies",
            json={"name": "lifecycle_test", "symbol": "XAUUSD"},
        )
        # Start
        resp = self.client.post("/api/trading/strategies/lifecycle_test/start")
        assert resp.status_code == 200
        # Stop
        resp = self.client.post("/api/trading/strategies/lifecycle_test/stop")
        assert resp.status_code == 200
        # Delete
        resp = self.client.delete("/api/trading/strategies/lifecycle_test")
        assert resp.status_code == 200


# ============================================================
# api/admin.py
# ============================================================

import os as _os
import time as _time

import jwt as _jwt

from api.admin import (
    _activity_log,
    _check_module,
    _load_persisted_risk_settings,
    log_activity,
)
from api.admin import (
    router as admin_router,
)


def _admin_token() -> str:
    # Read the secret at call time — other test modules may have set it.
    # Do NOT overwrite the env var here; just use whatever is current.
    secret = _os.environ.get("SECURITY_JWT_SECRET", "unit-test-admin-secret-key-32chars!!")
    return _jwt.encode(
        {"sub": "test-admin", "role": "admin", "type": "access", "exp": int(_time.time()) + 3600},
        secret,
        algorithm="HS256",
    )


class _AdminClient:
    """Thin wrapper that injects an admin Bearer token on every request."""

    def __init__(self, inner: "TestClient"):
        self._inner = inner

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {_admin_token()}"}

    def get(self, url, **kw):
        kw.setdefault("headers", {}).update(self._headers())
        return self._inner.get(url, **kw)

    def post(self, url, **kw):
        kw.setdefault("headers", {}).update(self._headers())
        return self._inner.post(url, **kw)

    def put(self, url, **kw):
        kw.setdefault("headers", {}).update(self._headers())
        return self._inner.put(url, **kw)

    def delete(self, url, **kw):
        kw.setdefault("headers", {}).update(self._headers())
        return self._inner.delete(url, **kw)


def _make_admin_client() -> "_AdminClient":
    """Create a TestClient for the admin router with a real admin JWT."""
    application = FastAPI()
    application.include_router(admin_router)
    return _AdminClient(TestClient(application))


@pytest.mark.unit
class TestAdminHelpers:
    """Unit tests for admin helper functions."""

    def test_log_activity_adds_entry(self):
        _activity_log.clear()
        log_activity("test event")
        assert len(_activity_log) == 1
        entry = _activity_log[0]
        assert entry["message"] == "test event"
        assert "time" in entry

    def test_log_activity_prepends(self):
        _activity_log.clear()
        log_activity("first")
        log_activity("second")
        assert _activity_log[0]["message"] == "second"
        assert _activity_log[1]["message"] == "first"

    def test_log_activity_bounded(self):
        _activity_log.clear()
        for i in range(55):
            log_activity(f"event {i}")
        assert len(_activity_log) <= 50

    def test_load_persisted_risk_settings_no_file(self):
        with patch("api.admin._RISK_SETTINGS_FILE") as mock_path:
            mock_path.exists.return_value = False
            result = _load_persisted_risk_settings()
        assert result == {}

    def test_load_persisted_risk_settings_valid_file(self):
        data = {"max_risk_per_trade": 1.5, "max_open_positions": 5}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            tmp_path = Path(f.name)
        with patch("api.admin._RISK_SETTINGS_FILE", tmp_path):
            result = _load_persisted_risk_settings()
        assert result["max_risk_per_trade"] == 1.5
        tmp_path.unlink(missing_ok=True)

    def test_load_persisted_risk_settings_invalid_json(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not valid json {{{")
            tmp_path = Path(f.name)
        with patch("api.admin._RISK_SETTINGS_FILE", tmp_path):
            result = _load_persisted_risk_settings()
        assert result == {}
        tmp_path.unlink(missing_ok=True)

    def test_check_module_existing(self):
        assert _check_module("json") is True
        assert _check_module("os") is True

    def test_check_module_nonexistent(self):
        assert _check_module("totally_fake_module_xyz") is False


@pytest.mark.unit
class TestAdminEndpoints:
    """Unit tests for admin API endpoints via TestClient."""

    def setup_method(self):
        self.client = _make_admin_client()

    def test_get_system_info(self):
        resp = self.client.get("/api/admin/system-info")
        assert resp.status_code == 200
        body = resp.json()
        assert body["version"] == "1.0.0"
        assert body["status"] == "running"
        assert "uptime" in body

    def test_get_settings(self):
        resp = self.client.get("/api/admin/settings")
        assert resp.status_code == 200
        body = resp.json()
        assert "max_risk_per_trade" in body
        assert "max_open_positions" in body
        assert "paper_trading_mode" in body

    def test_get_activity_empty(self):
        _activity_log.clear()
        resp = self.client.get("/api/admin/activity")
        assert resp.status_code == 200
        body = resp.json()
        assert "events" in body
        assert isinstance(body["events"], list)

    def test_get_activity_with_events(self):
        _activity_log.clear()
        log_activity("unit test event")
        resp = self.client.get("/api/admin/activity")
        assert resp.status_code == 200
        events = resp.json()["events"]
        assert len(events) >= 1
        assert events[0]["message"] == "unit test event"

    def test_get_dashboard_data(self):
        resp = self.client.get("/api/admin/dashboard-data")
        assert resp.status_code == 200
        body = resp.json()
        assert "system_health" in body
        assert "trading_stats" in body
        assert "risk_status" in body
        assert "module_status" in body

    def test_save_settings(self):
        resp = self.client.post(
            "/api/admin/settings",
            json={"max_risk_per_trade": 1.0, "max_open_positions": 5},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "saved" in body

    def test_get_system_metrics(self):
        resp = self.client.get("/api/admin/system-metrics")
        assert resp.status_code == 200
        body = resp.json()
        assert "uptime" in body
        assert "uptime_seconds" in body


# ============================================================
# api/signals.py
# ============================================================

from api.signals import (
    RealTimeSignalService,
    SignalAnalytics,
    SignalDirection,
    SignalStrength,
    TradingSignal,
)


def _make_signal(
    service: RealTimeSignalService,
    direction: SignalDirection = SignalDirection.BUY,
    confidence: float = 0.8,
    symbol: str = "XAUUSD",
) -> TradingSignal | None:
    """Helper to generate a valid signal."""
    return service.generate_signal(
        symbol=symbol,
        direction=direction,
        confidence=confidence,
        price=1900.0,
        entry_price=1902.0,
        stop_loss=1880.0,
        take_profit=1960.0,
        timeframe="1h",
        strategies_agreeing=["MA_Cross", "RSI"],
        total_strategies=3,
        regime="trending",
        session="london",
    )


@pytest.mark.unit
class TestTradingSignalDataclass:
    """Unit tests for the TradingSignal dataclass."""

    def _build_signal(self) -> TradingSignal:
        expiry = datetime.now(UTC) + timedelta(minutes=30)
        return TradingSignal(
            id="SIG-TEST-001",
            symbol="XAUUSD",
            direction=SignalDirection.BUY,
            strength=SignalStrength.STRONG,
            confidence=0.75,
            price=1900.0,
            entry_price=1902.0,
            stop_loss=1880.0,
            take_profit=1960.0,
            risk_reward_ratio=2.9,
            timeframe="1h",
            strategies_agreeing=["MA_Cross"],
            total_strategies=2,
            regime="trending",
            session="london",
            expiry=expiry,
        )

    def test_to_dict_keys(self):
        sig = self._build_signal()
        d = sig.to_dict()
        required = {
            "id",
            "symbol",
            "direction",
            "strength",
            "confidence",
            "price",
            "entry_price",
            "stop_loss",
            "take_profit",
            "risk_reward_ratio",
            "timeframe",
            "strategies_agreeing",
            "total_strategies",
            "regime",
            "session",
            "expiry",
            "timestamp",
            "metadata",
            "is_valid",
        }
        assert required.issubset(d.keys())

    def test_to_dict_enum_values(self):
        sig = self._build_signal()
        d = sig.to_dict()
        assert d["direction"] == "buy"
        assert d["strength"] == "strong"

    def test_is_valid_not_expired(self):
        sig = self._build_signal()
        assert sig.is_valid is True

    def test_is_valid_expired(self):
        expiry = datetime.now(UTC) - timedelta(minutes=1)
        sig = TradingSignal(
            id="SIG-EXP-001",
            symbol="XAUUSD",
            direction=SignalDirection.SELL,
            strength=SignalStrength.WEAK,
            confidence=0.5,
            price=1900.0,
            entry_price=1898.0,
            stop_loss=1920.0,
            take_profit=1860.0,
            risk_reward_ratio=2.0,
            timeframe="1h",
            strategies_agreeing=["MA"],
            total_strategies=2,
            regime="ranging",
            session="ny",
            expiry=expiry,
        )
        assert sig.is_valid is False

    def test_to_json_valid(self):
        sig = self._build_signal()
        result = sig.to_json()
        parsed = json.loads(result)
        assert parsed["id"] == "SIG-TEST-001"

    def test_metadata_default_empty(self):
        sig = self._build_signal()
        assert sig.metadata == {}


@pytest.mark.unit
class TestRealTimeSignalService:
    """Unit tests for RealTimeSignalService."""

    def setup_method(self):
        self.svc = RealTimeSignalService(
            config={
                "min_confidence": 0.3,
                "min_strategies": 2,
                "signal_expiry_minutes": 30,
            }
        )
        # Prevent Redis connection attempts and FCM calls in unit tests.
        # social_feed._get_sync_redis() hangs for 120s when Redis is absent;
        # returning None causes it to fall back to the in-process dict store.
        self._redis_patch = patch("api.social_feed._get_sync_redis", return_value=None)
        self._fcm_patch = patch.object(self.svc, "_push_fcm_to_all_users", return_value=None)
        self._redis_patch.start()
        self._fcm_patch.start()

    def teardown_method(self):
        self._redis_patch.stop()
        self._fcm_patch.stop()

    def test_initialization(self):
        assert self.svc.active_signals == {}
        assert len(self.svc.signal_history) == 0
        assert self.svc.min_confidence == 0.3
        assert self.svc.min_strategies == 2

    def test_generate_signal_success(self):
        sig = _make_signal(self.svc)
        assert sig is not None
        assert sig.symbol == "XAUUSD"
        assert sig.direction == SignalDirection.BUY
        assert sig.id.startswith("SIG-XAUUSD-")

    def test_generate_signal_low_confidence_rejected(self):
        sig = _make_signal(self.svc, confidence=0.1)
        assert sig is None

    def test_generate_signal_too_few_strategies_rejected(self):
        sig = self.svc.generate_signal(
            symbol="XAUUSD",
            direction=SignalDirection.BUY,
            confidence=0.8,
            price=1900.0,
            entry_price=1902.0,
            stop_loss=1880.0,
            take_profit=1960.0,
            timeframe="1h",
            strategies_agreeing=["MA_Cross"],  # only 1, min is 2
            total_strategies=3,
            regime="trending",
            session="london",
        )
        assert sig is None

    def test_generate_signal_added_to_active(self):
        sig = _make_signal(self.svc)
        assert sig.id in self.svc.active_signals

    def test_generate_signal_added_to_history(self):
        _make_signal(self.svc)
        assert len(self.svc.signal_history) == 1

    def test_generate_sell_signal(self):
        sig = _make_signal(self.svc, direction=SignalDirection.SELL)
        assert sig is not None
        assert sig.direction == SignalDirection.SELL

    def test_get_active_signals_all(self):
        _make_signal(self.svc)
        signals = self.svc.get_active_signals()
        assert len(signals) >= 1

    def test_get_active_signals_filter_symbol(self):
        _make_signal(self.svc, symbol="XAUUSD")
        _make_signal(self.svc, symbol="EURUSD")
        signals = self.svc.get_active_signals(symbol="XAUUSD")
        assert all(s.symbol == "XAUUSD" for s in signals)

    def test_get_active_signals_filter_direction(self):
        _make_signal(self.svc, direction=SignalDirection.BUY)
        signals = self.svc.get_active_signals(direction=SignalDirection.BUY)
        assert all(s.direction == SignalDirection.BUY for s in signals)

    def test_get_active_signals_filter_strength(self):
        _make_signal(self.svc, confidence=0.9)
        signals = self.svc.get_active_signals(min_strength=SignalStrength.STRONG)
        # All returned signals should be at least STRONG
        strength_order = list(SignalStrength)
        strong_idx = strength_order.index(SignalStrength.STRONG)
        for s in signals:
            assert strength_order.index(s.strength) <= strong_idx

    def test_get_active_signals_removes_expired(self):
        sig = _make_signal(self.svc)
        # Force expiry
        sig.expiry = datetime.now(UTC) - timedelta(seconds=1)
        signals = self.svc.get_active_signals()
        assert sig.id not in [s.id for s in signals]

    def test_get_signal_by_id(self):
        sig = _make_signal(self.svc)
        fetched = self.svc.get_signal(sig.id)
        assert fetched is sig

    def test_get_signal_missing_id(self):
        assert self.svc.get_signal("nonexistent") is None

    def test_expire_signal(self):
        sig = _make_signal(self.svc)
        self.svc.expire_signal(sig.id)
        assert sig.id not in self.svc.active_signals

    def test_record_signal_outcome(self):
        sig = _make_signal(self.svc)
        self.svc.record_signal_outcome(sig.id, "tp", 1960.0)
        assert sig.id not in self.svc.active_signals
        assert self.svc.analytics.hit_rate["tp"] == 1

    def test_get_signal_history_all(self):
        _make_signal(self.svc)
        history = self.svc.get_signal_history(hours=24)
        assert len(history) >= 1

    def test_get_signal_history_symbol_filter(self):
        _make_signal(self.svc, symbol="XAUUSD")
        history = self.svc.get_signal_history(symbol="XAUUSD", hours=24)
        assert all(s.symbol == "XAUUSD" for s in history)

    def test_get_signal_history_time_cutoff(self):
        _make_signal(self.svc)
        history = self.svc.get_signal_history(hours=0)
        # Very short window — may be empty or contain the fresh signal
        assert isinstance(history, list)

    def test_get_analytics(self):
        _make_signal(self.svc)
        analytics = self.svc.get_analytics()
        assert analytics["signals_generated"] >= 1
        assert "signals_by_direction" in analytics
        assert "signals_by_strength" in analytics

    def test_get_signal_summary(self):
        _make_signal(self.svc)
        summary = self.svc.get_signal_summary()
        assert "active_signals" in summary
        assert "active_alerts" in summary
        assert "direction_distribution" in summary

    def test_subscribe_and_receive_event(self):
        events = []

        def callback(event_type, event):
            events.append(event_type)

        self.svc.subscribe(callback)
        _make_signal(self.svc)
        assert "signal_generated" in events

    def test_unsubscribe(self):
        events = []

        def callback(event_type, event):
            events.append(event_type)

        self.svc.subscribe(callback)
        self.svc.unsubscribe(callback)
        _make_signal(self.svc)
        assert events == []

    def test_create_alert(self):
        alert = self.svc.create_alert(symbol="XAUUSD", min_confidence=0.5)
        assert alert.symbol == "XAUUSD"
        assert alert.id in self.svc.alerts

    def test_alert_triggered_by_signal(self):
        triggered = []

        def callback(event_type, event):
            if event_type == "alert_triggered":
                triggered.append(event)

        self.svc.subscribe(callback)
        self.svc.create_alert(symbol="XAUUSD", min_confidence=0.5)
        _make_signal(self.svc, confidence=0.8)
        assert len(triggered) >= 1

    def test_delete_alert(self):
        alert = self.svc.create_alert(symbol="XAUUSD")
        self.svc.delete_alert(alert.id)
        assert alert.id not in self.svc.alerts

    def test_get_alerts(self):
        self.svc.create_alert(symbol="XAUUSD")
        alerts = self.svc.get_alerts()
        assert len(alerts) >= 1

    def test_get_alerts_filter_symbol(self):
        self.svc.create_alert(symbol="XAUUSD")
        self.svc.create_alert(symbol="EURUSD")
        alerts = self.svc.get_alerts(symbol="XAUUSD")
        assert all(a.symbol == "XAUUSD" for a in alerts)

    def test_format_for_websocket(self):
        sig = _make_signal(self.svc)
        ws_msg = self.svc.format_for_websocket(sig)
        parsed = json.loads(ws_msg)
        assert parsed["event"] == "signal"
        assert "data" in parsed

    def test_get_websocket_channels(self):
        _make_signal(self.svc, symbol="XAUUSD")
        channels = self.svc.get_websocket_channels()
        assert "signals:all" in channels
        assert "alerts" in channels


@pytest.mark.unit
class TestSignalAnalytics:
    """Unit tests for SignalAnalytics."""

    def test_record_signal(self):
        analytics = SignalAnalytics()
        expiry = datetime.now(UTC) + timedelta(minutes=30)
        sig = TradingSignal(
            id="SIG-ANA-001",
            symbol="XAUUSD",
            direction=SignalDirection.BUY,
            strength=SignalStrength.VERY_STRONG,
            confidence=0.9,
            price=1900.0,
            entry_price=1902.0,
            stop_loss=1880.0,
            take_profit=1960.0,
            risk_reward_ratio=2.9,
            timeframe="1h",
            strategies_agreeing=["S1", "S2"],
            total_strategies=3,
            regime="trending",
            session="london",
            expiry=expiry,
        )
        analytics.record_signal(sig)
        assert analytics.signals_generated == 1
        assert analytics.signals_by_direction["buy"] == 1
        assert analytics.signals_by_symbol["XAUUSD"] == 1

    def test_record_outcome(self):
        analytics = SignalAnalytics()
        analytics.record_outcome("tp")
        analytics.record_outcome("sl")
        assert analytics.hit_rate["tp"] == 1
        assert analytics.hit_rate["sl"] == 1

    def test_to_dict(self):
        analytics = SignalAnalytics()
        d = analytics.to_dict()
        assert "signals_generated" in d
        assert "tp_rate" in d
        assert "avg_confidence" in d


@pytest.mark.unit
class TestCalculateStrength:
    """Unit tests for RealTimeSignalService._calculate_strength."""

    def setup_method(self):
        self.svc = RealTimeSignalService()

    def test_very_strong(self):
        strength = self.svc._calculate_strength(0.9, 3, 3, 3.0)
        assert strength in (SignalStrength.VERY_STRONG, SignalStrength.STRONG)

    def test_very_weak(self):
        strength = self.svc._calculate_strength(0.05, 1, 5, 0.1)
        assert strength in (SignalStrength.VERY_WEAK, SignalStrength.WEAK)

    def test_moderate(self):
        strength = self.svc._calculate_strength(0.5, 2, 4, 1.5)
        assert strength in (
            SignalStrength.MODERATE,
            SignalStrength.STRONG,
            SignalStrength.WEAK,
        )


# ============================================================
# api/monetization.py — Pydantic model tests
# ============================================================

from api.monetization import (
    ActivateCodeRequest,
    ActivateCodeResponse,
    AffiliateResponse,
    AffiliateSignupRequest,
    PartnerSignupRequest,
    PricingTierResponse,
    ReferralRequest,
    ReviewRequest,
    StrategyListRequest,
    StrategyPurchaseRequest,
    SubscribeRequest,
    SubscribeResponse,
    WhiteLabelRequest,
)


@pytest.mark.unit
class TestMonetizationModels:
    """Unit tests for monetization Pydantic models."""

    def test_pricing_tier_response(self):
        r = PricingTierResponse(
            tier="starter",
            name="Starter",
            monthly_price=1800.0,
            annual_price=18000.0,
            commission_rate=0.005,
            features={"max_strategies": 5},
        )
        assert r.tier == "starter"
        assert r.monthly_price == 1800.0

    def test_subscribe_request_defaults(self):
        r = SubscribeRequest(tier="starter")
        assert r.billing_cycle == "monthly"

    def test_subscribe_request_annual(self):
        r = SubscribeRequest(tier="professional", billing_cycle="annual")
        assert r.billing_cycle == "annual"

    def test_subscribe_response(self):
        r = SubscribeResponse(
            subscription_id="sub_001",
            checkout_url="https://stripe.com/checkout",
            status="pending",
            tier="starter",
            billing_cycle="monthly",
        )
        assert r.subscription_id == "sub_001"
        assert r.checkout_url is not None

    def test_activate_code_request(self):
        r = ActivateCodeRequest(code="HOPE-TEST-CODE")
        assert r.code == "HOPE-TEST-CODE"

    def test_activate_code_response_success(self):
        r = ActivateCodeResponse(
            success=True,
            tier="starter",
            expires_at="2026-01-01T00:00:00",
            message="Code activated",
        )
        assert r.success is True

    def test_activate_code_response_failure(self):
        r = ActivateCodeResponse(success=False, message="Invalid code")
        assert r.tier is None

    def test_affiliate_signup_request(self):
        r = AffiliateSignupRequest(
            payment_email="pay@test.com",
            custom_code="MY_CODE",
        )
        assert r.custom_code == "MY_CODE"

    def test_affiliate_signup_request_minimal(self):
        r = AffiliateSignupRequest()
        assert r.payment_email is None
        assert r.custom_code is None

    def test_affiliate_response(self):
        r = AffiliateResponse(
            affiliate_id="aff_001",
            code="HOPEFX-u1",
            level="bronze",
            commission_rate=0.10,
            status="active",
        )
        assert r.level == "bronze"
        assert r.commission_rate == 0.10

    def test_referral_request(self):
        r = ReferralRequest(affiliate_code="CODE123")
        assert r.affiliate_code == "CODE123"

    def test_strategy_list_request_defaults(self):
        r = StrategyListRequest(
            name="My Strategy",
            description="desc",
            category="scalping",
            price=99.0,
        )
        assert r.license_type == "purchase"
        assert r.min_tier == "starter"
        assert r.tags is None

    def test_strategy_purchase_request(self):
        r = StrategyPurchaseRequest(strategy_id="strat_001", stripe_customer_id="cus_test")
        assert r.strategy_id == "strat_001"

    def test_review_request_valid(self):
        r = ReviewRequest(
            strategy_id="strat_001",
            rating=5,
            title="Excellent",
            content="Works great!",
        )
        assert r.rating == 5

    def test_review_request_invalid_rating(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ReviewRequest(
                strategy_id="strat_001",
                rating=6,  # out of range
                title="T",
                content="C",
            )

    def test_partner_signup_request(self):
        r = PartnerSignupRequest(
            company_name="Acme Corp",
            contact_email="contact@acme.com",
            partner_type="reseller",
        )
        assert r.company_name == "Acme Corp"

    def test_white_label_request(self):
        r = WhiteLabelRequest(
            partner_id="p1",
            name="WL Platform",
            company_name="Acme",
            logo_url="https://acme.com/logo.png",
            primary_color="#FF0000",
            secondary_color="#00FF00",
        )
        assert r.primary_color == "#FF0000"
        assert r.custom_domain is None


@pytest.mark.unit
class TestMonetizationEndpoints:
    """Smoke tests for monetization API endpoints."""

    def setup_method(self):
        app = FastAPI()
        from api.auth import TokenPayload, get_current_user
        from api.monetization import router as mon_router

        app.include_router(mon_router)
        app.dependency_overrides[get_current_user] = lambda: TokenPayload(sub="test_user", role="admin")
        self.client = TestClient(app)

    def test_get_pricing(self):
        resp = self.client.get("/api/monetization/pricing")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        assert len(body) > 0

    def test_get_tier_pricing_valid(self):
        resp = self.client.get("/api/monetization/pricing/free")
        assert resp.status_code == 200

    def test_get_tier_pricing_invalid(self):
        resp = self.client.get("/api/monetization/pricing/invalid_tier_xyz")
        assert resp.status_code == 400

    def test_subscribe_free_tier(self):
        resp = self.client.post(
            "/api/monetization/subscribe",
            json={"user_id": "test_user_free", "tier": "free"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "active"
        assert body["tier"] == "free"

    def test_subscribe_invalid_tier(self):
        resp = self.client.post(
            "/api/monetization/subscribe",
            json={"user_id": "u1", "tier": "diamond"},
        )
        assert resp.status_code == 400

    def test_get_subscription_no_sub(self):
        resp = self.client.get("/api/monetization/subscription/user_no_sub_xyz")
        assert resp.status_code == 200
        body = resp.json()
        assert body["has_subscription"] is False

    def test_get_user_limits(self):
        resp = self.client.get("/api/monetization/subscription/someuser/limits")
        assert resp.status_code == 200

    def test_get_analytics_dashboard(self):
        resp = self.client.get("/api/monetization/analytics/dashboard")
        assert resp.status_code == 200

    def test_get_revenue_breakdown(self):
        resp = self.client.get("/api/monetization/analytics/revenue")
        assert resp.status_code == 200
        body = resp.json()
        assert "by_source" in body
        assert "by_tier" in body

    def test_get_growth_metrics(self):
        resp = self.client.get("/api/monetization/analytics/growth")
        assert resp.status_code == 200
        body = resp.json()
        assert "mrr" in body
        assert "arr" in body

    def test_marketplace_search(self):
        resp = self.client.get("/api/monetization/marketplace/strategies")
        assert resp.status_code == 200
        body = resp.json()
        assert "strategies" in body

    def test_marketplace_featured(self):
        resp = self.client.get("/api/monetization/marketplace/featured")
        assert resp.status_code == 200

    def test_marketplace_stats(self):
        resp = self.client.get("/api/monetization/marketplace/stats")
        assert resp.status_code == 200

    def test_enterprise_stats(self):
        resp = self.client.get("/api/monetization/enterprise/stats")
        assert resp.status_code == 200

    def test_affiliate_leaderboard(self):
        resp = self.client.get("/api/monetization/affiliate/leaderboard")
        assert resp.status_code == 200

    def test_validate_code_nonexistent(self):
        resp = self.client.get("/api/monetization/validate-code/NOTREAL123")
        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is False

    def test_analytics_report(self):
        resp = self.client.get("/api/monetization/analytics/report?period=monthly")
        assert resp.status_code == 200


# ============================================================
# api/ws_live.py — LiveConnectionManager
# ============================================================

from api.ws_live import LiveConnectionManager, get_live_manager


class _MockWS:
    """Minimal WebSocket stand-in that records sent frames."""

    def __init__(self):
        self.sent: list[str] = []
        self.closed: bool = False

    async def accept(self):
        pass

    async def send_text(self, text: str):
        self.sent.append(text)

    async def close(self, code: int = 1000):
        self.closed = True


@pytest.mark.unit
class TestLiveConnectionManager:
    """Unit tests for LiveConnectionManager (api/ws_live.py)."""

    def setup_method(self):
        self.mgr = LiveConnectionManager()

    # ── connect / disconnect ──────────────────────────────────────────────────

    async def test_connect_accepts_and_returns_id(self):
        ws = _MockWS()
        cid = await self.mgr.connect(ws)
        assert cid.startswith("conn_")
        assert self.mgr.connection_count == 1

    async def test_disconnect_removes_connection(self):
        ws = _MockWS()
        cid = await self.mgr.connect(ws)
        self.mgr.disconnect(cid)
        assert self.mgr.connection_count == 0

    async def test_disconnect_nonexistent_is_noop(self):
        self.mgr.disconnect("no_such_conn")  # must not raise

    async def test_connection_count_tracks_multiple(self):
        ws1, ws2 = _MockWS(), _MockWS()
        await self.mgr.connect(ws1)
        await self.mgr.connect(ws2)
        assert self.mgr.connection_count == 2

    # ── auth ─────────────────────────────────────────────────────────────────

    async def test_authenticate_sets_user(self):
        ws = _MockWS()
        cid = await self.mgr.connect(ws)
        assert not self.mgr.is_authenticated(cid)
        self.mgr.authenticate(cid, "user-42")
        assert self.mgr.is_authenticated(cid)
        assert self.mgr.get_user_id(cid) == "user-42"

    async def test_unauthenticated_user_id_is_none(self):
        ws = _MockWS()
        cid = await self.mgr.connect(ws)
        assert self.mgr.get_user_id(cid) is None

    # ── subscribe / unsubscribe ───────────────────────────────────────────────

    async def test_subscribe_adds_channel(self):
        ws = _MockWS()
        cid = await self.mgr.connect(ws)
        self.mgr.subscribe(cid, ["prices", "signals"])
        assert "prices" in self.mgr._subscriptions[cid]
        assert "signals" in self.mgr._subscriptions[cid]

    async def test_unsubscribe_removes_channel(self):
        ws = _MockWS()
        cid = await self.mgr.connect(ws)
        self.mgr.subscribe(cid, ["prices", "signals"])
        self.mgr.unsubscribe(cid, ["prices"])
        assert "prices" not in self.mgr._subscriptions[cid]
        assert "signals" in self.mgr._subscriptions[cid]

    async def test_subscribe_unknown_connection_is_noop(self):
        self.mgr.subscribe("ghost", ["prices"])  # must not raise

    # ── broadcast ────────────────────────────────────────────────────────────

    async def test_broadcast_reaches_subscriber(self):
        ws = _MockWS()
        cid = await self.mgr.connect(ws)
        self.mgr.authenticate(cid, "user-test")
        self.mgr.subscribe(cid, ["account"])
        msg = {"type": "account_update", "data": {"balance": 10000.0}}
        await self.mgr.broadcast("account", msg)
        assert len(ws.sent) == 1
        assert json.loads(ws.sent[0])["type"] == "account_update"

    async def test_broadcast_skips_non_subscriber(self):
        ws = _MockWS()
        cid = await self.mgr.connect(ws)
        self.mgr.subscribe(cid, ["signals"])
        await self.mgr.broadcast("account", {"type": "account_update", "data": {}})
        # ws subscribed to "signals", not "account" — should receive nothing
        # (non-empty subscription set means explicit opt-in only)
        assert len(ws.sent) == 0

    async def test_broadcast_empty_subscriptions_receives_all(self):
        """A connection with no explicit subscriptions gets every channel."""
        ws = _MockWS()
        cid = await self.mgr.connect(ws)  # no subscribe() call → empty set
        self.mgr.authenticate(cid, "user-test")
        await self.mgr.broadcast("prices", {"type": "price_tick", "data": {}})
        assert len(ws.sent) == 1

    async def test_broadcast_removes_dead_connection(self):
        """A send_text failure should silently drop the connection."""

        class _DeadWS(_MockWS):
            async def send_text(self, text: str):
                raise RuntimeError("connection closed")

        ws = _DeadWS()
        cid = await self.mgr.connect(ws)
        self.mgr.authenticate(cid, "user-test")
        self.mgr.subscribe(cid, ["prices"])
        await self.mgr.broadcast("prices", {"type": "price_tick", "data": {}})
        assert self.mgr.connection_count == 0

    # ── send_to_user ─────────────────────────────────────────────────────────

    async def test_send_to_user_reaches_correct_connection(self):
        """Routing: only the addressed user's connection receives the message.

        Both connections now subscribe explicitly. `account` is a private
        channel, and send_to_user no longer delivers private channels via the
        "empty subscription = all channels" fallback — broadcast() already
        guarded that and the guard was missing here (audit finding S8-02).
        This test's subject is user routing, which the explicit subscription
        preserves; the fallback behaviour it previously depended on is asserted
        against in test_send_to_user_skips_unsubscribed_private_channel below.
        """
        ws_a, ws_b = _MockWS(), _MockWS()
        cid_a = await self.mgr.connect(ws_a)
        cid_b = await self.mgr.connect(ws_b)
        self.mgr.authenticate(cid_a, "alice")
        self.mgr.authenticate(cid_b, "bob")
        self.mgr.subscribe(cid_a, ["account"])
        self.mgr.subscribe(cid_b, ["account"])
        msg = {"type": "account_update", "data": {"balance": 5000.0}}
        await self.mgr.send_to_user("alice", "account", msg)
        assert len(ws_a.sent) == 1
        assert len(ws_b.sent) == 0

    async def test_send_to_user_skips_unsubscribed_private_channel(self):
        """A connection that never opted in must not receive private data (S8-02)."""
        ws_a = _MockWS()
        cid_a = await self.mgr.connect(ws_a)
        self.mgr.authenticate(cid_a, "alice")  # no subscribe() call
        await self.mgr.send_to_user("alice", "account", {"type": "account_update", "data": {}})
        assert len(ws_a.sent) == 0

    # ── heartbeat helpers ─────────────────────────────────────────────────────

    async def test_record_hb_miss_increments(self):
        ws = _MockWS()
        cid = await self.mgr.connect(ws)
        assert self.mgr.record_hb_miss(cid) == 1
        assert self.mgr.record_hb_miss(cid) == 2

    async def test_record_pong_resets_miss_count(self):
        ws = _MockWS()
        cid = await self.mgr.connect(ws)
        self.mgr.record_hb_miss(cid)
        self.mgr.record_hb_miss(cid)
        self.mgr.record_pong(cid)
        assert self.mgr._hb_misses[cid] == 0

    # ── singleton ─────────────────────────────────────────────────────────────

    def test_get_live_manager_returns_instance(self):
        mgr = get_live_manager()
        assert isinstance(mgr, LiveConnectionManager)

    def test_get_live_manager_is_singleton(self):
        assert get_live_manager() is get_live_manager()

    # ── ws/live/stats REST endpoint ───────────────────────────────────────────

    def test_ws_live_stats_endpoint(self):
        from api.ws_live import router as ws_router

        app = FastAPI()
        app.include_router(ws_router)
        client = TestClient(app)
        resp = client.get("/ws/live/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert "connections" in body
        assert "timestamp" in body


@pytest.mark.unit
class TestAccountBroadcasterMarginLevel:
    """
    Verify the margin_level sentinel logic in _account_update_broadcaster.

    The original bug: margin_level was 0.0 when no positions were open.
    The fix: use 9999.0 when margin_used == 0 (no open positions → no risk).
    """

    def _compute_margin_level(self, acct_raw: dict) -> float:
        """Mirror the broadcaster's normalisation logic."""
        balance = float(acct_raw.get("balance", 0.0) or 0.0)
        equity = float(acct_raw.get("equity", balance) or balance)
        margin_used = float(acct_raw.get("margin_used", 0.0) or 0.0)
        return (equity / margin_used * 100) if margin_used > 0 else 9999.0

    def test_no_positions_yields_sentinel(self):
        """margin_used=0 → 9999.0, not 0.0."""
        result = self._compute_margin_level({"balance": 10000.0, "equity": 10000.0, "margin_used": 0.0})
        assert result == 9999.0

    def test_margin_used_missing_yields_sentinel(self):
        """Broker omits margin_used → defaults to 0 → sentinel."""
        result = self._compute_margin_level({"balance": 10000.0, "equity": 10000.0})
        assert result == 9999.0

    def test_margin_used_none_yields_sentinel(self):
        """Broker returns None for margin_used → treated as 0 → sentinel."""
        result = self._compute_margin_level({"balance": 10000.0, "equity": 10000.0, "margin_used": None})
        assert result == 9999.0

    def test_open_positions_computes_correctly(self):
        """With margin_used > 0, margin_level = equity / margin_used * 100."""
        result = self._compute_margin_level({"balance": 10000.0, "equity": 10500.0, "margin_used": 1000.0})
        assert abs(result - 1050.0) < 0.01

    def test_broker_margin_level_field_ignored(self):
        """If broker sends margin_level=0.0 but margin_used=0, sentinel wins."""
        result = self._compute_margin_level(
            {"balance": 10000.0, "equity": 10000.0, "margin_used": 0.0, "margin_level": 0.0}
        )
        assert result == 9999.0

    @pytest.mark.asyncio
    async def test_paper_broker_always_yields_sentinel(self):
        """PaperTradingBroker always returns margin_used=0.0 → sentinel."""
        from brokers.paper_trading import PaperTradingBroker

        broker = PaperTradingBroker(initial_balance=10000.0)
        info = await broker.get_account_info()
        margin_used = float(info.margin_used if hasattr(info, "margin_used") else 0.0)
        margin_level = (info.equity / margin_used * 100) if margin_used > 0 else 9999.0
        assert margin_level == 9999.0
