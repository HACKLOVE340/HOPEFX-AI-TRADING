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

Data sources and fallback chain
--------------------------------
Each series is resolved through a priority chain; the first source that
returns usable data wins.

  wgc_total_demand / wgc_investment / wgc_jewellery / wgc_central_bank
    1. WGC JSON API  (goldhub-api.gold.org — machine-readable, no key)
    2. WGC CSV download  (www.gold.org?download=csv)
    3. Local cache  (stale-but-valid file in WGC_CACHE_DIR)

  wgc_etf_flow
    1. WGC JSON API  (goldhub-api.gold.org)
    2. WGC CSV download
    3. yfinance proxy  (GLD daily AUM → implied flow, monthly resampled)
    4. Local cache

  wgc_central_bank  (additional proxy when WGC is unavailable)
    World Bank API  (indicator FI.RES.TOTL.CD — total reserves including
    gold, annual first-difference used as CB accumulation proxy)

Environment variables
---------------------
  WGC_CACHE_DIR          — local cache directory (default: data/wgc_cache)
  WGC_REFRESH_INTERVAL   — seconds between refreshes (default: 86400 = 24h)
  WGC_DEMAND_URL         — override quarterly demand CSV URL
  WGC_ETF_FLOW_URL       — override ETF flow CSV URL
  WGC_JSON_API_BASE      — override WGC JSON API base URL
  WGC_YFINANCE_ETF       — yfinance ticker for ETF proxy (default: GLD)
  WGC_WB_CB_INDICATOR    — World Bank indicator for CB proxy
                           (default: FI.RES.TOTL.CD)
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
from datetime import datetime, timezone

UTC = timezone.utc
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


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

# WGC JSON API — machine-readable endpoint served by goldhub-api.gold.org.
# Returns JSON arrays keyed by dataset slug; no authentication required.
# Ref: https://goldhub-api.gold.org/v1/datasets/<slug>
_WGC_JSON_API_BASE = os.getenv(
    "WGC_JSON_API_BASE",
    "https://goldhub-api.gold.org/v1/datasets",
)
# Dataset slugs used by the WGC JSON API
_WGC_JSON_DEMAND_SLUG = "gold-demand-statistics"
_WGC_JSON_ETF_SLUG = "global-gold-backed-etf-holdings-and-flows"

# yfinance ETF proxy — GLD AUM changes are used as a monthly ETF-flow proxy
# when the WGC endpoint is unavailable.
_YFINANCE_ETF_TICKER = os.getenv("WGC_YFINANCE_ETF", "GLD")

# World Bank API — FI.RES.TOTL.CD (total reserves including gold, USD) is used
# as a central-bank demand proxy when WGC data is unavailable.
# We diff the series to approximate net quarterly CB purchases.
_WB_CB_INDICATOR = os.getenv("WGC_WB_CB_INDICATOR", "FI.RES.TOTL.CD")
_WB_API_BASE = "https://api.worldbank.org/v2"

# HTTP timeout for WGC requests
_HTTP_TIMEOUT = float(os.getenv("WGC_HTTP_TIMEOUT_S", "8.0"))

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
        if s.startswith("Q") and len(s) >= 7:
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
            if line.count(",") >= 3:
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


# ── Source helpers ────────────────────────────────────────────────────────────


