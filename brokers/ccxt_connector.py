"""
CCXT Universal Broker Connector

Wraps the ccxt library to give HOPEFX access to 50+ exchanges
(Binance, Bybit, OKX, Kraken, Coinbase, Gate.io, Bitget, etc.)
through a single unified interface that matches BrokerConnector.

Usage:
    from brokers.ccxt_connector import CCXTConnector

    broker = CCXTConnector({
        "exchange": "binance",          # any ccxt exchange id
        "api_key": "...",
        "api_secret": "...",
        "sandbox": True,                # use testnet
        "options": {"defaultType": "future"},  # spot / future / margin
    })
    broker.connect()
    info = broker.get_account_info()
    data = broker.get_market_data("BTC/USDT", "1h", 200)
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from brokers.base import (
    AccountInfo,
    BrokerConnector,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
)

logger = logging.getLogger(__name__)

# ccxt timeframe aliases → ccxt format
_TF_MAP = {
    "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1h", "2h": "2h", "4h": "4h", "6h": "6h", "8h": "8h", "12h": "12h",
    "1d": "1d", "3d": "3d", "1w": "1w", "1M": "1M",
}


def _ts(ms: Optional[int]) -> Optional[datetime]:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


class CCXTConnector(BrokerConnector):
    """
    Universal connector for any ccxt-supported exchange.

    Supports spot, futures, and margin markets depending on the
    exchange and the ``options.defaultType`` config key.
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self._exchange_id: str = config.get("exchange", "binance").lower()
        self._exchange = None
        self.name = f"CCXT:{self._exchange_id}"

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def connect(self) -> bool:
        try:
            import ccxt

            exchange_class = getattr(ccxt, self._exchange_id)
            params: Dict[str, Any] = {
                "apiKey": self.config.get("api_key", ""),
                "secret": self.config.get("api_secret", ""),
            }
            if self.config.get("password"):
                params["password"] = self.config["password"]
            if self.config.get("options"):
                params["options"] = self.config["options"]

            self._exchange = exchange_class(params)

            if self.config.get("sandbox", False):
                self._exchange.set_sandbox_mode(True)

            # Verify connectivity by loading markets
            self._exchange.load_markets()
            self.connected = True
            logger.info("Connected to %s (%d markets)", self._exchange_id,
                        len(self._exchange.markets))
            return True
        except Exception as exc:
            logger.error("CCXT connect failed for %s: %s", self._exchange_id, exc)
            self.connected = False
            return False

    def disconnect(self) -> bool:
        if self._exchange and hasattr(self._exchange, "close"):
            try:
                import asyncio
                asyncio.get_event_loop().run_until_complete(self._exchange.close())
            except Exception:
                pass
        self.connected = False
        self._exchange = None
        return True

    # ── Orders ───────────────────────────────────────────────────────────────

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
        self._require_connected()
        ccxt_type = {
            OrderType.MARKET: "market",
            OrderType.LIMIT: "limit",
            OrderType.STOP: "stop",
            OrderType.STOP_LIMIT: "stop_limit",
        }.get(order_type, "market")

        ccxt_side = "buy" if side == OrderSide.BUY else "sell"
        params = kwargs.get("params", {})
        if stop_price:
            params["stopPrice"] = stop_price

        raw = self._exchange.create_order(
            symbol, ccxt_type, ccxt_side, quantity, price, params
        )
        return self._parse_order(raw)

    def cancel_order(self, order_id: str, symbol: str = None) -> bool:
        self._require_connected()
        try:
            self._exchange.cancel_order(order_id, symbol)
            return True
        except Exception as exc:
            logger.error("Cancel order %s failed: %s", order_id, exc)
            return False

    def get_order(self, order_id: str, symbol: str = None) -> Optional[Order]:
        self._require_connected()
        try:
            raw = self._exchange.fetch_order(order_id, symbol)
            return self._parse_order(raw)
        except Exception as exc:
            logger.error("Fetch order %s failed: %s", order_id, exc)
            return None

    # ── Positions ────────────────────────────────────────────────────────────

    def get_positions(self) -> List[Position]:
        self._require_connected()
        try:
            if self._exchange.has.get("fetchPositions"):
                raws = self._exchange.fetch_positions()
                return [self._parse_position(p) for p in raws
                        if float(p.get("contracts") or p.get("size") or 0) != 0]
            # Spot fallback: derive from balance
            balance = self._exchange.fetch_balance()
            positions = []
            for asset, info in balance.get("total", {}).items():
                if asset in ("USDT", "USD", "BUSD", "USDC") or float(info or 0) == 0:
                    continue
                positions.append(Position(
                    symbol=f"{asset}/USDT",
                    side="LONG",
                    quantity=float(info),
                    entry_price=0.0,
                    current_price=0.0,
                    unrealized_pnl=0.0,
                    timestamp=datetime.now(timezone.utc),
                ))
            return positions
        except Exception as exc:
            logger.error("Fetch positions failed: %s", exc)
            return []

    def close_position(self, symbol: str) -> bool:
        self._require_connected()
        try:
            positions = self.get_positions()
            for pos in positions:
                if pos.symbol == symbol:
                    side = OrderSide.SELL if pos.side == "LONG" else OrderSide.BUY
                    self.place_order(symbol, side, OrderType.MARKET, abs(pos.quantity))
                    return True
            return False
        except Exception as exc:
            logger.error("Close position %s failed: %s", symbol, exc)
            return False

    # ── Account ──────────────────────────────────────────────────────────────

    def get_account_info(self) -> AccountInfo:
        self._require_connected()
        try:
            bal = self._exchange.fetch_balance()
            total = bal.get("total", {})
            free = bal.get("free", {})
            # Use USDT/USD as base currency
            for base in ("USDT", "USD", "BUSD", "USDC"):
                if base in total:
                    equity = float(total[base] or 0)
                    available = float(free.get(base, 0) or 0)
                    return AccountInfo(
                        balance=equity,
                        equity=equity,
                        margin_used=equity - available,
                        margin_available=available,
                        positions_count=len(self.get_positions()),
                        timestamp=datetime.now(timezone.utc),
                    )
            return AccountInfo(0, 0, 0, 0, 0, datetime.now(timezone.utc))
        except Exception as exc:
            logger.error("Fetch account info failed: %s", exc)
            return AccountInfo(0, 0, 0, 0, 0, datetime.now(timezone.utc))

    # ── Market data ──────────────────────────────────────────────────────────

    def get_market_data(
        self,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        self._require_connected()
        tf = _TF_MAP.get(timeframe, timeframe)
        try:
            ohlcv = self._exchange.fetch_ohlcv(symbol, tf, limit=limit)
            return [
                {
                    "timestamp": _ts(row[0]),
                    "open": row[1],
                    "high": row[2],
                    "low": row[3],
                    "close": row[4],
                    "volume": row[5],
                }
                for row in ohlcv
            ]
        except Exception as exc:
            logger.error("Fetch OHLCV %s/%s failed: %s", symbol, timeframe, exc)
            return []

    def get_ticker(self, symbol: str) -> Dict[str, Any]:
        """Return latest ticker for a symbol."""
        self._require_connected()
        try:
            return self._exchange.fetch_ticker(symbol)
        except Exception as exc:
            logger.error("Fetch ticker %s failed: %s", symbol, exc)
            return {}

    def get_orderbook(self, symbol: str, limit: int = 20) -> Dict[str, Any]:
        """Return order book (bids/asks)."""
        self._require_connected()
        try:
            return self._exchange.fetch_order_book(symbol, limit)
        except Exception as exc:
            logger.error("Fetch orderbook %s failed: %s", symbol, exc)
            return {"bids": [], "asks": []}

    def list_symbols(self) -> List[str]:
        """Return all tradeable symbols on this exchange."""
        self._require_connected()
        return list(self._exchange.markets.keys())

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _require_connected(self):
        if not self.connected or self._exchange is None:
            raise RuntimeError(f"{self.name} is not connected. Call connect() first.")

    def _parse_order(self, raw: Dict) -> Order:
        status_map = {
            "open": OrderStatus.OPEN,
            "closed": OrderStatus.FILLED,
            "canceled": OrderStatus.CANCELLED,
            "cancelled": OrderStatus.CANCELLED,
            "rejected": OrderStatus.REJECTED,
        }
        side_map = {"buy": OrderSide.BUY, "sell": OrderSide.SELL}
        type_map = {
            "market": OrderType.MARKET,
            "limit": OrderType.LIMIT,
            "stop": OrderType.STOP,
            "stop_limit": OrderType.STOP_LIMIT,
        }
        return Order(
            id=str(raw.get("id", "")),
            symbol=raw.get("symbol", ""),
            side=side_map.get(raw.get("side", "buy"), OrderSide.BUY),
            type=type_map.get(raw.get("type", "market"), OrderType.MARKET),
            quantity=float(raw.get("amount") or 0),
            price=raw.get("price"),
            status=status_map.get(raw.get("status", "open"), OrderStatus.OPEN),
            filled_quantity=float(raw.get("filled") or 0),
            average_price=raw.get("average"),
            timestamp=_ts(raw.get("timestamp")),
        )

    def _parse_position(self, raw: Dict) -> Position:
        side = "LONG" if float(raw.get("contracts") or raw.get("size") or 0) > 0 else "SHORT"
        return Position(
            symbol=raw.get("symbol", ""),
            side=side,
            quantity=abs(float(raw.get("contracts") or raw.get("size") or 0)),
            entry_price=float(raw.get("entryPrice") or 0),
            current_price=float(raw.get("markPrice") or raw.get("lastPrice") or 0),
            unrealized_pnl=float(raw.get("unrealizedPnl") or 0),
            realized_pnl=float(raw.get("realizedPnl") or 0),
            timestamp=datetime.now(timezone.utc),
        )


def list_supported_exchanges() -> List[str]:
    """Return all exchange IDs supported by ccxt."""
    try:
        import ccxt
        return ccxt.exchanges
    except ImportError:
        return []
