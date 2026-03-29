# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
data_layer/feeds/macro/store_bridge.py
========================================
MacroStoreBridge — keeps ml/macro_store.py populated from FRED.

The existing MacroStore (ml/macro_store.py) is the ML pipeline's source
of truth for daily macro series. This bridge:
  1. Fetches all FRED series on startup
  2. Loads them into the MacroStore singleton
  3. Runs a daily refresh at 18:00 UTC (after US market close)
  4. Exposes get_ml_features() for real-time macro feature injection

This is the correct integration point — the ML pipeline continues to
call macro_store.align_to_hourly() exactly as before, but now the store
is populated from FRED automatically rather than requiring manual CSV files.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Optional

from data_layer.feeds.macro.fred import FREDFeed, FRED_SERIES, fred_feed

logger = logging.getLogger(__name__)


class MacroStoreBridge:
    """
    Bridges FRED data into ml.macro_store.MacroStore.

    Usage:
        bridge = MacroStoreBridge()
        await bridge.start()   # loads FRED data + starts daily refresh
    """

    def __init__(self, fred: Optional[FREDFeed] = None) -> None:
        self._fred = fred or fred_feed
        self._loaded = False
        self._last_refresh: Optional[datetime] = None

    async def start(self) -> None:
        """Load FRED data into MacroStore and start daily refresh."""
        await self._load_fred_into_store()
        asyncio.create_task(self._daily_refresh_loop(), name="macro_store_bridge_refresh")

    async def _load_fred_into_store(self) -> None:
        """Fetch all FRED series and load into MacroStore singleton."""
        try:
            from ml.macro_store import macro_store

            logger.info("MacroStoreBridge: fetching FRED series...")
            all_series = await self._fred.fetch_all()

            for name, series in all_series.items():
                if series.empty:
                    logger.debug("MacroStoreBridge: %s empty — skipping", name)
                    continue
                # Inject directly into MacroStore's internal dict
                macro_store._series[name] = series
                logger.info(
                    "MacroStoreBridge: loaded %s (%d obs)", name, len(series)
                )

            self._loaded = True
            self._last_refresh = datetime.now(timezone.utc)
            logger.info(
                "MacroStoreBridge: MacroStore populated with %d series",
                len(macro_store),
            )
        except Exception as exc:
            logger.error("MacroStoreBridge load error: %s", exc)

    async def _daily_refresh_loop(self) -> None:
        """Refresh FRED data daily at 18:00 UTC."""
        while True:
            now = datetime.now(timezone.utc)
            # Next 18:00 UTC
            target = now.replace(hour=18, minute=0, second=0, microsecond=0)
            if target <= now:
                from datetime import timedelta
                target = target + timedelta(days=1)
            wait_s = (target - now).total_seconds()
            logger.debug(
                "MacroStoreBridge: next refresh in %.1f hours", wait_s / 3600
            )
            await asyncio.sleep(wait_s)
            await self._load_fred_into_store()

    def get_ml_features(self) -> Dict[str, float]:
        """
        Return latest macro values as flat ML features.

        These are the raw latest values — the ML pipeline uses
        macro_store.align_to_hourly() for time-series alignment.
        """
        try:
            from ml.macro_store import macro_store
            snap = macro_store.snapshot()
            features: Dict[str, float] = {}
            for name, info in snap.items():
                if info and info.get("value") is not None:
                    features[f"macro_{name}"] = float(info["value"])
                else:
                    features[f"macro_{name}"] = 0.0
            return features
        except Exception as exc:
            logger.debug("MacroStoreBridge.get_ml_features error: %s", exc)
            return {}

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def health(self) -> dict:
        try:
            from ml.macro_store import macro_store
            snap = macro_store.snapshot()
        except Exception:
            snap = {}
        return {
            "loaded":       self._loaded,
            "last_refresh": self._last_refresh.isoformat() if self._last_refresh else None,
            "series_count": len(snap),
            "series":       {
                name: info.get("date") if info else None
                for name, info in snap.items()
            },
        }


# Module-level singleton
macro_store_bridge = MacroStoreBridge()
