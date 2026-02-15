"""
Comprehensive Tests for Alert Engine Module

Tests for:
- Alert creation
- Alert conditions
- Alert triggering
- Alert management
"""

import pytest
from datetime import datetime, timedelta


class TestAlertConditionType:
    """Tests for AlertConditionType enum."""

    def test_price_conditions(self):
        """Test price-related condition types."""
        from notifications.alert_engine import AlertConditionType

        assert AlertConditionType.PRICE_ABOVE.value == "price_above"
        assert AlertConditionType.PRICE_BELOW.value == "price_below"
        assert AlertConditionType.PRICE_CROSS_ABOVE.value == "price_cross_above"
        assert AlertConditionType.PRICE_CROSS_BELOW.value == "price_cross_below"

    def test_indicator_conditions(self):
        """Test indicator-related condition types."""
        from notifications.alert_engine import AlertConditionType

        assert AlertConditionType.INDICATOR_ABOVE.value == "indicator_above"
        assert AlertConditionType.INDICATOR_BELOW.value == "indicator_below"
        assert AlertConditionType.RSI_OVERBOUGHT.value == "rsi_overbought"
        assert AlertConditionType.RSI_OVERSOLD.value == "rsi_oversold"


class TestAlertPriority:
    """Tests for AlertPriority enum."""

    def test_priority_values(self):
        """Test priority enum values."""
        from notifications.alert_engine import AlertPriority

        assert AlertPriority.CRITICAL.value == "critical"
        assert AlertPriority.HIGH.value == "high"
        assert AlertPriority.MEDIUM.value == "medium"
        assert AlertPriority.LOW.value == "low"
        assert AlertPriority.INFO.value == "info"


class TestAlertStatus:
    """Tests for AlertStatus enum."""

    def test_status_values(self):
        """Test status enum values."""
        from notifications.alert_engine import AlertStatus

        assert AlertStatus.ACTIVE.value == "active"
        assert AlertStatus.TRIGGERED.value == "triggered"
        assert AlertStatus.PAUSED.value == "paused"
        assert AlertStatus.EXPIRED.value == "expired"
        assert AlertStatus.CANCELLED.value == "cancelled"


class TestAlertCondition:
    """Tests for AlertCondition dataclass."""

    def test_condition_creation(self):
        """Test creating an alert condition."""
        from notifications.alert_engine import AlertCondition, AlertConditionType

        condition = AlertCondition(
            type=AlertConditionType.PRICE_ABOVE,
            threshold=2000.00
        )

        assert condition.type == AlertConditionType.PRICE_ABOVE
        assert condition.threshold == 2000.00

    def test_condition_with_indicator(self):
        """Test condition with indicator."""
        from notifications.alert_engine import AlertCondition, AlertConditionType

        condition = AlertCondition(
            type=AlertConditionType.INDICATOR_ABOVE,
            threshold=70.0,
            indicator="rsi_14"
        )

        assert condition.indicator == "rsi_14"

    def test_condition_to_dict(self):
        """Test condition serialization."""
        from notifications.alert_engine import AlertCondition, AlertConditionType

        condition = AlertCondition(
            type=AlertConditionType.PRICE_BELOW,
            threshold=1900.00
        )

        result = condition.to_dict()
        assert result['type'] == "price_below"
        assert result['threshold'] == 1900.00


