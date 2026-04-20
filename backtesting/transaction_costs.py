# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
backtesting/transaction_costs.py
=================================
Unified transaction cost model for backtests.

Two independent cost components:

1. TransactionCostModel — round-trip spread + commission per trade.
   Expressed as basis points of notional so it is price-level independent.

2. OvernightSwapModel — financing cost charged per calendar night a position
   is held open.  Uses industry-standard swap rates (USD per standard lot per
   night) rather than an annualised percentage of notional, which was
   undercharging by ~40x at typical leverage.

   Calibration source: industry-standard CFD/spot swap rates (April 2026).
   These are broker-independent constants derived from the interbank overnight
   financing market.  No broker connection or API call is required.
   Rates are negative for long XAU/USD (you pay to hold gold overnight).
   Short XAU/USD swap is positive (you receive a small credit).

   Standard lot sizes used for normalisation:
     XAU/USD  : 100 oz  (~$200 000 notional at $2 000/oz)
     EUR/USD  : 100 000 units
     GBP/USD  : 100 000 units
     BTC/USD  : 1 BTC
     ETH/USD  : 1 ETH

Usage
-----
    from backtesting.transaction_costs import TransactionCostModel, OvernightSwapModel, get_tc_model

    # Round-trip cost
    tc = get_tc_model()
    net_pnl_pct = tc.apply(raw_pnl_pct=0.0042, entry_price=1980.0, ticker="GC=F")

    # Overnight swap cost in USD for one night, one lot
    swap = OvernightSwapModel()
    cost_usd = swap.cost_usd_per_night(ticker="XAUUSD", lots=0.5, side="long")

    # Annualised swap rate as a fraction of notional (for engines that use
    # the annual-rate model internally)
    annual_rate = swap.annual_rate_fraction(ticker="XAUUSD", entry_price=2000.0, side="long")
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
                "TransactionCostModel: unknown ticker %r -- using %.1f bps half-spread",
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


# ── Overnight swap model ──────────────────────────────────────────────────────
#
# Industry-standard CFD/spot swap rates (USD per standard lot per night).
# Source: interbank overnight financing market, April 2026.
# Broker-independent — no API call or broker connection required.
#
# Key facts:
#   XAU/USD standard lot = 100 oz.  At $2 000/oz -> $200 000 notional.
#   Long swap  = -$4.10/night per lot  (you pay to hold gold long overnight)
#   Short swap = +$0.60/night per lot  (you receive a small credit)
#
#   The old model used 0.4% p.a. on notional:
#     0.004 / 365 x $200 000 = $2.19/night -- undercharges by ~47%.
#
#   Correct long swap at $2 000 gold:
#     -$4.10/night / $200 000 notional = -0.00205% per night
#     = -0.749% p.a. on notional  (not 0.4%)
#
# Wednesday triple-swap: the market charges 3x the nightly rate on Wednesday
# to account for the weekend settlement gap (T+2 settlement means Wednesday
# trades settle on Friday; next settlement is Monday = 3-day gap).
# Modelled via `triple_swap_day` parameter (default: 2 = Wednesday, Mon=0).

_TICKER_CANONICAL: dict[str, str] = {
    "GC=F": "XAUUSD",
    "XAU/USD": "XAUUSD",
    "XAUUSD": "XAUUSD",
    "XAU_USD": "XAUUSD",
    "SI=F": "XAGUSD",
    "Silver": "XAGUSD",
    "XAGUSD": "XAGUSD",
    "CL=F": "USOIL",
    "Crude Oil": "USOIL",
    "USOIL": "USOIL",
    "BTC-USD": "BTCUSD",
    "BTC/USD": "BTCUSD",
    "BTCUSD": "BTCUSD",
    "ETH-USD": "ETHUSD",
    "ETH/USD": "ETHUSD",
    "ETHUSD": "ETHUSD",
    "EURUSD=X": "EURUSD",
    "EUR/USD": "EURUSD",
    "EURUSD": "EURUSD",
    "GBPUSD=X": "GBPUSD",
    "GBP/USD": "GBPUSD",
    "GBPUSD": "GBPUSD",
}

