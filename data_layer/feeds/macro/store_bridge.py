# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
data_layer/feeds/macro/store_bridge.py
========================================
MacroStoreBridge — keeps ml/macro_store.py populated from FRED.

The existing MacroStore (ml/macro_store.py) is the ML pipeline's source
of truth for daily macro series. This bridge:
  1. Fetches all FRED series on startup (concurrent, with retry)
  2. Loads them into the MacroStore singleton via _series dict injection
  3. Runs a daily refresh at 18:00 UTC (after US market close)
  4. Exposes get_ml_features() for real-time macro feature injection

This is the correct integration point — the ML pipeline continues to
call macro_store.align_to_hourly() exactly as before, but now the store
is populated from FRED automatically rather than requiring manual CSV files.

Graceful degradation: if FRED is unavailable, falls back to CSV files
in data/macro/ (the original MacroStore.load_defaults() path).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

UTC = timezone.utc

from data_layer.feeds.macro.fred import FREDFeed, FRED_SERIES, fred_feed
from data_layer.feeds.macro.wgc import WGCFeed, wgc_feed
import contextlib

logger = logging.getLogger(__name__)

# Startup retry config
_STARTUP_MAX_RETRIES = int(__import__("os").getenv("MACRO_BRIDGE_STARTUP_RETRIES", "3"))
_STARTUP_RETRY_DELAY = float(__import__("os").getenv("MACRO_BRIDGE_STARTUP_RETRY_S", "5.0"))


