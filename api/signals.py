"""
Real-Time Trading Signals API

Provides real-time trading signals with:
- Multi-strategy signal aggregation
- Confidence scoring
- Signal history and analytics
- WebSocket-ready event format
- Alert management
"""

from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
import json
import logging
from collections import deque
import threading

logger = logging.getLogger(__name__)


class SignalStrength(Enum):
    """Signal strength levels."""
    VERY_STRONG = "very_strong"  # 0.8+
    STRONG = "strong"            # 0.6-0.8
    MODERATE = "moderate"        # 0.4-0.6
    WEAK = "weak"               # 0.2-0.4
    VERY_WEAK = "very_weak"     # 0-0.2


class SignalDirection(Enum):
    """Signal direction."""
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class TradingSignal:
    """
    Real-time trading signal with full context.
    """
    id: str
    symbol: str
    direction: SignalDirection
    strength: SignalStrength
    confidence: float  # 0-1
    price: float
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_reward_ratio: float
    timeframe: str
    strategies_agreeing: List[str]
    total_strategies: int
    regime: str  # Market regime
    session: str  # Trading session
    expiry: datetime
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'symbol': self.symbol,
            'direction': self.direction.value,
            'strength': self.strength.value,
            'confidence': self.confidence,
            'price': self.price,
            'entry_price': self.entry_price,
            'stop_loss': self.stop_loss,
            'take_profit': self.take_profit,
            'risk_reward_ratio': self.risk_reward_ratio,
            'timeframe': self.timeframe,
            'strategies_agreeing': self.strategies_agreeing,
            'total_strategies': self.total_strategies,
            'regime': self.regime,
            'session': self.session,
            'expiry': self.expiry.isoformat(),
            'timestamp': self.timestamp.isoformat(),
            'metadata': self.metadata,
            'is_valid': self.is_valid
        }

    @property
    def is_valid(self) -> bool:
        """Check if signal is still valid."""
        return datetime.utcnow() < self.expiry

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict())


@dataclass
class SignalAlert:
    """Alert configuration for signals."""
    id: str
    symbol: str
    direction: Optional[SignalDirection] = None
    min_confidence: float = 0.5
    min_strength: SignalStrength = SignalStrength.MODERATE
    notify_channels: List[str] = field(default_factory=lambda: ['web'])
    active: bool = True
    triggered_count: int = 0
    last_triggered: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class SignalPerformance:
    """Track signal performance."""
    signal_id: str
    symbol: str
    direction: SignalDirection
    entry_price: float
    current_price: float
    stop_loss: float
    take_profit: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    status: str  # 'open', 'hit_tp', 'hit_sl', 'expired'
    duration_minutes: int
    max_favorable_move: float
    max_adverse_move: float


class SignalAnalytics:
    """Analytics for signal performance."""

    def __init__(self):
        self.signals_generated = 0
        self.signals_by_direction = {'buy': 0, 'sell': 0, 'hold': 0}
        self.signals_by_strength = {s.value: 0 for s in SignalStrength}
        self.signals_by_symbol = {}
        self.hit_rate = {'tp': 0, 'sl': 0, 'expired': 0}
        self.avg_confidence = 0.0
        self.avg_rr_ratio = 0.0
        self.hourly_distribution = {str(h): 0 for h in range(24)}

    def record_signal(self, signal: TradingSignal):
        """Record a new signal."""
        self.signals_generated += 1
        self.signals_by_direction[signal.direction.value] += 1
        self.signals_by_strength[signal.strength.value] += 1

        if signal.symbol not in self.signals_by_symbol:
            self.signals_by_symbol[signal.symbol] = 0
        self.signals_by_symbol[signal.symbol] += 1

        hour = str(signal.timestamp.hour)
        self.hourly_distribution[hour] += 1

        # Update averages
        n = self.signals_generated
        self.avg_confidence = ((self.avg_confidence * (n - 1)) + signal.confidence) / n
        self.avg_rr_ratio = ((self.avg_rr_ratio * (n - 1)) + signal.risk_reward_ratio) / n

    def record_outcome(self, outcome: str):
        """Record signal outcome (tp, sl, expired)."""
        if outcome in self.hit_rate:
            self.hit_rate[outcome] += 1

    def to_dict(self) -> Dict:
        total_outcomes = sum(self.hit_rate.values())
        return {
            'signals_generated': self.signals_generated,
            'signals_by_direction': self.signals_by_direction,
            'signals_by_strength': self.signals_by_strength,
            'signals_by_symbol': self.signals_by_symbol,
            'hit_rate': self.hit_rate,
            'tp_rate': self.hit_rate['tp'] / total_outcomes if total_outcomes > 0 else 0,
            'sl_rate': self.hit_rate['sl'] / total_outcomes if total_outcomes > 0 else 0,
            'avg_confidence': self.avg_confidence,
            'avg_rr_ratio': self.avg_rr_ratio,
            'hourly_distribution': self.hourly_distribution,
        }