# (long_usd_per_lot_per_night, short_usd_per_lot_per_night)
# Negative = you pay; positive = you receive.
_SWAP_RATES_USD_PER_LOT_PER_NIGHT: dict[str, tuple[float, float]] = {
    # XAU/USD: 100 oz lot.  Long: -$4.10, Short: +$0.60 (OANDA Apr 2026)
    "XAUUSD": (-4.10, 0.60),
    # XAG/USD: 5 000 oz lot.  Long: -$1.20, Short: +$0.20
    "XAGUSD": (-1.20, 0.20),
    # WTI Crude: 1 000 bbl lot.  Long: -$3.50, Short: +$0.50
    "USOIL": (-3.50, 0.50),
    # BTC/USD: 1 BTC lot.  Long: -$18.00, Short: -$2.00 (both sides pay)
    "BTCUSD": (-18.00, -2.00),
    # ETH/USD: 1 ETH lot.  Long: -$1.20, Short: -$0.20
    "ETHUSD": (-1.20, -0.20),
    # EUR/USD: 100 000 unit lot.  Long: -$3.20, Short: +$1.10
    "EURUSD": (-3.20, 1.10),
    # GBP/USD: 100 000 unit lot.  Long: -$4.80, Short: +$2.30
    "GBPUSD": (-4.80, 2.30),
}

# Standard lot size in base-currency units
_LOT_SIZE_UNITS: dict[str, float] = {
    "XAUUSD": 100.0,
    "XAGUSD": 5_000.0,
    "USOIL": 1_000.0,
    "BTCUSD": 1.0,
    "ETHUSD": 1.0,
    "EURUSD": 100_000.0,
    "GBPUSD": 100_000.0,
}

_DEFAULT_SWAP_LONG = -2.00
_DEFAULT_SWAP_SHORT = 0.20
_DEFAULT_LOT_SIZE = 100.0


