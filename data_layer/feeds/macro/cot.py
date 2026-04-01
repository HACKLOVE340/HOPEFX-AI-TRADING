# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
data_layer/feeds/macro/cot.py
==============================
Real CFTC Commitments of Traders (COT) feed for gold futures (GC).

Fetches disaggregated COT data from CFTC public Socrata API.
Produces net speculative positioning and concentration metrics.

Data: https://publicreporting.cftc.gov/resource/jun7-fc8e.json
Published: every Friday after US market close
"""
from __future__ import annotations

import logging
import os
from datetime import timezone

UTC = timezone.utc

import aiohttp
import pandas as pd

logger = logging.getLogger(__name__)

_CFTC_BASE = "https://publicreporting.cftc.gov/resource/jun7-fc8e.json"
_CFTC_APP_TOKEN = os.getenv("CFTC_APP_TOKEN", "")
# Gold futures CFTC commodity code
_GOLD_CODE = "088691"
_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=30.0)


class COTFeed:
    """Async CFTC COT data fetcher for gold futures (GC)."""

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=_HTTP_TIMEOUT)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def fetch_cot(self, lookback_weeks: int = 260) -> pd.DataFrame:
        """Fetch COT data for gold futures from CFTC Socrata API."""
        params: dict[str, str] = {
            "$where": f"cftc_commodity_code='{_GOLD_CODE}'",
            "$order": "report_date_as_yyyy_mm_dd DESC",
            "$limit": str(lookback_weeks),
        }
        if _CFTC_APP_TOKEN:
            params["$$app_token"] = _CFTC_APP_TOKEN

        try:
            session = await self._get_session()
            async with session.get(_CFTC_BASE, params=params) as resp:
                resp.raise_for_status()
                data = await resp.json()
        except Exception as exc:
            logger.warning("COT fetch error: %s", exc)
            return pd.DataFrame()

        if not data:
            return pd.DataFrame()

        records = []
        for row in data:
            try:
                date = pd.Timestamp(row["report_date_as_yyyy_mm_dd"], tz="UTC")
                mm_long = float(row.get("m_money_positions_long_all") or 0)
                mm_short = float(row.get("m_money_positions_short_all") or 0)
                comm_long = float(row.get("comm_positions_long_all") or 0)
                comm_short = float(row.get("comm_positions_short_all") or 0)
                oi = float(row.get("open_interest_all") or 0)
                conc_long_4 = float(row.get("conc_gross_le_4_tdr_long_all") or 0)
                conc_short_4 = float(row.get("conc_gross_le_4_tdr_short_all") or 0)
                records.append({
                    "date": date,
                    "net_spec": mm_long - mm_short,
                    "commercial_net": comm_long - comm_short,
                    "open_interest": oi,
                    "concentration_long_4": conc_long_4,
                    "concentration_short_4": conc_short_4,
                })
            except (KeyError, ValueError, TypeError) as exc:
                logger.debug("COT: skipping row: %s", exc)

        if not records:
            return pd.DataFrame()

        df = (
            pd.DataFrame(records)
            .sort_values("date")
            .reset_index(drop=True)
            .set_index("date")
        )
        return df

    async def fetch_series(self) -> dict[str, pd.Series]:
        """Return COT-derived pd.Series dict for MacroStore injection."""
        df = await self.fetch_cot()
        if df.empty:
            return {}

        result: dict[str, pd.Series] = {
            "cot_net_spec": df["net_spec"],
            "cot_commercial_net": df["commercial_net"],
            "cot_open_interest": df["open_interest"],
        }

        # Concentration long/short ratio
        denom = df["concentration_short_4"].replace(0, float("nan"))
        result["cot_concentration_lr"] = df["concentration_long_4"] / denom

        # 20-week rolling z-score
        roll = df["net_spec"].rolling(window=20, min_periods=5)
        std = roll.std().replace(0, float("nan"))
        result["cot_net_spec_z"] = (df["net_spec"] - roll.mean()) / std

        return {k: v.dropna() for k, v in result.items()}

    async def inject_into_macro_store(self) -> int:
        """Fetch and inject all COT series into MacroStore. Returns count."""
        from ml.macro_store import macro_store  # noqa: PLC0415
        series = await self.fetch_series()
        count = 0
        for name, s in series.items():
            if not s.empty:
                macro_store._series[name] = s
                count += 1
        if count:
            logger.info("COT: injected %d series into MacroStore", count)
        return count


cot_feed = COTFeed()
