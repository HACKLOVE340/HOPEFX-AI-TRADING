# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
MT5Backup — last-resort price source via a MetaTrader 5 demo account.

Used exclusively by ProductionDataEngine when all REST providers have failed.
The MT5 SDK is optional; if it is not installed the class degrades gracefully
and connect() returns False so the engine skips this provider silently.

Thread safety
-------------
MetaTrader5 calls are synchronous and must not be called from multiple threads
concurrently.  All public methods run the blocking MT5 calls in the default
executor (asyncio.get_event_loop().run_in_executor) so the async event loop
is never blocked.
"""

import asyncio
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# Attempt to import the MT5 SDK once at module load.
try:
    import MetaTrader5 as _mt5  # type: ignore

    _MT5_AVAILABLE = True
except ImportError:
    _mt5 = None  # type: ignore
    _MT5_AVAILABLE = False
    logger.warning(
        "MetaTrader5 SDK not installed — MT5Backup provider will be unavailable. Install with: pip install MetaTrader5"
    )


def _resolve_env(value: Any) -> str:
    """Expand ``${ENV_VAR:default}`` placeholders (mirrors engine.py helper)."""
    if not isinstance(value, str):
        return str(value) if value is not None else ""
    if value.startswith("${") and value.endswith("}"):
        inner = value[2:-1]
        var, _, default = inner.partition(":")
        return os.environ.get(var, default)
    return value


class MT5Backup:
    """
    Async wrapper around the synchronous MetaTrader5 SDK.

    Parameters
    ----------
    config:
        Dict with keys ``login``, ``password``, ``server`` — values may be
        ``${ENV_VAR:default}`` placeholders that are resolved at connect time.
    symbol:
        MT5 symbol to quote (default: ``XAUUSD``).
    """

    def __init__(self, config: dict, symbol: str = "XAUUSD") -> None:
        self._config = config
        self.symbol = symbol
        self.connected: bool = False
        self._loop: asyncio.AbstractEventLoop | None = None

    # ── Public API ────────────────────────────────────────────────────────────

    async def connect(self) -> bool:
        """
        Initialise the MT5 terminal and log in with the configured credentials.

        Returns True on success, False on any failure (SDK missing, bad creds,
        terminal not running, etc.).
        """
        if not _MT5_AVAILABLE:
            logger.error("MT5Backup.connect: MetaTrader5 SDK not installed")
            return False

        self._loop = asyncio.get_event_loop()
        return await self._loop.run_in_executor(None, self._sync_connect)

    async def get_price(self) -> float | None:
        """
        Return the mid-price for ``self.symbol`` or None if unavailable.

        The price is computed as ``(bid + ask) / 2``.
        """
        if not self.connected or not _MT5_AVAILABLE:
            return None
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._sync_get_price)

    async def disconnect(self) -> None:
        """Shut down the MT5 terminal connection."""
        if self.connected and _MT5_AVAILABLE:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, _mt5.shutdown)
            self.connected = False
            logger.info("MT5Backup disconnected")

    # ── Synchronous helpers (run in executor) ─────────────────────────────────

    def _sync_connect(self) -> bool:
        """Blocking MT5 initialise + login.  Called from executor."""
        if not _mt5.initialize():
            error = _mt5.last_error()
            logger.error("MT5 initialize() failed: %s", error)
            return False

        login = _resolve_env(self._config.get("login", ""))
        password = _resolve_env(self._config.get("password", ""))
        server = _resolve_env(self._config.get("server", ""))

        if not login or login in ("your_mt5_demo_login", ""):
            logger.error("MT5Backup: login not configured — set MT5_DEMO_LOGIN env var or update config/data_feed.yaml")
            _mt5.shutdown()
            return False

        try:
            login_int = int(login)
        except ValueError:
            logger.error("MT5Backup: login must be numeric, got: %s", login)
            _mt5.shutdown()
            return False

        success = _mt5.login(login=login_int, password=password, server=server)
        if success:
            self.connected = True
            info = _mt5.account_info()
            logger.info(
                "MT5Backup connected | server=%s | login=%s | balance=%.2f %s",
                server,
                login_int,
                info.balance if info else 0.0,
                info.currency if info else "?",
            )
            return True

        error = _mt5.last_error()
        logger.error("MT5 login failed (login=%s, server=%s): %s", login_int, server, error)
        _mt5.shutdown()
        return False

    def _sync_get_price(self) -> float | None:
        """Blocking tick fetch.  Called from executor."""
        tick = _mt5.symbol_info_tick(self.symbol)
        if tick is None:
            logger.warning("MT5Backup: no tick data for symbol '%s'", self.symbol)
            return None
        mid = (tick.bid + tick.ask) / 2.0
        logger.debug(
            "MT5Backup tick | %s bid=%.5f ask=%.5f mid=%.5f",
            self.symbol,
            tick.bid,
            tick.ask,
            mid,
        )
        return mid

    # ── Diagnostics ───────────────────────────────────────────────────────────

    def status(self) -> dict:
        """Return a health snapshot for monitoring."""
        return {
            "provider": "mt5_demo",
            "connected": self.connected,
            "symbol": self.symbol,
            "sdk_available": _MT5_AVAILABLE,
        }
