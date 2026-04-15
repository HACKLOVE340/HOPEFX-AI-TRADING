# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Extended tests for Alert Engine module.

Covers:
- Complex alert creation
- Alert update/delete/pause/resume
- Condition evaluation (all condition types)
- Trigger creation and history
- Notification handlers
- FastAPI router
- Background monitoring
"""

import pytest


class TestAlertEngineExtended:
    """Extended tests for AlertEngine covering uncovered lines."""

    @pytest.fixture
    def engine(self):
        from notifications.alert_engine import AlertEngine

        return AlertEngine()

    @pytest.fixture
    def simple_alert(self, engine):
        from notifications.alert_engine import AlertConditionType

        return engine.create_alert(
            name="Test Alert",
            symbol="XAUUSD",
            condition_type=AlertConditionType.PRICE_ABOVE,
            threshold=1950.0,
        )

    # --- Create complex alert ---

    def test_create_complex_alert(self, engine):
        from notifications.alert_engine import AlertCondition, AlertConditionType

        cond1 = AlertCondition(type=AlertConditionType.PRICE_ABOVE, threshold=1900)
        cond2 = AlertCondition(type=AlertConditionType.RSI_OVERBOUGHT, threshold=70)
        alert = engine.create_complex_alert(
            name="Complex Alert",
            symbol="XAUUSD",
            conditions=[cond1, cond2],
            require_all=True,
        )
        assert alert is not None
        assert alert.symbol == "XAUUSD"

    def test_create_complex_alert_require_any(self, engine):
        from notifications.alert_engine import AlertCondition, AlertConditionType

        cond1 = AlertCondition(type=AlertConditionType.PRICE_ABOVE, threshold=1900)
        cond2 = AlertCondition(type=AlertConditionType.PRICE_BELOW, threshold=1800)
        alert = engine.create_complex_alert(
            name="Any Condition Alert",
            symbol="EURUSD",
            conditions=[cond1, cond2],
            require_all=False,
        )
        assert alert is not None
        assert any("logic:any" in tag for tag in alert.tags)

    # --- Update alert ---

    def test_update_alert_name(self, engine, simple_alert):
        updated = engine.update_alert(simple_alert.id, name="Updated Name")
        assert updated is not None
        assert updated.name == "Updated Name"

    def test_update_alert_nonexistent(self, engine):
        result = engine.update_alert("NONEXISTENT-ID", name="foo")
        assert result is None

    def test_update_alert_threshold(self, engine, simple_alert):
        updated = engine.update_alert(simple_alert.id, threshold_override=2000.0)
        assert updated is not None

    # --- Delete alert ---

    def test_delete_existing_alert(self, engine, simple_alert):
        result = engine.delete_alert(simple_alert.id)
        assert result is True
        assert engine.get_alert(simple_alert.id) is None

    def test_delete_nonexistent_alert(self, engine):
        result = engine.delete_alert("FAKE-ID-999")
        assert result is False

    def test_delete_removes_from_symbol_index(self, engine):
        from notifications.alert_engine import AlertConditionType

        alert = engine.create_alert(
            name="To Delete",
            symbol="BTCUSD",
            condition_type=AlertConditionType.PRICE_ABOVE,
            threshold=50000,
        )
        engine.delete_alert(alert.id)
        active = engine.get_active_alerts("BTCUSD")
        assert not any(a.id == alert.id for a in active)

    # --- Pause / Resume ---

    def test_pause_nonexistent(self, engine):
        result = engine.pause_alert("FAKE")
        assert result is False

    def test_resume_nonexistent(self, engine):
        result = engine.resume_alert("FAKE")
        assert result is False

    def test_pause_and_resume(self, engine, simple_alert):
        from notifications.alert_engine import AlertStatus

        engine.pause_alert(simple_alert.id)
        assert simple_alert.status == AlertStatus.PAUSED
        engine.resume_alert(simple_alert.id)
        assert simple_alert.status == AlertStatus.ACTIVE

    # --- Get alerts with filters ---

    def test_get_alerts_filter_by_user(self, engine):
        from notifications.alert_engine import AlertConditionType

        engine.create_alert(
            name="User Alert",
            symbol="XAUUSD",
            condition_type=AlertConditionType.PRICE_ABOVE,
            threshold=1900,
            user_id="user123",
        )
        alerts = engine.get_alerts(user_id="user123")
        assert all(a.user_id == "user123" for a in alerts)

    def test_get_alerts_filter_by_priority(self, engine):
        from notifications.alert_engine import AlertConditionType, AlertPriority

        engine.create_alert(
            name="Critical Alert",
            symbol="XAUUSD",
            condition_type=AlertConditionType.PRICE_ABOVE,
            threshold=1900,
            priority=AlertPriority.CRITICAL,
        )
        alerts = engine.get_alerts(priority=AlertPriority.CRITICAL)
        assert len(alerts) > 0
        assert all(a.priority == AlertPriority.CRITICAL for a in alerts)

    def test_get_alerts_filter_combined(self, engine):
        from notifications.alert_engine import AlertStatus

        alerts = engine.get_alerts(symbol="XAUUSD", status=AlertStatus.ACTIVE)
        assert isinstance(alerts, list)

    # --- Condition evaluation ---

    def test_check_alerts_price_cross_above(self, engine):
        from notifications.alert_engine import AlertConditionType

        engine.create_alert(
            name="Cross Above",
            symbol="XAUUSD",
            condition_type=AlertConditionType.PRICE_CROSS_ABOVE,
            threshold=1950.0,
        )
        # Need two calls to set both last_value and previous_value
        engine.check_alerts(
            {
                "XAUUSD": {
                    "price": 1940.0,
                    "volume": 1000,
                    "indicators": {},
                    "spread": 1.0,
                    "imbalance": 0.0,
                }
            }
        )
        engine.check_alerts(
            {
                "XAUUSD": {
                    "price": 1945.0,
                    "volume": 1000,
                    "indicators": {},
                    "spread": 1.0,
                    "imbalance": 0.0,
                }
            }
        )
        # Third call: price crosses above threshold
        triggered = engine.check_alerts(
            {
                "XAUUSD": {
                    "price": 1960.0,
                    "volume": 1000,
                    "indicators": {},
                    "spread": 1.0,
                    "imbalance": 0.0,
                }
            }
        )
        assert len(triggered) >= 1

    def test_check_alerts_price_cross_below(self, engine):
        from notifications.alert_engine import AlertConditionType

        engine.create_alert(
            name="Cross Below",
            symbol="XAUUSD",
            condition_type=AlertConditionType.PRICE_CROSS_BELOW,
            threshold=1950.0,
        )
        # Need two calls to set both last_value and previous_value
        engine.check_alerts(
            {
                "XAUUSD": {
                    "price": 1960.0,
                    "volume": 1000,
                    "indicators": {},
                    "spread": 1.0,
                    "imbalance": 0.0,
                }
            }
        )
        engine.check_alerts(
            {
                "XAUUSD": {
                    "price": 1955.0,
                    "volume": 1000,
                    "indicators": {},
                    "spread": 1.0,
                    "imbalance": 0.0,
                }
            }
        )
        # Third call: price crosses below threshold
        triggered = engine.check_alerts(
            {
                "XAUUSD": {
                    "price": 1940.0,
                    "volume": 1000,
                    "indicators": {},
                    "spread": 1.0,
                    "imbalance": 0.0,
                }
            }
        )
        assert len(triggered) >= 1

    def test_check_alerts_price_inside_range(self, engine):
        from notifications.alert_engine import AlertConditionType

        engine.create_alert(
            name="Inside Range",
            symbol="XAUUSD",
            condition_type=AlertConditionType.PRICE_INSIDE_RANGE,
            threshold=1900.0,
            threshold_2=2000.0,
        )
        market_data = {
            "XAUUSD": {
                "price": 1950.0,
                "volume": 1000,
                "indicators": {},
                "spread": 1.0,
                "imbalance": 0.0,
            }
        }
        triggered = engine.check_alerts(market_data)
        assert len(triggered) >= 1

    def test_check_alerts_price_outside_range(self, engine):
        from notifications.alert_engine import AlertConditionType

        engine.create_alert(
            name="Outside Range",
            symbol="XAUUSD",
            condition_type=AlertConditionType.PRICE_OUTSIDE_RANGE,
            threshold=1900.0,
            threshold_2=1910.0,
        )
        market_data = {
            "XAUUSD": {
                "price": 2000.0,
                "volume": 1000,
                "indicators": {},
                "spread": 1.0,
                "imbalance": 0.0,
            }
        }
        triggered = engine.check_alerts(market_data)
        assert len(triggered) >= 1

    def test_check_alerts_price_change_pct(self, engine):
        from notifications.alert_engine import AlertConditionType

        engine.create_alert(
            name="Pct Change",
            symbol="XAUUSD",
            condition_type=AlertConditionType.PRICE_CHANGE_PCT,
            threshold=2.0,  # 2% change
        )
        # First call to set last_value
        engine.check_alerts(
            {
                "XAUUSD": {
                    "price": 1950.0,
                    "volume": 1000,
                    "indicators": {},
                    "spread": 1.0,
                    "imbalance": 0.0,
                }
            }
        )
        # Second call sets previous_value = 1950 (last_value)
        engine.check_alerts(
            {
                "XAUUSD": {
                    "price": 1952.0,
                    "volume": 1000,
                    "indicators": {},
                    "spread": 1.0,
                    "imbalance": 0.0,
                }
            }
        )
        # Third call: 3%+ change from previous_value (1950)
        triggered = engine.check_alerts(
            {
                "XAUUSD": {
                    "price": 2012.0,
                    "volume": 1000,
                    "indicators": {},
                    "spread": 1.0,
                    "imbalance": 0.0,
                }
            }
        )
        assert len(triggered) >= 1

    def test_check_alerts_price_change_abs(self, engine):
        from notifications.alert_engine import AlertConditionType

        engine.create_alert(
            name="Abs Change",
            symbol="XAUUSD",
            condition_type=AlertConditionType.PRICE_CHANGE_ABS,
            threshold=10.0,
        )
        # First call to set last_value
        engine.check_alerts(
            {
                "XAUUSD": {
                    "price": 1985.0,
                    "volume": 1000,
                    "indicators": {},
                    "spread": 1.0,
                    "imbalance": 0.0,
                }
            }
        )
        # Second call sets previous_value = 1985
        engine.check_alerts(
            {
                "XAUUSD": {
                    "price": 1986.0,
                    "volume": 1000,
                    "indicators": {},
                    "spread": 1.0,
                    "imbalance": 0.0,
                }
            }
        )
        # Third call: abs change > 10 from previous_value (1985)
        triggered = engine.check_alerts(
            {
                "XAUUSD": {
                    "price": 2000.0,
                    "volume": 1000,
                    "indicators": {},
                    "spread": 1.0,
                    "imbalance": 0.0,
                }
            }
        )
        assert len(triggered) >= 1

    def test_check_alerts_volume_spike(self, engine):
        from notifications.alert_engine import AlertConditionType

        engine.create_alert(
            name="Volume Spike",
            symbol="XAUUSD",
            condition_type=AlertConditionType.VOLUME_SPIKE,
            threshold=5000,
        )
        market_data = {
            "XAUUSD": {
                "price": 1950.0,
                "volume": 10000,
                "indicators": {},
                "spread": 1.0,
                "imbalance": 0.0,
            }
        }
        triggered = engine.check_alerts(market_data)
        assert len(triggered) >= 1

    def test_check_alerts_indicator_above(self, engine):
        from notifications.alert_engine import AlertConditionType

        engine.create_alert(
            name="Indicator Above",
            symbol="XAUUSD",
            condition_type=AlertConditionType.INDICATOR_ABOVE,
            threshold=70.0,
            indicator="rsi",
        )
        market_data = {
            "XAUUSD": {
                "price": 1950.0,
                "volume": 1000,
                "indicators": {"rsi": 75.0},
                "spread": 1.0,
                "imbalance": 0.0,
            }
        }
        triggered = engine.check_alerts(market_data)
        assert len(triggered) >= 1

    def test_check_alerts_indicator_below(self, engine):
        from notifications.alert_engine import AlertConditionType

        engine.create_alert(
            name="Indicator Below",
            symbol="XAUUSD",
            condition_type=AlertConditionType.INDICATOR_BELOW,
            threshold=30.0,
            indicator="rsi",
        )
        market_data = {
            "XAUUSD": {
                "price": 1950.0,
                "volume": 1000,
                "indicators": {"rsi": 25.0},
                "spread": 1.0,
                "imbalance": 0.0,
            }
        }
        triggered = engine.check_alerts(market_data)
        assert len(triggered) >= 1

    def test_check_alerts_rsi_oversold(self, engine):
        from notifications.alert_engine import AlertConditionType

        engine.create_alert(
            name="RSI Oversold",
            symbol="XAUUSD",
            condition_type=AlertConditionType.RSI_OVERSOLD,
            threshold=30.0,
        )
        market_data = {
            "XAUUSD": {
                "price": 1900.0,
                "volume": 1000,
                "indicators": {"rsi_14": 25.0},
                "spread": 1.0,
                "imbalance": 0.0,
            }
        }
        triggered = engine.check_alerts(market_data)
        assert len(triggered) >= 1

    def test_check_alerts_spread_above(self, engine):
        from notifications.alert_engine import AlertConditionType

        engine.create_alert(
            name="Wide Spread",
            symbol="XAUUSD",
            condition_type=AlertConditionType.SPREAD_ABOVE,
            threshold=3.0,
        )
        market_data = {
            "XAUUSD": {
                "price": 1950.0,
                "volume": 1000,
                "indicators": {},
                "spread": 5.0,
                "imbalance": 0.0,
            }
        }
        triggered = engine.check_alerts(market_data)
        assert len(triggered) >= 1

    def test_check_alerts_imbalance_threshold(self, engine):
        from notifications.alert_engine import AlertConditionType

        engine.create_alert(
            name="Imbalance",
            symbol="XAUUSD",
            condition_type=AlertConditionType.IMBALANCE_THRESHOLD,
            threshold=0.5,
        )
        market_data = {
            "XAUUSD": {
                "price": 1950.0,
                "volume": 1000,
                "indicators": {},
                "spread": 1.0,
                "imbalance": 0.8,
            }
        }
        triggered = engine.check_alerts(market_data)
        assert len(triggered) >= 1

    def test_check_alerts_no_previous_price_cross(self, engine):
        """Test cross conditions with no previous price."""
        from notifications.alert_engine import AlertConditionType

        engine.create_alert(
            name="Cross No Prev",
            symbol="XAUUSD",
            condition_type=AlertConditionType.PRICE_CROSS_ABOVE,
            threshold=1950.0,
        )
        market_data = {
            "XAUUSD": {
                "price": 1960.0,
                "volume": 1000,
                "indicators": {},
                "spread": 1.0,
                "imbalance": 0.0,
                # No previous_price key
            }
        }
        # Should not trigger without previous price
        triggered = engine.check_alerts(market_data)
        # With no previous price, cross should not trigger
        assert len(triggered) == 0

    def test_check_alerts_price_range_no_threshold_2(self, engine):
        """Test range condition without threshold_2 does not trigger."""
        from notifications.alert_engine import AlertConditionType

        engine.create_alert(
            name="Range No Threshold2",
            symbol="XAUUSD",
            condition_type=AlertConditionType.PRICE_INSIDE_RANGE,
            threshold=1900.0,
        )
        market_data = {
            "XAUUSD": {
                "price": 1950.0,
                "volume": 1000,
                "indicators": {},
                "spread": 1.0,
                "imbalance": 0.0,
            }
        }
        # With no threshold_2, should not trigger
        triggered = engine.check_alerts(market_data)
        assert len(triggered) == 0

    # --- Notification handler ---

    def test_notification_handler_called_on_trigger(self, engine):
        from notifications.alert_engine import AlertConditionType

        handler_calls = []

        def my_handler(trigger):
            handler_calls.append(trigger)

        engine.register_notification_handler(my_handler)

        engine.create_alert(
            name="Notify Test",
            symbol="XAUUSD",
            condition_type=AlertConditionType.PRICE_ABOVE,
            threshold=1940.0,
        )
        market_data = {
            "XAUUSD": {
                "price": 1960.0,
                "volume": 1000,
                "indicators": {},
                "spread": 1.0,
                "imbalance": 0.0,
            }
        }
        engine.check_alerts(market_data)
        assert len(handler_calls) >= 1

    def test_notification_handler_error_handled(self, engine):
        """Test that notification handler errors don't crash."""
        from notifications.alert_engine import AlertConditionType

        def bad_handler(trigger):
            raise RuntimeError("Handler error")

        engine.register_notification_handler(bad_handler)

        engine.create_alert(
            name="Error Handler Test",
            symbol="XAUUSD",
            condition_type=AlertConditionType.PRICE_ABOVE,
            threshold=1900.0,
        )
        market_data = {
            "XAUUSD": {
                "price": 1950.0,
                "volume": 1000,
                "indicators": {},
                "spread": 1.0,
                "imbalance": 0.0,
            }
        }
        # Should not raise
        engine.check_alerts(market_data)

    # --- Trigger history ---

    def test_get_trigger_history_by_symbol(self, engine):
        from notifications.alert_engine import AlertConditionType

        engine.create_alert(
            name="History Test",
            symbol="XAUUSD",
            condition_type=AlertConditionType.PRICE_ABOVE,
            threshold=1900.0,
        )
        market_data = {
            "XAUUSD": {
                "price": 1950.0,
                "volume": 1000,
                "indicators": {},
                "spread": 1.0,
                "imbalance": 0.0,
            }
        }
        engine.check_alerts(market_data)
        history = engine.get_trigger_history(symbol="XAUUSD")
        assert len(history) >= 1

    def test_get_trigger_history_by_alert_id(self, engine):
        from notifications.alert_engine import AlertConditionType

        alert = engine.create_alert(
            name="ID History",
            symbol="XAUUSD",
            condition_type=AlertConditionType.PRICE_ABOVE,
            threshold=1900.0,
        )
        market_data = {
            "XAUUSD": {
                "price": 1960.0,
                "volume": 1000,
                "indicators": {},
                "spread": 1.0,
                "imbalance": 0.0,
            }
        }
        engine.check_alerts(market_data)
        history = engine.get_trigger_history(alert_id=alert.id)
        assert len(history) >= 1

    def test_get_trigger_history_limit(self, engine):
        history = engine.get_trigger_history(limit=5)
        assert len(history) <= 5

    # --- Stats ---

    def test_get_stats_includes_active(self, engine):
        from notifications.alert_engine import AlertConditionType

        engine.create_alert(
            name="Stats Test",
            symbol="XAUUSD",
            condition_type=AlertConditionType.PRICE_ABOVE,
            threshold=1900.0,
        )
        stats = engine.get_stats()
        assert "active_alerts" in stats
        assert stats["active_alerts"] >= 1
        assert "total_alerts" in stats

    # --- Stop monitoring ---

    def test_stop_monitoring(self, engine):
        engine._monitoring = True
        engine.stop_monitoring()
        assert engine._monitoring is False

    # --- Alert trigger to_dict ---

    def test_trigger_to_dict(self, engine):
        from notifications.alert_engine import AlertConditionType

        engine.create_alert(
            name="Trigger Dict Test",
            symbol="XAUUSD",
            condition_type=AlertConditionType.PRICE_ABOVE,
            threshold=1900.0,
        )
        market_data = {
            "XAUUSD": {
                "price": 1960.0,
                "volume": 1000,
                "indicators": {},
                "spread": 1.0,
                "imbalance": 0.0,
            }
        }
        triggered = engine.check_alerts(market_data)
        assert len(triggered) >= 1
        d = triggered[0].to_dict()
        assert "alert_id" in d
        assert "symbol" in d
        assert "trigger_value" in d

    # --- Message template ---

    def test_custom_message_template(self, engine):
        from notifications.alert_engine import AlertConditionType

        engine.create_alert(
            name="Template Test",
            symbol="XAUUSD",
            condition_type=AlertConditionType.PRICE_ABOVE,
            threshold=1900.0,
            message_template="{symbol} hit {value:.2f}",
        )
        market_data = {
            "XAUUSD": {
                "price": 1960.0,
                "volume": 1000,
                "indicators": {},
                "spread": 1.0,
                "imbalance": 0.0,
            }
        }
        triggered = engine.check_alerts(market_data)
        assert len(triggered) >= 1
        assert "XAUUSD" in triggered[0].message

    # --- Complex alert condition checking ---

    def test_complex_alert_require_all_not_met(self, engine):
        """Test that complex alert with require_all=True doesn't trigger if one fails."""
        from notifications.alert_engine import AlertCondition, AlertConditionType

        cond1 = AlertCondition(type=AlertConditionType.PRICE_ABOVE, threshold=1900)
        cond2 = AlertCondition(type=AlertConditionType.PRICE_ABOVE, threshold=2100)  # Won't be met
        alert = engine.create_complex_alert(
            name="All Required",
            symbol="XAUUSD",
            conditions=[cond1, cond2],
            require_all=True,
        )
        market_data = {
            "XAUUSD": {
                "price": 1950.0,
                "volume": 1000,
                "indicators": {},
                "spread": 1.0,
                "imbalance": 0.0,
            }
        }
        triggered = engine.check_alerts(market_data)
        triggered_ids = [t.alert_id for t in triggered]
        assert alert.id not in triggered_ids

    def test_complex_alert_require_any_met(self, engine):
        """Test that complex alert with require_all=False triggers if any condition met."""
        from notifications.alert_engine import AlertCondition, AlertConditionType

        cond1 = AlertCondition(type=AlertConditionType.PRICE_ABOVE, threshold=1900)
        cond2 = AlertCondition(type=AlertConditionType.PRICE_ABOVE, threshold=2100)  # Won't be met
        alert = engine.create_complex_alert(
            name="Any Required",
            symbol="XAUUSD",
            conditions=[cond1, cond2],
            require_all=False,
        )
        market_data = {
            "XAUUSD": {
                "price": 1950.0,
                "volume": 1000,
                "indicators": {},
                "spread": 1.0,
                "imbalance": 0.0,
            }
        }
        triggered = engine.check_alerts(market_data)
        triggered_ids = [t.alert_id for t in triggered]
        assert alert.id in triggered_ids


