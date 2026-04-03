# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
data/feeds/macro.py
===================
Macro data feeds for DXY, US 10-year yield, and CPI from FRED (St. Louis Fed).

All series are free and publicly accessible.  A FRED API key is optional but
increases the rate limit from 120 to 500 requests/day.

Environment variables
---------------------
FRED_API_KEY   — optional; increases rate limit (get free at fred.stlouisfed.org)

Usage
-----
    from data.feeds.macro import fetch_dxy, fetch_10y_yield, fetch_cpi, MacroFeed

    # Async (preferred in FastAPI context)
    dxy = await fetch_dxy()
    yield10y = await fetch_10y_yield()
    cpi = await fetch_cpi()

    # Sync helper
    feed = MacroFeed()
    snapshot = feed.latest_snapshot()   # dict with current values
    features = feed.as_ml_features()    # flat dict ready to merge into feature matrix
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# ── FRED series IDs ───────────────────────────────────────────────────────────
# DXY proxy: Trade Weighted U.S. Dollar Index (Broad, Goods and Services)
_SERIES_DXY = "DTWEXBGS"
# US 10-year Treasury constant maturity yield
_SERIES_10Y = "DGS10"
# CPI All Urban Consumers (monthly, not seasonally adjusted)
_SERIES_CPI = "CPIAUCNS"
# US 2-year Treasury (for yield spread)
_SERIES_2Y = "DGS2"

_FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
_FRED_KEY = os.getenv("FRED_API_KEY", "")


# ── low-level FRED fetch ──────────────────────────────────────────────────────


def _fred_url(series_id: str, limit: int = 30) -> str:
    """Build a FRED observations URL."""
    params = f"series_id={series_id}&sort_order=desc&limit={limit}&file_type=json"
    if _FRED_KEY:
        params += f"&api_key={_FRED_KEY}"
    return f"{_FRED_BASE}?{params}"


def _parse_fred_response(data: dict) -> pd.DataFrame:
    """Convert FRED JSON observations to a DataFrame with date index."""
    obs = data.get("observations", [])
    rows = []
    for o in obs:
        try:
            val = float(o["value"])
            rows.append({"date": pd.to_datetime(o["date"]), "value": val})
        except (ValueError, KeyError):
            # FRED uses "." for missing values
            continue
    if not rows:
        return pd.DataFrame(columns=["date", "value"])
    df = pd.DataFrame(rows).set_index("date").sort_index()
    return df


async def _fetch_fred_async(series_id: str, limit: int = 30) -> pd.DataFrame:
    """Async FRED fetch using httpx if available, else requests in executor."""
    url = _fred_url(series_id, limit)
    try:
        import httpx

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return _parse_fred_response(resp.json())
    except ImportError:
        pass

    # Fallback: run blocking requests in thread pool
    import requests

    loop = asyncio.get_event_loop()

    def _sync():
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        return _parse_fred_response(r.json())

    return await loop.run_in_executor(None, _sync)


def _fetch_fred_sync(series_id: str, limit: int = 30) -> pd.DataFrame:
    """Synchronous FRED fetch (for use outside async context)."""
    import requests

    url = _fred_url(series_id, limit)
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        return _parse_fred_response(r.json())
    except Exception as exc:
        logger.warning("FRED fetch failed for %s: %s", series_id, exc)
        return pd.DataFrame(columns=["date", "value"])


# ── public async API ──────────────────────────────────────────────────────────


async def fetch_dxy(limit: int = 30) -> pd.DataFrame:
    """
    Fetch the Trade Weighted US Dollar Index (DXY proxy) from FRED.

    Returns a DataFrame with DatetimeIndex and a 'value' column.
    Higher values = stronger dollar = bearish for gold.
    """
    logger.debug("Fetching DXY (%s) from FRED...", _SERIES_DXY)
    df = await _fetch_fred_async(_SERIES_DXY, limit)
    df.columns = ["dxy"]
    return df


async def fetch_10y_yield(limit: int = 30) -> pd.DataFrame:
    """
    Fetch US 10-year Treasury yield from FRED.

    Returns a DataFrame with DatetimeIndex and a 'value' column.
    Rising yields = bearish for gold (opportunity cost of holding gold rises).
    """
    logger.debug("Fetching 10Y yield (%s) from FRED...", _SERIES_10Y)
    df = await _fetch_fred_async(_SERIES_10Y, limit)
    df.columns = ["yield_10y"]
    return df


async def fetch_2y_yield(limit: int = 30) -> pd.DataFrame:
    """Fetch US 2-year Treasury yield from FRED."""
    df = await _fetch_fred_async(_SERIES_2Y, limit)
    df.columns = ["yield_2y"]
    return df


async def fetch_cpi(limit: int = 12) -> pd.DataFrame:
    """
    Fetch US CPI (All Urban Consumers) from FRED.

    Returns a DataFrame with DatetimeIndex and a 'value' column.
    Rising CPI = bullish for gold (inflation hedge demand).
    """
    logger.debug("Fetching CPI (%s) from FRED...", _SERIES_CPI)
    df = await _fetch_fred_async(_SERIES_CPI, limit)
    df.columns = ["cpi"]
    return df


