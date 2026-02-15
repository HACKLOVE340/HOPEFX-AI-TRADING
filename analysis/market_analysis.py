"""
Market Regime Detection & Multi-Timeframe Analysis

Advanced market analysis tools:
- Market regime identification (trending/ranging/volatile)
- Multi-timeframe confluence analysis
- Volume profile analysis
- Session-based analysis (Asian, London, NY)
- Institutional flow detection
"""

from typing import Dict, List, Optional, Any, Tuple
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class MarketRegime(Enum):
    """Market regime types."""
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGING = "ranging"
    VOLATILE = "volatile"
    BREAKOUT = "breakout"
    CONSOLIDATION = "consolidation"
    CHOPPY = "choppy"


class TradingSession(Enum):
    """Major trading sessions."""
    ASIAN = "asian"
    LONDON = "london"
    NEW_YORK = "new_york"
    OVERLAP_LONDON_NY = "overlap_london_ny"
    PACIFIC = "pacific"


@dataclass
class RegimeAnalysis:
    """Market regime analysis result."""
    current_regime: MarketRegime
    regime_strength: float  # 0-1
    trend_direction: str  # 'up', 'down', 'neutral'
    volatility_percentile: float
    volume_state: str  # 'high', 'normal', 'low'
    regime_duration: int  # Bars in current regime
    transition_probability: Dict[str, float]
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict:
        return {
            'current_regime': self.current_regime.value,
            'regime_strength': self.regime_strength,
            'trend_direction': self.trend_direction,
            'volatility_percentile': self.volatility_percentile,
            'volume_state': self.volume_state,
            'regime_duration': self.regime_duration,
            'transition_probability': self.transition_probability,
            'timestamp': self.timestamp.isoformat()
        }


@dataclass
class TimeframeAnalysis:
    """Single timeframe analysis result."""
    timeframe: str
    trend: str  # 'bullish', 'bearish', 'neutral'
    trend_strength: float
    support_levels: List[float]
    resistance_levels: List[float]
    key_level_proximity: float  # Distance to nearest key level
    momentum: float  # -1 to 1
    volume_trend: str


@dataclass
class ConfluenceAnalysis:
    """Multi-timeframe confluence analysis result."""
    overall_bias: str  # 'bullish', 'bearish', 'neutral'
    confidence: float  # 0-1
    timeframe_alignment: float  # % of timeframes agreeing
    timeframe_analyses: Dict[str, TimeframeAnalysis]
    key_confluence_levels: List[Dict]
    recommended_action: str
    risk_level: str
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class SessionAnalysis:
    """Trading session analysis result."""
    session: TradingSession
    is_active: bool
    time_remaining_minutes: int
    typical_volatility: float
    typical_volume: float
    best_pairs: List[str]
    session_range: Dict[str, float]
    key_times: List[str]


@dataclass
class VolumeProfile:
    """Volume profile analysis result."""
    poc: float  # Point of Control (highest volume price)
    value_area_high: float
    value_area_low: float
    hvm_levels: List[float]  # High Volume Nodes
    lvm_levels: List[float]  # Low Volume Nodes
    volume_distribution: Dict[float, float]


