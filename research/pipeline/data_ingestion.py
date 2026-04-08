# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
research/pipeline/data_ingestion.py
====================================
Multi-source, no-API-key data ingestion layer.

Sources
-------
1. yfinance  — daily OHLCV back to 1980s for equities/ETFs/crypto/FX
2. yfinance  — intraday 5-min / 15-min (up to 60 days per call; paginated
               backward to extend coverage as far as yfinance allows)
3. Free RSS  — Google Finance / Yahoo Finance / Finviz RSS for sentiment
               proxies (headline polarity via VADER-lite word lists)

Design
------
- All data is cached to Parquet under data/cache/ so repeated runs are free.
- Rate-limit dodging: exponential back-off + jitter on every yfinance call.
- Gap handling: missing bars are forward-filled for price, zero-filled for
  volume, then flagged with a boolean `is_forward_filled` column.
- Output: clean pandas DataFrame with DatetimeIndex (UTC), columns:
    open, high, low, close, volume, vwap, sentiment_score, is_forward_filled
"""

from __future__ import annotations

import hashlib
import logging
import random
import time
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
from pathlib import Path
from typing import ClassVar

import feedparser  # pip install feedparser
import numpy as np
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# ── Cache directory ───────────────────────────────────────────────────────────
CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ── VADER-lite positive / negative word sets (no NLTK dependency) ─────────────
_POS_WORDS = {
    "surge",
    "rally",
    "gain",
    "rise",
    "jump",
    "beat",
    "record",
    "high",
    "profit",
    "growth",
    "strong",
    "bullish",
    "upgrade",
    "buy",
    "positive",
    "outperform",
    "exceed",
    "boom",
    "recover",
    "rebound",
}
_NEG_WORDS = {
    "fall",
    "drop",
    "plunge",
    "crash",
    "loss",
    "miss",
    "low",
    "weak",
    "bearish",
    "downgrade",
    "sell",
    "negative",
    "underperform",
    "decline",
    "recession",
    "fear",
    "risk",
    "warn",
    "cut",
    "layoff",
}

# ── RSS feeds (no key required) ───────────────────────────────────────────────
_RSS_FEEDS: dict[str, str] = {
    "yahoo_finance": "https://finance.yahoo.com/news/rssindex",
    "seeking_alpha": "https://seekingalpha.com/market_currents.xml",
    "marketwatch": "https://feeds.marketwatch.com/marketwatch/topstories/",
    "investing_com": "https://www.investing.com/rss/news.rss",
}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _cache_key(ticker: str, interval: str, start: str, end: str) -> Path:
    tag = hashlib.md5(f"{ticker}{interval}{start}{end}".encode(), usedforsecurity=False).hexdigest()[:10]
    return CACHE_DIR / f"{ticker.replace('/', '_')}_{interval}_{tag}.parquet"


def _backoff_download(ticker: str, **kwargs) -> pd.DataFrame:
    """yfinance download with exponential back-off + jitter."""
    for attempt in range(5):
        try:
            df = yf.download(ticker, progress=False, auto_adjust=True, **kwargs)
            if df is not None and not df.empty:
                return df
        except Exception as exc:
            logger.warning("yfinance attempt %d failed for %s: %s", attempt + 1, ticker, exc)
        sleep = (2**attempt) + random.uniform(0, 1)  # nosec B311 - exponential backoff jitter, not cryptographic
        time.sleep(sleep)
    return pd.DataFrame()


def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Flatten MultiIndex columns produced by yfinance multi-ticker downloads."""
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = ["_".join(c).strip().lower() for c in df.columns]
    else:
        df.columns = [c.lower() for c in df.columns]
    return df


def _add_vwap(df: pd.DataFrame) -> pd.DataFrame:
    """Intraday VWAP (resets each session). Falls back to typical price for daily."""
    if "volume" not in df.columns or df["volume"].sum() == 0:
        df["vwap"] = (df["high"] + df["low"] + df["close"]) / 3
        return df

    typical = (df["high"] + df["low"] + df["close"]) / 3
    cum_tp_vol = (typical * df["volume"]).cumsum()
    cum_vol = df["volume"].cumsum()
    df["vwap"] = cum_tp_vol / cum_vol.replace(0, np.nan)
    return df


def _fill_gaps(df: pd.DataFrame) -> pd.DataFrame:
    """
    Forward-fill price columns, zero-fill volume, flag synthetic bars.
    Drops rows where close is still NaN after ffill (leading NaNs).
    """
    price_cols = [c for c in ["open", "high", "low", "close", "vwap"] if c in df.columns]
    df["is_forward_filled"] = df["close"].isna()
    df[price_cols] = df[price_cols].ffill()
    if "volume" in df.columns:
        df["volume"] = df["volume"].fillna(0)
    df.dropna(subset=["close"], inplace=True)
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Daily data (back to 1980s for most US equities)
# ─────────────────────────────────────────────────────────────────────────────


