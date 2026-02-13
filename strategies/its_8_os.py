"""
ICT Trading System - 8 Optimal Setups (ITS-8-OS)

This strategy implements the 8 core optimal setups from the
Inner Circle Trader methodology:
1. AMD (Accumulation, Manipulation, Distribution)
2. Power of 3
3. Judas Swing
4. Kill Zones (London, New York, Asian)
5. ICT Turtle Soup
6. Silver Bullet Setup
7. Optimal Trade Entry
8. Session-based Analysis
"""

from typing import Dict, List, Optional, Any
from datetime import datetime, time
import logging
import numpy as np

from .base import BaseStrategy, Signal, SignalType, StrategyConfig

logger = logging.getLogger(__name__)


class ITS8OSStrategy(BaseStrategy):
    """
    ICT 8 Optimal Setups Strategy.

    Implements the complete ICT trading system with all 8 setups:
    - AMD pattern recognition
    - Power of 3 structure
    - Judas Swing detection
    - Kill Zone timing
    - Turtle Soup reversals
    - Silver Bullet entries
    - OTE precision
    - Session-based logic
    """

    def __init__(self, config: StrategyConfig):
        """
        Initialize ITS-8-OS Strategy.

        Args:
            config: Strategy configuration
        """
        super().__init__(config)

        # Strategy parameters
        params = config.parameters or {}
        self.enabled_setups = params.get('enabled_setups', list(range(1, 9)))  # All 8 by default
        self.min_setup_score = params.get('min_setup_score', 0.6)
        self.confluence_required = params.get('confluence_required', 2)  # Min setups agreeing

        # Kill Zone times (UTC)
        self.kill_zones = {
            'asian': {'start': time(0, 0), 'end': time(3, 0)},
            'london': {'start': time(2, 0), 'end': time(5, 0)},  # London open
            'new_york': {'start': time(8, 30), 'end': time(11, 0)},  # NY open
            'london_close': {'start': time(10, 0), 'end': time(12, 0)},
        }

        # State tracking
        self.current_session = None
        self.session_high = None
        self.session_low = None
        self.manipulation_detected = False
        self.amd_phase = 'accumulation'  # accumulation, manipulation, distribution

        logger.info(f"ITS-8-OS Strategy initialized for {config.symbol}")

    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze market using all 8 ICT optimal setups.

        Args:
            data: Market data with OHLCV and timestamp

        Returns:
            Analysis results for all 8 setups
        """
        try:
            prices = data.get('prices', [])
            if len(prices) < 50:
                return {'error': 'Insufficient data'}

            current_price = prices[-1].get('close', 0)
            current_time = data.get('timestamp', datetime.utcnow())

            # Run all 8 optimal setups
            setup_results = {}

            # Setup 1: AMD Pattern
            if 1 in self.enabled_setups:
                setup_results['amd'] = self._analyze_amd_pattern(prices)

            # Setup 2: Power of 3
            if 2 in self.enabled_setups:
                setup_results['power_of_3'] = self._analyze_power_of_3(prices)

            # Setup 3: Judas Swing
            if 3 in self.enabled_setups:
                setup_results['judas_swing'] = self._analyze_judas_swing(prices)

            # Setup 4: Kill Zones
            if 4 in self.enabled_setups:
                setup_results['kill_zone'] = self._analyze_kill_zones(current_time)

            # Setup 5: Turtle Soup
            if 5 in self.enabled_setups:
                setup_results['turtle_soup'] = self._analyze_turtle_soup(prices)

            # Setup 6: Silver Bullet
            if 6 in self.enabled_setups:
                setup_results['silver_bullet'] = self._analyze_silver_bullet(prices, current_time)

            # Setup 7: Optimal Trade Entry
            if 7 in self.enabled_setups:
                setup_results['ote'] = self._analyze_ote(prices)

            # Setup 8: Session Analysis
            if 8 in self.enabled_setups:
                setup_results['session'] = self._analyze_session(prices, current_time)

            # Calculate confluence
            confluence = self._calculate_confluence(setup_results)

            return {
                'current_price': current_price,
                'timestamp': current_time,
                'setup_results': setup_results,
                'confluence': confluence,
                'active_kill_zone': setup_results.get('kill_zone', {}).get('active_zone'),
            }

        except Exception as e:
            logger.error(f"Error in ITS-8-OS analysis: {e}")
            return {'error': str(e)}

    def generate_signal(self, analysis: Dict[str, Any]) -> Optional[Signal]:
        """
        Generate trading signal based on ITS-8-OS analysis.

        Args:
            analysis: ITS-8-OS analysis results

        Returns:
            Trading signal if optimal setup conditions met
        """
        if 'error' in analysis:
            return None

        try:
            current_price = analysis['current_price']
            confluence = analysis['confluence']
            setup_results = analysis['setup_results']

            # Check if we have enough confluence
            if confluence['agreeing_setups'] < self.confluence_required:
                return None

            signal_type = SignalType.HOLD
            confidence = 0.0
            metadata = {}

            # BULLISH SIGNAL - Multiple setups agree on long
            if confluence['bullish_score'] > confluence['bearish_score']:
                signal_type = SignalType.BUY
                confidence = min(confluence['bullish_score'], 1.0)
                metadata = {
                    'reason': 'ITS-8-OS Bullish Confluence',
                    'agreeing_setups': confluence['agreeing_setups'],
                    'bullish_setups': confluence['bullish_setups'],
                    'active_kill_zone': analysis.get('active_kill_zone'),
                    'setup_details': self._extract_signal_details(setup_results, 'bullish'),
                }

            # BEARISH SIGNAL - Multiple setups agree on short
            elif confluence['bearish_score'] > confluence['bullish_score']:
                signal_type = SignalType.SELL
                confidence = min(confluence['bearish_score'], 1.0)
                metadata = {
                    'reason': 'ITS-8-OS Bearish Confluence',
                    'agreeing_setups': confluence['agreeing_setups'],
                    'bearish_setups': confluence['bearish_setups'],
                    'active_kill_zone': analysis.get('active_kill_zone'),
                    'setup_details': self._extract_signal_details(setup_results, 'bearish'),
                }

            # Only generate signal if confidence meets minimum
            if signal_type != SignalType.HOLD and confidence >= self.min_setup_score:
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
            logger.error(f"Error generating ITS-8-OS signal: {e}")
            return None

    def _analyze_amd_pattern(self, prices: List[Dict]) -> Dict[str, Any]:
        """
        Setup 1: Accumulation, Manipulation, Distribution (AMD)

        Identifies the 3-phase market maker cycle
        """
        try:
            # Simplified AMD detection
            recent_prices = [p['close'] for p in prices[-30:]]
            recent_highs = [p['high'] for p in prices[-30:]]
            recent_lows = [p['low'] for p in prices[-30:]]

            # Calculate volatility
            price_range = max(recent_highs) - min(recent_lows)
            avg_price = np.mean(recent_prices)
            volatility = np.std(recent_prices) / avg_price

            # Accumulation: Low volatility, tight range
            if volatility < 0.005:  # 0.5%
                phase = 'accumulation'
                signal = 'neutral'
                score = 0.3

            # Manipulation: Sharp move against trend (liquidity grab)
            elif len(prices) > 5:
                last_move = abs(prices[-1]['close'] - prices[-5]['close']) / prices[-5]['close']
                if last_move > 0.01:  # 1% move
                    phase = 'manipulation'
                    # After manipulation, expect reversal
                    if prices[-1]['close'] < prices[-5]['close']:
                        signal = 'bullish'  # Down manipulation -> up distribution
                        score = 0.7
                    else:
                        signal = 'bearish'  # Up manipulation -> down distribution
                        score = 0.7
                else:
                    phase = 'distribution'
                    signal = 'neutral'
                    score = 0.4
            else:
                phase = 'unknown'
                signal = 'neutral'
                score = 0.0

            return {
                'phase': phase,
                'signal': signal,
                'score': score,
                'volatility': volatility,
            }

        except Exception as e:
            logger.error(f"Error analyzing AMD: {e}")
            return {'phase': 'unknown', 'signal': 'neutral', 'score': 0.0}

    def _analyze_power_of_3(self, prices: List[Dict]) -> Dict[str, Any]:
        """
        Setup 2: Power of 3 Pattern

        Identifies accumulation, manipulation, and distribution within session
        """
        try:
            # Look for the pattern in recent candles
            if len(prices) < 3:
                return {'detected': False, 'signal': 'neutral', 'score': 0.0}

            # Simplified: Look for range expansion after consolidation
            consolidation = all(
                abs(prices[i]['close'] - prices[i]['open']) <
                abs(prices[-1]['close'] - prices[-1]['open'])
                for i in range(-10, -1) if i + len(prices) > 0
            )

            expansion = abs(prices[-1]['close'] - prices[-1]['open']) / prices[-1]['open'] > 0.005

            if consolidation and expansion:
                if prices[-1]['close'] > prices[-1]['open']:
                    signal = 'bullish'
                    score = 0.7
                else:
                    signal = 'bearish'
                    score = 0.7
                detected = True
            else:
                signal = 'neutral'
                score = 0.0
                detected = False

            return {
                'detected': detected,
                'signal': signal,
                'score': score,
            }

        except Exception as e:
            logger.error(f"Error analyzing Power of 3: {e}")
            return {'detected': False, 'signal': 'neutral', 'score': 0.0}

    def _analyze_judas_swing(self, prices: List[Dict]) -> Dict[str, Any]:
        """
        Setup 3: Judas Swing

        False breakout followed by reversal
        """
        try:
            if len(prices) < 20:
                return {'detected': False, 'signal': 'neutral', 'score': 0.0}

            # Look for false breakout
            recent_high = max(p['high'] for p in prices[-20:-1])
            recent_low = min(p['low'] for p in prices[-20:-1])
            current = prices[-1]

            # Bullish Judas: False break below support, then reversal up
            false_break_low = current['low'] < recent_low and current['close'] > recent_low

            # Bearish Judas: False break above resistance, then reversal down
            false_break_high = current['high'] > recent_high and current['close'] < recent_high

            if false_break_low:
                signal = 'bullish'
                score = 0.8
                detected = True
            elif false_break_high:
                signal = 'bearish'
                score = 0.8
                detected = True
            else:
                signal = 'neutral'
                score = 0.0
                detected = False

            return {
                'detected': detected,
                'signal': signal,
                'score': score,
            }

        except Exception as e:
            logger.error(f"Error analyzing Judas Swing: {e}")
            return {'detected': False, 'signal': 'neutral', 'score': 0.0}

    def _analyze_kill_zones(self, current_time: datetime) -> Dict[str, Any]:
        """
        Setup 4: Kill Zones

        High-probability trading times
        """
        try:
            current_time_only = current_time.time()
            active_zone = None
            score = 0.0

            # Check which kill zone we're in
            for zone_name, zone_times in self.kill_zones.items():
                if zone_times['start'] <= current_time_only <= zone_times['end']:
                    active_zone = zone_name
                    # Higher score for prime zones (London, New York)
                    if zone_name in ['london', 'new_york']:
                        score = 0.8
                    else:
                        score = 0.5
                    break

            in_kill_zone = active_zone is not None

            return {
                'in_kill_zone': in_kill_zone,
                'active_zone': active_zone,
                'score': score,
                'signal': 'neutral',  # Kill zones don't give direction, just timing
            }

        except Exception as e:
            logger.error(f"Error analyzing kill zones: {e}")
            return {'in_kill_zone': False, 'active_zone': None, 'score': 0.0, 'signal': 'neutral'}

    def _analyze_turtle_soup(self, prices: List[Dict]) -> Dict[str, Any]:
        """
        Setup 5: ICT Turtle Soup

        Failed 20-day high/low breakout reversal
        """
        try:
            if len(prices) < 20:
                return {'detected': False, 'signal': 'neutral', 'score': 0.0}

            # Get 20-day high/low (excluding current bar)
            twenty_day_high = max(p['high'] for p in prices[-21:-1])
            twenty_day_low = min(p['low'] for p in prices[-21:-1])

            current = prices[-1]

            # Bullish Turtle Soup: Failed break below 20-day low
            if current['low'] < twenty_day_low and current['close'] > twenty_day_low:
                signal = 'bullish'
                score = 0.75
                detected = True

            # Bearish Turtle Soup: Failed break above 20-day high
            elif current['high'] > twenty_day_high and current['close'] < twenty_day_high:
                signal = 'bearish'
                score = 0.75
                detected = True

            else:
                signal = 'neutral'
                score = 0.0
                detected = False

            return {
                'detected': detected,
                'signal': signal,
                'score': score,
            }

        except Exception as e:
            logger.error(f"Error analyzing Turtle Soup: {e}")
            return {'detected': False, 'signal': 'neutral', 'score': 0.0}

    def _analyze_silver_bullet(self, prices: List[Dict], current_time: datetime) -> Dict[str, Any]:
        """
        Setup 6: Silver Bullet Setup

        Specific high-probability setup during key times
        """
        try:
            # Silver Bullet typically occurs during first hour of London/NY
            current_time_only = current_time.time()

            # London Silver Bullet: 3:00-4:00 UTC
            london_sb = time(3, 0) <= current_time_only <= time(4, 0)

            # NY Silver Bullet: 9:00-10:00 UTC
            ny_sb = time(9, 0) <= current_time_only <= time(10, 0)

            in_sb_window = london_sb or ny_sb

            if not in_sb_window:
                return {'detected': False, 'signal': 'neutral', 'score': 0.0}

            # Look for setup: Quick move followed by retracement
            if len(prices) >= 5:
                # Check for momentum followed by pullback
                initial_move = prices[-5]['close'] - prices[-10]['close'] if len(prices) >= 10 else 0
                recent_pullback = prices[-1]['close'] - prices[-5]['close']

                if initial_move > 0 and recent_pullback < 0:
                    # Bullish: Up move, then pullback
                    signal = 'bullish'
                    score = 0.85
                    detected = True
                elif initial_move < 0 and recent_pullback > 0:
                    # Bearish: Down move, then pullback
                    signal = 'bearish'
                    score = 0.85
                    detected = True
                else:
                    signal = 'neutral'
                    score = 0.0
                    detected = False
            else:
                signal = 'neutral'
                score = 0.0
                detected = False

            return {
                'detected': detected,
                'signal': signal,
                'score': score,
                'window': 'london' if london_sb else 'new_york' if ny_sb else None,
            }

        except Exception as e:
            logger.error(f"Error analyzing Silver Bullet: {e}")
            return {'detected': False, 'signal': 'neutral', 'score': 0.0}

    def _analyze_ote(self, prices: List[Dict]) -> Dict[str, Any]:
        """
        Setup 7: Optimal Trade Entry

        Fibonacci retracement entry zones
        """
        try:
            # Calculate swing high/low
            swing_high = max(p['high'] for p in prices[-50:])
            swing_low = min(p['low'] for p in prices[-50:])
            swing_range = swing_high - swing_low
            current_price = prices[-1]['close']

            # OTE zone: 0.62 to 0.79 retracement
            ote_low = swing_low + (swing_range * 0.62)
            ote_high = swing_low + (swing_range * 0.79)

            # Check if in OTE zone
            in_ote_zone = ote_low <= current_price <= ote_high

            if in_ote_zone:
                # Determine direction based on recent trend
                recent_trend = prices[-1]['close'] - prices[-20]['close']
                if recent_trend > 0:
                    signal = 'bullish'
                else:
                    signal = 'bearish'
                score = 0.7
            else:
                signal = 'neutral'
                score = 0.0

            return {
                'in_ote_zone': in_ote_zone,
                'signal': signal,
                'score': score,
                'ote_range': (ote_low, ote_high),
            }

        except Exception as e:
            logger.error(f"Error analyzing OTE: {e}")
            return {'in_ote_zone': False, 'signal': 'neutral', 'score': 0.0}

    def _analyze_session(self, prices: List[Dict], current_time: datetime) -> Dict[str, Any]:
        """
        Setup 8: Session-based Analysis

        Analyzes behavior within specific trading sessions
        """
        try:
            current_hour = current_time.hour

            # Determine session
            if 0 <= current_hour < 8:
                session = 'asian'
            elif 8 <= current_hour < 16:
                session = 'london'
            else:
                session = 'new_york'

            # Simple session bias
            # Asian: Range-bound
            # London: Trending
            # NY: Reversal potential

            if session == 'asian':
                signal = 'neutral'
                score = 0.3
                bias = 'range'
            elif session == 'london':
                # Look for trend continuation
                if len(prices) >= 10:
                    trend = prices[-1]['close'] - prices[-10]['close']
                    if trend > 0:
                        signal = 'bullish'
                        score = 0.6
                    else:
                        signal = 'bearish'
                        score = 0.6
                    bias = 'trending'
                else:
                    signal = 'neutral'
                    score = 0.3
                    bias = 'trending'
            else:  # NY session
                signal = 'neutral'
                score = 0.4
                bias = 'reversal'

            return {
                'session': session,
                'signal': signal,
                'score': score,
                'bias': bias,
            }

        except Exception as e:
            logger.error(f"Error analyzing session: {e}")
            return {'session': 'unknown', 'signal': 'neutral', 'score': 0.0}

    def _calculate_confluence(self, setup_results: Dict[str, Dict]) -> Dict[str, Any]:
        """Calculate confluence across all setups"""
        try:
            bullish_count = 0
            bearish_count = 0
            bullish_score = 0.0
            bearish_score = 0.0
            bullish_setups = []
            bearish_setups = []

            for setup_name, result in setup_results.items():
                signal = result.get('signal', 'neutral')
                score = result.get('score', 0.0)

                if signal == 'bullish':
                    bullish_count += 1
                    bullish_score += score
                    bullish_setups.append(setup_name)
                elif signal == 'bearish':
                    bearish_count += 1
                    bearish_score += score
                    bearish_setups.append(setup_name)

            # Normalize scores
            total_setups = len(setup_results)
            if total_setups > 0:
                bullish_score = bullish_score / total_setups
                bearish_score = bearish_score / total_setups

            agreeing_setups = max(bullish_count, bearish_count)

            return {
                'bullish_score': bullish_score,
                'bearish_score': bearish_score,
                'bullish_setups': bullish_setups,
                'bearish_setups': bearish_setups,
                'agreeing_setups': agreeing_setups,
            }

        except Exception as e:
            logger.error(f"Error calculating confluence: {e}")
            return {
                'bullish_score': 0.0,
                'bearish_score': 0.0,
                'bullish_setups': [],
                'bearish_setups': [],
                'agreeing_setups': 0,
            }

    def _extract_signal_details(self, setup_results: Dict, direction: str) -> Dict[str, Any]:
        """Extract details of setups supporting the signal"""
        details = {}
        for setup_name, result in setup_results.items():
            if result.get('signal') == direction:
                details[setup_name] = {
                    'score': result.get('score', 0.0),
                    'detected': result.get('detected', False),
                }
        return details