class MacroStoreBridge:
    """
    Bridges FRED and WGC data into ml.macro_store.MacroStore.

    Loads FRED macro series (DXY, yields, CPI, VIX, M2) and WGC gold demand
    series (total demand, investment, central bank, jewellery, ETF flow) into
    the MacroStore singleton at startup and refreshes them daily.

    Usage:
        bridge = MacroStoreBridge()
        await bridge.start()   # loads FRED + WGC data + starts daily refresh
    """

    def __init__(
        self,
        fred: FREDFeed | None = None,
        wgc: WGCFeed | None = None,
    ) -> None:
        self._fred = fred or fred_feed
        self._wgc = wgc or wgc_feed
        self._loaded = False
        self._running = False
        self._last_refresh: datetime | None = None
        self._series_loaded: int = 0
        self._wgc_series_loaded: int = 0

        # Prometheus
        self._prom_series_count = None
        self._prom_last_refresh = None
        self._init_prometheus()

    def _init_prometheus(self) -> None:
        try:
            from prometheus_client import Gauge, REGISTRY

            def _gauge(name: str, doc: str):
                try:
                    return Gauge(name, doc)
                except ValueError:
                    return REGISTRY._names_to_collectors.get(name)

            self._prom_series_count = _gauge(
                "hopefx_macro_fred_series_loaded",
                "Number of FRED series loaded into MacroStore",
            )
            self._prom_last_refresh = _gauge(
                "hopefx_macro_fred_last_refresh_epoch",
                "Unix epoch of last FRED refresh",
            )
        except Exception as _exc:
            logger.debug("MacroStoreBridge: Prometheus init skipped: %s", _exc)

    async def start(self) -> None:
        """
        Load FRED and WGC data into MacroStore and start daily refresh.

        FRED: retries up to MACRO_BRIDGE_STARTUP_RETRIES times with exponential
        backoff before falling back to CSV files in data/macro/.

        WGC: single attempt at startup (quarterly data changes slowly).
        Failures are non-fatal — WGC series will be zero-filled until the
        next daily refresh succeeds.
        """
        self._running = True

        # Attempt FRED load with retry
        for attempt in range(1, _STARTUP_MAX_RETRIES + 1):
            await self._load_fred_into_store()
            if self._loaded:
                break
            if attempt < _STARTUP_MAX_RETRIES:
                wait = _STARTUP_RETRY_DELAY * (2 ** (attempt - 1))
                logger.warning(
                    "MacroStoreBridge: FRED load attempt %d/%d failed — retrying in %.1fs",
                    attempt,
                    _STARTUP_MAX_RETRIES,
                    wait,
                )
                await asyncio.sleep(wait)
            else:
                logger.warning(
                    "MacroStoreBridge: all %d FRED load attempts failed — falling back to CSV files in data/macro/",
                    _STARTUP_MAX_RETRIES,
                )
                self._load_csv_fallback()

        # Load WGC demand data (non-blocking — failure is non-fatal)
        await self._load_wgc_into_store()

        asyncio.create_task(self._daily_refresh_loop(), name="macro_store_bridge_refresh")

    async def stop(self) -> None:
        """Close FRED HTTP session and stop refresh loop."""
        self._running = False
        try:
            await self._fred.close()
        except Exception as exc:
            logger.debug("MacroStoreBridge.stop: FRED close error: %s", exc)

    def _load_csv_fallback(self) -> None:
        """
        Load macro series from CSV files in data/macro/ when FRED is unavailable.

        Delegates to MacroStore.load_defaults() which reads the pre-bundled
        CSV files. This ensures the ML pipeline always has some macro context
        even without a FRED API key or network access.
        """
        try:
            from ml.macro_store import macro_store

            macro_store.load_defaults()
            loaded = len(macro_store._series)
            if loaded > 0:
                self._loaded = True
                self._series_loaded = loaded
                self._last_refresh = datetime.now(UTC)
                logger.info(
                    "MacroStoreBridge: CSV fallback loaded %d series from data/macro/",
                    loaded,
                )
            else:
                logger.warning(
                    "MacroStoreBridge: CSV fallback found no series in data/macro/ — "
                    "macro features will be zero until FRED is available"
                )
        except Exception as exc:
            logger.warning("MacroStoreBridge._load_csv_fallback error: %s", exc)

    async def _load_wgc_into_store(self) -> None:
        """Fetch all WGC series and inject into MacroStore singleton."""
        try:
            logger.info("MacroStoreBridge: fetching WGC gold demand data...")
            series = await self._wgc.fetch_all()
            injected = self._wgc.inject_into_macro_store(series)
            self._wgc_series_loaded = injected

            if self._prom_series_count and injected > 0:
                # Increment total series count to include WGC
                with contextlib.suppress(Exception):
                    self._prom_series_count.set(self._series_loaded + injected)

            if injected > 0:
                logger.info(
                    "MacroStoreBridge: WGC injected %d series into MacroStore",
                    injected,
                )
            else:
                logger.warning(
                    "MacroStoreBridge: WGC returned no series — place CSV files in %s or check WGC_CACHE_DIR",
                    "data/wgc_cache",
                )
        except Exception as exc:
            logger.warning("MacroStoreBridge._load_wgc_into_store error: %s", exc)

    async def _load_fred_into_store(self) -> None:
        """Fetch all FRED series and load into MacroStore singleton."""
        try:
            from ml.macro_store import macro_store

            logger.info("MacroStoreBridge: fetching %d FRED series...", len(FRED_SERIES))
            all_series = await self._fred.fetch_all()

            loaded = 0
            for name, series in all_series.items():
                if series.empty:
                    logger.debug("MacroStoreBridge: %s empty — skipping", name)
                    continue
                macro_store._series[name] = series
                loaded += 1
                logger.info(
                    "MacroStoreBridge: loaded %s (%d obs, latest=%.4f)",
                    name,
                    len(series),
                    float(series.iloc[-1]) if not series.empty else 0.0,
                )

            self._loaded = True
            self._series_loaded = loaded
            self._last_refresh = datetime.now(UTC)

            if self._prom_series_count:
                self._prom_series_count.set(loaded)
            if self._prom_last_refresh:
                self._prom_last_refresh.set(self._last_refresh.timestamp())

            logger.info(
                "MacroStoreBridge: MacroStore populated with %d/%d series",
                loaded,
                len(FRED_SERIES),
            )

        except ImportError:
            logger.warning("MacroStoreBridge: ml.macro_store not available — macro features will use CSV fallback")
        except Exception as exc:
            logger.error("MacroStoreBridge load error: %s", exc)

    async def _daily_refresh_loop(self) -> None:
        """
        Refresh FRED and WGC data daily at 18:00 UTC (after US market close).

        FRED: refreshed every day — yields, DXY, and CPI update daily/monthly.
        WGC: refreshed every day — ETF flows update monthly, demand quarterly.
             The WGC feed's own cache TTL (WGC_REFRESH_INTERVAL) prevents
             redundant HTTP requests when data hasn't changed.
        """
        while self._running:
            now = datetime.now(UTC)
            target = now.replace(hour=18, minute=0, second=0, microsecond=0)
            if target <= now:
                target = target + timedelta(days=1)
            wait_s = (target - now).total_seconds()
            logger.debug(
                "MacroStoreBridge: next FRED+WGC refresh in %.1f hours",
                wait_s / 3600.0,
            )
            await asyncio.sleep(wait_s)
            # Run FRED and WGC refreshes concurrently
            await asyncio.gather(
                self._load_fred_into_store(),
                self._load_wgc_into_store(),
                return_exceptions=True,
            )

    def get_ml_features(self) -> dict[str, float]:
        """
        Return latest macro values as flat ML features.

        Keys are prefixed macro_ (e.g. macro_dxy, macro_us10y).
        These are the raw latest values — the ML pipeline uses
        macro_store.align_to_hourly() for time-series alignment.
        """
        try:
            from ml.macro_store import macro_store

            snap = macro_store.snapshot()
            features: dict[str, float] = {}
            for name, info in snap.items():
                if info and info.get("value") is not None:
                    features[f"macro_{name}"] = float(info["value"])
                else:
                    features[f"macro_{name}"] = 0.0
            return features
        except Exception as exc:
            logger.debug("MacroStoreBridge.get_ml_features error: %s", exc)
            return {}

    def snapshot(self) -> dict[str, object]:
        """
        Return a full macro snapshot for caching and health endpoints.

        Includes health info, ML features, and per-series latest values
        with their observation dates.  Safe to call before start() —
        returns empty features when FRED data has not yet loaded.
        """
        try:
            from ml.macro_store import macro_store

            raw_snap = macro_store.snapshot()
        except ImportError:
            raw_snap = {}

        series_detail: dict[str, object] = {}
        for name, info in raw_snap.items():
            if info:
                series_detail[name] = {
                    "value": info.get("value"),
                    "date": info.get("date"),
                }

        return {
            "health": self.health(),
            "ml_features": self.get_ml_features(),
            "series": series_detail,
            "series_count": len(series_detail),
            "loaded": self._loaded,
            "last_refresh": self._last_refresh.isoformat() if self._last_refresh else None,
        }

    def force_refresh(self) -> None:
        """
        Schedule an immediate FRED refresh outside the daily cycle.

        Creates a fire-and-forget asyncio task.  Safe to call from sync
        code — does nothing if no event loop is running.
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(
                    self._load_fred_into_store(),
                    loop=loop,
                )
            else:
                loop.run_until_complete(self._load_fred_into_store())
        except RuntimeError:
            logger.warning("MacroStoreBridge.force_refresh: no event loop available")

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def health(self) -> dict:
        try:
            from ml.macro_store import macro_store

            snap = macro_store.snapshot()
        except ImportError:
            snap = {}
        return {
            "loaded": self._loaded,
            "series_loaded": self._series_loaded,
            "wgc_series_loaded": self._wgc_series_loaded,
            "last_refresh": self._last_refresh.isoformat() if self._last_refresh else None,
            "series_count": len(snap),
            "wgc_health": self._wgc.health(),
            "series": {name: info.get("date") if info else None for name, info in snap.items()},
        }


# Module-level singleton
macro_store_bridge = MacroStoreBridge()