class MarketRegimeDetector:
    """
    Detects current market regime using multiple indicators.

    Regimes:
    - Trending Up/Down: Clear directional movement
    - Ranging: Price oscillating between levels
    - Volatile: High volatility with no clear direction
    - Breakout: Price breaking key levels with momentum
    - Consolidation: Tight range, decreasing volatility
    - Choppy: Erratic price action
    """

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize regime detector.

        Args:
            config: Configuration dict
        """
        self.config = config or {}
        self.lookback_period = self.config.get('lookback_period', 100)
        self.atr_period = self.config.get('atr_period', 14)
        self.trend_period = self.config.get('trend_period', 20)

        # Regime history for transition analysis
        self.regime_history = []

        logger.info("Market Regime Detector initialized")

    def detect_regime(self, prices: pd.DataFrame) -> RegimeAnalysis:
        """
        Detect current market regime.

        Args:
            prices: DataFrame with OHLCV data

        Returns:
            RegimeAnalysis object
        """
        if len(prices) < self.lookback_period:
            return self._default_analysis()

        try:
            # Calculate indicators
            atr = self._calculate_atr(prices)
            adx = self._calculate_adx(prices)
            volatility_pct = self._calculate_volatility_percentile(prices, atr)
            trend = self._calculate_trend(prices)
            volume_state = self._analyze_volume(prices)

            # Determine regime
            regime, strength = self._classify_regime(
                adx, volatility_pct, trend, prices
            )

            # Calculate regime duration
            duration = self._calculate_regime_duration(regime)

            # Calculate transition probabilities
            transition_prob = self._calculate_transition_probability(regime)

            analysis = RegimeAnalysis(
                current_regime=regime,
                regime_strength=strength,
                trend_direction=trend['direction'],
                volatility_percentile=volatility_pct,
                volume_state=volume_state,
                regime_duration=duration,
                transition_probability=transition_prob
            )

            # Update history
            self.regime_history.append({
                'regime': regime,
                'timestamp': datetime.utcnow()
            })
            self.regime_history = self.regime_history[-1000:]  # Keep last 1000

            return analysis

        except Exception as e:
            logger.error(f"Error detecting regime: {e}")
            return self._default_analysis()

    def _calculate_atr(self, prices: pd.DataFrame) -> pd.Series:
        """Calculate Average True Range."""
        high = prices['high']
        low = prices['low']
        close = prices['close']

        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))

        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = true_range.rolling(window=self.atr_period).mean()

        return atr

    def _calculate_adx(self, prices: pd.DataFrame, period: int = 14) -> float:
        """Calculate Average Directional Index."""
        high = prices['high']
        low = prices['low']
        close = prices['close']

        # Calculate +DM and -DM
        plus_dm = high.diff()
        minus_dm = low.diff().abs()

        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm < 0] = 0

        # Where +DM > -DM, set -DM to 0 and vice versa
        plus_dm[plus_dm < minus_dm] = 0
        minus_dm[minus_dm < plus_dm] = 0

        # Calculate TR
        tr = self._calculate_atr(prices) * period  # Approximation

        # Calculate DI
        plus_di = 100 * (plus_dm.rolling(period).sum() / tr)
        minus_di = 100 * (minus_dm.rolling(period).sum() / tr)

        # Calculate DX and ADX
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di + 1e-8)
        adx = dx.rolling(period).mean()

        return float(adx.iloc[-1]) if not np.isnan(adx.iloc[-1]) else 20.0

    def _calculate_volatility_percentile(
        self,
        prices: pd.DataFrame,
        atr: pd.Series
    ) -> float:
        """Calculate current volatility percentile vs history."""
        current_atr = atr.iloc[-1]
        historical_atr = atr.dropna()

        if len(historical_atr) == 0:
            return 50.0

        percentile = (historical_atr < current_atr).sum() / len(historical_atr) * 100
        return float(percentile)

    def _calculate_trend(self, prices: pd.DataFrame) -> Dict[str, Any]:
        """Calculate trend direction and strength."""
        close = prices['close']

        # Multiple MA periods
        sma_short = close.rolling(10).mean()
        sma_medium = close.rolling(20).mean()
        sma_long = close.rolling(50).mean()

        current_price = close.iloc[-1]
        sma_s = sma_short.iloc[-1]
        sma_m = sma_medium.iloc[-1]
        sma_l = sma_long.iloc[-1]

        # Determine direction
        bullish_count = sum([
            current_price > sma_s,
            current_price > sma_m,
            current_price > sma_l,
            sma_s > sma_m,
            sma_m > sma_l
        ])

        if bullish_count >= 4:
            direction = 'up'
            strength = bullish_count / 5
        elif bullish_count <= 1:
            direction = 'down'
            strength = (5 - bullish_count) / 5
        else:
            direction = 'neutral'
            strength = 0.5

        return {
            'direction': direction,
            'strength': strength,
            'ma_alignment': bullish_count / 5
        }

    def _analyze_volume(self, prices: pd.DataFrame) -> str:
        """Analyze volume state."""
        if 'volume' not in prices.columns:
            return 'unknown'

        volume = prices['volume']
        avg_volume = volume.rolling(20).mean()
        current_volume = volume.iloc[-1]
        avg_vol = avg_volume.iloc[-1]

        if current_volume > avg_vol * 1.5:
            return 'high'
        elif current_volume < avg_vol * 0.5:
            return 'low'
        else:
            return 'normal'

    def _classify_regime(
        self,
        adx: float,
        volatility_pct: float,
        trend: Dict,
        prices: pd.DataFrame
    ) -> Tuple[MarketRegime, float]:
        """Classify market regime based on indicators."""

        close = prices['close']
        returns = close.pct_change().dropna()

        # Calculate range metrics
        recent_high = prices['high'].tail(20).max()
        recent_low = prices['low'].tail(20).min()
        range_pct = (recent_high - recent_low) / recent_low

        # Classify based on ADX and volatility
        if adx > 25 and trend['direction'] == 'up':
            return MarketRegime.TRENDING_UP, min(adx / 50, 1.0)

        elif adx > 25 and trend['direction'] == 'down':
            return MarketRegime.TRENDING_DOWN, min(adx / 50, 1.0)

        elif volatility_pct > 80:
            return MarketRegime.VOLATILE, volatility_pct / 100

        elif adx < 20 and range_pct < 0.02:
            return MarketRegime.CONSOLIDATION, (20 - adx) / 20

        elif adx < 20 and range_pct > 0.03:
            return MarketRegime.RANGING, 0.6

        elif volatility_pct > 60 and adx < 25:
            return MarketRegime.CHOPPY, 0.5

        else:
            # Check for breakout
            current_price = close.iloc[-1]
            if current_price > recent_high * 0.99 or current_price < recent_low * 1.01:
                return MarketRegime.BREAKOUT, 0.7

            return MarketRegime.RANGING, 0.5

    def _calculate_regime_duration(self, current_regime: MarketRegime) -> int:
        """Calculate how long current regime has lasted."""
        if not self.regime_history:
            return 1

        duration = 0
        for entry in reversed(self.regime_history):
            if entry['regime'] == current_regime:
                duration += 1
            else:
                break

        return duration + 1

    def _calculate_transition_probability(self, current_regime: MarketRegime) -> Dict[str, float]:
        """Calculate regime transition probabilities based on history."""
        if len(self.regime_history) < 10:
            # Default probabilities
            return {r.value: 0.14 for r in MarketRegime}

        # Count transitions from current regime
        transitions = {}
        for i in range(len(self.regime_history) - 1):
            if self.regime_history[i]['regime'] == current_regime:
                next_regime = self.regime_history[i + 1]['regime'].value
                transitions[next_regime] = transitions.get(next_regime, 0) + 1

        # Normalize
        total = sum(transitions.values())
        if total == 0:
            return {r.value: 0.14 for r in MarketRegime}

        return {k: v / total for k, v in transitions.items()}

    def _default_analysis(self) -> RegimeAnalysis:
        """Return default analysis when insufficient data."""
        return RegimeAnalysis(
            current_regime=MarketRegime.RANGING,
            regime_strength=0.5,
            trend_direction='neutral',
            volatility_percentile=50.0,
            volume_state='unknown',
            regime_duration=0,
            transition_probability={}
        )


class MultiTimeframeAnalyzer:
    """
    Analyzes multiple timeframes for confluence.

    Features:
    - Trend alignment across timeframes
    - Support/resistance confluence
    - Momentum confluence
    - Entry timing based on MTF analysis
    """

    def __init__(self, timeframes: List[str] = None, config: Optional[Dict] = None):
        """
        Initialize MTF analyzer.

        Args:
            timeframes: List of timeframes to analyze
            config: Configuration dict
        """
        self.timeframes = timeframes or ['M5', 'M15', 'H1', 'H4', 'D1']
        self.config = config or {}

        # Timeframe weights (higher = more important)
        self.tf_weights = {
            'M1': 0.05,
            'M5': 0.10,
            'M15': 0.15,
            'M30': 0.15,
            'H1': 0.20,
            'H4': 0.20,
            'D1': 0.25,
            'W1': 0.30,
            'MN1': 0.35,
        }

        logger.info(f"MTF Analyzer initialized with timeframes: {self.timeframes}")

    def analyze_confluence(
        self,
        data_by_timeframe: Dict[str, pd.DataFrame]
    ) -> ConfluenceAnalysis:
        """
        Analyze confluence across multiple timeframes.

        Args:
            data_by_timeframe: Dict of DataFrames keyed by timeframe

        Returns:
            ConfluenceAnalysis object
        """
        try:
            tf_analyses = {}
            trends = []
            weighted_trends = []

            for tf, data in data_by_timeframe.items():
                if len(data) < 50:
                    continue

                analysis = self._analyze_single_timeframe(tf, data)
                tf_analyses[tf] = analysis

                # Track trend direction
                if analysis.trend == 'bullish':
                    trends.append(1)
                    weighted_trends.append(self.tf_weights.get(tf, 0.1))
                elif analysis.trend == 'bearish':
                    trends.append(-1)
                    weighted_trends.append(-self.tf_weights.get(tf, 0.1))
                else:
                    trends.append(0)
                    weighted_trends.append(0)

            # Calculate overall bias
            if not trends:
                return self._default_confluence()

            weighted_sum = sum(weighted_trends)
            alignment = sum(1 for t in trends if t == np.sign(weighted_sum)) / len(trends)

            if weighted_sum > 0.1:
                overall_bias = 'bullish'
            elif weighted_sum < -0.1:
                overall_bias = 'bearish'
            else:
                overall_bias = 'neutral'

            # Calculate confidence
            confidence = abs(weighted_sum) * alignment

            # Find confluence levels
            confluence_levels = self._find_confluence_levels(tf_analyses)

            # Generate recommendation
            recommendation, risk_level = self._generate_recommendation(
                overall_bias, confidence, alignment, tf_analyses
            )

            return ConfluenceAnalysis(
                overall_bias=overall_bias,
                confidence=min(confidence, 1.0),
                timeframe_alignment=alignment,
                timeframe_analyses=tf_analyses,
                key_confluence_levels=confluence_levels,
                recommended_action=recommendation,
                risk_level=risk_level
            )

        except Exception as e:
            logger.error(f"Error in confluence analysis: {e}")
            return self._default_confluence()

    def _analyze_single_timeframe(self, tf: str, data: pd.DataFrame) -> TimeframeAnalysis:
        """Analyze a single timeframe."""
        close = data['close']
        high = data['high']
        low = data['low']

        # Calculate trend
        sma_fast = close.rolling(10).mean()
        sma_slow = close.rolling(20).mean()
        sma_50 = close.rolling(50).mean()

        current_price = close.iloc[-1]

        if current_price > sma_fast.iloc[-1] > sma_slow.iloc[-1] > sma_50.iloc[-1]:
            trend = 'bullish'
            trend_strength = 0.9
        elif current_price < sma_fast.iloc[-1] < sma_slow.iloc[-1] < sma_50.iloc[-1]:
            trend = 'bearish'
            trend_strength = 0.9
        elif current_price > sma_slow.iloc[-1]:
            trend = 'bullish'
            trend_strength = 0.5
        elif current_price < sma_slow.iloc[-1]:
            trend = 'bearish'
            trend_strength = 0.5
        else:
            trend = 'neutral'
            trend_strength = 0.3

        # Find support/resistance
        support_levels = self._find_support_levels(data)
        resistance_levels = self._find_resistance_levels(data)

        # Calculate proximity to key levels
        all_levels = support_levels + resistance_levels
        if all_levels:
            distances = [abs(current_price - level) / current_price for level in all_levels]
            key_level_proximity = min(distances)
        else:
            key_level_proximity = 1.0

        # Calculate momentum
        momentum = (current_price - close.iloc[-20]) / close.iloc[-20]

        # Volume trend
        if 'volume' in data.columns:
            vol_sma = data['volume'].rolling(20).mean()
            if data['volume'].iloc[-1] > vol_sma.iloc[-1]:
                volume_trend = 'increasing'
            else:
                volume_trend = 'decreasing'
        else:
            volume_trend = 'unknown'

        return TimeframeAnalysis(
            timeframe=tf,
            trend=trend,
            trend_strength=trend_strength,
            support_levels=support_levels,
            resistance_levels=resistance_levels,
            key_level_proximity=key_level_proximity,
            momentum=momentum,
            volume_trend=volume_trend
        )

    def _find_support_levels(self, data: pd.DataFrame, num_levels: int = 3) -> List[float]:
        """Find support levels using swing lows."""
        lows = data['low'].values
        levels = []

        for i in range(2, len(lows) - 2):
            if lows[i] < lows[i-1] and lows[i] < lows[i-2] and \
               lows[i] < lows[i+1] and lows[i] < lows[i+2]:
                levels.append(float(lows[i]))

        # Return most recent levels
        return levels[-num_levels:] if levels else []

    def _find_resistance_levels(self, data: pd.DataFrame, num_levels: int = 3) -> List[float]:
        """Find resistance levels using swing highs."""
        highs = data['high'].values
        levels = []

        for i in range(2, len(highs) - 2):
            if highs[i] > highs[i-1] and highs[i] > highs[i-2] and \
               highs[i] > highs[i+1] and highs[i] > highs[i+2]:
                levels.append(float(highs[i]))

        return levels[-num_levels:] if levels else []

    def _find_confluence_levels(
        self,
        tf_analyses: Dict[str, TimeframeAnalysis]
    ) -> List[Dict]:
        """Find levels that appear on multiple timeframes."""
        all_supports = []
        all_resistances = []

        for tf, analysis in tf_analyses.items():
            for level in analysis.support_levels:
                all_supports.append({'level': level, 'timeframe': tf})
            for level in analysis.resistance_levels:
                all_resistances.append({'level': level, 'timeframe': tf})

        # Cluster nearby levels
        confluence_levels = []

        # Process supports
        for sup in all_supports:
            matching = [s for s in all_supports
                       if abs(s['level'] - sup['level']) / sup['level'] < 0.005]
            if len(matching) >= 2:
                avg_level = np.mean([s['level'] for s in matching])
                tfs = list(set(s['timeframe'] for s in matching))
                if not any(abs(cl['level'] - avg_level) < avg_level * 0.003 for cl in confluence_levels):
                    confluence_levels.append({
                        'level': avg_level,
                        'type': 'support',
                        'timeframes': tfs,
                        'strength': len(matching)
                    })

        # Process resistances
        for res in all_resistances:
            matching = [r for r in all_resistances
                       if abs(r['level'] - res['level']) / res['level'] < 0.005]
            if len(matching) >= 2:
                avg_level = np.mean([r['level'] for r in matching])
                tfs = list(set(r['timeframe'] for r in matching))
                if not any(abs(cl['level'] - avg_level) < avg_level * 0.003 for cl in confluence_levels):
                    confluence_levels.append({
                        'level': avg_level,
                        'type': 'resistance',
                        'timeframes': tfs,
                        'strength': len(matching)
                    })

        return sorted(confluence_levels, key=lambda x: -x['strength'])[:10]

    def _generate_recommendation(
        self,
        bias: str,
        confidence: float,
        alignment: float,
        analyses: Dict[str, TimeframeAnalysis]
    ) -> Tuple[str, str]:
        """Generate trading recommendation."""

        if confidence > 0.7 and alignment > 0.7:
            if bias == 'bullish':
                return "Strong BUY setup - High timeframe alignment", "low"
            elif bias == 'bearish':
                return "Strong SELL setup - High timeframe alignment", "low"

        elif confidence > 0.5 and alignment > 0.5:
            if bias == 'bullish':
                return "Moderate BUY setup - Wait for pullback to support", "medium"
            elif bias == 'bearish':
                return "Moderate SELL setup - Wait for pullback to resistance", "medium"

        elif confidence < 0.3 or alignment < 0.4:
            return "No clear setup - Stay out or reduce position size", "high"

        else:
            return "Mixed signals - Trade with caution", "medium"

    def _default_confluence(self) -> ConfluenceAnalysis:
        """Return default confluence analysis."""
        return ConfluenceAnalysis(
            overall_bias='neutral',
            confidence=0.0,
            timeframe_alignment=0.0,
            timeframe_analyses={},
            key_confluence_levels=[],
            recommended_action="Insufficient data",
            risk_level='high'
        )


class SessionAnalyzer:
    """
    Analyzes trading sessions and optimal trading times.

    Sessions:
    - Asian: 00:00-09:00 UTC
    - London: 07:00-16:00 UTC
    - New York: 12:00-21:00 UTC
    - Overlap: London-NY overlap (12:00-16:00 UTC)
    """

    # Session times in UTC
    SESSIONS = {
        TradingSession.ASIAN: (time(0, 0), time(9, 0)),
        TradingSession.LONDON: (time(7, 0), time(16, 0)),
        TradingSession.NEW_YORK: (time(12, 0), time(21, 0)),
        TradingSession.OVERLAP_LONDON_NY: (time(12, 0), time(16, 0)),
        TradingSession.PACIFIC: (time(21, 0), time(0, 0)),  # Wraps around midnight
    }

    # Best pairs per session
    BEST_PAIRS = {
        TradingSession.ASIAN: ['USDJPY', 'AUDUSD', 'NZDUSD', 'AUDJPY'],
        TradingSession.LONDON: ['EURUSD', 'GBPUSD', 'EURGBP', 'XAUUSD'],
        TradingSession.NEW_YORK: ['EURUSD', 'GBPUSD', 'USDCAD', 'XAUUSD'],
        TradingSession.OVERLAP_LONDON_NY: ['EURUSD', 'GBPUSD', 'XAUUSD'],
        TradingSession.PACIFIC: ['AUDUSD', 'NZDUSD'],
    }

    def __init__(self):
        """Initialize session analyzer."""
        logger.info("Session Analyzer initialized")

    def get_current_session(self, utc_time: datetime = None) -> List[TradingSession]:
        """Get currently active trading sessions."""
        if utc_time is None:
            utc_time = datetime.utcnow()

        current_time = utc_time.time()
        active_sessions = []

        for session, (start, end) in self.SESSIONS.items():
            if start <= end:  # Normal case
                if start <= current_time <= end:
                    active_sessions.append(session)
            else:  # Wraps around midnight
                if current_time >= start or current_time <= end:
                    active_sessions.append(session)

        return active_sessions

    def analyze_session(
        self,
        session: TradingSession,
        utc_time: datetime = None
    ) -> SessionAnalysis:
        """Analyze a specific trading session."""
        if utc_time is None:
            utc_time = datetime.utcnow()

        start, end = self.SESSIONS[session]
        current_time = utc_time.time()

        # Check if session is active
        if start <= end:
            is_active = start <= current_time <= end
            if is_active:
                end_dt = datetime.combine(utc_time.date(), end)
                remaining = (end_dt - utc_time).seconds // 60
            else:
                remaining = 0
        else:  # Wraps midnight
            is_active = current_time >= start or current_time <= end
            remaining = 0  # Complex calculation, simplify

        # Typical characteristics
        volatility_map = {
            TradingSession.ASIAN: 0.4,
            TradingSession.LONDON: 0.8,
            TradingSession.NEW_YORK: 0.9,
            TradingSession.OVERLAP_LONDON_NY: 1.0,
            TradingSession.PACIFIC: 0.3,
        }

        volume_map = {
            TradingSession.ASIAN: 0.5,
            TradingSession.LONDON: 0.9,
            TradingSession.NEW_YORK: 0.95,
            TradingSession.OVERLAP_LONDON_NY: 1.0,
            TradingSession.PACIFIC: 0.3,
        }

        key_times_map = {
            TradingSession.ASIAN: ['00:00 UTC - Tokyo Open', '01:00 UTC - Sydney Close'],
            TradingSession.LONDON: ['07:00 UTC - London Open', '08:00 UTC - Frankfurt Open'],
            TradingSession.NEW_YORK: ['12:00 UTC - NY Open', '14:30 UTC - US Economic Data'],
            TradingSession.OVERLAP_LONDON_NY: ['12:00-14:00 UTC - Highest Volume'],
            TradingSession.PACIFIC: ['21:00 UTC - Sydney Open'],
        }

        return SessionAnalysis(
            session=session,
            is_active=is_active,
            time_remaining_minutes=remaining,
            typical_volatility=volatility_map.get(session, 0.5),
            typical_volume=volume_map.get(session, 0.5),
            best_pairs=self.BEST_PAIRS.get(session, []),
            session_range={'start': str(start), 'end': str(end)},
            key_times=key_times_map.get(session, [])
        )

    def get_optimal_trading_times(self, pair: str) -> List[str]:
        """Get optimal trading times for a specific pair."""
        optimal_sessions = []

        for session, pairs in self.BEST_PAIRS.items():
            if pair.upper() in pairs:
                optimal_sessions.append(session.value)

        return optimal_sessions
