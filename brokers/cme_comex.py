# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
brokers/cme_comex.py
=====================
CME COMEX GC (Gold Futures) broker connector.

Venue
-----
CME Group COMEX division — the world's primary gold futures exchange.
Contract: GC (100 troy oz, tick = $0.10 = $10.00/contract)
Continuous front-month via CONTFUT roll.

Connectivity options (in priority order)
-----------------------------------------
1. FIX 4.4 via CME iLink 3 — direct market access, lowest latency.
   Requires CME Globex FIX credentials and a co-located or nearby server.
   Uses execution/fix_adapter.py with CME-specific session config.

2. IBKR TWS API — routes GC futures through Interactive Brokers.
   Higher latency than direct FIX but no CME membership required.
   Uses brokers/ibkr_connector.py internally.

3. Paper trading fallback — simulates fills from CME market data.
   Used when neither FIX nor IBKR credentials are configured.

Symbol mapping
--------------
  HOPEFX internal  →  CME FIX symbol
  "XAU_USD"        →  "GC"   (COMEX Gold front-month continuous)
  "GC"             →  "GC"
  "XAUUSD"         →  "GC"

Contract spec
-------------
  Exchange:        NYMEX (CME Group COMEX division)
  Security type:   FUT (futures) / CONTFUT (continuous front-month)
  Multiplier:      100 (troy oz per contract)
  Tick size:       0.10 (USD per troy oz)
  Tick value:      $10.00 per contract
  Margin:          ~$7,000 initial (check CME for current)
  Trading hours:   Sunday 18:00 – Friday 17:00 ET (nearly 24h)
  Settlement:      Physical delivery (most traders roll before FND)

Environment variables
---------------------
  CME_FIX_HOST           FIX gateway host (default: 127.0.0.1)
  CME_FIX_PORT           FIX gateway port (default: 9876)
  CME_FIX_SENDER_ID      SenderCompID (your CME-assigned ID)
  CME_FIX_TARGET_ID      TargetCompID (CME: "CME" for Globex)
  CME_FIX_USERNAME       FIX logon username
  CME_FIX_PASSWORD       FIX logon password
  CME_FIX_CONFIG_FILE    Path to fix.cfg override (optional)
  CME_ACCOUNT            CME clearing account number
  CME_IBKR_FALLBACK      "true" to enable IBKR fallback (default: true)
  CME_PAPER_FALLBACK     "true" to enable paper fallback (default: true)
  CME_DEFAULT_CONTRACTS  Default contract quantity (default: 1)
  CME_LATENCY_WARN_MS    Log warning if fill latency exceeds N ms (default: 50)

Usage
-----
    from brokers.cme_comex import CMEComexConnector

    broker = CMEComexConnector.from_env()
    broker.connect()

    order = broker.place_order(
        symbol="XAU_USD",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=1,          # 1 contract = 100 troy oz
        price=2350.00,
    )
    logger.info(order.order_id, order.filled_price)
    broker.disconnect()
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from brokers.base import (
    AccountInfo,
    BrokerConnector,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    with_retry,
)

UTC = timezone.utc
logger = logging.getLogger(__name__)

# ── Contract specification ────────────────────────────────────────────────────
_CME_MULTIPLIER = 100  # troy oz per GC contract
_CME_TICK_SIZE = 0.10  # USD per troy oz
_CME_TICK_VALUE = 10.00  # USD per tick per contract
_CME_EXCHANGE = "NYMEX"
_CME_SEC_TYPE = "CONTFUT"  # continuous front-month

# ── Symbol normalisation ──────────────────────────────────────────────────────
_SYMBOL_MAP: dict[str, str] = {
    "XAU_USD": "GC",
    "XAUUSD": "GC",
    "XAU/USD": "GC",
    "GOLD": "GC",
    "GC": "GC",
}

