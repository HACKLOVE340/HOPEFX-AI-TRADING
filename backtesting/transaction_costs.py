# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
backtest/transaction_costs.py
==============================
Realistic transaction cost model for backtests.

Every trade incurs two costs expressed as a **fraction of notional**:
  1. Round-trip spread  = 2 × half_spread_bps / 10_000
  2. Round-trip commission = commission_bps / 10_000

Both are subtracted from the raw close-to-close P&L percentage.

Design notes
------------
All costs are stored as fractions of notional (basis points) so they apply
correctly regardless of the instrument's price level.  This avoids the error
of dividing a fixed-USD commission by a sub-$2 forex quote.

Spread calibration (half-spread in basis points)
-------------------------------------------------
  XAU/USD  : 1.50 bps  ($0.30 on ~$2000 gold — OANDA practice typical)
  BTC/USD  : 1.00 bps  ($5 on ~$50k BTC)
  ETH/USD  : 1.67 bps  ($0.50 on ~$3000 ETH)
  EUR/USD  : 0.92 bps  (1 pip = 0.0001 on 1.085)
  GBP/USD  : 0.95 bps  (1.2 pips on 1.265)
  Silver   : 8.33 bps  ($0.02 on ~$24)
  Crude Oil: 4.00 bps  ($0.03 on ~$75)
  default  : 2.00 bps  (conservative fallback)

Commission calibration (round-trip in basis points)
----------------------------------------------------
  Futures (GC=F, SI=F, CL=F): 3.50 bps  (~$7 RT on ~$20k notional)
  Crypto (BTC-USD, ETH-USD)  : 10.00 bps (0.05% taker × 2 sides)
  Forex (EURUSD=X, GBPUSD=X) : 3.00 bps  (~$3 per $100k lot)
  default                    : 10.00 bps

Usage
-----
    from backtesting.transaction_costs import TransactionCostModel, get_tc_model

    tc = get_tc_model()
    net_pnl_pct = tc.apply(raw_pnl_pct=0.0042, entry_price=1980.0, ticker="GC=F")
    summary = tc.cost_summary(entry_price=1980.0, ticker="GC=F")
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ── Half-spread in basis points (1 bp = 0.0001 of notional) ──────────────────
_HALF_SPREAD_BPS: dict[str, float] = {
    "GC=F": 1.50,
    "XAU/USD": 1.50,
    "XAUUSD": 1.50,
    "BTC-USD": 1.00,
    "BTC/USD": 1.00,
    "ETH-USD": 1.67,
    "ETH/USD": 1.67,
    "EURUSD=X": 0.92,
    "EUR/USD": 0.92,
    "GBPUSD=X": 0.95,
    "GBP/USD": 0.95,
    "SI=F": 8.33,
    "Silver": 8.33,
    "CL=F": 4.00,
    "Crude Oil": 4.00,
}

# ── Round-trip commission in basis points ─────────────────────────────────────
_COMMISSION_BPS: dict[str, float] = {
    "GC=F": 3.50,
    "XAU/USD": 3.50,
    "XAUUSD": 3.50,
    "SI=F": 3.50,
    "Silver": 3.50,
    "CL=F": 3.50,
    "Crude Oil": 3.50,
    "BTC-USD": 10.00,
    "BTC/USD": 10.00,
    "ETH-USD": 10.00,
    "ETH/USD": 10.00,
    "EURUSD=X": 3.00,
    "EUR/USD": 3.00,
    "GBPUSD=X": 3.00,
    "GBP/USD": 3.00,
}

_DEFAULT_HALF_SPREAD_BPS = 2.0
_DEFAULT_COMMISSION_BPS = 10.0


class TransactionCostModel:
    """
    Applies spread + commission to a raw close-to-close P&L percentage.

    All costs are expressed as fractions of notional (basis points / 10_000)
    so they are independent of the instrument's absolute price level.

    Parameters
    ----------
    extra_spread_bps : Additional spread in basis points added on top of the
                       table value (e.g. for illiquid hours). Default 0.
    """

    def __init__(self, extra_spread_bps: float = 0.0) -> None:
        self._extra_spread_bps = extra_spread_bps

    def round_trip_cost_frac(self, ticker: str) -> float:
        """Return total round-trip cost as a fraction of notional."""
        half_spread_bps = _HALF_SPREAD_BPS.get(ticker)
        if half_spread_bps is None:
            half_spread_bps = _DEFAULT_HALF_SPREAD_BPS
            logger.debug(
                "TransactionCostModel: unknown ticker %r — using %.1f bps half-spread",
                ticker,
                _DEFAULT_HALF_SPREAD_BPS,
            )
        commission_bps = _COMMISSION_BPS.get(ticker, _DEFAULT_COMMISSION_BPS)
        extra_bps = self._extra_spread_bps * 2.0  # entry + exit
        total_bps = 2.0 * half_spread_bps + commission_bps + extra_bps
        return total_bps / 10_000.0

    def apply(
        self,
        raw_pnl_pct: float,
        entry_price: float,
        ticker: str,
    ) -> float:
        """
        Deduct round-trip transaction costs from a raw P&L percentage.

        Parameters
        ----------
        raw_pnl_pct  : Raw close-to-close return (e.g. 0.0042 = +0.42%).
        entry_price  : Entry price (used only for cost_summary logging).
        ticker       : yfinance ticker or display name (e.g. "GC=F", "XAU/USD").

        Returns
        -------
        Net P&L percentage after costs.
        """
        cost = self.round_trip_cost_frac(ticker)
        return raw_pnl_pct - cost

    def cost_summary(self, entry_price: float, ticker: str) -> dict:
        """Return a breakdown dict for logging/reporting."""
        half_spread_bps = _HALF_SPREAD_BPS.get(ticker, _DEFAULT_HALF_SPREAD_BPS)
        commission_bps = _COMMISSION_BPS.get(ticker, _DEFAULT_COMMISSION_BPS)
        total_bps = 2.0 * half_spread_bps + commission_bps + self._extra_spread_bps * 2.0
        total_frac = total_bps / 10_000.0
        return {
            "ticker": ticker,
            "entry_price": entry_price,
            "half_spread_bps": half_spread_bps,
            "round_trip_spread_bps": 2.0 * half_spread_bps,
            "commission_bps": commission_bps,
            "total_cost_bps": round(total_bps, 4),
            "total_cost_pct": round(total_frac * 100, 4),
            "approx_cost_usd_per_unit": round(entry_price * total_frac, 6),
        }


# Module-level singleton
_default_tc_model: TransactionCostModel | None = None


def get_tc_model(extra_spread_bps: float = 0.0) -> TransactionCostModel:
    """Return the module-level TransactionCostModel singleton."""
    global _default_tc_model
    if _default_tc_model is None or extra_spread_bps != 0.0:
        _default_tc_model = TransactionCostModel(extra_spread_bps=extra_spread_bps)
    return _default_tc_model