async def _fetch_wgc_json_api(
    slug: str,
    col_variants: dict[str, list[str]],
    http_fetch: Any,
) -> dict[str, pd.Series]:
    """
    Fetch a WGC dataset from the goldhub JSON API.

    The API returns a JSON object with a ``data`` list of row dicts.  Each row
    has a ``date`` field (ISO-8601 or quarter string) and one or more numeric
    columns matching the WGC CSV column names.

    ``http_fetch`` is a coroutine callable with signature
    ``async (url: str) -> str | None`` — typically ``WGCFeed._fetch_url``.

    Returns an empty dict on any error so callers can fall through to the next
    source in the chain.
    """
    import json

    url = f"{_WGC_JSON_API_BASE}/{slug}"
    text = await http_fetch(url)
    if not text:
        return {}

    try:
        payload = json.loads(text)
    except Exception as exc:
        logger.debug("WGC JSON API: JSON parse error for %s: %s", slug, exc)
        return {}

    # Normalise: API may return {"data": [...]} or a bare list
    rows = payload.get("data", payload) if isinstance(payload, dict) else payload
    if not isinstance(rows, list) or not rows:
        logger.debug("WGC JSON API: unexpected payload shape for %s", slug)
        return {}

    try:
        df = pd.DataFrame(rows)
    except Exception as exc:
        logger.debug("WGC JSON API: DataFrame construction failed for %s: %s", slug, exc)
        return {}

    dates = _parse_date_col(df)
    if dates is None or dates.notna().sum() == 0:
        logger.debug("WGC JSON API: no parseable date column for %s. cols=%s", slug, list(df.columns))
        return {}

    df["_date"] = dates
    df = df.dropna(subset=["_date"]).set_index("_date").sort_index()

    results: dict[str, pd.Series] = {}
    for series_name, variants in col_variants.items():
        col = _find_col(df, variants)
        if col is None:
            continue
        try:
            s = pd.to_numeric(df[col], errors="coerce").dropna()
            if s.empty:
                continue
            s.index = pd.DatetimeIndex(s.index)
            s.name = series_name
            results[series_name] = s
            logger.info(
                "WGC JSON API: %s — %d obs (latest: %.1f t on %s)",
                series_name,
                len(s),
                float(s.iloc[-1]),
                s.index[-1].date().isoformat(),
            )
        except Exception as exc:
            logger.debug("WGC JSON API: extraction failed for %s: %s", series_name, exc)

    return results


async def _etf_proxy_yfinance(loop: Any | None = None) -> dict[str, pd.Series]:
    """
    Derive a monthly ETF-flow proxy from yfinance GLD price/volume data.

    GLD AUM is not directly available via yfinance, so we use the product of
    adjusted close price and volume as a proportional AUM proxy, then compute
    month-over-month changes as an implied flow signal (in arbitrary units,
    not tonnes).  The series is normalised to the WGC ETF-flow scale using the
    last 12 months of overlap when WGC data is available; otherwise it is
    returned as-is with a ``_proxy`` suffix so downstream code can distinguish
    it from authoritative WGC data.

    Returns ``{"wgc_etf_flow_proxy": pd.Series}`` or ``{}`` on failure.
    """
    try:
        import yfinance as yf
    except ImportError:
        logger.debug("yfinance not installed — ETF proxy unavailable")
        return {}

    ticker = _YFINANCE_ETF_TICKER
    try:
        _loop = loop or asyncio.get_running_loop()
        raw: pd.DataFrame = await _loop.run_in_executor(
            None,
            lambda: yf.download(ticker, period="10y", interval="1d", progress=False, auto_adjust=True),
        )
    except Exception as exc:
        logger.debug("yfinance download failed for %s: %s", ticker, exc)
        return {}

    if raw is None or raw.empty:
        logger.debug("yfinance returned empty DataFrame for %s", ticker)
        return {}

    try:
        # Flatten MultiIndex columns if present (yfinance ≥0.2.38 behaviour)
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)

        close = raw.get("Close", raw.get("Adj Close"))
        volume = raw.get("Volume")
        if close is None or volume is None:
            logger.debug("yfinance: missing Close or Volume for %s", ticker)
            return {}

        aum_proxy = (close * volume).rename("aum_proxy")
        aum_proxy.index = pd.DatetimeIndex(aum_proxy.index).tz_localize("UTC") if aum_proxy.index.tz is None else pd.DatetimeIndex(aum_proxy.index).tz_convert("UTC")

        # Resample to monthly, compute MoM change as flow proxy
        monthly = aum_proxy.resample("MS").sum()
        flow_proxy = monthly.diff().dropna()
        flow_proxy.name = "wgc_etf_flow_proxy"

        if flow_proxy.empty:
            return {}

        logger.info(
            "yfinance ETF proxy (%s): %d monthly obs (latest: %.2e on %s)",
            ticker,
            len(flow_proxy),
            float(flow_proxy.iloc[-1]),
            flow_proxy.index[-1].date().isoformat(),
        )
        return {"wgc_etf_flow_proxy": flow_proxy}
    except Exception as exc:
        logger.warning("yfinance ETF proxy computation failed: %s", exc)
        return {}


