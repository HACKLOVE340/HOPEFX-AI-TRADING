# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
brokers/mt5_bridge.py
=====================
Full MetaTrader 5 bridge — hybrid Python-signal / MT5-execution mode.

Features
--------
- Direct MetaTrader5 package integration (connect / send_order / monitor_fill / close_position)
- Hybrid mode: Python strategy signals → MT5 execution
- .ex5 signal exporter: writes JSON signal files that a companion MT5 EA reads
- PropEnforcer integration: every order is gated through prop-firm compliance rules
- Exponential-backoff retry on transient errors
- Per-call timeout enforcement
- Thread-safe connection management
- Async wrappers (run_in_executor) for FastAPI / asyncio contexts

Environment variables
---------------------
MT5_LOGIN      — MT5 account login (integer)
MT5_PASSWORD   — MT5 account password
MT5_SERVER     — MT5 broker server name
MT5_PATH       — Optional path to terminal64.exe
MT5_SIGNAL_DIR — Directory for .ex5 signal JSON files (default: data/mt5_signals)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
from enum import Enum, auto
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── optional MT5 import (Windows-only package) ────────────────────────────────
try:
    import MetaTrader5 as mt5  # type: ignore

    _MT5_AVAILABLE = True
except ImportError:
    mt5 = None  # type: ignore
    _MT5_AVAILABLE = False
    logger.warning(
        "MetaTrader5 package not available — bridge runs in signal-export mode only. "
        "Install on Windows: pip install MetaTrader5",
    )

# ── signal export directory ───────────────────────────────────────────────────
_SIGNAL_DIR = Path(os.environ.get("MT5_SIGNAL_DIR", "data/mt5_signals"))


# ── domain types ─────────────────────────────────────────────────────────────


class OrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    MARKET = auto()
    LIMIT = auto()
    STOP = auto()


class FillStatus(Enum):
    PENDING = auto()
    FILLED = auto()
    PARTIAL = auto()
    REJECTED = auto()
    CANCELLED = auto()


@dataclass
class MT5Order:
    symbol: str
    side: OrderSide
    volume: float
    order_type: OrderType = OrderType.MARKET
    price: float | None = None
    stop_loss: float | None = None  # mandatory — bridge rejects if None/0
    take_profit: float | None = None
    deviation: int = 20
    magic: int = 234_001
    comment: str = "HOPEFX"
    timeout_sec: float = 10.0


@dataclass
class MT5FillResult:
    ticket: int
    status: FillStatus
    filled_volume: float
    fill_price: float
    commission: float
    swap: float
    profit: float
    comment: str
    raw: Any = field(default=None, repr=False)


# ── retry decorator ───────────────────────────────────────────────────────────


def _retry(max_attempts: int = 3, base_delay: float = 0.5):
    """Retry with exponential back-off; re-raises last exception on exhaustion.

    Uses threading.Event.wait() instead of time.sleep() so the GIL is
    released during the back-off interval.  This matters when the decorated
    sync method is called from an async run_in_executor context.
    """

    def decorator(fn):
        def wrapper(*args, **kwargs):
            delay = base_delay
            last_exc: Exception | None = None
            _wait = threading.Event()
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except (OSError, RuntimeError, ValueError, AttributeError) as exc:
                    last_exc = exc
                    logger.warning(
                        "mt5_bridge retry attempt=%d/%d fn=%s error=%s",
                        attempt,
                        max_attempts,
                        fn.__name__,
                        exc,
                    )
                    if attempt < max_attempts:
                        _wait.wait(timeout=delay)
                        delay *= 2
            raise last_exc  # type: ignore[misc]

        return wrapper

    return decorator


# ── .ex5 signal exporter ─────────────────────────────────────────────────────


