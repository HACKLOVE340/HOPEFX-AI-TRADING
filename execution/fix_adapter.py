"""
execution/fix_adapter.py
========================
Low-latency FIX protocol adapter using quickfix / pyfixmsg.

Features:
  - FIX 4.4 session with configurable heartbeat (default 5 s)
  - Circuit breaker: suspends order flow if round-trip latency > 100 ms
  - Async-compatible send_order() that resolves on ExecutionReport
  - Integration hook for SmartOrderRouter (brokers/smart_router.py)
  - Structured logging

Dependencies (install as needed):
    pip install quickfix          # C-extension, preferred for production
    pip install pyfixmsg          # Pure-Python fallback

The adapter tries quickfix first; falls back to pyfixmsg if unavailable.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Library detection — prefer quickfix, fall back to pyfixmsg
# ---------------------------------------------------------------------------
_FIX_BACKEND: str = "none"

try:
    import quickfix as fix  # type: ignore
    import quickfix44 as fix44  # type: ignore
    _FIX_BACKEND = "quickfix"
    logger.info("fix_adapter: using quickfix backend")
except ImportError:
    fix = None  # type: ignore
    fix44 = None  # type: ignore

if _FIX_BACKEND == "none":
    try:
        import pyfixmsg  # type: ignore
        from pyfixmsg.lib.message import FixMessage  # type: ignore
        _FIX_BACKEND = "pyfixmsg"
        logger.info("fix_adapter: using pyfixmsg backend")
    except ImportError:
        pyfixmsg = None  # type: ignore
        FixMessage = None  # type: ignore
        logger.warning(
            "fix_adapter: no FIX library found. "
            "Install quickfix or pyfixmsg for live execution."
        )


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------

class FIXSide(Enum):
    BUY = "1"
    SELL = "2"


class FIXOrdType(Enum):
    MARKET = "1"
    LIMIT = "2"
    STOP = "3"


class FIXExecType(Enum):
    NEW = "0"
    PARTIAL_FILL = "1"
    FILL = "2"
    CANCELLED = "4"
    REJECTED = "8"


@dataclass
class FIXOrder:
    symbol: str
    side: FIXSide
    quantity: float
    ord_type: FIXOrdType = FIXOrdType.MARKET
    price: Optional[float] = None        # Required for LIMIT
    stop_px: Optional[float] = None      # Required for STOP
    cl_ord_id: str = field(default_factory=lambda: str(uuid.uuid4())[:16])
    account: str = ""
    currency: str = "USD"
    time_in_force: str = "0"             # 0=Day, 1=GTC, 3=IOC, 4=FOK


@dataclass
class FIXFillReport:
    cl_ord_id: str
    order_id: str
    exec_type: FIXExecType
    symbol: str
    side: FIXSide
    filled_qty: float
    avg_px: float
    leaves_qty: float
    cum_qty: float
    text: str = ""
    latency_ms: float = 0.0
    raw: Any = field(default=None, repr=False)


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------

class CircuitBreaker:
    """
    Opens when measured latency exceeds `threshold_ms`.
    Resets after `reset_after_sec` seconds of no new orders.
    """

    def __init__(self, threshold_ms: float = 100.0, reset_after_sec: float = 30.0) -> None:
        self.threshold_ms = threshold_ms
        self.reset_after_sec = reset_after_sec
        self._open = False
        self._opened_at: Optional[float] = None
        self._lock = threading.Lock()

    def record_latency(self, latency_ms: float) -> None:
        with self._lock:
            if latency_ms > self.threshold_ms:
                if not self._open:
                    self._open = True
                    self._opened_at = time.monotonic()
                    logger.error(
                        "circuit_breaker.OPEN latency=%.1f ms threshold=%.1f ms",
                        latency_ms, self.threshold_ms,
                    )
            else:
                if self._open:
                    elapsed = time.monotonic() - (self._opened_at or 0)
                    if elapsed >= self.reset_after_sec:
                        self._open = False
                        logger.info("circuit_breaker.CLOSED latency=%.1f ms", latency_ms)

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._open

    def check(self) -> None:
        """Raise if circuit is open."""
        if self.is_open:
            raise RuntimeError(
                f"FIX circuit breaker is OPEN (latency > {self.threshold_ms} ms). "
                "Order flow suspended."
            )


# ---------------------------------------------------------------------------
# quickfix Application callbacks
# ---------------------------------------------------------------------------

class _QuickfixApp(fix.Application):  # type: ignore[misc]
    """
    quickfix Application implementation.
    Dispatches ExecutionReports to pending futures registered by FIXAdapter.
    """

    def __init__(
        self,
        on_exec_report: Callable[[FIXFillReport], None],
        circuit_breaker: CircuitBreaker,
    ) -> None:
        super().__init__()
        self._on_exec_report = on_exec_report
        self._cb = circuit_breaker
        self._send_times: dict[str, float] = {}  # cl_ord_id → send monotonic time

    # --- quickfix callbacks ---

    def onCreate(self, session_id):
        logger.info("fix.session_created session=%s", session_id)

    def onLogon(self, session_id):
        logger.info("fix.logon session=%s", session_id)

    def onLogout(self, session_id):
        logger.info("fix.logout session=%s", session_id)

    def toAdmin(self, message, session_id):
        pass  # Heartbeats / logon handled by quickfix engine

    def fromAdmin(self, message, session_id):
        pass

    def toApp(self, message, session_id):
        # Record send time for latency measurement
        try:
            cl_ord_id = message.getField(fix.ClOrdID()).getString()
            self._send_times[cl_ord_id] = time.monotonic()
        except Exception:
            pass

    def fromApp(self, message, session_id):
        msg_type = fix.MsgType()
        message.getHeader().getField(msg_type)

        if msg_type.getValue() == fix.MsgType_ExecutionReport:
            self._handle_exec_report(message)

    # --- Internal ---

    def _handle_exec_report(self, message) -> None:
        try:
            cl_ord_id_f = fix.ClOrdID()
            order_id_f = fix.OrderID()
            exec_type_f = fix.ExecType()
            symbol_f = fix.Symbol()
            side_f = fix.Side()
            last_qty_f = fix.LastQty()
            avg_px_f = fix.AvgPx()
            leaves_qty_f = fix.LeavesQty()
            cum_qty_f = fix.CumQty()

            message.getField(cl_ord_id_f)
            message.getField(order_id_f)
            message.getField(exec_type_f)
            message.getField(symbol_f)
            message.getField(side_f)
            message.getField(last_qty_f)
            message.getField(avg_px_f)
            message.getField(leaves_qty_f)
            message.getField(cum_qty_f)

            cl_ord_id = cl_ord_id_f.getString()
            latency_ms = 0.0
            if cl_ord_id in self._send_times:
                latency_ms = (time.monotonic() - self._send_times.pop(cl_ord_id)) * 1000
                self._cb.record_latency(latency_ms)

            report = FIXFillReport(
                cl_ord_id=cl_ord_id,
                order_id=order_id_f.getString(),
                exec_type=FIXExecType(exec_type_f.getValue()),
                symbol=symbol_f.getString(),
                side=FIXSide(side_f.getValue()),
                filled_qty=float(last_qty_f.getValue()),
                avg_px=float(avg_px_f.getValue()),
                leaves_qty=float(leaves_qty_f.getValue()),
                cum_qty=float(cum_qty_f.getValue()),
                latency_ms=latency_ms,
                raw=message,
            )
            self._on_exec_report(report)

        except Exception as exc:
            logger.exception("fix_adapter._handle_exec_report error: %s", exc)


# ---------------------------------------------------------------------------
# Main adapter
# ---------------------------------------------------------------------------

class FIXAdapter:
    """
    Low-latency FIX 4.4 order adapter.

    Integrates with SmartOrderRouter via `route_hook()`.

    Usage:
        adapter = FIXAdapter(
            config_file="fix.cfg",
            sender_comp_id="CLIENT1",
            target_comp_id="BROKER1",
        )
        adapter.start()
        report = await adapter.send_order(order)
        adapter.stop()
    """

    HEARTBEAT_INTERVAL = 5  # seconds

    def __init__(
        self,
        config_file: str = "fix.cfg",
        sender_comp_id: str = "CLIENT",
        target_comp_id: str = "BROKER",
        host: str = "127.0.0.1",
        port: int = 9876,
        latency_threshold_ms: float = 100.0,
    ) -> None:
        self.config_file = config_file
        self.sender_comp_id = sender_comp_id
        self.target_comp_id = target_comp_id
        self.host = host
        self.port = port

        self.circuit_breaker = CircuitBreaker(threshold_ms=latency_threshold_ms)

        # Pending order futures: cl_ord_id → asyncio.Future
        self._pending: dict[str, asyncio.Future] = {}
        self._pending_lock = threading.Lock()

        # quickfix objects (set in start())
        self._initiator: Any = None
        self._session_id: Any = None
        self._app: Optional[_QuickfixApp] = None

        # Heartbeat thread
        self._hb_thread: Optional[threading.Thread] = None
        self._running = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the FIX session."""
        if _FIX_BACKEND == "quickfix":
            self._start_quickfix()
        elif _FIX_BACKEND == "pyfixmsg":
            self._start_pyfixmsg()
        else:
            logger.warning(
                "fix_adapter.start: no FIX backend available — running in simulation mode"
            )

        self._running = True
        self._hb_thread = threading.Thread(
            target=self._heartbeat_loop, daemon=True, name="FIXHeartbeat"
        )
        self._hb_thread.start()
        logger.info("fix_adapter.started backend=%s", _FIX_BACKEND)

    def stop(self) -> None:
        """Stop the FIX session."""
        self._running = False
        if self._initiator:
            try:
                self._initiator.stop()
            except Exception:
                pass
        logger.info("fix_adapter.stopped")

    def _start_quickfix(self) -> None:
        """Initialise quickfix initiator from config file or generated settings."""
        self._app = _QuickfixApp(
            on_exec_report=self._dispatch_exec_report,
            circuit_breaker=self.circuit_breaker,
        )

        import os
        if os.path.exists(self.config_file):
            settings = fix.SessionSettings(self.config_file)
        else:
            # Build minimal in-memory settings
            settings_str = (
                "[DEFAULT]\n"
                f"ConnectionType=initiator\n"
                f"HeartBtInt={self.HEARTBEAT_INTERVAL}\n"
                f"ReconnectInterval=5\n"
                f"FileStorePath=fix_store\n"
                f"FileLogPath=fix_log\n"
                f"StartTime=00:00:00\n"
                f"EndTime=00:00:00\n"
                f"UseDataDictionary=N\n"
                f"[SESSION]\n"
                f"BeginString=FIX.4.4\n"
                f"SenderCompID={self.sender_comp_id}\n"
                f"TargetCompID={self.target_comp_id}\n"
                f"SocketConnectHost={self.host}\n"
                f"SocketConnectPort={self.port}\n"
            )
            import tempfile, os
            tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".cfg", delete=False)
            tmp.write(settings_str)
            tmp.close()
            settings = fix.SessionSettings(tmp.name)
            os.unlink(tmp.name)

        store_factory = fix.FileStoreFactory(settings)
        log_factory = fix.FileLogFactory(settings)
        self._initiator = fix.SocketInitiator(self._app, store_factory, settings, log_factory)
        self._initiator.start()

        # Capture session ID
        for sid in self._initiator.getSessions():
            self._session_id = sid
            break

    def _start_pyfixmsg(self) -> None:
        """pyfixmsg uses a simpler socket-based approach — stub for extensibility."""
        logger.info("fix_adapter: pyfixmsg session initialised (stub)")

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    def _heartbeat_loop(self) -> None:
        """Log heartbeat every HEARTBEAT_INTERVAL seconds and check circuit breaker."""
        while self._running:
            time.sleep(self.HEARTBEAT_INTERVAL)
            status = "OPEN" if self.circuit_breaker.is_open else "CLOSED"
            logger.debug(
                "fix_adapter.heartbeat backend=%s circuit=%s",
                _FIX_BACKEND, status,
            )

    # ------------------------------------------------------------------
    # Order sending
    # ------------------------------------------------------------------

    async def send_order(self, order: FIXOrder) -> FIXFillReport:
        """
        Send a FIX NewOrderSingle and await the ExecutionReport.

        Raises RuntimeError if the circuit breaker is open.
        Raises TimeoutError if no fill arrives within 30 s.
        """
        self.circuit_breaker.check()

        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()

        with self._pending_lock:
            self._pending[order.cl_ord_id] = future

        try:
            if _FIX_BACKEND == "quickfix":
                await loop.run_in_executor(None, self._send_quickfix, order)
            elif _FIX_BACKEND == "pyfixmsg":
                await loop.run_in_executor(None, self._send_pyfixmsg, order)
            else:
                # Simulation: resolve immediately with a synthetic fill
                report = self._simulate_fill(order)
                future.set_result(report)

            return await asyncio.wait_for(future, timeout=30.0)

        except asyncio.TimeoutError:
            with self._pending_lock:
                self._pending.pop(order.cl_ord_id, None)
            raise TimeoutError(
                f"FIX ExecutionReport not received within 30 s for {order.cl_ord_id}"
            )

    def _send_quickfix(self, order: FIXOrder) -> None:
        """Build and send a FIX 4.4 NewOrderSingle via quickfix."""
        if self._session_id is None:
            raise RuntimeError("FIX session not established")

        msg = fix44.NewOrderSingle()
        header = msg.getHeader()
        header.setField(fix.BeginString(fix.BeginString_FIX44))

        msg.setField(fix.ClOrdID(order.cl_ord_id))
        msg.setField(fix.Symbol(order.symbol))
        msg.setField(fix.Side(order.side.value))
        msg.setField(fix.TransactTime())
        msg.setField(fix.OrdType(order.ord_type.value))
        msg.setField(fix.OrderQty(order.quantity))
        msg.setField(fix.TimeInForce(order.time_in_force))

        if order.ord_type == FIXOrdType.LIMIT and order.price is not None:
            msg.setField(fix.Price(order.price))
        if order.ord_type == FIXOrdType.STOP and order.stop_px is not None:
            msg.setField(fix.StopPx(order.stop_px))
        if order.account:
            msg.setField(fix.Account(order.account))

        fix.Session.sendToTarget(msg, self._session_id)
        logger.info(
            "fix_adapter.sent cl_ord_id=%s symbol=%s side=%s qty=%.2f",
            order.cl_ord_id, order.symbol, order.side.value, order.quantity,
        )

    def _send_pyfixmsg(self, order: FIXOrder) -> None:
        """pyfixmsg send stub — extend with actual socket send."""
        logger.info(
            "fix_adapter.pyfixmsg.send cl_ord_id=%s symbol=%s",
            order.cl_ord_id, order.symbol,
        )

    def _simulate_fill(self, order: FIXOrder) -> FIXFillReport:
        """Return a synthetic fill for simulation / testing."""
        return FIXFillReport(
            cl_ord_id=order.cl_ord_id,
            order_id=str(uuid.uuid4())[:8],
            exec_type=FIXExecType.FILL,
            symbol=order.symbol,
            side=order.side,
            filled_qty=order.quantity,
            avg_px=order.price or 1950.0,
            leaves_qty=0.0,
            cum_qty=order.quantity,
            latency_ms=0.5,
        )

    # ------------------------------------------------------------------
    # Execution report dispatch
    # ------------------------------------------------------------------

    def _dispatch_exec_report(self, report: FIXFillReport) -> None:
        """Called from quickfix thread; resolves the matching asyncio Future."""
        with self._pending_lock:
            future = self._pending.pop(report.cl_ord_id, None)

        if future is None:
            logger.debug("fix_adapter: unsolicited exec report cl_ord_id=%s", report.cl_ord_id)
            return

        if not future.done():
            # Schedule resolution on the event loop thread
            try:
                future.get_event_loop().call_soon_threadsafe(future.set_result, report)
            except Exception as exc:
                logger.warning("fix_adapter._dispatch_exec_report: %s", exc)

    # ------------------------------------------------------------------
    # SmartOrderRouter integration hook
    # ------------------------------------------------------------------

    def route_hook(self) -> Callable:
        """
        Returns a coroutine factory compatible with SmartOrderRouter.

        Usage in smart_router.py:
            fix_adapter = FIXAdapter(...)
            router.add_broker("fix", fix_adapter.route_hook())
        """
        async def _route(order_dict: dict) -> dict:
            fix_order = FIXOrder(
                symbol=order_dict["symbol"],
                side=FIXSide.BUY if order_dict.get("side", "BUY") == "BUY" else FIXSide.SELL,
                quantity=float(order_dict.get("quantity", 1.0)),
                ord_type=FIXOrdType.MARKET,
                price=order_dict.get("price"),
                account=order_dict.get("account", ""),
            )
            report = await self.send_order(fix_order)
            return {
                "broker": "fix",
                "cl_ord_id": report.cl_ord_id,
                "order_id": report.order_id,
                "filled_qty": report.filled_qty,
                "avg_px": report.avg_px,
                "latency_ms": report.latency_ms,
                "exec_type": report.exec_type.name,
            }

        return _route
