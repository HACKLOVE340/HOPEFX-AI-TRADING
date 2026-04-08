# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
monitoring/trade_logger.py
==========================
Persistent paper-trading logger.

Writes every fill, slippage measurement, and equity snapshot to:
  - Daily CSV files in LOG_DIR (default: logs/paper_trading/)
  - Prometheus gauges (scraped by /metrics endpoint)

CSV files
---------
  fills_YYYY-MM-DD.csv      — one row per fill
  equity_YYYY-MM-DD.csv     — one row per equity snapshot (written every N seconds)

Prometheus metrics
------------------
  hopefx_equity_usd          — current equity (gauge)
  hopefx_balance_usd         — current balance (gauge)
  hopefx_daily_pnl_usd       — today's realised P&L (gauge)
  hopefx_total_fills         — total fills since process start (counter)
  hopefx_avg_slippage_pips   — rolling average slippage in pips (gauge)
  hopefx_open_positions      — number of open positions (gauge)
  hopefx_drawdown_pct        — current drawdown % from HWM (gauge)

Usage
-----
    from monitoring.trade_logger import get_trade_logger

    logger = get_trade_logger()

    # On each fill:
    logger.log_fill(
        symbol="XAUUSD", side="BUY", lots=0.01,
        requested_price=2341.5, fill_price=2341.8,
        pnl=0.0, broker="oanda",
    )

    # On each equity update (call from main loop):
    logger.log_equity(equity=10420.0, balance=10400.0, open_positions=1)

    # Prometheus metrics are updated automatically on each log call.