class TestCreateAlertRouter:
    """Tests for the FastAPI alert router."""

    def test_create_alert_router(self):
        from notifications.alert_engine import AlertEngine, create_alert_router

        engine = AlertEngine()
        router = create_alert_router(engine)
        assert router is not None
        # Check routes exist
        route_paths = [r.path for r in router.routes]
        assert "/api/alerts/" in route_paths or any("alerts" in p for p in route_paths)

    def test_alert_router_has_routes(self):
        from fastapi import FastAPI

        from notifications.alert_engine import AlertEngine, create_alert_router

        engine = AlertEngine()
        router = create_alert_router(engine)
        app = FastAPI()
        app.include_router(router)
        routes = [r.path for r in app.routes]
        assert any("alerts" in p for p in routes)


class TestAlertEndToEndRouting:
    """End-to-end alert routing: create → check → handler fired.

    Verifies the full internal path without any external network calls:
      create_alert() → check_alerts() → _send_notifications() → handler()

    This is the path that Prometheus/Alertmanager sits downstream of —
    if this chain is broken, no alert reaches any channel.
    """

    def test_price_above_triggers_handler(self):
        """PRICE_ABOVE alert fires the registered handler when price breaches threshold."""
        from notifications.alert_engine import AlertConditionType, AlertEngine

        engine = AlertEngine()
        received: list = []
        engine.register_notification_handler(received.append)

        engine.create_alert(
            name="Gold above 2000",
            symbol="XAUUSD",
            condition_type=AlertConditionType.PRICE_ABOVE,
            threshold=2000.0,
            cooldown_minutes=0,
        )

        triggered = engine.check_alerts({"XAUUSD": {"price": 2050.0}})

        assert len(triggered) == 1, "expected exactly one trigger"
        assert triggered[0].symbol == "XAUUSD"
        assert triggered[0].trigger_value == 2050.0
        # Handler must have been called with the same trigger object
        assert len(received) == 1
        assert received[0].alert_id == triggered[0].alert_id

    def test_price_below_threshold_does_not_trigger(self):
        """PRICE_ABOVE alert must not fire when price is below threshold."""
        from notifications.alert_engine import AlertConditionType, AlertEngine

        engine = AlertEngine()
        received: list = []
        engine.register_notification_handler(received.append)

        engine.create_alert(
            name="Gold above 2000",
            symbol="XAUUSD",
            condition_type=AlertConditionType.PRICE_ABOVE,
            threshold=2000.0,
            cooldown_minutes=0,
        )

        triggered = engine.check_alerts({"XAUUSD": {"price": 1950.0}})

        assert triggered == []
        assert received == []

    def test_multiple_handlers_all_called(self):
        """All registered handlers receive the trigger when an alert fires."""
        from notifications.alert_engine import AlertConditionType, AlertEngine

        engine = AlertEngine()
        bucket_a: list = []
        bucket_b: list = []
        engine.register_notification_handler(bucket_a.append)
        engine.register_notification_handler(bucket_b.append)

        engine.create_alert(
            name="Gold spike",
            symbol="XAUUSD",
            condition_type=AlertConditionType.PRICE_ABOVE,
            threshold=1900.0,
            cooldown_minutes=0,
        )

        engine.check_alerts({"XAUUSD": {"price": 1950.0}})

        assert len(bucket_a) == 1
        assert len(bucket_b) == 1
        assert bucket_a[0].alert_id == bucket_b[0].alert_id

    def test_handler_exception_does_not_block_other_handlers(self):
        """A failing handler must not prevent subsequent handlers from running."""
        from notifications.alert_engine import AlertConditionType, AlertEngine

        engine = AlertEngine()
        good_bucket: list = []

        def bad_handler(_trigger):
            raise RuntimeError("simulated handler failure")

        engine.register_notification_handler(bad_handler)
        engine.register_notification_handler(good_bucket.append)

        engine.create_alert(
            name="Fault tolerance test",
            symbol="XAUUSD",
            condition_type=AlertConditionType.PRICE_ABOVE,
            threshold=1000.0,
            cooldown_minutes=0,
        )

        # Must not raise even though bad_handler raises
        engine.check_alerts({"XAUUSD": {"price": 1100.0}})

        assert len(good_bucket) == 1, "good handler must still be called after bad handler raises"

    def test_trigger_contains_expected_fields(self):
        """AlertTrigger returned by check_alerts has all required fields populated."""
        from notifications.alert_engine import AlertConditionType, AlertEngine

        engine = AlertEngine()
        engine.register_notification_handler(lambda _: None)

        alert = engine.create_alert(
            name="Field check",
            symbol="EURUSD",
            condition_type=AlertConditionType.PRICE_ABOVE,
            threshold=1.10,
            cooldown_minutes=0,
        )

        triggered = engine.check_alerts({"EURUSD": {"price": 1.15}})

        assert len(triggered) == 1
        t = triggered[0]
        assert t.alert_id == alert.id
        assert t.symbol == "EURUSD"
        assert t.trigger_value == 1.15
        assert t.triggered_at is not None
        assert t.message != ""
