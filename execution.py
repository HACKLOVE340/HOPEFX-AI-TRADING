#!/usr/bin/env python3
# Copyright (c) 2025-2026
# HOPEFX-AI-TRADING
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
HOPEFX Execution Module
Smart order execution with slippage modeling and safety checks.
"""

import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

from validation import OrderValidator, Order  # pylint: disable=no-name-in-module

logger = logging.getLogger("execution")


class OrderStatus(Enum):
    PENDING = "pending"
    FILLED = "filled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    PARTIAL = "partial"


@dataclass
class ExecutionResult:
    """Result of order execution."""

    order_id: str
    status: OrderStatus
    filled_qty: float
    avg_price: float
    slippage: float
    commission: float
    pnl: float | None = None
    message: str | None = None
    timestamp: str | None = None


class PaperExecutor:
    """
    Paper trading executor with realistic fill simulation.

    Accounting model
    ----------------
    cash   — free cash not tied up in positions.  Changes only when a
             position is opened (cash decreases by notional + commission)
             or closed (cash increases by proceeds - commission).
    equity — mark-to-market account value = cash + sum(unrealised P&L).
             Recomputed on every call to update_equity().

    The previous implementation mutated both self.balance and self.equity
    independently on every fill, causing them to diverge immediately.
    """

    def __init__(
        self,
        initial_balance: float = 10000.0,
        commission_per_lot: float = 3.5,
        slippage_model: str = "variable",
    ):
        self._initial_balance = initial_balance
        self.cash = initial_balance  # free cash
        self.commission_per_lot = commission_per_lot
        self.slippage_model = slippage_model
        self.positions: dict[str, dict] = {}
        self.order_history: list = []
        self.validator = OrderValidator()
        self.order_counter = 0
        self._last_prices: dict[str, float] = {}  # for equity mark-to-market

    @property
    def balance(self) -> float:
        """Alias for cash — kept for backward compatibility."""
        return self.cash

    @property
    def equity(self) -> float:
        """Mark-to-market equity = cash + sum of all unrealised P&L."""
        total_upnl = sum(
            self.get_unrealized_pnl(sym, self._last_prices[sym]) for sym in self.positions if sym in self._last_prices
        )
        return self.cash + total_upnl

    def update_prices(self, prices: dict[str, float]) -> None:
        """Update last-known prices for equity mark-to-market."""
        self._last_prices.update(prices)

    def _generate_order_id(self) -> str:
        """Generate unique order ID."""
        self.order_counter += 1
        return f"ORD_{int(time.time())}_{self.order_counter}"

    def _calculate_slippage(
        self,
        symbol: str,
        side: str,
        qty: float,
        base_price: float,
        volatility: float = 0.0,
    ) -> float:
        """
        Calculate realistic slippage based on market conditions.

        Args:
            symbol: Trading symbol
            side: 'buy' or 'sell'
            qty: Order quantity in lots
            base_price: Current market price
            volatility: Current volatility (0-1 scale)

        Returns:
            Slippage amount in price terms
        """
        if self.slippage_model == "fixed":
            # Fixed $0.05 slippage for XAUUSD
            return 0.05 if symbol == "XAUUSD" else base_price * 0.0001

        elif self.slippage_model == "variable":
            # Variable slippage based on size and volatility
            base_slippage = 0.02  # $0.02 base for XAUUSD

            # Size penalty (larger orders = more slippage)
            size_factor = min(qty / 0.1, 5.0)  # Cap at 5x for 1.0 lots

            # Volatility penalty
            vol_factor = 1.0 + (volatility * 2.0)

            slippage = base_slippage * size_factor * vol_factor
            return min(slippage, 0.5)  # Cap at $0.50

        return 0.0

    def _calculate_commission(self, qty: float, symbol: str) -> float:
        """Calculate commission based on quantity."""
        # Standard: $3.50 per lot round turn
        return self.commission_per_lot * qty

    def submit_order(
        self,
        order: Order,
        current_price: float,
        bid: float | None = None,
        ask: float | None = None,
        volatility: float = 0.0,
        skip_validation: bool = False,
    ) -> ExecutionResult:
        """
        Submit and execute an order with full validation.

        Args:
            order: Order to execute
            current_price: Current market price
            bid: Bid price (optional)
            ask: Ask price (optional)
            volatility: Current market volatility
            skip_validation: Skip validation (for testing only)

        Returns:
            ExecutionResult with fill details
        """
        order_id = self._generate_order_id()
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        # Validation
        if not skip_validation:
            validation = self.validator.validate_order(
                order=order,
                current_price=current_price,
                account_balance=self.equity,
                open_positions=list(self.positions.values()),
            )

            if not validation.valid:
                logger.error(f"Order {order_id} rejected: {validation.reason}")
                return ExecutionResult(
                    order_id=order_id,
                    status=OrderStatus.REJECTED,
                    filled_qty=0.0,
                    avg_price=0.0,
                    slippage=0.0,
                    commission=0.0,
                    message=validation.reason,
                    timestamp=timestamp,
                )

            self.validator.record_trade(validation.risk_pct)

        # Determine fill price
        if order.side == "buy":
            base_price = ask if ask else current_price + 0.02
            slippage = self._calculate_slippage(order.symbol, order.side, order.qty, base_price, volatility)
            fill_price = base_price + slippage
        else:
            base_price = bid if bid else current_price - 0.02
            slippage = self._calculate_slippage(order.symbol, order.side, order.qty, base_price, volatility)
            fill_price = base_price - slippage

        # Calculate costs
        commission = self._calculate_commission(order.qty, order.symbol)

        # Execute based on order type
        if order.order_type == "market":
            return self._execute_market_order(order_id, order, fill_price, slippage, commission, timestamp)
        elif order.order_type == "limit":
            return self._execute_limit_order(
                order_id,
                order,
                current_price,
                fill_price,
                slippage,
                commission,
                timestamp,
            )
        else:
            return ExecutionResult(
                order_id=order_id,
                status=OrderStatus.REJECTED,
                filled_qty=0.0,
                avg_price=0.0,
                slippage=0.0,
                commission=0.0,
                message=f"Unsupported order type: {order.order_type}",
                timestamp=timestamp,
            )

    def _execute_market_order(
        self,
        order_id: str,
        order: Order,
        fill_price: float,
        slippage: float,
        commission: float,
        timestamp: str,
    ) -> ExecutionResult:
        """Execute a market order."""
        notional = order.qty * fill_price
        total_cost = notional + commission

        # ── Cash sufficiency check ────────────────────────────────────────────
        # For buys: require enough free cash to cover notional + commission.
        # For sells: require an open position to close.
        pnl: float = 0.0

        if order.side == "buy":
            if total_cost > self.cash:
                return ExecutionResult(
                    order_id=order_id,
                    status=OrderStatus.REJECTED,
                    filled_qty=0.0,
                    avg_price=0.0,
                    slippage=0.0,
                    commission=0.0,
                    message=f"Insufficient balance: need {total_cost:.2f}, have {self.cash:.2f}",
                    timestamp=timestamp,
                )

            # Close existing short first (buy-to-cover)
            if order.symbol in self.positions and self.positions[order.symbol]["side"] == "short":
                old_pos = self.positions[order.symbol]
                close_qty = min(order.qty, old_pos["qty"])
                pnl = (old_pos["entry_price"] - fill_price) * close_qty - commission
                # Return the original short notional to cash, add/subtract P&L
                self.cash += old_pos["entry_price"] * close_qty + pnl
                if close_qty >= old_pos["qty"]:
                    del self.positions[order.symbol]
                else:
                    old_pos["qty"] -= close_qty
                logger.info(f"Closed short {order.symbol} qty={close_qty} P&L=${pnl:.2f}")
            else:
                # Open or add to long — deduct cash
                self.cash -= total_cost
                if order.symbol in self.positions:
                    old = self.positions[order.symbol]
                    total_qty = old["qty"] + order.qty
                    avg_entry = (old["entry_price"] * old["qty"] + fill_price * order.qty) / total_qty
                    old["qty"] = total_qty
                    old["entry_price"] = avg_entry
                else:
                    self.positions[order.symbol] = {
                        "symbol": order.symbol,
                        "side": "long",
                        "qty": order.qty,
                        "entry_price": fill_price,
                        "entry_time": timestamp,
                        "stop_loss": order.stop_loss,
                        "take_profit": order.take_profit,
                    }

        elif order.symbol not in self.positions:
            # No existing position — reject; paper trading does not support naked shorts.
            return ExecutionResult(
                order_id=order_id,
                status=OrderStatus.REJECTED,
                filled_qty=0.0,
                avg_price=0.0,
                slippage=0.0,
                commission=0.0,
                message=f"No open position for {order.symbol}; cannot sell without a position",
                timestamp=timestamp,
            )
        else:
            pos = self.positions[order.symbol]
            if pos["side"] != "long":
                return ExecutionResult(
                    order_id=order_id,
                    status=OrderStatus.REJECTED,
                    filled_qty=0.0,
                    avg_price=0.0,
                    slippage=0.0,
                    commission=0.0,
                    message=f"Cannot sell into existing {pos['side']} position via this path",
                    timestamp=timestamp,
                )

            close_qty = min(order.qty, pos["qty"])
            pnl = (fill_price - pos["entry_price"]) * close_qty - commission
            # Return original cost basis to cash, add realised P&L
            self.cash += pos["entry_price"] * close_qty + pnl

            if close_qty >= pos["qty"]:
                del self.positions[order.symbol]
            else:
                pos["qty"] -= close_qty

        # Update last-known price for equity mark-to-market
        self._last_prices[order.symbol] = fill_price

        # Determine fill status: PARTIAL when only part of the requested qty
        # was filled (e.g. closing a position smaller than the order qty).
        actual_filled = order.qty
        if order.side in ("sell", "short") and order.symbol in self.positions:
            # Position was partially closed — remaining qty still open
            remaining = self.positions[order.symbol]["qty"] if order.symbol in self.positions else 0
            actual_filled = order.qty - remaining if remaining < order.qty else order.qty

        fill_status = OrderStatus.PARTIAL if actual_filled < order.qty else OrderStatus.FILLED

        result = ExecutionResult(
            order_id=order_id,
            status=fill_status,
            filled_qty=actual_filled,
            avg_price=fill_price,
            slippage=slippage,
            commission=commission,
            pnl=round(pnl, 6) if pnl != 0.0 else None,
            timestamp=timestamp,
        )

        self.order_history.append(
            {
                "order": order,
                "result": result,
                "cash_after": self.cash,
                "equity_after": self.equity,
            }
        )

        logger.info(
            f"Executed {order.side} {order.qty} {order.symbol} @ {fill_price:.2f} "
            f"(slip: ${slippage:.2f}, comm: ${commission:.2f})"
        )

        return result

    def _execute_limit_order(
        self,
        order_id: str,
        order: Order,
        current_price: float,
        fill_price: float,
        slippage: float,
        commission: float,
        timestamp: str,
    ) -> ExecutionResult:
        """Execute a limit order (simplified - immediate fill if price OK)."""
        if order.price is None:
            return ExecutionResult(
                order_id=order_id,
                status=OrderStatus.REJECTED,
                filled_qty=0.0,
                avg_price=0.0,
                slippage=0.0,
                commission=0.0,
                message="Limit order requires price",
                timestamp=timestamp,
            )

        # Check if limit price is acceptable
        if order.side == "buy" and current_price > order.price:
            # Price moved above limit, won't fill
            return ExecutionResult(
                order_id=order_id,
                status=OrderStatus.PENDING,
                filled_qty=0.0,
                avg_price=0.0,
                slippage=0.0,
                commission=0.0,
                message="Limit price not reached",
                timestamp=timestamp,
            )

        if order.side == "sell" and current_price < order.price:
            return ExecutionResult(
                order_id=order_id,
                status=OrderStatus.PENDING,
                filled_qty=0.0,
                avg_price=0.0,
                slippage=0.0,
                commission=0.0,
                message="Limit price not reached",
                timestamp=timestamp,
            )

        # Fill at limit price (or better)
        fill_price = order.price
        return self._execute_market_order(order_id, order, fill_price, 0.0, commission, timestamp)

    def get_position(self, symbol: str) -> dict | None:
        """Get current position for symbol."""
        return self.positions.get(symbol)

    def get_unrealized_pnl(self, symbol: str, current_price: float) -> float:
        """Calculate unrealized P&L for a position."""
        pos = self.positions.get(symbol)
        if not pos:
            return 0.0

        if pos["side"] == "long":
            return (current_price - pos["entry_price"]) * pos["qty"]
        else:
            return (pos["entry_price"] - current_price) * pos["qty"]

    def close_all_positions(self, current_prices: dict[str, float]) -> list:
        """Close all open positions."""
        results = []
        for symbol in list(self.positions.keys()):
            pos = self.positions[symbol]
            order = Order(
                symbol=symbol,
                side="sell" if pos["side"] == "long" else "buy",
                qty=pos["qty"],
            )
            result = self.submit_order(order, current_prices.get(symbol, pos["entry_price"]))
            results.append(result)
        return results


class SmartOrderRouter:
    """
    Multi-broker smart order router with latency tracking, cost scoring,
    and automatic failover.

    Routing algorithm
    -----------------
    Each registered broker is scored on every route call using:
      score = w_cost * (1 - normalised_fee)
            + w_latency * (1 - normalised_latency)
            + w_reliability * recent_fill_rate
            + w_spread * (1 - normalised_spread)

    Weights are configurable; defaults favour cost (40%) and reliability (35%).
    The broker with the highest score receives the order.  If it fails, the
    router retries in score order until one succeeds or all are exhausted.

    Metrics tracked per broker
    --------------------------
    - latency_ms: exponential moving average of round-trip time
    - fill_rate:  fraction of last N orders that filled (not rejected/timeout)
    - error_count: consecutive errors (triggers temporary exclusion after 3)
    """

    _ROUTING_WEIGHTS = {
        "cost": 0.40,
        "latency": 0.15,
        "reliability": 0.35,
        "spread": 0.10,
    }
    _MAX_LATENCY_MS = 500.0  # normalisation ceiling
    _MAX_FEE_BPS = 10.0  # normalisation ceiling (10 bps)
    _MAX_SPREAD_BPS = 10.0
    _FILL_HISTORY_LEN = 50
    _ERROR_EXCLUSION = 3  # consecutive errors before temporary exclusion

    def __init__(self, routing_weights: dict[str, float] | None = None):
        self.brokers: dict[str, Any] = {}
        self.default_broker: str | None = None
        self._weights = routing_weights or self._ROUTING_WEIGHTS

        # Per-broker metrics
        self._latency_ema: dict[str, float] = {}  # ms
        self._fill_history: dict[str, list] = {}  # deque of 0/1
        self._fee_bps: dict[str, float] = {}  # configured fee
        self._spread_bps: dict[str, float] = {}  # configured spread
        self._error_count: dict[str, int] = {}  # consecutive errors
        self._excluded_until: dict[str, float] = {}  # time.monotonic() deadline

    def register_broker(
        self,
        name: str,
        broker_instance: Any,
        is_default: bool = False,
        fee_bps: float = 3.0,
        spread_bps: float = 3.0,
    ) -> None:
        """Register a broker for routing."""
        self.brokers[name] = broker_instance
        self._latency_ema[name] = 50.0  # optimistic initial estimate
        self._fill_history[name] = []
        self._fee_bps[name] = fee_bps
        self._spread_bps[name] = spread_bps
        self._error_count[name] = 0
        self._excluded_until[name] = 0.0
        if is_default or self.default_broker is None:
            self.default_broker = name
        logger.info(f"SmartOrderRouter: registered broker '{name}' (fee={fee_bps}bps, spread={spread_bps}bps)")

    def _score_broker(self, name: str) -> float:
        """Compute routing score for a broker (higher = preferred)."""
        cost_score = 1.0 - min(self._fee_bps[name] / self._MAX_FEE_BPS, 1.0)
        latency_score = 1.0 - min(self._latency_ema[name] / self._MAX_LATENCY_MS, 1.0)
        spread_score = 1.0 - min(self._spread_bps[name] / self._MAX_SPREAD_BPS, 1.0)
        hist = self._fill_history[name]
        fill_rate = float(sum(hist) / len(hist)) if hist else 0.5
        return (
            self._weights["cost"] * cost_score
            + self._weights["latency"] * latency_score
            + self._weights["reliability"] * fill_rate
            + self._weights["spread"] * spread_score
        )

    def _ranked_brokers(self) -> list:
        """Return broker names sorted by score, excluding temporarily excluded ones."""
        now = time.monotonic()
        available = [name for name in self.brokers if self._excluded_until.get(name, 0.0) <= now]
        return sorted(available, key=self._score_broker, reverse=True)

    def _update_metrics(self, name: str, latency_ms: float, success: bool) -> None:
        """Update EMA latency and fill history after an attempt."""
        alpha = 0.2
        self._latency_ema[name] = alpha * latency_ms + (1 - alpha) * self._latency_ema[name]
        hist = self._fill_history[name]
        hist.append(1 if success else 0)
        if len(hist) > self._FILL_HISTORY_LEN:
            hist.pop(0)
        if success:
            self._error_count[name] = 0
        else:
            self._error_count[name] += 1
            if self._error_count[name] >= self._ERROR_EXCLUSION:
                exclusion_secs = 60.0 * self._error_count[name]
                self._excluded_until[name] = time.monotonic() + exclusion_secs
                logger.warning(
                    f"SmartOrderRouter: broker '{name}' excluded for "
                    f"{exclusion_secs:.0f}s after {self._error_count[name]} consecutive errors"
                )

    def route_order(self, order: Any, **kwargs) -> ExecutionResult:
        """
        Route order to the highest-scoring available broker.
        Retries in score order on failure; raises RuntimeError if all fail.
        """
        if not self.brokers:
            raise RuntimeError("SmartOrderRouter: no brokers registered")

        ranked = self._ranked_brokers()
        if not ranked:
            raise RuntimeError("SmartOrderRouter: all brokers are temporarily excluded")

        last_error: Exception | None = None
        for name in ranked:
            broker = self.brokers[name]
            if not hasattr(broker, "submit_order"):
                logger.warning(f"SmartOrderRouter: broker '{name}' has no submit_order — skipping")
                continue

            t0 = time.monotonic()
            try:
                result: ExecutionResult = broker.submit_order(order, **kwargs)
                latency_ms = (time.monotonic() - t0) * 1000
                success = result.status == OrderStatus.FILLED
                self._update_metrics(name, latency_ms, success)
                logger.debug(
                    f"SmartOrderRouter: routed to '{name}' latency={latency_ms:.1f}ms status={result.status.value}"
                )
                return result
            except Exception as exc:
                latency_ms = (time.monotonic() - t0) * 1000
                self._update_metrics(name, latency_ms, False)
                logger.warning(f"SmartOrderRouter: broker '{name}' raised {exc!r} — trying next")
                last_error = exc

        raise RuntimeError(f"SmartOrderRouter: all brokers failed. Last error: {last_error}")

    def get_routing_stats(self) -> dict[str, Any]:
        """Return per-broker routing statistics for monitoring."""
        stats = {}
        for name in self.brokers:
            hist = self._fill_history[name]
            stats[name] = {
                "score": round(self._score_broker(name), 4),
                "latency_ema_ms": round(self._latency_ema[name], 2),
                "fill_rate": round(sum(hist) / len(hist), 3) if hist else None,
                "fee_bps": self._fee_bps[name],
                "spread_bps": self._spread_bps[name],
                "error_count": self._error_count[name],
                "excluded": self._excluded_until.get(name, 0.0) > time.monotonic(),
            }
        return stats


if __name__ == "__main__":
    # Demo
    print("=" * 60)
    print("Execution Module Demo")
    print("=" * 60)

    executor = PaperExecutor(initial_balance=10000.0)

    # Buy order
    buy_order = Order(symbol="XAUUSD", side="buy", qty=0.01, stop_loss=1950.0)
    result = executor.submit_order(buy_order, current_price=2000.0)
    print(f"\\nBuy order: {result.status.value} @ {result.avg_price:.2f}")
    print(f"  Slippage: ${result.slippage:.2f}, Commission: ${result.commission:.2f}")
    print(f"  Balance: ${executor.balance:.2f}, Equity: ${executor.equity:.2f}")

    # Sell order
    sell_order = Order(symbol="XAUUSD", side="sell", qty=0.01)
    result = executor.submit_order(sell_order, current_price=2010.0)
    print(f"\\nSell order: {result.status.value} @ {result.avg_price:.2f}")
    print(f"  Balance: ${executor.balance:.2f}, Equity: ${executor.equity:.2f}")

    # Invalid order (should reject)
    bad_order = Order(symbol="INVALID", side="buy", qty=0.01)
    result = executor.submit_order(bad_order, current_price=100.0)
    print(f"\\nInvalid order: {result.status.value} - {result.message}")
