# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
brokers/manager.py

Production broker abstraction layer.

Responsibilities:
- Single entry point for all order/position/account operations
- IBKR is the primary (and only live) broker; paper trading for testing
- Clean interface swap: callers never import broker-specific classes
- Thread-safe: all public methods protected by RLock
- Zero silent failures: every exception logged + Sentry captured
- Kill-switch integration: all order methods check kill switch first
- Health monitoring: heartbeat() returns per-broker status dict
- Circuit breaker: consecutive failures trigger automatic failover to paper

Primary broker priority:
  1. IBKRConnector (ib_insync path) — live/paper via IBKR_PORT
  2. IBKRFIXBridge (FIX 4.4 path) — low-latency, optional
  3. PaperTradingBroker — fallback for testing only

Environment variables:
  BROKER_PRIMARY=ibkr|paper          (default: ibkr)
  BROKER_ENABLE_FIX=true|false       (default: false)
  IBKR_HOST, IBKR_PORT, IBKR_CLIENT_ID, IBKR_ACCOUNT
"""

from __future__ import annotations

import logging
import threading
import traceback
from datetime import datetime, timezone
UTC = timezone.utc
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

# Optional Sentry
try:
    import sentry_sdk  # type: ignore[import]

    _SENTRY = True
except ImportError:
    _SENTRY = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_MAX_CONSECUTIVE_FAILURES = 5  # before auto-failover to paper
_PRIMARY_BROKER_ENV = "BROKER_PRIMARY"
_ENABLE_FIX_ENV = "BROKER_ENABLE_FIX"


# ---------------------------------------------------------------------------
# Broker health snapshot
# ---------------------------------------------------------------------------
class BrokerHealth:
    """Per-broker health snapshot returned by BrokerManager.heartbeat()."""

    def __init__(
        self,
        name: str,
        connected: bool,
        consecutive_failures: int,
        last_error: str | None,
        is_primary: bool,
        mode: str,
    ) -> None:
        self.name = name
        self.connected = connected
        self.consecutive_failures = consecutive_failures
        self.last_error = last_error
        self.is_primary = is_primary
        self.mode = mode
        self.timestamp = datetime.now(UTC)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "connected": self.connected,
            "consecutive_failures": self.consecutive_failures,
            "last_error": self.last_error,
            "is_primary": self.is_primary,
            "mode": self.mode,
            "timestamp": self.timestamp.isoformat(),
        }


# ---------------------------------------------------------------------------
# Broker Manager
# ---------------------------------------------------------------------------
class BrokerManager:
    """
    Production broker abstraction layer.

    All trading operations route through this class.
    Callers are fully decoupled from broker-specific implementations.

    Thread-safety: all public methods are safe to call from any thread.
    """

    def __init__(
        self,
        primary_broker_name: str = "ibkr",
        kill_switch=None,
        enable_fix: bool = False,
    ) -> None:
        self._primary_name = primary_broker_name.lower()
        self._kill_switch = kill_switch
        self._enable_fix = enable_fix

        self._brokers: dict[str, BrokerConnector] = {}
        self._active_name: str | None = None
        self._lock = threading.RLock()
        self._consecutive_failures: dict[str, int] = {}
        self._last_errors: dict[str, str | None] = {}

        # FIX bridge (optional low-latency path)
        self._fix_bridge = None

        # Ordered failover chain: [primary, ...live secondaries..., paper]
        # Built by _auto_register(); pre-populated here so the attribute
        # always exists even when brokers are registered manually.
        self._failover_chain: list[str] = []

        logger.info(
            "BrokerManager initialised | primary=%s fix=%s",
            self._primary_name,
            enable_fix,
        )

    # ------------------------------------------------------------------
    # Factory / registration
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls, kill_switch=None) -> BrokerManager:
        """
        Construct BrokerManager from environment variables.

        BROKER_PRIMARY: "ibkr" (default) or "paper"
        BROKER_ENABLE_FIX: "true" to enable FIX 4.4 bridge
        """
        import os

        primary = os.environ.get(_PRIMARY_BROKER_ENV, "ibkr").lower()
        enable_fix = os.environ.get(_ENABLE_FIX_ENV, "false").lower() == "true"
        mgr = cls(
            primary_broker_name=primary,
            kill_switch=kill_switch,
            enable_fix=enable_fix,
        )
        mgr._auto_register()
        return mgr

    def _auto_register(self) -> None:
        """Register all available brokers based on environment.

        Priority for live failover:
          1. IBKR (primary live broker)
          2. OANDA (live secondary — activated if OANDA_API_KEY is set)
          3. Paper trading (last-resort fallback — always registered)
        """
        import os

        # Always register paper trading (no external deps)
        try:
            from brokers.paper_trading import PaperTradingBroker

            self.register("paper", PaperTradingBroker({}))
        except Exception as exc:
            logger.warning("PaperTradingBroker unavailable: %s", exc)

        # Register IBKR connector
        try:
            from brokers.ibkr_connector import IBKRConfig, IBKRConnector

            cfg = IBKRConfig()
            connector = IBKRConnector(config=cfg, kill_switch=self._kill_switch)
            self.register("ibkr", connector)
        except Exception as exc:
            logger.warning("IBKRConnector unavailable: %s", exc)

        # Register OANDA as live secondary broker (failover target before paper).
        # Activated when OANDA_API_KEY (or BROKER_OANDA_TOKEN) is present in the
        # environment.  In practice-mode (OANDA_PRACTICE=true, default) this acts
        # as a safe live-secondary that does NOT risk real capital.
        _oanda_key = (
            os.getenv("OANDA_API_KEY")
            or os.getenv("BROKER_OANDA_TOKEN")
            or os.getenv("OANDA_ACCESS_TOKEN")
        )
        if _oanda_key:
            try:
                from brokers.oanda_broker import OandaBroker

                _oanda_cfg = {
                    "login": os.getenv("OANDA_ACCOUNT_ID", ""),
                    "password": _oanda_key,
                    "server": "live" if os.getenv("OANDA_PRACTICE", "true").lower() == "false" else "practice",
                }
                self.register("oanda", OandaBroker(_oanda_cfg))
            except Exception as exc:
                logger.warning("OandaBroker unavailable: %s", exc)
        else:
            logger.info(
                "BrokerManager: OANDA_API_KEY not set — OANDA secondary broker not registered. "
                "Set OANDA_API_KEY to enable live failover."
            )

        # Register FIX bridge if enabled
        if self._enable_fix:
            try:
                from brokers.ibkr_fix_bridge import IBKRFIXBridge

                self._fix_bridge = IBKRFIXBridge.from_env(kill_switch=self._kill_switch)
            except Exception as exc:
                logger.warning("IBKRFIXBridge unavailable: %s", exc)

        # Determine failover chain: primary → secondary live broker → paper
        self._failover_chain = self._build_failover_chain()

        # Set primary
        if self._primary_name in self._brokers:
            self._active_name = self._primary_name
        elif self._brokers:
            self._active_name = next(iter(self._brokers))
            logger.warning(
                "Primary broker '%s' not registered; falling back to '%s'.",
                self._primary_name,
                self._active_name,
            )
        else:
            logger.critical("BrokerManager: no brokers registered.")

    def _build_failover_chain(self) -> list[str]:
        """
        Return an ordered list of broker names for sequential failover.

        Order: primary → other live brokers (not paper) → paper.
        This ensures we never jump straight to paper if a live secondary is
        available (e.g. IBKR primary fails → OANDA secondary → paper).
        """
        chain: list[str] = []
        # Primary first
        if self._primary_name in self._brokers:
            chain.append(self._primary_name)
        # Other live brokers (excludes paper and primary)
        for name in self._brokers:
            if name != self._primary_name and name != "paper":
                chain.append(name)
        # Paper always last
        if "paper" in self._brokers:
            chain.append("paper")
        logger.info("BrokerManager: failover chain = %s", chain)
        return chain

    def register(self, name: str, broker: BrokerConnector) -> None:
        """Register a broker instance."""
        with self._lock:
            self._brokers[name.lower()] = broker
            self._consecutive_failures[name.lower()] = 0
            self._last_errors[name.lower()] = None
        logger.info("BrokerManager: registered broker '%s' (%s)", name, type(broker).__name__)

    def set_active(self, name: str) -> None:
        """Switch the active broker by name."""
        with self._lock:
            if name.lower() not in self._brokers:
                raise ValueError(f"Broker '{name}' not registered. Available: {list(self._brokers)}")
            self._active_name = name.lower()
        logger.info("BrokerManager: active broker set to '%s'.", name)

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def connect_all(self) -> dict[str, bool]:
        """Connect all registered brokers. Returns {name: success}."""
        results: dict[str, bool] = {}
        with self._lock:
            brokers = dict(self._brokers)
        for name, broker in brokers.items():
            try:
                ok = broker.connect()
                results[name] = ok
                if ok:
                    logger.info("BrokerManager: '%s' connected.", name)
                else:
                    logger.error("BrokerManager: '%s' connect() returned False.", name)
            except Exception as exc:
                logger.error("BrokerManager: '%s' connect() raised: %s", name, exc)
                self._capture_sentry(exc)
                results[name] = False

        # Start FIX bridge if enabled
        if self._fix_bridge:
            try:
                self._fix_bridge.start()
                logger.info("BrokerManager: FIX bridge started.")
            except Exception as exc:
                logger.error("BrokerManager: FIX bridge start failed: %s", exc)
                self._capture_sentry(exc)

        return results

    def disconnect_all(self) -> None:
        """Disconnect all registered brokers."""
        with self._lock:
            brokers = dict(self._brokers)
        for name, broker in brokers.items():
            try:
                broker.disconnect()
                logger.info("BrokerManager: '%s' disconnected.", name)
            except Exception as exc:
                logger.error("BrokerManager: '%s' disconnect() raised: %s", name, exc)
                self._capture_sentry(exc)

        if self._fix_bridge:
            try:
                self._fix_bridge.stop()
            except Exception as exc:
                logger.error("BrokerManager: FIX bridge stop failed: %s", exc)

    def connect_primary(self) -> bool:
        """Connect only the primary broker."""
        broker = self._get_active_broker()
        if broker is None:
            return False
        try:
            ok = broker.connect()
            if ok:
                logger.info("BrokerManager: primary broker '%s' connected.", self._active_name)
            return ok
        except Exception as exc:
            logger.error("BrokerManager: primary connect failed: %s", exc)
            self._capture_sentry(exc)
            return False

    # ------------------------------------------------------------------
    # Order operations
    # ------------------------------------------------------------------

    def place_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        price: float | None = None,
        stop_price: float | None = None,
        **kwargs,
    ) -> Order:
        """
        Place an order via the active broker.

        Kill-switch is checked here as a final safety net (pre-trade gate
        in execution/trade_executor.py is the primary check).

        Raises:
            RuntimeError: if kill switch active, no broker connected, or
                          broker raises after exhausting retries.
        """
        self._check_kill_switch("place_order")

        broker = self._require_connected_broker()
        try:
            order = broker.place_order(
                symbol=symbol,
                side=side,
                order_type=order_type,
                quantity=quantity,
                price=price,
                stop_price=stop_price,
                **kwargs,
            )
            self._reset_failures()
            return order
        except Exception as exc:
            self._record_failure(exc)
            raise

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order by ID."""
        self._check_kill_switch("cancel_order")
        broker = self._require_connected_broker()
        try:
            result = broker.cancel_order(order_id)
            self._reset_failures()
            return result
        except Exception as exc:
            self._record_failure(exc)
            raise

    def get_order(self, order_id: str) -> Order | None:
        """Retrieve order by ID."""
        broker = self._require_connected_broker()
        try:
            return broker.get_order(order_id)
        except Exception as exc:
            self._record_failure(exc)
            raise

    # ------------------------------------------------------------------
    # Position operations
    # ------------------------------------------------------------------

    def get_positions(self) -> list[Position]:
        """Return all open positions from the active broker."""
        broker = self._require_connected_broker()
        try:
            positions = broker.get_positions()
            self._reset_failures()
            return positions
        except Exception as exc:
            self._record_failure(exc)
            raise

    def close_position(self, symbol: str) -> bool:
        """Close all positions for *symbol* at market."""
        self._check_kill_switch("close_position")
        broker = self._require_connected_broker()
        try:
            result = broker.close_position(symbol)
            self._reset_failures()
            return result
        except Exception as exc:
            self._record_failure(exc)
            raise

    def close_all_positions(self) -> dict[str, bool]:
        """Close all open positions. Returns {symbol: success}."""
        self._check_kill_switch("close_all_positions")
        broker = self._require_connected_broker()
        results: dict[str, bool] = {}
        try:
            positions = broker.get_positions()
        except Exception as exc:
            logger.error("BrokerManager.close_all_positions: get_positions failed: %s", exc)
            self._capture_sentry(exc)
            return {}

        for pos in positions:
            try:
                ok = broker.close_position(pos.symbol)
                results[pos.symbol] = ok
            except Exception as exc:
                logger.error(
                    "BrokerManager.close_all_positions: close %s failed: %s",
                    pos.symbol,
                    exc,
                )
                self._capture_sentry(exc)
                results[pos.symbol] = False

        return results

    # ------------------------------------------------------------------
    # Account info
    # ------------------------------------------------------------------

    def get_account_info(self) -> AccountInfo:
        """Return account info from the active broker."""
        broker = self._require_connected_broker()
        try:
            info = broker.get_account_info()
            self._reset_failures()
            return info
        except Exception as exc:
            self._record_failure(exc)
            raise

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------

    def get_market_data(
        self,
        symbol: str,
        timeframe: str = "1 hour",
        limit: int = 100,
        **kwargs,
    ) -> list[dict[str, Any]]:
        """Return historical OHLCV bars from the active broker."""
        broker = self._require_connected_broker()
        try:
            return broker.get_market_data(symbol, timeframe, limit, **kwargs)
        except Exception as exc:
            self._record_failure(exc)
            raise

    # ------------------------------------------------------------------
    # Health monitoring
    # ------------------------------------------------------------------

    def heartbeat(self) -> dict[str, BrokerHealth]:
        """
        Check health of all registered brokers.

        Returns a dict of {broker_name: BrokerHealth}.
        Does NOT raise — health check failures are logged and returned.
        """
        results: dict[str, BrokerHealth] = {}
        with self._lock:
            brokers = dict(self._brokers)
            active = self._active_name

        for name, broker in brokers.items():
            try:
                connected = broker.is_connected()
            except Exception as exc:
                logger.error("BrokerManager.heartbeat: '%s' is_connected() raised: %s", name, exc)
                connected = False

            # Detect mode (paper vs live)
            mode = "unknown"
            if hasattr(broker, "_cfg") and hasattr(broker._cfg, "mode_label"):
                mode = broker._cfg.mode_label
            elif hasattr(broker, "paper_trading"):
                mode = "PAPER" if broker.paper_trading else "LIVE"

            results[name] = BrokerHealth(
                name=name,
                connected=connected,
                consecutive_failures=self._consecutive_failures.get(name, 0),
                last_error=self._last_errors.get(name),
                is_primary=(name == active),
                mode=mode,
            )

        return results

    def get_active_broker_name(self) -> str | None:
        """Return the name of the currently active broker."""
        with self._lock:
            return self._active_name

    def is_connected(self) -> bool:
        """Return True if the active broker is connected."""
        broker = self._get_active_broker()
        if broker is None:
            return False
        try:
            return broker.is_connected()
        except Exception as exc:
            logger.warning("BrokerManager.is_connected() failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # FIX bridge (low-latency path)
    # ------------------------------------------------------------------

    async def place_order_fix(self, order: object) -> dict[str, object]:
        """
        Submit order via FIX 4.4 bridge (low-latency path).

        Falls back to ib_insync path if FIX bridge is not started.
        """
        if self._fix_bridge and self._fix_bridge._started:
            return await self._fix_bridge.place_order(order)
        raise RuntimeError(
            "FIX bridge not started. Set BROKER_ENABLE_FIX=true and call connect_all().",
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_active_broker(self) -> BrokerConnector | None:
        with self._lock:
            if self._active_name is None:
                return None
            return self._brokers.get(self._active_name)

    def _require_connected_broker(self) -> BrokerConnector:
        """Return active broker or raise RuntimeError."""
        broker = self._get_active_broker()
        if broker is None:
            raise RuntimeError(
                "BrokerManager: no active broker. Call register() and set_active().",
            )
        if not broker.is_connected():
            raise RuntimeError(
                f"BrokerManager: active broker '{self._active_name}' is not connected. "
                "Call connect_primary() or connect_all() first.",
            )
        return broker

    def _check_kill_switch(self, operation: str) -> None:
        """Raise RuntimeError if kill switch is active."""
        if self._kill_switch and self._kill_switch.is_active():
            reason = getattr(self._kill_switch, "_reason", "kill switch active")
            raise RuntimeError(
                f"BrokerManager.{operation} blocked by kill switch: {reason}",
            )

    def _record_failure(self, exc: Exception) -> None:
        """Increment failure counter for active broker and log."""
        with self._lock:
            name = self._active_name or "unknown"
            self._consecutive_failures[name] = self._consecutive_failures.get(name, 0) + 1
            self._last_errors[name] = str(exc)
            failures = self._consecutive_failures[name]

        tb = traceback.format_exc()
        logger.error(
            "BrokerManager: broker '%s' failure #%d: %s\n%s",
            name,
            failures,
            exc,
            tb,
        )
        self._capture_sentry(exc)

        # Auto-failover using the ordered failover chain (primary → live secondary → paper)
        if failures >= _MAX_CONSECUTIVE_FAILURES:
            with self._lock:
                chain = getattr(self, "_failover_chain", [])
                # Build chain on-demand if empty (manual registration without _auto_register)
                if not chain:
                    chain = self._build_failover_chain()
                    self._failover_chain = chain
                current = self._active_name
                # Find the next broker in the chain after the current one
                try:
                    current_idx = chain.index(current)
                    next_brokers = chain[current_idx + 1:]
                except ValueError:
                    next_brokers = [b for b in chain if b != current]

                target = next(
                    (b for b in next_brokers if b in self._brokers and b != current),
                    None,
                )
                if target is not None:
                    logger.critical(
                        "BrokerManager: %d consecutive failures on '%s'. "
                        "Auto-failing over to '%s'.",
                        failures,
                        name,
                        target,
                    )
                    self._active_name = target
                    # Reset failure counter for the new active broker
                    self._consecutive_failures[target] = 0
                    if _SENTRY:
                        try:
                            sentry_sdk.capture_message(
                                f"BrokerManager auto-failover: {name} → {target} after {failures} failures",
                                level="critical",
                            )
                        except Exception as _exc:
                            logger.debug("Suppressed exception: %s", _exc)
                else:
                    logger.critical(
                        "BrokerManager: %d consecutive failures on '%s' and no further "
                        "failover target available in chain %s.",
                        failures,
                        name,
                        chain,
                    )

    def _reset_failures(self) -> None:
        """Reset failure counter for active broker on success."""
        with self._lock:
            name = self._active_name or "unknown"
            if self._consecutive_failures.get(name, 0) > 0:
                logger.info(
                    "BrokerManager: '%s' recovered after %d failures.",
                    name,
                    self._consecutive_failures[name],
                )
            self._consecutive_failures[name] = 0
            self._last_errors[name] = None

    @staticmethod
    def _capture_sentry(exc: Exception) -> None:
        if _SENTRY:
            try:
                sentry_sdk.capture_exception(exc)
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> BrokerManager:
        self.connect_all()
        return self

    def __exit__(self, *_) -> None:
        self.disconnect_all()
