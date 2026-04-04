# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
brokers/bybit_connector.py
===========================
ByBit DMA-like connector for XAUUSDT perpetual futures.

ByBit operates a Central Limit Order Book (CLOB) for its perpetual futures
markets.  Your order goes directly into the public book — there is no market
maker internalising it.  XAUUSDT perpetuals give gold exposure without retail
broker spread manipulation.

Usage
-----
    broker = ByBitConnector({
        "api_key": "...",
        "api_secret": "...",
        "sandbox": True,      # use testnet (default: True for safety)
        "symbol_map": {       # optional override
            "XAUUSD": "XAUUSDT",
        },
    })
    broker.connect()
    info  = broker.get_account_info()
    ohlcv = broker.get_market_data("XAUUSD", "1h", 200)
    order = broker.place_order(
        symbol="XAUUSD",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=0.01,
        price=2350.0,
    )

Environment variables
---------------------
BYBIT_API_KEY       ByBit API key
BYBIT_API_SECRET    ByBit API secret
BYBIT_SANDBOX       "true" | "false"  (default: "true")
BYBIT_DEFAULT_TYPE  "linear" | "inverse" | "spot"  (default: "linear")

Notes
-----
- Default market type is "linear" (USDT-margined perpetuals, e.g. XAUUSDT).
- ByBit symbol for gold is "XAUUSDT" (not "XAUUSD" or "XAU/USD").
- The ``symbol_map`` config key translates HOPEFX internal symbols to ByBit
  symbols so the rest of the system can use "XAUUSD" throughout.
- Uses :class:`brokers.ccxt_connector.CCXTConnector` internally — no direct
  ByBit SDK required.
- Sandbox is enabled by default.  Set ``BYBIT_SANDBOX=false`` (and explicitly
  pass ``sandbox=False`` in config) to switch to live trading.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from brokers.base import (
    AccountInfo,
    BrokerConnector,
    Order,
    OrderSide,
    OrderType,
    Position,
)

logger = logging.getLogger(__name__)

# ── Default symbol mapping  HOPEFX → ByBit ──────────────────────────────────
# "XAU/USD" is listed before "XAUUSD" so that "XAUUSD" wins the reverse map
# (XAUUSDT → XAUUSD) when the reverse dict is built from the final iteration.
_DEFAULT_SYMBOL_MAP: dict[str, str] = {
    "XAU/USD": "XAUUSDT",
    "XAUUSD": "XAUUSDT",
    "BTCUSD": "BTCUSDT",
    "ETHUSD": "ETHUSDT",
    "SOLUSD": "SOLUSDT",
}

# Reverse map (ByBit → HOPEFX) for translating responses back
_DEFAULT_SYMBOL_MAP_REV: dict[str, str] = {v: k for k, v in _DEFAULT_SYMBOL_MAP.items()}


