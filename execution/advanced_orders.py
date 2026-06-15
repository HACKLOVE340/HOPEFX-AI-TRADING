# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
execution/advanced_orders.py
=============================
Advanced Order Types — OCO, Trailing Stop, and Stop-Limit orders.

Provides native broker-level order management for complex order types that
reduce slippage risk by executing at the broker's matching engine rather
than relying on in-memory monitoring.

Order Types
-----------
OCO (One-Cancels-the-Other)
    Pairs a stop-loss and take-profit order. When one fills, the other is
    automatically cancelled. Eliminates the latency risk of polling-based
    SL/TP management.

TrailingStop
    A dynamic stop-loss that follows the price by a fixed distance (in pips
    or percentage). Locks in profits as the market moves favorably while
    protecting against reversals.

StopLimit
    A stop order that becomes a limit order once the stop price is reached.
    Provides price certainty at the cost of fill certainty.

Architecture
------------
- AdvancedOrderManager: manages lifecycle of all advanced orders.
- BrokerOrderAdapter: translates HOPEFX orders into broker-native formats.
- Fallback: if broker doesn't support native OCO/trailing, falls back to
  in-memory monitoring with the SL/TP monitor.

Usage
-----
    from execution.advanced_orders import get_advanced_order_manager

    manager = get_advanced_order_manager()
    await manager.start(broker=broker_instance, event_bus=bus)

    # Submit OCO (simultaneous SL + TP)
    oco_id = await manager.submit_oco(
        position_id="pos_123",
        symbol="XAU_USD",
        side="SELL",  # closing side
        quantity=1.0,
        stop_loss_price=1920.50,
        take_profit_price=1945.00,
    )

    # Submit Trailing Stop
    trail_id = await manager.submit_trailing_stop(
        position_id="pos_456",
        symbol="XAU_USD",
        side="SELL",
        quantity=1.0,
        trail_distance_pips=50.0,
        activation_price=1935.00,
    )
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

UTC = timezone.utc
logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

import os

_MONITOR_INTERVAL_MS = int(os.getenv("ADV_ORDER_MONITOR_INTERVAL_MS", "100"))
_MAX_RETRIES = int(os.getenv("ADV_ORDER_MAX_RETRIES", "3"))
_RETRY_DELAY_S = float(os.getenv("ADV_ORDER_RETRY_DELAY_S", "0.5"))

# ── Prometheus metrics ────────────────────────────────────────────────────────

try:
    from prometheus_client import Counter, Histogram

    _oco_submitted = Counter(
        "hopefx_oco_orders_submitted_total",
        "OCO orders submitted",
    )
    _oco_filled = Counter(
        "hopefx_oco_orders_filled_total",
        "OCO orders filled",
        ["fill_type"],  # "stop_loss" or "take_profit"
    )
    _trailing_stops_submitted = Counter(
        "hopefx_trailing_stops_submitted_total",
        "Trailing stop orders submitted",
    )
    _trailing_stops_triggered = Counter(
        "hopefx_trailing_stops_triggered_total",
        "Trailing stop orders triggered",
    )
    _order_latency = Histogram(
        "hopefx_advanced_order_latency_seconds",
        "Latency of advanced order operations",
        ["order_type"],
    )
    _PROM_OK = True
except Exception:
    _PROM_OK = False


# ── Enums ─────────────────────────────────────────────────────────────────────


class AdvancedOrderType(Enum):
    OCO = "oco"
    TRAILING_STOP = "trailing_stop"
    STOP_LIMIT = "stop_limit"


class AdvancedOrderState(Enum):
    PENDING = "pending"
    ACTIVE = "active"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    FAILED = "failed"
    EXPIRED = "expired"


class FillType(Enum):
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    TRAILING_STOP = "trailing_stop"
    STOP_LIMIT = "stop_limit"


# ── Data Models ───────────────────────────────────────────────────────────────


