# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
api/analysis.py
===============
Market analysis endpoints — correlation matrix and COT sentiment.

Routes:
    GET /api/analysis/correlation   — rolling Pearson correlation matrix
    GET /api/analysis/cot           — CFTC COT gold speculator sentiment

These are thin wrappers that delegate to the implementations in
api/advanced_trading.py so the logic lives in one place.  The /api/analysis
prefix is what the dashboard and frontend expect; /api/advanced/* are the
legacy paths kept for backward compatibility.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from api.auth import TokenPayload, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analysis", tags=["Analysis"])


@router.get("/correlation")
async def get_correlation(
    window: int = 30,
    user: TokenPayload = Depends(get_current_user),
):
    """
    Rolling Pearson correlation matrix for the default symbol set.

    Delegates to the implementation in api.advanced_trading which reads
    OHLCV history from the price engine or CSV files in data/.

    Query params:
        window  — look-back period in days (default 30, min 5, max 365)

    Returns:
        {
          "matrix": { "XAU_USD": { "EUR_USD": 0.62, … }, … },
          "symbols_with_data": […],
          "symbols_missing_data": […],
          "window": <int>,
          "insights": […],
          "updated_at": "<iso8601>"
        }

    Raises HTTP 503 when fewer than 2 symbols have sufficient history.
    """
    from api.advanced_trading import _collect_series_from_engine

    window = max(5, min(window, 365))
    sym_list = ["XAU_USD", "EUR_USD", "GBP_USD", "USD_JPY", "BTC_USD"]
    return await _collect_series_from_engine(None, sym_list, window)


@router.get("/cot")
async def get_cot(
    user: TokenPayload = Depends(get_current_user),
):
    """
    CFTC Commitment of Traders data for gold (COMEX, code 088691).

    Fetches the most recent weekly report from the CFTC public API.
    Returns HTTP 503 when the API is unreachable.

    Returns:
        {
          "report_date": "YYYY-MM-DD",
          "net_speculator_long": <int>,
          "long_positions": <int>,
          "short_positions": <int>,
          "sentiment": "BULLISH" | "BEARISH",
          "sentiment_strength": "STRONG" | "MODERATE",
          "weekly_change": <int>,
          "source": "CFTC",
          "note": "…"
        }
    """
    from api.advanced_trading import get_cot_gold

    return await get_cot_gold(user)