class TestAlert:
    """Tests for Alert dataclass."""

    def test_alert_creation(self):
        """Test creating an alert."""
        from notifications.alert_engine import (
            Alert, AlertCondition, AlertConditionType, 
            AlertPriority, AlertStatus
        )

        condition = AlertCondition(
            type=AlertConditionType.PRICE_ABOVE,
            threshold=2000.00
        )

        alert = Alert(
            id="ALERT-001",
            name="Gold Above 2000",
            symbol="XAUUSD",
            conditions=[condition],
            priority=AlertPriority.HIGH,
            notify_channels=['discord', 'email']
        )

        assert alert.id == "ALERT-001"
        assert alert.name == "Gold Above 2000"
        assert alert.symbol == "XAUUSD"
        assert alert.priority == AlertPriority.HIGH
        assert len(alert.conditions) == 1

    def test_alert_is_active(self):
        """Test alert active status check."""
        from notifications.alert_engine import (
            Alert, AlertCondition, AlertConditionType, 
            AlertPriority, AlertStatus
        )

        condition = AlertCondition(type=AlertConditionType.PRICE_ABOVE, threshold=2000)

        # Active alert
        alert = Alert(
            id="ALERT-001",
            name="Test",
            symbol="XAUUSD",
            conditions=[condition],
            status=AlertStatus.ACTIVE
        )
        assert alert.is_active() is True

        # Paused alert
        alert.status = AlertStatus.PAUSED
        assert alert.is_active() is False

    def test_alert_expiration(self):
        """Test alert expiration check."""
        from notifications.alert_engine import (
            Alert, AlertCondition, AlertConditionType
        )

        condition = AlertCondition(type=AlertConditionType.PRICE_ABOVE, threshold=2000)

        # Expired alert
        alert = Alert(
            id="ALERT-001",
            name="Test",
            symbol="XAUUSD",
            conditions=[condition],
            expires_at=datetime.utcnow() - timedelta(hours=1)  # Expired 1 hour ago
        )
        assert alert.is_active() is False

    def test_alert_cooldown(self):
        """Test alert cooldown check."""
        from notifications.alert_engine import (
            Alert, AlertCondition, AlertConditionType
        )

        condition = AlertCondition(type=AlertConditionType.PRICE_ABOVE, threshold=2000)

        alert = Alert(
            id="ALERT-001",
            name="Test",
            symbol="XAUUSD",
            conditions=[condition],
            cooldown_minutes=5,
            last_triggered_at=datetime.utcnow() - timedelta(minutes=2)  # 2 min ago
        )

        assert alert.is_in_cooldown() is True

    def test_alert_to_dict(self):
        """Test alert serialization."""
        from notifications.alert_engine import (
            Alert, AlertCondition, AlertConditionType
        )

        condition = AlertCondition(type=AlertConditionType.PRICE_ABOVE, threshold=2000)

        alert = Alert(
            id="ALERT-001",
            name="Test",
            symbol="XAUUSD",
            conditions=[condition]
        )

        result = alert.to_dict()
        assert result['id'] == "ALERT-001"
        assert result['name'] == "Test"
        assert result['symbol'] == "XAUUSD"
        assert 'conditions' in result


