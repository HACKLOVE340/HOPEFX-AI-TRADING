# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
data_layer/feeds/macro/wgc.py
==============================
World Gold Council (WGC) demand data feed.

WGC publishes quarterly gold demand statistics and monthly ETF flow data
as free CSV/Excel downloads from https://www.gold.org/goldhub/data/

No API key required. Data is fetched from WGC's public download endpoints
and cached locally to avoid hammering their servers.

MacroStore series produced
--------------------------
  wgc_total_demand   — total gold demand (tonnes, quarterly, forward-filled)
  wgc_investment     — bar/coin + ETF investment demand (tonnes, quarterly)
  wgc_central_bank   — central bank net purchases (tonnes, quarterly)
  wgc_jewellery      — jewellery demand (tonnes, quarterly)
  wgc_etf_flow       — ETF net flow (tonnes, monthly)

Gold demand signal logic
------------------------
  High central bank demand  → structural bullish (sovereign accumulation)
  High investment demand    → risk-off / inflation hedge demand
  Rising ETF flows          → institutional positioning bullish
  Falling jewellery demand  → consumer price sensitivity (bearish at extremes)

Data sources
------------
WGC Gold Demand Trends (quarterly):
  https://www.gold.org/goldhub/data/gold-demand-statistics

WGC ETF Holdings and Flows (monthly):
  https://www.gold.org/goldhub/data/global-gold-backed-etf-holdings-and-flows

Environment variables
---------------------
  WGC_CACHE_DIR          — local cache directory (default: data/wgc_cache)
  WGC_REFRESH_INTERVAL   — seconds between refreshes (default: 86400 = 24h)
  WGC_DEMAND_URL         — override quarterly demand CSV URL
  WGC_ETF_FLOW_URL       — override ETF flow CSV URL
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

UTC = timezone.utc

# ── Configuration ─────────────────────────────────────────────────────────────

_CACHE_DIR = Path(os.getenv("WGC_CACHE_DIR", "data/wgc_cache"))
_REFRESH_INTERVAL = int(os.getenv("WGC_REFRESH_INTERVAL", "86400"))

# WGC public download URLs.
# WGC serves these as direct CSV/Excel downloads from their data portal.
# The URLs below are the stable permalink format used since 2022.
_DEMAND_URL = os.getenv(
    "WGC_DEMAND_URL",
    "https://www.gold.org/goldhub/data/gold-demand-statistics",
)
_ETF_FLOW_URL = os.getenv(
    "WGC_ETF_FLOW_URL",
    "https://www.gold.org/goldhub/data/global-gold-backed-etf-holdings-and-flows",
)

# WGC also publishes machine-readable CSVs via their data API endpoint.
# These are the direct download links used by their own charting tools.
_WGC_DEMAND_CSV_URL = "https://www.gold.org/goldhub/data/gold-demand-statistics?download=csv"
_WGC_ETF_CSV_URL = "https://www.gold.org/goldhub/data/global-gold-backed-etf-holdings-and-flows?download=csv"

# HTTP timeout for WGC requests
_HTTP_TIMEOUT = 30.0

# Cache filenames
_DEMAND_CACHE_FILE = "wgc_demand_quarterly.csv"
_ETF_CACHE_FILE = "wgc_etf_flow_monthly.csv"

# Column name mappings from WGC CSV headers to internal series names.
# WGC changes column names occasionally; we try multiple variants.
_DEMAND_COL_VARIANTS: dict[str, list[str]] = {
    "wgc_total_demand": [
        "Total demand",
        "Total Gold Demand",
        "Total demand (t)",
        "Total",
    ],
    "wgc_investment": [
        "Total investment",
        "Investment",
        "Total bar and coin demand",
        "Bar and coin",
        "Physical bar demand",
    ],
    "wgc_central_bank": [
        "Central banks & other inst.",
        "Central banks",
        "Central bank net purchases",
        "Official sector",
    ],
    "wgc_jewellery": [
        "Jewellery",
        "Jewellery consumption",
        "Jewellery demand",
    ],
}

_ETF_COL_VARIANTS: dict[str, list[str]] = {
    "wgc_etf_flow": [
        "Net flows (t)",
        "Net flows",
        "Flows (t)",
        "Net flow",
        "Total net flows",
    ],
}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _find_col(df: pd.DataFrame, variants: list[str]) -> str | None:
    """Return the first column name from *variants* that exists in *df*."""
    for v in variants:
        if v in df.columns:
            return v
        # Case-insensitive fallback
        for col in df.columns:
            if col.strip().lower() == v.lower():
                return col
    return None