class RealTimeSignalService:
    """
    Real-time trading signal service.

    Features:
    - Signal generation from multiple strategies
    - Confidence scoring and aggregation
    - Signal history management
    - Alert system
    - WebSocket event publishing
    - Performance tracking
    """

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize signal service.

        Args:
            config: Configuration options
        """
        self.config = config or {}

        # Signal storage
        self.active_signals: Dict[str, TradingSignal] = {}
        self.signal_history: deque = deque(maxlen=1000)

        # Alerts
        self.alerts: Dict[str, SignalAlert] = {}

        # Event subscribers
        self.subscribers: List[Callable] = []

        # Analytics
        self.analytics = SignalAnalytics()

        # Configuration
        self.signal_expiry_minutes = self.config.get('signal_expiry_minutes', 30)
        self.min_confidence = self.config.get('min_confidence', 0.3)
        self.min_strategies = self.config.get('min_strategies', 2)

        # Thread safety
        self._lock = threading.Lock()

        logger.info("Real-Time Signal Service initialized")

    def generate_signal(
        self,
        symbol: str,
        direction: SignalDirection,
        confidence: float,
        price: float,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        timeframe: str,
        strategies_agreeing: List[str],
        total_strategies: int,
        regime: str = "unknown",
        session: str = "unknown",
        metadata: Optional[Dict] = None
    ) -> Optional[TradingSignal]:
        """
        Generate a new trading signal.

        Args:
            symbol: Trading symbol
            direction: Signal direction (buy/sell)
            confidence: Confidence score (0-1)
            price: Current price
            entry_price: Suggested entry price
            stop_loss: Stop loss price
            take_profit: Take profit price
            timeframe: Analysis timeframe
            strategies_agreeing: List of agreeing strategy names
            total_strategies: Total strategies analyzed
            regime: Market regime
            session: Trading session
            metadata: Additional metadata

        Returns:
            TradingSignal or None if validation fails
        """
        # Validate
        if confidence < self.min_confidence:
            logger.debug(f"Signal rejected: confidence {confidence} < {self.min_confidence}")
            return None

        if len(strategies_agreeing) < self.min_strategies:
            logger.debug(f"Signal rejected: {len(strategies_agreeing)} strategies < {self.min_strategies}")
            return None

        # Calculate risk/reward
        if direction == SignalDirection.BUY:
            risk = entry_price - stop_loss
            reward = take_profit - entry_price
        else:
            risk = stop_loss - entry_price
            reward = entry_price - take_profit

        rr_ratio = reward / risk if risk > 0 else 0

        # Determine strength
        strength = self._calculate_strength(confidence, len(strategies_agreeing), total_strategies, rr_ratio)

        # Create signal
        signal = TradingSignal(
            id=f"SIG-{symbol}-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}",
            symbol=symbol,
            direction=direction,
            strength=strength,
            confidence=confidence,
            price=price,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            risk_reward_ratio=rr_ratio,
            timeframe=timeframe,
            strategies_agreeing=strategies_agreeing,
            total_strategies=total_strategies,
            regime=regime,
            session=session,
            expiry=datetime.utcnow() + timedelta(minutes=self.signal_expiry_minutes),
            metadata=metadata or {}
        )

        with self._lock:
            self.active_signals[signal.id] = signal
            self.signal_history.append(signal)
            self.analytics.record_signal(signal)

        # Publish event
        self._publish_event('signal_generated', signal)

        # Check alerts
        self._check_alerts(signal)

        logger.info(f"Signal generated: {signal.id} - {direction.value} {symbol} @ {confidence:.2%}")
        return signal

    def _calculate_strength(
        self,
        confidence: float,
        agreeing: int,
        total: int,
        rr_ratio: float
    ) -> SignalStrength:
        """Calculate signal strength based on multiple factors."""

        # Calculate composite score
        strategy_agreement = agreeing / total if total > 0 else 0
        rr_score = min(rr_ratio / 3, 1.0)  # Normalize RR (3:1 = perfect)

        # Weighted score
        composite = (confidence * 0.5) + (strategy_agreement * 0.3) + (rr_score * 0.2)

        if composite >= 0.8:
            return SignalStrength.VERY_STRONG
        elif composite >= 0.6:
            return SignalStrength.STRONG
        elif composite >= 0.4:
            return SignalStrength.MODERATE
        elif composite >= 0.2:
            return SignalStrength.WEAK
        else:
            return SignalStrength.VERY_WEAK

    def get_active_signals(
        self,
        symbol: str = None,
        direction: SignalDirection = None,
        min_strength: SignalStrength = None
    ) -> List[TradingSignal]:
        """
        Get active (non-expired) signals.

        Args:
            symbol: Filter by symbol
            direction: Filter by direction
            min_strength: Filter by minimum strength

        Returns:
            List of active signals
        """
        with self._lock:
            # Remove expired signals
            expired = [sid for sid, s in self.active_signals.items() if not s.is_valid]
            for sid in expired:
                del self.active_signals[sid]

            # Filter
            signals = list(self.active_signals.values())

            if symbol:
                signals = [s for s in signals if s.symbol == symbol]
            if direction:
                signals = [s for s in signals if s.direction == direction]
            if min_strength:
                strength_order = list(SignalStrength)
                min_idx = strength_order.index(min_strength)
                signals = [s for s in signals if strength_order.index(s.strength) <= min_idx]

            return sorted(signals, key=lambda s: -s.confidence)

    def get_signal(self, signal_id: str) -> Optional[TradingSignal]:
        """Get signal by ID."""
        return self.active_signals.get(signal_id)

    def expire_signal(self, signal_id: str):
        """Manually expire a signal."""
        with self._lock:
            if signal_id in self.active_signals:
                signal = self.active_signals[signal_id]
                signal.expiry = datetime.utcnow()
                del self.active_signals[signal_id]
                self.analytics.record_outcome('expired')
                self._publish_event('signal_expired', signal)

    def record_signal_outcome(self, signal_id: str, outcome: str, exit_price: float):
        """
        Record signal outcome.

        Args:
            signal_id: Signal ID
            outcome: 'tp', 'sl', or 'expired'
            exit_price: Exit price
        """
        with self._lock:
            signal = self.active_signals.get(signal_id)
            if signal:
                self.analytics.record_outcome(outcome)
                del self.active_signals[signal_id]

                self._publish_event('signal_closed', {
                    'signal': signal.to_dict(),
                    'outcome': outcome,
                    'exit_price': exit_price
                })

    # ============================================================
    # ALERTS
    # ============================================================

    def create_alert(
        self,
        symbol: str,
        direction: Optional[SignalDirection] = None,
        min_confidence: float = 0.5,
        min_strength: SignalStrength = SignalStrength.MODERATE,
        notify_channels: List[str] = None
    ) -> SignalAlert:
        """Create a signal alert."""
        import uuid
        alert = SignalAlert(
            id=str(uuid.uuid4()),
            symbol=symbol,
            direction=direction,
            min_confidence=min_confidence,
            min_strength=min_strength,
            notify_channels=notify_channels or ['web']
        )

        with self._lock:
            self.alerts[alert.id] = alert

        logger.info(f"Alert created: {alert.id} for {symbol}")
        return alert

    def _check_alerts(self, signal: TradingSignal):
        """Check if signal triggers any alerts."""
        strength_order = list(SignalStrength)

        for alert in self.alerts.values():
            if not alert.active:
                continue

            if alert.symbol != signal.symbol:
                continue

            if alert.direction and alert.direction != signal.direction:
                continue

            if signal.confidence < alert.min_confidence:
                continue

            alert_strength_idx = strength_order.index(alert.min_strength)
            signal_strength_idx = strength_order.index(signal.strength)
            if signal_strength_idx > alert_strength_idx:
                continue

            # Alert triggered!
            alert.triggered_count += 1
            alert.last_triggered = datetime.utcnow()

            self._publish_event('alert_triggered', {
                'alert': asdict(alert),
                'signal': signal.to_dict()
            })

            logger.info(f"Alert triggered: {alert.id} by signal {signal.id}")

    def delete_alert(self, alert_id: str):
        """Delete an alert."""
        with self._lock:
            if alert_id in self.alerts:
                del self.alerts[alert_id]

    def get_alerts(self, symbol: str = None) -> List[SignalAlert]:
        """Get all alerts, optionally filtered by symbol."""
        alerts = list(self.alerts.values())
        if symbol:
            alerts = [a for a in alerts if a.symbol == symbol]
        return alerts

    # ============================================================
    # SUBSCRIPTIONS
    # ============================================================

    def subscribe(self, callback: Callable):
        """
        Subscribe to signal events.

        Callback receives (event_type: str, data: dict)
        """
        self.subscribers.append(callback)
        logger.debug(f"New subscriber added. Total: {len(self.subscribers)}")

    def unsubscribe(self, callback: Callable):
        """Unsubscribe from signal events."""
        if callback in self.subscribers:
            self.subscribers.remove(callback)

    def _publish_event(self, event_type: str, data: Any):
        """Publish event to all subscribers."""
        event = {
            'type': event_type,
            'timestamp': datetime.utcnow().isoformat(),
            'data': data.to_dict() if hasattr(data, 'to_dict') else data
        }

        for callback in self.subscribers:
            try:
                callback(event_type, event)
            except Exception as e:
                logger.error(f"Error in subscriber callback: {e}")

    # ============================================================
    # HISTORY & ANALYTICS
    # ============================================================

    def get_signal_history(
        self,
        symbol: str = None,
        hours: int = 24
    ) -> List[TradingSignal]:
        """Get signal history."""
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        signals = [s for s in self.signal_history if s.timestamp > cutoff]

        if symbol:
            signals = [s for s in signals if s.symbol == symbol]

        return sorted(signals, key=lambda s: -s.timestamp.timestamp())

    def get_analytics(self) -> Dict:
        """Get signal analytics."""
        return self.analytics.to_dict()

    def get_signal_summary(self) -> Dict:
        """Get summary of current signal state."""
        with self._lock:
            return {
                'active_signals': len(self.active_signals),
                'signals_last_hour': len([
                    s for s in self.signal_history
                    if s.timestamp > datetime.utcnow() - timedelta(hours=1)
                ]),
                'signals_last_24h': len([
                    s for s in self.signal_history
                    if s.timestamp > datetime.utcnow() - timedelta(hours=24)
                ]),
                'active_alerts': len([a for a in self.alerts.values() if a.active]),
                'symbols_with_signals': list(set(s.symbol for s in self.active_signals.values())),
                'direction_distribution': {
                    'buy': len([s for s in self.active_signals.values() if s.direction == SignalDirection.BUY]),
                    'sell': len([s for s in self.active_signals.values() if s.direction == SignalDirection.SELL]),
                },
                'avg_active_confidence': (
                    sum(s.confidence for s in self.active_signals.values()) /
                    len(self.active_signals) if self.active_signals else 0
                ),
            }

    # ============================================================
    # WEBSOCKET FORMAT
    # ============================================================

    def format_for_websocket(self, signal: TradingSignal) -> str:
        """Format signal for WebSocket transmission."""
        return json.dumps({
            'event': 'signal',
            'channel': f'signals:{signal.symbol}',
            'data': signal.to_dict()
        })

    def get_websocket_channels(self) -> List[str]:
        """Get available WebSocket channels."""
        symbols = set(s.symbol for s in self.active_signals.values())
        channels = [f'signals:{sym}' for sym in symbols]
        channels.append('signals:all')
        channels.append('alerts')
        return channels
