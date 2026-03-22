"""
OANDA REST v20 Broker Connector (synchronous)
Uses requests.Session. Supports practice and live environments.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import requests
from brokers.base import (AccountInfo, BrokerConnector, Order, OrderSide,
                           OrderStatus, OrderType, Position)

logger = logging.getLogger(__name__)


class OANDAConnector(BrokerConnector):
    PRACTICE_URL = "https://api-fxpractice.oanda.com"
    LIVE_URL     = "https://api-fxtrade.oanda.com"

    def __init__(self, config: Dict[str, Any] = None, api_key: str = None,
                 account_id: str = None, practice: bool = True, **kwargs):
        if config is None:
            config = {}
        # Allow keyword args to override config dict
        if api_key:
            config = dict(config); config["api_key"] = api_key
        if account_id:
            config = dict(config); config["account_id"] = account_id
        if not practice:
            config = dict(config); config["environment"] = "live"
        super().__init__(config)
        self.api_key    = config.get("api_key", "")
        self.account_id = config.get("account_id", "")
        if not self.api_key or not self.account_id:
            raise ValueError("OANDAConnector requires 'api_key' and 'account_id'")
        self.environment = config.get("environment", "practice")
        self.base_url    = self.LIVE_URL if self.environment == "live" else self.PRACTICE_URL
        self.session: Optional[requests.Session] = None
        self.name = "OANDA"

    def connect(self) -> bool:
        try:
            self.session = requests.Session()
            self.session.headers.update({"Authorization": f"Bearer {self.api_key}",
                                          "Content-Type": "application/json"})
            r = self.session.get(f"{self.base_url}/v3/accounts/{self.account_id}", timeout=10)
            r.raise_for_status()
            self.connected = True
            return True
        except Exception as exc:
            logger.error("OANDA connect failed: %s", exc)
            self.connected = False; self.session = None
            return False

    def disconnect(self) -> bool:
        if self.session: self.session.close(); self.session = None
        self.connected = False
        return True

    def place_order(self, symbol: str, side: OrderSide, quantity: float,
                    order_type: OrderType = OrderType.MARKET,
                    price: Optional[float] = None, **kw) -> Optional[Order]:
        if not self.connected or not self.session: return None
        units = quantity if side == OrderSide.BUY else -quantity
        body: Dict = {"order": {"instrument": symbol, "units": str(int(units)),
                                 "type": "MARKET" if order_type == OrderType.MARKET else "LIMIT",
                                 "timeInForce": "FOK" if order_type == OrderType.MARKET else "GTC"}}
        if price and order_type != OrderType.MARKET:
            body["order"]["price"] = str(price)
        try:
            r = self.session.post(f"{self.base_url}/v3/accounts/{self.account_id}/orders",
                                   json=body, timeout=10)
            r.raise_for_status()
            return self._parse_order_response(r.json(), symbol, side, abs(quantity))
        except Exception as exc:
            logger.error("OANDA place_order: %s", exc); return None

    def cancel_order(self, order_id: str, symbol: str = None) -> bool:
        if not self.connected or not self.session: return False
        try:
            r = self.session.put(f"{self.base_url}/v3/accounts/{self.account_id}/orders/{order_id}/cancel", timeout=10)
            r.raise_for_status(); return True
        except Exception as exc:
            logger.error("OANDA cancel_order: %s", exc); return False

    def get_order(self, order_id: str, symbol: str = None) -> Optional[Order]:
        if not self.connected or not self.session: return None
        try:
            r = self.session.get(f"{self.base_url}/v3/accounts/{self.account_id}/orders/{order_id}", timeout=10)
            r.raise_for_status(); return self._parse_order_dict(r.json().get("order", {}))
        except Exception as exc:
            logger.error("OANDA get_order: %s", exc); return None

    def get_positions(self) -> List[Position]:
        if not self.connected or not self.session: return []
        try:
            r = self.session.get(f"{self.base_url}/v3/accounts/{self.account_id}/openPositions", timeout=10)
            r.raise_for_status(); out = []
            for p in r.json().get("positions", []):
                lu = float(p.get("long",  {}).get("units", 0))
                su = float(p.get("short", {}).get("units", 0))
                if lu != 0:
                    side, units = "LONG",  lu
                    avg  = float(p["long"].get("averagePrice", 0))
                    upnl = float(p["long"].get("unrealizedPL",  0))
                    rpnl = float(p["long"].get("realizedPL",    0))
                elif su != 0:
                    side, units = "SHORT", abs(su)
                    avg  = float(p["short"].get("averagePrice", 0))
                    upnl = float(p["short"].get("unrealizedPL",  0))
                    rpnl = float(p["short"].get("realizedPL",    0))
                else: continue
                instrument = p.get("instrument", "").replace("_", "/")
                out.append(Position(symbol=instrument, side=side, quantity=units,
                                    entry_price=avg, current_price=avg, unrealized_pnl=upnl,
                                    realized_pnl=rpnl, timestamp=datetime.now(timezone.utc)))
            return out
        except Exception as exc:
            logger.error("OANDA get_positions: %s", exc); return []

    def close_position(self, symbol: str) -> bool:
        if not self.connected or not self.session: return False
        try:
            r = self.session.put(f"{self.base_url}/v3/accounts/{self.account_id}/positions/{symbol}/close",
                                  json={"longUnits":"ALL","shortUnits":"ALL"}, timeout=10)
            r.raise_for_status(); return True
        except Exception as exc:
            logger.error("OANDA close_position: %s", exc); return False

    def get_account_info(self) -> Optional[AccountInfo]:
        if not self.connected or not self.session: return None
        try:
            r = self.session.get(f"{self.base_url}/v3/accounts/{self.account_id}/summary", timeout=10)
            r.raise_for_status(); a = r.json().get("account", {})
            bal = float(a.get("balance", 0)); nav = float(a.get("NAV", bal))
            return AccountInfo(balance=bal, equity=nav,
                               margin_used=float(a.get("marginUsed", 0)),
                               margin_available=float(a.get("marginAvailable", nav)),
                               positions_count=int(a.get("openPositionCount", a.get("openTradeCount", 0))),
                               timestamp=datetime.now(timezone.utc))
        except Exception as exc:
            logger.error("OANDA get_account_info: %s", exc); return None

    def get_market_data(self, symbol: str, timeframe: str = "H1", limit: int = 100) -> List[Dict]:
        if not self.connected or not self.session: return []
        _TF = {"1m":"M1","5m":"M5","15m":"M15","30m":"M30","1h":"H1","4h":"H4","1d":"D","1w":"W"}
        gran = _TF.get(timeframe, timeframe)
        try:
            r = self.session.get(f"{self.base_url}/v3/instruments/{symbol}/candles",
                                  params={"granularity": gran, "count": limit}, timeout=10)
            r.raise_for_status()
            return [{"timestamp": c.get("time"), "open": float(c["mid"]["o"]),
                     "high": float(c["mid"]["h"]), "low": float(c["mid"]["l"]),
                     "close": float(c["mid"]["c"]), "volume": int(c.get("volume", 0))}
                    for c in r.json().get("candles", []) if c.get("complete", True)]
        except Exception as exc:
            logger.error("OANDA get_market_data: %s", exc); return []

    def _parse_order_response(self, data: Dict, symbol: str, side: OrderSide, qty: float) -> Order:
        fill   = data.get("orderFillTransaction")
        create = data.get("orderCreateTransaction")
        if fill:
            return Order(id=str(fill.get("id","")), symbol=symbol, side=side,
                         type=OrderType.MARKET, quantity=abs(float(fill.get("units", qty))),
                         price=float(fill["price"]) if fill.get("price") else None,
                         status=OrderStatus.FILLED,
                         filled_quantity=abs(float(fill.get("units", qty))),
                         timestamp=datetime.now(timezone.utc))
        if create:
            return Order(id=str(create.get("id","")), symbol=symbol, side=side,
                         type=OrderType.LIMIT, quantity=abs(float(create.get("units", qty))),
                         price=float(create["price"]) if create.get("price") else None,
                         status=OrderStatus.OPEN, filled_quantity=0.0,
                         timestamp=datetime.now(timezone.utc))
        return Order(id="", symbol=symbol, side=side, type=OrderType.MARKET,
                     quantity=qty, status=OrderStatus.REJECTED, filled_quantity=0.0,
                     timestamp=datetime.now(timezone.utc))

    _STATUS_MAP = {
        "FILLED": OrderStatus.FILLED,
        "CANCELLED": OrderStatus.CANCELLED,
        "PENDING": OrderStatus.PENDING,
        "OPEN": OrderStatus.OPEN,
        "TRIGGERED": OrderStatus.FILLED,
        "REJECTED": OrderStatus.REJECTED,
    }

    def _parse_order_status(self, state: str) -> OrderStatus:
        return self._STATUS_MAP.get(state.upper(), OrderStatus.OPEN)

    def _parse_order_dict(self, data: Dict) -> Order:
        side = OrderSide.BUY if float(data.get("units", 1)) > 0 else OrderSide.SELL
        sm = {"PENDING": OrderStatus.OPEN, "FILLED": OrderStatus.FILLED,
              "CANCELLED": OrderStatus.CANCELLED, "TRIGGERED": OrderStatus.FILLED}
        return Order(id=str(data.get("id","")), symbol=data.get("instrument",""),
                     side=side, type=OrderType.LIMIT if data.get("price") else OrderType.MARKET,
                     quantity=abs(float(data.get("units", 0))),
                     price=float(data["price"]) if data.get("price") else None,
                     status=sm.get(data.get("state",""), OrderStatus.OPEN),
                     filled_quantity=abs(float(data.get("filledUnits", 0))),
                     timestamp=datetime.now(timezone.utc))


# Backward-compat aliases
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