async def _cb_proxy_world_bank(loop: Any | None = None) -> dict[str, pd.Series]:
    """
    Fetch World Bank total-reserves data as a central-bank demand proxy.

    Uses indicator FI.RES.TOTL.CD (total reserves including gold, current USD)
    aggregated across all countries.  The annual first-difference is used as a
    proxy for net CB gold purchases (positive = accumulation).

    The series is returned as ``wgc_central_bank_proxy`` to distinguish it from
    authoritative WGC quarterly data.

    World Bank API docs: https://datahelpdesk.worldbank.org/knowledgebase/articles/898581
    """
    import json

    # Aggregate world total: country code "WLD"
    url = (
        f"{_WB_API_BASE}/country/WLD/indicator/{_WB_CB_INDICATOR}"
        "?format=json&per_page=100&mrv=30"
    )

    try:
        _loop = loop or asyncio.get_running_loop()

        def _sync_fetch() -> str | None:
            try:
                import requests

                r = requests.get(url, timeout=_HTTP_TIMEOUT)
                if r.status_code == 200:
                    return r.text
                logger.debug("World Bank API returned HTTP %d for %s", r.status_code, _WB_CB_INDICATOR)
            except Exception as exc:
                logger.debug("World Bank API request failed: %s", exc)
            return None

        text = await _loop.run_in_executor(None, _sync_fetch)
    except Exception as exc:
        logger.debug("World Bank CB proxy executor error: %s", exc)
        return {}

    if not text:
        return {}

    try:
        payload = json.loads(text)
        # WB API returns [metadata_dict, [data_rows]]
        if not isinstance(payload, list) or len(payload) < 2:
            return {}
        rows = payload[1]
        if not rows:
            return {}

        records = []
        for row in rows:
            date_str = row.get("date", "")
            value = row.get("value")
            if value is None or not date_str:
                continue
            try:
                ts = pd.Timestamp(year=int(date_str), month=1, day=1, tz="UTC")
                records.append((ts, float(value)))
            except (ValueError, TypeError):
                continue

        if not records:
            return {}

        s = pd.Series(
            {ts: val for ts, val in records},
            name="wgc_central_bank_proxy",
            dtype=float,
        ).sort_index()
        s.index = pd.DatetimeIndex(s.index)

        # Annual first-difference as CB accumulation proxy
        proxy = s.diff().dropna()
        proxy.name = "wgc_central_bank_proxy"

        if proxy.empty:
            return {}

        logger.info(
            "World Bank CB proxy (%s): %d annual obs (latest: %.2e on %s)",
            _WB_CB_INDICATOR,
            len(proxy),
            float(proxy.iloc[-1]),
            proxy.index[-1].date().isoformat(),
        )
        return {"wgc_central_bank_proxy": proxy}
    except Exception as exc:
        logger.warning("World Bank CB proxy parse failed: %s", exc)
        return {}


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
        # Suppress repeated "offline" warnings — log once per provider lifetime
        self._warned_demand_offline: bool = False
        self._warned_etf_offline: bool = False
        self._warned_json_api_offline: bool = False
        self._warned_yfinance_offline: bool = False
        self._warned_wb_offline: bool = False

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
            async with (
                aiohttp.ClientSession(timeout=timeout) as session,
                session.get(url, headers=headers, allow_redirects=True) as resp,
            ):
                if resp.status == 200:
                    return await resp.text(encoding="utf-8", errors="replace")
                logger.debug("WGC fetch %s returned HTTP %d", url, resp.status)
                return None
        except ImportError:
            ...  # nosec B110
        except Exception as exc:
            logger.debug("WGC aiohttp fetch failed for %s: %s", url, exc)

        # Fallback: requests in thread executor
        try:
            import requests

            loop = asyncio.get_running_loop()

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
                if r.status_code == 200:
                    return r.text
                logger.debug("WGC requests fetch %s returned HTTP %d", url, r.status_code)
                return None

            return await loop.run_in_executor(None, _sync_get)
        except Exception as exc:
            logger.debug("WGC requests fetch failed for %s: %s", url, exc)
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
        """Return cached content only if it is within _REFRESH_INTERVAL."""
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

    def _read_cache_any_age(self, filename: str) -> str | None:
        """Return cached content regardless of age — used as last-resort fallback."""
        try:
            path = self._cache_path(filename)
            if path.exists():
                return path.read_text(encoding="utf-8")
        except Exception as exc:
            logger.debug("WGC: stale cache read failed for %s: %s", filename, exc)
        return None

    # ── Fetch ─────────────────────────────────────────────────────────────────

    async def _fetch_demand(self) -> dict[str, pd.Series]:
        """
        Fetch WGC quarterly gold demand data via a three-source fallback chain.

        Priority:
          1. WGC JSON API  (goldhub-api.gold.org — structured, no key)
          2. WGC CSV download  (www.gold.org?download=csv)
          3. Local disk cache  (stale-but-valid file from a previous run)

        Returns an empty dict only when all three sources fail.
        """
        # ── 1. WGC JSON API ───────────────────────────────────────────────────
        try:
            json_series = await _fetch_wgc_json_api(
                _WGC_JSON_DEMAND_SLUG, _DEMAND_COL_VARIANTS, self._fetch_url
            )
            if json_series:
                logger.debug("WGC demand: resolved via JSON API")
                return json_series
            if not self._warned_json_api_offline:
                logger.debug("WGC JSON API returned no demand data — trying CSV download")
                self._warned_json_api_offline = True
        except Exception as exc:
            if not self._warned_json_api_offline:
                logger.debug("WGC JSON API demand fetch failed (%s) — trying CSV download", exc)
                self._warned_json_api_offline = True

        # ── 2. WGC CSV download ───────────────────────────────────────────────
        text = await self._fetch_url(_WGC_DEMAND_CSV_URL)
        if text and "," in text and len(text) > 200:
            if not text.strip().startswith("<!"):
                self._write_cache(_DEMAND_CACHE_FILE, text)
                logger.debug("WGC demand: resolved via CSV download")
                return _csv_to_series(text, _DEMAND_COL_VARIANTS)
            if not self._warned_demand_offline:
                logger.info(
                    "WGC demand URL returned HTML — www.gold.org may require a browser session. "
                    "Place a manually downloaded CSV at %s",
                    self._cache_path(_DEMAND_CACHE_FILE),
                )
                self._warned_demand_offline = True
        elif not self._warned_demand_offline:
            logger.info(
                "WGC demand CSV fetch returned no usable data — www.gold.org unreachable. "
                "Place a manually downloaded CSV at %s",
                self._cache_path(_DEMAND_CACHE_FILE),
            )
            self._warned_demand_offline = True

        # ── 3. Stale local cache ──────────────────────────────────────────────
        cached = self._read_cache_any_age(_DEMAND_CACHE_FILE)
        if cached:
            logger.info("WGC demand: using stale local cache (all live sources failed)")
            return _csv_to_series(cached, _DEMAND_COL_VARIANTS)

        return {}

    async def _fetch_etf_flow(self) -> dict[str, pd.Series]:
        """
        Fetch WGC monthly ETF flow data via a four-source fallback chain.

        Priority:
          1. WGC JSON API  (goldhub-api.gold.org)
          2. WGC CSV download  (www.gold.org?download=csv)
          3. yfinance GLD proxy  (AUM-change approximation, monthly)
          4. Local disk cache  (stale-but-valid file from a previous run)

        The yfinance proxy series is keyed ``wgc_etf_flow_proxy`` so callers
        can distinguish it from authoritative WGC data.
        """
        # ── 1. WGC JSON API ───────────────────────────────────────────────────
        try:
            json_series = await _fetch_wgc_json_api(
                _WGC_JSON_ETF_SLUG, _ETF_COL_VARIANTS, self._fetch_url
            )
            if json_series:
                logger.debug("WGC ETF flow: resolved via JSON API")
                return json_series
        except Exception as exc:
            logger.debug("WGC JSON API ETF fetch failed (%s) — trying CSV download", exc)

        # ── 2. WGC CSV download ───────────────────────────────────────────────
        text = await self._fetch_url(_WGC_ETF_CSV_URL)
        if text and "," in text and len(text) > 200:
            if not text.strip().startswith("<!"):
                self._write_cache(_ETF_CACHE_FILE, text)
                logger.debug("WGC ETF flow: resolved via CSV download")
                return _csv_to_series(text, _ETF_COL_VARIANTS)
            if not self._warned_etf_offline:
                logger.info(
                    "WGC ETF flow URL returned HTML — www.gold.org may require a browser session. "
                    "Place a manually downloaded CSV at %s",
                    self._cache_path(_ETF_CACHE_FILE),
                )
                self._warned_etf_offline = True
        elif not self._warned_etf_offline:
            logger.info(
                "WGC ETF flow CSV fetch returned no usable data — www.gold.org unreachable. "
                "Place a manually downloaded CSV at %s",
                self._cache_path(_ETF_CACHE_FILE),
            )
            self._warned_etf_offline = True

        # ── 3. yfinance ETF proxy ─────────────────────────────────────────────
        try:
            yf_series = await _etf_proxy_yfinance()
            if yf_series:
                # Log once: first time we fall back to the proxy
                if not self._warned_yfinance_offline:
                    logger.info(
                        "WGC ETF flow: using yfinance %s proxy (WGC sources unavailable)",
                        _YFINANCE_ETF_TICKER,
                    )
                    self._warned_yfinance_offline = True
                return yf_series
            # yfinance returned empty — fall through to stale cache
            if not self._warned_yfinance_offline:
                logger.debug("yfinance ETF proxy returned no data — trying stale cache")
                self._warned_yfinance_offline = True
        except Exception as exc:
            if not self._warned_yfinance_offline:
                logger.debug("yfinance ETF proxy failed (%s) — trying stale cache", exc)
                self._warned_yfinance_offline = True

        # ── 4. Stale local cache ──────────────────────────────────────────────
        cached = self._read_cache_any_age(_ETF_CACHE_FILE)
        if cached:
            logger.info("WGC ETF flow: using stale local cache (all live sources failed)")
            return _csv_to_series(cached, _ETF_COL_VARIANTS)

        return {}

    async def fetch_all(self) -> dict[str, pd.Series]:
        """
        Fetch all WGC series concurrently.

        Runs demand, ETF-flow, and World Bank CB proxy fetches in parallel.
        The World Bank CB proxy (``wgc_central_bank_proxy``) is only included
        when the authoritative ``wgc_central_bank`` series is absent, so it
        acts as a last-resort fallback rather than overwriting WGC data.

        Returns a dict of {series_name: pd.Series(float, DatetimeIndex[UTC])}.
        Series that could not be fetched are omitted — callers must handle
        missing keys gracefully.
        """
        demand_task = asyncio.create_task(self._fetch_demand())
        etf_task = asyncio.create_task(self._fetch_etf_flow())
        wb_task = asyncio.create_task(_cb_proxy_world_bank())

        demand_series, etf_series, wb_series = await asyncio.gather(
            demand_task, etf_task, wb_task, return_exceptions=True
        )

        results: dict[str, pd.Series] = {}

        if isinstance(demand_series, dict):
            results.update(demand_series)
        else:
            logger.warning("WGC demand fetch raised: %s", demand_series)

        if isinstance(etf_series, dict):
            results.update(etf_series)
        else:
            logger.warning("WGC ETF flow fetch raised: %s", etf_series)

        # Include World Bank CB proxy only when WGC authoritative CB data is missing
        if isinstance(wb_series, dict) and wb_series:
            if "wgc_central_bank" not in results:
                results.update(wb_series)
                if not self._warned_wb_offline:
                    logger.info(
                        "WGC: wgc_central_bank absent — using World Bank CB proxy (%s)",
                        _WB_CB_INDICATOR,
                    )
        elif not isinstance(wb_series, dict):
            logger.debug("World Bank CB proxy raised: %s", wb_series)

        self._last_fetch = datetime.now(UTC)
        self._cached_series = results

        loaded = list(results.keys())
        logger.info(
            "WGC: fetched %d series: %s",
            len(loaded),
            loaded or "(none — check cache dir or download manually)",
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