class ByBitConnector(BrokerConnector):
    """
    ByBit CLOB connector wrapping CCXT for XAUUSDT and other perpetual futures.

    Extends ``BrokerConnector`` so it can be used anywhere a broker is expected.
    Delegates all exchange communication to :class:`~brokers.ccxt_connector.CCXTConnector`.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.name = "ByBit"

        # Resolve credentials from env if not in config
        api_key = config.get("api_key") or os.getenv("BYBIT_API_KEY", "")
        api_secret = config.get("api_secret") or os.getenv("BYBIT_API_SECRET", "")

        sandbox_env = os.getenv("BYBIT_SANDBOX", "true").lower() == "true"
        sandbox = config.get("sandbox", sandbox_env)

        default_type = config.get("default_type") or os.getenv("BYBIT_DEFAULT_TYPE", "linear")

        symbol_map: dict[str, str] = dict(_DEFAULT_SYMBOL_MAP)
        symbol_map.update(config.get("symbol_map") or {})
        self._symbol_map = symbol_map
        self._symbol_map_rev = {v: k for k, v in symbol_map.items()}

        ccxt_config: dict[str, Any] = {
            "exchange": "bybit",
            "api_key": api_key,
            "api_secret": api_secret,
            "sandbox": sandbox,
            "options": {
                "defaultType": default_type,
                # ByBit requires a recv_window for signed requests
                "recvWindow": int(config.get("recv_window", 5000)),
            },
        }

        from brokers.ccxt_connector import CCXTConnector

        self._ccxt = CCXTConnector(ccxt_config)

        mode_str = "SANDBOX/TESTNET" if sandbox else "LIVE"
        logger.info(
            "ByBitConnector initialised | mode=%s | type=%s | symbol_map=%s",
            mode_str,
            default_type,
            list(symbol_map.keys()),
        )

    # ── Symbol translation helpers ────────────────────────────────────────────

    def _to_bybit(self, symbol: str) -> str:
        """Translate an internal symbol to ByBit format."""
        return self._symbol_map.get(symbol, symbol)

    def _from_bybit(self, symbol: str) -> str:
        """Translate a ByBit symbol back to internal format."""
        return self._symbol_map_rev.get(symbol, symbol)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def connect(self) -> bool:
        self._ccxt.connect()
        self.connected = self._ccxt.connected
        if self.connected:
            logger.info("ByBitConnector: connected to ByBit exchange.")
        else:
            logger.error("ByBitConnector: connection failed.")
        return self.connected

    def disconnect(self) -> bool:
        result = self._ccxt.disconnect()
        self.connected = False
        return result

    # ── Account ───────────────────────────────────────────────────────────────

    def get_account_info(self) -> AccountInfo:
        """Return ByBit account info as :class:`~brokers.base.AccountInfo`."""
        info = self._ccxt.get_account_info()
        if info is None:
            return AccountInfo(
                balance=0.0,
                equity=0.0,
                margin_used=0.0,
                margin_available=0.0,
                positions_count=0,
            )
        return info

    # ── Market data ───────────────────────────────────────────────────────────

    def get_market_data(
        self,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 200,
    ):
        """Return OHLCV data for *symbol* (translated to ByBit format)."""
        bybit_sym = self._to_bybit(symbol)
        return self._ccxt.get_market_data(bybit_sym, timeframe, limit)

    def get_current_price(self, symbol: str) -> float | None:
        """Return the current mid-price for *symbol*."""
        bybit_sym = self._to_bybit(symbol)
        return self._ccxt.get_current_price(bybit_sym)

    # ── Orders ────────────────────────────────────────────────────────────────

    def place_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        price: float | None = None,
        stop_price: float | None = None,
    ) -> Order:
        """Place an order on ByBit via CCXT."""
        bybit_sym = self._to_bybit(symbol)
        order = self._ccxt.place_order(
            symbol=bybit_sym,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            stop_price=stop_price,
        )
        # Translate symbol back in the returned order
        if order is not None and hasattr(order, "symbol"):
            object.__setattr__(order, "symbol", self._from_bybit(order.symbol))
        return order

    def cancel_order(self, order_id: str) -> bool:
        return self._ccxt.cancel_order(order_id)

    def get_order(self, order_id: str) -> Order | None:
        """Return order details by ID."""
        return self._ccxt.get_order(order_id)

    def cancel_all_orders(self) -> bool:
        return self._ccxt.cancel_all_orders()

    # ── Positions ─────────────────────────────────────────────────────────────

    def get_positions(self) -> list[Position]:
        positions = self._ccxt.get_positions()
        for pos in positions:
            if hasattr(pos, "symbol"):
                object.__setattr__(pos, "symbol", self._from_bybit(pos.symbol))
        return positions

    def close_position(self, symbol: str) -> bool:
        """Close the open position for *symbol* on ByBit."""
        bybit_sym = self._to_bybit(symbol)
        try:
            return bool(self._ccxt.close_position(bybit_sym))
        except (RuntimeError, OSError, ValueError) as exc:
            logger.error("ByBitConnector.close_position(%s) failed: %s", symbol, exc)
            return False

    # ── Diagnostics ───────────────────────────────────────────────────────────

    def get_exchange_info(self) -> dict[str, Any]:
        """Return ByBit exchange metadata for *XAUUSDT* and related symbols."""
        return self._ccxt.get_exchange_info()

    def __repr__(self) -> str:
        sandbox = self.config.get("sandbox", True)
        return f"ByBitConnector(mode={'SANDBOX' if sandbox else 'LIVE'}, connected={self.connected})"
