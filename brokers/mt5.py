# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
MT5 Universal Connector

Universal MetaTrader 5 connector that can connect to ANY MT5-compatible broker.
Works with retail brokers, prop firms, and institutional MT5 servers.

Supported:
- Any MT5 broker (OANDA, Pepperstone, IC Markets, etc.)
- Any prop firm using MT5 (FTMO, TopstepTrader, The5ers, etc.)
- Any MT5 server worldwide
"""

import logging
from datetime import datetime, timezone

UTC = timezone.utc
from typing import Any

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5

    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    logger.warning("MetaTrader5 package not installed. MT5 connector will not work.")

from .base import (
    AccountInfo,
    BrokerConnector,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
)


class MT5Connector(BrokerConnector):
    """
    Universal MT5 Connector - Works with ANY MT5 broker or prop firm.

    Configuration:
        server: MT5 server address (e.g., "ICMarkets-Demo", "FTMO-Demo")
        login: MT5 account number
        password: MT5 account password
        timeout: Connection timeout in seconds (default: 60000)
        portable: Use portable mode if True
        path: Path to MT5 terminal (optional)

    Examples:
        # Connect to any retail broker
        config = {
            'server': 'ICMarkets-Demo',
            'login': 12345678,
            'password': 'your_password'  # pragma: allowlist secret
        }

        # Connect to FTMO prop firm
        config = {
            'server': 'FTMO-Demo',
            'login': 98765432,
            'password': 'ftmo_password'  # pragma: allowlist secret
        }

        # Connect to TopstepTrader
        config = {
            'server': 'TopstepTrader-Server01',
            'login': 11111111,
            'password': 'topstep_pass'  # pragma: allowlist secret
        }
    """

    def __init__(self, config: dict[str, Any]):
        """
        Initialize MT5 connector.

        Args:
            config: Configuration dict with server, login, password
        """
        super().__init__(config)

        if not MT5_AVAILABLE:
            raise ImportError(
                "MetaTrader5 package not installed. Install with: pip install MetaTrader5",
            )

        self.server = config.get("server")
        self.login = config.get("login")
        self.password = config.get("password")
        self.timeout = config.get("timeout", 60000)
        self.portable = config.get("portable", False)
        self.path = config.get("path")

        self.connected = False
        self.account_info = None

        # Validate required fields
        if not all([self.server, self.login, self.password]):
            raise ValueError("MT5 connector requires: server, login, password")

    def connect(self) -> bool:
        """
        Connect to MT5 server (any broker/prop firm).

        Returns:
            True if connected successfully
        """
        try:
            # Initialize MT5
            if self.path:
                if not mt5.initialize(path=self.path, portable=self.portable):
                    logger.error("MT5 initialize failed: %s", mt5.last_error())

                    return False
            elif not mt5.initialize(portable=self.portable):
                logger.error("MT5 initialize failed: %s", mt5.last_error())

                return False

            # Login to server
            authorized = mt5.login(
                login=self.login,
                password=self.password,
                server=self.server,
                timeout=self.timeout,
            )

            if not authorized:
                logger.error("MT5 login failed: %s", mt5.last_error())

                mt5.shutdown()
                return False

            self.connected = True

            # Get account info
            account_info = mt5.account_info()
            if account_info:
                logger.info("Connected to MT5: %s", account_info.server)

                logger.info("Account: %s", account_info.login)

                logger.info("Balance: $%s", account_info.balance)

                logger.info("Leverage: 1:%s", account_info.leverage)

            return True

        except Exception as e:
            logger.error("MT5 connection error: %s", e)

            return False

    def disconnect(self) -> bool:
        """Disconnect from MT5."""
        try:
            mt5.shutdown()
            self.connected = False
            logger.info("Disconnected from MT5")
            return True
        except Exception as e:
            logger.error("MT5 disconnect error: %s", e)

            return False

    def place_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType = OrderType.MARKET,
        quantity: float = 0.0,
        price: float | None = None,
        stop_price: float | None = None,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        **kwargs: Any,
    ) -> Order | None:
        """
        Place order on MT5.

        Args:
            symbol: Trading symbol (e.g., "EURUSD", "BTCUSD")
            side: BUY or SELL
            quantity: Lot size (0.01 = micro lot, 1.0 = standard lot)
            order_type: Market, Limit, Stop, etc.
            price: Limit price (for limit orders)
            stop_loss: Stop loss price
            take_profit: Take profit price

        Returns:
            Order object if successful
        """
        if not self.connected:
            logger.warning("place_order called while not connected to MT5")
            return None

        try:
            # Get symbol info
            symbol_info = mt5.symbol_info(symbol)
            if symbol_info is None:
                raise ValueError(f"Symbol {symbol} not found")

            if not symbol_info.visible and not mt5.symbol_select(symbol, True):
                raise RuntimeError(f"Failed to select symbol {symbol}")

            # Determine order type
            if order_type == OrderType.MARKET:
                mt5_order_type = mt5.ORDER_TYPE_BUY if side == OrderSide.BUY else mt5.ORDER_TYPE_SELL
            elif order_type == OrderType.LIMIT:
                mt5_order_type = mt5.ORDER_TYPE_BUY_LIMIT if side == OrderSide.BUY else mt5.ORDER_TYPE_SELL_LIMIT
            elif order_type == OrderType.STOP:
                mt5_order_type = mt5.ORDER_TYPE_BUY_STOP if side == OrderSide.BUY else mt5.ORDER_TYPE_SELL_STOP
            else:
                raise ValueError(f"Unsupported order type: {order_type}")

            # Get current price for market orders
            if order_type == OrderType.MARKET:
                tick = mt5.symbol_info_tick(symbol)
                if tick is None:
                    raise RuntimeError(f"Failed to get tick for {symbol}")
                price = tick.ask if side == OrderSide.BUY else tick.bid

            # Build request
            request: dict[str, Any] = {
                "action": mt5.TRADE_ACTION_DEAL if order_type == OrderType.MARKET else mt5.TRADE_ACTION_PENDING,
                "symbol": symbol,
                "volume": float(quantity),
                "type": mt5_order_type,
                "price": float(price) if price else 0.0,
                "deviation": kwargs.get("deviation", 20),
                "magic": kwargs.get("magic", 234000),
                "comment": kwargs.get("comment", "HOPEFX AI Trading"),
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }

            # Add SL/TP if provided
            if stop_loss:
                request["sl"] = float(stop_loss)
            if take_profit:
                request["tp"] = float(take_profit)

            # Send order
            result = mt5.order_send(request)

            if result.retcode != mt5.TRADE_RETCODE_DONE:
                raise RuntimeError(f"Order failed: {result.comment}")

            # Use the EXECUTED fill, never the requested values. For a market
            # order a DONE retcode with zero/absent volume or price is degenerate
            # and must be rejected rather than booked as a clean fill (mirrors the
            # OANDA adapter). A partial fill must not be reported as fully FILLED.
            # Pending (limit/stop) orders rest with no fill — volume/price 0 is
            # legitimate there, so the fill validation applies to market orders.
            filled_vol = float(getattr(result, "volume", 0) or 0)
            fill_price = float(getattr(result, "price", 0) or 0)

            if order_type == OrderType.MARKET:
                if filled_vol <= 0 or fill_price <= 0:
                    raise RuntimeError(
                        f"Degenerate MT5 market fill: volume={filled_vol} price={fill_price} "
                        f"comment={getattr(result, 'comment', '')}"
                    )
                _status = OrderStatus.FILLED if filled_vol >= float(quantity) else OrderStatus.PARTIAL
                _filled_qty = filled_vol
                _avg_price = fill_price
            else:
                # Pending order accepted but not yet filled.
                _status = OrderStatus.PENDING
                _filled_qty = filled_vol
                _avg_price = fill_price if fill_price > 0 else price

            # Create Order object
            order = Order(
                id=str(result.order),
                symbol=symbol,
                side=side,
                type=order_type,
                quantity=quantity,
                price=price,
                status=_status,
                filled_quantity=_filled_qty,
                average_price=_avg_price,
                timestamp=datetime.now(UTC),
                metadata={
                    "mt5_order": result.order,
                    "mt5_deal": result.deal if hasattr(result, "deal") else None,
                },
            )

            logger.info("Order placed: %s %s %s @ %s", symbol, side.value, quantity, price)

            return order

        except Exception as e:
            logger.error("place_order failed for %s: %s", symbol, e)
            return None

    def cancel_order(self, order_id: str) -> bool:
        """Cancel pending order."""
        if not self.connected:
            return False

        try:
            request = {
                "action": mt5.TRADE_ACTION_REMOVE,
                "order": int(order_id),
            }

            result = mt5.order_send(request)
            return bool(result.retcode == mt5.TRADE_RETCODE_DONE)

        except Exception as e:
            logger.error("Cancel order error: %s", e)

            return False

    def get_order(self, order_id: str) -> Order | None:
        """Get order by ID."""
        if not self.connected:
            return None

        try:
            orders = mt5.orders_get()
            if orders:
                for mt5_order in orders:
                    if str(mt5_order.ticket) == order_id:
                        return self._mt5_order_to_order(mt5_order)
            return None
        except Exception as e:
            logger.error("Get order error: %s", e)

            return None

    def get_positions(self, symbol: str | None = None) -> list[Position]:
        """Get open positions."""
        if not self.connected:
            return []

        try:
            positions = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()

            if positions is None:
                return []

            result = []
            for mt5_pos in positions:
                # Get current price
                tick = mt5.symbol_info_tick(mt5_pos.symbol)
                current_price = tick.bid if mt5_pos.type == mt5.POSITION_TYPE_BUY else tick.ask

                position = Position(
                    symbol=mt5_pos.symbol,
                    side="LONG" if mt5_pos.type == mt5.POSITION_TYPE_BUY else "SHORT",
                    quantity=mt5_pos.volume,
                    entry_price=mt5_pos.price_open,
                    current_price=current_price,
                    unrealized_pnl=mt5_pos.profit,
                    realized_pnl=0.0,
                    timestamp=datetime.fromtimestamp(mt5_pos.time),
                )
                result.append(position)

            return result

        except Exception as e:
            logger.error("Get positions error: %s", e)

            return []

    def close_position(self, symbol: str, quantity: float | None = None) -> bool:
        """Close position (full or partial)."""
        if not self.connected:
            return False

        try:
            positions = mt5.positions_get(symbol=symbol)
            if not positions:
                logger.warning("No position found for %s", symbol)

                return False

            for position in positions:
                # Determine close type (opposite of position)
                close_type = mt5.ORDER_TYPE_SELL if position.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY

                # Get current price
                tick = mt5.symbol_info_tick(symbol)
                if tick is None:
                    continue

                close_price = tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask
                close_volume = quantity or position.volume

                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": symbol,
                    "volume": float(close_volume),
                    "type": close_type,
                    "position": position.ticket,
                    "price": close_price,
                    "deviation": 20,
                    "magic": 234000,
                    "comment": "Close by HOPEFX",
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": mt5.ORDER_FILLING_IOC,
                }

                result = mt5.order_send(request)
                if result.retcode != mt5.TRADE_RETCODE_DONE:
                    logger.error("Close position failed: %s", result.comment)

                    return False

            logger.info("Closed position: %s", symbol)

            return True

        except Exception as e:
            logger.error("Close position error: %s", e)

            return False

    def get_account_info(self) -> AccountInfo | None:
        """Get account information."""
        if not self.connected:
            logger.warning("get_account_info called while not connected to MT5")
            return None

        try:
            account = mt5.account_info()
            if account is None:
                logger.warning("mt5.account_info() returned None")
                return None

            return AccountInfo(
                balance=account.balance,
                equity=account.equity,
                margin_used=account.margin,
                margin_available=account.margin_free,
                positions_count=len(mt5.positions_get() or []),
                timestamp=datetime.now(UTC),
            )

        except Exception as e:
            logger.error("get_account_info failed: %s", e)
            return None

    def get_market_data(  # pylint: disable=arguments-differ
        self,
        symbol: str,
        timeframe: str = "H1",
        limit: int = 100,
    ) -> list[dict[str, Any]] | None:
        """
        Get historical market data.

        Args:
            symbol: Trading symbol
            timeframe: M1, M5, M15, M30, H1, H4, D1, W1, MN1
            count: Number of bars

        Returns:
            List of candle dictionaries
        """
        if not self.connected:
            return None

        try:
            # Map timeframe to MT5 constant
            timeframe_map = {
                "M1": mt5.TIMEFRAME_M1,
                "M5": mt5.TIMEFRAME_M5,
                "M15": mt5.TIMEFRAME_M15,
                "M30": mt5.TIMEFRAME_M30,
                "H1": mt5.TIMEFRAME_H1,
                "H4": mt5.TIMEFRAME_H4,
                "D1": mt5.TIMEFRAME_D1,
                "W1": mt5.TIMEFRAME_W1,
                "MN1": mt5.TIMEFRAME_MN1,
            }

            mt5_timeframe = timeframe_map.get(timeframe.upper(), mt5.TIMEFRAME_H1)

            # Get candles
            rates = mt5.copy_rates_from_pos(symbol, mt5_timeframe, 0, limit)
            if rates is None:
                return None

            candles: list[dict[str, Any]] = []
            for rate in rates:
                candles.append(
                    {
                        "time": datetime.fromtimestamp(rate["time"]),
                        "open": rate["open"],
                        "high": rate["high"],
                        "low": rate["low"],
                        "close": rate["close"],
                        "volume": rate["tick_volume"],
                    },
                )

            return candles

        except Exception as e:
            logger.error("get_market_data failed for %s: %s", symbol, e)
            return None

    def get_symbols(self) -> list[str]:
        """Get all available symbols."""
        if not self.connected:
            return []

        try:
            symbols = mt5.symbols_get()
            if symbols:
                return [s.name for s in symbols if s.visible]
            return []
        except Exception as e:
            logger.error("Get symbols error: %s", e)

            return []

    def _mt5_order_to_order(self, mt5_order: Any) -> Order:
        """Convert MT5 order to Order object."""
        return Order(
            id=str(mt5_order.ticket),
            symbol=mt5_order.symbol,
            side=OrderSide.BUY
            if mt5_order.type in [mt5.ORDER_TYPE_BUY, mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_BUY_STOP]
            else OrderSide.SELL,
            type=OrderType.MARKET if mt5_order.type in [mt5.ORDER_TYPE_BUY, mt5.ORDER_TYPE_SELL] else OrderType.LIMIT,
            quantity=mt5_order.volume_current,
            price=mt5_order.price_open,
            status=OrderStatus.OPEN,
            timestamp=datetime.fromtimestamp(mt5_order.time_setup),
        )


# Alias for consistent naming across the codebase
MT5Broker = MT5Connector
