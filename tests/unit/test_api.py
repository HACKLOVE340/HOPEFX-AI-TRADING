"""
Unit tests for API modules.

Tests for:
- api/trading.py: Trading endpoints, Pydantic models
- api/admin.py: Admin panel endpoints and helpers
- api/signals.py: TradingSignal, RealTimeSignalService
- api/monetization.py: Monetization Pydantic models
- api/websocket_server.py: WebSocketManager, WebSocketMessage
"""

import json
import pytest
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

# ============================================================
# api/trading.py
# ============================================================

from api.trading import (
    StrategyCreateRequest,
    StrategyResponse,
    SignalResponse,
    PositionSizeRequest,
    PositionSizeResponse,
    router as trading_router,
)


def _make_trading_client() -> TestClient:
    """Create a TestClient for the trading router."""
    app = FastAPI()
    app.include_router(trading_router)
    return TestClient(app)


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

from api.admin import (
    log_activity,
    _load_persisted_risk_settings,
    _check_module,
    _activity_log,
    router as admin_router,
)


def _make_admin_client() -> TestClient:
    """Create a TestClient for the admin router."""
    app = FastAPI()
    app.include_router(admin_router)
    return TestClient(app)


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
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(data, f)
            tmp_path = Path(f.name)
        with patch("api.admin._RISK_SETTINGS_FILE", tmp_path):
            result = _load_persisted_risk_settings()
        assert result["max_risk_per_trade"] == 1.5
        tmp_path.unlink(missing_ok=True)

    def test_load_persisted_risk_settings_invalid_json(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
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
        resp = self.client.get("/admin/api/system-info")
        assert resp.status_code == 200
        body = resp.json()
        assert body["version"] == "1.0.0"
        assert body["status"] == "running"
        assert "uptime" in body

    def test_get_settings(self):
        resp = self.client.get("/admin/api/settings")
        assert resp.status_code == 200
        body = resp.json()
        assert "max_risk_per_trade" in body
        assert "max_open_positions" in body
        assert "paper_trading_mode" in body

    def test_get_activity_empty(self):
        _activity_log.clear()
        resp = self.client.get("/admin/api/activity")
        assert resp.status_code == 200
        body = resp.json()
        assert "events" in body
        assert isinstance(body["events"], list)

    def test_get_activity_with_events(self):
        _activity_log.clear()
        log_activity("unit test event")
        resp = self.client.get("/admin/api/activity")
        assert resp.status_code == 200
        events = resp.json()["events"]
        assert len(events) >= 1
        assert events[0]["message"] == "unit test event"

    def test_get_dashboard_data(self):
        resp = self.client.get("/admin/api/dashboard-data")
        assert resp.status_code == 200
        body = resp.json()
        assert "system_health" in body
        assert "trading_stats" in body
        assert "risk_status" in body
        assert "module_status" in body

    def test_save_settings(self):
        resp = self.client.post(
            "/admin/api/settings",
            json={"max_risk_per_trade": 1.0, "max_open_positions": 5},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] in ("ok", "error")

    def test_get_system_metrics(self):
        resp = self.client.get("/admin/api/system-metrics")
        assert resp.status_code == 200
        body = resp.json()
        assert "uptime" in body
        assert "uptime_seconds" in body


# ============================================================
# api/signals.py
# ============================================================

from api.signals import (
    TradingSignal,
    SignalStrength,
    SignalDirection,
    SignalAlert,
    SignalAnalytics,
    RealTimeSignalService,
)


def _make_signal(
    service: RealTimeSignalService,
    direction: SignalDirection = SignalDirection.BUY,
    confidence: float = 0.8,
    symbol: str = "XAUUSD",
) -> Optional[TradingSignal]:
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
        expiry = datetime.now(timezone.utc) + timedelta(minutes=30)
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
            "id", "symbol", "direction", "strength", "confidence", "price",
            "entry_price", "stop_loss", "take_profit", "risk_reward_ratio",
            "timeframe", "strategies_agreeing", "total_strategies", "regime",
            "session", "expiry", "timestamp", "metadata", "is_valid",
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
        expiry = datetime.now(timezone.utc) - timedelta(minutes=1)
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
            config={"min_confidence": 0.3, "min_strategies": 2, "signal_expiry_minutes": 30}
        )

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
        sig.expiry = datetime.now(timezone.utc) - timedelta(seconds=1)
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
        expiry = datetime.now(timezone.utc) + timedelta(minutes=30)
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
    PricingTierResponse,
    SubscribeRequest,
    SubscribeResponse,
    ActivateCodeRequest,
    ActivateCodeResponse,
    AffiliateSignupRequest,
    AffiliateResponse,
    ReferralRequest,
    StrategyListRequest,
    StrategyPurchaseRequest,
    ReviewRequest,
    PartnerSignupRequest,
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
        r = SubscribeRequest(user_id="u1", tier="starter")
        assert r.billing_cycle == "monthly"

    def test_subscribe_request_annual(self):
        r = SubscribeRequest(user_id="u1", tier="professional", billing_cycle="annual")
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
        r = ActivateCodeRequest(user_id="u1", code="HOPE-TEST-CODE")
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
            user_id="u1",
            payment_email="pay@test.com",
            custom_code="MY_CODE",
        )
        assert r.custom_code == "MY_CODE"

    def test_affiliate_signup_request_minimal(self):
        r = AffiliateSignupRequest(user_id="u2")
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
        r = ReferralRequest(affiliate_code="CODE123", referred_user_id="newuser")
        assert r.affiliate_code == "CODE123"

    def test_strategy_list_request_defaults(self):
        r = StrategyListRequest(
            creator_id="c1",
            name="My Strategy",
            description="desc",
            category="scalping",
            price=99.0,
        )
        assert r.license_type == "purchase"
        assert r.min_tier == "starter"
        assert r.tags is None

    def test_strategy_purchase_request(self):
        r = StrategyPurchaseRequest(buyer_id="b1", strategy_id="strat_001")
        assert r.buyer_id == "b1"

    def test_review_request_valid(self):
        r = ReviewRequest(
            user_id="u1",
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
                user_id="u1",
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
        from api.monetization import router as mon_router
        app.include_router(mon_router)
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
# api/websocket_server.py
# ============================================================

from api.websocket_server import (
    WebSocketManager,
    WebSocketMessage,
    ConnectionInfo,
    ChannelType,
    get_websocket_manager,
    create_websocket_router,
)


class _MockWebSocket:
    """Mock WebSocket with send_text tracking."""

    def __init__(self):
        self.sent: list = []

    async def send_text(self, text: str):
        self.sent.append(text)


@pytest.mark.unit
class TestWebSocketMessage:
    """Unit tests for WebSocketMessage dataclass."""

    def test_to_json_basic(self):
        msg = WebSocketMessage(
            event="update",
            channel="prices:XAUUSD",
            data={"price": 1900.0},
        )
        parsed = json.loads(msg.to_json())
        assert parsed["event"] == "update"
        assert parsed["channel"] == "prices:XAUUSD"
        assert parsed["data"]["price"] == 1900.0

    def test_timestamp_auto_set(self):
        msg = WebSocketMessage(event="test", channel="ch", data={})
        assert msg.timestamp is not None
        # Should be ISO-format string
        datetime.fromisoformat(msg.timestamp)

    def test_sequence_default_zero(self):
        msg = WebSocketMessage(event="e", channel="c", data={})
        assert msg.sequence == 0


@pytest.mark.unit
class TestWebSocketManager:
    """Unit tests for WebSocketManager."""

    def setup_method(self):
        self.manager = WebSocketManager(
            config={
                "heartbeat_interval": 30,
                "max_subscriptions": 100,
                "rate_limit": 100,
            }
        )

    def test_initialization(self):
        assert self.manager._connections == {}
        assert self.manager._channels == {}
        assert self.manager._sequence == 0

    def test_register_connection_returns_id(self):
        ws = _MockWebSocket()
        conn_id = self.manager.register_connection(ws)
        assert conn_id is not None
        assert conn_id in self.manager._connections

    def test_register_connection_custom_id(self):
        ws = _MockWebSocket()
        conn_id = self.manager.register_connection(ws, connection_id="custom_123")
        assert conn_id == "custom_123"

    def test_register_connection_with_user_id(self):
        ws = _MockWebSocket()
        conn_id = self.manager.register_connection(ws, user_id="user1")
        info = self.manager.get_connection_info(conn_id)
        assert info.user_id == "user1"
        assert info.authenticated is True

    def test_register_increments_total_connections(self):
        ws = _MockWebSocket()
        self.manager.register_connection(ws)
        assert self.manager._stats["total_connections"] >= 1

    def test_unregister_removes_connection(self):
        ws = _MockWebSocket()
        conn_id = self.manager.register_connection(ws)
        self.manager.unregister_connection(conn_id)
        assert conn_id not in self.manager._connections

    def test_unregister_nonexistent_is_noop(self):
        self.manager.unregister_connection("does_not_exist")  # Should not raise

    def test_get_connection_info_existing(self):
        ws = _MockWebSocket()
        conn_id = self.manager.register_connection(ws)
        info = self.manager.get_connection_info(conn_id)
        assert isinstance(info, ConnectionInfo)
        assert info.connection_id == conn_id

    def test_get_connection_info_missing_returns_none(self):
        assert self.manager.get_connection_info("no_such_id") is None

    def test_get_active_connections(self):
        ws1, ws2 = _MockWebSocket(), _MockWebSocket()
        id1 = self.manager.register_connection(ws1)
        id2 = self.manager.register_connection(ws2)
        active = self.manager.get_active_connections()
        assert id1 in active
        assert id2 in active

    # ---- async subscription tests ----

    async def test_subscribe_success(self):
        ws = _MockWebSocket()
        conn_id = self.manager.register_connection(ws)
        result = await self.manager.subscribe(conn_id, "prices:XAUUSD")
        assert result is True
        assert "prices:XAUUSD" in self.manager._channels
        # Confirmation message sent
        assert len(ws.sent) >= 1

    async def test_subscribe_unknown_connection(self):
        result = await self.manager.subscribe("no_conn", "prices:XAUUSD")
        assert result is False

    async def test_subscribe_adds_channel_to_info(self):
        ws = _MockWebSocket()
        conn_id = self.manager.register_connection(ws)
        await self.manager.subscribe(conn_id, "signals:XAUUSD")
        info = self.manager.get_connection_info(conn_id)
        assert "signals:XAUUSD" in info.subscriptions

    async def test_unsubscribe_success(self):
        ws = _MockWebSocket()
        conn_id = self.manager.register_connection(ws)
        await self.manager.subscribe(conn_id, "prices:XAUUSD")
        result = await self.manager.unsubscribe(conn_id, "prices:XAUUSD")
        assert result is True
        info = self.manager.get_connection_info(conn_id)
        assert "prices:XAUUSD" not in info.subscriptions

    async def test_unsubscribe_removes_empty_channel(self):
        ws = _MockWebSocket()
        conn_id = self.manager.register_connection(ws)
        await self.manager.subscribe(conn_id, "prices:XAUUSD")
        await self.manager.unsubscribe(conn_id, "prices:XAUUSD")
        assert "prices:XAUUSD" not in self.manager._channels

    async def test_unsubscribe_nonexistent_channel(self):
        ws = _MockWebSocket()
        conn_id = self.manager.register_connection(ws)
        result = await self.manager.unsubscribe(conn_id, "nonexistent:channel")
        assert result is False

    async def test_broadcast_sends_to_subscribers(self):
        ws = _MockWebSocket()
        conn_id = self.manager.register_connection(ws)
        await self.manager.subscribe(conn_id, "prices:XAUUSD")
        ws.sent.clear()

        await self.manager.broadcast(
            "prices:XAUUSD",
            {"price": 1905.0},
            event="price",
        )
        assert len(ws.sent) >= 1
        parsed = json.loads(ws.sent[-1])
        assert parsed["event"] == "price"

    async def test_broadcast_empty_channel_no_error(self):
        # Should silently do nothing
        await self.manager.broadcast("nonexistent:channel", {"data": 1})

    async def test_broadcast_to_all(self):
        ws1, ws2 = _MockWebSocket(), _MockWebSocket()
        self.manager.register_connection(ws1)
        self.manager.register_connection(ws2)
        ws1.sent.clear()
        ws2.sent.clear()
        await self.manager.broadcast_to_all({"msg": "hello"})
        assert len(ws1.sent) >= 1
        assert len(ws2.sent) >= 1

    async def test_broadcast_excludes_connections(self):
        ws1, ws2 = _MockWebSocket(), _MockWebSocket()
        id1 = self.manager.register_connection(ws1)
        id2 = self.manager.register_connection(ws2)
        await self.manager.subscribe(id1, "ch:test")
        await self.manager.subscribe(id2, "ch:test")
        ws1.sent.clear()
        ws2.sent.clear()
        await self.manager.broadcast("ch:test", {}, exclude={id1})
        assert len(ws1.sent) == 0
        assert len(ws2.sent) >= 1

    async def test_send_to_user(self):
        ws = _MockWebSocket()
        conn_id = self.manager.register_connection(ws, user_id="user_abc")
        ws.sent.clear()
        await self.manager.send_to_user("user_abc", {"alert": "test"})
        assert len(ws.sent) >= 1

    async def test_handle_message_subscribe(self):
        ws = _MockWebSocket()
        conn_id = self.manager.register_connection(ws)
        resp = await self.manager.handle_message(
            conn_id,
            json.dumps({"action": "subscribe", "channel": "prices:XAUUSD"}),
        )
        assert resp is not None
        assert resp["status"] == "subscribed"

    async def test_handle_message_unsubscribe(self):
        ws = _MockWebSocket()
        conn_id = self.manager.register_connection(ws)
        await self.manager.subscribe(conn_id, "prices:XAUUSD")
        resp = await self.manager.handle_message(
            conn_id,
            json.dumps({"action": "unsubscribe", "channel": "prices:XAUUSD"}),
        )
        assert resp["status"] == "unsubscribed"

    async def test_handle_message_ping(self):
        ws = _MockWebSocket()
        conn_id = self.manager.register_connection(ws)
        resp = await self.manager.handle_message(
            conn_id, json.dumps({"action": "ping"})
        )
        assert resp["action"] == "pong"

    async def test_handle_message_auth(self):
        ws = _MockWebSocket()
        conn_id = self.manager.register_connection(ws)
        resp = await self.manager.handle_message(
            conn_id, json.dumps({"action": "auth", "token": "mytoken123"})
        )
        assert resp["status"] == "authenticated"

    async def test_handle_message_invalid_json(self):
        ws = _MockWebSocket()
        conn_id = self.manager.register_connection(ws)
        resp = await self.manager.handle_message(conn_id, "not json {{")
        assert "error" in resp

    async def test_handle_message_unknown_connection(self):
        resp = await self.manager.handle_message("no_conn", json.dumps({"action": "ping"}))
        assert resp is None

    def test_get_stats(self):
        stats = self.manager.get_stats()
        assert "total_connections" in stats
        assert "total_messages_sent" in stats
        assert "active_connections" in stats
        assert "active_channels" in stats

    def test_get_channel_subscribers(self):
        # No subscribers yet
        subs = self.manager.get_channel_subscribers("prices:XAUUSD")
        assert isinstance(subs, set)
        assert len(subs) == 0

    def test_get_available_channels_empty(self):
        channels = self.manager.get_available_channels()
        assert isinstance(channels, list)

    def test_on_connect_callback(self):
        fired = []
        self.manager.on_connect(lambda cid, info: fired.append(cid))
        ws = _MockWebSocket()
        conn_id = self.manager.register_connection(ws)
        assert conn_id in fired

    def test_on_disconnect_callback(self):
        fired = []
        self.manager.on_disconnect(lambda cid: fired.append(cid))
        ws = _MockWebSocket()
        conn_id = self.manager.register_connection(ws)
        self.manager.unregister_connection(conn_id)
        assert conn_id in fired

    async def test_on_message_callback(self):
        fired = []
        self.manager.on_message(lambda cid, data: fired.append(data))

        ws = _MockWebSocket()
        conn_id = self.manager.register_connection(ws)
        await self.manager.handle_message(conn_id, json.dumps({"action": "unknown"}))
        assert len(fired) >= 1

    async def test_broadcast_price_update(self):
        ws = _MockWebSocket()
        conn_id = self.manager.register_connection(ws)
        await self.manager.subscribe(conn_id, "prices:XAUUSD")
        ws.sent.clear()
        await self.manager.broadcast_price_update(
            symbol="XAUUSD",
            price=1905.0,
            bid=1904.9,
            ask=1905.1,
        )
        assert len(ws.sent) >= 1
        parsed = json.loads(ws.sent[-1])
        assert parsed["data"]["symbol"] == "XAUUSD"

    async def test_broadcast_trade(self):
        ws = _MockWebSocket()
        conn_id = self.manager.register_connection(ws)
        await self.manager.subscribe(conn_id, "trades:XAUUSD")
        ws.sent.clear()
        await self.manager.broadcast_trade(
            symbol="XAUUSD",
            price=1906.0,
            quantity=10.0,
            side="buy",
        )
        assert len(ws.sent) >= 1

    async def test_broadcast_signal(self):
        ws = _MockWebSocket()
        conn_id = self.manager.register_connection(ws)
        await self.manager.subscribe(conn_id, "signals:XAUUSD")
        await self.manager.subscribe(conn_id, "signals:all")
        ws.sent.clear()
        await self.manager.broadcast_signal("XAUUSD", {"direction": "buy"})
        assert len(ws.sent) >= 1

    async def test_broadcast_alert_to_user(self):
        ws = _MockWebSocket()
        conn_id = self.manager.register_connection(ws, user_id="alert_user")
        ws.sent.clear()
        await self.manager.broadcast_alert("alert_user", {"message": "price alert"})
        assert len(ws.sent) >= 1

    async def test_broadcast_alert_to_channel(self):
        ws = _MockWebSocket()
        conn_id = self.manager.register_connection(ws)
        await self.manager.subscribe(conn_id, "alerts")
        ws.sent.clear()
        await self.manager.broadcast_alert(None, {"message": "global alert"})
        assert len(ws.sent) >= 1

    async def test_unregister_removes_from_channel(self):
        ws = _MockWebSocket()
        conn_id = self.manager.register_connection(ws)
        await self.manager.subscribe(conn_id, "prices:XAUUSD")
        self.manager.unregister_connection(conn_id)
        subs = self.manager.get_channel_subscribers("prices:XAUUSD")
        assert conn_id not in subs

    async def test_max_subscriptions_enforced(self):
        mgr = WebSocketManager(config={"max_subscriptions": 2})
        ws = _MockWebSocket()
        conn_id = mgr.register_connection(ws)
        r1 = await mgr.subscribe(conn_id, "ch:1")
        r2 = await mgr.subscribe(conn_id, "ch:2")
        r3 = await mgr.subscribe(conn_id, "ch:3")  # Should fail
        assert r1 is True
        assert r2 is True
        assert r3 is False


@pytest.mark.unit
class TestGetWebSocketManager:
    """Unit tests for the global WebSocket manager singleton."""

    def test_get_websocket_manager_returns_instance(self):
        mgr = get_websocket_manager()
        assert isinstance(mgr, WebSocketManager)

    def test_get_websocket_manager_singleton(self):
        mgr1 = get_websocket_manager()
        mgr2 = get_websocket_manager()
        assert mgr1 is mgr2


@pytest.mark.unit
class TestCreateWebSocketRouter:
    """Unit tests for the create_websocket_router factory."""

    def test_creates_router_with_stats_endpoint(self):
        mgr = WebSocketManager()
        router = create_websocket_router(mgr)
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)
        resp = client.get("/ws/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert "active_connections" in body

    def test_creates_router_with_channels_endpoint(self):
        mgr = WebSocketManager()
        router = create_websocket_router(mgr)
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)
        resp = client.get("/ws/channels")
        assert resp.status_code == 200
        body = resp.json()
        assert "channels" in body