# ── Configuration ─────────────────────────────────────────────────────────────
_FIX_HOST = os.getenv("CME_FIX_HOST", "127.0.0.1")
_FIX_PORT = int(os.getenv("CME_FIX_PORT", "9876"))
_FIX_SENDER_ID = os.getenv("CME_FIX_SENDER_ID", "HOPEFX")
_FIX_TARGET_ID = os.getenv("CME_FIX_TARGET_ID", "CME")
_FIX_USERNAME = os.getenv("CME_FIX_USERNAME", "")
_FIX_PASSWORD = os.getenv("CME_FIX_PASSWORD", "")
_FIX_CONFIG_FILE = os.getenv("CME_FIX_CONFIG_FILE", "fix.cfg")
_CME_ACCOUNT = os.getenv("CME_ACCOUNT", "")
_IBKR_FALLBACK = os.getenv("CME_IBKR_FALLBACK", "true").lower() == "true"
_PAPER_FALLBACK = os.getenv("CME_PAPER_FALLBACK", "true").lower() == "true"
_DEFAULT_CONTRACTS = int(os.getenv("CME_DEFAULT_CONTRACTS", "1"))
_LATENCY_WARN_MS = float(os.getenv("CME_LATENCY_WARN_MS", "50"))


# ── Data structures ───────────────────────────────────────────────────────────


@dataclass
class CMEFill:
    """Normalised fill record from CME execution."""

    order_id: str
    cl_ord_id: str
    symbol: str
    side: str
    contracts: float
    avg_price: float
    commission: float
    latency_ms: float
    source: str  # "fix" | "ibkr" | "paper"
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def notional_usd(self) -> float:
        return self.contracts * _CME_MULTIPLIER * self.avg_price

    @property
    def tick_value_usd(self) -> float:
        return self.contracts * _CME_TICK_VALUE


# ── CME COMEX Connector ───────────────────────────────────────────────────────


