# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Paper Trading Broker

Simulated broker for testing strategies without real money.
"""

import logging
import math
import os
import random
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any

from .base import (
    AccountInfo,
    BrokerConnector,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
)

UTC = timezone.utc

logger = logging.getLogger(__name__)


class StalePriceError(RuntimeError):
    """Raised when the paper broker's price feed is stale and PAPER_RAISE_ON_STALE=true.

    In live-adjacent paper trading (e.g. shadow mode alongside a live account)
    filling orders at a stale price produces misleading P&L. Set
    PAPER_RAISE_ON_STALE=true to block fills instead of silently using
    an outdated price.

    Set PAPER_RAISE_ON_STALE=false (default) to retain the legacy warn-and-fill
    behaviour for offline demo / backtesting scenarios.
    """

# ── Per-symbol spread table (bid-ask half-spread in price units) ──────────────
# Sources: typical retail broker spreads during liquid hours.
# Used as the base spread; actual slippage adds a random component on top.
_DEFAULT_SPREADS: dict[str, float] = {
    "XAUUSD": 0.30,  # Gold: ~$0.30 half-spread
    "XAGUSD": 0.02,
    "XPTUSD": 0.50,
    "EURUSD": 0.00010,  # 1 pip
    "GBPUSD": 0.00012,
    "USDJPY": 0.012,
    "USDCHF": 0.00012,
    "AUDUSD": 0.00012,
    "USDCAD": 0.00015,
    "NZDUSD": 0.00015,
    "EURGBP": 0.00012,
    "EURJPY": 0.015,
    "GBPJPY": 0.020,
    "BTC/USD": 5.0,
    "ETH/USD": 0.50,
    "SOL/USD": 0.05,
    "XRP/USD": 0.0005,
    "SPY": 0.01,
    "QQQ": 0.01,
    "AAPL": 0.01,
    "MSFT": 0.01,
    "TSLA": 0.02,
    "NVDA": 0.02,
    "US30": 2.0,
    "US500": 0.25,
    "NAS100": 1.0,
}
_FALLBACK_SPREAD_PCT = float(os.getenv("PAPER_FALLBACK_SPREAD_PCT", "0.0002"))  # 2 bps


class SlippageModel:
    """
    Realistic fill-price model for paper trading.

    Three components are applied on every fill:
      1. Half-spread  — always paid (bid-ask crossing cost).
      2. Market impact — proportional to order size relative to a notional
                         ADV (average daily volume); larger orders move price more.
      3. Random noise  — Gaussian jitter representing intra-bar price uncertainty.

    All three are directional: buys pay more, sells receive less.

    Models
    ------
    "gaussian"  — Gaussian noise (default, calibrated to retail FX/metals).
    "fixed"     — Fixed fractional slippage (PAPER_FIXED_SLIPPAGE_PCT env).
    "zero"      — No slippage (useful for unit tests only).

    Environment overrides
    ---------------------
    PAPER_SLIPPAGE_MODEL        — "gaussian" | "fixed" | "zero"
    PAPER_FIXED_SLIPPAGE_PCT    — fractional slippage for "fixed" model (default 0.0005)
    PAPER_IMPACT_FACTOR         — market-impact coefficient (default 0.1)
    PAPER_NOISE_SIGMA_PCT       — Gaussian noise std as fraction of price (default 0.0001)
    """

    def __init__(self, model: str = "gaussian", seed: int | None = None) -> None:
        self._model = os.getenv("PAPER_SLIPPAGE_MODEL", model).lower()
        self._fixed_pct = float(os.getenv("PAPER_FIXED_SLIPPAGE_PCT", "0.0005"))
        self._impact_factor = float(os.getenv("PAPER_IMPACT_FACTOR", "0.1"))
        self._noise_sigma_pct = float(os.getenv("PAPER_NOISE_SIGMA_PCT", "0.0001"))
        # Instance-level spread overrides (symbol → half-spread).
        # Populated via set_spread() to avoid mutating the module-level table.
        self._spread_overrides: dict[str, float] = {}
        # seed=None → random (appropriate for live paper trading).
        # Pass an integer seed for deterministic replay or test scenarios.
        self._rng = random.Random(seed)  # nosec B311 - paper trading simulation

    def fill_price(
        self,
        symbol: str,
        mid_price: float,
        side: "OrderSide",
        quantity: float,
        notional_adv: float = 1_000_000.0,
    ) -> float:
        """
        Return the simulated fill price for a market order.

        Parameters
        ----------
        symbol       : Instrument symbol (used for spread lookup).
        mid_price    : Current mid-market price.
        side         : OrderSide.BUY or OrderSide.SELL.
        quantity     : Order size in base units.
        notional_adv : Assumed average daily volume in base units (for impact).

        Returns
        -------
        Simulated fill price (always > 0).
        """
        if mid_price <= 0:
            return mid_price

        if self._model == "zero":
            return mid_price

        # Direction: +1 for buys (price goes up), -1 for sells (price goes down)
        direction = 1.0 if str(side).upper() in ("BUY", "ORDERSIDE.BUY", "LONG") else -1.0

        if self._model == "fixed":
            slippage = mid_price * self._fixed_pct * direction
            fill = mid_price + slippage
            logger.debug(
                "SlippageModel[fixed] %s %s qty=%.4f mid=%.5f fill=%.5f slip=%.5f",
                side,
                symbol,
                quantity,
                mid_price,
                fill,
                slippage,
            )
            return max(fill, 1e-8)

        # ── Gaussian model ────────────────────────────────────────────────────
        # 1. Half-spread (always paid): instance overrides take priority.
        half_spread = self._spread_overrides.get(symbol, _DEFAULT_SPREADS.get(symbol, mid_price * _FALLBACK_SPREAD_PCT))
        spread_cost = half_spread * direction

        # 2. Market impact: sqrt-law approximation
        #    impact = factor * mid * sqrt(qty / adv)
        impact = self._impact_factor * mid_price * math.sqrt(max(quantity, 0.0) / max(notional_adv, 1.0)) * direction

        # 3. Gaussian noise
        noise = self._rng.gauss(0.0, mid_price * self._noise_sigma_pct)

        slippage = spread_cost + impact + noise
        fill = mid_price + slippage

        logger.debug(
            "SlippageModel[gaussian] %s %s qty=%.4f mid=%.5f spread=%.5f impact=%.5f noise=%.5f fill=%.5f",
            side,
            symbol,
            quantity,
            mid_price,
            spread_cost,
            impact,
            noise,
            fill,
        )
        return max(fill, 1e-8)


class PaperTradingBroker(BrokerConnector):
    """
    Paper trading broker for testing.

    Simulates order execution and position management
    without connecting to real exchanges.
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        session_factory=None,
        user_id: str = "paper",
        initial_balance: float | None = None,
        commission_per_lot: float | None = None,
        slippage_model: str = "gaussian",
        seed: int | None = None,
    ):
        """
        Initialize paper trading broker.

        Accepts either a config dict or keyword arguments directly.

        Parameters
        ----------
        seed : int | None
            RNG seed for the slippage model.  None (default) uses a random
            seed — appropriate for live paper trading where realistic variance
            is desired.  Pass an integer for deterministic replay or tests.
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
        self._slippage = SlippageModel(model=config.get("slippage_model", slippage_model), seed=seed)
        # Commission per standard lot (100 000 units).  Charged on open AND close.
        # Default 0.0 so existing callers that don't pass commission_per_lot are unaffected.
        self._commission_per_lot: float = float(config.get("commission_per_lot", 0.0))
        self._standard_lot_units: float = 100_000.0  # 1 standard lot = 100 000 units

        self.orders: dict[str, Order] = {}
        self.positions: dict[str, Position] = {}

        # ── Redis state persistence ───────────────────────────────────────────
        # Orders and positions are persisted to Redis so they survive process
        # restarts.  Without this, a restart (deploy, crash, OOM) silently
        # loses all open paper positions, making P&L tracking unreliable.
        self._redis_state = None
        self._init_redis_state()

        # Equity history: deque of (unix_timestamp, equity_value) tuples.
        # Bounded at 10 000 points (~2.7 hours at 1-second resolution or
        # ~7 months at 30-minute snapshots).  Seeded with the initial balance
        # so the equity curve always has at least one data point.
        self._equity_history: deque = deque(maxlen=10_000)
        self._equity_history.append((time.time(), self.initial_balance))

        # Tracks when each symbol's price was last updated by a LIVE feed.
        # Symbols absent from this dict are using hardcoded fallback prices.
        self._price_timestamps: dict[str, float] = {}
        self._price_stale_secs = float(os.getenv("PAPER_PRICE_STALE_SECONDS", "120"))
        # When True, raise StalePriceError instead of filling at a stale/fallback price.
        # Default False to preserve offline demo / backtest behaviour.
        self._raise_on_stale: bool = os.getenv("PAPER_RAISE_ON_STALE", "false").lower() in ("1", "true", "yes")

        # Optional price feed / engine — set via set_price_feed().
        # Queried in place_order() to refresh prices before filling.
        self._price_feed = None

        # Simulated market prices - Multi-asset support
        # Last updated: 2025-Q2. These are fallback prices used only when
        # no live feed is available. Update periodically or wire a live feed.
        self.market_prices = {
            # Precious Metals
            "XAUUSD": 3300.0,  # Gold (~Mar 2025)
            "XAGUSD": 33.50,  # Silver
            "XPTUSD": 980.0,  # Platinum
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
            "US30": 41500.0,  # Dow Jones
            "US500": 5600.0,  # S&P 500
            "NAS100": 19500.0,  # Nasdaq 100
        }

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *args):
        await self.disconnect()

    def _init_redis_state(self) -> None:
        """Initialise Redis state persistence (best-effort, non-fatal on failure)."""
        try:
            import os as _os

            import redis as _redis_lib

            from execution.redis_state import RedisStateStore

            redis_url = _os.getenv("REDIS_URL", "").strip()
            # Track whether the operator explicitly configured Redis so we can
            # choose the right log level on failure.
            _explicitly_configured = bool(redis_url)

            if not redis_url:
                # No REDIS_URL set — use the dev default but don't warn;
                # Redis being absent in dev is expected and non-actionable.
                redis_url = "redis://localhost:6379/0"

            password = _os.getenv("REDIS_PASSWORD", "") or None

            # Inject REDIS_PASSWORD when not already embedded in the URL.
            if password and "@" not in redis_url.split("://", 1)[-1]:
                scheme, rest = redis_url.split("://", 1)
                redis_url = f"{scheme}://:{password}@{rest}"

            r = _redis_lib.from_url(
                redis_url,
                decode_responses=False,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
            r.ping()
            self._redis_state = RedisStateStore(r)
            logger.info("PaperTradingBroker: Redis state persistence connected")
        except Exception as exc:
            self._redis_state = None
            import os as _os
            _explicitly_configured = bool(_os.getenv("REDIS_URL", "").strip())
            if _explicitly_configured:
                # REDIS_URL was set but Redis is unreachable — operator needs to know.
                logger.warning(
                    "PaperTradingBroker: Redis unavailable (%s) — position/order state will NOT "
                    "survive process restarts. Check REDIS_URL and ensure Redis is running.",
                    exc,
                )
            else:
                # No REDIS_URL configured — in-memory only mode, expected in dev.
                logger.info(
                    "PaperTradingBroker: Redis not configured — position/order state is "
                    "in-memory only and will not survive restarts. Set REDIS_URL to enable persistence."
                )

    async def connect(self) -> bool:
        """Connect to paper trading broker and restore persisted state."""
        self.connected = True
        logger.info("Connected to %s (Paper Trading)", self.name)
        logger.info("Initial balance: $%.2f", self.initial_balance)
        # Restore orders and positions persisted from the previous session.
        if self._redis_state is not None:
            self._restore_state_from_redis()
        return True

    def _restore_state_from_redis(self) -> None:
        """Reload open orders and positions from Redis after a restart."""
        try:
            state = self._redis_state.load_state_on_boot()
            restored_positions = 0
            for pos_dict in state.get("positions", []):
                sym = pos_dict.get("symbol")
                entry = float(pos_dict.get("entry_price", 0))
                current = float(pos_dict.get("current_price", 0))
                qty = float(pos_dict.get("quantity", 0))
                if not sym or entry <= 0 or qty <= 0:
                    logger.warning(
                        "PaperTradingBroker: skipping invalid persisted position "
                        "symbol=%s entry_price=%s qty=%s — position would produce incorrect P&L",
                        sym,
                        entry,
                        qty,
                    )
                    continue
                # Normalise legacy "LONG"/"SHORT" stored values to enum values "BUY"/"SELL"
                _raw_side = pos_dict.get("side", "BUY")
                if isinstance(_raw_side, str):
                    _raw_side = "BUY" if _raw_side.upper() in ("LONG", "BUY") else "SELL"
                self.positions[sym] = Position(
                    id=pos_dict.get("id", str(uuid.uuid4())),
                    symbol=sym,
                    side=OrderSide(_raw_side),
                    quantity=qty,
                    entry_price=entry,
                    current_price=current if current > 0 else entry,
                    unrealized_pnl=float(pos_dict.get("unrealized_pnl", 0)),
                    realized_pnl=float(pos_dict.get("realized_pnl", 0)),
                )
                restored_positions += 1
            if restored_positions:
                logger.info(
                    "PaperTradingBroker: restored %d open position(s) from Redis",
                    restored_positions,
                )
        except Exception as exc:
            logger.warning("PaperTradingBroker: state restore from Redis failed: %s", exc)

    async def disconnect(self) -> bool:
        """Disconnect from paper trading broker."""
        self.connected = False
        logger.info("Disconnected from %s", self.name)
        return True

    def set_spread(self, spread: float, symbol: str | None = None) -> None:
        """
        Update the current spread used by the slippage model.

        Parameters
        ----------
        spread : Full bid-ask spread in price units.
        symbol : If provided, update the spread for this symbol only.
                 If None, update the fallback ``_current_spread`` attribute
                 used when the symbol has no entry in the spread table.
        """
        if symbol is not None:
            # Store in instance-level dict to avoid mutating module-level state
            self._slippage._spread_overrides[symbol] = spread / 2.0  # table stores half-spread
            logger.debug("PaperTrading: spread updated for %s → %.5f", symbol, spread)
        else:
            self._current_spread = spread
            logger.debug("PaperTrading: default spread updated → %.5f", spread)

    def place_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        price: float | None = None,
        stop_price: float | None = None,
        stop_loss: float | None = None,
        take_profit: float | None = None,
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

        # Get current market price — try price feed first for freshest data.
        # When the feed provides real bid/ask we store them so the fill can
        # use the correct side of the spread (buy at ask, sell at bid).
        _sym_upper = symbol.upper()
        current_price = (
            self.market_prices.get(symbol)
            or self.market_prices.get(_sym_upper)
            or self.market_prices.get(symbol.lower())
            or 0.0
        )
        # Real bid/ask from the live feed — None means use SlippageModel spread table.
        _live_bid: float | None = None
        _live_ask: float | None = None

        if self._price_feed is not None:
            try:
                broker_sym = symbol.replace("/", "")
                tick = (
                    self._price_feed.get_last_price(broker_sym)
                    or self._price_feed.get_last_price(symbol)
                )
                if tick is not None:
                    tick_bid = float(getattr(tick, "bid", 0) or 0)
                    tick_ask = float(getattr(tick, "ask", 0) or 0)
                    tick_mid = getattr(tick, "mid", None)
                    if tick_mid is None and tick_bid > 0 and tick_ask > 0:
                        tick_mid = (tick_bid + tick_ask) / 2.0
                    tick_mid = float(tick_mid or 0)
                    if tick_mid > 0:
                        self.update_market_price(symbol, tick_mid)
                        current_price = tick_mid
                    # Preserve real bid/ask for directional fill pricing
                    if tick_bid > 0 and tick_ask > 0:
                        _live_bid = tick_bid
                        _live_ask = tick_ask
            except Exception as _exc:
                logger.debug("price_feed lookup failed for %s: %s", symbol, _exc)

        if current_price == 0.0:
            # No price available from feed or market_prices table — cannot fill.
            # Raise unconditionally: filling at an invented price produces
            # meaningless P&L regardless of PAPER_RAISE_ON_STALE setting.
            raise StalePriceError(
                f"No price available for {symbol}: live feed not connected and "
                "symbol not in market_prices table. Connect a price feed or add "
                "the symbol to the market_prices dict before placing orders."
            )

        # Staleness guard — check whether the price came from a live feed tick.
        last_update = self._price_timestamps.get(symbol)
        if last_update is not None:
            age = time.time() - last_update
            if self._price_stale_secs > 0 and age > self._price_stale_secs:
                msg = (
                    f"Price feed stale for {symbol}: last live update {age:.0f}s ago "
                    f"(threshold={self._price_stale_secs:.0f}s). "
                    f"Last known price={current_price:.5f}."
                )
                if self._raise_on_stale:
                    raise StalePriceError(msg + " Set PAPER_RAISE_ON_STALE=false to warn-and-fill instead.")
                logger.warning(
                    "%s Filling at stale price — reconnect feed for accurate fills.", msg
                )
        else:
            # Price came from the hardcoded market_prices table, not a live feed.
            msg = (
                f"ORDER on {symbol} using hardcoded fallback price {current_price:.5f} "
                "— no live feed tick received for this symbol."
            )
            if self._raise_on_stale:
                raise StalePriceError(
                    msg + " Connect a live price feed or set PAPER_RAISE_ON_STALE=false "
                    "to allow fills at hardcoded prices (offline/demo mode only)."
                )
            logger.warning(
                "%s Set PAPER_PRICE_STALE_SECONDS=0 to suppress in offline demo mode.", msg
            )

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
            timestamp=datetime.now(UTC),
        )

        # Process order
        if order_type == OrderType.MARKET:
            # Directional fill pricing:
            #   BUY  → start from ask (buyer crosses the spread)
            #   SELL → start from bid (seller crosses the spread)
            # When real bid/ask are available from the live feed, use them
            # directly as the reference price so the spread is not double-counted
            # (SlippageModel would otherwise add a synthetic spread on top of mid).
            # When only mid is available, fall back to SlippageModel which adds
            # the spread from its internal table.
            _is_buy = str(side).upper() in ("BUY", "ORDERSIDE.BUY", "LONG")
            if _live_bid is not None and _live_ask is not None:
                # Use real spread: buy fills at ask + impact + noise,
                # sell fills at bid - impact - noise.
                _ref_price = _live_ask if _is_buy else _live_bid
                fill_price = self._slippage.fill_price(
                    symbol=symbol,
                    mid_price=_ref_price,   # reference is already the correct side
                    side=side,
                    quantity=quantity,
                )
                # Override the spread component: SlippageModel will add its
                # table spread on top of _ref_price, which double-counts.
                # Suppress the spread by temporarily zeroing the override,
                # then restore it.  We achieve this by using the "zero" model
                # path only for the spread component — instead, compute impact
                # + noise directly without the spread term.
                # Simpler: use the slippage model with the real-side price as
                # mid and set the symbol's spread override to 0 for this call.
                _saved = self._slippage._spread_overrides.get(symbol)
                self._slippage._spread_overrides[symbol] = 0.0  # spread already in ref price
                fill_price = self._slippage.fill_price(
                    symbol=symbol,
                    mid_price=_ref_price,
                    side=side,
                    quantity=quantity,
                )
                # Restore spread override
                if _saved is None:
                    self._slippage._spread_overrides.pop(symbol, None)
                else:
                    self._slippage._spread_overrides[symbol] = _saved
            else:
                # No live bid/ask — use mid + SlippageModel spread table
                fill_price = self._slippage.fill_price(
                    symbol=symbol,
                    mid_price=current_price,
                    side=side,
                    quantity=quantity,
                )

            order.status = OrderStatus.FILLED
            order.filled_quantity = quantity
            order.average_price = fill_price

            # Deduct opening commission
            commission = self._deduct_commission(quantity)

            # Update position at the slippage-adjusted fill price
            self._update_position(symbol, side, quantity, fill_price,
                                  stop_loss=stop_loss, take_profit=take_profit)

            # Record equity snapshot after every fill
            self._snapshot_equity()

            logger.info(
                "Market order filled: %s %s %s mid=%.5f ref=%.5f fill=%.5f slip=%.5f commission=%.4f",
                side.value,
                quantity,
                symbol,
                current_price,
                _live_ask if _is_buy else (_live_bid if _live_bid else current_price),
                fill_price,
                fill_price - current_price,
                commission,
            )
        else:
            # For limit/stop orders, just mark as open
            order.status = OrderStatus.OPEN
            logger.info("Limit order placed: %s %s %s @ $%s", side.value, quantity, symbol, price)

        self.orders[order_id] = order
        # Persist order to Redis for crash recovery.
        if self._redis_state is not None:
            try:
                self._redis_state.save_order(
                    {
                        "id": order_id,
                        "symbol": symbol,
                        "side": str(side.value),
                        "type": str(order_type.value),
                        "quantity": order.quantity,
                        "price": order.price,
                        "status": str(order.status.value),
                        "filled_price": order.average_price,
                        "timestamp": (
                            order.timestamp.isoformat()
                            if hasattr(order.timestamp, "isoformat")
                            else str(order.timestamp)
                        ),
                    }
                )
            except Exception as _rse:
                logger.warning("PaperTradingBroker: Redis save_order failed: %s", _rse)
        return order

    def _deduct_commission(self, quantity: float) -> float:
        """
        Deduct commission for a fill and return the commission amount charged.

        Commission is proportional to lot size:
            commission = (quantity / standard_lot) * commission_per_lot
        """
        if self._commission_per_lot <= 0:
            return 0.0
        commission = (quantity / self._standard_lot_units) * self._commission_per_lot
        self.balance -= commission
        self.equity = self.balance
        logger.debug(
            "Commission charged: $%.4f (qty=%.0f lots=%.4f rate=%.2f/lot)",
            commission,
            quantity,
            quantity / self._standard_lot_units,
            self._commission_per_lot,
        )
        return commission

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order"""
        if order_id in self.orders:
            order = self.orders[order_id]
            if order.status in [OrderStatus.PENDING, OrderStatus.OPEN]:
                order.status = OrderStatus.CANCELLED
                logger.info("Order cancelled: %s", order_id)

                return True

        logger.warning("Cannot cancel order %s", order_id)

        return False

    def get_order(self, order_id: str) -> Order | None:
        """Get order by ID"""
        return self.orders.get(order_id)

    def _get_positions_sync(self) -> list[Position]:
        """Sync helper used internally."""
        positions = []
        for position in self.positions.values():
            current_price = self.market_prices.get(
                position.symbol,
                position.entry_price,
            )
            if str(position.side).upper() in ("LONG", "ORDERSIDE.BUY", "BUY"):
                unrealized_pnl = (current_price - position.entry_price) * position.quantity
            else:
                unrealized_pnl = (position.entry_price - current_price) * position.quantity
            position.current_price = current_price
            position.unrealized_pnl = unrealized_pnl
            if not hasattr(position, "id") or not position.id:
                position.id = position.symbol
            positions.append(position)
        return positions

    def get_positions(self) -> list[Position]:
        """Get all open positions."""
        return self._get_positions_sync()

    def close_position(self, symbol: str) -> bool:  # pylint: disable=arguments-differ
        """Close a position by symbol or position id."""
        symbol_or_id = symbol
        if symbol_or_id not in self.positions:
            for sym, pos in self.positions.items():
                if getattr(pos, "id", sym) == symbol_or_id:
                    symbol = sym
                    break
            else:
                logger.warning("No open position for %s", symbol_or_id)

                return False
        if symbol not in self.positions:
            return False

        position = self.positions[symbol]
        mid_price = self.market_prices.get(symbol, position.entry_price)

        # Closing a LONG = selling (fills at bid); closing a SHORT = buying (fills at ask).
        close_side = OrderSide.SELL if str(position.side).upper() in ("LONG", "ORDERSIDE.BUY", "BUY") else OrderSide.BUY
        _is_close_buy = close_side == OrderSide.BUY

        # Fetch real bid/ask from price feed if available
        _close_bid: float | None = None
        _close_ask: float | None = None
        if self._price_feed is not None:
            try:
                broker_sym = symbol.replace("/", "")
                tick = (
                    self._price_feed.get_last_price(broker_sym)
                    or self._price_feed.get_last_price(symbol)
                )
                if tick is not None:
                    tb = float(getattr(tick, "bid", 0) or 0)
                    ta = float(getattr(tick, "ask", 0) or 0)
                    if tb > 0 and ta > 0:
                        _close_bid, _close_ask = tb, ta
                        mid_price = (tb + ta) / 2.0
            except Exception as _exc:
                logger.debug("close_position price_feed lookup failed for %s: %s", symbol, _exc)

        if _close_bid is not None and _close_ask is not None:
            # Use real spread: close-buy fills at ask, close-sell fills at bid
            _ref_price = _close_ask if _is_close_buy else _close_bid
            _saved = self._slippage._spread_overrides.get(symbol)
            self._slippage._spread_overrides[symbol] = 0.0  # spread already in ref price
            exit_price = self._slippage.fill_price(
                symbol=symbol,
                mid_price=_ref_price,
                side=close_side,
                quantity=position.quantity,
            )
            if _saved is None:
                self._slippage._spread_overrides.pop(symbol, None)
            else:
                self._slippage._spread_overrides[symbol] = _saved
        else:
            exit_price = self._slippage.fill_price(
                symbol=symbol,
                mid_price=mid_price,
                side=close_side,
                quantity=position.quantity,
            )

        # Calculate gross P&L at slippage-adjusted exit price
        if str(position.side).upper() in ("LONG", "ORDERSIDE.BUY", "BUY"):
            gross_pnl = (exit_price - position.entry_price) * position.quantity
        else:
            gross_pnl = (position.entry_price - exit_price) * position.quantity

        # Apply gross P&L then deduct closing commission
        self.balance += gross_pnl
        self.equity = self.balance
        close_commission = self._deduct_commission(position.quantity)
        net_pnl = gross_pnl - close_commission

        # Persist closed trade to DB (record net P&L)
        self._persist_trade(position, exit_price, net_pnl)

        # Remove position and clean up Redis persistence.
        del self.positions[symbol]
        if self._redis_state is not None:
            try:
                self._redis_state.remove_position(symbol)
            except Exception as _rse:
                logger.warning("PaperTradingBroker: Redis remove_position failed: %s", _rse)

        logger.info(
            "Position closed: %s gross_pnl=$%.2f commission=$%.4f net_pnl=$%.2f balance=$%.2f",
            symbol,
            gross_pnl,
            close_commission,
            net_pnl,
            self.balance,
        )

        # Snapshot equity after close so the equity curve reflects realised P&L
        self._snapshot_equity()

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
                str(position.side).lower().replace("orderside.", "").replace("long", "buy").replace("short", "sell")
            )
            side_enum = OrderSide.BUY if "buy" in raw_side or "long" in raw_side else OrderSide.SELL

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
                entry_time=getattr(position, "entry_time", datetime.now(UTC)),
                exit_time=datetime.now(UTC),
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
            timestamp=datetime.now(UTC),
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

    def get_equity_history(self) -> list[tuple[float, float]]:
        """
        Return the equity curve as a list of (unix_timestamp, equity) tuples.

        Called by api/performance.py _load_equity_curve() to build the
        /api/performance/equity-curve response.  Always returns at least
        the initial balance point recorded at broker startup.
        """
        return list(self._equity_history)

    async def place_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        **kwargs,
    ):
        """Async market order — delegates to sync place_order."""
        from .base import OrderSide as _OS
        from .base import OrderType as _OT

        side_enum = _OS.BUY if str(side).lower() in ("buy", "long") else _OS.SELL
        return self.place_order(
            symbol=symbol,
            side=side_enum,
            order_type=_OT.MARKET,
            quantity=quantity,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )

    async def close_all_positions(self) -> list[str]:
        """Close all open positions. Returns list of successfully closed position IDs."""
        closed: list[str] = []
        for symbol in list(self.positions.keys()):
            try:
                if self.close_position(symbol):
                    closed.append(symbol)
            except Exception as exc:
                logger.warning("Failed to close position %s: %s", symbol, exc)
        return closed

    def get_market_data(
        self,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Get simulated market data for paper trading and testing.

        Returns synthetic OHLCV bars generated from a seed price.
        Raises RuntimeError in production (APP_ENV=production) because
        synthetic bars must never feed the ML predictor in live trading.
        """
        import os as _os

        if _os.getenv("APP_ENV", "development").lower() == "production":
            raise RuntimeError(
                "PaperTradingBroker.get_market_data() must not be called in production. "
                "Use a real market data source (price engine or CSV files)."
            )

        current_price = self.market_prices.get(symbol, 1000.0)

        # Timeframe → seconds mapping for realistic bar timestamps
        _tf_seconds = {
            "1m": 60,
            "5m": 300,
            "15m": 900,
            "30m": 1800,
            "1h": 3600,
            "4h": 14400,
            "1d": 86400,
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
        self._price_timestamps[symbol] = time.time()
        logger.debug("Updated %s price to $%s", symbol, price)

    def _update_position(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        price: float,
        stop_loss: float | None = None,
        take_profit: float | None = None,
    ):
        """Update or create position"""
        position_side = "LONG" if side == OrderSide.BUY else "SHORT"

        if symbol in self.positions:
            # Update existing position
            position = self.positions[symbol]

            # For simplicity, assume same side
            total_quantity = position.quantity + quantity
            if total_quantity <= 0:
                return
            avg_price = (position.entry_price * position.quantity + price * quantity) / total_quantity

            position.quantity = total_quantity
            position.entry_price = avg_price
            # Update SL/TP when explicitly provided
            if stop_loss is not None:
                position.stop_loss = stop_loss
            if take_profit is not None:
                position.take_profit = take_profit
        else:
            # Create new position
            self.positions[symbol] = Position(
                symbol=symbol,
                side=position_side,
                quantity=quantity,
                entry_price=price,
                current_price=price,
                unrealized_pnl=0.0,
                stop_loss=stop_loss,
                take_profit=take_profit,
                timestamp=datetime.now(UTC),
            )

        # Persist updated/new position to Redis for crash recovery.
        if self._redis_state is not None:
            try:
                pos = self.positions[symbol]
                self._redis_state.save_position(
                    {
                        "symbol": symbol,
                        "side": str(pos.side),
                        "quantity": pos.quantity,
                        "entry_price": pos.entry_price,
                        "current_price": pos.current_price,
                        "unrealized_pnl": pos.unrealized_pnl,
                        "realized_pnl": getattr(pos, "realized_pnl", 0.0),
                        "id": getattr(pos, "id", str(uuid.uuid4())),
                    }
                )
            except Exception as _rse:
                logger.warning("PaperTradingBroker: Redis save_position failed: %s", _rse)
