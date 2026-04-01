# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
data_layer/feeds/macro/options_flow.py
========================================
Gold options flow — GC put/call ratio and IV skew.

Fetches GLD/GC options data from CBOE delayed quotes API and computes:
  - gc_put_call_ratio  — volume put/call ratio
  - gc_iv_atm          — at-the-money implied volatility
  - gc_iv_skew         — 25-delta put IV minus call IV (skew)

Source: https://cdn.cboe.com/api/global/delayed_quotes/options/GLD.json
"""
from __future__ import annotations

import logging
import os
from typing import Any

import aiohttp
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_CBOE_GLD_URL = os.getenv(
    "CBOE_OPTIONS_URL",
    "https://cdn.cboe.com/api/global/delayed_quotes/options/GLD.json",
)
_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=30.0)


class OptionsFlowFeed:
    """Fetches GLD/GC options flow metrics from CBOE delayed quotes."""

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            headers = {
                "User-Agent": "Mozilla/5.0 (compatible; HOPEFX/1.0)",
                "Accept": "application/json",
            }
            self._session = aiohttp.ClientSession(
                timeout=_HTTP_TIMEOUT, headers=headers
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def fetch_latest(self) -> dict[str, float]:
        """
        Fetch latest gold options metrics from CBOE.

        Returns dict with keys: gc_put_call_ratio, gc_iv_atm, gc_iv_skew
        """
        try:
            session = await self._get_session()
            async with session.get(_CBOE_GLD_URL) as resp:
                resp.raise_for_status()
                data: dict[str, Any] = await resp.json(content_type=None)
        except Exception as exc:
            logger.warning("Options flow: CBOE fetch error: %s", exc)
            return {}

        options = data.get("data", {}).get("options", [])
        if not options:
            logger.warning("Options flow: no options data in response")
            return {}

        underlying = float(data.get("data", {}).get("close") or 0)
        put_vol = 0.0
        call_vol = 0.0
        atm_ivs: list[float] = []
        put_25d_ivs: list[float] = []
        call_25d_ivs: list[float] = []

        for opt in options:
            try:
                opt_type = str(opt.get("option", ""))
                volume = float(opt.get("volume") or 0)
                iv = float(opt.get("iv") or 0)
                strike = float(opt.get("strike") or 0)
                delta = float(opt.get("delta") or 0)

                if "P" in opt_type:
                    put_vol += volume
                    if -0.35 < delta < -0.15 and iv > 0:
                        put_25d_ivs.append(iv)
                elif "C" in opt_type:
                    call_vol += volume
                    if 0.15 < delta < 0.35 and iv > 0:
                        call_25d_ivs.append(iv)

                if underlying > 0 and iv > 0:
                    moneyness = abs(strike - underlying) / underlying
                    if moneyness < 0.02:
                        atm_ivs.append(iv)
            except (ValueError, TypeError):
                continue

        result: dict[str, float] = {}
        if call_vol > 0:
            result["gc_put_call_ratio"] = put_vol / call_vol
        if atm_ivs:
            result["gc_iv_atm"] = float(np.mean(atm_ivs))
        if put_25d_ivs and call_25d_ivs:
            result["gc_iv_skew"] = float(np.mean(put_25d_ivs) - np.mean(call_25d_ivs))

        if result:
            logger.info("Options flow: fetched %d metrics", len(result))
        return result

    async def fetch_series(self) -> dict[str, pd.Series]:
        """Return options metrics as pd.Series for MacroStore injection."""
        latest = await self.fetch_latest()
        if not latest:
            return {}
        now = pd.Timestamp.now(tz="UTC").normalize()
        return {
            k: pd.Series([v], index=pd.DatetimeIndex([now]), dtype=float)
            for k, v in latest.items()
        }

    async def inject_into_macro_store(self) -> int:
        """Inject options flow data into MacroStore. Returns count injected."""
        from ml.macro_store import macro_store  # noqa: PLC0415
        series = await self.fetch_series()
        count = 0
        for name, s in series.items():
            if not s.empty:
                if name in macro_store._series and not macro_store._series[name].empty:
                    combined = pd.concat([macro_store._series[name], s])
                    macro_store._series[name] = combined[
                        ~combined.index.duplicated(keep="last")
                    ].sort_index()
                else:
                    macro_store._series[name] = s
                count += 1
        if count:
            logger.info("Options flow: injected %d series", count)
        return count


options_flow_feed = OptionsFlowFeed()
