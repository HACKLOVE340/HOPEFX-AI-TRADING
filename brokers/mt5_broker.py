# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
MT5Broker — yaml-config-driven MetaTrader 5 broker implementation.

Accepts the same ``login / password / server`` credential shape used in
``config/brokers.yaml`` and wraps the synchronous MetaTrader5 SDK in an
async-friendly interface by running blocking calls in the default executor.

This class is intentionally separate from the existing ``brokers/mt5.py``
(MT5Connector) so that the new yaml-based factory can use it without
touching the legacy connector registry.

Usage
-----
    broker = MT5Broker(config)          # config dict from brokers.yaml
    await broker.connect()
    info = await broker.get_account_info()
    result = await broker.place_order({...})
    await broker.disconnect()
"""

import asyncio
import logging
import os

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as _mt5  # type: ignore

    _MT5_AVAILABLE = True
except ImportError:
    _mt5 = None  # type: ignore
    _MT5_AVAILABLE = False
    logger.warning(
        "MetaTrader5 SDK not installed — MT5Broker will be unavailable. Install with: pip install MetaTrader5"
    )


def _resolve_env(value: object) -> str:
    """Expand ``${ENV_VAR:default}`` placeholders."""
    if not isinstance(value, str):
        return str(value) if value is not None else ""
    if value.startswith("${") and value.endswith("}"):
        inner = value[2:-1]
        var, _, default = inner.partition(":")
        return os.environ.get(var, default)
    return value


# MT5 order type constants (mirrored here so callers don't need to import MT5).
ORDER_TYPE_BUY = 0
ORDER_TYPE_SELL = 1
ORDER_TYPE_BUY_LIMIT = 2
ORDER_TYPE_SELL_LIMIT = 3
ORDER_TYPE_BUY_STOP = 4
ORDER_TYPE_SELL_STOP = 5

# MT5 trade action constants.
TRADE_ACTION_DEAL = 1  # Market order
TRADE_ACTION_PENDING = 5  # Pending order
TRADE_ACTION_SLTP = 6  # Modify SL/TP
TRADE_ACTION_MODIFY = 7  # Modify pending order
TRADE_ACTION_REMOVE = 8  # Delete pending order
TRADE_ACTION_CLOSE_BY = 10  # Close by opposite position


class MT5Broker:
    """
    Async MT5 broker backed by ``config/brokers.yaml`` credentials.

    Parameters
    ----------
    config:
        Dict with keys ``login``, ``password``, ``server``.
        Optional keys: ``terminal_path`` (str), ``timeout_ms`` (int).
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        self.connected: bool = False
        self._login: int | None = None
        self._server: str | None = None

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def connect(self) -> bool:
        """
        Initialise the MT5 terminal and authenticate.

        Returns True on success, False on any failure.
        """
        if not _MT5_AVAILABLE:
            logger.error("MT5Broker.connect: MetaTrader5 SDK not installed")
            return False
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_connect)

    async def disconnect(self) -> None:
        """Shut down the MT5 terminal connection."""
        if self.connected and _MT5_AVAILABLE:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _mt5.shutdown)
            self.connected = False
            logger.info("MT5Broker disconnected (login=%s)", self._login)

    # ── Account ───────────────────────────────────────────────────────────────

    async def get_account_info(self) -> dict | None:
        """Return account details as a plain dict, or None if not connected."""
        if not self._assert_connected("get_account_info"):
            return None
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_account_info)

    async def get_positions(self) -> list[dict]:
        """Return all open positions as a list of dicts."""
        if not self._assert_connected("get_positions"):
            return []
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_positions)

    async def get_orders(self) -> list[dict]:
        """Return all pending orders as a list of dicts."""
        if not self._assert_connected("get_orders"):
            return []
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_orders)

    # ── Order execution ───────────────────────────────────────────────────────

    async def place_order(self, order_params: dict) -> dict:
        """
        Send a trade request to MT5.

        Parameters
        ----------
        order_params:
            Dict with at minimum:
                symbol   (str)   — e.g. "XAUUSD"
                action   (str)   — "buy" | "sell"
                volume   (float) — lot size
            Optional:
                order_type (str) — "market" (default) | "limit" | "stop"
                price      (float) — required for limit/stop orders
                sl         (float) — stop-loss price
                tp         (float) — take-profit price
                comment    (str)  — order comment (max 31 chars)
                magic      (int)  — EA magic number

        Returns
        -------
        Dict with keys: ``success`` (bool), ``order`` (int ticket), ``comment`` (str).
        """
        if not self._assert_connected("place_order"):
            return {"success": False, "order": 0, "comment": "Not connected"}
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_place_order, order_params)

    async def close_position(self, ticket: int, volume: float | None = None) -> dict:
        """
        Close an open position by ticket number.

        Parameters
        ----------
        ticket: Position ticket to close.
        volume: Partial close volume (None = full close).
        """
        if not self._assert_connected("close_position"):
            return {"success": False, "comment": "Not connected"}
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_close_position, ticket, volume)

    async def modify_position(self, ticket: int, sl: float = 0.0, tp: float = 0.0) -> dict:
        """Modify the SL/TP of an open position."""
        if not self._assert_connected("modify_position"):
            return {"success": False, "comment": "Not connected"}
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_modify_position, ticket, sl, tp)

    async def cancel_order(self, ticket: int) -> dict:
        """Delete a pending order by ticket number."""
        if not self._assert_connected("cancel_order"):
            return {"success": False, "comment": "Not connected"}
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_cancel_order, ticket)

    async def cancel_all_orders(self) -> bool:
        """
        Close all open positions and cancel all pending orders.

        Called by the kill switch on activation. Iterates all open
        positions and pending orders, closing/cancelling each one.
        """
        if not self._assert_connected("cancel_all_orders"):
            return False

        all_ok = True

        # 1. Close all open positions
        try:
            positions = await self.get_positions()
            for pos in positions:
                ticket = pos.get("ticket")
                if ticket is None:
                    continue
                try:
                    result = await self.close_position(ticket)
                    if result.get("success"):
                        logger.warning("MT5Broker.cancel_all_orders: closed position ticket=%s", ticket)
                    else:
                        logger.error(
                            "MT5Broker.cancel_all_orders: close ticket=%s failed: %s",
                            ticket, result.get("comment"),
                        )
                        all_ok = False
                except Exception as exc:
                    logger.error("MT5Broker.cancel_all_orders: close ticket=%s raised: %s", ticket, exc)
                    all_ok = False
        except Exception as exc:
            logger.error("MT5Broker.cancel_all_orders: get_positions failed: %s", exc)
            all_ok = False

        # 2. Cancel all pending orders
        try:
            orders = await self.get_orders()
            for order in orders:
                ticket = order.get("ticket")
                if ticket is None:
                    continue
                try:
                    result = await self.cancel_order(ticket)
                    if result.get("success"):
                        logger.warning("MT5Broker.cancel_all_orders: cancelled order ticket=%s", ticket)
                    else:
                        logger.error(
                            "MT5Broker.cancel_all_orders: cancel ticket=%s failed: %s",
                            ticket, result.get("comment"),
                        )
                        all_ok = False
                except Exception as exc:
                    logger.error("MT5Broker.cancel_all_orders: cancel ticket=%s raised: %s", ticket, exc)
                    all_ok = False
        except Exception as exc:
            logger.error("MT5Broker.cancel_all_orders: get_orders failed: %s", exc)
            all_ok = False

        logger.warning("MT5Broker.cancel_all_orders: complete (all_ok=%s)", all_ok)
        return all_ok

    # ── Market data ───────────────────────────────────────────────────────────

    async def get_tick(self, symbol: str) -> dict | None:
        """Return the latest bid/ask tick for *symbol*."""
        if not self._assert_connected("get_tick"):
            return None
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_get_tick, symbol)

    # ── Synchronous helpers (run in executor) ─────────────────────────────────

    def _sync_connect(self) -> bool:
        login_raw = _resolve_env(self._config.get("login", ""))
        password = _resolve_env(self._config.get("password", ""))
        server = _resolve_env(self._config.get("server", ""))
        terminal_path = _resolve_env(self._config.get("terminal_path", ""))
        timeout_ms = int(self._config.get("timeout_ms", 60000))

        if not login_raw or login_raw in ("your_prop_password", "12345678"):
            logger.warning(
                "MT5Broker: login appears to be a placeholder ('%s'). "
                "Set PROP_MT5_LOGIN env var or update config/brokers.yaml.",
                login_raw,
            )

        try:
            login_int = int(login_raw)
        except ValueError:
            logger.error("MT5Broker: login must be numeric, got: '%s'", login_raw)
            return False

        init_kwargs: dict = {"timeout": timeout_ms}
        if terminal_path:
            init_kwargs["path"] = terminal_path

        if not _mt5.initialize(**init_kwargs):
            logger.error("MT5 initialize() failed: %s", _mt5.last_error())
            return False

        success = _mt5.login(login=login_int, password=password, server=server)
        if not success:
            logger.error(
                "MT5 login failed (login=%s, server=%s): %s",
                login_int,
                server,
                _mt5.last_error(),
            )
            _mt5.shutdown()
            return False

        self.connected = True
        self._login = login_int
        self._server = server
        info = _mt5.account_info()
        logger.info(
            "MT5Broker connected | login=%s | server=%s | balance=%.2f %s",
            login_int,
            server,
            info.balance if info else 0.0,
            info.currency if info else "?",
        )
        return True

    def _sync_account_info(self) -> dict | None:
        info = _mt5.account_info()
        if info is None:
            return None
        return {
            "login": info.login,
            "server": info.server,
            "balance": info.balance,
            "equity": info.equity,
            "margin": info.margin,
            "free_margin": info.margin_free,
            "margin_level": info.margin_level,
            "currency": info.currency,
            "leverage": info.leverage,
            "profit": info.profit,
        }

    def _sync_positions(self) -> list[dict]:
        positions = _mt5.positions_get()
        if positions is None:
            return []
        return [
            {
                "ticket": p.ticket,
                "symbol": p.symbol,
                "type": "buy" if p.type == 0 else "sell",
                "volume": p.volume,
                "open_price": p.price_open,
                "current_price": p.price_current,
                "sl": p.sl,
                "tp": p.tp,
                "profit": p.profit,
                "comment": p.comment,
                "magic": p.magic,
                "time": p.time,
            }
            for p in positions
        ]

    def _sync_orders(self) -> list[dict]:
        orders = _mt5.orders_get()
        if orders is None:
            return []
        return [
            {
                "ticket": o.ticket,
                "symbol": o.symbol,
                "type": o.type,
                "volume": o.volume_current,
                "price": o.price_open,
                "sl": o.sl,
                "tp": o.tp,
                "comment": o.comment,
                "magic": o.magic,
                "time_setup": o.time_setup,
            }
            for o in orders
        ]

    def _sync_place_order(self, params: dict) -> dict:
        symbol: str = params.get("symbol", "XAUUSD")
        action_str: str = params.get("action", "buy").lower()
        volume: float = float(params.get("volume", 0.01))
        order_type_str: str = params.get("order_type", "market").lower()
        price: float = float(params.get("price", 0.0))
        sl: float = float(params.get("sl", 0.0))
        tp: float = float(params.get("tp", 0.0))
        comment: str = str(params.get("comment", "HOPEFX"))[:31]
        magic: int = int(params.get("magic", 0))

        # Resolve order type
        if order_type_str == "market":
            trade_action = TRADE_ACTION_DEAL
            tick = _mt5.symbol_info_tick(symbol)
            if tick is None:
                return {
                    "success": False,
                    "order": 0,
                    "comment": f"No tick for {symbol}",
                }
            price = tick.ask if action_str == "buy" else tick.bid
            mt5_order_type = ORDER_TYPE_BUY if action_str == "buy" else ORDER_TYPE_SELL
        elif order_type_str == "limit":
            trade_action = TRADE_ACTION_PENDING
            mt5_order_type = ORDER_TYPE_BUY_LIMIT if action_str == "buy" else ORDER_TYPE_SELL_LIMIT
        elif order_type_str == "stop":
            trade_action = TRADE_ACTION_PENDING
            mt5_order_type = ORDER_TYPE_BUY_STOP if action_str == "buy" else ORDER_TYPE_SELL_STOP
        else:
            return {
                "success": False,
                "order": 0,
                "comment": f"Unknown order_type: {order_type_str}",
            }

        sym_info = _mt5.symbol_info(symbol)
        if sym_info is None:
            return {
                "success": False,
                "order": 0,
                "comment": f"Symbol {symbol} not found",
            }

        request = {
            "action": trade_action,
            "symbol": symbol,
            "volume": volume,
            "type": mt5_order_type,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": 20,
            "magic": magic,
            "comment": comment,
            "type_time": _mt5.ORDER_TIME_GTC if _MT5_AVAILABLE else 0,
            "type_filling": _mt5.ORDER_FILLING_IOC if _MT5_AVAILABLE else 0,
        }

        result = _mt5.order_send(request)
        if result is None:
            return {"success": False, "order": 0, "comment": str(_mt5.last_error())}

        success = result.retcode == _mt5.TRADE_RETCODE_DONE
        if not success:
            logger.warning(
                "MT5 order_send failed | retcode=%s | comment=%s",
                result.retcode,
                result.comment,
            )
        else:
            logger.info(
                "MT5 order placed | ticket=%s | symbol=%s | %s %.2f @ %.5f",
                result.order,
                symbol,
                action_str,
                volume,
                price,
            )
        return {
            "success": success,
            "order": result.order,
            "retcode": result.retcode,
            "comment": result.comment,
        }

    def _sync_close_position(self, ticket: int, volume: float | None) -> dict:
        positions = _mt5.positions_get(ticket=ticket)
        if not positions:
            return {"success": False, "comment": f"Position {ticket} not found"}
        pos = positions[0]
        close_volume = volume if volume is not None else pos.volume
        close_type = ORDER_TYPE_SELL if pos.type == 0 else ORDER_TYPE_BUY
        tick = _mt5.symbol_info_tick(pos.symbol)
        if tick is None:
            return {"success": False, "comment": f"No tick for {pos.symbol}"}
        close_price = tick.bid if pos.type == 0 else tick.ask

        request = {
            "action": TRADE_ACTION_DEAL,
            "symbol": pos.symbol,
            "volume": close_volume,
            "type": close_type,
            "position": ticket,
            "price": close_price,
            "deviation": 20,
            "magic": pos.magic,
            "comment": "HOPEFX close",
            "type_time": _mt5.ORDER_TIME_GTC if _MT5_AVAILABLE else 0,
            "type_filling": _mt5.ORDER_FILLING_IOC if _MT5_AVAILABLE else 0,
        }
        result = _mt5.order_send(request)
        if result is None:
            return {"success": False, "comment": str(_mt5.last_error())}
        success = result.retcode == _mt5.TRADE_RETCODE_DONE
        logger.info("MT5 close position | ticket=%s | success=%s", ticket, success)
        return {
            "success": success,
            "retcode": result.retcode,
            "comment": result.comment,
        }

    def _sync_modify_position(self, ticket: int, sl: float, tp: float) -> dict:
        request = {
            "action": TRADE_ACTION_SLTP,
            "position": ticket,
            "sl": sl,
            "tp": tp,
        }
        result = _mt5.order_send(request)
        if result is None:
            return {"success": False, "comment": str(_mt5.last_error())}
        success = result.retcode == _mt5.TRADE_RETCODE_DONE
        return {
            "success": success,
            "retcode": result.retcode,
            "comment": result.comment,
        }

    def _sync_cancel_order(self, ticket: int) -> dict:
        request = {"action": TRADE_ACTION_REMOVE, "order": ticket}
        result = _mt5.order_send(request)
        if result is None:
            return {"success": False, "comment": str(_mt5.last_error())}
        success = result.retcode == _mt5.TRADE_RETCODE_DONE
        return {
            "success": success,
            "retcode": result.retcode,
            "comment": result.comment,
        }

    def _sync_get_tick(self, symbol: str) -> dict | None:
        tick = _mt5.symbol_info_tick(symbol)
        if tick is None:
            return None
        return {
            "symbol": symbol,
            "bid": tick.bid,
            "ask": tick.ask,
            "mid": (tick.bid + tick.ask) / 2.0,
            "time": tick.time,
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _assert_connected(self, method: str) -> bool:
        if not self.connected:
            logger.error("MT5Broker.%s called before connect()", method)
            return False
        return True

    def status(self) -> dict:
        """Return a health snapshot for monitoring."""
        return {
            "broker": "mt5",
            "connected": self.connected,
            "login": self._login,
            "server": self._server,
            "sdk_available": _MT5_AVAILABLE,
        }