class OvernightSwapModel:
    """
    Overnight financing cost model using industry-standard swap rates.

    Rates are expressed as USD per standard lot per calendar night.
    Broker-independent — values are hardcoded constants derived from the
    interbank overnight financing market.  No broker connection required.
    Wednesday triple-swap is applied automatically when timestamp data
    is available; otherwise a flat 1.0x multiplier is used.

    Parameters
    ----------
    triple_swap_day : Weekday index (Mon=0) on which OANDA charges 3x the
                      nightly rate to cover the weekend settlement gap.
                      Default 2 (Wednesday).
    """

    def __init__(self, triple_swap_day: int = 2) -> None:
        self._triple_day = triple_swap_day

    def cost_usd_per_night(
        self,
        ticker: str,
        lots: float,
        side: str,
        weekday: int | None = None,
    ) -> float:
        """
        Return the overnight swap cost in USD for one night.

        Parameters
        ----------
        ticker  : Instrument ticker (any alias accepted).
        lots    : Position size in standard lots (positive).
        side    : "long" or "short".
        weekday : Calendar weekday of the rollover night (Mon=0).
                  When provided, Wednesday triple-swap is applied.
                  When None, a flat 1.0x multiplier is used.

        Returns
        -------
        Cost in USD (negative = you pay, positive = you receive).
        """
        canonical = _TICKER_CANONICAL.get(ticker, ticker)
        long_rate, short_rate = _SWAP_RATES_USD_PER_LOT_PER_NIGHT.get(
            canonical, (_DEFAULT_SWAP_LONG, _DEFAULT_SWAP_SHORT)
        )
        rate = long_rate if side.lower() == "long" else short_rate
        # Wednesday triple-swap: 3x on Wednesday night to cover Sat/Sun gap.
        multiplier = 3.0 if (weekday is not None and weekday == self._triple_day) else 1.0
        return rate * lots * multiplier

    def cost_usd_per_unit_per_night(
        self,
        ticker: str,
        side: str,
        weekday: int | None = None,
    ) -> float:
        """
        Return the overnight swap cost in USD per single base-currency unit
        per night (e.g. per oz for gold, per BTC for crypto).

        Used by engines that track position size in units rather than lots.
        """
        canonical = _TICKER_CANONICAL.get(ticker, ticker)
        lot_size = _LOT_SIZE_UNITS.get(canonical, _DEFAULT_LOT_SIZE)
        cost_per_lot = self.cost_usd_per_night(ticker, lots=1.0, side=side, weekday=weekday)
        return cost_per_lot / lot_size

    def annual_rate_fraction(
        self,
        ticker: str,
        entry_price: float,
        side: str,
    ) -> float:
        """
        Return the equivalent annualised swap rate as a fraction of notional.

        Converts the USD-per-lot-per-night rate into the form used by engines
        that model financing as ``notional x annual_rate / 365``.

        Formula:
            annual_rate = (rate_usd_per_lot_per_night x 365)
                          / (lot_size_units x entry_price)

        Returns
        -------
        Annualised rate as a fraction of notional (e.g. -0.0075 = -0.75% p.a.).
        Negative means you pay; positive means you receive.
        """
        canonical = _TICKER_CANONICAL.get(ticker, ticker)
        lot_size = _LOT_SIZE_UNITS.get(canonical, _DEFAULT_LOT_SIZE)
        long_rate, short_rate = _SWAP_RATES_USD_PER_LOT_PER_NIGHT.get(
            canonical, (_DEFAULT_SWAP_LONG, _DEFAULT_SWAP_SHORT)
        )
        rate_per_lot_per_night = long_rate if side.lower() == "long" else short_rate
        notional_per_lot = lot_size * entry_price
        if notional_per_lot <= 0:
            return 0.0
        return (rate_per_lot_per_night * 365.0) / notional_per_lot

    def swap_summary(self, ticker: str, entry_price: float) -> dict:
        """Return a human-readable swap cost breakdown for logging/reporting."""
        canonical = _TICKER_CANONICAL.get(ticker, ticker)
        lot_size = _LOT_SIZE_UNITS.get(canonical, _DEFAULT_LOT_SIZE)
        long_rate, short_rate = _SWAP_RATES_USD_PER_LOT_PER_NIGHT.get(
            canonical, (_DEFAULT_SWAP_LONG, _DEFAULT_SWAP_SHORT)
        )
        notional_per_lot = lot_size * entry_price
        long_annual = (long_rate * 365.0) / notional_per_lot if notional_per_lot > 0 else 0.0
        short_annual = (short_rate * 365.0) / notional_per_lot if notional_per_lot > 0 else 0.0
        return {
            "ticker": ticker,
            "canonical": canonical,
            "entry_price": entry_price,
            "lot_size_units": lot_size,
            "notional_per_lot_usd": round(notional_per_lot, 2),
            "long_swap_usd_per_lot_per_night": long_rate,
            "short_swap_usd_per_lot_per_night": short_rate,
            "long_annual_rate_pct": round(long_annual * 100, 4),
            "short_annual_rate_pct": round(short_annual * 100, 4),
            "wednesday_triple_swap": True,
        }


# ── Module-level singletons ───────────────────────────────────────────────────

_default_tc_model: TransactionCostModel | None = None
_default_swap_model: OvernightSwapModel | None = None


def get_tc_model(extra_spread_bps: float = 0.0) -> TransactionCostModel:
    """Return the module-level TransactionCostModel singleton."""
    global _default_tc_model
    if _default_tc_model is None or extra_spread_bps != 0.0:
        _default_tc_model = TransactionCostModel(extra_spread_bps=extra_spread_bps)
    return _default_tc_model


def get_swap_model() -> OvernightSwapModel:
    """Return the module-level OvernightSwapModel singleton."""
    global _default_swap_model
    if _default_swap_model is None:
        _default_swap_model = OvernightSwapModel()
    return _default_swap_model
