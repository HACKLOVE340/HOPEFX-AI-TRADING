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

from typing import Dict, List, Optional, Any
from datetime import datetime
import logging
import numpy as np

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
        self.ob_lookback = params.get('ob_lookback', 20)  # Order block lookback
        self.fvg_min_gap = params.get('fvg_min_gap', 0.001)  # Min gap for FVG (0.1%)
        self.liquidity_threshold = params.get('liquidity_threshold', 0.002)  # 0.2%
        self.structure_lookback = params.get('structure_lookback', 50)
        self.ote_fibonacci = params.get('ote_fibonacci', [0.62, 0.705, 0.79])  # OTE levels

        # State tracking
        self.market_structure = 'neutral'  # 'bullish', 'bearish', 'neutral'
        self.last_higher_high = None
        self.last_higher_low = None
        self.last_lower_high = None
        self.last_lower_low = None
        self.order_blocks = {'bullish': [], 'bearish': []}
        self.fair_value_gaps = {'bullish': [], 'bearish': []}

        logger.info(f"SMC ICT Strategy initialized for {config.symbol}")

    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze market using Smart Money Concepts.

        Args:
            data: Market data with OHLCV

        Returns:
            Analysis results including SMC indicators
        """
        try:
            # Extract price data
            prices = data.get('prices', [])
            if len(prices) < self.structure_lookback:
                return {'error': 'Insufficient data'}

            current_price = prices[-1].get('close', 0)
            high = prices[-1].get('high', 0)
            low = prices[-1].get('low', 0)
            volume = prices[-1].get('volume', 0)

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
                'current_price': current_price,
                'high': high,
                'low': low,
                'volume': volume,
                'market_structure': market_structure,
                'order_blocks': order_blocks,
                'fair_value_gaps': fair_value_gaps,
                'liquidity_zones': liquidity_zones,
                'premium_discount': premium_discount,
                'ote_levels': ote_levels,
                'timestamp': datetime.utcnow(),
            }

        except Exception as e:
            logger.error(f"Error in SMC ICT analysis: {e}")
            return {'error': str(e)}

    def generate_signal(self, analysis: Dict[str, Any]) -> Optional[Signal]:
        """
        Generate trading signal based on SMC analysis.

        Args:
            analysis: SMC analysis results

        Returns:
            Trading signal if conditions met
        """
        if 'error' in analysis:
            return None

        try:
            current_price = analysis['current_price']
            market_structure = analysis['market_structure']
            order_blocks = analysis['order_blocks']
            fair_value_gaps = analysis['fair_value_gaps']
            liquidity_zones = analysis['liquidity_zones']
            premium_discount = analysis['premium_discount']
            ote_levels = analysis['ote_levels']

            signal_type = SignalType.HOLD
            confidence = 0.0
            metadata = {}

            # BULLISH SETUP
            if market_structure.get('trend') == 'bullish':
                # Check for bullish order block support
                bullish_ob = self._price_near_level(current_price, order_blocks.get('bullish', []))

                # Check for bullish FVG fill
                bullish_fvg = self._price_in_fvg(current_price, fair_value_gaps.get('bullish', []))

                # Check if in discount zone (good for longs)
                in_discount = premium_discount.get('zone') == 'discount'

                # Check if at OTE level
                at_ote = self._price_near_level(current_price, ote_levels.get('bullish', []))

                # Liquidity swept below
                liquidity_swept = liquidity_zones.get('swept_below', False)

                # Calculate bullish confidence
                bullish_score = 0
                if bullish_ob: bullish_score += 0.25
                if bullish_fvg: bullish_score += 0.25
                if in_discount: bullish_score += 0.2
                if at_ote: bullish_score += 0.2
                if liquidity_swept: bullish_score += 0.1

                if bullish_score >= 0.5:  # Need at least 50% confidence
                    signal_type = SignalType.BUY
                    confidence = min(bullish_score, 1.0)
                    metadata = {
                        'reason': 'SMC Bullish Setup',
                        'order_block': bullish_ob,
                        'fvg': bullish_fvg,
                        'discount_zone': in_discount,
                        'ote_level': at_ote,
                        'structure': market_structure.get('type', 'unknown'),
                    }

            # BEARISH SETUP
            elif market_structure.get('trend') == 'bearish':
                # Check for bearish order block resistance
                bearish_ob = self._price_near_level(current_price, order_blocks.get('bearish', []))

                # Check for bearish FVG fill
                bearish_fvg = self._price_in_fvg(current_price, fair_value_gaps.get('bearish', []))

                # Check if in premium zone (good for shorts)
                in_premium = premium_discount.get('zone') == 'premium'

                # Check if at OTE level
                at_ote = self._price_near_level(current_price, ote_levels.get('bearish', []))

                # Liquidity swept above
                liquidity_swept = liquidity_zones.get('swept_above', False)

                # Calculate bearish confidence
                bearish_score = 0
                if bearish_ob: bearish_score += 0.25
                if bearish_fvg: bearish_score += 0.25
                if in_premium: bearish_score += 0.2
                if at_ote: bearish_score += 0.2
                if liquidity_swept: bearish_score += 0.1

                if bearish_score >= 0.5:  # Need at least 50% confidence
                    signal_type = SignalType.SELL
                    confidence = min(bearish_score, 1.0)
                    metadata = {
                        'reason': 'SMC Bearish Setup',
                        'order_block': bearish_ob,
                        'fvg': bearish_fvg,
                        'premium_zone': in_premium,
                        'ote_level': at_ote,
                        'structure': market_structure.get('type', 'unknown'),
                    }

            # Create signal if not HOLD
            if signal_type != SignalType.HOLD and confidence > 0:
                return Signal(
                    signal_type=signal_type,
                    symbol=self.config.symbol,
                    price=current_price,
                    timestamp=analysis['timestamp'],
                    confidence=confidence,
                    metadata=metadata
                )

            return None

        except Exception as e:
            logger.error(f"Error generating SMC ICT signal: {e}")
            return None

    def _analyze_market_structure(self, prices: List[Dict]) -> Dict[str, Any]:
        """Analyze market structure for BOS/CHoCh"""
        try:
            # Simple structure analysis - identify higher highs/lows or lower highs/lows
            recent_highs = [p['high'] for p in prices[-self.structure_lookback:]]
            recent_lows = [p['low'] for p in prices[-self.structure_lookback:]]

            # Check for higher highs and higher lows (bullish)
            hh_count = sum(1 for i in range(1, len(recent_highs)) if recent_highs[i] > recent_highs[i-1])
            hl_count = sum(1 for i in range(1, len(recent_lows)) if recent_lows[i] > recent_lows[i-1])

            # Check for lower highs and lower lows (bearish)
            lh_count = sum(1 for i in range(1, len(recent_highs)) if recent_highs[i] < recent_highs[i-1])
            ll_count = sum(1 for i in range(1, len(recent_lows)) if recent_lows[i] < recent_lows[i-1])

            if hh_count > lh_count and hl_count > ll_count:
                trend = 'bullish'
                structure_type = 'higher_highs_higher_lows'
            elif lh_count > hh_count and ll_count > hl_count:
                trend = 'bearish'
                structure_type = 'lower_highs_lower_lows'
            else:
                trend = 'neutral'
                structure_type = 'consolidation'

            return {
                'trend': trend,
                'type': structure_type,
                'strength': abs(hh_count - lh_count) / len(recent_highs),
            }

        except Exception as e:
            logger.error(f"Error analyzing market structure: {e}")
            return {'trend': 'neutral', 'type': 'unknown', 'strength': 0}

    def _identify_order_blocks(self, prices: List[Dict]) -> Dict[str, List[float]]:
        """Identify bullish and bearish order blocks"""
        bullish_obs = []
        bearish_obs = []

        try:
            for i in range(len(prices) - self.ob_lookback, len(prices) - 1):
                if i < 2:
                    continue

                # Bullish OB: Last down candle before strong up move
                if (prices[i]['close'] < prices[i]['open'] and  # Down candle
                    prices[i+1]['close'] > prices[i+1]['open'] and  # Up candle
                    prices[i+1]['close'] > prices[i]['high']):  # Breaks previous high
                    bullish_obs.append(prices[i]['low'])

                # Bearish OB: Last up candle before strong down move
                if (prices[i]['close'] > prices[i]['open'] and  # Up candle
                    prices[i+1]['close'] < prices[i+1]['open'] and  # Down candle
                    prices[i+1]['close'] < prices[i]['low']):  # Breaks previous low
                    bearish_obs.append(prices[i]['high'])

        except Exception as e:
            logger.error(f"Error identifying order blocks: {e}")

        return {
            'bullish': bullish_obs[-5:] if bullish_obs else [],  # Keep last 5
            'bearish': bearish_obs[-5:] if bearish_obs else [],
        }

    def _identify_fair_value_gaps(self, prices: List[Dict]) -> Dict[str, List[Dict]]:
        """Identify Fair Value Gaps (imbalances)"""
        bullish_fvgs = []
        bearish_fvgs = []

        try:
            for i in range(2, len(prices)):
                # Bullish FVG: Gap between bar[i-2] high and bar[i] low
                if prices[i]['low'] > prices[i-2]['high']:
                    gap_size = (prices[i]['low'] - prices[i-2]['high']) / prices[i-2]['high']
                    if gap_size >= self.fvg_min_gap:
                        bullish_fvgs.append({
                            'top': prices[i]['low'],
                            'bottom': prices[i-2]['high'],
                            'size': gap_size,
                        })

                # Bearish FVG: Gap between bar[i-2] low and bar[i] high
                if prices[i]['high'] < prices[i-2]['low']:
                    gap_size = (prices[i-2]['low'] - prices[i]['high']) / prices[i]['high']
                    if gap_size >= self.fvg_min_gap:
                        bearish_fvgs.append({
                            'top': prices[i-2]['low'],
                            'bottom': prices[i]['high'],
                            'size': gap_size,
                        })

        except Exception as e:
            logger.error(f"Error identifying FVGs: {e}")

        return {
            'bullish': bullish_fvgs[-3:] if bullish_fvgs else [],  # Keep last 3
            'bearish': bearish_fvgs[-3:] if bearish_fvgs else [],
        }

    def _analyze_liquidity(self, prices: List[Dict]) -> Dict[str, Any]:
        """Analyze liquidity sweeps/raids"""
        try:
            recent_highs = [p['high'] for p in prices[-20:]]
            recent_lows = [p['low'] for p in prices[-20:]]
            current_high = prices[-1]['high']
            current_low = prices[-1]['low']

            # Check if recent high was swept
            swept_above = current_high > max(recent_highs[:-1])

            # Check if recent low was swept
            swept_below = current_low < min(recent_lows[:-1])

            return {
                'swept_above': swept_above,
                'swept_below': swept_below,
                'liquidity_level_high': max(recent_highs[:-1]) if len(recent_highs) > 1 else current_high,
                'liquidity_level_low': min(recent_lows[:-1]) if len(recent_lows) > 1 else current_low,
            }

        except Exception as e:
            logger.error(f"Error analyzing liquidity: {e}")
            return {'swept_above': False, 'swept_below': False}

    def _calculate_premium_discount(self, prices: List[Dict]) -> Dict[str, Any]:
        """Calculate if price is in premium or discount zone"""
        try:
            # Use recent range to determine premium/discount
            recent_high = max(p['high'] for p in prices[-50:])
            recent_low = min(p['low'] for p in prices[-50:])
            current_price = prices[-1]['close']

            range_size = recent_high - recent_low
            mid_point = recent_low + (range_size * 0.5)

            # Premium zone: above 50% of range
            # Discount zone: below 50% of range
            if current_price > mid_point:
                zone = 'premium'
                level = (current_price - mid_point) / (range_size * 0.5)
            else:
                zone = 'discount'
                level = (mid_point - current_price) / (range_size * 0.5)

            return {
                'zone': zone,
                'level': min(level, 1.0),
                'range_high': recent_high,
                'range_low': recent_low,
                'mid_point': mid_point,
            }

        except Exception as e:
            logger.error(f"Error calculating premium/discount: {e}")
            return {'zone': 'neutral', 'level': 0}

    def _calculate_ote_levels(self, prices: List[Dict], structure: Dict) -> Dict[str, List[float]]:
        """Calculate Optimal Trade Entry levels (Fibonacci retracement)"""
        try:
            recent_high = max(p['high'] for p in prices[-50:])
            recent_low = min(p['low'] for p in prices[-50:])
            range_size = recent_high - recent_low

            bullish_ote = []
            bearish_ote = []

            # For bullish trend, OTE is retracement from high
            if structure.get('trend') == 'bullish':
                for fib in self.ote_fibonacci:
                    level = recent_high - (range_size * fib)
                    bullish_ote.append(level)

            # For bearish trend, OTE is retracement from low
            if structure.get('trend') == 'bearish':
                for fib in self.ote_fibonacci:
                    level = recent_low + (range_size * fib)
                    bearish_ote.append(level)

            return {
                'bullish': bullish_ote,
                'bearish': bearish_ote,
            }

        except Exception as e:
            logger.error(f"Error calculating OTE levels: {e}")
            return {'bullish': [], 'bearish': []}

    def _price_near_level(self, price: float, levels: List[float], threshold: float = 0.001) -> bool:
        """Check if price is near any of the given levels"""
        for level in levels:
            if abs(price - level) / level <= threshold:
                return True
        return False

    def _price_in_fvg(self, price: float, fvgs: List[Dict]) -> bool:
        """Check if price is inside any Fair Value Gap"""
        for fvg in fvgs:
            if fvg['bottom'] <= price <= fvg['top']:
                return True
        return False