def fetch_daily(
    ticker: str,
    start: str = "1980-01-01",
    end: str | None = None,
    use_cache: bool = True,
) -> pd.DataFrame:
    """
    Download daily OHLCV from yfinance.

    Parameters
    ----------
    ticker    : Yahoo Finance ticker symbol (e.g. 'AAPL', 'GC=F', 'BTC-USD')
    start     : ISO date string
    end       : ISO date string; defaults to today
    use_cache : Load from / save to Parquet cache

    Returns
    -------
    DataFrame with DatetimeIndex (UTC), columns:
        open, high, low, close, volume, vwap, is_forward_filled
    """
    end = end or datetime.now(UTC).strftime("%Y-%m-%d")
    cache_path = _cache_key(ticker, "1d", start, end)

    if use_cache and cache_path.exists():
        logger.info("Cache hit: %s", cache_path.name)
        return pd.read_parquet(cache_path)

    logger.info("Fetching daily %s  %s → %s", ticker, start, end)
    raw = _backoff_download(ticker, start=start, end=end, interval="1d")

    if raw.empty:
        logger.warning("No daily data returned for %s", ticker)
        return pd.DataFrame()

    df = _flatten_columns(raw)
    # Rename adj close if present
    for col in list(df.columns):
        if "adj" in col and "close" in col:
            df.rename(columns={col: "close"}, inplace=True)
            break

    # Ensure standard columns exist
    for col in ["open", "high", "low", "close", "volume"]:
        if col not in df.columns:
            df[col] = np.nan

    df.index = pd.to_datetime(df.index, utc=True)
    df = df[["open", "high", "low", "close", "volume"]].copy()
    df = _add_vwap(df)
    df = _fill_gaps(df)

    if use_cache:
        df.to_parquet(cache_path)

    return df


# ─────────────────────────────────────────────────────────────────────────────
# Intraday data — paginated backward to maximise history
# ─────────────────────────────────────────────────────────────────────────────

_INTRADAY_WINDOW_DAYS: dict[str, int] = {
    "1m": 7,
    "2m": 60,
    "5m": 60,
    "15m": 60,
    "30m": 60,
    "60m": 730,
    "90m": 60,
    "1h": 730,
}


def fetch_intraday(
    ticker: str,
    interval: str = "5m",
    lookback_days: int = 365,
    use_cache: bool = True,
) -> pd.DataFrame:
    """
    Download intraday OHLCV by paginating backward in chunks.

    yfinance limits each intraday call to a fixed window (e.g. 60 days for 5m).
    This function issues multiple calls, stepping backward, then concatenates
    and deduplicates the results.

    Parameters
    ----------
    ticker       : Yahoo Finance ticker
    interval     : '1m','5m','15m','30m','1h' etc.
    lookback_days: Total history to attempt (capped by yfinance limits)
    use_cache    : Parquet cache

    Returns
    -------
    DataFrame with DatetimeIndex (UTC), same schema as fetch_daily()
    """
    end_dt = datetime.now(UTC)
    start_str = (end_dt - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    end_str = end_dt.strftime("%Y-%m-%d")
    cache_path = _cache_key(ticker, interval, start_str, end_str)

    if use_cache and cache_path.exists():
        logger.info("Cache hit: %s", cache_path.name)
        return pd.read_parquet(cache_path)

    window = _INTRADAY_WINDOW_DAYS.get(interval, 60)
    chunks: ClassVar[list[pd.DataFrame]] = []
    chunk_end = end_dt

    while (end_dt - chunk_end).days < lookback_days:
        chunk_start = chunk_end - timedelta(days=window)
        if (end_dt - chunk_start).days > lookback_days:
            chunk_start = end_dt - timedelta(days=lookback_days)

        logger.info(
            "Intraday chunk %s  %s → %s",
            ticker,
            chunk_start.strftime("%Y-%m-%d"),
            chunk_end.strftime("%Y-%m-%d"),
        )
        raw = _backoff_download(
            ticker,
            start=chunk_start.strftime("%Y-%m-%d"),
            end=chunk_end.strftime("%Y-%m-%d"),
            interval=interval,
        )
        if not raw.empty:
            chunks.append(raw)

        chunk_end = chunk_start - timedelta(days=1)
        # Respect rate limits
        time.sleep(random.uniform(0.5, 1.5))  # nosec B311 - rate-limit sleep jitter, not cryptographic

        if chunk_start <= end_dt - timedelta(days=lookback_days):
            break

    if not chunks:
        logger.warning("No intraday data for %s @ %s", ticker, interval)
        return pd.DataFrame()

    df = pd.concat(chunks)
    df = _flatten_columns(df)
    df.index = pd.to_datetime(df.index, utc=True)
    df = df[~df.index.duplicated(keep="last")].sort_index()

    for col in ["open", "high", "low", "close", "volume"]:
        if col not in df.columns:
            df[col] = np.nan

    df = df[["open", "high", "low", "close", "volume"]].copy()
    df = _add_vwap(df)
    df = _fill_gaps(df)

    if use_cache:
        df.to_parquet(cache_path)

    return df


# ─────────────────────────────────────────────────────────────────────────────
# Multi-asset batch fetch
# ─────────────────────────────────────────────────────────────────────────────

# Curated universe: equities + ETFs + crypto + FX + commodities
DEFAULT_UNIVERSE: dict[str, list[str]] = {
    "equities": ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "JPM", "GS"],
    "etfs": ["SPY", "QQQ", "IWM", "GLD", "SLV", "TLT", "HYG", "EEM", "XLE"],
    "crypto": ["BTC-USD", "ETH-USD", "SOL-USD"],
    "fx": ["EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X"],
    "commodities": ["GC=F", "SI=F", "CL=F", "NG=F"],
    "macro": ["^VIX", "^TNX", "^IRX", "DX-Y.NYB", "^GSPC"],
}


