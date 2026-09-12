# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
RSI (Relative Strength Index) Trading Strategy

This strategy uses RSI to identify overbought and oversold conditions.
"""

import logging
from datetime import datetime, timezone

UTC = timezone.utc
from typing import Any

import pandas as pd

from strategies.base import BaseStrategy, Signal, SignalType, StrategyConfig

logger = logging.getLogger(__name__)


class RSIStrategy(BaseStrategy):
    """
    RSI-based trading strategy.

    Buys when RSI is oversold (below lower threshold).
    Sells when RSI is overbought (above upper threshold).
    """

    def __init__(
        self,
        config: StrategyConfig,
        *_args,
        period: int = 14,
        oversold: float = 30,
        overbought: float = 70,
    ):
        """
        Initialize RSI strategy.

        Args:
            config: StrategyConfig with name, symbol, timeframe
            period: RSI calculation period
            oversold: Oversold threshold (buy signal)
            overbought: Overbought threshold (sell signal)
        """
        super().__init__(config)
        self.period = period
        self.oversold = oversold
        self.overbought = overbought
        self.position: str | None = None  # tracks current position side: "LONG", "SHORT", or None
        logger.info("RSI Strategy initialized: period=%s, oversold=%s, overbought=%s", period, oversold, overbought)

    @staticmethod
    def _first_non_empty(*candidates: Any) -> Any:
        """First candidate that actually holds prices. Series-safe.

        This was ``data.get("prices") or data.get("close")``, and ``or`` calls
        ``__bool__``, which pandas raises on for a Series:

            ValueError: The truth value of a Series is ambiguous.

        So the very next line's ``isinstance(prices, pd.Series)`` branch could
        never be reached — passing a Series raised from the ``or`` first. The
        falsy-fallback semantics for lists are preserved exactly: an empty list
        under ``prices`` still falls through to ``close``.
        """
        # `len()` is the right test here and `bool()` is not: pandas defines
        # `__len__` on a Series and raises on `__bool__`. A mutation that
        # removed an earlier `isinstance(candidate, pd.Series)` special case
        # survived every test, which was correct — the special case was
        # redundant, and the simpler form is the one that says why.
        for candidate in candidates:
            if candidate is not None and len(candidate):
                return candidate
        return None

    def analyze(self, data: dict[str, Any]) -> dict[str, Any]:
        """Compute RSI from OHLCV data dict."""
        prices = self._first_non_empty(data.get("prices"), data.get("close"))
        if prices is None:
            return {"rsi": None, "error": "no price data"}
        series = pd.Series(prices) if not isinstance(prices, pd.Series) else prices
        rsi = self.calculate_rsi(series)
        current = float(rsi.iloc[-1]) if not rsi.empty else None
        return {
            "rsi": current,
            "oversold": self.oversold,
            "overbought": self.overbought,
        }

    def generate_signal(self, analysis) -> Any:
        """Dual-dispatch: DataFrame → dict signal, dict → Optional[Signal]."""
        if isinstance(analysis, pd.DataFrame):
            return self._generate_dict_signal(analysis)
        # dict path — BaseStrategy abstract method contract
        rsi = analysis.get("rsi")
        if rsi is None:
            return None
        price = analysis.get("price", 0.0)
        if rsi < self.oversold:
            return Signal(
                SignalType.BUY,
                self.config.symbol,
                price,
                datetime.now(UTC),
                confidence=min(0.95, 0.5 + (self.oversold - rsi) / self.oversold * 0.4),
            )
        if rsi > self.overbought:
            return Signal(
                SignalType.SELL,
                self.config.symbol,
                price,
                datetime.now(UTC),
                confidence=min(
                    0.95,
                    0.5 + (rsi - self.overbought) / (100 - self.overbought) * 0.4,
                ),
            )
        return None

    def generate_signal_from_data(self, market_data: pd.DataFrame) -> dict[str, Any]:
        """Legacy helper used by backtesting — returns dict signal."""
        return self._generate_dict_signal(market_data)

    def calculate_rsi(self, prices: pd.Series) -> pd.Series:
        """
        Calculate RSI indicator.

        Args:
            prices: Series of closing prices

        Returns:
            Series of RSI values
        """
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=self.period).mean().fillna(0.0)
        loss = (-delta.where(delta < 0, 0)).rolling(window=self.period).mean().fillna(0.0)

        rs = gain / loss.replace(0, float("nan"))
        rsi = 100 - (100 / (1 + rs))

        # A window with no losses is not a neutral reading — it is the most
        # overbought RSI can be, and 100 is what the definition gives. Dividing
        # by a zeroed loss produced NaN, and `.fillna(50.0)` then called it
        # neutral: measured on a monotonic rally of 40 bars, this returned
        # **50.0**, so the overbought branch could not fire during the strongest
        # uptrend the strategy will ever see. The defect was one-sided — a
        # monotonic slide correctly returned 0.0, because there `rs` is 0/0 → 0
        # rather than NaN — which left the strategy able to see oversold and not
        # overbought.
        rsi = rsi.where(~((loss == 0) & (gain > 0)), 100.0)

        # Only a window with neither gains nor losses is genuinely neutral, and
        # that includes the warm-up bars before the rolling window fills.
        return rsi.fillna(50.0)

    def _generate_dict_signal(self, market_data: pd.DataFrame) -> dict[str, Any]:
        """Generate dict-style signal from OHLCV DataFrame (used by backtesting)."""
        try:
            if len(market_data) < self.period + 1:
                return {
                    "type": "HOLD",
                    "confidence": 0.0,
                    "reason": "Insufficient data for RSI calculation",
                    "timestamp": datetime.now(UTC),
                }

            # Calculate RSI
            close = market_data["close"]
            rsi = self.calculate_rsi(close)

            current_rsi = rsi.iloc[-1]
            previous_rsi = rsi.iloc[-2]
            current_price = close.iloc[-1]

            # Check for NaN or inf from rolling RSI computation
            if pd.isna(current_rsi) or not (float("-inf") < current_rsi < float("inf")):
                return {
                    "type": "HOLD",
                    "confidence": 0.0,
                    "reason": "RSI calculation resulted in NaN",
                    "timestamp": datetime.now(UTC),
                }

            signal_type = "HOLD"
            confidence = 0.0
            reason = ""

            # BUY signal: RSI is oversold and starting to rise
            if current_rsi < self.oversold:
                signal_type = "BUY"
                # Confidence increases as RSI gets more oversold
                confidence = 0.5 + (self.oversold - current_rsi) / self.oversold * 0.4
                confidence = min(0.95, confidence)
                reason = f"RSI oversold: {current_rsi:.2f} < {self.oversold}"

                # Higher confidence if RSI is turning up
                if current_rsi > previous_rsi:
                    confidence = min(0.95, confidence + 0.1)
                    reason += " and rising"

            # SELL signal: RSI is overbought and starting to fall
            elif current_rsi > self.overbought:
                signal_type = "SELL"
                # Confidence increases as RSI gets more overbought
                confidence = 0.5 + (current_rsi - self.overbought) / (100 - self.overbought) * 0.4
                confidence = min(0.95, confidence)
                reason = f"RSI overbought: {current_rsi:.2f} > {self.overbought}"

                # Higher confidence if RSI is turning down
                if current_rsi < previous_rsi:
                    confidence = min(0.95, confidence + 0.1)
                    reason += " and falling"

            # Exit long position if RSI reaches neutral/overbought
            elif hasattr(self, "position") and self.position == "LONG" and current_rsi > 50:
                if current_rsi > self.overbought or current_rsi < previous_rsi:
                    signal_type = "SELL"
                    confidence = 0.6
                    reason = f"Exit long: RSI = {current_rsi:.2f}"

            # Exit short position if RSI reaches neutral/oversold
            elif hasattr(self, "position") and self.position == "SHORT" and current_rsi < 50:
                if current_rsi < self.oversold or current_rsi > previous_rsi:
                    signal_type = "BUY"
                    confidence = 0.6
                    reason = f"Exit short: RSI = {current_rsi:.2f}"

            else:
                reason = f"RSI neutral: {current_rsi:.2f} (range: {self.oversold}-{self.overbought})"

            return {
                "type": signal_type,
                "confidence": confidence,
                "reason": reason,
                "timestamp": datetime.now(UTC),
                "metadata": {
                    "rsi": current_rsi,
                    "previous_rsi": previous_rsi,
                    "price": current_price,
                    "oversold_level": self.oversold,
                    "overbought_level": self.overbought,
                },
            }

        except Exception as e:
            self.logger.error("Error generating RSI signal: %s", e)

            return {
                "type": "HOLD",
                "confidence": 0.0,
                "reason": f"Error: {e!s}",
                "timestamp": datetime.now(UTC),
            }
