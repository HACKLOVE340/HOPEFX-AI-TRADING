# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Real-Time Trading Signals API

Provides real-time trading signals with:
- Multi-strategy signal aggregation
- Confidence scoring
- Signal history and analytics
- WebSocket-ready event format
- Alert management
"""

import json
import logging
import threading
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Signal confidence thresholds
_CONF_VERY_STRONG = 0.8
_CONF_STRONG = 0.6
_CONF_MODERATE = 0.4
_CONF_WEAK = 0.2
_CONF_HIGH_PUSH = 0.70  # threshold for social-feed + FCM push
# Minimum sample size for distribution validation
_VALIDATION_MIN_SAMPLES = 30


class SignalStrength(Enum):
    """Signal strength levels."""

    VERY_STRONG = "very_strong"  # 0.8+
    STRONG = "strong"  # 0.6-0.8
    MODERATE = "moderate"  # 0.4-0.6
    WEAK = "weak"  # 0.2-0.4
    VERY_WEAK = "very_weak"  # 0-0.2


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
    strategies_agreeing: list[str]
    total_strategies: int
    regime: str  # Market regime
    session: str  # Trading session
    expiry: datetime
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "direction": self.direction.value,
            "strength": self.strength.value,
            "confidence": self.confidence,
            "price": self.price,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "risk_reward_ratio": self.risk_reward_ratio,
            "timeframe": self.timeframe,
            "strategies_agreeing": self.strategies_agreeing,
            "total_strategies": self.total_strategies,
            "regime": self.regime,
            "session": self.session,
            "expiry": self.expiry.isoformat(),
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
            "is_valid": self.is_valid,
        }

    @property
    def is_valid(self) -> bool:
        """Check if signal is still valid."""
        return datetime.now(UTC) < self.expiry

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict())


@dataclass
class SignalAlert:
    """Alert configuration for signals."""

    id: str
    symbol: str
    direction: SignalDirection | None = None
    min_confidence: float = 0.5
    min_strength: SignalStrength = SignalStrength.MODERATE
    notify_channels: list[str] = field(default_factory=lambda: ["web"])
    active: bool = True
    triggered_count: int = 0
    last_triggered: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


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
        self.signals_by_direction = {"buy": 0, "sell": 0, "hold": 0}
        self.signals_by_strength = {s.value: 0 for s in SignalStrength}
        self.signals_by_symbol = {}
        self.hit_rate = {"tp": 0, "sl": 0, "expired": 0}
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

    def to_dict(self) -> dict:
        total_outcomes = sum(self.hit_rate.values())
        return {
            "signals_generated": self.signals_generated,
            "signals_by_direction": self.signals_by_direction,
            "signals_by_strength": self.signals_by_strength,
            "signals_by_symbol": self.signals_by_symbol,
            "hit_rate": self.hit_rate,
            "tp_rate": self.hit_rate["tp"] / total_outcomes if total_outcomes > 0 else 0,
            "sl_rate": self.hit_rate["sl"] / total_outcomes if total_outcomes > 0 else 0,
            "avg_confidence": self.avg_confidence,
            "avg_rr_ratio": self.avg_rr_ratio,
            "hourly_distribution": self.hourly_distribution,
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

    def __init__(self, config: dict | None = None):
        """
        Initialize signal service.

        Args:
            config: Configuration options
        """
        self.config = config or {}

        # Signal storage
        self.active_signals: dict[str, TradingSignal] = {}
        self.signal_history: deque = deque(maxlen=1000)

        # Alerts
        self.alerts: dict[str, SignalAlert] = {}

        # Event subscribers
        self.subscribers: list[Callable] = []

        # Analytics
        self.analytics = SignalAnalytics()

        # Configuration
        self.signal_expiry_minutes = self.config.get("signal_expiry_minutes", 30)
        self.min_confidence = self.config.get("min_confidence", 0.3)
        # Default 1: a single strategy (or the ML engine) is enough to generate
        # a signal via the API. Raise via config for stricter multi-strategy consensus.
        self.min_strategies = self.config.get("min_strategies", 1)

        # Thread safety
        self._lock = threading.Lock()

        logger.info("Real-Time Signal Service initialized")

    def generate_signal(  # noqa: PLR0913
        self,
        symbol: str,
        direction: SignalDirection,
        confidence: float,
        price: float,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        timeframe: str,
        strategies_agreeing: list[str],
        total_strategies: int,
        regime: str = "unknown",
        session: str = "unknown",
        metadata: dict | None = None,
    ) -> TradingSignal | None:
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
            logger.debug("Signal rejected: confidence %s < %s", confidence, self.min_confidence)
            return None

        if len(strategies_agreeing) < self.min_strategies:
            logger.debug("Signal rejected: %s strategies < %s", len(strategies_agreeing), self.min_strategies)
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
        strength = self._calculate_strength(
            confidence,
            len(strategies_agreeing),
            total_strategies,
            rr_ratio,
        )

        # Create signal
        signal = TradingSignal(
            id=f"SIG-{symbol}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}",
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
            expiry=datetime.now(UTC) + timedelta(minutes=self.signal_expiry_minutes),
            metadata=metadata or {},
        )

        with self._lock:
            self.active_signals[signal.id] = signal
            self.signal_history.append(signal)
            self.analytics.record_signal(signal)

        # Publish event
        self._publish_event("signal_generated", signal)

        # Check alerts
        self._check_alerts(signal)

        # ── High-confidence pipeline: social feed + FCM push ─────────────────
        if confidence >= _CONF_HIGH_PUSH:
            self._publish_to_social_feed(signal)
            self._push_fcm_to_all_users(signal)

        logger.info("Signal generated: %s - %s %s @ %s", signal.id, direction.value, symbol, confidence)
        return signal

    def _publish_to_social_feed(self, signal: "TradingSignal") -> None:
        """Publish a high-confidence signal to the community social feed."""
        try:
            from api.social_feed import _publish_signal

            _publish_signal(
                signal={
                    "signal_id": signal.id,
                    "symbol": signal.symbol,
                    "direction": signal.direction.value.upper(),
                    "confidence": round(signal.confidence * 100, 1),
                    "entry_price": signal.entry_price,
                    "stop_loss": signal.stop_loss,
                    "take_profit": signal.take_profit,
                    "pnl": None,
                    "copies": 0,
                    "is_public": True,
                },
                username="HOPEFX AI",
                trader_id="ai_engine",
            )
            logger.debug("Signal %s published to social feed", signal.id)
        except Exception as exc:
            logger.debug("Social feed publish skipped: %s", exc)

    def _push_fcm_to_all_users(self, signal: "TradingSignal") -> None:
        """Send FCM push notification to all opted-in users for a high-confidence signal."""
        try:
            from api.social_feed import _opted_in
            from mobile.push_notifications import _device_tokens, push_manager

            # Send to users who have opted into the feed and have FCM tokens
            target_users = list(_opted_in) if _opted_in else list(_device_tokens.keys())
            for user_id in target_users:
                push_manager.send_new_signal(
                    user_id=user_id,
                    symbol=signal.symbol,
                    direction=signal.direction.value.upper(),
                    confidence=signal.confidence * 100,
                )
            if target_users:
                logger.debug("FCM signal push sent to %d users", len(target_users))
        except Exception as exc:
            logger.debug("FCM signal push skipped: %s", exc)

    def _calculate_strength(
        self,
        confidence: float,
        agreeing: int,
        total: int,
        rr_ratio: float,
    ) -> SignalStrength:
        """Calculate signal strength based on multiple factors."""

        # Calculate composite score
        strategy_agreement = agreeing / total if total > 0 else 0
        rr_score = min(rr_ratio / 3, 1.0)  # Normalize RR (3:1 = perfect)

        # Weighted score
        composite = (confidence * 0.5) + (strategy_agreement * 0.3) + (rr_score * 0.2)

        if composite >= _CONF_VERY_STRONG:
            return SignalStrength.VERY_STRONG
        if composite >= _CONF_STRONG:
            return SignalStrength.STRONG
        if composite >= _CONF_MODERATE:
            return SignalStrength.MODERATE
        if composite >= _CONF_WEAK:
            return SignalStrength.WEAK
        return SignalStrength.VERY_WEAK

    def get_active_signals(
        self,
        symbol: str | None = None,
        direction: SignalDirection | None = None,
        min_strength: SignalStrength | None = None,
    ) -> list[TradingSignal]:
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

    def get_signal(self, signal_id: str) -> TradingSignal | None:
        """Get signal by ID."""
        return self.active_signals.get(signal_id)

    def expire_signal(self, signal_id: str):
        """Manually expire a signal."""
        with self._lock:
            if signal_id in self.active_signals:
                signal = self.active_signals[signal_id]
                signal.expiry = datetime.now(UTC)
                del self.active_signals[signal_id]
                self.analytics.record_outcome("expired")
                self._publish_event("signal_expired", signal)

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

                self._publish_event(
                    "signal_closed",
                    {
                        "signal": signal.to_dict(),
                        "outcome": outcome,
                        "exit_price": exit_price,
                    },
                )

    # ============================================================
    # ALERTS
    # ============================================================

    def create_alert(
        self,
        symbol: str,
        direction: SignalDirection | None = None,
        min_confidence: float = 0.5,
        min_strength: SignalStrength = SignalStrength.MODERATE,
        notify_channels: list[str] | None = None,
    ) -> SignalAlert:
        """Create a signal alert."""
        alert = SignalAlert(
            id=str(uuid.uuid4()),
            symbol=symbol,
            direction=direction,
            min_confidence=min_confidence,
            min_strength=min_strength,
            notify_channels=notify_channels or ["web"],
        )

        with self._lock:
            self.alerts[alert.id] = alert

        logger.info("Alert created: %s for %s", alert.id, symbol)

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
            alert.last_triggered = datetime.now(UTC)

            self._publish_event(
                "alert_triggered",
                {"alert": asdict(alert), "signal": signal.to_dict()},
            )

            logger.info("Alert triggered: %s by signal %s", alert.id, signal.id)

    def delete_alert(self, alert_id: str):
        """Delete an alert."""
        with self._lock:
            if alert_id in self.alerts:
                del self.alerts[alert_id]

    def get_alerts(self, symbol: str | None = None) -> list[SignalAlert]:
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
        logger.debug("New subscriber added. Total: %s", len(self.subscribers))

    def unsubscribe(self, callback: Callable):
        """Unsubscribe from signal events."""
        if callback in self.subscribers:
            self.subscribers.remove(callback)

    def _publish_event(self, event_type: str, data: Any):
        """Publish event to all subscribers."""
        event = {
            "type": event_type,
            "timestamp": datetime.now(UTC).isoformat(),
            "data": data.to_dict() if hasattr(data, "to_dict") else data,
        }

        for callback in self.subscribers:
            try:
                callback(event_type, event)
            except Exception as e:
                logger.error("Error in subscriber callback: %s", e)

    # ============================================================
    # HISTORY & ANALYTICS
    # ============================================================

    def get_signal_history(
        self,
        symbol: str | None = None,
        hours: int = 24,
    ) -> list[TradingSignal]:
        """Get signal history."""
        cutoff = datetime.now(UTC) - timedelta(hours=hours)
        signals = [s for s in self.signal_history if s.timestamp > cutoff]

        if symbol:
            signals = [s for s in signals if s.symbol == symbol]

        return sorted(signals, key=lambda s: -s.timestamp.timestamp())

    def get_analytics(self) -> dict:
        """Get signal analytics."""
        return self.analytics.to_dict()

    def get_signal_summary(self) -> dict:
        """Get summary of current signal state."""
        with self._lock:
            return {
                "active_signals": len(self.active_signals),
                "signals_last_hour": len(
                    [s for s in self.signal_history if s.timestamp > datetime.now(UTC) - timedelta(hours=1)],
                ),
                "signals_last_24h": len(
                    [s for s in self.signal_history if s.timestamp > datetime.now(UTC) - timedelta(hours=24)],
                ),
                "active_alerts": len([a for a in self.alerts.values() if a.active]),
                "symbols_with_signals": list(
                    {s.symbol for s in self.active_signals.values()},
                ),
                "direction_distribution": {
                    "buy": len(
                        [s for s in self.active_signals.values() if s.direction == SignalDirection.BUY],
                    ),
                    "sell": len(
                        [s for s in self.active_signals.values() if s.direction == SignalDirection.SELL],
                    ),
                },
                "avg_active_confidence": (
                    sum(s.confidence for s in self.active_signals.values()) / len(self.active_signals)
                    if self.active_signals
                    else 0
                ),
            }

    # ============================================================
    # WEBSOCKET FORMAT
    # ============================================================

    def format_for_websocket(self, signal: TradingSignal) -> str:
        """Format signal for WebSocket transmission."""
        return json.dumps(
            {
                "event": "signal",
                "channel": f"signals:{signal.symbol}",
                "data": signal.to_dict(),
            },
        )

    def get_websocket_channels(self) -> list[str]:
        """Get available WebSocket channels."""
        symbols = {s.symbol for s in self.active_signals.values()}
        channels = [f"signals:{sym}" for sym in symbols]
        channels.append("signals:all")
        channels.append("alerts")
        return channels

    def ingest_engine_signal(self, payload: dict[str, Any]) -> Optional["TradingSignal"]:
        """
        Ingest a signal dict produced by core/signal_engine.py and store it in
        the ring buffer so /api/signals/latest reflects engine-generated signals.

        Parameters
        ----------
        payload:
            Dict with keys: symbol, direction, confidence, probability,
            entry_price, stop_loss, take_profit, timestamp, source.

        Returns the created TradingSignal or None on failure.
        """
        try:
            direction_str = payload.get("direction", "hold").lower()
            try:
                direction = SignalDirection(direction_str)
            except ValueError:
                direction = SignalDirection.HOLD

            confidence = float(payload.get("confidence", 0.0))
            entry = float(payload.get("entry_price") or 0.0)
            sl = payload.get("stop_loss")
            tp = payload.get("take_profit")

            # Derive SL/TP from entry if not provided (0.5% conservative default)
            if sl is None:
                sl = round(entry * 0.995, 5) if direction == SignalDirection.BUY else round(entry * 1.005, 5)
            if tp is None:
                tp = round(entry * 1.015, 5) if direction == SignalDirection.BUY else round(entry * 0.985, 5)

            rr = abs(float(tp) - entry) / max(abs(entry - float(sl)), 1e-9)

            strength = (
                SignalStrength.VERY_STRONG
                if confidence >= _CONF_VERY_STRONG
                else SignalStrength.STRONG
                if confidence >= _CONF_STRONG
                else SignalStrength.MODERATE
                if confidence >= _CONF_MODERATE
                else SignalStrength.WEAK
            )

            signal = TradingSignal(
                id=f"eng_{payload.get('symbol', 'UNK')}_{int(datetime.now(UTC).timestamp())}",
                symbol=payload.get("symbol", "UNKNOWN"),
                direction=direction,
                strength=strength,
                confidence=confidence,
                price=entry,
                entry_price=entry,
                stop_loss=float(sl),
                take_profit=float(tp),
                risk_reward_ratio=round(rr, 2),
                timeframe="1m",
                strategies_agreeing=["signal_engine"],
                total_strategies=1,
                regime=payload.get("regime", "unknown"),
                session="live",
                expiry=datetime.now(UTC)
                .replace(second=0, microsecond=0)
                .__class__.fromtimestamp(datetime.now(UTC).timestamp() + 1800, tz=UTC),
                metadata={
                    "probability": payload.get("probability"),
                    "model_version": payload.get("model_version"),
                    "source": payload.get("source", "signal_engine"),
                },
            )

            with self._lock:
                self.signal_history.appendleft(signal)
                self.active_signals[signal.id] = signal

            return signal
        except Exception as exc:
            logger.debug("ingest_engine_signal failed: %s", exc)
            return None


# ─────────────────────────────────────────────────────────────
# FastAPI router — exposes RealTimeSignalService via REST
# ─────────────────────────────────────────────────────────────

_signal_service: Optional["RealTimeSignalService"] = None


def _get_signal_service() -> "RealTimeSignalService":
    """Lazily create / return the singleton signal service."""
    global _signal_service
    if _signal_service is None:
        _signal_service = RealTimeSignalService()
    return _signal_service


def _register_signal_read_routes(router: Any) -> None:
    """Register read-only signal GET endpoints."""
    @router.get("/summary")
    async def get_signal_summary():
        return _get_signal_service().get_signal_summary()

    @router.get("/latest")
    async def get_latest_signals(symbol: str | None = None, limit: int = 10):
        svc = _get_signal_service()
        signals = svc.get_signal_history(symbol=symbol, hours=24)[:limit]
        return {"signals": [s.to_dict() for s in signals], "count": len(signals), "symbol_filter": symbol}

    @router.get("/active")
    async def get_active_signals(symbol: str | None = None):
        signals = _get_signal_service().get_active_signals(symbol=symbol)
        return {"signals": [s.to_dict() for s in signals], "count": len(signals)}

    @router.get("/history")
    async def get_signal_history(symbol: str | None = None, hours: int = 24):
        signals = _get_signal_service().get_signal_history(symbol=symbol, hours=hours)
        return {"signals": [s.to_dict() for s in signals], "count": len(signals)}

    @router.get("/analytics")
    async def get_signal_analytics():
        return _get_signal_service().get_analytics()

    @router.get("/channels")
    async def get_websocket_channels():
        return {"channels": _get_signal_service().get_websocket_channels()}

    @router.get("/engine")
    async def get_engine_status():
        except Exception:
            logger.exception("Failed to get signal engine status")
            engine_status = {
                "status": "unavailable",
                "error": "Signal engine status is temporarily unavailable."
            }
            engine_status = get_signal_engine_status()
        except Exception as exc:
            engine_status = {"error": str(exc)}
        return {
            "engine": engine_status,
            "recent_engine_signals": engine_signals,
            "recent_engine_signal_count": len(engine_signals),
        }
        recent = svc.get_signal_history(hours=1)
        engine_signals = [s.to_dict() for s in recent if s.metadata.get("source") == "signal_engine"][:10]
        return {"engine": engine_status, "recent_engine_signals": engine_signals, "recent_engine_signal_count": len(engine_signals)}


def _register_signal_write_routes(router: Any) -> None:  # noqa: C901
    """Register signal generation, alert, and distribution write endpoints."""
    from fastapi import HTTPException as _HTTPException

    @router.post("/generate")
    async def generate_signal(req: _GenerateSignalRequest):
        try:
            svc = _get_signal_service()
            try:
                direction = SignalDirection(req.direction.lower())
            except ValueError:
                raise _HTTPException(status_code=422, detail=f"Invalid direction: '{req.direction}'. Use 'buy' or 'sell'.") from None
            entry = req.entry_price if req.entry_price is not None else req.price
            if direction == SignalDirection.BUY:
                sl = req.stop_loss if req.stop_loss is not None else round(entry * 0.995, 5)
                tp = req.take_profit if req.take_profit is not None else round(entry * 1.015, 5)
            else:
                sl = req.stop_loss if req.stop_loss is not None else round(entry * 1.005, 5)
                tp = req.take_profit if req.take_profit is not None else round(entry * 0.985, 5)

            # Ensure at least one strategy name is present so min_strategies
            # check passes for direct API calls (e.g. from the frontend or tests).
            strategies = req.strategies_agreeing or ["api_signal"]
            signal = svc.generate_signal(symbol=req.symbol, direction=direction, confidence=req.confidence, price=req.price, entry_price=entry, stop_loss=sl, take_profit=tp, timeframe=req.timeframe, strategies_agreeing=strategies, total_strategies=max(req.total_strategies, len(strategies)), regime=req.regime, session=req.session, metadata=req.parameters or {})
            if signal is None:
                return {"signal": None, "message": "No signal generated (confidence or strategy threshold not met)"}
            return {"signal": signal.to_dict()}
        except _HTTPException:
            raise
        except Exception:
            logger.exception("Signal generation failed: %s")
            raise HTTPException(
                status_code=500,
                detail="Signal generation failed",
            ) from None

    @router.post("/alerts")
    async def create_alert(req: _CreateAlertRequest):
        try:
            svc = _get_signal_service()
            notify_channels = ["web"]
            if req.notify_webhook:
                notify_channels.append(req.notify_webhook)
            alert = svc.create_alert(
                symbol=req.symbol,
                direction=req.direction,
                min_confidence=req.min_confidence,
                notify_channels=notify_channels,
            )
            return {"alert_id": alert.id, "status": "created"}
        except Exception as e:
            logger.error("Alert creation failed: %s", e)
            raise HTTPException(status_code=500, detail="Alert creation failed — check server logs") from e

    @router.get("/alerts")
    async def list_alerts(symbol: str | None = None):
        alerts = _get_signal_service().get_alerts(symbol=symbol)
        return {"alerts": [{"id": a.id, "symbol": a.symbol, "direction": a.direction, "min_confidence": a.min_confidence, "active": a.active, "created_at": a.created_at.isoformat()} for a in alerts], "count": len(alerts)}

    @router.delete("/alerts/{alert_id}")
    async def delete_alert(alert_id: str):
        _get_signal_service().delete_alert(alert_id)
        return {"status": "deleted", "alert_id": alert_id}

    @signals_router.get("/channels")
    async def get_websocket_channels():
        """List available WebSocket channel names for signal subscriptions."""
        return {"channels": _get_signal_service().get_websocket_channels()}

    @signals_router.get("/engine")
    async def get_engine_status():
        """
        Return the live signal engine health and Phase 1–4 store status.

        Includes:
        - ml_available, symbols, interval_seconds, auto_trade flag
        - phase1_mtf: MTF fusion store status
        - phase2_anomaly: anomaly detection store status
        - phase3_online: Phase-3 OnlineLearnerStore status
        - phase4_deep: deep ensemble store status
        - recent_signals: last 10 engine-generated signals from the ring buffer
        """
        try:
            from core.signal_engine import get_signal_engine_status

            engine_status = get_signal_engine_status()
        except Exception as exc:
            logger.warning("get_signal_engine_status failed: %s", exc)
            engine_status = {"error": "Signal engine unavailable — check server logs"}

        # Pull the last 10 engine-generated signals from the ring buffer
        svc = _get_signal_service()
        recent = svc.get_signal_history(hours=1)
        engine_signals = [s.to_dict() for s in recent if s.metadata.get("source") == "signal_engine"][:10]

        return {
            "engine": engine_status,
            "recent_engine_signals": engine_signals,
            "recent_engine_signal_count": len(engine_signals),
        }


def _register_distribution_routes(router: Any, OOSSignalItem: Any, LiveSignalItem: Any, SetOOSReferenceRequest: Any, ValidateSignalsRequest: Any) -> None:
    """Register signal distribution validation endpoints."""
    @router.post("/distribution/oos-reference")
    async def set_oos_reference(body: SetOOSReferenceRequest):
        from ml.signal_validator import SignalRecord, get_validator
        validator = get_validator()
        records = [SignalRecord(direction=s.direction, confidence=s.confidence, raw_score=s.raw_score) for s in body.signals]
        validator.set_oos_reference(records)
        return {"set": True, "oos_sample_size": len(records)}

    @router.post("/distribution/validate")
    async def validate_signal_distribution(body: ValidateSignalsRequest):
        from ml.signal_validator import SignalRecord, get_validator
        validator = get_validator()
        live_records = [SignalRecord(direction=s.direction, confidence=s.confidence, raw_score=s.raw_score) for s in body.live_signals] if body.live_signals is not None else None
        return validator.validate(live_records).to_dict()

    @router.post("/distribution/add-live")
    async def add_live_signal(body: LiveSignalItem):
        from ml.signal_validator import SignalRecord, get_validator
        validator = get_validator()
        validator.add_live_signal(SignalRecord(direction=body.direction, confidence=body.confidence, raw_score=body.raw_score))
        return {"buffered": True, "buffer_size": len(validator._live_signals)}

    @router.get("/distribution/status")
    async def signal_distribution_status():
        from ml.signal_validator import get_validator
        validator = get_validator()
        report = (
            validator.validate()
            if (
                len(validator._oos_signals) >= _VALIDATION_MIN_SAMPLES
                and len(validator._live_signals) >= _VALIDATION_MIN_SAMPLES
            )
            else None
        )
        return {
            "oos_sample_size": len(validator._oos_signals),
            "live_buffer_size": len(validator._live_signals),
            "validation": report.to_dict() if report else None,
        }

def create_signals_router():
    """Build and return a FastAPI APIRouter with all signal endpoints."""
    try:
        from fastapi import APIRouter
    except ImportError:
        logger.warning("FastAPI not available; signals router not created.")
        return None

    signals_router = APIRouter(prefix="/api/signals", tags=["Signals"])
    _register_signal_read_routes(signals_router)
    _register_signal_write_routes(signals_router)
    return signals_router