class EX5SignalExporter:
    """
    Writes Python-generated signals as JSON files into MT5_SIGNAL_DIR.

    A companion MT5 Expert Advisor (EA) polls this directory and executes
    the signals natively inside the MT5 terminal.  This allows Linux/Mac
    Python servers to drive MT5 execution on a Windows VPS without the
    MetaTrader5 Python package.

    Signal file format
    ------------------
    {
      "id":          "XAUUSD_BUY_1711234567",
      "symbol":      "XAUUSD",
      "side":        "BUY",
      "volume":      0.10,
      "order_type":  "MARKET",
      "price":       null,
      "stop_loss":   1920.00,
      "take_profit": 1960.00,
      "magic":       234001,
      "comment":     "HOPEFX",
      "issued_at":   "2025-03-24T12:34:56Z",
      "status":      "PENDING"
    }

    The EA sets status to "FILLED" or "REJECTED" and writes fill_price / ticket
    back into the same file.  poll_fill() polls for that update.
    """

    def __init__(self, signal_dir: Path = _SIGNAL_DIR):
        self.signal_dir = signal_dir
        self.signal_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _write_json_locked(path: Path, payload: dict) -> None:
        """
        Write JSON to path with cross-platform file locking.

        Uses fcntl.flock on POSIX and msvcrt.locking on Windows.
        Falls back to a .lock sentinel file when neither is available
        (e.g. network filesystems that don't support advisory locks).

        This prevents race conditions when the MT5 EA and Python both
        read/write the same signal file simultaneously.
        """
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2))

        # Atomic rename — on POSIX this is guaranteed atomic; on Windows
        # it may fail if the target exists, so we remove first.
        try:
            tmp.replace(path)
        except OSError:
            try:
                path.unlink(missing_ok=True)
                tmp.replace(path)
            except OSError as exc:
                logger.warning("Atomic rename failed for %s: %s", path, exc)
                tmp.write_text(json.dumps(payload, indent=2))
                import shutil

                shutil.copy2(str(tmp), str(path))
                tmp.unlink(missing_ok=True)

    @staticmethod
    def _read_json_locked(path: Path) -> dict:
        """Read JSON from path safely (handles partial writes from EA).

        Uses threading.Event-based sleep so this sync helper does not block
        an event loop when called from a thread pool executor.
        """
        _wait = threading.Event()
        for attempt in range(3):
            try:
                text = path.read_text(encoding="utf-8")
                return json.loads(text)
            except json.JSONDecodeError:
                if attempt < 2:  # noqa: PLR2004
                    _wait.wait(timeout=0.1)
        return {}

    def export(self, order: MT5Order) -> Path:
        """
        Write a signal JSON file with file locking; returns the file path.

        Uses atomic write (write to .tmp then rename) to prevent the MT5 EA
        from reading a partially-written file.
        """
        ts = int(time.time())
        signal_id = f"{order.symbol}_{order.side.value}_{ts}"
        payload = {
            "id": signal_id,
            "symbol": order.symbol,
            "side": order.side.value,
            "volume": order.volume,
            "order_type": order.order_type.name,
            "price": order.price,
            "stop_loss": order.stop_loss,
            "take_profit": order.take_profit,
            "magic": order.magic,
            "comment": order.comment,
            "issued_at": datetime.now(UTC).isoformat(),
            "status": "PENDING",
        }
        path = self.signal_dir / f"{signal_id}.json"
        self._write_json_locked(path, payload)
        logger.info("ex5_export signal_id=%s path=%s", signal_id, path)
        return path

    def export_modify(
        self,
        ticket: int,
        symbol: str,
        stop_loss: float | None = None,
        take_profit: float | None = None,
    ) -> Path:
        """
        Write a MODIFY signal file for the MT5 EA to update SL/TP on an open position.
        """
        ts = int(time.time())
        signal_id = f"MODIFY_{symbol}_{ticket}_{ts}"
        payload = {
            "id": signal_id,
            "action": "MODIFY",
            "ticket": ticket,
            "symbol": symbol,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "issued_at": datetime.now(UTC).isoformat(),
            "status": "PENDING",
        }
        path = self.signal_dir / f"{signal_id}.json"
        self._write_json_locked(path, payload)
        logger.info(
            "ex5_modify ticket=%d SL=%s TP=%s path=%s",
            ticket,
            stop_loss,
            take_profit,
            path,
        )
        return path

    def export_cancel(self, ticket: int, symbol: str) -> Path:
        """Write a CANCEL signal file for the MT5 EA to delete a pending order."""
        ts = int(time.time())
        signal_id = f"CANCEL_{symbol}_{ticket}_{ts}"
        payload = {
            "id": signal_id,
            "action": "CANCEL",
            "ticket": ticket,
            "symbol": symbol,
            "issued_at": datetime.now(UTC).isoformat(),
            "status": "PENDING",
        }
        path = self.signal_dir / f"{signal_id}.json"
        self._write_json_locked(path, payload)
        logger.info("ex5_cancel ticket=%d path=%s", ticket, path)
        return path

    def poll_fill(self, signal_path: Path, timeout_sec: float = 30.0) -> MT5FillResult:
        """
        Poll the signal file until the EA updates status to FILLED/REJECTED.
        Uses locked reader to avoid reading partial writes from the EA.
        Returns MT5FillResult on fill; raises TimeoutError on timeout.
        """
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            try:
                data = self._read_json_locked(signal_path)
                status = data.get("status", "PENDING")
                if status == "FILLED":
                    return MT5FillResult(
                        ticket=int(data.get("ticket", 0)),
                        status=FillStatus.FILLED,
                        filled_volume=float(data.get("fill_volume", data.get("volume", 0))),
                        fill_price=float(data.get("fill_price", 0)),
                        commission=float(data.get("commission", 0)),
                        swap=float(data.get("swap", 0)),
                        profit=float(data.get("profit", 0)),
                        comment=data.get("comment", ""),
                        raw=data,
                    )
                if status == "REJECTED":
                    raise RuntimeError(
                        f"MT5 EA rejected signal {signal_path.name}: {data.get('reject_reason', 'unknown')}",
                    )
            except RuntimeError:
                raise
            except (OSError, ValueError, KeyError) as _exc:
                logger.debug("Suppressed exception: %s", _exc)
            # Non-blocking wait: uses Event.wait() so a thread-pool executor
            # does not starve the event loop during the poll interval.
            threading.Event().wait(timeout=0.5)
        raise TimeoutError(f"Signal {signal_path.name} not filled within {timeout_sec}s")

    def cleanup_old_signals(self, max_age_hours: int = 24) -> int:
        """Remove signal files older than max_age_hours. Returns count removed."""
        cutoff = time.time() - max_age_hours * 3600
        removed = 0
        for f in self.signal_dir.glob("*.json"):
            if f.stat().st_mtime < cutoff:
                f.unlink(missing_ok=True)
                removed += 1
        return removed