class TestAlertEngine:
    """Tests for AlertEngine class."""

    def test_engine_initialization(self):
        """Test engine initialization."""
        from notifications.alert_engine import AlertEngine

        engine = AlertEngine()
        assert engine is not None
        assert hasattr(engine, '_alerts')

    def test_create_alert(self):
        """Test creating an alert."""
        from notifications.alert_engine import AlertEngine, AlertConditionType

        engine = AlertEngine()
        alert = engine.create_alert(
            name="Gold Above 2000",
            symbol="XAUUSD",
            condition_type=AlertConditionType.PRICE_ABOVE,
            threshold=2000.00
        )

        assert alert is not None
        assert alert.name == "Gold Above 2000"
        assert "ALERT-" in alert.id

    def test_create_alert_with_options(self):
        """Test creating alert with all options."""
        from notifications.alert_engine import AlertEngine, AlertConditionType, AlertPriority

        engine = AlertEngine()
        alert = engine.create_alert(
            name="RSI Oversold",
            symbol="EURUSD",
            condition_type=AlertConditionType.RSI_OVERSOLD,
            threshold=30.0,
            priority=AlertPriority.HIGH,
            notify_channels=['discord', 'telegram'],
            expires_in_hours=24,
            cooldown_minutes=10,
            max_triggers=5
        )

        assert alert.priority == AlertPriority.HIGH
        assert alert.cooldown_minutes == 10
        assert alert.max_triggers == 5

    def test_get_alert(self):
        """Test getting an alert by ID."""
        from notifications.alert_engine import AlertEngine, AlertConditionType

        engine = AlertEngine()
        alert = engine.create_alert(
            name="Test Alert",
            symbol="XAUUSD",
            condition_type=AlertConditionType.PRICE_ABOVE,
            threshold=2000
        )

        retrieved = engine.get_alert(alert.id)
        assert retrieved is not None
        assert retrieved.id == alert.id

    def test_get_nonexistent_alert(self):
        """Test getting non-existent alert."""
        from notifications.alert_engine import AlertEngine

        engine = AlertEngine()
        result = engine.get_alert("NONEXISTENT")

        assert result is None

    def test_delete_alert(self):
        """Test deleting an alert."""
        from notifications.alert_engine import AlertEngine, AlertConditionType

        engine = AlertEngine()
        alert = engine.create_alert(
            name="Test",
            symbol="XAUUSD",
            condition_type=AlertConditionType.PRICE_ABOVE,
            threshold=2000
        )

        result = engine.delete_alert(alert.id)
        assert result is True
        assert engine.get_alert(alert.id) is None

    def test_pause_resume_alert(self):
        """Test pausing and resuming an alert."""
        from notifications.alert_engine import AlertEngine, AlertConditionType, AlertStatus

        engine = AlertEngine()
        alert = engine.create_alert(
            name="Test",
            symbol="XAUUSD",
            condition_type=AlertConditionType.PRICE_ABOVE,
            threshold=2000
        )

        # Pause
        engine.pause_alert(alert.id)
        assert engine.get_alert(alert.id).status == AlertStatus.PAUSED

        # Resume
        engine.resume_alert(alert.id)
        assert engine.get_alert(alert.id).status == AlertStatus.ACTIVE

    def test_get_alerts(self):
        """Test getting all alerts."""
        from notifications.alert_engine import AlertEngine, AlertConditionType

        engine = AlertEngine()

        engine.create_alert("Alert 1", "XAUUSD", AlertConditionType.PRICE_ABOVE, 2000)
        engine.create_alert("Alert 2", "EURUSD", AlertConditionType.PRICE_BELOW, 1.10)
        engine.create_alert("Alert 3", "XAUUSD", AlertConditionType.RSI_OVERSOLD, 30)

        # Get all
        all_alerts = engine.get_alerts()
        assert len(all_alerts) >= 3

        # Filter by symbol
        xauusd_alerts = engine.get_alerts(symbol="XAUUSD")
        assert len(xauusd_alerts) >= 2

    def test_get_active_alerts(self):
        """Test getting active alerts only."""
        from notifications.alert_engine import AlertEngine, AlertConditionType

        engine = AlertEngine()

        alert1 = engine.create_alert("Active", "XAUUSD", AlertConditionType.PRICE_ABOVE, 2000)
        alert2 = engine.create_alert("Paused", "EURUSD", AlertConditionType.PRICE_BELOW, 1.10)

        engine.pause_alert(alert2.id)

        active = engine.get_active_alerts()
        assert len(active) >= 1
        assert all(a.is_active() for a in active)

    def test_check_alerts_price_above(self):
        """Test checking alerts for price above condition."""
        from notifications.alert_engine import AlertEngine, AlertConditionType

        engine = AlertEngine()
        engine.create_alert(
            name="Gold Above 2000",
            symbol="XAUUSD",
            condition_type=AlertConditionType.PRICE_ABOVE,
            threshold=2000.00
        )

        # Price above threshold - should trigger
        market_data = {'XAUUSD': {'price': 2005.00}}
        triggered = engine.check_alerts(market_data)

        assert len(triggered) >= 1

    def test_check_alerts_price_below(self):
        """Test checking alerts for price below condition."""
        from notifications.alert_engine import AlertEngine, AlertConditionType

        engine = AlertEngine()
        engine.create_alert(
            name="Gold Below 1900",
            symbol="XAUUSD",
            condition_type=AlertConditionType.PRICE_BELOW,
            threshold=1900.00
        )

        # Price below threshold - should trigger
        market_data = {'XAUUSD': {'price': 1890.00}}
        triggered = engine.check_alerts(market_data)

        assert len(triggered) >= 1

    def test_check_alerts_not_triggered(self):
        """Test alerts not triggered when conditions not met."""
        from notifications.alert_engine import AlertEngine, AlertConditionType

        engine = AlertEngine()
        engine.create_alert(
            name="Gold Above 2100",
            symbol="XAUUSD",
            condition_type=AlertConditionType.PRICE_ABOVE,
            threshold=2100.00
        )

        # Price below threshold - should NOT trigger
        market_data = {'XAUUSD': {'price': 2050.00}}
        triggered = engine.check_alerts(market_data)

        assert len(triggered) == 0

    def test_check_alerts_rsi(self):
        """Test checking RSI alerts."""
        from notifications.alert_engine import AlertEngine, AlertConditionType

        engine = AlertEngine()
        engine.create_alert(
            name="RSI Oversold",
            symbol="XAUUSD",
            condition_type=AlertConditionType.RSI_OVERSOLD,
            threshold=30.0
        )

        # RSI oversold - should trigger (using rsi_14 or rsi key)
        market_data = {'XAUUSD': {'price': 1950, 'indicators': {'rsi': 25, 'rsi_14': 25}}}
        triggered = engine.check_alerts(market_data)

        assert len(triggered) >= 1

    def test_check_alerts_volume(self):
        """Test checking volume alerts."""
        from notifications.alert_engine import AlertEngine, AlertConditionType

        engine = AlertEngine()
        engine.create_alert(
            name="Volume Spike",
            symbol="XAUUSD",
            condition_type=AlertConditionType.VOLUME_ABOVE,
            threshold=1000000
        )

        # High volume - should trigger
        market_data = {'XAUUSD': {'price': 1950, 'volume': 1500000}}
        triggered = engine.check_alerts(market_data)

        assert len(triggered) >= 1

    def test_get_trigger_history(self):
        """Test getting trigger history."""
        from notifications.alert_engine import AlertEngine, AlertConditionType

        engine = AlertEngine()
        engine.create_alert(
            name="Test Alert",
            symbol="XAUUSD",
            condition_type=AlertConditionType.PRICE_ABOVE,
            threshold=2000
        )

        # Trigger alert
        market_data = {'XAUUSD': {'price': 2010}}
        engine.check_alerts(market_data)

        history = engine.get_trigger_history()
        assert len(history) >= 1

    def test_get_stats(self):
        """Test getting engine statistics."""
        from notifications.alert_engine import AlertEngine, AlertConditionType

        engine = AlertEngine()
        engine.create_alert("Test", "XAUUSD", AlertConditionType.PRICE_ABOVE, 2000)

        stats = engine.get_stats()
        assert 'total_alerts' in stats
        assert 'active_alerts' in stats

    def test_notification_handler(self):
        """Test notification handler registration."""
        from notifications.alert_engine import AlertEngine, AlertConditionType

        engine = AlertEngine()

        # Track if handler was called
        handler_called = []

        def test_handler(trigger):
            handler_called.append(trigger)

        engine.register_notification_handler(test_handler)

        engine.create_alert("Test", "XAUUSD", AlertConditionType.PRICE_ABOVE, 2000)
        engine.check_alerts({'XAUUSD': {'price': 2005}})

        assert len(handler_called) >= 1

    def test_global_instance(self):
        """Test global alert engine instance."""
        from notifications.alert_engine import get_alert_engine

        engine1 = get_alert_engine()
        engine2 = get_alert_engine()

        assert engine1 is engine2