async def fetch_yield_spread(limit: int = 30) -> pd.DataFrame:
    """
    Compute 10Y-2Y yield spread (recession indicator).

    Negative spread (inverted curve) historically precedes recessions and
    is associated with risk-off flows into gold.
    """
    df_10y, df_2y = await asyncio.gather(
        fetch_10y_yield(limit),
        fetch_2y_yield(limit),
    )
    if df_10y.empty or df_2y.empty:
        return pd.DataFrame(columns=["yield_spread"])
    combined = df_10y.join(df_2y, how="inner")
    combined["yield_spread"] = combined["yield_10y"] - combined["yield_2y"]
    return combined[["yield_spread"]]


# ── MacroFeed class ───────────────────────────────────────────────────────────


class MacroFeed:
    """
    Aggregates macro data from FRED and exposes it as ML features.

    Caches results for ``cache_ttl_seconds`` to avoid hammering FRED on
    every prediction request.
    """

    def __init__(self, cache_ttl_seconds: int = 3600):
        self._cache_ttl = cache_ttl_seconds
        self._cache: dict[str, Any] = {}
        self._cache_ts: datetime | None = None

    def _is_cache_fresh(self) -> bool:
        if self._cache_ts is None:
            return False
        age = (datetime.now(UTC) - self._cache_ts).total_seconds()
        return age < self._cache_ttl

    def refresh(self) -> dict[str, Any]:
        """Synchronously refresh all macro data and return the snapshot."""
        dxy_df = _fetch_fred_sync(_SERIES_DXY, limit=5)
        y10_df = _fetch_fred_sync(_SERIES_10Y, limit=5)
        y2_df = _fetch_fred_sync(_SERIES_2Y, limit=5)
        cpi_df = _fetch_fred_sync(_SERIES_CPI, limit=3)

        def _latest(df: pd.DataFrame, col: str) -> float | None:
            if df.empty:
                return None
            return float(df.iloc[-1].iloc[0])

        dxy = _latest(dxy_df, "dxy")
        y10 = _latest(y10_df, "yield_10y")
        y2 = _latest(y2_df, "yield_2y")
        cpi = _latest(cpi_df, "cpi")
        spread = (y10 - y2) if (y10 is not None and y2 is not None) else None

        # YoY CPI change
        cpi_yoy = None
        if not cpi_df.empty and len(cpi_df) >= 2:
            try:
                cpi_now = float(cpi_df.iloc[-1].iloc[0])
                cpi_prev = float(cpi_df.iloc[0].iloc[0])
                if cpi_prev > 0:
                    cpi_yoy = round((cpi_now - cpi_prev) / cpi_prev * 100, 2)
            except Exception as exc:
                logger.warning("MacroFeed.refresh: CPI YoY calculation failed: %s", exc)

        # Macro regime score for gold (0 = bearish, 100 = bullish)
        score = _macro_regime_score(dxy, y10, spread, cpi_yoy)

        snapshot = {
            "dxy": dxy,
            "yield_10y": y10,
            "yield_2y": y2,
            "yield_spread": spread,
            "cpi_latest": cpi,
            "cpi_yoy_pct": cpi_yoy,
            "macro_regime_score": score,
            "macro_stance": _regime_label(score),
            "refreshed_at": datetime.now(UTC).isoformat(),
        }
        self._cache = snapshot
        self._cache_ts = datetime.now(UTC)
        return snapshot

    def latest_snapshot(self) -> dict[str, Any]:
        """Return cached snapshot, refreshing if stale."""
        if not self._is_cache_fresh():
            try:
                self.refresh()
            except Exception as exc:
                logger.warning("MacroFeed refresh failed: %s", exc)
                if not self._cache:
                    return {
                        "error": "Macro feed unavailable — check server logs",
                        "macro_regime_score": 50,
                        "macro_stance": "neutral",
                    }
        return self._cache

    def as_ml_features(self) -> dict[str, float]:
        """
        Return macro values as a flat dict of floats for ML feature injection.

        Keys are prefixed with 'macro_' to avoid collisions with OHLCV features.
        Missing values are filled with 0.0 so the feature vector stays fixed-width.

        Includes WGC gold demand series from MacroStore when available.
        """
        snap = self.latest_snapshot()
        features: dict[str, float] = {
            "macro_dxy": snap.get("dxy") or 0.0,
            "macro_yield_10y": snap.get("yield_10y") or 0.0,
            "macro_yield_2y": snap.get("yield_2y") or 0.0,
            "macro_yield_spread": snap.get("yield_spread") or 0.0,
            "macro_cpi_yoy": snap.get("cpi_yoy_pct") or 0.0,
            "macro_regime_score": snap.get("macro_regime_score") or 50.0,
        }

        # Merge WGC series from MacroStore (latest values, forward-filled)
        try:
            from ml.macro_store import macro_store

            store_snap = macro_store.snapshot()
            wgc_keys = [
                "wgc_total_demand",
                "wgc_investment",
                "wgc_central_bank",
                "wgc_jewellery",
                "wgc_etf_flow",
            ]
            for key in wgc_keys:
                info = store_snap.get(key)
                features[f"macro_{key}"] = float(info["value"]) if info else 0.0
        except Exception:
            # MacroStore unavailable — WGC features default to 0.0
            for key in [
                "wgc_total_demand",
                "wgc_investment",
                "wgc_central_bank",
                "wgc_jewellery",
                "wgc_etf_flow",
            ]:
                features.setdefault(f"macro_{key}", 0.0)

        return features

    async def refresh_async(self) -> dict[str, Any]:
        """Async version of refresh() — preferred in FastAPI context."""
        dxy_df, y10_df, y2_df, cpi_df = await asyncio.gather(
            fetch_dxy(5),
            fetch_10y_yield(5),
            fetch_2y_yield(5),
            fetch_cpi(3),
        )

        def _latest(df: pd.DataFrame) -> float | None:
            if df.empty:
                return None
            return float(df.iloc[-1].iloc[0])

        dxy = _latest(dxy_df)
        y10 = _latest(y10_df)
        y2 = _latest(y2_df)
        cpi = _latest(cpi_df)
        spread = (y10 - y2) if (y10 is not None and y2 is not None) else None

        cpi_yoy = None
        if not cpi_df.empty and len(cpi_df) >= 2:
            try:
                cpi_now = float(cpi_df.iloc[-1].iloc[0])
                cpi_prev = float(cpi_df.iloc[0].iloc[0])
                if cpi_prev > 0:
                    cpi_yoy = round((cpi_now - cpi_prev) / cpi_prev * 100, 2)
            except Exception as exc:
                logger.warning("MacroFeed.refresh_async: CPI YoY calculation failed: %s", exc)

        score = _macro_regime_score(dxy, y10, spread, cpi_yoy)
        snapshot = {
            "dxy": dxy,
            "yield_10y": y10,
            "yield_2y": y2,
            "yield_spread": spread,
            "cpi_latest": cpi,
            "cpi_yoy_pct": cpi_yoy,
            "macro_regime_score": score,
            "macro_stance": _regime_label(score),
            "refreshed_at": datetime.now(UTC).isoformat(),
        }
        self._cache = snapshot
        self._cache_ts = datetime.now(UTC)
        return snapshot