def _parse_date_col(df: pd.DataFrame) -> pd.Series | None:
    """
    Detect and parse the date column from a WGC CSV.

    WGC uses several date formats across their files:
      - "Q1 2024", "Q2 2023" (quarterly)
      - "January 2024", "Feb 2024" (monthly)
      - "2024-01-01" (ISO)
    """
    date_col_candidates = ["Date", "Period", "Quarter", "Month", "date", "period"]
    date_col = None
    for c in date_col_candidates:
        if c in df.columns:
            date_col = c
            break
    if date_col is None and len(df.columns) > 0:
        date_col = df.columns[0]

    if date_col is None:
        return None

    raw = df[date_col].astype(str).str.strip()

    # Try quarter format: "Q1 2024" → 2024-01-01
    def _parse_quarter(s: str) -> pd.Timestamp | None:
        s = s.strip()
        if s.startswith("Q") and len(s) >= 7:  # noqa: PLR2004
            try:
                q = int(s[1])
                year = int(s[3:7])
                month = (q - 1) * 3 + 1
                return pd.Timestamp(year=year, month=month, day=1, tz="UTC")
            except (ValueError, IndexError):
                return None
        return None

    parsed = raw.apply(_parse_quarter)
    if parsed.notna().sum() > len(df) * 0.5:
        return parsed

    # Try pandas general date parsing
    try:
        return pd.to_datetime(raw, utc=True, errors="coerce")
    except Exception:
        return None


def _csv_to_series(
    csv_text: str,
    col_variants: dict[str, list[str]],
) -> dict[str, pd.Series]:
    """
    Parse a WGC CSV string into a dict of {series_name: pd.Series}.

    Handles WGC's inconsistent column naming and date formats.
    Returns only series where at least one value was successfully parsed.
    """
    results: dict[str, pd.Series] = {}

    try:
        # WGC CSVs sometimes have metadata rows at the top; skip until header
        lines = csv_text.splitlines()
        header_idx = 0
        for i, line in enumerate(lines):
            # Header row has multiple comma-separated fields
            if line.count(",") >= 3:  # noqa: PLR2004
                header_idx = i
                break

        clean_csv = "\n".join(lines[header_idx:])
        df = pd.read_csv(io.StringIO(clean_csv), thousands=",")
    except Exception as exc:
        logger.warning("WGC CSV parse error: %s", exc)
        return results

    dates = _parse_date_col(df)
    if dates is None or dates.notna().sum() == 0:
        logger.warning("WGC CSV: could not parse date column. Columns: %s", list(df.columns))
        return results

    df["_date"] = dates
    df = df.dropna(subset=["_date"]).set_index("_date").sort_index()

    for series_name, variants in col_variants.items():
        col = _find_col(df, variants)
        if col is None:
            logger.debug("WGC: column not found for %s (tried: %s)", series_name, variants)
            continue
        try:
            s = pd.to_numeric(df[col], errors="coerce").dropna()
            if s.empty:
                continue
            s.index = pd.DatetimeIndex(s.index)
            s.name = series_name
            results[series_name] = s
            logger.info(
                "WGC: parsed %s — %d observations (latest: %.1f t on %s)",
                series_name,
                len(s),
                float(s.iloc[-1]),
                s.index[-1].date().isoformat(),
            )
        except Exception as exc:
            logger.warning("WGC: failed to extract %s: %s", series_name, exc)

    return results


# ── WGCFeed ───────────────────────────────────────────────────────────────────


