"""
Server-Side Alert Engine

Persistent, server-side alert monitoring system:
- Complex condition monitoring
- Multiple condition types (price, indicator, volume, pattern)
- Alert expiration and cooldown
- Multi-channel notifications
- Alert history and analytics

Inspired by: TradingView alerts, MT5 alerts, cTrader alerts
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable, Union
from dataclasses import dataclass, field, asdict
from enum import Enum
import threading
import uuid

logger = logging.getLogger(__name__)


class AlertConditionType(Enum):
    """Types of alert conditions."""
    # Price conditions
    PRICE_ABOVE = "price_above"
    PRICE_BELOW = "price_below"
    PRICE_CROSS_ABOVE = "price_cross_above"
    PRICE_CROSS_BELOW = "price_cross_below"

    # Percentage change
    PRICE_CHANGE_PCT = "price_change_pct"
    PRICE_CHANGE_ABS = "price_change_abs"

    # Range conditions
    PRICE_INSIDE_RANGE = "price_inside_range"
    PRICE_OUTSIDE_RANGE = "price_outside_range"

    # Indicator conditions
    INDICATOR_ABOVE = "indicator_above"
    INDICATOR_BELOW = "indicator_below"
    INDICATOR_CROSS_ABOVE = "indicator_cross_above"
    INDICATOR_CROSS_BELOW = "indicator_cross_below"

    # Volume conditions
    VOLUME_ABOVE = "volume_above"
    VOLUME_SPIKE = "volume_spike"

    # Technical patterns
    RSI_OVERBOUGHT = "rsi_overbought"
    RSI_OVERSOLD = "rsi_oversold"
    MACD_CROSS = "macd_cross"
    MA_CROSS = "ma_cross"

    # Order book / DOM
    SPREAD_ABOVE = "spread_above"
    IMBALANCE_THRESHOLD = "imbalance_threshold"

    # Custom
    CUSTOM = "custom"


class AlertPriority(Enum):
    """Alert priority levels."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class AlertStatus(Enum):
    """Alert status."""
    ACTIVE = "active"
    TRIGGERED = "triggered"
    PAUSED = "paused"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


@dataclass
class AlertCondition:
    """Single condition for an alert."""
    type: AlertConditionType
    threshold: float
    threshold_2: Optional[float] = None  # For range conditions
    indicator: Optional[str] = None  # For indicator conditions
    period: Optional[int] = None  # Timeframe/period
    operator: str = ">"  # Comparison operator

    def to_dict(self) -> Dict:
        return {
            'type': self.type.value,
            'threshold': self.threshold,
            'threshold_2': self.threshold_2,
            'indicator': self.indicator,
            'period': self.period,
            'operator': self.operator
        }


@dataclass
class Alert:
    """
    Alert definition.
    """
    id: str
    name: str
    symbol: str
    conditions: List[AlertCondition]
    priority: AlertPriority = AlertPriority.MEDIUM
    status: AlertStatus = AlertStatus.ACTIVE

    # Notification settings
    notify_channels: List[str] = field(default_factory=lambda: ['web'])
    message_template: Optional[str] = None

    # Timing settings
    expires_at: Optional[datetime] = None
    cooldown_minutes: int = 5  # Min time between triggers
    max_triggers: int = 0  # 0 = unlimited

    # State
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_triggered_at: Optional[datetime] = None
    trigger_count: int = 0
    last_value: Optional[float] = None
    previous_value: Optional[float] = None

    # User/ownership
    user_id: Optional[str] = None
    tags: List[str] = field(default_factory=list)

    def is_active(self) -> bool:
        """Check if alert is currently active."""
        if self.status != AlertStatus.ACTIVE:
            return False

        # Check expiration
        if self.expires_at and datetime.utcnow() > self.expires_at:
            return False

        # Check max triggers
        if self.max_triggers > 0 and self.trigger_count >= self.max_triggers:
            return False

        return True

    def is_in_cooldown(self) -> bool:
        """Check if alert is in cooldown period."""
        if not self.last_triggered_at:
            return False

        cooldown_end = self.last_triggered_at + timedelta(minutes=self.cooldown_minutes)
        return datetime.utcnow() < cooldown_end

    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'name': self.name,
            'symbol': self.symbol,
            'conditions': [c.to_dict() for c in self.conditions],
            'priority': self.priority.value,
            'status': self.status.value,
            'notify_channels': self.notify_channels,
            'message_template': self.message_template,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'cooldown_minutes': self.cooldown_minutes,
            'max_triggers': self.max_triggers,
            'created_at': self.created_at.isoformat(),
            'last_triggered_at': self.last_triggered_at.isoformat() if self.last_triggered_at else None,
            'trigger_count': self.trigger_count,
            'is_active': self.is_active(),
            'is_in_cooldown': self.is_in_cooldown(),
            'user_id': self.user_id,
            'tags': self.tags
        }


