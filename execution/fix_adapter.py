# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
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
import os
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Library detection — prefer quickfix, fall back to pyfixmsg
# ---------------------------------------------------------------------------
_FIX_BACKEND: str = "none"

try:
    import quickfix as fix
    import quickfix44 as fix44

    _FIX_BACKEND = "quickfix"
    logger.info("fix_adapter: using quickfix backend")
except ImportError:
    fix = None
    fix44 = None

if _FIX_BACKEND == "none":
    try:
        import pyfixmsg
        from pyfixmsg.lib.message import FixMessage

        _FIX_BACKEND = "pyfixmsg"
        logger.info("fix_adapter: using pyfixmsg backend")
    except ImportError:
        pyfixmsg = None
        FixMessage = None

if _FIX_BACKEND == "none":
    try:
        import simplefix as _simplefix_mod  # availability check only

        _FIX_BACKEND = "simplefix"
        del _simplefix_mod
        logger.info("fix_adapter: using simplefix backend (message encoding only)")
    except ImportError:
        logger.warning(
            "fix_adapter: no FIX library found. Install quickfix or pyfixmsg for live execution.",
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
    price: float | None = None  # Required for LIMIT
    stop_px: float | None = None  # Required for STOP
    cl_ord_id: str = field(default_factory=lambda: str(uuid.uuid4())[:16])
    account: str = ""
    currency: str = "USD"
    time_in_force: str = "0"  # 0=Day, 1=GTC, 3=IOC, 4=FOK


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

    def __init__(
        self,
        threshold_ms: float = 100.0,
        reset_after_sec: float = 30.0,
    ) -> None:
        self.threshold_ms = threshold_ms
        self.reset_after_sec = reset_after_sec
        self._open = False
        self._opened_at: float | None = None
        self._lock = threading.Lock()

    def record_latency(self, latency_ms: float) -> None:
        with self._lock:
            if latency_ms > self.threshold_ms:
                if not self._open:
                    self._open = True
                    self._opened_at = time.monotonic()
                    logger.error(
                        "circuit_breaker.OPEN latency=%.1f ms threshold=%.1f ms",
                        latency_ms,
                        self.threshold_ms,
                    )
            elif self._open:
                elapsed = time.monotonic() - (self._opened_at or 0)
                if elapsed >= self.reset_after_sec:
                    self._open = False
                    logger.info(
                        "circuit_breaker.CLOSED latency=%.1f ms",
                        latency_ms,
                    )

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._open

    def check(self) -> None:
        """Raise if circuit is open."""
        if self.is_open:
            raise RuntimeError(
                f"FIX circuit breaker is OPEN (latency > {self.threshold_ms} ms). Order flow suspended.",
            )


# ---------------------------------------------------------------------------
# quickfix Application callbacks
# ---------------------------------------------------------------------------

# _QuickfixApp inherits from fix.Application only when quickfix is available.
# When the library is absent we use a plain object base so the class can still
# be defined and imported without raising AttributeError.
_QuickfixBase: type = fix.Application if fix is not None else object


def _get_fix_field(message: Any, field_obj: Any, context: str = "") -> str:
    """
    Extract a string value from a FIX message field.

    Returns an empty string when the field is absent or unreadable.
    Optional fields in FIX 4.4 (Text, CxlRejReason, etc.) are legitimately
    absent — callers should treat "" as "not present".

    Parameters
    ----------
    message   : quickfix Message object
    field_obj : pre-constructed quickfix field object (e.g. fix.Text())
    context   : label used in the debug log when the field is absent
    """
    try:
        message.getField(field_obj)
        return str(field_obj.getString())
    except (AttributeError, TypeError, ValueError) as exc:
        if context:
            logger.debug("%s field absent: %s", context, exc)
        return ""


class _QuickfixApp(_QuickfixBase):  # type: ignore[misc]
    """
    quickfix Application implementation.
    Dispatches ExecutionReports to pending futures registered by FIXAdapter.
    """

    def __init__(
        self,
        on_exec_report: Callable[[FIXFillReport], None],
        circuit_breaker: CircuitBreaker,
        username: str = "",
        password: str = "",  # nosec B107 - optional FIX credential, empty default is intentional
    ) -> None:
        super().__init__()
        self._on_exec_report = on_exec_report
        self._cb = circuit_breaker
        self._send_times: dict[str, float] = {}  # cl_ord_id → send monotonic time
        self._username = username
        self._password = password

    # --- quickfix callbacks ---

    def onCreate(self, session_id: Any) -> None:
        logger.info("fix.session_created session=%s", session_id)

    def onLogon(self, session_id: Any) -> None:
        logger.info("fix.logon session=%s", session_id)

    def onLogout(self, session_id: Any) -> None:
        logger.info("fix.logout session=%s", session_id)

    def toAdmin(self, message: Any, session_id: Any) -> None:
        """
        Called before every admin message is sent (Logon, Heartbeat, etc.).

        Injects Username (553) and Password (554) into Logon messages when
        credentials are configured.  All other admin messages (Heartbeat,
        TestRequest, ResendRequest, SequenceReset) are handled entirely by
        the quickfix engine and require no application-level intervention.
        """
        if fix is None:
            return
        try:
            msg_type = fix.MsgType()
            message.getHeader().getField(msg_type)
            if msg_type.getValue() == fix.MsgType_Logon:
                if self._username:
                    message.setField(fix.Username(self._username))
                if self._password:
                    message.setField(fix.Password(self._password))
        except (AttributeError, TypeError, ValueError) as exc:
            logger.warning("fix.toAdmin: could not inject credentials: %s", exc)

    def _log_logout(self, message: Any, session_id: Any) -> None:
        """Log an inbound Logout message with its optional reason text."""
        text = _get_fix_field(message, fix.Text(), "fix.fromAdmin: Logout Text")
        logger.warning("fix.fromAdmin: Logout received session=%s text=%r", session_id, text)

    def _log_session_reject(self, message: Any) -> None:
        """Log an inbound session-level Reject with ref_seq, reason, and text."""
        ref_seq = _get_fix_field(message, fix.RefSeqNum(), "fix.fromAdmin: Reject RefSeqNum")
        reason = _get_fix_field(message, fix.SessionRejectReason(), "fix.fromAdmin: Reject SessionRejectReason")
        text = _get_fix_field(message, fix.Text(), "fix.fromAdmin: Reject Text")
        logger.error(
            "fix.fromAdmin: session Reject ref_seq=%s reason=%s text=%r",
            ref_seq,
            reason,
            text,
        )

    def fromAdmin(self, message: Any, session_id: Any) -> None:
        """
        Called for every inbound admin message (Logon, Logout, Heartbeat, etc.).

        Logs session-level rejects and Logout messages with their reason text
        so operators can diagnose authentication failures and forced disconnects.
        """
        if fix is None:
            return
        try:
            msg_type = fix.MsgType()
            message.getHeader().getField(msg_type)
            mt = msg_type.getValue()

            if mt == fix.MsgType_Logout:
                self._log_logout(message, session_id)
            elif mt == fix.MsgType_Reject:
                self._log_session_reject(message)
        except (AttributeError, ValueError, TypeError) as exc:
            logger.warning("fix.fromAdmin: error processing admin message: %s", exc)

    def toApp(self, message: Any, session_id: Any) -> None:
        # Record send time for latency measurement.
        # ClOrdID is absent on non-order admin messages — not an error.
        try:
            cl_ord_id = message.getField(fix.ClOrdID()).getString()
            self._send_times[cl_ord_id] = time.monotonic()
        except (AttributeError, TypeError) as _e:
            logger.debug("fix.toApp: ClOrdID not present in outbound message: %s", _e)

    def fromApp(self, message: Any, session_id: Any) -> None:
        msg_type = fix.MsgType()
        message.getHeader().getField(msg_type)
        mt = msg_type.getValue()

        if mt == fix.MsgType_ExecutionReport:
            self._handle_exec_report(message)
        elif mt == "9":  # OrderCancelReject
            self._handle_order_cancel_reject(message)

    # --- Internal ---

    def _extract_exec_report_fields(self, message: Any) -> dict[str, Any]:
        """
        Extract all required ExecutionReport fields from a quickfix message.

        Returns a plain dict so _handle_exec_report stays under 20 lines.
        Raises on any missing required field — callers catch and reject.
        """

        def _req(field_obj: Any) -> Any:
            """Fetch a required field; raises if absent."""
            message.getField(field_obj)
            return field_obj

        cl_ord_id_f = _req(fix.ClOrdID())
        order_id_f = _req(fix.OrderID())
        exec_type_f = _req(fix.ExecType())
        symbol_f = _req(fix.Symbol())
        side_f = _req(fix.Side())
        last_qty_f = _req(fix.LastQty())
        avg_px_f = _req(fix.AvgPx())
        leaves_qty_f = _req(fix.LeavesQty())
        cum_qty_f = _req(fix.CumQty())

        return {
            "cl_ord_id": cl_ord_id_f.getString(),
            "order_id": order_id_f.getString(),
            "exec_type": FIXExecType(exec_type_f.getValue()),
            "symbol": symbol_f.getString(),
            "side": FIXSide(side_f.getValue()),
            "filled_qty": float(last_qty_f.getValue()),
            "avg_px": float(avg_px_f.getValue()),
            "leaves_qty": float(leaves_qty_f.getValue()),
            "cum_qty": float(cum_qty_f.getValue()),
        }

    def _handle_exec_report(self, message: Any) -> None:
        cl_ord_id = "<unknown>"
        try:
            fields = self._extract_exec_report_fields(message)
            cl_ord_id = fields["cl_ord_id"]

            latency_ms = 0.0
            if cl_ord_id in self._send_times:
                latency_ms = (time.monotonic() - self._send_times.pop(cl_ord_id)) * 1000
                self._cb.record_latency(latency_ms)

            report = FIXFillReport(
                cl_ord_id=cl_ord_id,
                order_id=fields["order_id"],
                exec_type=fields["exec_type"],
                symbol=fields["symbol"],
                side=fields["side"],
                filled_qty=fields["filled_qty"],
                avg_px=fields["avg_px"],
                leaves_qty=fields["leaves_qty"],
                cum_qty=fields["cum_qty"],
                latency_ms=latency_ms,
                raw=message,
            )
            self._on_exec_report(report)

        except (AttributeError, ValueError, TypeError, KeyError) as exc:
            logger.exception(
                "fix_adapter._handle_exec_report error cl_ord_id=%s: %s",
                cl_ord_id,
                exc,
            )
            self._reject_pending(cl_ord_id, exc)

    def _handle_order_cancel_reject(self, message: Any) -> None:
        """Handle OrderCancelReject (MsgType=9) — broker refused cancel/replace."""
        cl_ord_id = "<unknown>"
        try:
            cl_ord_id_f = fix.ClOrdID()
            message.getField(cl_ord_id_f)
            cl_ord_id = cl_ord_id_f.getString()

            reason_code = _get_fix_field(message, fix.CxlRejReason(), "fix_adapter.OrderCancelReject: CxlRejReason")
            text = _get_fix_field(message, fix.Text(), "fix_adapter.OrderCancelReject: Text")

            logger.error(
                "fix_adapter.OrderCancelReject cl_ord_id=%s reason=%s text=%r",
                cl_ord_id,
                reason_code,
                text,
            )
            self._reject_pending(
                cl_ord_id,
                RuntimeError(
                    f"Order cancel/replace rejected by broker: cl_ord_id={cl_ord_id} reason={reason_code} text={text!r}"
                ),
            )
        except (AttributeError, ValueError, TypeError, KeyError) as exc:
            logger.exception(
                "fix_adapter._handle_order_cancel_reject error cl_ord_id=%s: %s",
                cl_ord_id,
                exc,
            )

    def _reject_pending(self, cl_ord_id: str, exc: Exception) -> None:
        """
        Resolve a pending future with an exception so the caller is not left hanging.

        NOTE: _pending and _pending_lock live on FIXAdapter, not on this class.
        They are injected via the on_exec_report callback path — this method is
        called by _handle_exec_report / _handle_order_cancel_reject which are
        invoked from the quickfix thread.  The FIXAdapter passes
        self._dispatch_exec_report as on_exec_report; _dispatch_exec_report owns
        the lock.  This method therefore delegates to the adapter's dispatcher
        rather than touching _pending directly.
        """
        # Wrap the exception in a synthetic FIXFillReport-like rejection and
        # route it through the normal on_exec_report callback so FIXAdapter's
        # _dispatch_exec_report can resolve the future under its own lock.
        # We signal rejection by calling on_exec_report with a REJECTED report.
        try:
            report = FIXFillReport(
                cl_ord_id=cl_ord_id,
                order_id="",
                exec_type=FIXExecType.REJECTED,
                symbol="",
                side=FIXSide.BUY,
                filled_qty=0.0,
                avg_px=0.0,
                leaves_qty=0.0,
                cum_qty=0.0,
                text=str(exc),
            )
            self._on_exec_report(report)
        except (RuntimeError, AttributeError, TypeError) as inner:
            logger.warning(
                "fix_adapter._reject_pending: could not dispatch rejection for cl_ord_id=%s: %s",
                cl_ord_id,
                inner,
            )


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
        username: str = "",
        password: str = "",  # nosec B107 - optional FIX credential, empty default is intentional
    ) -> None:
        self.config_file = config_file
        self.sender_comp_id = sender_comp_id
        self.target_comp_id = target_comp_id
        self.host = host
        self.port = port
        self._username = username
        self._password = password

        self.circuit_breaker = CircuitBreaker(threshold_ms=latency_threshold_ms)

        # Pending order futures: cl_ord_id → asyncio.Future
        self._pending: dict[str, asyncio.Future[FIXFillReport]] = {}
        self._pending_lock = threading.Lock()

        # quickfix objects (set in start())
        self._initiator: Any | None = None
        self._session_id: Any | None = None
        self._app: _QuickfixApp | None = None

        # Heartbeat thread
        self._hb_thread: threading.Thread | None = None
        self._hb_stop_event: threading.Event | None = None
        self._running = False

        # pyfixmsg socket state (set in _connect_pyfixmsg)
        self._pyfixmsg_sock: Any | None = None
        self._pyfixmsg_seq: int = 1

    # ------------------------------------------------------------------
    # Credential validation
    # ------------------------------------------------------------------

    _PLACEHOLDER_VALUES = frozenset(
        {
            "CLIENT",
            "BROKER",
            "HOPEFX",
            "CHANGE_ME",
            "<CHANGE_ME_YOUR_SENDER_COMP_ID>",
            "<CHANGE_ME_BROKER_TARGET_COMP_ID>",
            "<CHANGE_ME_BROKER_FIX_HOST>",
            "",
        }
    )

    def validate_credentials(self, *, raise_on_error: bool = False) -> bool:
        """Check that FIX session credentials are not placeholder values.

        Reads FIX_SENDER_COMP_ID / FIX_TARGET_COMP_ID / FIX_HOST / FIX_PORT
        from the environment and falls back to the constructor arguments.

        Returns True when all required values look real.  Logs a CRITICAL
        message for each placeholder found.  If *raise_on_error* is True,
        raises RuntimeError instead of returning False.

        Call this before start() in production to catch misconfiguration early:

            router = FIXRouter(...)
            router.validate_credentials(raise_on_error=True)
            router.start()
        """

        sender = os.environ.get("FIX_SENDER_COMP_ID", self.sender_comp_id)
        target = os.environ.get("FIX_TARGET_COMP_ID", self.target_comp_id)
        host = os.environ.get("FIX_HOST", self.host)

        errors: list[str] = []

        if sender in self._PLACEHOLDER_VALUES:
            errors.append(
                f"FIX_SENDER_COMP_ID is a placeholder ('{sender}'). "
                "Set FIX_SENDER_COMP_ID in your environment to the SenderCompID "
                "assigned by your broker during FIX onboarding."
            )
        if target in self._PLACEHOLDER_VALUES:
            errors.append(
                f"FIX_TARGET_COMP_ID is a placeholder ('{target}'). "
                "Set FIX_TARGET_COMP_ID to the TargetCompID from your broker's FIX spec."
            )
        if host in self._PLACEHOLDER_VALUES or host.startswith("<CHANGE_ME"):
            errors.append(f"FIX_HOST is a placeholder ('{host}'). Set FIX_HOST to your broker's FIX gateway hostname.")

        for msg in errors:
            logger.critical("fix_adapter credential error: %s", msg)

        if errors:
            if raise_on_error:
                raise RuntimeError(
                    "FIX session has placeholder credentials — cannot connect to broker. "
                    "See DEPLOYMENT.md §FIX Onboarding for setup instructions.\n"
                    + "\n".join(f"  • {e}" for e in errors)
                )
            return False

        logger.info(
            "fix_adapter credentials OK: sender=%s target=%s host=%s",
            sender,
            target,
            host,
        )
        return True

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the FIX session.

        Validates credentials before connecting.  In APP_ENV=production the
        check is enforced (raises RuntimeError on placeholder values).  In
        other environments a WARNING is logged and startup continues so that
        paper-trading and CI work without real broker credentials.
        """

        _is_production = os.environ.get("APP_ENV", "production") == "production"
        self.validate_credentials(raise_on_error=_is_production)

        if _FIX_BACKEND == "quickfix":
            self._start_quickfix()
        elif _FIX_BACKEND == "pyfixmsg":
            self._start_pyfixmsg()
        else:
            logger.warning(
                "fix_adapter.start: no FIX backend available — running in simulation mode",
            )

        self._running = True
        self._hb_thread = threading.Thread(
            target=self._heartbeat_loop,
            daemon=True,
            name="FIXHeartbeat",
        )
        self._hb_thread.start()
        logger.info("fix_adapter.started backend=%s", _FIX_BACKEND)

    def stop(self) -> None:
        """Stop the FIX session."""
        self._running = False
        # Signal the heartbeat Event.wait() to wake up immediately.
        hb_stop = getattr(self, "_hb_stop_event", None)
        if hb_stop is not None:
            hb_stop.set()
        if self._initiator:
            try:
                self._initiator.stop()
            except (RuntimeError, AttributeError, ConnectionError) as exc:
                # Log but do not re-raise — stop() must always complete so
                # the heartbeat thread and pending futures are cleaned up.
                logger.error("fix_adapter.stop: initiator.stop() raised: %s", exc)
        logger.info("fix_adapter.stopped")

    def _start_quickfix(self) -> None:
        """Initialise quickfix initiator from config file or generated settings."""
        self._app = _QuickfixApp(
            on_exec_report=self._dispatch_exec_report,
            circuit_breaker=self.circuit_breaker,
            username=self._username,
            password=self._password,
        )

        if Path(self.config_file).exists():
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
            import tempfile

            with tempfile.NamedTemporaryFile(mode="w", suffix=".cfg", delete=False) as tmp:
                tmp.write(settings_str)
                tmp_name = tmp.name
            settings = fix.SessionSettings(tmp_name)
            Path(tmp_name).unlink()

        store_factory = fix.FileStoreFactory(settings)
        log_factory = fix.FileLogFactory(settings)
        self._initiator = fix.SocketInitiator(
            self._app,
            store_factory,
            settings,
            log_factory,
        )
        self._initiator.start()

        # Capture session ID
        for sid in self._initiator.getSessions():
            self._session_id = sid
            break

    def _start_pyfixmsg(self) -> None:
        """
        Open a TCP socket to the FIX counterparty and send a FIX 4.4 Logon.

        pyfixmsg does not manage the session lifecycle the way quickfix does —
        the application is responsible for the socket and for sending/receiving
        raw FIX messages.  This implementation:

          1. Opens a blocking TCP socket to self.host:self.port.
          2. Sends a minimal FIX 4.4 Logon (MsgType=A) with HeartBtInt=30.
          3. Starts a background reader thread that feeds inbound bytes to
             pyfixmsg's codec and dispatches ExecutionReports.

        The socket is stored on self._pyfixmsg_sock so _send_pyfixmsg can use it.
        """
        import socket as _socket

        if pyfixmsg is None or FixMessage is None:  # pylint: disable=possibly-used-before-assignment
            raise RuntimeError("pyfixmsg is not installed. Run: pip install pyfixmsg")

        sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        sock.settimeout(10.0)
        try:
            sock.connect((self.host, self.port))
        except OSError as exc:
            raise RuntimeError(
                f"fix_adapter._start_pyfixmsg: cannot connect to {self.host}:{self.port} — {exc}",
            ) from exc

        sock.settimeout(None)  # switch to blocking for the reader thread
        self._pyfixmsg_sock = sock
        self._pyfixmsg_seq = 1  # outbound MsgSeqNum

        # Send Logon (MsgType=A) from exc
        logon = self._build_pyfixmsg_logon()
        sock.sendall(logon)
        logger.info(
            "fix_adapter._start_pyfixmsg: connected to %s:%s, Logon sent",
            self.host,
            self.port,
        )

        # Start background reader
        reader = threading.Thread(
            target=self._pyfixmsg_reader_loop,
            args=(sock,),
            daemon=True,
            name="FIXpyfixmsgReader",
        )
        reader.start()

    def _build_pyfixmsg_logon(self) -> bytes:
        """Build a minimal FIX 4.4 Logon message as raw bytes."""
        seq = self._pyfixmsg_seq
        self._pyfixmsg_seq += 1
        sending_time = time.strftime("%Y%m%d-%H:%M:%S", time.gmtime())

        fields = [
            ("8", "FIX.4.4"),
            ("35", "A"),  # MsgType = Logon
            ("49", self.sender_comp_id),
            ("56", self.target_comp_id),
            ("34", str(seq)),
            ("52", sending_time),
            ("98", "0"),  # EncryptMethod = None
            ("108", "30"),  # HeartBtInt
        ]
        if self._username:
            fields.append(("553", self._username))
        if self._password:
            fields.append(("554", self._password))

        body = "\x01".join(f"{tag}={val}" for tag, val in fields[1:]) + "\x01"
        body_len = len(body.encode())
        header = f"8=FIX.4.4\x019={body_len}\x01"
        raw = header + body
        checksum = sum(raw.encode()) % 256
        raw += f"10={checksum:03d}\x01"
        return raw.encode()

    def _pyfixmsg_reader_loop(self, sock: Any) -> None:
        """
        Read raw FIX bytes from the socket and dispatch ExecutionReports.

        Runs in a daemon thread.  Exits when the socket is closed or the
        adapter is stopped.
        """
        buf = b""
        while self._running:
            try:
                chunk = sock.recv(4096)
                if not chunk:
                    logger.warning(
                        "fix_adapter._pyfixmsg_reader_loop: connection closed by peer",
                    )
                    break
                buf += chunk
                # Split on SOH-terminated messages (FIX delimiter is \x01 after checksum tag 10=)
                while b"10=" in buf:
                    end = buf.find(b"\x01", buf.index(b"10="))
                    if end == -1:
                        break
                    raw_msg = buf[: end + 1]
                    buf = buf[end + 1 :]
                    self._handle_pyfixmsg_message(raw_msg)
            except OSError as exc:
                if self._running:
                    logger.error(
                        "fix_adapter._pyfixmsg_reader_loop: socket error: %s",
                        exc,
                    )
                break

    def _handle_pyfixmsg_message(self, raw: bytes) -> None:
        """Parse a raw FIX message and dispatch ExecutionReports."""
        try:
            # Parse tag=value pairs from raw bytes
            fields: dict[str, str] = {}
            for part in raw.decode(errors="replace").split("\x01"):
                if "=" in part:
                    tag, _, val = part.partition("=")
                    fields[tag] = val

            msg_type = fields.get("35", "")
            if msg_type == "8":  # ExecutionReport
                cl_ord_id = fields.get("11", "<unknown>")
                exec_type_raw = fields.get("150", "0")
                try:
                    exec_type = FIXExecType(exec_type_raw)
                except ValueError:
                    exec_type = FIXExecType.NEW

                report = FIXFillReport(
                    cl_ord_id=cl_ord_id,
                    order_id=fields.get("37", ""),
                    exec_type=exec_type,
                    symbol=fields.get("55", ""),
                    side=FIXSide(fields.get("54", "1")),
                    filled_qty=float(fields.get("32", 0)),  # LastQty
                    avg_px=float(fields.get("6", 0)),  # AvgPx
                    leaves_qty=float(fields.get("151", 0)),  # LeavesQty
                    cum_qty=float(fields.get("14", 0)),  # CumQty
                    text=fields.get("58", ""),
                    raw=fields,
                )
                self._dispatch_exec_report(report)

            elif msg_type == "5":  # Logout
                logger.warning(
                    "fix_adapter._handle_pyfixmsg_message: Logout received text=%r",
                    fields.get("58", ""),
                )
            elif msg_type == "3":  # Reject
                logger.error(
                    "fix_adapter._handle_pyfixmsg_message: session Reject ref_seq=%s text=%r",
                    fields.get("45", ""),
                    fields.get("58", ""),
                )
        except (ValueError, AttributeError, TypeError, KeyError) as exc:
            logger.exception(
                "fix_adapter._handle_pyfixmsg_message: parse error: %s",
                exc,
            )

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    def _heartbeat_loop(self) -> None:
        """Log heartbeat every HEARTBEAT_INTERVAL seconds and check circuit breaker.

        Uses threading.Event.wait() instead of time.sleep() so the GIL is
        released during the wait and stop() can interrupt the interval promptly.
        """
        _stop_event = threading.Event()
        # Store on self so stop() can set it for a clean interrupt.
        self._hb_stop_event = _stop_event
        while self._running:
            _stop_event.wait(timeout=self.HEARTBEAT_INTERVAL)
            if not self._running:
                break
            status = "OPEN" if self.circuit_breaker.is_open else "CLOSED"
            logger.debug(
                "fix_adapter.heartbeat backend=%s circuit=%s",
                _FIX_BACKEND,
                status,
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

        loop = asyncio.get_running_loop()
        future: asyncio.Future[FIXFillReport] = loop.create_future()

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

        except TimeoutError:
            with self._pending_lock:
                self._pending.pop(order.cl_ord_id, None)
            raise TimeoutError(
                f"FIX ExecutionReport not received within 30 s for {order.cl_ord_id}",
            ) from None

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
            order.cl_ord_id,
            order.symbol,
            order.side.value,
            order.quantity,
        )

    def _send_pyfixmsg(self, order: FIXOrder) -> None:
        """
        Build a FIX 4.4 NewOrderSingle and send it over the pyfixmsg socket.

        Raises RuntimeError if the socket is not connected (start() not called).
        """
        sock = getattr(self, "_pyfixmsg_sock", None)
        if sock is None:
            raise RuntimeError(
                "fix_adapter._send_pyfixmsg: socket not connected — call start() first",
            )

        seq = self._pyfixmsg_seq
        self._pyfixmsg_seq += 1
        sending_time = time.strftime("%Y%m%d-%H:%M:%S", time.gmtime())

        fields = [
            ("8", "FIX.4.4"),
            ("35", "D"),  # MsgType = NewOrderSingle
            ("49", self.sender_comp_id),
            ("56", self.target_comp_id),
            ("34", str(seq)),
            ("52", sending_time),
            ("11", order.cl_ord_id),  # ClOrdID
            ("55", order.symbol),  # Symbol
            ("54", order.side.value),  # Side
            ("60", sending_time),  # TransactTime
            ("40", order.ord_type.value),  # OrdType
            ("38", str(order.quantity)),  # OrderQty
            ("59", order.time_in_force),  # TimeInForce
        ]
        if order.ord_type == FIXOrdType.LIMIT and order.price is not None:
            fields.append(("44", str(order.price)))  # Price
        if order.ord_type == FIXOrdType.STOP and order.stop_px is not None:
            fields.append(("99", str(order.stop_px)))  # StopPx
        if order.account:
            fields.append(("1", order.account))  # Account
        if order.currency:
            fields.append(("15", order.currency))  # Currency

        body = "\x01".join(f"{tag}={val}" for tag, val in fields[1:]) + "\x01"
        body_len = len(body.encode())
        header = f"8=FIX.4.4\x019={body_len}\x01"
        raw = header + body
        checksum = sum(raw.encode()) % 256
        raw += f"10={checksum:03d}\x01"

        # Record send time for latency measurement (mirrors quickfix path)
        if self._app is not None:
            self._app._send_times[order.cl_ord_id] = time.monotonic()

        try:
            sock.sendall(raw.encode())
        except OSError as exc:
            raise RuntimeError(
                f"fix_adapter._send_pyfixmsg: send failed for {order.cl_ord_id}: {exc}",
            ) from exc

        logger.info(
            "fix_adapter.pyfixmsg.sent cl_ord_id=%s symbol=%s side=%s qty=%.2f",
            order.cl_ord_id,
            order.symbol,
            order.side.value,
            order.quantity,
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
        """
        Called from the quickfix or pyfixmsg reader thread; resolves the
        matching asyncio Future.

        REJECTED reports set an exception on the future so the caller receives
        a RuntimeError immediately rather than waiting for the 30 s timeout.
        """
        with self._pending_lock:
            future = self._pending.pop(report.cl_ord_id, None)

        if future is None:
            logger.debug(
                "fix_adapter: unsolicited exec report cl_ord_id=%s",
                report.cl_ord_id,
            )
            return

        if not future.done():
            try:
                loop = future.get_loop() if hasattr(future, "get_loop") else asyncio.get_running_loop()
                if report.exec_type == FIXExecType.REJECTED:
                    exc = RuntimeError(
                        f"FIX order rejected by broker: cl_ord_id={report.cl_ord_id} text={report.text!r}",
                    )
                    loop.call_soon_threadsafe(future.set_exception, exc)
                else:
                    loop.call_soon_threadsafe(future.set_result, report)
            except (RuntimeError, AttributeError, ValueError) as exc:
                logger.warning("fix_adapter._dispatch_exec_report: %s", exc)

    # ------------------------------------------------------------------
    # SmartOrderRouter integration hook
    # ------------------------------------------------------------------

    def route_hook(self) -> Callable[[dict[str, Any]], Any]:
        """
        Returns a coroutine factory compatible with SmartOrderRouter.

        Usage in smart_router.py:
            fix_adapter = FIXAdapter(...)
            router.add_broker("fix", fix_adapter.route_hook())
        """

        async def _route(order_dict: dict[str, Any]) -> dict[str, Any]:
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