"""

from __future__ import annotations

import csv
import logging
import os
import threading
import time
from datetime import datetime, timezone

UTC = timezone.utc
from pathlib import Path

logger = logging.getLogger(__name__)

_LOG_DIR = Path(os.getenv("PAPER_TRADE_LOG_DIR", "logs/paper_trading"))
_EQUITY_SNAPSHOT_INTERVAL = float(os.getenv("EQUITY_SNAPSHOT_INTERVAL_S", "60"))


# ── Prometheus metrics ────────────────────────────────────────────────────────


def _init_prometheus():
    """Initialise Prometheus gauges/counters. Returns metric objects or empty dict.

    Returns an empty dict when prometheus_client is unavailable or registration
    fails. Callers must guard metric access with ``if _PROM.get('equity')``.
    A warning is always logged so missing metrics are visible in logs.
    """
    try:
        from prometheus_client import Counter, Gauge

        equity_gauge = Gauge("hopefx_equity_usd", "Current floating equity (USD)")
        balance_gauge = Gauge("hopefx_balance_usd", "Current closed balance (USD)")
        daily_pnl_gauge = Gauge("hopefx_daily_pnl_usd", "Today's realised P&L (USD)")
        fills_counter = Counter("hopefx_total_fills", "Total fills since process start")
        slippage_gauge = Gauge("hopefx_avg_slippage_pips", "Rolling average slippage (pips)")
        positions_gauge = Gauge("hopefx_open_positions", "Number of open positions")
        drawdown_gauge = Gauge("hopefx_drawdown_pct", "Current drawdown % from HWM")
        return {
            "equity": equity_gauge,
            "balance": balance_gauge,
            "daily_pnl": daily_pnl_gauge,
            "fills": fills_counter,
            "slippage": slippage_gauge,
            "positions": positions_gauge,
            "drawdown": drawdown_gauge,
        }
    except ImportError:
        logger.warning(
            "prometheus_client is not installed — trade metrics will not be exported. "
            "Install with: pip install prometheus-client"
        )
        return {}
    except Exception as exc:
        logger.warning(
            "Prometheus trade metrics registration failed (%s) — metrics will not be "
            "exported. This may indicate a duplicate metric name or registry conflict.",
            exc,
        )
        return {}


# ── CSV helpers ───────────────────────────────────────────────────────────────

_FILL_HEADERS = [
    "timestamp",
    "symbol",
    "side",
    "lots",
    "requested_price",
    "fill_price",
    "slippage_pips",
    "slippage_usd",
    "pnl",
    "broker",
    "order_id",
    "notes",
]

_EQUITY_HEADERS = [
    "timestamp",
    "equity",
    "balance",
    "daily_pnl",
    "open_positions",
    "drawdown_pct",
]


def _today_str() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _append_csv(path: Path, headers: list, row: dict) -> None:
    """Append one row to a CSV file, writing headers if the file is new."""
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists() or path.stat().st_size == 0
    with Path(path).open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerow(row)


# ── TradeLogger ───────────────────────────────────────────────────────────────


class TradeLogger:
    """
    Thread-safe paper-trading logger.

    Writes fills and equity snapshots to daily CSV files and updates
    Prometheus gauges on every call.
    """

    def __init__(self, log_dir: Path = _LOG_DIR) -> None:
        self._log_dir = log_dir
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._metrics = _init_prometheus()
        self._lock = threading.Lock()

        # Rolling slippage tracking (last 100 fills)
        self._slippage_history: list[float] = []
        self._slippage_maxlen = 100

        # Equity state
        self._equity: float = 0.0
        self._balance: float = 0.0
        self._daily_pnl: float = 0.0
        self._open_positions: int = 0
        self._drawdown_pct: float = 0.0
        self._hwm: float = 0.0

        # Fill count
        self._fill_count: int = 0

        # Sharpe progress tracking toward N=250 (SE ≤ ±0.3)
        # Only closed fills with non-zero PnL count as "trades" for Sharpe SE.
        # SE formula: 1 / sqrt(2 * (N - 1))  — valid for iid trade returns.
        # At N=250: SE = 1/sqrt(498) ≈ ±0.045 (robust).
        # At N=48:  SE = 1/sqrt(94)  ≈ ±0.103 (current state).
        self._trade_pnls: list[float] = []  # net PnL per closed trade
        self._sharpe_target_n: int = 250  # target sample size

        logger.info("TradeLogger initialised — log_dir=%s", self._log_dir)

    # ── Fill logging ──────────────────────────────────────────────────────────

    def log_fill(
        self,
        symbol: str,
        side: str,
        lots: float,
        requested_price: float,
        fill_price: float,
        pnl: float = 0.0,
        broker: str = "paper",
        order_id: str = "",
        pip_size: float | None = None,
        notes: str = "",
    ) -> None:
        """
        Record a fill with slippage calculation.

        Slippage = fill_price - requested_price (positive = adverse for buys,
        negative = adverse for sells). Converted to pips using pip_size.

        Parameters
        ----------
        symbol          : Instrument symbol (e.g. "XAUUSD")
        side            : "BUY" or "SELL"
        lots            : Position size in lots
        requested_price : Price at signal generation time
        fill_price      : Actual execution price
        pnl             : Realised P&L of this fill (0 for opening fills)
        broker          : Broker name for attribution
        order_id        : Broker order ID
        pip_size        : Pip size for slippage conversion (default 0.0001)
        notes           : Free-text notes
        """
        # Slippage: positive = adverse (paid more than requested)
        raw_slip = fill_price - requested_price
        if side.upper() == "SELL":
            raw_slip = -raw_slip  # adverse for sells is fill < requested

        # Auto-detect pip size when not provided:
        # XAU/Gold: 0.01 (price ~2300, 1 pip = $0.01)
        # JPY pairs: 0.01
        # BTC/crypto: 1.0
        # Standard forex: 0.0001
        if not pip_size:
            sym_upper = symbol.upper()
            if "XAU" in sym_upper or "XAG" in sym_upper or "JPY" in sym_upper:
                pip_size = 0.01
            elif "BTC" in sym_upper or "ETH" in sym_upper:
                pip_size = 1.0
            else:
                pip_size = 0.0001
        slippage_pips = raw_slip / pip_size if pip_size > 0 else 0.0
        slippage_usd = raw_slip * lots * 100_000  # approximate for forex

        ts = datetime.now(UTC).isoformat()
        row = {
            "timestamp": ts,
            "symbol": symbol,
            "side": side.upper(),
            "lots": lots,
            "requested_price": requested_price,
            "fill_price": fill_price,
            "slippage_pips": round(slippage_pips, 4),
            "slippage_usd": round(slippage_usd, 4),
            "pnl": round(pnl, 4),
            "broker": broker,
            "order_id": order_id,
            "notes": notes,
        }

        today = _today_str()
        csv_path = self._log_dir / f"fills_{today}.csv"

        with self._lock:
            _append_csv(csv_path, _FILL_HEADERS, row)
            self._fill_count += 1

            # Track closed trades (non-zero PnL) for Sharpe SE progress
            if pnl != 0.0:
                self._trade_pnls.append(pnl)

            # Update rolling slippage
            self._slippage_history.append(slippage_pips)
            if len(self._slippage_history) > self._slippage_maxlen:
                self._slippage_history.pop(0)
            avg_slip = sum(self._slippage_history) / len(self._slippage_history)

        # Update Prometheus
        m = self._metrics
        if "fills" in m:
            m["fills"].inc()
        if "slippage" in m:
            m["slippage"].set(avg_slip)

        logger.info(
            "Fill logged: %s %s %.2f lots @ %.5f (slip=%.2f pips, pnl=%.2f)",
            side,
            symbol,
            lots,
            fill_price,
            slippage_pips,
            pnl,
        )

    # ── Equity snapshot ───────────────────────────────────────────────────────

    def log_equity(
        self,
        equity: float,
        balance: float | None = None,
        daily_pnl: float | None = None,
        open_positions: int = 0,
    ) -> None:
        """
        Record an equity snapshot.

        Called from the main trading loop (e.g. every 60 seconds or on each bar).
        Updates Prometheus gauges and appends to the daily equity CSV.

        Parameters
        ----------
        equity          : Floating equity (open P&L included)
        balance         : Closed balance (defaults to equity)
        daily_pnl       : Today's realised P&L (computed from balance if not given)
        open_positions  : Number of open positions
        """
        if balance is None:
            balance = equity

        # Update trailing HWM for drawdown calculation
        with self._lock:
            self._hwm = max(self._hwm, equity)
            drawdown_pct = (self._hwm - equity) / self._hwm * 100 if self._hwm > 0 else 0.0
            self._equity = equity
            self._balance = balance
            self._daily_pnl = daily_pnl if daily_pnl is not None else (balance - self._balance)
            self._open_positions = open_positions
            self._drawdown_pct = drawdown_pct

        ts = datetime.now(UTC).isoformat()
        row = {
            "timestamp": ts,
            "equity": round(equity, 4),
            "balance": round(balance, 4),
            "daily_pnl": round(self._daily_pnl, 4),
            "open_positions": open_positions,
            "drawdown_pct": round(drawdown_pct, 4),
        }

        today = _today_str()
        csv_path = self._log_dir / f"equity_{today}.csv"
        with self._lock:
            _append_csv(csv_path, _EQUITY_HEADERS, row)

        # Update Prometheus
        m = self._metrics
        if "equity" in m:
            m["equity"].set(equity)
        if "balance" in m:
            m["balance"].set(balance)
        if "daily_pnl" in m:
            m["daily_pnl"].set(self._daily_pnl)
        if "positions" in m:
            m["positions"].set(open_positions)
        if "drawdown" in m:
            m["drawdown"].set(drawdown_pct)

        logger.debug(
            "Equity snapshot: equity=%.2f balance=%.2f dd=%.2f%% positions=%d",
            equity,
            balance,
            drawdown_pct,
            open_positions,
        )

    # ── Background equity snapshotter ─────────────────────────────────────────

    def start_equity_snapshotter(self, get_equity_fn, interval: float = _EQUITY_SNAPSHOT_INTERVAL) -> threading.Thread:
        """
        Start a background thread that calls get_equity_fn() every `interval` seconds
        and logs the result.

        Parameters
        ----------
        get_equity_fn : Callable that returns dict with keys:
                        equity, balance, daily_pnl, open_positions
        interval      : Snapshot interval in seconds (default: EQUITY_SNAPSHOT_INTERVAL_S)

        Returns the daemon thread (already started).
        """

        def _loop():
            logger.info("Equity snapshotter started (interval=%.0fs)", interval)
            while True:
                try:
                    data = get_equity_fn()
                    if data:
                        self.log_equity(
                            equity=float(data.get("equity", 0)),
                            balance=float(data.get("balance", data.get("equity", 0))),
                            daily_pnl=data.get("daily_pnl"),
                            open_positions=int(data.get("open_positions", 0)),
                        )
                except Exception as exc:
                    logger.warning("Equity snapshotter error: %s", exc)
                time.sleep(interval)

        t = threading.Thread(target=_loop, daemon=True, name="equity-snapshotter")
        t.start()
        return t

    # ── Sharpe SE progress ────────────────────────────────────────────────────

    def sharpe_progress(self) -> dict:
        """
        Return Sharpe standard-error progress toward N=250.

        SE formula: 1 / sqrt(2 * (N - 1))  — valid for iid trade returns.

        Milestones
        ----------
        N=48  (current) → SE ≈ ±0.103
        N=100           → SE ≈ ±0.071
        N=250 (target)  → SE ≈ ±0.045  (robust threshold)

        Returns
        -------
        dict with keys:
          trade_count   : int   — closed trades with non-zero PnL
          n_needed      : int   — trades still needed to reach target
          sharpe_se     : float — current SE (lower = more reliable)
          target_n      : int   — target sample size (250)
          target_se     : float — SE at target N
          pct_complete  : float — progress toward target (0–100)
          sharpe        : float — current trade-level Sharpe (0 if N < 2)
        """
        import math

        with self._lock:
            pnls = list(self._trade_pnls)
            target_n = self._sharpe_target_n

        n = len(pnls)
        se = 1.0 / math.sqrt(2.0 * max(n - 1, 1)) if n >= 2 else float("inf")
        target_se = 1.0 / math.sqrt(2.0 * (target_n - 1))
        n_needed = max(0, target_n - n)
        pct_complete = min(100.0, n / target_n * 100.0)

        # Trade-level Sharpe: mean(pnl) / std(pnl) * sqrt(252)
        sharpe = 0.0
        if n >= 2:
            import statistics

            mean_pnl = statistics.mean(pnls)
            std_pnl = statistics.stdev(pnls)
            if std_pnl > 0:
                sharpe = round(mean_pnl / std_pnl * (252**0.5), 3)

        return {
            "trade_count": n,
            "n_needed": n_needed,
            "sharpe_se": round(se, 4) if se != float("inf") else None,
            "target_n": target_n,
            "target_se": round(target_se, 4),
            "pct_complete": round(pct_complete, 1),
            "sharpe": sharpe,
        }

    # ── Stats ─────────────────────────────────────────────────────────────────

    @property
    def stats(self) -> dict:
        with self._lock:
            avg_slip = sum(self._slippage_history) / len(self._slippage_history) if self._slippage_history else 0.0
        sp = self.sharpe_progress()
        return {
            "fill_count": self._fill_count,
            "avg_slippage_pips": round(avg_slip, 4),
            "equity": self._equity,
            "balance": self._balance,
            "daily_pnl": self._daily_pnl,
            "open_positions": self._open_positions,
            "drawdown_pct": round(self._drawdown_pct, 4),
            "hwm": self._hwm,
            "log_dir": str(self._log_dir),
            # Sharpe SE progress
            "trade_count": sp["trade_count"],
            "sharpe_se": sp["sharpe_se"],
            "sharpe": sp["sharpe"],
            "n_needed_for_robust_sharpe": sp["n_needed"],
            "sharpe_pct_complete": sp["pct_complete"],
        }


# ── Module-level singleton ────────────────────────────────────────────────────
_trade_logger: TradeLogger | None = None
_tl_lock = threading.Lock()


def get_trade_logger(log_dir: Path | None = None) -> TradeLogger:
    """Return the module-level TradeLogger singleton (thread-safe)."""
    global _trade_logger
    if _trade_logger is None:
        with _tl_lock:
            if _trade_logger is None:
                _trade_logger = TradeLogger(log_dir=log_dir or _LOG_DIR)
    return _trade_logger
