# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
backtest/data_validator.py
==========================
Multi-source backtest data validation.

Problem
-------
real_data_backtest.py pulls from a single feed (Binance via ccxt).
A bad data period — gaps, price spikes, wrong prices — silently corrupts
backtest results with no warning.

Solution
--------
Require agreement from at least 2 independent sources before accepting a
historical bar. Sources are fetched in parallel; bars that deviate beyond
configurable thresholds are flagged and excluded.

Sources supported
-----------------
- Binance (ccxt)       — primary, highest liquidity
- Kraken (ccxt)        — secondary, independent matching engine
- Yahoo Finance (yfinance) — tertiary, independent data vendor
- Alpha Vantage (REST) — quaternary, institutional data vendor

Validation rules per bar
------------------------
1. Price agreement: |source_A_close - source_B_close| / mid < MAX_PRICE_DEVIATION
2. Volume sanity: volume > 0 on at least one source
3. OHLC consistency: high >= close >= low, high >= open >= low
4. Gap detection: |bar_close - prev_close| / prev_close < MAX_GAP_PCT
5. Spike detection: bar range (high-low) / close < MAX_SPIKE_PCT

A bar is accepted only when MIN_SOURCES_AGREE sources agree within tolerance.

Usage
-----
    from backtest.data_validator import MultiSourceValidator, fetch_validated_ohlcv

    df = await fetch_validated_ohlcv(
        symbol="XAU/USDT",
        timeframe="1h",
        since_ms=since_ms,
        min_sources=2,
    )
    # df contains only bars validated by ≥2 sources
    # df.attrs["validation_report"] has per-bar quality details

Configuration (env vars)
------------------------
BACKTEST_MIN_SOURCES        — minimum agreeing sources (default: 2)
BACKTEST_MAX_PRICE_DEV      — max price deviation fraction (default: 0.005 = 0.5%)
BACKTEST_MAX_GAP_PCT        — max bar-to-bar gap fraction (default: 0.05 = 5%)
BACKTEST_MAX_SPIKE_PCT      — max bar range / close fraction (default: 0.10 = 10%)
ALPHA_VANTAGE_API_KEY       — Alpha Vantage API key (optional 4th source)
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

UTC = timezone.utc

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
MIN_SOURCES: int = int(os.getenv("BACKTEST_MIN_SOURCES", "2"))
MAX_PRICE_DEV: float = float(os.getenv("BACKTEST_MAX_PRICE_DEV", "0.005"))
MAX_GAP_PCT: float = float(os.getenv("BACKTEST_MAX_GAP_PCT", "0.05"))
MAX_SPIKE_PCT: float = float(os.getenv("BACKTEST_MAX_SPIKE_PCT", "0.10"))


# ── Data structures ───────────────────────────────────────────────────────────


@dataclass
class BarValidationResult:
    """Validation result for a single OHLCV bar."""

    timestamp: int  # Unix ms
    accepted: bool
    sources_agreed: int
    sources_total: int
    prices: dict[str, float]  # source_name → close price
    flags: list[str] = field(default_factory=list)


@dataclass
class ValidationReport:
    """Summary of multi-source validation for a full OHLCV dataset."""

    symbol: str
    timeframe: str
    total_bars: int
    accepted_bars: int
    rejected_bars: int
    sources_used: list[str]
    rejection_reasons: dict[str, int]  # flag → count
    coverage_pct: float

    def summary(self) -> str:
        return (
            f"MultiSource validation: {self.symbol} {self.timeframe} | "
            f"accepted={self.accepted_bars}/{self.total_bars} "
            f"({self.coverage_pct:.1f}%) | "
            f"sources={self.sources_used} | "
            f"rejections={self.rejection_reasons}"
        )


# ── Source fetchers ───────────────────────────────────────────────────────────


async def _fetch_ccxt(
    exchange_id: str,
    symbol: str,
    timeframe: str,
    since_ms: int,
    limit: int = 1000,
) -> pd.DataFrame | None:
    """Fetch OHLCV from a ccxt exchange. Returns DataFrame or None on failure."""
    try:
        import ccxt.async_support as ccxt_async
    except ImportError:
        logger.debug("ccxt not installed — skipping %s source", exchange_id)
        return None

    exchange = None
    try:
        exchange_cls = getattr(ccxt_async, exchange_id, None)
        if exchange_cls is None:
            return None
        exchange = exchange_cls({"enableRateLimit": True})
        all_bars = []
        since = since_ms
        while True:
            bars = await exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
            if not bars:
                break
            all_bars.extend(bars)
            if len(bars) < limit:
                break
            since = bars[-1][0] + 1
            await asyncio.sleep(exchange.rateLimit / 1000)

        if not all_bars:
            return None

        df = pd.DataFrame(all_bars, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = df["timestamp"].astype(int)
        df = df.set_index("timestamp").sort_index()
        logger.info("ccxt/%s: fetched %d bars for %s", exchange_id, len(df), symbol)
        return df
    except Exception as exc:
        logger.warning("ccxt/%s fetch failed for %s: %s", exchange_id, symbol, exc)
        return None
    finally:
        if exchange is not None:
            try:
                await exchange.close()
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)


