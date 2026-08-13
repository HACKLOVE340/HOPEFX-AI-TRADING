# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
data_feed/sources/yfinance_source.py
=====================================
yFinance tick-source adapter.

Fetches the latest price for a symbol using the yfinance library.
No API key required.  Rate limit: ~2000 req/hour per IP.

The adapter runs yfinance.download() in a thread-pool executor so the
async event loop is never blocked by the synchronous yfinance HTTP call.

Symbol mapping is driven by the ``yfinance_ticker`` field in
config/multi_source_feed.yaml (e.g. XAUUSD → "GC=F").
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

# yfinance is a [CORE] dependency — always available.
try:
    import yfinance as _yf  # type: ignore

    _YF_AVAILABLE = True
except ImportError:
    _yf = None  # type: ignore
    _YF_AVAILABLE = False
    logger.warning("yfinance not installed — YFinanceSource unavailable. pip install yfinance")


class YFinanceSource:
    """
    yFinance REST adapter.

    Parameters
    ----------
    period:
        yfinance download period (default ``"1d"``).
    interval:
        yfinance bar interval (default ``"1m"``).
    """

    name: str = "yfinance"

    def __init__(self, period: str = "1d", interval: str = "1m") -> None:
        self._period = period
        self._interval = interval

    def can_serve(self, symbol: str, cfg: dict[str, Any]) -> bool:
        """Whether this source could price *symbol* at all — no I/O.

        A blank ``yfinance_ticker`` is a deliberate configuration fact (Yahoo
        delisted spot metals), not an outage. The caller uses this to SKIP the
        source rather than call fetch() and treat the None as a failure.
        """
        if not _YF_AVAILABLE:
            return False
        return bool(cfg.get("yfinance_ticker"))

    async def fetch(self, symbol: str, cfg: dict[str, Any]) -> float | None:
        """
        Return the latest mid price for *symbol* or None on failure.

        Parameters
        ----------
        symbol:
            Canonical symbol (e.g. ``"XAUUSD"``).
        cfg:
            Symbol config dict from multi_source_feed.yaml — must contain
            ``yfinance_ticker``.
        """
        if not _YF_AVAILABLE:
            return None

        ticker = cfg.get("yfinance_ticker", "")
        if not ticker:
            logger.warning("YFinanceSource: no yfinance_ticker configured for %s", symbol)
            return None

        loop = asyncio.get_running_loop()
        try:
            price = await loop.run_in_executor(None, self._sync_fetch, ticker)
            return price
        except Exception as exc:
            logger.warning("YFinanceSource[%s]: fetch error: %s", symbol, exc)
            return None

    def _sync_fetch(self, ticker: str) -> float | None:
        """Blocking yfinance call — runs in thread-pool executor."""
        try:
            data = _yf.download(
                ticker,
                period=self._period,
                interval=self._interval,
                progress=False,
                auto_adjust=True,
                # Suppress the multi-level column warning introduced in yfinance 0.2.38
                multi_level_index=False,
            )
            if data is None or data.empty:
                logger.debug("YFinanceSource[%s]: empty DataFrame returned", ticker)
                return None

            # Use the last Close price as the mid price.
            close_col = "Close"
            if close_col not in data.columns:
                # Fallback: try the first numeric column.
                numeric_cols = data.select_dtypes("number").columns.tolist()
                if not numeric_cols:
                    return None
                close_col = numeric_cols[0]

            last_close = float(data[close_col].dropna().iloc[-1])
            if last_close <= 0:
                return None
            return last_close
        except Exception as exc:
            logger.warning("YFinanceSource._sync_fetch[%s]: %s", ticker, exc)
            return None

    async def close(self) -> None:
        """No persistent connection to close."""

    def status(self) -> dict[str, Any]:
        return {
            "source": self.name,
            "available": _YF_AVAILABLE,
            "period": self._period,
            "interval": self._interval,
        }