class CMEComexConnector(BrokerConnector):
    """
    CME COMEX GC (Gold Futures) connector.

    Routing priority:
      1. Direct FIX 4.4 via CME iLink 3 (lowest latency, requires CME credentials)
      2. IBKR TWS API fallback (no CME membership required)
      3. Paper trading simulation (always available)

    All three implement the same BrokerConnector interface so the Smart Router
    and OMS work identically regardless of which path executes.
    """

    def __init__(
        self,
        fix_host: str = _FIX_HOST,
        fix_port: int = _FIX_PORT,
        fix_sender_id: str = _FIX_SENDER_ID,
        fix_target_id: str = _FIX_TARGET_ID,
        fix_username: str = _FIX_USERNAME,
        fix_password: str = _FIX_PASSWORD,
        fix_config_file: str = _FIX_CONFIG_FILE,
        cme_account: str = _CME_ACCOUNT,
        ibkr_fallback: bool = _IBKR_FALLBACK,
        paper_fallback: bool = _PAPER_FALLBACK,
    ) -> None:
        # Build a config dict for BrokerConnector.__init__ so self.config,
        # self.connected, self.name, and self.rate_limiter are all initialised.
        config: dict[str, Any] = {
            "fix_host": fix_host,
            "fix_port": fix_port,
            "fix_sender_id": fix_sender_id,
            "fix_target_id": fix_target_id,
            "cme_account": cme_account,
            "ibkr_fallback": ibkr_fallback,
            "paper_fallback": paper_fallback,
        }
        super().__init__(config)

        self._fix_host = fix_host
        self._fix_port = fix_port
        self._fix_sender_id = fix_sender_id
        self._fix_target_id = fix_target_id
        self._fix_username = fix_username
        self._fix_password = fix_password
        self._fix_config_file = fix_config_file
        self._cme_account = cme_account
        self._ibkr_fallback = ibkr_fallback
        self._paper_fallback = paper_fallback

        self._fix_adapter: Any | None = None
        self._ibkr_connector: Any | None = None
        self._fix_available: bool = False
        self._ibkr_available: bool = False
        # Note: self.connected is set by BrokerConnector.__init__ to False

        # Fill tracking
        self._fills: list[CMEFill] = []
        self._order_seq: int = 0

    @classmethod
    def from_env(cls) -> CMEComexConnector:
        """Construct from environment variables."""
        return cls()

    # ── BrokerConnector interface ─────────────────────────────────────────────

    def connect(self) -> bool:  # type: ignore[override]
        """
        Attempt FIX connection first, then IBKR fallback.
        Returns True if at least one execution path is available.
        """
        self._fix_available = self._init_fix()
        if not self._fix_available and self._ibkr_fallback:
            self._ibkr_available = self._init_ibkr()

        self.connected = self._fix_available or self._ibkr_available or self._paper_fallback

        logger.info(
            "CMEComexConnector connected — fix=%s ibkr=%s paper=%s",
            self._fix_available,
            self._ibkr_available,
            self._paper_fallback,
        )
        return self.connected

    def disconnect(self) -> bool:  # type: ignore[override]
        if self._fix_adapter:
            try:
                self._fix_adapter.stop()
            except Exception as exc:
                logger.warning("CME FIX disconnect error: %s", exc)
        self.connected = False
        logger.info("CMEComexConnector disconnected.")
        return True

    def place_order(  # type: ignore[override]
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        price: float | None = None,
        stop_price: float | None = None,
        **kwargs: Any,
    ) -> Order:
        """
        Place a GC futures order.

        quantity is in contracts (1 contract = 100 troy oz).
        price is in USD per troy oz (same as spot gold price).
        """
        fix_symbol = self._normalise_symbol(symbol)
        self._order_seq += 1

        t0 = time.monotonic()

        if self._fix_available and self._fix_adapter:
            fill = self._place_via_fix(fix_symbol, side, order_type, quantity, price, stop_price)
        elif self._ibkr_available and self._ibkr_connector:
            fill = self._place_via_ibkr(fix_symbol, side, order_type, quantity, price, stop_price)
        elif self._paper_fallback:
            fill = self._place_paper(fix_symbol, side, order_type, quantity, price)
        else:
            raise RuntimeError("CMEComexConnector: no execution path available — connect() first")

        latency_ms = (time.monotonic() - t0) * 1000
        if latency_ms > _LATENCY_WARN_MS:
            logger.warning("CME order latency %.1f ms exceeds warn threshold %.1f ms", latency_ms, _LATENCY_WARN_MS)

        self._fills.append(fill)
        return self._fill_to_order(fill, symbol, side, order_type, quantity)

    def get_account_info(self) -> AccountInfo:  # type: ignore[override]
        if self._ibkr_available and self._ibkr_connector:
            try:
                return self._ibkr_connector.get_account_info()
            except Exception as exc:
                logger.warning("CME: IBKR account info failed: %s", exc)
        return AccountInfo(
            balance=0.0,
            equity=0.0,
            margin_used=0.0,
            margin_available=0.0,
            positions_count=0,
        )

    def get_market_data(  # type: ignore[override]
        self,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Fetch GC OHLCV bars via IBKR or return empty list."""
        if self._ibkr_available and self._ibkr_connector:
            try:
                return self._ibkr_connector.get_market_data("GC", timeframe, limit)
            except Exception as exc:
                logger.warning("CME: IBKR market data failed: %s", exc)
        return []

    def get_positions(self) -> list[Position]:  # type: ignore[override]
        if self._ibkr_available and self._ibkr_connector:
            try:
                return self._ibkr_connector.get_positions()
            except Exception as exc:
                logger.warning("CME: IBKR positions failed: %s", exc)
        return []

    def cancel_order(self, order_id: str) -> bool:  # type: ignore[override]
        """Cancel a pending order. Not supported on paper path; IBKR delegates."""
        if self._ibkr_available and self._ibkr_connector:
            try:
                return self._ibkr_connector.cancel_order(order_id)
            except Exception as exc:
                logger.warning("CME: cancel_order failed: %s", exc)
        logger.warning("CME: cancel_order not supported on current execution path")
        return False

    def close_position(self, symbol: str) -> bool:  # type: ignore[override]
        """Close an open position. Delegates to IBKR when available."""
        if self._ibkr_available and self._ibkr_connector:
            try:
                return self._ibkr_connector.close_position(symbol)
            except Exception as exc:
                logger.warning("CME: close_position failed: %s", exc)
        logger.warning("CME: close_position not supported on current execution path")
        return False

    def get_order(self, order_id: str) -> Order | None:  # type: ignore[override]
        """Look up a previously placed order by ID from local fill history."""
        for fill in self._fills:
            if fill.order_id == order_id:
                return self._fill_to_order(
                    fill,
                    fill.symbol,
                    OrderSide(fill.side),
                    OrderType.MARKET,
                    fill.contracts,
                )
        return None

    # ── FIX execution path ────────────────────────────────────────────────────

    def _init_fix(self) -> bool:
        """Initialise FIX adapter for CME iLink 3."""
        try:
            from execution.fix_adapter import FIXAdapter

            self._fix_adapter = FIXAdapter(
                config_file=self._fix_config_file,
                sender_comp_id=self._fix_sender_id,
                target_comp_id=self._fix_target_id,
                host=self._fix_host,
                port=self._fix_port,
                username=self._fix_username,
                password=self._fix_password,
            )
            self._fix_adapter.start()
            logger.info("CME FIX session started — %s:%d", self._fix_host, self._fix_port)
            return True
        except Exception as exc:
            logger.info("CME FIX unavailable (%s) — will use fallback", exc)
            return False

    def _place_via_fix(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        price: float | None,
        stop_price: float | None,
    ) -> CMEFill:
        """Send order via FIX adapter (sync wrapper around async send_order)."""
        from execution.fix_adapter import FIXOrder, FIXOrdType, FIXSide

        fix_side = FIXSide.BUY if side == OrderSide.BUY else FIXSide.SELL
        fix_type = {
            OrderType.MARKET: FIXOrdType.MARKET,
            OrderType.LIMIT: FIXOrdType.LIMIT,
            OrderType.STOP: FIXOrdType.STOP,
        }.get(order_type, FIXOrdType.MARKET)

        fix_order = FIXOrder(
            symbol=symbol,
            side=fix_side,
            quantity=quantity,
            ord_type=fix_type,
            price=price,
            stop_px=stop_price,
            account=self._cme_account,
        )

        # Run async send_order in a new event loop if called from sync context
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(asyncio.run, self._fix_adapter.send_order(fix_order))
                    report = future.result(timeout=10.0)
            else:
                report = loop.run_until_complete(self._fix_adapter.send_order(fix_order))
        except Exception as exc:
            raise RuntimeError(f"CME FIX send_order failed: {exc}") from exc

        return CMEFill(
            order_id=report.order_id,
            cl_ord_id=report.cl_ord_id,
            symbol=symbol,
            side=side.value,
            contracts=report.cum_qty,
            avg_price=report.avg_px,
            commission=self._estimate_commission(report.cum_qty),
            latency_ms=report.latency_ms,
            source="fix",
        )

    # ── IBKR fallback path ────────────────────────────────────────────────────

    def _init_ibkr(self) -> bool:
        """Initialise IBKR connector as fallback for GC futures."""
        try:
            from brokers.ibkr_connector import IBKRConnector

            self._ibkr_connector = IBKRConnector(
                {
                    "host": os.getenv("IBKR_HOST", "127.0.0.1"),
                    "port": int(os.getenv("IBKR_PORT", "7497")),
                    "client_id": int(os.getenv("IBKR_CLIENT_ID", "10")),
                    "account": os.getenv("IBKR_ACCOUNT", ""),
                }
            )
            connected = self._ibkr_connector.connect()
            if connected:
                logger.info("CME: IBKR fallback connected for GC futures")
            return connected
        except Exception as exc:
            logger.info("CME: IBKR fallback unavailable (%s)", exc)
            return False

    def _place_via_ibkr(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        price: float | None,
        stop_price: float | None,
    ) -> CMEFill:
        """Route GC futures order through IBKR TWS."""
        t0 = time.monotonic()
        order = self._ibkr_connector.place_order(
            symbol="GC",
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            stop_price=stop_price,
        )
        latency_ms = (time.monotonic() - t0) * 1000
        return CMEFill(
            order_id=order.order_id,
            cl_ord_id=order.order_id,
            symbol=symbol,
            side=side.value,
            contracts=order.filled_quantity or quantity,
            avg_price=order.filled_price or (price or 0.0),
            commission=self._estimate_commission(quantity),
            latency_ms=latency_ms,
            source="ibkr",
        )

    # ── Paper fallback path ───────────────────────────────────────────────────

    def _place_paper(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        price: float | None,
    ) -> CMEFill:
        """Simulate a CME fill for paper trading.

        Fill price resolution order:
        1. Explicit ``price`` argument (limit/stop orders).
        2. Latest tick close from MarketDataCache (Redis).
        3. Latest OHLCV bar close from OHLCVStore ring buffer.
        4. Raises ``RuntimeError`` — no price source available.

        A hard-coded fallback is intentionally absent: paper fills must
        reflect real market prices so that P&L simulation is meaningful.
        """
        import uuid

        fill_price: float | None = price

        if fill_price is None or fill_price <= 0.0:
            fill_price = self._resolve_market_price(symbol)

        if fill_price is None or fill_price <= 0.0:
            raise RuntimeError(
                f"CME paper fill: no market price available for {symbol}. "
                "Ensure the market data feed is running and has published at "
                "least one tick or OHLCV bar before placing paper orders."
            )

        logger.info(
            "CME PAPER fill: %s %s %d contracts @ %.2f",
            side.value,
            symbol,
            int(quantity),
            fill_price,
        )
        return CMEFill(
            order_id=str(uuid.uuid4()),
            cl_ord_id=str(uuid.uuid4()),
            symbol=symbol,
            side=side.value,
            contracts=quantity,
            avg_price=fill_price,
            commission=self._estimate_commission(quantity),
            latency_ms=0.0,
            source="paper",
        )

    def _resolve_market_price(self, symbol: str) -> float | None:
        """
        Resolve the current mid-market price for *symbol* from live data.

        Tries, in order:
        1. MarketDataCache.get_latest_tick  (Redis tick stream)
        2. OHLCVStore.get                   (Redis-backed OHLCV ring buffer)

        Returns ``None`` when no data source has a price for the symbol.
        """
        cme_symbol = self._normalise_symbol(symbol)
        # Attempt both the CME symbol ("GC") and the HOPEFX internal form
        candidates = list({cme_symbol, symbol})

        # 1. Latest tick from Redis
        try:
            import redis as _redis_lib
            from market_data.redis_cache import MarketDataCache

            r = _redis_lib.from_url(
                os.getenv("REDIS_URL", "redis://localhost:6379/0"),
                socket_connect_timeout=1,
                socket_timeout=1,
                decode_responses=False,
            )
            r.ping()
            cache = MarketDataCache(r)
            for sym in candidates:
                tick = cache.get_latest_tick(sym)
                if tick:
                    close = tick.get("close") or tick.get("c") or tick.get("price") or tick.get("last")
                    if close and float(close) > 0:
                        return float(close)
        except Exception as exc:
            logger.debug("CME paper: Redis tick lookup failed (%s)", exc)

        # 2. Latest OHLCV bar from ring buffer
        try:
            from brokers.ohlcv_store import get_ohlcv_store

            store = get_ohlcv_store()
            for sym in candidates:
                df = store.get(sym, bars=1, allow_partial=True)
                if df is not None and not df.empty:
                    close = float(df["close"].iloc[-1])
                    if close > 0:
                        return close
        except Exception as exc:
            logger.debug("CME paper: OHLCVStore lookup failed (%s)", exc)

        return None

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _normalise_symbol(symbol: str) -> str:
        return _SYMBOL_MAP.get(symbol.upper().replace(" ", "_"), "GC")

    @staticmethod
    def _estimate_commission(contracts: float) -> float:
        """
        Estimate CME exchange fees + NFA surcharge.
        Typical all-in: $1.50–$2.50 per side per contract.
        """
        return round(contracts * 2.00, 2)

    @staticmethod
    def _fill_to_order(fill: CMEFill, symbol: str, side: OrderSide, order_type: OrderType, quantity: float) -> Order:
        return Order(
            id=fill.order_id,
            symbol=symbol,
            side=side,
            type=order_type,
            quantity=quantity,
            filled_quantity=fill.contracts,
            average_price=fill.avg_price,
            status=OrderStatus.FILLED,
            timestamp=fill.timestamp,
            metadata={"commission": fill.commission, "source": fill.source},
        )

    # ── Metrics ───────────────────────────────────────────────────────────────

    def metrics(self) -> dict[str, Any]:
        """Return fill statistics for monitoring."""
        if not self._fills:
            return {"fills": 0, "source": "none"}
        sources = {}
        for f in self._fills:
            sources[f.source] = sources.get(f.source, 0) + 1
        avg_latency = sum(f.latency_ms for f in self._fills) / len(self._fills)
        return {
            "fills": len(self._fills),
            "sources": sources,
            "avg_latency_ms": round(avg_latency, 2),
            "fix_available": self._fix_available,
            "ibkr_available": self._ibkr_available,
        }