# ── regime scoring ────────────────────────────────────────────────────────────


def _macro_regime_score(
    dxy: float | None,
    yield_10y: float | None,
    yield_spread: float | None,
    cpi_yoy: float | None,
) -> float:
    """
    Compute a 0–100 macro regime score for gold.

    100 = maximally bullish for gold (weak dollar, low yields, high inflation,
          inverted curve / risk-off).
    0   = maximally bearish (strong dollar, high yields, deflation).

    Each component contributes up to 25 points.  Missing data defaults to
    neutral (12.5 per component).
    """
    score = 0.0
    components = 0

    # DXY: lower = more bullish for gold
    # Typical range: 90–115.  Score 25 at 90, 0 at 115.
    if dxy is not None:
        dxy_score = max(0.0, min(25.0, (115.0 - dxy) / (115.0 - 90.0) * 25.0))
        score += dxy_score
        components += 1

    # 10Y yield: lower = more bullish for gold
    # Typical range: 0–6%.  Score 25 at 0%, 0 at 6%.
    if yield_10y is not None:
        y10_score = max(0.0, min(25.0, (6.0 - yield_10y) / 6.0 * 25.0))
        score += y10_score
        components += 1

    # Yield spread: inverted (negative) = risk-off = bullish for gold
    # Range: -1 to +3.  Score 25 at -1, 0 at +3.
    if yield_spread is not None:
        spread_score = max(0.0, min(25.0, (3.0 - yield_spread) / 4.0 * 25.0))
        score += spread_score
        components += 1

    # CPI YoY: higher inflation = more bullish for gold
    # Range: -1% to 10%.  Score 25 at 10%, 0 at -1%.
    if cpi_yoy is not None:
        cpi_score = max(0.0, min(25.0, (cpi_yoy - (-1.0)) / 11.0 * 25.0))
        score += cpi_score
        components += 1

    if components == 0:
        return 50.0  # neutral when no data

    # Scale to 0–100 based on available components
    return round(score / components * 4, 1)


def _regime_label(score: float) -> str:
    """Convert numeric score to human-readable stance label."""
    if score >= 70:
        return "Risk-off: gold bullish"
    if score >= 55:
        return "Mild tailwind for gold"
    if score >= 45:
        return "Neutral"
    if score >= 30:
        return "Dollar strength: gold headwind"
    return "Risk-on: gold bearish"


# ── module-level singleton ────────────────────────────────────────────────────

_feed: MacroFeed | None = None


def get_macro_feed() -> MacroFeed:
    """Return the module-level MacroFeed singleton (lazy init)."""
    global _feed
    if _feed is None:
        _feed = MacroFeed()
    return _feed
