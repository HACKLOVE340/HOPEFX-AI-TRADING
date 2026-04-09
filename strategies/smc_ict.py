# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Smart Money Concepts (SMC) - Inner Circle Trader (ICT) Strategy

This strategy implements Smart Money Concepts including:
- Order Blocks (OB)
- Fair Value Gaps (FVG)
- Liquidity Sweeps/Raids
- Break of Structure (BOS) / Change of Character (CHoCh)
- Premium/Discount zones
- Optimal Trade Entry (OTE) levels
- Market structure analysis
"""

import logging
from datetime import datetime, timezone

UTC = timezone.utc
from typing import Any

from .base import BaseStrategy, Signal, SignalType, StrategyConfig

logger = logging.getLogger(__name__)


class SMCICTStrategy(BaseStrategy):
    """
    Smart Money Concepts (ICT) Strategy.

    Identifies institutional order flow and smart money footprints:
    - Order blocks for support/resistance
    - Fair value gaps for entry zones
    - Liquidity sweeps for reversals
    - Market structure shifts
    """

    def __init__(self, config: StrategyConfig):
        """
        Initialize SMC ICT Strategy.

        Args:
            config: Strategy configuration
        """
        super().__init__(config)

        # Strategy parameters
        params = config.parameters or {}
        self.ob_lookback = params.get("ob_lookback", 20)  # Order block lookback
        self.fvg_min_gap = params.get("fvg_min_gap", 0.001)  # Min gap for FVG (0.1%)
        self.liquidity_threshold = params.get("liquidity_threshold", 0.002)  # 0.2%
        self.structure_lookback = params.get("structure_lookback", 50)
        self.ote_fibonacci = params.get(
            "ote_fibonacci",
            [0.62, 0.705, 0.79],
        )  # OTE levels

        # State tracking
        self.market_structure = "neutral"  # 'bullish', 'bearish', 'neutral'
        self.last_higher_high = None
        self.last_higher_low = None
        self.last_lower_high = None
        self.last_lower_low = None
        self.order_blocks = {"bullish": [], "bearish": []}
        self.fair_value_gaps = {"bullish": [], "bearish": []}

        logger.info("SMC ICT Strategy initialized for %s", config.symbol)

    def analyze(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        Analyze market using Smart Money Concepts.

        Args:
            data: Market data with OHLCV

        Returns:
            Analysis results including SMC indicators
        """
        try:
            # Extract price data
            prices = data.get("prices", [])
            if len(prices) < self.structure_lookback:
                return {"error": "Insufficient data"}

            current_price = prices[-1].get("close", 0)
            high = prices[-1].get("high", 0)
            low = prices[-1].get("low", 0)
            volume = prices[-1].get("volume", 0)

            # 1. Market Structure Analysis
            market_structure = self._analyze_market_structure(prices)

            # 2. Order Block Detection
            order_blocks = self._identify_order_blocks(prices)

            # 3. Fair Value Gap Detection
            fair_value_gaps = self._identify_fair_value_gaps(prices)

            # 4. Liquidity Analysis
            liquidity_zones = self._analyze_liquidity(prices)

            # 5. Premium/Discount Analysis
            premium_discount = self._calculate_premium_discount(prices)

            # 6. Optimal Trade Entry Levels
            ote_levels = self._calculate_ote_levels(prices, market_structure)

            return {
                "current_price": current_price,
                "high": high,
                "low": low,
                "volume": volume,
                "market_structure": market_structure,
                "order_blocks": order_blocks,
                "fair_value_gaps": fair_value_gaps,
                "liquidity_zones": liquidity_zones,
                "premium_discount": premium_discount,
                "ote_levels": ote_levels,
                "timestamp": datetime.now(UTC),
            }

        except Exception as e:
            logger.error("Error in SMC ICT analysis: %s", e)

            return {"error": str(e)}

    def generate_signal(self, analysis: dict[str, Any]) -> Signal | None:
        """
        Generate trading signal based on SMC analysis.

        Args:
            analysis: SMC analysis results

        Returns:
            Trading signal if conditions met
        """
        if "error" in analysis:
            return None

        try:
            current_price = analysis["current_price"]
            market_structure = analysis["market_structure"]
            order_blocks = analysis["order_blocks"]
            fair_value_gaps = analysis["fair_value_gaps"]
            liquidity_zones = analysis["liquidity_zones"]
            premium_discount = analysis["premium_discount"]
            ote_levels = analysis["ote_levels"]

            signal_type = SignalType.HOLD
            confidence = 0.0
            metadata = {}

            # BULLISH SETUP
            if market_structure.get("trend") == "bullish":
                # Check for bullish order block support
                bullish_ob = self._price_near_level(
                    current_price,
                    order_blocks.get("bullish", []),
                )

                # Check for bullish FVG fill
                bullish_fvg = self._price_in_fvg(
                    current_price,
                    fair_value_gaps.get("bullish", []),
                )

                # Check if in discount zone (good for longs)
                in_discount = premium_discount.get("zone") == "discount"

                # Check if at OTE level
                at_ote = self._price_near_level(
                    current_price,
                    ote_levels.get("bullish", []),
                )

                # Liquidity swept below
                liquidity_swept = liquidity_zones.get("swept_below", False)

                # Calculate bullish confidence
                bullish_score = 0
                if bullish_ob:
                    bullish_score += 0.25
                if bullish_fvg:
                    bullish_score += 0.25
                if in_discount:
                    bullish_score += 0.2
                if at_ote:
                    bullish_score += 0.2
                if liquidity_swept:
                    bullish_score += 0.1

                if bullish_score >= 0.5:  # Need at least 50% confidence
                    signal_type = SignalType.BUY
                    confidence = min(bullish_score, 1.0)
                    metadata = {
                        "reason": "SMC Bullish Setup",
                        "order_block": bullish_ob,
                        "fvg": bullish_fvg,
                        "discount_zone": in_discount,
                        "ote_level": at_ote,
                        "structure": market_structure.get("type", "unknown"),
                    }

            # BEARISH SETUP
            elif market_structure.get("trend") == "bearish":
                # Check for bearish order block resistance
                bearish_ob = self._price_near_level(
                    current_price,
                    order_blocks.get("bearish", []),
                )

                # Check for bearish FVG fill
                bearish_fvg = self._price_in_fvg(
                    current_price,
                    fair_value_gaps.get("bearish", []),
                )

                # Check if in premium zone (good for shorts)
                in_premium = premium_discount.get("zone") == "premium"

                # Check if at OTE level
                at_ote = self._price_near_level(
                    current_price,
                    ote_levels.get("bearish", []),
                )

                # Liquidity swept above
                liquidity_swept = liquidity_zones.get("swept_above", False)

                # Calculate bearish confidence
                bearish_score = 0
                if bearish_ob:
                    bearish_score += 0.25
                if bearish_fvg:
                    bearish_score += 0.25
                if in_premium:
                    bearish_score += 0.2
                if at_ote:
                    bearish_score += 0.2
                if liquidity_swept:
                    bearish_score += 0.1

                if bearish_score >= 0.5:  # Need at least 50% confidence
                    signal_type = SignalType.SELL
                    confidence = min(bearish_score, 1.0)
                    metadata = {
                        "reason": "SMC Bearish Setup",
                        "order_block": bearish_ob,
                        "fvg": bearish_fvg,
                        "premium_zone": in_premium,
                        "ote_level": at_ote,
                        "structure": market_structure.get("type", "unknown"),
                    }

            # Create signal if not HOLD
            if signal_type != SignalType.HOLD and confidence > 0:
                return Signal(
                    signal_type=signal_type,
                    symbol=self.config.symbol,
                    price=current_price,
                    timestamp=analysis["timestamp"],
                    confidence=confidence,
                    metadata=metadata,
                )

            return None

        except Exception as e:
            logger.error("Error generating SMC ICT signal: %s", e)

            return None

    def _analyze_market_structure(self, prices: list[dict]) -> dict[str, Any]:
        """Analyze market structure using swing pivots to detect BOS and CHoCH.

        Algorithm
        ---------
        1. Identify swing highs (SH) and swing lows (SL) using a left/right
           neighbour comparison (``pivot_n`` bars on each side).
        2. Walk the confirmed pivots in order to track the current sequence of
           Higher-Highs / Higher-Lows (bullish) or Lower-Highs / Lower-Lows
           (bearish).
        3. Detect Break of Structure (BOS): price closes beyond the most recent
           SH/SL in the direction of the prevailing trend — trend continuation.
        4. Detect Change of Character (CHoCH): price closes beyond the most
           recent SH/SL *against* the prevailing trend — potential reversal.
        """
        try:
            window = prices[-self.structure_lookback :]
            n = len(window)
            pivot_n: int = max(2, self.structure_lookback // 10)  # adaptive neighbour

            # ── Step 1: find swing highs and swing lows ───────────────────────
            swing_highs: list[tuple[int, float]] = []  # (index, price)
            swing_lows: list[tuple[int, float]] = []

            for i in range(pivot_n, n - pivot_n):
                h = window[i]["high"]
                lo = window[i]["low"]
                left_h = [window[j]["high"] for j in range(i - pivot_n, i)]
                right_h = [window[j]["high"] for j in range(i + 1, i + pivot_n + 1)]
                left_l = [window[j]["low"] for j in range(i - pivot_n, i)]
                right_l = [window[j]["low"] for j in range(i + 1, i + pivot_n + 1)]

                if h >= max(left_h) and h >= max(right_h):
                    swing_highs.append((i, h))
                if lo <= min(left_l) and lo <= min(right_l):
                    swing_lows.append((i, lo))

            if len(swing_highs) < 2 or len(swing_lows) < 2:
                # Not enough structure yet — neutral
                return {
                    "trend": "neutral",
                    "type": "insufficient_pivots",
                    "strength": 0.0,
                    "bos": False,
                    "choch": False,
                    "event": "none",
                    "last_sh": None,
                    "last_sl": None,
                }

            # ── Step 2: classify structure from last two SH and last two SL ───
            _, sh_prev_val = swing_highs[-2]
            _, sh_last_val = swing_highs[-1]
            _, sl_prev_val = swing_lows[-2]
            _, sl_last_val = swing_lows[-1]

            higher_high = sh_last_val > sh_prev_val
            higher_low = sl_last_val > sl_prev_val
            lower_high = sh_last_val < sh_prev_val
            lower_low = sl_last_val < sl_prev_val

            if higher_high and higher_low:
                trend = "bullish"
                structure_type = "higher_highs_higher_lows"
            elif lower_high and lower_low:
                trend = "bearish"
                structure_type = "lower_highs_lower_lows"
            elif higher_high and lower_low:
                trend = "neutral"
                structure_type = "expanding_range"
            else:
                trend = "neutral"
                structure_type = "consolidation"

            # ── Step 3/4: detect BOS / CHoCH from the last closed candle ──────
            current_close = window[-1]["close"]
            bos = False
            choch = False
            event_type = "none"

            if trend == "bullish":
                # BOS: bullish close above last SH (structure continuation)
                if current_close > sh_last_val:
                    bos = True
                    event_type = "BOS_bullish"
                # CHoCH: bearish close below last SL (character change)
                elif current_close < sl_last_val:
                    choch = True
                    event_type = "CHoCH_bearish"
            elif trend == "bearish":
                # BOS: bearish close below last SL (structure continuation)
                if current_close < sl_last_val:
                    bos = True
                    event_type = "BOS_bearish"
                # CHoCH: bullish close above last SH (character change)
                elif current_close > sh_last_val:
                    choch = True
                    event_type = "CHoCH_bullish"
            elif current_close > sh_last_val:
                # Neutral + close above last SH → bullish character change
                choch = True
                event_type = "CHoCH_bullish"
            elif current_close < sl_last_val:
                # Neutral + close below last SL → bearish character change
                choch = True
                event_type = "CHoCH_bearish"

            # Strength: relative distance of HH/HL or LH/LL moves
            sh_range = abs(sh_last_val - sh_prev_val)
            sl_range = abs(sl_last_val - sl_prev_val)
            price_range = max(window[-1]["high"] - window[0]["low"], 1e-9)
            strength = min(1.0, (sh_range + sl_range) / (2.0 * price_range))

            return {
                "trend": trend,
                "type": structure_type,
                "strength": round(strength, 4),
                "bos": bos,
                "choch": choch,
                "event": event_type,
                "last_sh": sh_last_val,
                "last_sl": sl_last_val,
            }

        except Exception as e:
            logger.error("Error analyzing market structure: %s", e)
            return {
                "trend": "neutral",
                "type": "unknown",
                "strength": 0.0,
                "bos": False,
                "choch": False,
                "event": "none",
                "last_sh": None,
                "last_sl": None,
            }

    def _identify_order_blocks(self, prices: list[dict]) -> dict[str, list[float]]:
        """Identify bullish and bearish order blocks"""
        bullish_obs = []
        bearish_obs = []

        try:
            for i in range(len(prices) - self.ob_lookback, len(prices) - 1):
                if i < 2:
                    continue

                # Bullish OB: Last down candle before strong up move
                if (
                    prices[i]["close"] < prices[i]["open"]  # Down candle
                    and prices[i + 1]["close"] > prices[i + 1]["open"]  # Up candle
                    and prices[i + 1]["close"] > prices[i]["high"]
                ):  # Breaks previous high
                    bullish_obs.append(prices[i]["low"])

                # Bearish OB: Last up candle before strong down move
                if (
                    prices[i]["close"] > prices[i]["open"]  # Up candle
                    and prices[i + 1]["close"] < prices[i + 1]["open"]  # Down candle
                    and prices[i + 1]["close"] < prices[i]["low"]
                ):  # Breaks previous low
                    bearish_obs.append(prices[i]["high"])

        except Exception as e:
            logger.error("Error identifying order blocks: %s", e)

        return {
            "bullish": bullish_obs[-5:] if bullish_obs else [],  # Keep last 5
            "bearish": bearish_obs[-5:] if bearish_obs else [],
        }

    def _identify_fair_value_gaps(self, prices: list[dict]) -> dict[str, list[dict]]:
        """Identify Fair Value Gaps (imbalances)"""
        bullish_fvgs = []
        bearish_fvgs = []

        try:
            for i in range(2, len(prices)):
                # Bullish FVG: Gap between bar[i-2] high and bar[i] low
                if prices[i]["low"] > prices[i - 2]["high"]:
                    gap_size = (prices[i]["low"] - prices[i - 2]["high"]) / prices[i - 2]["high"]
                    if gap_size >= self.fvg_min_gap:
                        bullish_fvgs.append(
                            {
                                "top": prices[i]["low"],
                                "bottom": prices[i - 2]["high"],
                                "size": gap_size,
                            },
                        )

                # Bearish FVG: Gap between bar[i-2] low and bar[i] high
                if prices[i]["high"] < prices[i - 2]["low"]:
                    gap_size = (prices[i - 2]["low"] - prices[i]["high"]) / prices[i]["high"]
                    if gap_size >= self.fvg_min_gap:
                        bearish_fvgs.append(
                            {
                                "top": prices[i - 2]["low"],
                                "bottom": prices[i]["high"],
                                "size": gap_size,
                            },
                        )

        except Exception as e:
            logger.error("Error identifying FVGs: %s", e)

        return {
            "bullish": bullish_fvgs[-3:] if bullish_fvgs else [],  # Keep last 3
            "bearish": bearish_fvgs[-3:] if bearish_fvgs else [],
        }

    def _analyze_liquidity(self, prices: list[dict]) -> dict[str, Any]:
        """Analyze liquidity sweeps/raids"""
        try:
            recent_highs = [p["high"] for p in prices[-20:]]
            recent_lows = [p["low"] for p in prices[-20:]]
            current_high = prices[-1]["high"]
            current_low = prices[-1]["low"]

            # Check if recent high was swept
            swept_above = current_high > max(recent_highs[:-1])

            # Check if recent low was swept
            swept_below = current_low < min(recent_lows[:-1])

            return {
                "swept_above": swept_above,
                "swept_below": swept_below,
                "liquidity_level_high": max(recent_highs[:-1]) if len(recent_highs) > 1 else current_high,
                "liquidity_level_low": min(recent_lows[:-1]) if len(recent_lows) > 1 else current_low,
            }

        except Exception as e:
            logger.error("Error analyzing liquidity: %s", e)

            return {"swept_above": False, "swept_below": False}

    def _calculate_premium_discount(self, prices: list[dict]) -> dict[str, Any]:
        """Calculate if price is in premium or discount zone"""
        try:
            # Use recent range to determine premium/discount
            recent_high = max(p["high"] for p in prices[-50:])
            recent_low = min(p["low"] for p in prices[-50:])
            current_price = prices[-1]["close"]

            range_size = recent_high - recent_low
            mid_point = recent_low + (range_size * 0.5)

            # Premium zone: above 50% of range
            # Discount zone: below 50% of range
            if current_price > mid_point:
                zone = "premium"
                level = (current_price - mid_point) / (range_size * 0.5)
            else:
                zone = "discount"
                level = (mid_point - current_price) / (range_size * 0.5)

            return {
                "zone": zone,
                "level": min(level, 1.0),
                "range_high": recent_high,
                "range_low": recent_low,
                "mid_point": mid_point,
            }

        except Exception as e:
            logger.error("Error calculating premium/discount: %s", e)

            return {"zone": "neutral", "level": 0}

    def _calculate_ote_levels(
        self,
        prices: list[dict],
        structure: dict,
    ) -> dict[str, list[float]]:
        """Calculate Optimal Trade Entry levels (Fibonacci retracement)"""
        try:
            recent_high = max(p["high"] for p in prices[-50:])
            recent_low = min(p["low"] for p in prices[-50:])
            range_size = recent_high - recent_low

            bullish_ote = []
            bearish_ote = []

            # For bullish trend, OTE is retracement from high
            if structure.get("trend") == "bullish":
                for fib in self.ote_fibonacci:
                    level = recent_high - (range_size * fib)
                    bullish_ote.append(level)

            # For bearish trend, OTE is retracement from low
            if structure.get("trend") == "bearish":
                for fib in self.ote_fibonacci:
                    level = recent_low + (range_size * fib)
                    bearish_ote.append(level)

            return {
                "bullish": bullish_ote,
                "bearish": bearish_ote,
            }

        except Exception as e:
            logger.error("Error calculating OTE levels: %s", e)

            return {"bullish": [], "bearish": []}

    def _price_near_level(
        self,
        price: float,
        levels: list[float],
        threshold: float = 0.001,
    ) -> bool:
        """Check if price is near any of the given levels"""
        return any(abs(price - level) / level <= threshold for level in levels)

    def _price_in_fvg(self, price: float, fvgs: list[dict]) -> bool:
        """Check if price is inside any Fair Value Gap"""
        return any(fvg["bottom"] <= price <= fvg["top"] for fvg in fvgs)