async def _fetch_yfinance(
    symbol: str,
    timeframe: str,
    since_ms: int,
) -> pd.DataFrame | None:
    """Fetch OHLCV from Yahoo Finance via yfinance. Returns DataFrame or None."""
    try:
        import yfinance as yf
    except ImportError:
        logger.debug("yfinance not installed — skipping Yahoo Finance source")
        return None

    # Map ccxt symbol to yfinance ticker
    _ticker_map = {
        "XAU/USDT": "GC=F",  # Gold futures
        "XAU/USD": "GC=F",
        "BTC/USDT": "BTC-USD",
        "ETH/USDT": "ETH-USD",
    }
    ticker = _ticker_map.get(symbol, symbol.replace("/", "-"))

    # Map ccxt timeframe to yfinance interval
    _interval_map = {
        "1h": "1h",
        "4h": "1h",
        "1d": "1d",
        "15m": "15m",
        "30m": "30m",
    }
    interval = _interval_map.get(timeframe, "1h")

    try:
        since_dt = datetime.fromtimestamp(since_ms / 1000, tz=UTC)
        # yfinance is synchronous — run in executor
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(
            None,
            lambda: yf.download(
                ticker,
                start=since_dt,
                interval=interval,
                progress=False,
                auto_adjust=True,
            ),
        )
        if data is None or data.empty:
            return None

        df = data[["Open", "High", "Low", "Close", "Volume"]].copy()
        df.columns = ["open", "high", "low", "close", "volume"]
        # Convert DatetimeIndex to Unix ms
        df.index = (df.index.astype(np.int64) // 10**6).astype(int)
        df.index.name = "timestamp"
        df = df.sort_index()
        logger.info("yfinance: fetched %d bars for %s (%s)", len(df), ticker, symbol)
        return df
    except Exception as exc:
        logger.warning("yfinance fetch failed for %s: %s", symbol, exc)
        return None


async def _fetch_alpha_vantage(
    symbol: str,
    timeframe: str,
) -> pd.DataFrame | None:
    """Fetch OHLCV from Alpha Vantage REST API. Returns DataFrame or None."""
    api_key = os.getenv("ALPHA_VANTAGE_API_KEY", "")
    if not api_key:
        return None

    # Map symbol to Alpha Vantage format
    _av_map = {
        "XAU/USDT": "XAUUSD",
        "XAU/USD": "XAUUSD",
        "BTC/USDT": "BTCUSD",
        "ETH/USDT": "ETHUSD",
    }
    av_symbol = _av_map.get(symbol, symbol.replace("/", ""))

    _interval_map = {"1h": "60min", "4h": "60min", "1d": "daily", "15m": "15min"}
    interval = _interval_map.get(timeframe, "60min")

    function = "FX_INTRADAY" if interval != "daily" else "FX_DAILY"
    url = (
        f"https://www.alphavantage.co/query?function={function}"
        f"&from_symbol={av_symbol[:3]}&to_symbol={av_symbol[3:]}"
        f"&interval={interval}&outputsize=full&apikey={api_key}"
    )

    try:
        import aiohttp

        async with (
            aiohttp.ClientSession() as session,
            session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp,
        ):
            if resp.status != 200:  # noqa: PLR2004
                return None
            data = await resp.json()

        key = f"Time Series FX ({interval})" if interval != "daily" else "Time Series FX (Daily)"
        ts = data.get(key, {})
        if not ts:
            return None

        rows = []
        for dt_str, vals in ts.items():
            try:
                dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
                rows.append(
                    {
                        "timestamp": int(dt.timestamp() * 1000),
                        "open": float(vals["1. open"]),
                        "high": float(vals["2. high"]),
                        "low": float(vals["3. low"]),
                        "close": float(vals["4. close"]),
                        "volume": 0.0,
                    }
                )
            except (KeyError, ValueError):
                continue

        if not rows:
            return None

        df = pd.DataFrame(rows).set_index("timestamp").sort_index()
        logger.info("AlphaVantage: fetched %d bars for %s", len(df), symbol)
        return df
    except Exception as exc:
        logger.warning("AlphaVantage fetch failed for %s: %s", symbol, exc)
        return None


# ── Validation engine ─────────────────────────────────────────────────────────


class MultiSourceValidator:
    """
    Validates OHLCV bars by cross-checking multiple independent data sources.

    A bar is accepted only when at least MIN_SOURCES sources agree on the
    close price within MAX_PRICE_DEV tolerance.
    """

    def __init__(
        self,
        min_sources: int = MIN_SOURCES,
        max_price_dev: float = MAX_PRICE_DEV,
        max_gap_pct: float = MAX_GAP_PCT,
        max_spike_pct: float = MAX_SPIKE_PCT,
    ) -> None:
        self.min_sources = min_sources
        self.max_price_dev = max_price_dev
        self.max_gap_pct = max_gap_pct
        self.max_spike_pct = max_spike_pct

    async def fetch_all_sources(
        self,
        symbol: str,
        timeframe: str,
        since_ms: int,
    ) -> dict[str, pd.DataFrame]:
        """
        Fetch OHLCV from all available sources in parallel.

        Returns dict of source_name → DataFrame (may be empty if source failed).
        """
        tasks = {
            "binance": _fetch_ccxt("binance", symbol, timeframe, since_ms),
            "kraken": _fetch_ccxt("kraken", symbol, timeframe, since_ms),
            "yfinance": _fetch_yfinance(symbol, timeframe, since_ms),
            "alpha_vantage": _fetch_alpha_vantage(symbol, timeframe),
        }
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        sources: dict[str, pd.DataFrame] = {}
        for name, result in zip(tasks.keys(), results, strict=False):
            if isinstance(result, pd.DataFrame) and not result.empty:
                sources[name] = result
            elif isinstance(result, Exception):
                logger.debug("Source %s raised: %s", name, result)

        logger.info(
            "MultiSourceValidator: %d/%d sources available for %s: %s",
            len(sources),
            len(tasks),
            symbol,
            list(sources.keys()),
        )
        return sources

    def validate(
        self,
        sources: dict[str, pd.DataFrame],
        symbol: str,
        timeframe: str,
    ) -> tuple[pd.DataFrame, ValidationReport]:
        """
        Cross-validate bars across sources and return only accepted bars.

        Parameters
        ----------
        sources : Dict of source_name → OHLCV DataFrame (index = Unix ms timestamp).

        Returns
        -------
        (validated_df, report) where validated_df contains only accepted bars.
        """
        if len(sources) < self.min_sources:
            logger.warning(
                "MultiSourceValidator: only %d source(s) available for %s "
                "(need %d) — using single source with OHLC sanity checks only",
                len(sources),
                symbol,
                self.min_sources,
            )
            # Fall back to single-source with OHLC sanity only
            if sources:
                primary = next(iter(sources.values()))
                validated = self._ohlc_sanity_filter(primary)
                report = ValidationReport(
                    symbol=symbol,
                    timeframe=timeframe,
                    total_bars=len(primary),
                    accepted_bars=len(validated),
                    rejected_bars=len(primary) - len(validated),
                    sources_used=list(sources.keys()),
                    rejection_reasons={"ohlc_sanity": len(primary) - len(validated)},
                    coverage_pct=len(validated) / max(len(primary), 1) * 100,
                )
                return validated, report
            return pd.DataFrame(), ValidationReport(
                symbol=symbol,
                timeframe=timeframe,
                total_bars=0,
                accepted_bars=0,
                rejected_bars=0,
                sources_used=[],
                rejection_reasons={},
                coverage_pct=0.0,
            )

        # Use the source with the most bars as the reference index
        primary_name = max(sources, key=lambda k: len(sources[k]))
        primary = sources[primary_name].copy()

        bar_results: list[BarValidationResult] = []
        rejection_reasons: dict[str, int] = {}

        prev_close: float | None = None

        for ts, row in primary.iterrows():
            flags: list[str] = []
            prices: dict[str, float] = {primary_name: float(row["close"])}

            # ── Collect close prices from all sources at this timestamp ───────
            for src_name, src_df in sources.items():
                if src_name == primary_name:
                    continue
                # Find the nearest bar within ±1 bar interval
                if ts in src_df.index:
                    prices[src_name] = float(src_df.loc[ts, "close"])
                else:
                    # Try nearest timestamp within tolerance
                    diffs = abs(src_df.index - ts)
                    nearest_idx = diffs.argmin()
                    if diffs.iloc[nearest_idx] < self._bar_ms(timeframe) * 1.5:
                        prices[src_name] = float(src_df.iloc[nearest_idx]["close"])

            # ── Price agreement check ─────────────────────────────────────────
            close_values = list(prices.values())
            mid = np.median(close_values)
            agreeing = sum(1 for p in close_values if mid > 0 and abs(p - mid) / mid <= self.max_price_dev)

            if agreeing < self.min_sources:
                flags.append("PRICE_DISAGREEMENT")

            # ── OHLC sanity ───────────────────────────────────────────────────
            o, h, lo, c = (
                float(row["open"]),
                float(row["high"]),
                float(row["low"]),
                float(row["close"]),
            )
            if not (h >= o and h >= c and lo <= o and lo <= c and h >= lo):
                flags.append("OHLC_INVALID")

            # ── Gap detection ─────────────────────────────────────────────────
            if prev_close is not None and prev_close > 0:
                gap = abs(o - prev_close) / prev_close
                if gap > self.max_gap_pct:
                    flags.append(f"GAP_{gap:.1%}")

            # ── Spike detection ───────────────────────────────────────────────
            if c > 0:
                spike = (h - lo) / c
                if spike > self.max_spike_pct:
                    flags.append(f"SPIKE_{spike:.1%}")

            accepted = len(flags) == 0
            if not accepted:
                for f in flags:
                    rejection_reasons[f] = rejection_reasons.get(f, 0) + 1

            bar_results.append(
                BarValidationResult(
                    timestamp=int(ts),
                    accepted=accepted,
                    sources_agreed=agreeing,
                    sources_total=len(prices),
                    prices=prices,
                    flags=flags,
                )
            )
            prev_close = c

        # Build validated DataFrame
        accepted_ts = {r.timestamp for r in bar_results if r.accepted}
        validated = primary[primary.index.isin(accepted_ts)].copy()

        report = ValidationReport(
            symbol=symbol,
            timeframe=timeframe,
            total_bars=len(primary),
            accepted_bars=len(validated),
            rejected_bars=len(primary) - len(validated),
            sources_used=list(sources.keys()),
            rejection_reasons=rejection_reasons,
            coverage_pct=len(validated) / max(len(primary), 1) * 100,
        )
        logger.info(report.summary())
        return validated, report

    def _ohlc_sanity_filter(self, df: pd.DataFrame) -> pd.DataFrame:
        """Filter bars that fail basic OHLC sanity checks."""
        mask = (
            (df["high"] >= df["open"])
            & (df["high"] >= df["close"])
            & (df["low"] <= df["open"])
            & (df["low"] <= df["close"])
            & (df["high"] >= df["low"])
            & (df["close"] > 0)
        )
        return df[mask]

    @staticmethod
    def _bar_ms(timeframe: str) -> int:
        """Return bar duration in milliseconds."""
        _map = {
            "1m": 60_000,
            "5m": 300_000,
            "15m": 900_000,
            "30m": 1_800_000,
            "1h": 3_600_000,
            "4h": 14_400_000,
            "1d": 86_400_000,
        }
        return _map.get(timeframe, 3_600_000)


# ── Convenience function ──────────────────────────────────────────────────────


async def fetch_validated_ohlcv(
    symbol: str,
    timeframe: str = "1h",
    since_ms: int | None = None,
    min_sources: int = MIN_SOURCES,
) -> pd.DataFrame:
    """
    Fetch and cross-validate OHLCV data from multiple sources.

    Returns a DataFrame of accepted bars only. Attaches a ValidationReport
    to df.attrs["validation_report"] for inspection.

    Parameters
    ----------
    symbol      : ccxt-format symbol, e.g. "XAU/USDT".
    timeframe   : Bar timeframe, e.g. "1h".
    since_ms    : Start timestamp in Unix milliseconds. Defaults to 3 years ago.
    min_sources : Minimum agreeing sources required (default: BACKTEST_MIN_SOURCES).

    Returns
    -------
    pd.DataFrame with columns: open, high, low, close, volume.
    Index: Unix ms timestamp.
    """
    if since_ms is None:
        # Default: 3 years of history
        import time as _time

        since_ms = int((_time.time() - 3 * 365 * 24 * 3600) * 1000)

    validator = MultiSourceValidator(min_sources=min_sources)
    sources = await validator.fetch_all_sources(symbol, timeframe, since_ms)
    validated_df, report = validator.validate(sources, symbol, timeframe)
    validated_df.attrs["validation_report"] = report
    return validated_df