def fetch_universe(
    universe: dict[str, list[str]] | None = None,
    interval: str = "1d",
    start: str = "1990-01-01",
    lookback_days: int = 365,
    use_cache: bool = True,
) -> dict[str, pd.DataFrame]:
    """
    Fetch OHLCV for every ticker in the universe dict.

    Returns a dict mapping ticker → DataFrame.
    """
    universe = universe or DEFAULT_UNIVERSE
    results: dict[str, pd.DataFrame] = {}

    for category, tickers in universe.items():
        for ticker in tickers:
            try:
                if interval == "1d":
                    df = fetch_daily(ticker, start=start, use_cache=use_cache)
                else:
                    df = fetch_intraday(
                        ticker,
                        interval=interval,
                        lookback_days=lookback_days,
                        use_cache=use_cache,
                    )
                if not df.empty:
                    df["category"] = category
                    results[ticker] = df
                    logger.info("✓ %s  (%s rows)", ticker, len(df))
            except Exception as exc:
                logger.error("Failed %s: %s", ticker, exc)

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Sentiment from free RSS feeds
# ─────────────────────────────────────────────────────────────────────────────


def _score_headline(text: str) -> float:
    """
    Lightweight VADER-style polarity score in [-1, +1].
    No NLTK / transformers required.
    """
    words = text.lower().split()
    pos = sum(1 for w in words if w in _POS_WORDS)
    neg = sum(1 for w in words if w in _NEG_WORDS)
    total = pos + neg
    if total == 0:
        return 0.0
    return (pos - neg) / total


def fetch_rss_sentiment(
    ticker: str,
    max_articles: int = 100,
) -> pd.DataFrame:
    """
    Pull headlines from free RSS feeds and return a DataFrame with columns:
        published (UTC DatetimeIndex), title, sentiment_score

    Sentiment is a simple word-count polarity in [-1, +1].
    No API key required.
    """
    records = []

    for source, url in _RSS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:max_articles]:
                title = getattr(entry, "title", "")
                # Filter loosely by ticker mention
                if ticker.upper().replace("=X", "").replace("-USD", "") not in title.upper():
                    # Still include general market news with lower weight
                    score = _score_headline(title) * 0.3
                else:
                    score = _score_headline(title)

                published = getattr(entry, "published_parsed", None)
                ts = datetime(*published[:6], tzinfo=UTC) if published else datetime.now(UTC)

                records.append(
                    {
                        "published": ts,
                        "title": title,
                        "sentiment_score": score,
                        "source": source,
                    }
                )
        except Exception as exc:
            logger.warning("RSS fetch failed (%s): %s", source, exc)

    if not records:
        return pd.DataFrame(columns=["published", "title", "sentiment_score", "source"])

    df = pd.DataFrame(records)
    df["published"] = pd.to_datetime(df["published"], utc=True)
    df = df.sort_values("published").set_index("published")
    return df


def attach_sentiment(
    price_df: pd.DataFrame,
    sentiment_df: pd.DataFrame,
    window: str = "1D",
) -> pd.DataFrame:
    """
    Resample sentiment to match price_df frequency and merge.

    Adds columns: sentiment_mean, sentiment_std, sentiment_count
    """
    if sentiment_df.empty:
        price_df["sentiment_mean"] = 0.0
        price_df["sentiment_std"] = 0.0
        price_df["sentiment_count"] = 0
        return price_df

    sent_resampled = (
        sentiment_df["sentiment_score"]
        .resample(window)
        .agg(
            sentiment_mean="mean",
            sentiment_std="std",
            sentiment_count="count",
        )
    )
    sent_resampled = sent_resampled.fillna({"sentiment_mean": 0.0, "sentiment_std": 0.0, "sentiment_count": 0})

    merged = price_df.join(sent_resampled, how="left")
    merged[["sentiment_mean", "sentiment_std", "sentiment_count"]] = merged[
        ["sentiment_mean", "sentiment_std", "sentiment_count"]
    ].fillna({"sentiment_mean": 0.0, "sentiment_std": 0.0, "sentiment_count": 0})

    return merged