@dataclass
class OCOOrder:
    """One-Cancels-the-Other order pairing SL and TP."""

    order_id: str
    position_id: str
    symbol: str
    side: str  # closing side
    quantity: float
    stop_loss_price: float
    take_profit_price: float
    state: AdvancedOrderState = AdvancedOrderState.PENDING
    broker_sl_order_id: str | None = None
    broker_tp_order_id: str | None = None
    fill_type: FillType | None = None
    fill_price: float | None = None
    filled_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    slippage: float = 0.0
    native_broker_support: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "type": AdvancedOrderType.OCO.value,
            "position_id": self.position_id,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "stop_loss_price": self.stop_loss_price,
            "take_profit_price": self.take_profit_price,
            "state": self.state.value,
            "broker_sl_order_id": self.broker_sl_order_id,
            "broker_tp_order_id": self.broker_tp_order_id,
            "fill_type": self.fill_type.value if self.fill_type else None,
            "fill_price": self.fill_price,
            "filled_at": self.filled_at.isoformat() if self.filled_at else None,
            "created_at": self.created_at.isoformat(),
            "slippage": self.slippage,
            "native_broker_support": self.native_broker_support,
        }


@dataclass
class TrailingStopOrder:
    """Dynamic stop-loss that follows price movement."""

    order_id: str
    position_id: str
    symbol: str
    side: str  # closing side
    quantity: float
    trail_distance_pips: float
    activation_price: float | None = None  # Only activate trailing after this price
    current_stop_price: float = 0.0
    highest_price: float = 0.0  # For BUY positions (trailing sell stop)
    lowest_price: float = float("inf")  # For SELL positions (trailing buy stop)
    state: AdvancedOrderState = AdvancedOrderState.PENDING
    broker_order_id: str | None = None
    fill_price: float | None = None
    filled_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    activated: bool = False
    native_broker_support: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "type": AdvancedOrderType.TRAILING_STOP.value,
            "position_id": self.position_id,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "trail_distance_pips": self.trail_distance_pips,
            "activation_price": self.activation_price,
            "current_stop_price": self.current_stop_price,
            "highest_price": self.highest_price,
            "lowest_price": self.lowest_price if self.lowest_price != float("inf") else None,
            "state": self.state.value,
            "broker_order_id": self.broker_order_id,
            "fill_price": self.fill_price,
            "filled_at": self.filled_at.isoformat() if self.filled_at else None,
            "created_at": self.created_at.isoformat(),
            "activated": self.activated,
            "native_broker_support": self.native_broker_support,
        }


@dataclass
class StopLimitOrder:
    """Stop order that becomes a limit order at the stop price."""

    order_id: str
    position_id: str
    symbol: str
    side: str
    quantity: float
    stop_price: float  # Trigger price
    limit_price: float  # Limit price once triggered
    state: AdvancedOrderState = AdvancedOrderState.PENDING
    triggered: bool = False
    broker_order_id: str | None = None
    fill_price: float | None = None
    filled_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    native_broker_support: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "type": AdvancedOrderType.STOP_LIMIT.value,
            "position_id": self.position_id,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "stop_price": self.stop_price,
            "limit_price": self.limit_price,
            "state": self.state.value,
            "triggered": self.triggered,
            "broker_order_id": self.broker_order_id,
            "fill_price": self.fill_price,
            "filled_at": self.filled_at.isoformat() if self.filled_at else None,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "native_broker_support": self.native_broker_support,
        }


# ── Broker Order Adapter ─────────────────────────────────────────────────────


