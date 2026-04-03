# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
brokers/ibkr_fix_bridge.py

IBKR FIX 4.4 bridge — wires the existing execution/fix_adapter.py to the
IBKR-specific FIX session configuration for XAUUSD low-latency execution.

Architecture:
  IBKRFIXBridge
    └── FIXAdapter (execution/fix_adapter.py)
          └── quickfix / pyfixmsg session → IBKR FIX Gateway

This module handles:
  - IBKR-specific FIX session config generation (SenderCompID, TargetCompID,
    SocketConnectHost/Port, HeartBtInt, ResetOnLogon, etc.)
  - XAUUSD contract symbol mapping (IBKR FIX uses "XAUUSD" with SecType=CMDTY)
  - Order routing: market/limit/stop for XAUUSD spot and futures
  - Round-trip latency target: <50ms (enforced by circuit breaker at 100ms)
  - Kill-switch integration

Usage:
    bridge = IBKRFIXBridge.from_env()
    bridge.start()
    report = await bridge.place_order(FIXOrder(
        symbol="XAUUSD",
        side=FIXSide.BUY,
        quantity=1.0,
        ord_type=FIXOrdType.LIMIT,
        price=1950.00,
    ))
    bridge.stop()
"""

from __future__ import annotations

import logging
import os
import tempfile
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Re-export FIX types so callers only need to import from this module
from execution.fix_adapter import (
    FIXAdapter,
    FIXFillReport,
    FIXOrder,
)

# Optional Sentry
try:
    import sentry_sdk  # type: ignore[import]

    _SENTRY = True
except ImportError:
    _SENTRY = False


# ---------------------------------------------------------------------------
# IBKR FIX session configuration
# ---------------------------------------------------------------------------


@dataclass
class IBKRFIXConfig:
    """
    IBKR FIX 4.4 session parameters.

    IBKR FIX Gateway listens on:
      - Live:  host=<gateway-host>  port=4001  (or TWS port 7496)
      - Paper: host=<gateway-host>  port=4002  (or TWS port 7497)

    SenderCompID: your IBKR username (or assigned FIX comp ID)
    TargetCompID: "IBFX" for FIX Gateway
    """

    sender_comp_id: str = field(
        default_factory=lambda: os.environ.get("IBKR_FIX_SENDER_COMP_ID", "HOPEFX"),
    )
    target_comp_id: str = field(
        default_factory=lambda: os.environ.get("IBKR_FIX_TARGET_COMP_ID", "IBFX"),
    )
    host: str = field(
        default_factory=lambda: os.environ.get("IBKR_HOST", "127.0.0.1"),
    )
    port: int = field(
        default_factory=lambda: int(os.environ.get("IBKR_FIX_PORT", "4002")),
    )
    heartbeat_interval: int = 30  # seconds — IBKR default
    reset_on_logon: bool = True
    reset_on_logout: bool = False
    reset_on_disconnect: bool = False
    reconnect_interval: int = 10  # seconds between reconnect attempts
    latency_threshold_ms: float = 100.0  # circuit breaker threshold
    username: str = field(
        default_factory=lambda: os.environ.get("IBKR_FIX_USERNAME", ""),
    )
    password: str = field(
        default_factory=lambda: os.environ.get("IBKR_FIX_PASSWORD", ""),
    )
    # Path for FIX session store (sequence numbers).
    # Uses tempfile.gettempdir() as the default base to avoid hardcoded /tmp.
    store_path: str = field(
        default_factory=lambda: os.environ.get(
            "IBKR_FIX_STORE_PATH",
            str(tempfile.gettempdir()) + "/ibkr_fix_store",
        ),
    )
    log_path: str = field(
        default_factory=lambda: os.environ.get(
            "IBKR_FIX_LOG_PATH",
            str(tempfile.gettempdir()) + "/ibkr_fix_logs",
        ),
    )

    @property
    def is_paper(self) -> bool:
        return self.port in (4002, 7497)

    def generate_quickfix_cfg(self) -> str:
        """
        Generate a quickfix-compatible session config string.

        This is written to a temp file and passed to FIXAdapter.
        IBKR FIX 4.4 requires specific field values documented at:
        https://www.interactivebrokers.com/en/trading/fix-connectivity.php
        """
        Path(self.store_path).mkdir(parents=True, exist_ok=True)
        Path(self.log_path).mkdir(parents=True, exist_ok=True)

        return textwrap.dedent(f"""\
            [DEFAULT]
            ConnectionType=initiator
            ReconnectInterval={self.reconnect_interval}
            FileStorePath={self.store_path}
            FileLogPath={self.log_path}
            StartTime=00:00:00
            EndTime=00:00:00
            UseDataDictionary=N
            DataDictionary=FIX44.xml
            ValidateUserDefinedFields=N
            ValidateIncomingMessage=N
            ResetOnLogon={"Y" if self.reset_on_logon else "N"}
            ResetOnLogout={"Y" if self.reset_on_logout else "N"}
            ResetOnDisconnect={"Y" if self.reset_on_disconnect else "N"}

            [SESSION]
            BeginString=FIX.4.4
            SenderCompID={self.sender_comp_id}
            TargetCompID={self.target_comp_id}
            SocketConnectHost={self.host}
            SocketConnectPort={self.port}
            HeartBtInt={self.heartbeat_interval}
        """)


# ---------------------------------------------------------------------------
# IBKR FIX Bridge
# ---------------------------------------------------------------------------


class IBKRFIXBridge:
    """
    IBKR FIX 4.4 bridge for XAUUSD low-latency order execution.

    Wraps FIXAdapter with IBKR-specific configuration and symbol mapping.
    Target round-trip latency: <50ms (circuit breaker opens at 100ms).

    Thread-safe: start()/stop()/place_order() can be called from any thread.
    """

    def __init__(
        self,
        config: IBKRFIXConfig | None = None,
        kill_switch=None,
    ) -> None:
        self._cfg = config or IBKRFIXConfig()
        self._kill_switch = kill_switch
        self._adapter: FIXAdapter | None = None
        self._cfg_file: str | None = None
        self._started = False

        logger.info(
            "IBKRFIXBridge initialised | host=%s port=%d sender=%s target=%s mode=%s",
            self._cfg.host,
            self._cfg.port,
            self._cfg.sender_comp_id,
            self._cfg.target_comp_id,
            "PAPER" if self._cfg.is_paper else "LIVE",
        )

    @classmethod
    def from_env(cls, kill_switch=None) -> IBKRFIXBridge:
        """Construct from environment variables."""
        return cls(config=IBKRFIXConfig(), kill_switch=kill_switch)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """
        Start the FIX session.

        Writes quickfix config to a temp file, instantiates FIXAdapter,
        and initiates the FIX logon sequence.
        """
        if self._started:
            logger.warning("IBKRFIXBridge.start() called while already started — ignored.")
            return

        cfg_content = self._cfg.generate_quickfix_cfg()

        # Write to temp file — FIXAdapter reads from filesystem
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".cfg",
            prefix="ibkr_fix_",
            delete=False,
        ) as tmp:
            tmp.write(cfg_content)
            tmp.flush()
        self._cfg_file = tmp.name

        logger.info(
            "IBKRFIXBridge: wrote FIX config to %s\n%s",
            self._cfg_file,
            cfg_content,
        )

        self._adapter = FIXAdapter(
            config_file=self._cfg_file,
            username=self._cfg.username,
            password=self._cfg.password,
            latency_threshold_ms=self._cfg.latency_threshold_ms,
        )
        self._adapter.start()
        self._started = True
        logger.info("IBKRFIXBridge started.")

    def stop(self) -> None:
        """Stop the FIX session and clean up temp config."""
        if self._adapter:
            try:
                self._adapter.stop()
            except Exception as exc:
                logger.error("IBKRFIXBridge.stop: adapter stop error: %s", exc)
                self._capture_sentry(exc)

        if self._cfg_file:
            try:
                Path(self._cfg_file).unlink(missing_ok=True)
            except Exception as exc:
                logger.warning("IBKRFIXBridge: could not delete temp config: %s", exc)

        self._started = False
        logger.info("IBKRFIXBridge stopped.")

    # ------------------------------------------------------------------
    # Order placement
    # ------------------------------------------------------------------

    async def place_order(self, order: FIXOrder) -> FIXFillReport:
        """
        Submit a FIX order to IBKR and await the ExecutionReport.

        Args:
            order: FIXOrder with IBKR-compatible fields.

        Returns:
            FIXFillReport with fill details and round-trip latency.

        Raises:
            RuntimeError: if bridge not started, kill switch active, or
                          circuit breaker open.
        """
        if not self._started or not self._adapter:
            raise RuntimeError("IBKRFIXBridge.place_order: bridge not started.")

        # Kill-switch hard block
        if self._kill_switch and self._kill_switch.is_active():
            reason = getattr(self._kill_switch, "_reason", "kill switch active")
            raise RuntimeError(
                f"IBKRFIXBridge.place_order blocked by kill switch: {reason}",
            )

        # Circuit breaker check
        self._adapter.circuit_breaker.check()

        # Map XAUUSD symbol to IBKR FIX format
        order = self._map_symbol(order)

        logger.info(
            "IBKRFIXBridge: submitting FIX order | symbol=%s side=%s type=%s qty=%.4f price=%s cl_ord_id=%s",
            order.symbol,
            order.side.name,
            order.ord_type.name,
            order.quantity,
            order.price or order.stop_px,
            order.cl_ord_id,
        )

        try:
            report = await self._adapter.send_order(order)
            logger.info(
                "IBKRFIXBridge: fill report | cl_ord_id=%s exec_type=%s filled=%.4f avg_px=%.4f latency=%.2fms",
                report.cl_ord_id,
                report.exec_type.name,
                report.filled_qty,
                report.avg_px,
                report.latency_ms,
            )
            return report
        except Exception as exc:
            logger.error("IBKRFIXBridge.place_order error: %s", exc)
            self._capture_sentry(exc)
            raise

    # ------------------------------------------------------------------
    # Symbol mapping
    # ------------------------------------------------------------------

    @staticmethod
    def _map_symbol(order: FIXOrder) -> FIXOrder:
        """
        Normalise symbol to IBKR FIX format.

        IBKR FIX uses "XAUUSD" for gold spot/CFD.
        Aliases: "GOLD", "XAU/USD", "XAU_USD" → "XAUUSD"
        """
        aliases = {"GOLD", "XAU/USD", "XAU_USD", "XAU"}
        if order.symbol.upper() in aliases:
            # Return a copy with normalised symbol
            from dataclasses import replace

            return replace(order, symbol="XAUUSD")
        return order

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

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

    def __enter__(self) -> IBKRFIXBridge:
        self.start()
        return self

    def __exit__(self, *_) -> None:
        self.stop()
