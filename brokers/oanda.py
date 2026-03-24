"""
OANDA REST v20 Broker Connectors

Two implementations are provided:

OANDAConnector (synchronous)
    Uses requests.Session.  Kept for backward compatibility with CLI tools,
    tests, and any non-async callers.  Do NOT use inside an async FastAPI
    application — every call blocks the event loop.

AsyncOANDAConnector (async)
    Uses aiohttp.ClientSession.  Use this in all async contexts (FastAPI,
    asyncio trading loops, signal engine).  Calling synchronous
    OANDAConnector methods from an async application blocks the event loop
    on every API call, causing missed fills and stale prices.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

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

_PRACTICE_URL = "https://api-fxpractice.oanda.com"
_LIVE_URL = "https://api-fxtrade.oanda.com"

_TF_MAP: Dict[str, str] = {
    "1m": "M1", "5m": "M5", "15m": "M15", "30m": "M30",
    "1h": "H1", "4h": "H4", "1d": "D", "1w": "W",
}

_STATUS_MAP: Dict[str, OrderStatus] = {
    "FILLED": OrderStatus.FILLED,
    "CANCELLED": OrderStatus.CANCELLED,
    "PENDING": OrderStatus.PENDING,
    "OPEN": OrderStatus.OPEN,
    "TRIGGERED": OrderStatus.FILLED,
    "REJECTED": OrderStatus.REJECTED,
}


# ---------------------------------------------------------------------------
# Shared parsing helpers (used by both sync and async connectors)
# ---------------------------------------------------------------------------

def _parse_order_response(
    data: Dict, symbol: str, side: OrderSide, qty: float
) -> Order:
    fill = data.get("orderFillTransaction")
    create = data.get("orderCreateTransaction")
    if fill:
        return Order(
            id=str(fill.get("id", "")),
            symbol=symbol,
            side=side,
            type=OrderType.MARKET,
            quantity=abs(float(fill.get("units", qty))),
            price=float(fill["price"]) if fill.get("price") else None,
            status=OrderStatus.FILLED,
            filled_quantity=abs(float(fill.get("units", qty))),
            timestamp=datetime.now(timezone.utc),
        )
    if create:
        return Order(
            id=str(create.get("id", "")),
            symbol=symbol,
            side=side,
            type=OrderType.LIMIT,
            quantity=abs(float(create.get("units", qty))),
            price=float(create["price"]) if create.get("price") else None,
            status=OrderStatus.OPEN,
            filled_quantity=0.0,
            timestamp=datetime.now(timezone.utc),
        )
    return Order(
        id="",
        symbol=symbol,
        side=side,
        type=OrderType.MARKET,
        quantity=qty,
        status=OrderStatus.REJECTED,
        filled_quantity=0.0,
        timestamp=datetime.now(timezone.utc),
    )


def _parse_order_dict(data: Dict) -> Order:
    side = OrderSide.BUY if float(data.get("units", 1)) > 0 else OrderSide.SELL
    sm = {
        "PENDING": OrderStatus.OPEN,
        "FILLED": OrderStatus.FILLED,
        "CANCELLED": OrderStatus.CANCELLED,
        "TRIGGERED": OrderStatus.FILLED,
    }
    return Order(
        id=str(data.get("id", "")),
        symbol=data.get("instrument", ""),
        side=side,
        type=OrderType.LIMIT if data.get("price") else OrderType.MARKET,
        quantity=abs(float(data.get("units", 0))),
        price=float(data["price"]) if data.get("price") else None,
        status=sm.get(data.get("state", ""), OrderStatus.OPEN),
        filled_quantity=abs(float(data.get("filledUnits", 0))),
        timestamp=datetime.now(timezone.utc),
    )


def _parse_positions(raw_positions: List[Dict]) -> List[Position]:
    out: List[Position] = []
    for p in raw_positions:
        lu = float(p.get("long", {}).get("units", 0))
        su = float(p.get("short", {}).get("units", 0))
        if lu != 0:
            side, units = "LONG", lu
            avg = float(p["long"].get("averagePrice", 0))
            upnl = float(p["long"].get("unrealizedPL", 0))
            rpnl = float(p["long"].get("realizedPL", 0))
        elif su != 0:
            side, units = "SHORT", abs(su)
            avg = float(p["short"].get("averagePrice", 0))
            upnl = float(p["short"].get("unrealizedPL", 0))
            rpnl = float(p["short"].get("realizedPL", 0))
        else:
            continue
        instrument = p.get("instrument", "").replace("_", "/")
        out.append(
            Position(
                symbol=instrument,
                side=side,
                quantity=units,
                entry_price=avg,
                current_price=avg,
                unrealized_pnl=upnl,
                realized_pnl=rpnl,
                timestamp=datetime.now(timezone.utc),
            )
        )
    return out


# ---------------------------------------------------------------------------
# Synchronous connector (backward compat — do not use in async contexts)
# ---------------------------------------------------------------------------

class OANDAConnector(BrokerConnector):
    """
    Synchronous OANDA REST v20 connector.

    WARNING: Uses requests.Session which blocks the calling thread on every
    API call.  In an async FastAPI application this blocks the event loop,
    causing missed fills and stale prices.  Use AsyncOANDAConnector instead.
    """

    PRACTICE_URL = _PRACTICE_URL
    LIVE_URL = _LIVE_URL

    def __init__(
        self,
        config: Dict[str, Any] = None,
        api_key: str = None,
        account_id: str = None,
        practice: bool = True,
        **kwargs,
    ):
        if config is None:
            config = {}
        if api_key:
            config = dict(config); config["api_key"] = api_key
        if account_id:
            config = dict(config); config["account_id"] = account_id
        if not practice:
            config = dict(config); config["environment"] = "live"
        super().__init__(config)
        self.api_key = config.get("api_key", "")
        self.account_id = config.get("account_id", "")
        if not self.api_key or not self.account_id:
            raise ValueError("OANDAConnector requires 'api_key' and 'account_id'")
        self.environment = config.get("environment", "practice")
        self.base_url = self.LIVE_URL if self.environment == "live" else self.PRACTICE_URL
        self.session: Optional[requests.Session] = None
        self.name = "OANDA"

    def connect(self) -> bool:
        try:
            self.session = requests.Session()
            self.session.headers.update(
                {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
            )
            r = self.session.get(
                f"{self.base_url}/v3/accounts/{self.account_id}", timeout=10
            )
            r.raise_for_status()
            self.connected = True
            return True
        except Exception as exc:
            logger.error("OANDA connect failed: %s", exc)
            self.connected = False
            self.session = None
            return False

    def disconnect(self) -> bool:
        if self.session:
            self.session.close()
            self.session = None
        self.connected = False
        return True

    def place_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        order_type: OrderType = OrderType.MARKET,
        price: Optional[float] = None,
        **kw,
    ) -> Optional[Order]:
        if not self.connected or not self.session:
            return None
        units = quantity if side == OrderSide.BUY else -quantity
        body: Dict = {
            "order": {
                "instrument": symbol,
                "units": str(int(units)),
                "type": "MARKET" if order_type == OrderType.MARKET else "LIMIT",
                "timeInForce": "FOK" if order_type == OrderType.MARKET else "GTC",
            }
        }
        if price and order_type != OrderType.MARKET:
            body["order"]["price"] = str(price)
        try:
            r = self.session.post(
                f"{self.base_url}/v3/accounts/{self.account_id}/orders",
                json=body,
                timeout=10,
            )
            r.raise_for_status()
            return _parse_order_response(r.json(), symbol, side, abs(quantity))
        except Exception as exc:
            logger.error("OANDA place_order: %s", exc)
            return None

    def cancel_order(self, order_id: str, symbol: str = None) -> bool:
        if not self.connected or not self.session:
            return False
        try:
            r = self.session.put(
                f"{self.base_url}/v3/accounts/{self.account_id}/orders/{order_id}/cancel",
                timeout=10,
            )
            r.raise_for_status()
            return True
        except Exception as exc:
            logger.error("OANDA cancel_order: %s", exc)
            return False

    def get_order(self, order_id: str, symbol: str = None) -> Optional[Order]:
        if not self.connected or not self.session:
            return None
        try:
            r = self.session.get(
                f"{self.base_url}/v3/accounts/{self.account_id}/orders/{order_id}",
                timeout=10,
            )
            r.raise_for_status()
            return _parse_order_dict(r.json().get("order", {}))
        except Exception as exc:
            logger.error("OANDA get_order: %s", exc)
            return None

    def get_positions(self) -> List[Position]:
        if not self.connected or not self.session:
            return []
        try:
            r = self.session.get(
                f"{self.base_url}/v3/accounts/{self.account_id}/openPositions",
                timeout=10,
            )
            r.raise_for_status()
            return _parse_positions(r.json().get("positions", []))
        except Exception as exc:
            logger.error("OANDA get_positions: %s", exc)
            return []

    def close_position(self, symbol: str) -> bool:
        if not self.connected or not self.session:
            return False
        try:
            r = self.session.put(
                f"{self.base_url}/v3/accounts/{self.account_id}/positions/{symbol}/close",
                json={"longUnits": "ALL", "shortUnits": "ALL"},
                timeout=10,
            )
            r.raise_for_status()
            return True
        except Exception as exc:
            logger.error("OANDA close_position: %s", exc)
            return False

    def get_account_info(self) -> Optional[AccountInfo]:
        if not self.connected or not self.session:
            return None
        try:
            r = self.session.get(
                f"{self.base_url}/v3/accounts/{self.account_id}/summary", timeout=10
            )
            r.raise_for_status()
            a = r.json().get("account", {})
            bal = float(a.get("balance", 0))
            nav = float(a.get("NAV", bal))
            return AccountInfo(
                balance=bal,
                equity=nav,
                margin_used=float(a.get("marginUsed", 0)),
                margin_available=float(a.get("marginAvailable", nav)),
                positions_count=int(
                    a.get("openPositionCount", a.get("openTradeCount", 0))
                ),
                timestamp=datetime.now(timezone.utc),
            )
        except Exception as exc:
            logger.error("OANDA get_account_info: %s", exc)
            return None

    def get_market_data(
        self, symbol: str, timeframe: str = "H1", limit: int = 100
    ) -> List[Dict]:
        if not self.connected or not self.session:
            return []
        gran = _TF_MAP.get(timeframe, timeframe)
        try:
            r = self.session.get(
                f"{self.base_url}/v3/instruments/{symbol}/candles",
                params={"granularity": gran, "count": limit},
                timeout=10,
            )
            r.raise_for_status()
            return [
                {
                    "timestamp": c.get("time"),
                    "open": float(c["mid"]["o"]),
                    "high": float(c["mid"]["h"]),
                    "low": float(c["mid"]["l"]),
                    "close": float(c["mid"]["c"]),
                    "volume": int(c.get("volume", 0)),
                }
                for c in r.json().get("candles", [])
                if c.get("complete", True)
            ]
        except Exception as exc:
            logger.error("OANDA get_market_data: %s", exc)
            return []

    def get_live_prices(self, symbols: List[str]) -> Dict[str, Dict[str, float]]:
        """Fetch live bid/ask for one or more instruments."""
        if not self.connected or not self.session:
            return {}
        instruments = ",".join(s.replace("/", "_") for s in symbols)
        try:
            r = self.session.get(
                f"{self.base_url}/v3/accounts/{self.account_id}/pricing",
                params={"instruments": instruments},
                timeout=10,
            )
            r.raise_for_status()
            out: Dict[str, Dict[str, float]] = {}
            for price in r.json().get("prices", []):
                raw = price.get("instrument", "")
                sym = raw.replace("_", "")
                bid = float(price.get("bids", [{}])[0].get("price", 0))
                ask = float(price.get("asks", [{}])[0].get("price", 0))
                out[sym] = {"bid": bid, "ask": ask, "mid": round((bid + ask) / 2, 5)}
            return out
        except Exception as exc:
            logger.warning("OANDA get_live_prices: %s", exc)
            return {}

    # Keep private helpers for any external callers that reference them directly
    def _parse_order_response(self, data, symbol, side, qty):
        return _parse_order_response(data, symbol, side, qty)

    def _parse_order_dict(self, data):
        return _parse_order_dict(data)

    def _parse_order_status(self, state: str) -> OrderStatus:
        return _STATUS_MAP.get(state.upper(), OrderStatus.OPEN)


# ---------------------------------------------------------------------------
# Async connector — use this in all async / FastAPI contexts
# ---------------------------------------------------------------------------

class AsyncOANDAConnector:
    """
    Async OANDA REST v20 connector using aiohttp.ClientSession.

    All methods are coroutines and must be awaited.  Use as an async context
    manager to ensure the session is properly closed:

        async with AsyncOANDAConnector(api_key=..., account_id=...) as conn:
            info = await conn.get_account_info()

    Or manage the lifecycle manually:

        conn = AsyncOANDAConnector(api_key=..., account_id=...)
        await conn.connect()
        ...
        await conn.disconnect()
    """

    PRACTICE_URL = _PRACTICE_URL
    LIVE_URL = _LIVE_URL

    def __init__(
        self,
        api_key: str = "",
        account_id: str = "",
        practice: bool = True,
        timeout: float = 10.0,
        **kwargs,
    ):
        if not api_key or not account_id:
            raise ValueError("AsyncOANDAConnector requires api_key and account_id")
        self.api_key = api_key
        self.account_id = account_id
        self.base_url = self.PRACTICE_URL if practice else self.LIVE_URL
        self._timeout = timeout
        self._session: Optional[Any] = None  # aiohttp.ClientSession
        self.connected = False
        self.name = "OANDA-async"

    async def __aenter__(self) -> "AsyncOANDAConnector":
        await self.connect()
        return self

    async def __aexit__(self, *args) -> None:
        await self.disconnect()

    async def connect(self) -> bool:
        try:
            import aiohttp
            self._session = aiohttp.ClientSession(
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=aiohttp.ClientTimeout(total=self._timeout),
            )
            async with self._session.get(
                f"{self.base_url}/v3/accounts/{self.account_id}"
            ) as resp:
                resp.raise_for_status()
            self.connected = True
            logger.info("AsyncOANDAConnector connected (%s)", self.base_url)
            return True
        except Exception as exc:
            logger.error("AsyncOANDAConnector connect failed: %s", exc)
            if self._session:
                await self._session.close()
                self._session = None
            self.connected = False
            return False

    async def disconnect(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None
        self.connected = False

    def _require_session(self) -> Any:
        if not self.connected or self._session is None:
            raise RuntimeError(
                "AsyncOANDAConnector is not connected. Call await connect() first."
            )
        return self._session

    async def place_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        order_type: OrderType = OrderType.MARKET,
        price: Optional[float] = None,
        **kw,
    ) -> Optional[Order]:
        session = self._require_session()
        units = quantity if side == OrderSide.BUY else -quantity
        body: Dict = {
            "order": {
                "instrument": symbol,
                "units": str(int(units)),
                "type": "MARKET" if order_type == OrderType.MARKET else "LIMIT",
                "timeInForce": "FOK" if order_type == OrderType.MARKET else "GTC",
            }
        }
        if price and order_type != OrderType.MARKET:
            body["order"]["price"] = str(price)
        try:
            async with session.post(
                f"{self.base_url}/v3/accounts/{self.account_id}/orders", json=body
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
            return _parse_order_response(data, symbol, side, abs(quantity))
        except Exception as exc:
            logger.error("AsyncOANDAConnector place_order: %s", exc)
            return None

    async def cancel_order(self, order_id: str, symbol: str = None) -> bool:
        session = self._require_session()
        try:
            async with session.put(
                f"{self.base_url}/v3/accounts/{self.account_id}/orders/{order_id}/cancel"
            ) as resp:
                resp.raise_for_status()
            return True
        except Exception as exc:
            logger.error("AsyncOANDAConnector cancel_order: %s", exc)
            return False

    async def get_order(self, order_id: str, symbol: str = None) -> Optional[Order]:
        session = self._require_session()
        try:
            async with session.get(
                f"{self.base_url}/v3/accounts/{self.account_id}/orders/{order_id}"
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
            return _parse_order_dict(data.get("order", {}))
        except Exception as exc:
            logger.error("AsyncOANDAConnector get_order: %s", exc)
            return None

    async def get_positions(self) -> List[Position]:
        session = self._require_session()
        try:
            async with session.get(
                f"{self.base_url}/v3/accounts/{self.account_id}/openPositions"
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
            return _parse_positions(data.get("positions", []))
        except Exception as exc:
            logger.error("AsyncOANDAConnector get_positions: %s", exc)
            return []

    async def close_position(self, symbol: str) -> bool:
        session = self._require_session()
        try:
            async with session.put(
                f"{self.base_url}/v3/accounts/{self.account_id}/positions/{symbol}/close",
                json={"longUnits": "ALL", "shortUnits": "ALL"},
            ) as resp:
                resp.raise_for_status()
            return True
        except Exception as exc:
            logger.error("AsyncOANDAConnector close_position: %s", exc)
            return False

    async def get_account_info(self) -> Optional[AccountInfo]:
        session = self._require_session()
        try:
            async with session.get(
                f"{self.base_url}/v3/accounts/{self.account_id}/summary"
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
            a = data.get("account", {})
            bal = float(a.get("balance", 0))
            nav = float(a.get("NAV", bal))
            return AccountInfo(
                balance=bal,
                equity=nav,
                margin_used=float(a.get("marginUsed", 0)),
                margin_available=float(a.get("marginAvailable", nav)),
                positions_count=int(
                    a.get("openPositionCount", a.get("openTradeCount", 0))
                ),
                timestamp=datetime.now(timezone.utc),
            )
        except Exception as exc:
            logger.error("AsyncOANDAConnector get_account_info: %s", exc)
            return None

    async def get_market_data(
        self, symbol: str, timeframe: str = "H1", limit: int = 100
    ) -> List[Dict]:
        session = self._require_session()
        gran = _TF_MAP.get(timeframe, timeframe)
        try:
            async with session.get(
                f"{self.base_url}/v3/instruments/{symbol}/candles",
                params={"granularity": gran, "count": limit},
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
            return [
                {
                    "timestamp": c.get("time"),
                    "open": float(c["mid"]["o"]),
                    "high": float(c["mid"]["h"]),
                    "low": float(c["mid"]["l"]),
                    "close": float(c["mid"]["c"]),
                    "volume": int(c.get("volume", 0)),
                }
                for c in data.get("candles", [])
                if c.get("complete", True)
            ]
        except Exception as exc:
            logger.error("AsyncOANDAConnector get_market_data: %s", exc)
            return []

    async def get_live_prices(
        self, symbols: List[str]
    ) -> Dict[str, Dict[str, float]]:
        """Fetch live bid/ask for one or more instruments."""
        session = self._require_session()
        instruments = ",".join(s.replace("/", "_") for s in symbols)
        try:
            async with session.get(
                f"{self.base_url}/v3/accounts/{self.account_id}/pricing",
                params={"instruments": instruments},
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
            out: Dict[str, Dict[str, float]] = {}
            for price in data.get("prices", []):
                raw = price.get("instrument", "")
                sym = raw.replace("_", "")
                bid = float(price.get("bids", [{}])[0].get("price", 0))
                ask = float(price.get("asks", [{}])[0].get("price", 0))
                out[sym] = {"bid": bid, "ask": ask, "mid": round((bid + ask) / 2, 5)}
            return out
        except Exception as exc:
            logger.warning("AsyncOANDAConnector get_live_prices: %s", exc)
            return {}


# ---------------------------------------------------------------------------
# Backward-compat aliases
# ---------------------------------------------------------------------------

class OandaBroker:
    """Async-friendly OANDA broker wrapper used by integration tests."""

    def __init__(self, api_key: str = "", account_id: str = "", **kwargs):
        self.api_key = api_key
        self.account_id = account_id
        self.connected = False
        self.api = None
        self.risk_manager = None

    async def connect(self) -> bool:
        if self.api and hasattr(self.api, "get_account"):
            try:
                self.api.get_account()
                self.connected = True
                return True
            except Exception:
                return False
        self.connected = True
        return True

    async def place_order(self, order: dict = None, **kwargs) -> Optional[dict]:
        od = order if order is not None else kwargs
        rm = getattr(self, "risk_manager", None)
        if rm and hasattr(rm, "check_order"):
            check = rm.check_order(od)
            if check and not check.passed:
                raise ValueError(check.message)
        if self.api and hasattr(self.api, "place_order"):
            result = self.api.place_order(**od)
            return result
        return {"id": "mock", "status": "filled"}


OandaAPI = OANDAConnector