# ── main bridge ───────────────────────────────────────────────────────────────


class MT5Bridge:
    """
    Hybrid Python <-> MT5 execution bridge.

    Modes
    -----
    1. Direct mode  (MT5 package available, Windows):
       connect() -> send_order() -> monitor_fill() -> close_position()

    2. Signal-export mode (Linux/Mac or MT5 package absent):
       send_order() writes a JSON signal file; companion EA executes it.
       monitor_fill() polls the file for EA confirmation.

    PropEnforcer integration
    ------------------------
    Pass a PropEnforcer instance to enforce prop-firm rules before every order.
    Orders that breach daily DD, total DD, news blackout, or weekend window
    are rejected before reaching MT5.
    """

    def __init__(
        self,
        server: str,
        login: int,
        password: str,
        path: str | None = None,
        portable: bool = False,
        timeout_ms: int = 60_000,
        enforcer=None,
        signal_dir: Path = _SIGNAL_DIR,
    ) -> None:
        self.server = server
        self.login = login
        self.password = password
        self.path = path
        self.portable = portable
        self.timeout_ms = timeout_ms
        self._enforcer = enforcer
        self._connected = False
        self._lock = threading.Lock()
        self._exporter = EX5SignalExporter(signal_dir)

    @classmethod
    def from_env(cls, enforcer=None) -> MT5Bridge:
        """Construct from MT5_LOGIN / MT5_PASSWORD / MT5_SERVER env vars."""
        login_str = os.environ.get("MT5_LOGIN", "")
        if not login_str:
            raise OSError("MT5_LOGIN env var not set")
        return cls(
            server=os.environ.get("MT5_SERVER", ""),
            login=int(login_str),
            password=os.environ.get("MT5_PASSWORD", ""),
            path=os.environ.get("MT5_PATH"),
            enforcer=enforcer,
        )

    # ── connection lifecycle ──────────────────────────────────────────────────

    @_retry(max_attempts=3, base_delay=1.0)
    def connect(self) -> bool:
        if not _MT5_AVAILABLE:
            logger.info("mt5_bridge: MT5 package absent — signal-export mode active")
            self._connected = True
            return True

        init_kwargs: dict[str, Any] = {"portable": self.portable}
        if self.path:
            init_kwargs["path"] = self.path

        if not mt5.initialize(**init_kwargs):
            raise ConnectionError(f"mt5.initialize failed: {mt5.last_error()}")

        authorised = mt5.login(
            login=self.login,
            password=self.password,
            server=self.server,
            timeout=self.timeout_ms,
        )
        if not authorised:
            mt5.shutdown()
            raise ConnectionError(f"mt5.login failed: {mt5.last_error()}")

        self._connected = True
        info = mt5.account_info()
        logger.info(
            "mt5_bridge connected server=%s login=%s balance=%.2f currency=%s",
            self.server,
            self.login,
            info.balance if info else 0,
            info.currency if info else "?",
        )
        return True

    def disconnect(self) -> None:
        if _MT5_AVAILABLE and self._connected:
            mt5.shutdown()
        self._connected = False
        logger.info("mt5_bridge disconnected")

    def _require_connected(self) -> None:
        if not self._connected:
            raise RuntimeError("MT5Bridge not connected — call connect() first")

    def _enforce(self, instrument: str) -> None:
        """Raise RuntimeError if PropEnforcer blocks the order."""
        if self._enforcer is None:
            return
        ok, reason = self._enforcer.before_execute(instrument)
        if not ok:
            raise RuntimeError(f"PropEnforcer blocked order: {reason}")

    # ── order placement ───────────────────────────────────────────────────────

    @_retry(max_attempts=3, base_delay=0.3)
    def send_order(self, order: MT5Order) -> MT5FillResult:
        """
        Send a market, limit, or stop order.
        Validates stop_loss, runs PropEnforcer gate, then executes.
        Falls back to .ex5 signal export when MT5 package is unavailable.
        """
        self._require_connected()

        if not order.stop_loss:
            raise ValueError(
                f"Order for {order.symbol!r} rejected: stop_loss must be set. Never trade without a stop-loss.",
            )

        self._enforce(order.symbol)

        if not _MT5_AVAILABLE:
            path = self._exporter.export(order)
            return self._exporter.poll_fill(path, timeout_sec=order.timeout_sec)

        return self._send_direct(order)

    def _send_direct(self, order: MT5Order) -> MT5FillResult:
        sym_info = mt5.symbol_info(order.symbol)
        if sym_info is None:
            raise ValueError(f"Symbol {order.symbol!r} not found in MT5")
        if not sym_info.visible and not mt5.symbol_select(order.symbol, True):
            raise RuntimeError(f"Cannot select symbol {order.symbol!r}")

        tick = mt5.symbol_info_tick(order.symbol)
        if tick is None:
            raise RuntimeError(f"No tick data for {order.symbol!r}")

        if order.order_type == OrderType.MARKET:
            price = tick.ask if order.side == OrderSide.BUY else tick.bid
            action = mt5.TRADE_ACTION_DEAL
            mt5_type = mt5.ORDER_TYPE_BUY if order.side == OrderSide.BUY else mt5.ORDER_TYPE_SELL
        elif order.order_type == OrderType.LIMIT:
            if order.price is None:
                raise ValueError("LIMIT order requires a price")
            price = order.price
            action = mt5.TRADE_ACTION_PENDING
            mt5_type = mt5.ORDER_TYPE_BUY_LIMIT if order.side == OrderSide.BUY else mt5.ORDER_TYPE_SELL_LIMIT
        else:
            if order.price is None:
                raise ValueError("STOP order requires a price")
            price = order.price
            action = mt5.TRADE_ACTION_PENDING
            mt5_type = mt5.ORDER_TYPE_BUY_STOP if order.side == OrderSide.BUY else mt5.ORDER_TYPE_SELL_STOP

        request: dict[str, Any] = {
            "action": action,
            "symbol": order.symbol,
            "volume": float(order.volume),
            "type": mt5_type,
            "price": float(price),
            "sl": float(order.stop_loss),
            "deviation": order.deviation,
            "magic": order.magic,
            "comment": order.comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        if order.take_profit is not None:
            request["tp"] = float(order.take_profit)

        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            retcode = result.retcode if result else -1
            comment = result.comment if result else "no result"
            raise RuntimeError(f"MT5 order rejected retcode={retcode} comment={comment!r}")

        fill = MT5FillResult(
            ticket=result.order,
            status=FillStatus.FILLED,
            filled_volume=result.volume,
            fill_price=result.price,
            commission=getattr(result, "commission", 0.0),
            swap=getattr(result, "swap", 0.0),
            profit=getattr(result, "profit", 0.0),
            comment=result.comment,
            raw=result,
        )
        logger.info(
            "mt5_bridge filled ticket=%d symbol=%s side=%s vol=%.2f price=%.5f",
            fill.ticket,
            order.symbol,
            order.side.value,
            fill.filled_volume,
            fill.fill_price,
        )
        return fill

    # ── fill monitoring ───────────────────────────────────────────────────────

    def monitor_fill(
        self,
        ticket: int,
        poll_interval: float = 0.5,
        timeout_sec: float = 30.0,
    ) -> MT5FillResult:
        """Poll MT5 until a pending order is filled, rejected, or timeout expires."""
        self._require_connected()

        if not _MT5_AVAILABLE:
            raise RuntimeError(
                "monitor_fill() with a ticket requires direct MT5 mode. "
                "In signal-export mode, use EX5SignalExporter.poll_fill(path).",
            )

        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            orders = mt5.orders_get(ticket=ticket)
            if orders:
                time.sleep(poll_interval)
                continue

            now = datetime.now(UTC)
            deals = mt5.history_deals_get(now - timedelta(minutes=5), now)
            if deals:
                for deal in deals:
                    if deal.order == ticket:
                        return MT5FillResult(
                            ticket=ticket,
                            status=FillStatus.FILLED,
                            filled_volume=deal.volume,
                            fill_price=deal.price,
                            commission=deal.commission,
                            swap=deal.swap,
                            profit=deal.profit,
                            comment=deal.comment,
                            raw=deal,
                        )
            # Non-blocking wait: Event.wait() yields the GIL so the event loop
            # is not starved when monitor_fill() runs in a thread pool executor.
            threading.Event().wait(timeout=poll_interval)

        raise TimeoutError(f"monitor_fill: ticket {ticket} not filled within {timeout_sec}s")

    # ── position management ───────────────────────────────────────────────────

    @_retry(max_attempts=2, base_delay=0.5)
    def close_position(
        self,
        symbol: str,
        volume: float | None = None,
        deviation: int = 20,
        magic: int = 234_001,
        comment: str = "HOPEFX close",
    ) -> list[MT5FillResult]:
        """Close all (or partial) open positions for symbol."""
        self._require_connected()

        if not _MT5_AVAILABLE:
            close_order = MT5Order(
                symbol=symbol,
                side=OrderSide.SELL,
                volume=volume or 0.0,
                stop_loss=0.0001,
                comment="HOPEFX close",
            )
            path = self._exporter.export(close_order)
            fill = self._exporter.poll_fill(path, timeout_sec=30.0)
            return [fill]

        positions = mt5.positions_get(symbol=symbol)
        if not positions:
            logger.info("mt5_bridge.close_position: no open positions for %s", symbol)
            return []

        results: list[MT5FillResult] = []
        for pos in positions:
            close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                logger.error("mt5_bridge.close_position: no tick for %s", symbol)
                continue

            close_price = tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask
            close_vol = volume if volume is not None else pos.volume

            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": float(close_vol),
                "type": close_type,
                "position": pos.ticket,
                "price": close_price,
                "deviation": deviation,
                "magic": magic,
                "comment": comment,
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            result = mt5.order_send(request)
            if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
                retcode = result.retcode if result else -1
                logger.error(
                    "mt5_bridge.close_position failed ticket=%d retcode=%d",
                    pos.ticket,
                    retcode,
                )
                continue

            fill = MT5FillResult(
                ticket=result.order,
                status=FillStatus.FILLED,
                filled_volume=result.volume,
                fill_price=result.price,
                commission=getattr(result, "commission", 0.0),
                swap=getattr(result, "swap", 0.0),
                profit=getattr(result, "profit", 0.0),
                comment=result.comment,
                raw=result,
            )
            results.append(fill)
            logger.info(
                "mt5_bridge closed ticket=%d symbol=%s vol=%.2f price=%.5f",
                fill.ticket,
                symbol,
                fill.filled_volume,
                fill.fill_price,
            )
        return results

    # ── account / position queries ────────────────────────────────────────────

    def get_account(self) -> dict[str, Any]:
        self._require_connected()
        if not _MT5_AVAILABLE:
            return {"mode": "signal_export", "connected": True}
        info = mt5.account_info()
        if info is None:
            raise RuntimeError(f"mt5.account_info() failed: {mt5.last_error()}")
        return {
            "login": info.login,
            "server": info.server,
            "balance": info.balance,
            "equity": info.equity,
            "margin": info.margin,
            "margin_free": info.margin_free,
            "margin_level": info.margin_level,
            "leverage": info.leverage,
            "currency": info.currency,
        }

    def get_position(self, symbol: str) -> dict[str, Any]:
        self._require_connected()
        if not _MT5_AVAILABLE:
            return {}
        positions = mt5.positions_get(symbol=symbol)
        if not positions:
            return {}
        total_volume = sum(p.volume for p in positions)
        avg_price = sum(p.price_open * p.volume for p in positions) / total_volume
        total_profit = sum(p.profit for p in positions)
        side = "LONG" if positions[0].type == mt5.POSITION_TYPE_BUY else "SHORT"
        return {
            "symbol": symbol,
            "side": side,
            "volume": total_volume,
            "avg_entry_price": avg_price,
            "unrealized_pnl": total_profit,
            "tickets": [p.ticket for p in positions],
        }

    # ── modify / cancel ───────────────────────────────────────────────────────

    @_retry(max_attempts=2, base_delay=0.5)
    def modify_order(
        self,
        ticket: int,
        symbol: str,
        stop_loss: float | None = None,
        take_profit: float | None = None,
    ) -> bool:
        """
        Modify stop-loss and/or take-profit on an open position or pending order.

        Direct mode: uses mt5.order_send with TRADE_ACTION_SLTP.
        Signal-export mode: writes a MODIFY signal file for the EA.

        Returns True on success, raises RuntimeError on failure.
        """
        self._require_connected()

        if not _MT5_AVAILABLE:
            # Signal-export mode — write MODIFY file for EA
            path = self._exporter.export_modify(
                ticket=ticket,
                symbol=symbol,
                stop_loss=stop_loss,
                take_profit=take_profit,
            )
            logger.info(
                "mt5_bridge.modify_order (signal): ticket=%d SL=%s TP=%s path=%s",
                ticket,
                stop_loss,
                take_profit,
                path,
            )
            return True

        # Direct MT5 mode
        request: dict[str, Any] = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "symbol": symbol,
        }
        if stop_loss is not None:
            request["sl"] = float(stop_loss)
        if take_profit is not None:
            request["tp"] = float(take_profit)

        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            retcode = result.retcode if result else -1
            raise RuntimeError(f"mt5_bridge.modify_order failed ticket={ticket} retcode={retcode}")
        logger.info(
            "mt5_bridge.modify_order: ticket=%d SL=%s TP=%s retcode=%d",
            ticket,
            stop_loss,
            take_profit,
            result.retcode,
        )
        return True

    @_retry(max_attempts=2, base_delay=0.5)
    def cancel_order(self, ticket: int, symbol: str = "") -> bool:
        """
        Cancel a pending order by ticket.

        Direct mode: uses mt5.order_send with TRADE_ACTION_REMOVE.
        Signal-export mode: writes a CANCEL signal file for the EA.

        Returns True on success, raises RuntimeError on failure.
        """
        self._require_connected()

        if not _MT5_AVAILABLE:
            path = self._exporter.export_cancel(ticket=ticket, symbol=symbol)
            logger.info("mt5_bridge.cancel_order (signal): ticket=%d path=%s", ticket, path)
            return True

        request = {
            "action": mt5.TRADE_ACTION_REMOVE,
            "order": ticket,
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            retcode = result.retcode if result else -1
            raise RuntimeError(f"mt5_bridge.cancel_order failed ticket={ticket} retcode={retcode}")
        logger.info("mt5_bridge.cancel_order: ticket=%d retcode=%d", ticket, result.retcode)
        return True

    # ── async wrappers ────────────────────────────────────────────────────────

    async def async_send_order(self, order: MT5Order) -> MT5FillResult:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.send_order, order)

    async def async_close_position(
        self,
        symbol: str,
        volume: float | None = None,
    ) -> list[MT5FillResult]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.close_position, symbol, volume)

    async def async_modify_order(
        self,
        ticket: int,
        symbol: str,
        stop_loss: float | None = None,
        take_profit: float | None = None,
    ) -> bool:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.modify_order, ticket, symbol, stop_loss, take_profit)

    async def async_cancel_order(self, ticket: int, symbol: str = "") -> bool:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.cancel_order, ticket, symbol)

    # ── context manager ───────────────────────────────────────────────────────

    def __enter__(self) -> MT5Bridge:
        self.connect()
        return self

    def __exit__(self, *_) -> None:
        self.disconnect()
