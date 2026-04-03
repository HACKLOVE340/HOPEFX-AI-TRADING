# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
ml/position_sizer.py
====================
Volatility-scaled, Kelly-adjusted position sizing.

The reconciled backtest showed that fixed position sizing with $70 round-trip
costs destroys thin edges. This module implements three sizing methods that
adapt to current market conditions:

1. Volatility-scaled sizing (default)
   Size = (account_equity × risk_pct) / (ATR × atr_multiplier)
   Reduces size in high-vol regimes, increases in low-vol.

2. Kelly-adjusted sizing
   f* = (p × b - q) / b, scaled by kelly_fraction (default 0.25 = quarter-Kelly)
   Uses rolling win rate and avg win/loss from SignalFilter outcomes.

3. Fixed fractional (fallback)
   Size = account_equity × fixed_risk_pct / entry_price

All methods are capped at MAX_POSITION_PCT of account equity and
MIN_LOTS / MAX_LOTS absolute bounds.

Usage
-----
    from ml.position_sizer import PositionSizer

    sizer = PositionSizer()
    size = sizer.compute(
        symbol="XAUUSD",
        direction="BUY",
        entry_price=3300.0,
        stop_loss=3270.0,
        account_equity=100_000.0,
        confidence=0.65,
    )
"""

from __future__ import annotations

import logging
import os
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# ── Configuration (env-tunable) ───────────────────────────────────────────────
_RISK_PCT = float(os.getenv("POSITION_RISK_PCT", "0.01"))  # 1% risk per trade
_MAX_POSITION_PCT = float(os.getenv("MAX_POSITION_PCT", "0.05"))  # 5% max position
_KELLY_FRACTION = float(os.getenv("KELLY_FRACTION", "0.25"))  # quarter-Kelly
_ATR_MULT = float(os.getenv("SL_ATR_MULT", "1.5"))  # ATR multiplier for SL
_MIN_LOTS = float(os.getenv("MIN_LOTS", "0.01"))
_MAX_LOTS = float(os.getenv("MAX_LOTS", "10.0"))
_SIZING_METHOD = os.getenv("POSITION_SIZING_METHOD", "volatility")  # volatility|kelly|fixed


class PositionSizer:
    """
    Compute position size for a signal using the configured method.

    Integrates with SignalFilter to use rolling EV statistics for Kelly sizing.
    """

    def compute(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        stop_loss: float | None,
        account_equity: float,
        confidence: float = 0.6,
        ohlcv: Any | None = None,
    ) -> float:
        """
        Compute position size in lots.

        Parameters
        ----------
        symbol         : trading symbol (e.g. "XAUUSD")
        direction      : "BUY" or "SELL"
        entry_price    : signal entry price
        stop_loss      : ATR-based stop loss price (None → use ATR fallback)
        account_equity : current account equity in USD
        confidence     : model confidence [0, 1]
        ohlcv          : optional OHLCV DataFrame for ATR calculation

        Returns
        -------
        float : position size in lots, clamped to [MIN_LOTS, MAX_LOTS]
        """
        if account_equity <= 0 or entry_price <= 0:
            return _MIN_LOTS

        method = _SIZING_METHOD.lower()

        try:
            if method == "kelly":
                size = self._kelly_size(symbol, account_equity, entry_price, confidence)
            elif method == "volatility":
                size = self._volatility_size(account_equity, entry_price, stop_loss, ohlcv)
            else:
                size = self._fixed_size(account_equity, entry_price)
        except Exception as exc:
            logger.debug("Position sizer error, using fixed fallback: %s", exc)
            size = self._fixed_size(account_equity, entry_price)

        # Apply max position cap
        max_size_usd = account_equity * _MAX_POSITION_PCT
        max_lots = max_size_usd / entry_price if entry_price > 0 else _MAX_LOTS
        size = min(size, max_lots, _MAX_LOTS)
        size = max(size, _MIN_LOTS)

        logger.debug(
            "PositionSizer[%s]: method=%s size=%.4f lots entry=%.2f equity=%.0f",
            symbol,
            method,
            size,
            entry_price,
            account_equity,
        )
        return round(size, 4)

    # ── Sizing methods ────────────────────────────────────────────────────────

    def _volatility_size(
        self,
        equity: float,
        entry: float,
        stop_loss: float | None,
        ohlcv: Any | None,
    ) -> float:
        """
        Volatility-scaled sizing: risk a fixed % of equity per ATR unit.

        size = (equity × risk_pct) / risk_per_lot
        risk_per_lot = |entry - stop_loss| × lot_value

        For XAUUSD: 1 lot = 100 oz, so lot_value = 100.
        For forex: 1 lot = 100,000 units.
        """
        risk_amount = equity * _RISK_PCT

        # Compute risk per lot from SL distance
        if stop_loss is not None and abs(entry - stop_loss) > 0:
            sl_distance = abs(entry - stop_loss)
        else:
            # Fallback: use ATR from OHLCV
            sl_distance = self._atr_distance(entry, ohlcv)

        # Lot value: approximate for XAUUSD (100 oz/lot)
        lot_value = 100.0  # USD per point per lot for XAUUSD
        risk_per_lot = sl_distance * lot_value

        if risk_per_lot <= 0:
            return _MIN_LOTS

        return risk_amount / risk_per_lot

    def _kelly_size(
        self,
        symbol: str,
        equity: float,
        entry: float,
        confidence: float,
    ) -> float:
        """
        Quarter-Kelly sizing using rolling win rate and avg win/loss.

        f* = (p × b - q) / b
        where p = win_rate, q = 1-p, b = avg_win / avg_loss

        Scaled by KELLY_FRACTION (default 0.25) to reduce variance.
        """
        try:
            from ml.signal_filter import get_signal_filter

            stats = get_signal_filter().ev_stats(symbol)
        except ImportError:
            stats = {}

        win_rate = stats.get("win_rate") or confidence
        avg_win = stats.get("avg_win") or 0.01
        avg_loss = abs(stats.get("avg_loss") or 0.005)

        if avg_loss <= 0 or avg_win <= 0:
            return self._fixed_size(equity, entry)

        b = avg_win / avg_loss  # payoff ratio
        p = win_rate
        q = 1.0 - p

        kelly_f = (p * b - q) / b if b > 0 else 0.0
        kelly_f = max(0.0, kelly_f) * _KELLY_FRACTION

        # Convert fraction to lots
        position_value = equity * kelly_f
        lots = position_value / entry if entry > 0 else _MIN_LOTS
        return lots

    def _fixed_size(self, equity: float, entry: float) -> float:
        """Fixed fractional: risk RISK_PCT of equity at entry price."""
        position_value = equity * _RISK_PCT
        return position_value / entry if entry > 0 else _MIN_LOTS

    @staticmethod
    def _atr_distance(entry: float, ohlcv: Any | None) -> float:
        """Compute ATR(14) distance for SL fallback."""
        try:
            if ohlcv is not None and len(ohlcv) >= 15:
                h = ohlcv["high"].values[-15:].astype(float)
                l = ohlcv["low"].values[-15:].astype(float)
                c = ohlcv["close"].values[-15:].astype(float)
                tr = np.maximum(
                    h[1:] - l[1:],
                    np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])),
                )
                if len(tr) >= 14:
                    return float(np.mean(tr[-14:])) * _ATR_MULT
        except Exception as _exc:
            logger.debug("Suppressed exception: %s", _exc)
        return entry * 0.008 * _ATR_MULT  # 0.8% × multiplier fallback


# ── Module-level singleton ────────────────────────────────────────────────────

_SIZER_SINGLETON: PositionSizer | None = None


def get_position_sizer() -> PositionSizer:
    """Return the module-level PositionSizer singleton."""
    global _SIZER_SINGLETON
    if _SIZER_SINGLETON is None:
        _SIZER_SINGLETON = PositionSizer()
    return _SIZER_SINGLETON