@dataclass
class AlertTrigger:
    """Record of an alert trigger."""
    alert_id: str
    alert_name: str
    symbol: str
    triggered_at: datetime
    trigger_value: float
    threshold: float
    condition_type: str
    message: str
    priority: str
    notify_channels: List[str]

    def to_dict(self) -> Dict:
        return {
            'alert_id': self.alert_id,
            'alert_name': self.alert_name,
            'symbol': self.symbol,
            'triggered_at': self.triggered_at.isoformat(),
            'trigger_value': self.trigger_value,
            'threshold': self.threshold,
            'condition_type': self.condition_type,
            'message': self.message,
            'priority': self.priority,
            'notify_channels': self.notify_channels
        }


class AlertEngine:
    """
    Server-side alert engine for persistent alert monitoring.

    Features:
    - Multiple condition types
    - Alert cooldown and expiration
    - Multi-channel notifications
    - Alert history
    - Real-time checking
    - Background monitoring

    Usage:
        alert_engine = AlertEngine()

        # Create alert
        alert = alert_engine.create_alert(
            name="Gold Above 2000",
            symbol="XAUUSD",
            condition_type=AlertConditionType.PRICE_ABOVE,
            threshold=2000.00,
            notify_channels=['discord', 'email']
        )

        # Check alerts in main loop
        triggered = alert_engine.check_alerts(market_data)

        # Start background monitoring
        await alert_engine.start_monitoring()
    """

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize alert engine.

        Args:
            config: Configuration options
        """
        self.config = config or {}

        # Alert storage
        self._alerts: Dict[str, Alert] = {}
        self._alerts_by_symbol: Dict[str, List[str]] = {}

        # History
        self._history_size = self.config.get('history_size', 1000)
        self._trigger_history: List[AlertTrigger] = []

        # Notification callbacks
        self._notification_handlers: List[Callable] = []

        # Indicator cache
        self._indicator_cache: Dict[str, Dict[str, float]] = {}

        # Thread safety
        self._lock = threading.RLock()

        # Background monitoring
        self._monitoring = False
        self._monitor_task: Optional[asyncio.Task] = None

        # Statistics
        self._stats = {
            'total_alerts_created': 0,
            'total_triggers': 0,
            'alerts_by_type': {},
            'triggers_by_symbol': {}
        }

        logger.info("Alert Engine initialized")

    # ================================================================
    # ALERT MANAGEMENT
    # ================================================================

    def create_alert(
        self,
        name: str,
        symbol: str,
        condition_type: AlertConditionType,
        threshold: float,
        threshold_2: Optional[float] = None,
        indicator: Optional[str] = None,
        period: Optional[int] = None,
        priority: AlertPriority = AlertPriority.MEDIUM,
        notify_channels: Optional[List[str]] = None,
        message_template: Optional[str] = None,
        expires_in_hours: Optional[int] = None,
        cooldown_minutes: int = 5,
        max_triggers: int = 0,
        user_id: Optional[str] = None,
        tags: Optional[List[str]] = None
    ) -> Alert:
        """
        Create a new alert.

        Args:
            name: Alert name
            symbol: Trading symbol
            condition_type: Type of condition
            threshold: Threshold value
            threshold_2: Second threshold for range conditions
            indicator: Indicator name for indicator conditions
            period: Indicator period
            priority: Alert priority
            notify_channels: Notification channels
            message_template: Custom message template
            expires_in_hours: Alert expiration
            cooldown_minutes: Cooldown between triggers
            max_triggers: Maximum triggers (0 = unlimited)
            user_id: User ID
            tags: Alert tags

        Returns:
            Created Alert
        """
        with self._lock:
            alert_id = f"ALERT-{uuid.uuid4().hex[:8].upper()}"

            condition = AlertCondition(
                type=condition_type,
                threshold=threshold,
                threshold_2=threshold_2,
                indicator=indicator,
                period=period
            )

            expires_at = None
            if expires_in_hours:
                expires_at = datetime.utcnow() + timedelta(hours=expires_in_hours)

            alert = Alert(
                id=alert_id,
                name=name,
                symbol=symbol,
                conditions=[condition],
                priority=priority,
                notify_channels=notify_channels or ['web'],
                message_template=message_template,
                expires_at=expires_at,
                cooldown_minutes=cooldown_minutes,
                max_triggers=max_triggers,
                user_id=user_id,
                tags=tags or []
            )

            self._alerts[alert_id] = alert

            # Index by symbol
            if symbol not in self._alerts_by_symbol:
                self._alerts_by_symbol[symbol] = []
            self._alerts_by_symbol[symbol].append(alert_id)

            # Update stats
            self._stats['total_alerts_created'] += 1
            type_key = condition_type.value
            self._stats['alerts_by_type'][type_key] = \
                self._stats['alerts_by_type'].get(type_key, 0) + 1

            logger.info(f"Alert created: {alert_id} - {name} for {symbol}")
            return alert

    def create_complex_alert(
        self,
        name: str,
        symbol: str,
        conditions: List[AlertCondition],
        require_all: bool = True,
        **kwargs
    ) -> Alert:
        """
        Create an alert with multiple conditions.

        Args:
            name: Alert name
            symbol: Trading symbol
            conditions: List of AlertCondition objects
            require_all: If True, all conditions must be met
            **kwargs: Additional alert parameters

        Returns:
            Created Alert
        """
        with self._lock:
            alert_id = f"ALERT-{uuid.uuid4().hex[:8].upper()}"

            alert = Alert(
                id=alert_id,
                name=name,
                symbol=symbol,
                conditions=conditions,
                **kwargs
            )

            # Store metadata about condition logic
            alert.tags.append(f"logic:{'all' if require_all else 'any'}")

            self._alerts[alert_id] = alert

            if symbol not in self._alerts_by_symbol:
                self._alerts_by_symbol[symbol] = []
            self._alerts_by_symbol[symbol].append(alert_id)

            logger.info(f"Complex alert created: {alert_id} with {len(conditions)} conditions")
            return alert

    def update_alert(self, alert_id: str, **updates) -> Optional[Alert]:
        """Update an alert."""
        with self._lock:
            if alert_id not in self._alerts:
                return None

            alert = self._alerts[alert_id]

            for key, value in updates.items():
                if hasattr(alert, key):
                    setattr(alert, key, value)

            logger.info(f"Alert updated: {alert_id}")
            return alert

    def delete_alert(self, alert_id: str) -> bool:
        """Delete an alert."""
        with self._lock:
            if alert_id not in self._alerts:
                return False

            alert = self._alerts[alert_id]

            # Remove from symbol index
            if alert.symbol in self._alerts_by_symbol:
                self._alerts_by_symbol[alert.symbol] = [
                    aid for aid in self._alerts_by_symbol[alert.symbol]
                    if aid != alert_id
                ]

            del self._alerts[alert_id]
            logger.info(f"Alert deleted: {alert_id}")
            return True

    def pause_alert(self, alert_id: str) -> bool:
        """Pause an alert."""
        with self._lock:
            if alert_id not in self._alerts:
                return False
            self._alerts[alert_id].status = AlertStatus.PAUSED
            return True

    def resume_alert(self, alert_id: str) -> bool:
        """Resume a paused alert."""
        with self._lock:
            if alert_id not in self._alerts:
                return False
            self._alerts[alert_id].status = AlertStatus.ACTIVE
            return True

    def get_alert(self, alert_id: str) -> Optional[Alert]:
        """Get an alert by ID."""
        return self._alerts.get(alert_id)

    def get_alerts(
        self,
        symbol: Optional[str] = None,
        user_id: Optional[str] = None,
        status: Optional[AlertStatus] = None,
        priority: Optional[AlertPriority] = None
    ) -> List[Alert]:
        """Get alerts with optional filters."""
        with self._lock:
            alerts = list(self._alerts.values())

            if symbol:
                alerts = [a for a in alerts if a.symbol == symbol]
            if user_id:
                alerts = [a for a in alerts if a.user_id == user_id]
            if status:
                alerts = [a for a in alerts if a.status == status]
            if priority:
                alerts = [a for a in alerts if a.priority == priority]

            return alerts

    def get_active_alerts(self, symbol: Optional[str] = None) -> List[Alert]:
        """Get all active alerts."""
        return [a for a in self.get_alerts(symbol=symbol) if a.is_active()]

    # ================================================================
    # ALERT CHECKING
    # ================================================================

    def check_alerts(
        self,
        market_data: Dict[str, Dict[str, Any]]
    ) -> List[AlertTrigger]:
        """
        Check all active alerts against market data.

        Args:
            market_data: Dict of symbol -> data dict
                Expected format:
                {
                    'XAUUSD': {
                        'price': 1950.50,
                        'bid': 1950.45,
                        'ask': 1950.55,
                        'volume': 1000,
                        'indicators': {
                            'rsi_14': 65.5,
                            'macd': 0.5,
                            ...
                        }
                    }
                }

        Returns:
            List of triggered AlertTrigger objects
        """
        triggered = []

        with self._lock:
            for symbol, data in market_data.items():
                # Get alerts for this symbol
                alert_ids = self._alerts_by_symbol.get(symbol, [])

                for alert_id in alert_ids:
                    alert = self._alerts.get(alert_id)
                    if not alert or not alert.is_active() or alert.is_in_cooldown():
                        continue

                    # Check conditions
                    trigger = self._check_alert_conditions(alert, data)
                    if trigger:
                        triggered.append(trigger)

        # Send notifications
        for trigger in triggered:
            self._send_notifications(trigger)

        return triggered

    def _check_alert_conditions(
        self,
        alert: Alert,
        data: Dict[str, Any]
    ) -> Optional[AlertTrigger]:
        """Check if alert conditions are met."""
        price = data.get('price', 0)
        volume = data.get('volume', 0)
        indicators = data.get('indicators', {})
        spread = data.get('spread', 0)
        imbalance = data.get('imbalance', 0)

        # Determine if we need all conditions or any
        require_all = 'logic:all' in alert.tags or 'logic:any' not in alert.tags

        conditions_met = []

        for condition in alert.conditions:
            met, trigger_value = self._evaluate_condition(
                condition, price, volume, indicators, spread, imbalance,
                alert.previous_value
            )
            conditions_met.append((met, trigger_value, condition))

        # Update previous value for cross-type conditions
        alert.previous_value = alert.last_value
        alert.last_value = price

        # Check if conditions are satisfied
        if require_all:
            all_met = all(m for m, _, _ in conditions_met)
            if not all_met:
                return None
        else:
            any_met = any(m for m, _, _ in conditions_met)
            if not any_met:
                return None

        # Get the first satisfied condition for the trigger
        for met, trigger_value, condition in conditions_met:
            if met:
                return self._create_trigger(alert, trigger_value, condition)

        return None

    def _evaluate_condition(
        self,
        condition: AlertCondition,
        price: float,
        volume: float,
        indicators: Dict[str, float],
        spread: float,
        imbalance: float,
        previous_value: Optional[float]
    ) -> tuple:
        """
        Evaluate a single condition.

        Returns:
            (condition_met: bool, trigger_value: float)
        """
        ctype = condition.type
        threshold = condition.threshold
        threshold_2 = condition.threshold_2

        # Price conditions
        if ctype == AlertConditionType.PRICE_ABOVE:
            return price > threshold, price

        elif ctype == AlertConditionType.PRICE_BELOW:
            return price < threshold, price

        elif ctype == AlertConditionType.PRICE_CROSS_ABOVE:
            if previous_value is None:
                return False, price
            return previous_value <= threshold < price, price

        elif ctype == AlertConditionType.PRICE_CROSS_BELOW:
            if previous_value is None:
                return False, price
            return previous_value >= threshold > price, price

        elif ctype == AlertConditionType.PRICE_INSIDE_RANGE:
            if threshold_2 is None:
                return False, price
            return threshold <= price <= threshold_2, price

        elif ctype == AlertConditionType.PRICE_OUTSIDE_RANGE:
            if threshold_2 is None:
                return False, price
            return price < threshold or price > threshold_2, price

        elif ctype == AlertConditionType.PRICE_CHANGE_PCT:
            if previous_value is None or previous_value == 0:
                return False, 0
            change_pct = ((price - previous_value) / previous_value) * 100
            return abs(change_pct) >= threshold, change_pct

        elif ctype == AlertConditionType.PRICE_CHANGE_ABS:
            if previous_value is None:
                return False, 0
            change = abs(price - previous_value)
            return change >= threshold, change

        # Volume conditions
        elif ctype == AlertConditionType.VOLUME_ABOVE:
            return volume > threshold, volume

        elif ctype == AlertConditionType.VOLUME_SPIKE:
            # Would need average volume for comparison
            return volume > threshold, volume

        # Indicator conditions
        elif ctype == AlertConditionType.INDICATOR_ABOVE:
            indicator_value = indicators.get(condition.indicator, 0)
            return indicator_value > threshold, indicator_value

        elif ctype == AlertConditionType.INDICATOR_BELOW:
            indicator_value = indicators.get(condition.indicator, 0)
            return indicator_value < threshold, indicator_value

        # RSI conditions
        elif ctype == AlertConditionType.RSI_OVERBOUGHT:
            rsi = indicators.get('rsi', indicators.get('rsi_14', 50))
            return rsi > threshold, rsi

        elif ctype == AlertConditionType.RSI_OVERSOLD:
            rsi = indicators.get('rsi', indicators.get('rsi_14', 50))
            return rsi < threshold, rsi

        # Spread/imbalance
        elif ctype == AlertConditionType.SPREAD_ABOVE:
            return spread > threshold, spread

        elif ctype == AlertConditionType.IMBALANCE_THRESHOLD:
            return abs(imbalance) > threshold, imbalance

        return False, 0

    def _create_trigger(
        self,
        alert: Alert,
        trigger_value: float,
        condition: AlertCondition
    ) -> AlertTrigger:
        """Create an alert trigger record."""
        now = datetime.utcnow()

        # Update alert state
        alert.last_triggered_at = now
        alert.trigger_count += 1

        # Generate message
        message = self._generate_message(alert, trigger_value, condition)

        trigger = AlertTrigger(
            alert_id=alert.id,
            alert_name=alert.name,
            symbol=alert.symbol,
            triggered_at=now,
            trigger_value=trigger_value,
            threshold=condition.threshold,
            condition_type=condition.type.value,
            message=message,
            priority=alert.priority.value,
            notify_channels=alert.notify_channels
        )

        # Store in history
        self._trigger_history.append(trigger)
        if len(self._trigger_history) > self._history_size:
            self._trigger_history.pop(0)

        # Update stats
        self._stats['total_triggers'] += 1
        self._stats['triggers_by_symbol'][alert.symbol] = \
            self._stats['triggers_by_symbol'].get(alert.symbol, 0) + 1

        logger.info(f"Alert triggered: {alert.id} - {alert.name}")
        return trigger

    def _generate_message(
        self,
        alert: Alert,
        trigger_value: float,
        condition: AlertCondition
    ) -> str:
        """Generate alert message."""
        if alert.message_template:
            return alert.message_template.format(
                symbol=alert.symbol,
                value=trigger_value,
                threshold=condition.threshold,
                name=alert.name
            )

        return (
            f"🚨 {alert.name}\n"
            f"Symbol: {alert.symbol}\n"
            f"Condition: {condition.type.value}\n"
            f"Value: {trigger_value:.4f}\n"
            f"Threshold: {condition.threshold:.4f}"
        )

    # ================================================================
    # NOTIFICATIONS
    # ================================================================

    def register_notification_handler(self, handler: Callable):
        """
        Register a notification handler.

        Handler signature: handler(trigger: AlertTrigger)
        """
        self._notification_handlers.append(handler)

    def _send_notifications(self, trigger: AlertTrigger):
        """Send notifications for a trigger."""
        for handler in self._notification_handlers:
            try:
                handler(trigger)
            except Exception as e:
                logger.error(f"Notification handler error: {e}")

    # ================================================================
    # HISTORY & STATISTICS
    # ================================================================

    def get_trigger_history(
        self,
        symbol: Optional[str] = None,
        alert_id: Optional[str] = None,
        limit: int = 50
    ) -> List[AlertTrigger]:
        """Get trigger history."""
        history = self._trigger_history.copy()

        if symbol:
            history = [t for t in history if t.symbol == symbol]
        if alert_id:
            history = [t for t in history if t.alert_id == alert_id]

        return history[-limit:]

    def get_stats(self) -> Dict:
        """Get alert engine statistics."""
        with self._lock:
            return {
                **self._stats,
                'active_alerts': len([a for a in self._alerts.values() if a.is_active()]),
                'total_alerts': len(self._alerts),
                'alerts_in_cooldown': len([a for a in self._alerts.values() if a.is_in_cooldown()]),
                'trigger_history_size': len(self._trigger_history)
            }

    # ================================================================
    # BACKGROUND MONITORING
    # ================================================================

    async def start_monitoring(
        self,
        data_provider: Callable,
        interval_seconds: float = 1.0
    ):
        """
        Start background alert monitoring.

        Args:
            data_provider: Async callable that returns market data dict
            interval_seconds: Check interval
        """
        self._monitoring = True
        logger.info("Alert monitoring started")

        while self._monitoring:
            try:
                market_data = await data_provider()
                self.check_alerts(market_data)
            except Exception as e:
                logger.error(f"Alert monitoring error: {e}")

            await asyncio.sleep(interval_seconds)

    def stop_monitoring(self):
        """Stop background monitoring."""
        self._monitoring = False
        logger.info("Alert monitoring stopped")


# ================================================================
# FASTAPI INTEGRATION
# ================================================================

def create_alert_router(alert_engine: AlertEngine):
    """
    Create FastAPI router with alert endpoints.

    Args:
        alert_engine: AlertEngine instance

    Returns:
        FastAPI APIRouter
    """
    from fastapi import APIRouter, HTTPException
    from pydantic import BaseModel
    from typing import Optional, List

    router = APIRouter(prefix="/api/alerts", tags=["Alerts"])

    class CreateAlertRequest(BaseModel):
        name: str
        symbol: str
        condition_type: str
        threshold: float
        threshold_2: Optional[float] = None
        indicator: Optional[str] = None
        priority: str = "medium"
        notify_channels: List[str] = ["web"]
        expires_in_hours: Optional[int] = None
        cooldown_minutes: int = 5
        max_triggers: int = 0

    @router.post("/")
    async def create_alert(request: CreateAlertRequest):
        """Create a new alert."""
        try:
            condition_type = AlertConditionType(request.condition_type)
            priority = AlertPriority(request.priority)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        alert = alert_engine.create_alert(
            name=request.name,
            symbol=request.symbol,
            condition_type=condition_type,
            threshold=request.threshold,
            threshold_2=request.threshold_2,
            indicator=request.indicator,
            priority=priority,
            notify_channels=request.notify_channels,
            expires_in_hours=request.expires_in_hours,
            cooldown_minutes=request.cooldown_minutes,
            max_triggers=request.max_triggers
        )
        return alert.to_dict()

    @router.get("/")
    async def list_alerts(
        symbol: Optional[str] = None,
        status: Optional[str] = None
    ):
        """List all alerts."""
        status_enum = AlertStatus(status) if status else None
        alerts = alert_engine.get_alerts(symbol=symbol, status=status_enum)
        return [a.to_dict() for a in alerts]

    @router.get("/active")
    async def get_active_alerts(symbol: Optional[str] = None):
        """Get active alerts."""
        alerts = alert_engine.get_active_alerts(symbol)
        return [a.to_dict() for a in alerts]

    @router.get("/{alert_id}")
    async def get_alert(alert_id: str):
        """Get alert by ID."""
        alert = alert_engine.get_alert(alert_id)
        if not alert:
            raise HTTPException(status_code=404, detail="Alert not found")
        return alert.to_dict()

    @router.delete("/{alert_id}")
    async def delete_alert(alert_id: str):
        """Delete an alert."""
        if not alert_engine.delete_alert(alert_id):
            raise HTTPException(status_code=404, detail="Alert not found")
        return {"status": "deleted"}

    @router.post("/{alert_id}/pause")
    async def pause_alert(alert_id: str):
        """Pause an alert."""
        if not alert_engine.pause_alert(alert_id):
            raise HTTPException(status_code=404, detail="Alert not found")
        return {"status": "paused"}

    @router.post("/{alert_id}/resume")
    async def resume_alert(alert_id: str):
        """Resume an alert."""
        if not alert_engine.resume_alert(alert_id):
            raise HTTPException(status_code=404, detail="Alert not found")
        return {"status": "resumed"}

    @router.get("/history/triggers")
    async def get_trigger_history(
        symbol: Optional[str] = None,
        alert_id: Optional[str] = None,
        limit: int = 50
    ):
        """Get trigger history."""
        history = alert_engine.get_trigger_history(symbol, alert_id, limit)
        return [t.to_dict() for t in history]

    @router.get("/stats")
    async def get_stats():
        """Get alert engine statistics."""
        return alert_engine.get_stats()

    return router


# Global instance for easy access
_alert_engine: Optional[AlertEngine] = None


def get_alert_engine() -> AlertEngine:
    """Get the global alert engine instance."""
    global _alert_engine
    if _alert_engine is None:
        _alert_engine = AlertEngine()
    return _alert_engine
