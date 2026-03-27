# HOPEFX-AI-TRADING
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Paper Trading Broker

Simulated broker for testing strategies without real money.
"""

import logging
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .base import (
    AccountInfo,
    BrokerConnector,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
)

logger = logging.getLogger(__name__)


class PaperTradingBroker(BrokerConnector):
    """
    Paper trading broker for testing.

    Simulates order execution and position management
    without connecting to real exchanges.
    """

    def __init__(
        self,
        config: Dict[str, Any] = None,
        session_factory=None,
        user_id: str = "paper",
        initial_balance: float = None,
        commission_per_lot: float = None,
        slippage_model: str = "gaussian",
    ):
        """
        Initialize paper trading broker.

        Accepts either a config dict or keyword arguments directly.
        """
        if config is None:
            config = {}
        # Allow keyword args to override config dict
        if initial_balance is not None:
            config = dict(config)
            config["initial_balance"] = initial_balance
        if commission_per_lot is not None:
            config = dict(config)
            config["commission_per_lot"] = commission_per_lot
        super().__init__(config)

        self.initial_balance = config.get("initial_balance", 10000.0)
        self.balance = self.initial_balance
        self.equity = self.initial_balance
        self._session_factory = session_factory
        self._user_id = user_id

        self.orders: Dict[str, Order] = {}
        self.positions: Dict[str, Position] = {}

        # Equity history: deque of (unix_timestamp, equity_value) tuples.
        # Bounded at 10 000 points (~2.7 hours at 1-second resolution or
        # ~7 months at 30-minute snapshots).  Seeded with the initial balance
        # so the equity curve always has at least one data point.
        self._equity_history: deque = deque(maxlen=10_000)
        self._equity_history.append((time.time(), self.initial_balance))

        # Simulated market prices - Multi-asset support
        # Last updated: 2025-Q2. These are fallback prices used only when
        # no live feed is available. Update periodically or wire a live feed.
        self.market_prices = {
            # Precious Metals
            "XAUUSD": 3300.0,  # Gold (~Mar 2025)
            "XAGUSD": 33.50,   # Silver
            "XPTUSD": 980.0,   # Platinum
            # Major Forex Pairs
            "EURUSD": 1.0820,
            "GBPUSD": 1.2940,
            "USDJPY": 149.50,
            "USDCHF": 0.8820,
            "AUDUSD": 0.6290,
            "USDCAD": 1.3850,
            "NZDUSD": 0.5720,
            # Cross Pairs
            "EURGBP": 0.8360,
            "EURJPY": 161.80,
            "GBPJPY": 193.60,
            # Crypto
            "BTC/USD": 85000.0,
            "ETH/USD": 1900.0,
            "SOL/USD": 130.0,
            "XRP/USD": 2.10,
            # US Stocks/ETFs (for reference)
            "SPY": 555.0,
            "QQQ": 470.0,
            "AAPL": 210.0,
            "MSFT": 390.0,
            "TSLA": 250.0,
            "NVDA": 880.0,
            # Indices
            "US30": 41500.0,   # Dow Jones
            "US500": 5600.0,   # S&P 500
            "NAS100": 19500.0, # Nasdaq 100
        }

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *args):
        await self.disconnect()

    async def connect(self) -> bool:
        """Connect to paper trading broker (always succeeds)"""
        self.connected = True
        logger.info(f"Connected to {self.name} (Paper Trading)")
        logger.info(f"Initial balance: ${self.initial_balance:,.2f}")
        return True

    async def disconnect(self) -> bool:
        """Disconnect from paper trading broker"""
        self.connected = False
        logger.info(f"Disconnected from {self.name}")
        return True

    def place_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
        **kwargs,
    ) -> Order:
        """
        Place a simulated order.

        Market orders are filled immediately at current market price.
        Limit orders are filled if price conditions are met.
        """
        if not self.connected:
            raise ConnectionError("Not connected to broker")

        # Generate order ID
        order_id = str(uuid.uuid4())

        # Get current market price
        current_price = self.market_prices.get(symbol, 0.0)
        if current_price == 0.0:
            logger.warning(f"Unknown symbol {symbol}, using default price 1000.0")
            current_price = 1000.0

        # Create order
        order = Order(
            id=order_id,
            symbol=symbol,
            side=side,
            type=order_type,
            quantity=quantity,
            price=price,
            stop_price=stop_price,
            status=OrderStatus.PENDING,
            timestamp=datetime.now(timezone.utc),
        )

        # Process order
        if order_type == OrderType.MARKET:
            # Execute immediately
            order.status = OrderStatus.FILLED
            order.filled_quantity = quantity
            order.average_price = current_price

            # Update position
            self._update_position(symbol, side, quantity, current_price)

            # Record equity snapshot after every fill
            self._snapshot_equity()

            logger.info(
                f"Market order filled: {side.value} {quantity} {symbol} @ ${current_price}",
            )
        else:
            # For limit/stop orders, just mark as open
            order.status = OrderStatus.OPEN
            logger.info(
                f"Limit order placed: {side.value} {quantity} {symbol} @ ${price}",
            )

        self.orders[order_id] = order
        return order

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order"""
        if order_id in self.orders:
            order = self.orders[order_id]
            if order.status in [OrderStatus.PENDING, OrderStatus.OPEN]:
                order.status = OrderStatus.CANCELLED
                logger.info(f"Order cancelled: {order_id}")
                return True

        logger.warning(f"Cannot cancel order {order_id}")
        return False

    def get_order(self, order_id: str) -> Optional[Order]:
        """Get order by ID"""
        return self.orders.get(order_id)

    def _get_positions_sync(self) -> List[Position]:
        """Sync helper used internally."""
        positions = []
        for position in self.positions.values():
            current_price = self.market_prices.get(
                position.symbol,
                position.entry_price,
            )
            if position.side == "LONG":
                unrealized_pnl = (
                    current_price - position.entry_price
                ) * position.quantity
            else:
                unrealized_pnl = (
                    position.entry_price - current_price
                ) * position.quantity
            position.current_price = current_price
            position.unrealized_pnl = unrealized_pnl
            if not hasattr(position, "id") or not position.id:
                position.id = position.symbol
            positions.append(position)
        return positions

    def get_positions(self) -> List[Position]:
        """Get all open positions."""
        return self._get_positions_sync()

    def close_position(self, symbol_or_id: str) -> bool:
        """Close a position by symbol or position id."""
        symbol = symbol_or_id
        if symbol_or_id not in self.positions:
            for sym, pos in self.positions.items():
                if getattr(pos, "id", sym) == symbol_or_id:
                    symbol = sym
                    break
            else:
                logger.warning(f"No open position for {symbol_or_id}")
                return False
        if symbol not in self.positions:
            return False

        position = self.positions[symbol]
        current_price = self.market_prices.get(symbol, position.entry_price)

        # Calculate P&L
        if position.side == "LONG":
            pnl = (current_price - position.entry_price) * position.quantity
        else:
            pnl = (position.entry_price - current_price) * position.quantity

        # Update balance
        self.balance += pnl
        self.equity = self.balance

        # Persist closed trade to DB
        self._persist_trade(position, current_price, pnl)

        # Remove position
        del self.positions[symbol]

        logger.info(
            f"Position closed: {symbol}, P&L: ${pnl:.2f}, "
            f"New balance: ${self.balance:.2f}",
        )

        return True

    def _persist_trade(
        self,
        position: "Position",
        exit_price: float,
        realized_pnl: float,
    ) -> None:
        """Write a closed trade record to the DB trades table."""
        if not self._session_factory:
            return
        try:
            from database.models import OrderSide, Trade, TradeStatus

            # Normalise side to OrderSide enum
            raw_side = (
                str(position.side)
                .lower()
                .replace("orderside.", "")
                .replace("long", "buy")
                .replace("short", "sell")
            )
            side_enum = (
                OrderSide.BUY
                if "buy" in raw_side or "long" in raw_side
                else OrderSide.SELL
            )

            trade = Trade(
                trade_id=str(uuid.uuid4()),
                symbol=position.symbol,
                side=side_enum,
                entry_price=float(position.entry_price),
                entry_quantity=float(position.quantity),
                exit_price=float(exit_price),
                exit_quantity=float(position.quantity),
                realized_pnl=float(realized_pnl),
                total_pnl=float(realized_pnl),
                commission=0.0,
                status=TradeStatus.CLOSED,
                is_open=False,
                strategy=getattr(position, "strategy", "paper"),
                entry_time=getattr(position, "entry_time", datetime.now(timezone.utc)),
                exit_time=datetime.now(timezone.utc),
            )
            with self._session_factory() as session:
                session.add(trade)
                session.commit()
            logger.debug(
                "Trade persisted: %s %s pnl=%.2f",
                position.symbol,
                position.side,
                realized_pnl,
            )
        except Exception as exc:
            logger.warning("Failed to persist trade to DB: %s", exc)

    def _get_account_info_sync(self) -> AccountInfo:
        """Sync helper — returns AccountInfo dataclass."""
        total_unrealized = sum(p.unrealized_pnl for p in self._get_positions_sync())
        equity = self.balance + total_unrealized
        return AccountInfo(
            balance=self.balance,
            equity=equity,
            margin_used=0.0,
            margin_available=equity,
            positions_count=len(self.positions),
            timestamp=datetime.now(timezone.utc),
        )

    def get_account_info(self) -> "AccountInfo":
        """Get account information."""
        info = self._get_account_info_sync()
        # Record a throttled equity snapshot (at most once per 60 seconds)
        # so the equity curve grows over time even without active trading.
        last_ts = self._equity_history[-1][0] if self._equity_history else 0.0
        if time.time() - last_ts >= 60.0:
            self._equity_history.append((time.time(), float(info.equity)))
        return info

    def set_price_feed(self, price_engine) -> None:
        """Attach a price feed / engine for live price updates."""
        self._price_feed = price_engine

    def _snapshot_equity(self) -> None:
        """Append a (timestamp, equity) point to the equity history."""
        account = self._get_account_info_sync()
        self._equity_history.append((time.time(), float(account.equity)))

    def get_equity_history(self) -> List[Tuple[float, float]]:
        """
        Return the equity curve as a list of (unix_timestamp, equity) tuples.

        Called by api/performance.py _load_equity_curve() to build the
        /api/performance/equity-curve response.  Always returns at least
        the initial balance point recorded at broker startup.
        """
        return list(self._equity_history)

    async def place_market_order(self, symbol: str, side: str, quantity: float):
        """Async market order — delegates to sync place_order."""
        from .base import OrderSide as _OS
        from .base import OrderType as _OT

        side_enum = _OS.BUY if str(side).lower() in ("buy", "long") else _OS.SELL
        return self.place_order(
            symbol=symbol,
            side=side_enum,
            order_type=_OT.MARKET,
            quantity=quantity,
        )

    async def close_all_positions(self) -> int:
        """Close all open positions. Returns number closed."""
        closed = 0
        for symbol in list(self.positions.keys()):
            try:
                if self.close_position(symbol):
                    closed += 1
            except Exception as exc:
                logger.warning("Failed to close position %s: %s", symbol, exc)
        return closed

    def get_market_data(
        self,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Get simulated market data.

        Returns simple OHLCV data for testing.
        """
        current_price = self.market_prices.get(symbol, 1000.0)

        # Timeframe → seconds mapping for realistic bar timestamps
        _tf_seconds = {
            "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
            "1h": 3600, "4h": 14400, "1d": 86400,
        }
        bar_seconds = _tf_seconds.get(timeframe, 3600)
        now_ts = time.time()

        data = []
        for i in range(limit):
            bar_ts = now_ts - (limit - i) * bar_seconds
            price = current_price * (1 + (i % 10 - 5) / 1000)
            data.append(
                {
                    "timestamp": bar_ts,
                    "open": round(price, 5),
                    "high": round(price * 1.001, 5),
                    "low": round(price * 0.999, 5),
                    "close": round(price, 5),
                    "volume": 1000.0,
                },
            )

        return data

    def get_market_price(self, symbol: str) -> float:
        """
        Get current market price for a symbol.

        Args:
            symbol: Trading symbol

        Returns:
            Current market price
        """
        return self.market_prices.get(symbol, 0.0)

    def update_market_price(self, symbol: str, price: float):
        """
        Update simulated market price.

        Args:
            symbol: Trading symbol
            price: New price
        """
        self.market_prices[symbol] = price
        logger.debug(f"Updated {symbol} price to ${price}")

    def _update_position(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        price: float,
    ):
        """Update or create position"""
        position_side = "LONG" if side == OrderSide.BUY else "SHORT"

        if symbol in self.positions:
            # Update existing position
            position = self.positions[symbol]

            # For simplicity, assume same side
            total_quantity = position.quantity + quantity
            avg_price = (
                position.entry_price * position.quantity + price * quantity
            ) / total_quantity

            position.quantity = total_quantity
            position.entry_price = avg_price
        else:
            # Create new position
            self.positions[symbol] = Position(
                symbol=symbol,
                side=position_side,
                quantity=quantity,
                entry_price=price,
                current_price=price,
                unrealized_pnl=0.0,
                timestamp=datetime.now(timezone.utc),
            )