class WGCFeed:
    """
    World Gold Council demand data feed.

    Fetches quarterly demand and monthly ETF flow data from WGC's public
    download endpoints. Results are cached locally and refreshed daily.

    Usage
    -----
        feed = WGCFeed()
        series = await feed.fetch_all()
        # series: {"wgc_total_demand": pd.Series, "wgc_etf_flow": pd.Series, ...}

        # Inject into MacroStore:
        from ml.macro_store import macro_store
        for name, s in series.items():
            for ts, val in s.items():
                macro_store.update(name, ts, val)
    """

    def __init__(self) -> None:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self._last_fetch: datetime | None = None
        self._cached_series: dict[str, pd.Series] = {}

    # ── HTTP ──────────────────────────────────────────────────────────────────

    async def _fetch_url(self, url: str) -> str | None:
        """
        Fetch a URL and return the response body as text.

        Tries aiohttp first, falls back to requests in a thread executor.
        Returns None on any error.
        """
        try:
            import aiohttp

            timeout = aiohttp.ClientTimeout(total=_HTTP_TIMEOUT)
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (compatible; HOPEFX-AI-TRADING/1.0; +https://github.com/HACKLOVE340/HOPEFX-AI-TRADING)"
                ),
                "Accept": "text/csv,application/csv,text/plain,*/*",
            }
            async with aiohttp.ClientSession(timeout=timeout) as session:  # noqa: SIM117
                async with session.get(url, headers=headers, allow_redirects=True) as resp:
                    if resp.status == 200:  # noqa: PLR2004
                        return await resp.text(encoding="utf-8", errors="replace")
                    logger.warning("WGC fetch %s returned HTTP %d", url, resp.status)
                    return None
        except ImportError:
            pass
        except Exception as exc:
            logger.warning("WGC aiohttp fetch failed for %s: %s", url, exc)

        # Fallback: requests in thread executor
        try:
            import requests

            loop = asyncio.get_event_loop()

            def _sync_get() -> str | None:
                r = requests.get(
                    url,
                    timeout=_HTTP_TIMEOUT,
                    headers={
                        "User-Agent": ("Mozilla/5.0 (compatible; HOPEFX-AI-TRADING/1.0)"),
                        "Accept": "text/csv,application/csv,text/plain,*/*",
                    },
                    allow_redirects=True,
                )
                if r.status_code == 200:  # noqa: PLR2004
                    return r.text
                logger.warning("WGC requests fetch %s returned HTTP %d", url, r.status_code)
                return None

            return await loop.run_in_executor(None, _sync_get)
        except Exception as exc:
            logger.warning("WGC requests fetch failed for %s: %s", url, exc)
            return None

    # ── Cache ─────────────────────────────────────────────────────────────────

    def _cache_path(self, filename: str) -> Path:
        return _CACHE_DIR / filename

    def _write_cache(self, filename: str, content: str) -> None:
        try:
            path = self._cache_path(filename)
            path.write_text(content, encoding="utf-8")
            logger.debug("WGC: cached %s (%d bytes)", filename, len(content))
        except Exception as exc:
            logger.warning("WGC: cache write failed for %s: %s", filename, exc)

    def _read_cache(self, filename: str) -> str | None:
        try:
            path = self._cache_path(filename)
            if path.exists():
                age_s = (datetime.now(UTC) - datetime.fromtimestamp(path.stat().st_mtime, UTC)).total_seconds()
                if age_s < _REFRESH_INTERVAL:
                    return path.read_text(encoding="utf-8")
                logger.debug("WGC: cache stale for %s (age=%.0fs)", filename, age_s)
        except Exception as exc:
            logger.debug("WGC: cache read failed for %s: %s", filename, exc)
        return None

    # ── Fetch ─────────────────────────────────────────────────────────────────

    async def _fetch_demand(self) -> dict[str, pd.Series]:
        """
        Fetch WGC quarterly gold demand data.

        Tries the direct CSV download URL first. If WGC's download endpoint
        returns HTML (they sometimes gate downloads), falls back to the cached
        file. If no cache exists, returns an empty dict — the MacroStore will
        use zero-fill until the next successful fetch.
        """
        cached = self._read_cache(_DEMAND_CACHE_FILE)
        if cached:
            logger.debug("WGC: using cached demand data")
            return _csv_to_series(cached, _DEMAND_COL_VARIANTS)

        text = await self._fetch_url(_WGC_DEMAND_CSV_URL)
        if text and "," in text and len(text) > 200:  # noqa: PLR2004
            # Validate it looks like CSV (not an HTML error page)
            if not text.strip().startswith("<!"):
                self._write_cache(_DEMAND_CACHE_FILE, text)
                return _csv_to_series(text, _DEMAND_COL_VARIANTS)
            logger.warning(
                "WGC demand URL returned HTML — WGC may require browser session. Place a manually downloaded CSV at %s",
                self._cache_path(_DEMAND_CACHE_FILE),
            )
        else:
            logger.warning(
                "WGC demand fetch returned no usable data. Place a manually downloaded CSV at %s",
                self._cache_path(_DEMAND_CACHE_FILE),
            )

        return {}

    async def _fetch_etf_flow(self) -> dict[str, pd.Series]:
        """
        Fetch WGC monthly ETF holdings and flow data.

        Same fallback logic as _fetch_demand().
        """
        cached = self._read_cache(_ETF_CACHE_FILE)
        if cached:
            logger.debug("WGC: using cached ETF flow data")
            return _csv_to_series(cached, _ETF_COL_VARIANTS)

        text = await self._fetch_url(_WGC_ETF_CSV_URL)
        if text and "," in text and len(text) > 200:  # noqa: PLR2004
            if not text.strip().startswith("<!"):
                self._write_cache(_ETF_CACHE_FILE, text)
                return _csv_to_series(text, _ETF_COL_VARIANTS)
            logger.warning(
                "WGC ETF flow URL returned HTML — WGC may require browser session. "
                "Place a manually downloaded CSV at %s",
                self._cache_path(_ETF_CACHE_FILE),
            )
        else:
            logger.warning(
                "WGC ETF flow fetch returned no usable data. Place a manually downloaded CSV at %s",
                self._cache_path(_ETF_CACHE_FILE),
            )

        return {}

    async def fetch_all(self) -> dict[str, pd.Series]:
        """
        Fetch all WGC series concurrently.

        Returns a dict of {series_name: pd.Series(float, DatetimeIndex[UTC])}.
        Series that could not be fetched are omitted — callers must handle
        missing keys gracefully.
        """
        demand_task = asyncio.create_task(self._fetch_demand())
        etf_task = asyncio.create_task(self._fetch_etf_flow())

        demand_series, etf_series = await asyncio.gather(demand_task, etf_task, return_exceptions=True)

        results: dict[str, pd.Series] = {}

        if isinstance(demand_series, dict):
            results.update(demand_series)
        else:
            logger.warning("WGC demand fetch raised: %s", demand_series)

        if isinstance(etf_series, dict):
            results.update(etf_series)
        else:
            logger.warning("WGC ETF flow fetch raised: %s", etf_series)

        self._last_fetch = datetime.now(UTC)
        self._cached_series = results

        loaded = list(results.keys())
        logger.info(
            "WGC: fetched %d series: %s",
            len(loaded),
            loaded if loaded else "(none — check cache dir or download manually)",
        )
        return results

    def load_from_csv(self, path: str | Path, series_name: str) -> pd.Series | None:
        """
        Load a single WGC series from a manually downloaded CSV file.

        Expected format (WGC standard export):
            Date,<series_column>,...
            Q1 2020,1083.8,...
            Q2 2020,960.5,...

        This is the recommended path when WGC's download endpoint requires
        a browser session. Download the CSV manually from gold.org and place
        it in WGC_CACHE_DIR.

        Returns the parsed Series, or None on failure.
        """
        p = Path(path)
        if not p.exists():
            logger.warning("WGC.load_from_csv: file not found: %s", p)
            return None
        try:
            text = p.read_text(encoding="utf-8")
            # Determine which column map to use based on series_name
            col_map = _ETF_COL_VARIANTS if series_name == "wgc_etf_flow" else _DEMAND_COL_VARIANTS
            parsed = _csv_to_series(text, col_map)
            return parsed.get(series_name)
        except Exception as exc:
            logger.warning("WGC.load_from_csv failed for %s: %s", path, exc)
            return None

    def inject_into_macro_store(self, series: dict[str, pd.Series]) -> int:
        """
        Inject fetched WGC series into the ml.macro_store singleton.

        Each observation is upserted via macro_store.update() so the ML
        pipeline immediately sees the new values on the next inference call.

        Returns the number of series successfully injected.
        """
        try:
            from ml.macro_store import macro_store
        except ImportError:
            logger.warning("WGC: ml.macro_store not available — skipping injection")
            return 0

        injected = 0
        for name, s in series.items():
            if s.empty:
                continue
            try:
                for ts, val in s.items():
                    macro_store.update(name, ts, float(val))
                injected += 1
                logger.info(
                    "WGC: injected %s into MacroStore (%d obs, latest=%.1f t)",
                    name,
                    len(s),
                    float(s.iloc[-1]),
                )
            except Exception as exc:
                logger.warning("WGC: MacroStore injection failed for %s: %s", name, exc)

        return injected

    async def fetch_and_inject(self) -> dict[str, Any]:
        """
        Fetch all WGC series and inject them into MacroStore.

        Returns a status dict suitable for health/status endpoints.
        """
        series = await self.fetch_all()
        injected = self.inject_into_macro_store(series)
        return {
            "series_fetched": list(series.keys()),
            "series_injected": injected,
            "last_fetch": self._last_fetch.isoformat() if self._last_fetch else None,
            "cache_dir": str(_CACHE_DIR),
        }

    def health(self) -> dict[str, Any]:
        """Return health/status dict for monitoring endpoints."""
        series_info: dict[str, Any] = {}
        for name, s in self._cached_series.items():
            if not s.empty:
                series_info[name] = {
                    "observations": len(s),
                    "latest_value": float(s.iloc[-1]),
                    "latest_date": s.index[-1].date().isoformat(),
                }
        return {
            "loaded": bool(self._cached_series),
            "series_count": len(self._cached_series),
            "last_fetch": self._last_fetch.isoformat() if self._last_fetch else None,
            "cache_dir": str(_CACHE_DIR),
            "series": series_info,
        }


# ── Module-level singleton ────────────────────────────────────────────────────

wgc_feed = WGCFeed()