class BrokerOrderAdapter:
    """
    Translates HOPEFX advanced orders into broker-native formats.

    Detects broker capabilities and uses native OCO/trailing stop support
    when available. Falls back to in-memory monitoring otherwise.
    """

    def __init__(self, broker: Any) -> None:
        self._broker = broker
        self._capabilities = self._detect_capabilities()

    def _detect_capabilities(self) -> dict[str, bool]:
        """Detect which advanced order types the broker supports natively."""
        caps = {
            "native_oco": False,
            "native_trailing_stop": False,
            "native_stop_limit": False,
        }

        if self._broker is None:
            return caps

        # Check for native OCO support
        if hasattr(self._broker, "place_oco_order"):
            caps["native_oco"] = True

        # Check for native trailing stop support
        if hasattr(self._broker, "place_trailing_stop"):
            caps["native_trailing_stop"] = True

        # Check for native stop-limit support
        if hasattr(self._broker, "place_stop_limit"):
            caps["native_stop_limit"] = True

        logger.info("BrokerOrderAdapter capabilities: %s", caps)
        return caps

    @property
    def supports_native_oco(self) -> bool:
        return self._capabilities.get("native_oco", False)

    @property
    def supports_native_trailing_stop(self) -> bool:
        return self._capabilities.get("native_trailing_stop", False)

    @property
    def supports_native_stop_limit(self) -> bool:
        return self._capabilities.get("native_stop_limit", False)

    async def submit_native_oco(
        self,
        symbol: str,
        side: str,
        quantity: float,
        stop_loss_price: float,
        take_profit_price: float,
    ) -> tuple[str, str]:
        """Submit OCO order natively to broker. Returns (sl_order_id, tp_order_id)."""
        result = await self._broker.place_oco_order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
        )
        return result["sl_order_id"], result["tp_order_id"]

    async def submit_native_trailing_stop(
        self,
        symbol: str,
        side: str,
        quantity: float,
        trail_distance_pips: float,
        activation_price: float | None = None,
    ) -> str:
        """Submit trailing stop natively to broker. Returns order_id."""
        result = await self._broker.place_trailing_stop(
            symbol=symbol,
            side=side,
            quantity=quantity,
            trail_distance=trail_distance_pips,
            activation_price=activation_price,
        )
        return result["order_id"]

    async def submit_native_stop_limit(
        self,
        symbol: str,
        side: str,
        quantity: float,
        stop_price: float,
        limit_price: float,
    ) -> str:
        """Submit stop-limit natively to broker. Returns order_id."""
        result = await self._broker.place_stop_limit(
            symbol=symbol,
            side=side,
            quantity=quantity,
            stop_price=stop_price,
            limit_price=limit_price,
        )
        return result["order_id"]

    async def submit_market_close(
        self,
        symbol: str,
        side: str,
        quantity: float,
    ) -> dict[str, Any]:
        """Submit a market close order (fallback execution)."""
        if hasattr(self._broker, "place_order"):
            return await self._broker.place_order(
                symbol=symbol,
                side=side,
                quantity=quantity,
                order_type="market",
            )
        raise RuntimeError("Broker does not support place_order")

    async def cancel_order(self, broker_order_id: str) -> bool:
        """Cancel an order on the broker."""
        if hasattr(self._broker, "cancel_order"):
            await self._broker.cancel_order(broker_order_id)
            return True
        return False


# ── Advanced Order Manager ────────────────────────────────────────────────────


