# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
utils/yfinance_compat.py
========================
yfinance compatibility helpers — suppress known noisy warnings and provide
a robust download wrapper with automatic fallback for GC=F gold futures.

GC=F (CME front-month gold futures) rolls quarterly. During the roll window
yfinance may return empty data and emit "possibly delisted" UserWarnings.
This module:
  1. Suppresses those warnings globally via Python's warnings module.
  2. Silences the yfinance logger (it also logs via logging, not just warnings).
  3. Provides ``safe_download()`` — a drop-in for ``yf.download()`` that
     automatically falls back to GLD (SPDR Gold ETF) when GC=F is empty.

Usage
-----
    from utils.yfinance_compat import safe_download, suppress_yfinance_warnings

    suppress_yfinance_warnings()   # call once at module level
    df = safe_download("GC=F", start="2024-01-01", interval="1d")
"""

from __future__ import annotations

import logging
import warnings
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# ── Ticker fallback map ───────────────────────────────────────────────────────
# When a primary ticker returns empty data, try these in order.
_FALLBACKS: dict[str, list[str]] = {
    "GC=F": ["GLD", "IAU"],  # gold futures → SPDR Gold ETF → iShares Gold ETF
    "SI=F": ["SLV"],  # silver futures → iShares Silver ETF
    "CL=F": ["USO"],  # crude oil futures → US Oil Fund ETF
    "NG=F": ["UNG"],  # natural gas futures → US Natural Gas Fund ETF
    "ZC=F": ["CORN"],  # corn futures → Teucrium Corn ETF
    "ZW=F": ["WEAT"],  # wheat futures → Teucrium Wheat ETF
}

_SUPPRESSED = False


def suppress_yfinance_warnings() -> None:
    """
    Suppress yfinance "possibly delisted" and related warnings globally.

    Safe to call multiple times — idempotent.
    """
    global _SUPPRESSED
    if _SUPPRESSED:
        return

    # Python warnings module — catches warnings raised via warnings.warn()
    warnings.filterwarnings("ignore", message=".*possibly delisted.*", category=UserWarning)
    warnings.filterwarnings("ignore", message=".*No price data found.*", category=UserWarning)
    warnings.filterwarnings("ignore", message=".*Period.*not supported.*", category=UserWarning)
    warnings.filterwarnings("ignore", message=".*auto_adjust.*", category=FutureWarning)
    warnings.filterwarnings("ignore", message=".*actions.*", category=FutureWarning)

    # yfinance logs "possibly delisted" and roll-window errors at ERROR level
    # via the logging module. Silence all yfinance sub-loggers to CRITICAL so
    # only genuine fatal errors surface. Our own fallback logic logs the
    # outcome at INFO/WARNING level with actionable context.
    for _name in (
        "yfinance",
        "yfinance.base",
        "yfinance.utils",
        "yfinance.ticker",
        "yfinance.multi",
        "yfinance.scrapers.history",
        "yfinance.scrapers.quote",
        "yfinance.scrapers.fundamentals",
        "yfinance.cache",
        "peewee",  # yfinance uses peewee for its SQLite cache
    ):
        logging.getLogger(_name).setLevel(logging.CRITICAL)

    _SUPPRESSED = True


def safe_download(
    ticker: str,
    *,
    start: str | None = None,
    end: str | None = None,
    interval: str = "1d",
    auto_adjust: bool = True,
    progress: bool = False,
    **kwargs: Any,
) -> pd.DataFrame:
    """
    Download OHLCV data from Yahoo Finance with automatic fallback.

    For tickers in ``_FALLBACKS`` (e.g. GC=F), if the primary ticker returns
    empty data the function tries each fallback in order. This handles the
    quarterly CME futures roll window transparently.

    Parameters
    ----------
    ticker : str
        Primary Yahoo Finance ticker symbol.
    start, end : str, optional
        Date range strings (YYYY-MM-DD). Passed directly to yf.download().
    interval : str
        Bar interval: '1m', '5m', '15m', '30m', '1h', '1d', '1wk', '1mo'.
    auto_adjust : bool
        Adjust OHLCV for splits and dividends (default True).
    progress : bool
        Show download progress bar (default False — keeps terminal clean).
    **kwargs
        Additional keyword arguments forwarded to yf.download().

    Returns
    -------
    pd.DataFrame
        OHLCV DataFrame with lowercase column names, or empty DataFrame if
        all tickers (primary + fallbacks) return no data.
    """
    suppress_yfinance_warnings()

    try:
        import yfinance as yf
    except ImportError as exc:
        raise ImportError("yfinance is not installed — pip install yfinance") from exc

    tickers_to_try = [ticker] + _FALLBACKS.get(ticker, [])

    for t in tickers_to_try:
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=UserWarning)
                warnings.filterwarnings("ignore", category=FutureWarning)
                df = yf.download(
                    t,
                    start=start,
                    end=end,
                    interval=interval,
                    auto_adjust=auto_adjust,
                    progress=progress,
                    **kwargs,
                )

            if df is None or df.empty:
                if t != ticker:
                    logger.info("yfinance: %s empty — tried fallback %s (also empty)", ticker, t)
                else:
                    logger.debug("yfinance: %s returned empty data — trying fallbacks", ticker)
                continue

            # Flatten MultiIndex columns (yfinance ≥0.2.x)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [col[0].lower() for col in df.columns]
            else:
                df.columns = [c.lower() for c in df.columns]

            if t != ticker:
                logger.info("yfinance: %s empty (roll window?) — using fallback %s (%d bars)", ticker, t, len(df))
            else:
                logger.debug("yfinance: downloaded %d bars for %s", len(df), ticker)

            return df

        except Exception as exc:
            logger.debug("yfinance: download failed for %s: %s", t, exc)
            continue

    logger.warning("yfinance: all tickers exhausted for %s — returning empty DataFrame", ticker)
    return pd.DataFrame()


# Apply suppression at import time so any module that imports this file
# immediately benefits without needing to call suppress_yfinance_warnings().
suppress_yfinance_warnings()