class AdvancedOrderManager:
    """
    Manages the lifecycle of all advanced order types.

    Responsibilities:
    - Submit OCO, Trailing Stop, and Stop-Limit orders
    - Monitor prices and trigger orders when broker doesn't support natively
    - Publish fill events to the EventBus
    - Track order performance metrics (slippage, latency)
    """

    def __init__(self) -> None:
        self._oco_orders: dict[str, OCOOrder] = {}
        self._trailing_orders: dict[str, TrailingStopOrder] = {}
        self._stop_limit_orders: dict[str, StopLimitOrder] = {}
        self._adapter: BrokerOrderAdapter | None = None
        self._event_bus: Any = None
        self._running = False
        self._monitor_task: asyncio.Task | None = None
        self._latest_prices: dict[str, float] = {}  # symbol -> mid price
        self._lock = asyncio.Lock()

    async def start(self, broker: Any = None, event_bus: Any = None) -> None:
        """Initialize the manager with broker and event bus connections."""
        self._adapter = BrokerOrderAdapter(broker) if broker else None
        self._event_bus = event_bus
        self._running = True

        # Start the price monitor for non-native order types
        self._monitor_task = asyncio.create_task(self._price_monitor_loop())

        # Subscribe to tick events for price updates
        if self._event_bus:
            try:
                from core.event_bus import CH_TICK

                self._event_bus.subscribe_local(CH_TICK, self._on_tick)
            except ImportError:
                logger.debug("EventBus not available for tick subscription")

        logger.info(
            "AdvancedOrderManager started: native_oco=%s native_trailing=%s native_stop_limit=%s",
            self._adapter.supports_native_oco if self._adapter else False,
            self._adapter.supports_native_trailing_stop if self._adapter else False,
            self._adapter.supports_native_stop_limit if self._adapter else False,
        )

    async def stop(self) -> None:
        """Graceful shutdown."""
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._monitor_task
        logger.info("AdvancedOrderManager stopped")

    # ── Tick handler ──────────────────────────────────────────────────────────

    def _on_tick(self, message: dict) -> None:
        """Update latest prices from tick events."""
        symbol = message.get("symbol", "")
        mid = message.get("mid")
        if symbol and mid is not None:
            self._latest_prices[symbol] = float(mid)

    # ── OCO Orders ────────────────────────────────────────────────────────────

    async def submit_oco(
        self,
        position_id: str,
        symbol: str,
        side: str,
        quantity: float,
        stop_loss_price: float,
        take_profit_price: float,
    ) -> str:
        """
        Submit an OCO (One-Cancels-the-Other) order.

        If the broker supports native OCO, submits directly.
        Otherwise, manages both legs in-memory with tick monitoring.
        """
        order_id = f"oco_{uuid.uuid4().hex[:12]}"
        start_time = time.monotonic()

        order = OCOOrder(
            order_id=order_id,
            position_id=position_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
        )

        # Try native broker OCO first
        if self._adapter and self._adapter.supports_native_oco:
            try:
                sl_id, tp_id = await self._adapter.submit_native_oco(
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    stop_loss_price=stop_loss_price,
                    take_profit_price=take_profit_price,
                )
                order.broker_sl_order_id = sl_id
                order.broker_tp_order_id = tp_id
                order.native_broker_support = True
                order.state = AdvancedOrderState.ACTIVE
                logger.info(
                    "OCO submitted natively: order_id=%s sl_broker=%s tp_broker=%s",
                    order_id,
                    sl_id,
                    tp_id,
                )
            except Exception as exc:
                logger.warning("Native OCO submission failed, falling back to in-memory: %s", exc)
                order.state = AdvancedOrderState.ACTIVE
                order.native_broker_support = False
        else:
            order.state = AdvancedOrderState.ACTIVE
            order.native_broker_support = False

        async with self._lock:
            self._oco_orders[order_id] = order

        if _PROM_OK:
            _oco_submitted.inc()
            _order_latency.labels(order_type="oco").observe(time.monotonic() - start_time)

        return order_id

    # ── Trailing Stop Orders ──────────────────────────────────────────────────

    async def submit_trailing_stop(
        self,
        position_id: str,
        symbol: str,
        side: str,
        quantity: float,
        trail_distance_pips: float,
        activation_price: float | None = None,
    ) -> str:
        """
        Submit a trailing stop order.

        The stop price follows the market price by trail_distance_pips.
        If activation_price is set, trailing only begins after that price is reached.
        """
        order_id = f"trail_{uuid.uuid4().hex[:12]}"
        start_time = time.monotonic()

        order = TrailingStopOrder(
            order_id=order_id,
            position_id=position_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            trail_distance_pips=trail_distance_pips,
            activation_price=activation_price,
        )

        # Initialize with current price if available
        current_price = self._latest_prices.get(symbol)
        if current_price:
            if side.upper() == "SELL":
                # Long position — trailing sell stop below price
                order.highest_price = current_price
                order.current_stop_price = current_price - (trail_distance_pips * 0.01)
            else:
                # Short position — trailing buy stop above price
                order.lowest_price = current_price
                order.current_stop_price = current_price + (trail_distance_pips * 0.01)

        # Try native broker trailing stop
        if self._adapter and self._adapter.supports_native_trailing_stop:
            try:
                broker_id = await self._adapter.submit_native_trailing_stop(
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    trail_distance_pips=trail_distance_pips,
                    activation_price=activation_price,
                )
                order.broker_order_id = broker_id
                order.native_broker_support = True
                order.state = AdvancedOrderState.ACTIVE
                order.activated = activation_price is None
            except Exception as exc:
                logger.warning("Native trailing stop failed, falling back to in-memory: %s", exc)
                order.state = AdvancedOrderState.ACTIVE
                order.native_broker_support = False
                order.activated = activation_price is None
        else:
            order.state = AdvancedOrderState.ACTIVE
            order.native_broker_support = False
            order.activated = activation_price is None

        async with self._lock:
            self._trailing_orders[order_id] = order

        if _PROM_OK:
            _trailing_stops_submitted.inc()
            _order_latency.labels(order_type="trailing_stop").observe(time.monotonic() - start_time)

        return order_id

    # ── Stop-Limit Orders ─────────────────────────────────────────────────────

    async def submit_stop_limit(
        self,
        position_id: str,
        symbol: str,
        side: str,
        quantity: float,
        stop_price: float,
        limit_price: float,
        expires_at: datetime | None = None,
    ) -> str:
        """
        Submit a stop-limit order.

        When price reaches stop_price, a limit order at limit_price is placed.
        """
        order_id = f"stoplim_{uuid.uuid4().hex[:12]}"
        start_time = time.monotonic()

        order = StopLimitOrder(
            order_id=order_id,
            position_id=position_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            stop_price=stop_price,
            limit_price=limit_price,
            expires_at=expires_at,
        )

        # Try native broker stop-limit
        if self._adapter and self._adapter.supports_native_stop_limit:
            try:
                broker_id = await self._adapter.submit_native_stop_limit(
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    stop_price=stop_price,
                    limit_price=limit_price,
                )
                order.broker_order_id = broker_id
                order.native_broker_support = True
                order.state = AdvancedOrderState.ACTIVE
            except Exception as exc:
                logger.warning("Native stop-limit failed, falling back to in-memory: %s", exc)
                order.state = AdvancedOrderState.ACTIVE
                order.native_broker_support = False
        else:
            order.state = AdvancedOrderState.ACTIVE
            order.native_broker_support = False

        async with self._lock:
            self._stop_limit_orders[order_id] = order

        if _PROM_OK:
            _order_latency.labels(order_type="stop_limit").observe(time.monotonic() - start_time)

        return order_id

    # ── Cancel ────────────────────────────────────────────────────────────────

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an active advanced order."""
        async with self._lock:
            # Check OCO orders
            if order_id in self._oco_orders:
                order = self._oco_orders[order_id]
                if order.state == AdvancedOrderState.ACTIVE:
                    order.state = AdvancedOrderState.CANCELLED
                    # Cancel broker orders if native
                    if order.native_broker_support and self._adapter:
                        if order.broker_sl_order_id:
                            await self._adapter.cancel_order(order.broker_sl_order_id)
                        if order.broker_tp_order_id:
                            await self._adapter.cancel_order(order.broker_tp_order_id)
                    return True

            # Check trailing stop orders
            if order_id in self._trailing_orders:
                order = self._trailing_orders[order_id]
                if order.state == AdvancedOrderState.ACTIVE:
                    order.state = AdvancedOrderState.CANCELLED
                    if order.native_broker_support and self._adapter and order.broker_order_id:
                        await self._adapter.cancel_order(order.broker_order_id)
                    return True

            # Check stop-limit orders
            if order_id in self._stop_limit_orders:
                order = self._stop_limit_orders[order_id]
                if order.state == AdvancedOrderState.ACTIVE:
                    order.state = AdvancedOrderState.CANCELLED
                    if order.native_broker_support and self._adapter and order.broker_order_id:
                        await self._adapter.cancel_order(order.broker_order_id)
                    return True

        return False

    # ── Price Monitor Loop ────────────────────────────────────────────────────

    async def _price_monitor_loop(self) -> None:
        """
        Background loop that monitors prices for non-native orders.

        Checks OCO, trailing stop, and stop-limit orders against latest prices
        and triggers execution when conditions are met.
        """
        interval_s = _MONITOR_INTERVAL_MS / 1000.0

        while self._running:
            try:
                await self._check_oco_orders()
                await self._check_trailing_orders()
                await self._check_stop_limit_orders()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("AdvancedOrderManager monitor error: %s", exc)

            await asyncio.sleep(interval_s)

    async def _check_oco_orders(self) -> None:
        """Check OCO orders against current prices."""
        async with self._lock:
            for order in list(self._oco_orders.values()):
                if order.state != AdvancedOrderState.ACTIVE:
                    continue
                if order.native_broker_support:
                    continue  # Broker handles it

                price = self._latest_prices.get(order.symbol)
                if price is None:
                    continue

                triggered = False
                fill_type = None

                if order.side.upper() == "SELL":
                    # Long position: SL below entry, TP above entry
                    if price <= order.stop_loss_price:
                        triggered = True
                        fill_type = FillType.STOP_LOSS
                    elif price >= order.take_profit_price:
                        triggered = True
                        fill_type = FillType.TAKE_PROFIT
                # Short position: SL above entry, TP below entry
                elif price >= order.stop_loss_price:
                    triggered = True
                    fill_type = FillType.STOP_LOSS
                elif price <= order.take_profit_price:
                    triggered = True
                    fill_type = FillType.TAKE_PROFIT

                if triggered and fill_type:
                    await self._execute_oco_fill(order, price, fill_type)

    async def _check_trailing_orders(self) -> None:
        """Check trailing stop orders against current prices."""
        async with self._lock:
            for order in list(self._trailing_orders.values()):
                if order.state != AdvancedOrderState.ACTIVE:
                    continue
                if order.native_broker_support:
                    continue

                price = self._latest_prices.get(order.symbol)
                if price is None:
                    continue

                # Check activation
                if not order.activated and order.activation_price:
                    if order.side.upper() == "SELL":
                        if price >= order.activation_price:
                            order.activated = True
                            order.highest_price = price
                            order.current_stop_price = price - (order.trail_distance_pips * 0.01)
                    elif price <= order.activation_price:
                        order.activated = True
                        order.lowest_price = price
                        order.current_stop_price = price + (order.trail_distance_pips * 0.01)
                    continue

                if not order.activated:
                    continue

                # Update trailing stop
                if order.side.upper() == "SELL":
                    # Long position — trail below highest price
                    if price > order.highest_price:
                        order.highest_price = price
                        order.current_stop_price = price - (order.trail_distance_pips * 0.01)

                    # Check if stop is hit
                    if price <= order.current_stop_price:
                        await self._execute_trailing_fill(order, price)
                else:
                    # Short position — trail above lowest price
                    if price < order.lowest_price:
                        order.lowest_price = price
                        order.current_stop_price = price + (order.trail_distance_pips * 0.01)

                    # Check if stop is hit
                    if price >= order.current_stop_price:
                        await self._execute_trailing_fill(order, price)

    async def _check_stop_limit_orders(self) -> None:
        """Check stop-limit orders against current prices."""
        async with self._lock:
            for order in list(self._stop_limit_orders.values()):
                if order.state != AdvancedOrderState.ACTIVE:
                    continue
                if order.native_broker_support:
                    continue

                # Check expiration
                if order.expires_at and datetime.now(UTC) > order.expires_at:
                    order.state = AdvancedOrderState.EXPIRED
                    continue

                price = self._latest_prices.get(order.symbol)
                if price is None:
                    continue

                # Check if stop price is reached
                if not order.triggered:
                    triggered = False
                    if order.side.upper() in ("BUY", "LONG"):
                        if price >= order.stop_price:
                            triggered = True
                    elif price <= order.stop_price:
                        triggered = True

                    if triggered:
                        order.triggered = True
                        # Now check if limit price is achievable
                        await self._execute_stop_limit(order, price)

    # ── Execution ─────────────────────────────────────────────────────────────

    async def _execute_oco_fill(self, order: OCOOrder, price: float, fill_type: FillType) -> None:
        """Execute an OCO fill — close position and publish event."""
        order.state = AdvancedOrderState.FILLED
        order.fill_type = fill_type
        order.fill_price = price
        order.filled_at = datetime.now(UTC)

        # Calculate slippage
        target_price = order.stop_loss_price if fill_type == FillType.STOP_LOSS else order.take_profit_price
        order.slippage = abs(price - target_price)

        # Execute market close via broker
        if self._adapter:
            for attempt in range(_MAX_RETRIES):
                try:
                    await self._adapter.submit_market_close(
                        symbol=order.symbol,
                        side=order.side,
                        quantity=order.quantity,
                    )
                    break
                except Exception as exc:
                    if attempt == _MAX_RETRIES - 1:
                        logger.error(
                            "OCO fill execution failed after %d retries: %s",
                            _MAX_RETRIES,
                            exc,
                        )
                        order.state = AdvancedOrderState.FAILED
                        return
                    await asyncio.sleep(_RETRY_DELAY_S)

        # Publish fill event
        await self._publish_fill_event(order, fill_type)

        if _PROM_OK:
            _oco_filled.labels(fill_type=fill_type.value).inc()

        logger.info(
            "OCO filled: order_id=%s type=%s price=%.5f slippage=%.5f",
            order.order_id,
            fill_type.value,
            price,
            order.slippage,
        )

    async def _execute_trailing_fill(self, order: TrailingStopOrder, price: float) -> None:
        """Execute a trailing stop fill."""
        order.state = AdvancedOrderState.FILLED
        order.fill_price = price
        order.filled_at = datetime.now(UTC)

        # Execute market close via broker
        if self._adapter:
            for attempt in range(_MAX_RETRIES):
                try:
                    await self._adapter.submit_market_close(
                        symbol=order.symbol,
                        side=order.side,
                        quantity=order.quantity,
                    )
                    break
                except Exception as exc:
                    if attempt == _MAX_RETRIES - 1:
                        logger.error(
                            "Trailing stop execution failed after %d retries: %s",
                            _MAX_RETRIES,
                            exc,
                        )
                        order.state = AdvancedOrderState.FAILED
                        return
                    await asyncio.sleep(_RETRY_DELAY_S)

        # Publish fill event
        await self._publish_fill_event(order, FillType.TRAILING_STOP)

        if _PROM_OK:
            _trailing_stops_triggered.inc()

        logger.info(
            "Trailing stop filled: order_id=%s price=%.5f stop_price=%.5f",
            order.order_id,
            price,
            order.current_stop_price,
        )

    async def _execute_stop_limit(self, order: StopLimitOrder, price: float) -> None:
        """Execute a stop-limit order (place limit order at broker)."""
        # Check if current price is within limit
        can_fill = price <= order.limit_price if order.side.upper() in ("BUY", "LONG") else price >= order.limit_price

        if can_fill and self._adapter:
            for attempt in range(_MAX_RETRIES):
                try:
                    await self._adapter.submit_market_close(
                        symbol=order.symbol,
                        side=order.side,
                        quantity=order.quantity,
                    )
                    order.state = AdvancedOrderState.FILLED
                    order.fill_price = price
                    order.filled_at = datetime.now(UTC)
                    await self._publish_fill_event(order, FillType.STOP_LIMIT)
                    break
                except Exception as exc:
                    if attempt == _MAX_RETRIES - 1:
                        logger.error(
                            "Stop-limit execution failed after %d retries: %s",
                            _MAX_RETRIES,
                            exc,
                        )
                        order.state = AdvancedOrderState.FAILED
                    await asyncio.sleep(_RETRY_DELAY_S)
        elif not can_fill:
            # Price moved past limit — order cannot be filled at desired price
            logger.warning(
                "Stop-limit triggered but price %.5f past limit %.5f — waiting",
                price,
                order.limit_price,
            )

    # ── Event Publishing ──────────────────────────────────────────────────────

    async def _publish_fill_event(self, order: Any, fill_type: FillType) -> None:
        """Publish a fill event to the EventBus."""
        if not self._event_bus:
            return

        try:
            from core.event_bus import CH_ORDER

            event = {
                "type": "advanced_order_fill",
                "order_id": order.order_id,
                "position_id": order.position_id,
                "symbol": order.symbol,
                "side": order.side,
                "quantity": order.quantity,
                "fill_type": fill_type.value,
                "fill_price": order.fill_price,
                "filled_at": order.filled_at.isoformat() if order.filled_at else None,
            }

            if hasattr(self._event_bus, "publish"):
                await self._event_bus.publish(CH_ORDER, event)
            elif hasattr(self._event_bus, "publish_local"):
                await self._event_bus.publish_local(CH_ORDER, event)
        except Exception as exc:
            logger.warning("Failed to publish fill event: %s", exc)

    # ── Queries ───────────────────────────────────────────────────────────────

    def get_order(self, order_id: str) -> dict[str, Any] | None:
        """Get an order by ID."""
        if order_id in self._oco_orders:
            return self._oco_orders[order_id].to_dict()
        if order_id in self._trailing_orders:
            return self._trailing_orders[order_id].to_dict()
        if order_id in self._stop_limit_orders:
            return self._stop_limit_orders[order_id].to_dict()
        return None

    def get_active_orders(self, position_id: str | None = None) -> list[dict[str, Any]]:
        """Get all active advanced orders, optionally filtered by position."""
        orders: list[dict[str, Any]] = []

        for o in self._oco_orders.values():
            if o.state == AdvancedOrderState.ACTIVE and (position_id is None or o.position_id == position_id):
                orders.append(o.to_dict())

        for o in self._trailing_orders.values():
            if o.state == AdvancedOrderState.ACTIVE and (position_id is None or o.position_id == position_id):
                orders.append(o.to_dict())

        for o in self._stop_limit_orders.values():
            if o.state == AdvancedOrderState.ACTIVE and (position_id is None or o.position_id == position_id):
                orders.append(o.to_dict())

        return orders

    def health(self) -> dict[str, Any]:
        """Return manager health metrics."""
        return {
            "running": self._running,
            "active_oco": sum(1 for o in self._oco_orders.values() if o.state == AdvancedOrderState.ACTIVE),
            "active_trailing": sum(1 for o in self._trailing_orders.values() if o.state == AdvancedOrderState.ACTIVE),
            "active_stop_limit": sum(
                1 for o in self._stop_limit_orders.values() if o.state == AdvancedOrderState.ACTIVE
            ),
            "total_orders": (len(self._oco_orders) + len(self._trailing_orders) + len(self._stop_limit_orders)),
            "tracked_symbols": list(self._latest_prices.keys()),
            "native_oco": self._adapter.supports_native_oco if self._adapter else False,
            "native_trailing": (self._adapter.supports_native_trailing_stop if self._adapter else False),
            "native_stop_limit": (self._adapter.supports_native_stop_limit if self._adapter else False),
        }


# ── Module-level singleton ────────────────────────────────────────────────────

_manager: AdvancedOrderManager | None = None


def get_advanced_order_manager() -> AdvancedOrderManager:
    """Return the module-level AdvancedOrderManager singleton."""
    global _manager
    if _manager is None:
        _manager = AdvancedOrderManager()
    return _manager
