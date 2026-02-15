"""
Market Scanner Module

Multi-symbol opportunity scanner:
- Multiple scan criteria (breakout, momentum, volume, pattern)
- Real-time opportunity detection
- Ranked results by signal strength
- Customizable filters
- Alert integration

Inspired by: TradeStation RadarScreen, TradingView Screener, TC2000
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)


class ScanCriteriaType(Enum):
    """Types of scan criteria."""
    # Price-based
    BREAKOUT = "breakout"
    PRICE_ABOVE_MA = "price_above_ma"
    PRICE_BELOW_MA = "price_below_ma"
    NEW_HIGH = "new_high"
    NEW_LOW = "new_low"
    GAP_UP = "gap_up"
    GAP_DOWN = "gap_down"

    # Momentum
    MOMENTUM = "momentum"
    RSI_OVERBOUGHT = "rsi_overbought"
    RSI_OVERSOLD = "rsi_oversold"
    MACD_BULLISH_CROSS = "macd_bullish_cross"
    MACD_BEARISH_CROSS = "macd_bearish_cross"
    STOCHASTIC_OVERSOLD = "stochastic_oversold"
    STOCHASTIC_OVERBOUGHT = "stochastic_overbought"

    # Volume
    VOLUME_SPIKE = "volume_spike"
    UNUSUAL_VOLUME = "unusual_volume"
    VOLUME_BREAKOUT = "volume_breakout"

    # Trend
    UPTREND = "uptrend"
    DOWNTREND = "downtrend"
    TREND_REVERSAL = "trend_reversal"
    MA_CROSSOVER = "ma_crossover"

    # Volatility
    VOLATILITY_EXPANSION = "volatility_expansion"
    VOLATILITY_CONTRACTION = "volatility_contraction"
    BOLLINGER_SQUEEZE = "bollinger_squeeze"

    # Pattern
    SUPPORT_BOUNCE = "support_bounce"
    RESISTANCE_REJECTION = "resistance_rejection"
    CONSOLIDATION_BREAK = "consolidation_break"

    # Custom
    CUSTOM = "custom"


class SignalDirection(Enum):
    """Direction of opportunity signal."""
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


@dataclass
class ScanCriteria:
    """Single scan criterion configuration."""
    type: ScanCriteriaType
    parameters: Dict[str, Any] = field(default_factory=dict)
    weight: float = 1.0  # Importance weight
    required: bool = False  # Must be met?

    def to_dict(self) -> Dict:
        return {
            'type': self.type.value,
            'parameters': self.parameters,
            'weight': self.weight,
            'required': self.required
        }


@dataclass
class ScanResult:
    """Result for a single symbol from a scan."""
    symbol: str
    criteria_met: List[str]
    total_criteria: int
    match_score: float  # 0-1 weighted score
    direction: SignalDirection
    signal_strength: float  # 0-100
    details: Dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict:
        return {
            'symbol': self.symbol,
            'criteria_met': self.criteria_met,
            'total_criteria': self.total_criteria,
            'match_score': self.match_score,
            'direction': self.direction.value,
            'signal_strength': self.signal_strength,
            'details': self.details,
            'timestamp': self.timestamp.isoformat()
        }


@dataclass
class MarketOpportunity:
    """Trading opportunity identified by scanner."""
    symbol: str
    opportunity_type: str
    direction: SignalDirection
    strength: float  # 0-100
    entry_price: Optional[float]
    stop_loss: Optional[float]
    take_profit: Optional[float]
    risk_reward: Optional[float]
    triggers: List[str]
    analysis: Dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None

    @property
    def is_valid(self) -> bool:
        if not self.expires_at:
            return True
        return datetime.utcnow() < self.expires_at

    def to_dict(self) -> Dict:
        return {
            'symbol': self.symbol,
            'opportunity_type': self.opportunity_type,
            'direction': self.direction.value,
            'strength': self.strength,
            'entry_price': self.entry_price,
            'stop_loss': self.stop_loss,
            'take_profit': self.take_profit,
            'risk_reward': self.risk_reward,
            'triggers': self.triggers,
            'analysis': self.analysis,
            'timestamp': self.timestamp.isoformat(),
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'is_valid': self.is_valid
        }


class MarketScanner:
    """
    Multi-symbol market scanner for opportunity detection.

    Features:
    - Scan multiple symbols simultaneously
    - Multiple scan criteria
    - Weighted scoring
    - Real-time opportunity alerts
    - Historical scan results
    - Custom criteria support

    Usage:
        scanner = MarketScanner()

        # Add symbols to scan
        scanner.add_symbols(['XAUUSD', 'EURUSD', 'GBPUSD'])

        # Configure scan
        scanner.add_criteria(ScanCriteriaType.BREAKOUT, {'period': 20})
        scanner.add_criteria(ScanCriteriaType.RSI_OVERSOLD, {'threshold': 30})

        # Run scan
        results = scanner.scan(market_data)

        # Get top opportunities
        opportunities = scanner.get_top_opportunities(limit=5)
    """

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize market scanner.

        Args:
            config: Configuration options
        """
        self.config = config or {}

        # Symbols to scan
        self._symbols: List[str] = []

        # Scan criteria
        self._criteria: List[ScanCriteria] = []

        # Results storage
        self._last_results: Dict[str, ScanResult] = {}
        self._opportunities: List[MarketOpportunity] = []
        self._max_opportunities = self.config.get('max_opportunities', 100)

        # Data providers
        self._data_providers: Dict[str, Callable] = {}

        # Callbacks
        self._on_opportunity_callbacks: List[Callable] = []

        # Thread safety
        self._lock = threading.RLock()

        # Configuration
        self._min_strength = self.config.get('min_strength', 50.0)
        self._parallel_scan = self.config.get('parallel_scan', True)
        self._max_workers = self.config.get('max_workers', 10)

        # Statistics
        self._stats = {
            'scans_performed': 0,
            'opportunities_found': 0,
            'last_scan_time': None
        }

        logger.info("Market Scanner initialized")

    # ================================================================
    # SYMBOL MANAGEMENT
    # ================================================================

    def add_symbols(self, symbols: List[str]):
        """Add symbols to scan."""
        with self._lock:
            for symbol in symbols:
                if symbol not in self._symbols:
                    self._symbols.append(symbol)
        logger.info(f"Added {len(symbols)} symbols to scanner")

    def remove_symbol(self, symbol: str):
        """Remove a symbol from scanning."""
        with self._lock:
            if symbol in self._symbols:
                self._symbols.remove(symbol)

    def set_symbols(self, symbols: List[str]):
        """Set the complete list of symbols to scan."""
        with self._lock:
            self._symbols = list(symbols)

    def get_symbols(self) -> List[str]:
        """Get list of symbols being scanned."""
        return self._symbols.copy()

    # ================================================================
    # CRITERIA MANAGEMENT
    # ================================================================

    def add_criteria(
        self,
        criteria_type: ScanCriteriaType,
        parameters: Optional[Dict] = None,
        weight: float = 1.0,
        required: bool = False
    ):
        """
        Add a scan criterion.

        Args:
            criteria_type: Type of criterion
            parameters: Criterion parameters
            weight: Importance weight (higher = more important)
            required: If True, must be met for result to be valid
        """
        criteria = ScanCriteria(
            type=criteria_type,
            parameters=parameters or {},
            weight=weight,
            required=required
        )
        with self._lock:
            self._criteria.append(criteria)

    def clear_criteria(self):
        """Clear all scan criteria."""
        with self._lock:
            self._criteria.clear()

    def get_criteria(self) -> List[ScanCriteria]:
        """Get current scan criteria."""
        return self._criteria.copy()

    # ================================================================
    # SCANNING
    # ================================================================

    def scan(
        self,
        market_data: Dict[str, Dict[str, Any]],
        criteria: Optional[List[ScanCriteriaType]] = None,
        min_strength: Optional[float] = None
    ) -> List[ScanResult]:
        """
        Run scan across all symbols.

        Args:
            market_data: Dict of symbol -> market data
                Expected format:
                {
                    'XAUUSD': {
                        'price': 1950.50,
                        'open': 1948.00,
                        'high': 1952.00,
                        'low': 1946.00,
                        'close': 1950.50,
                        'volume': 1000000,
                        'ma_20': 1945.00,
                        'ma_50': 1940.00,
                        'rsi': 65.5,
                        'macd': 0.5,
                        'macd_signal': 0.3,
                        'atr': 5.0,
                        'high_20': 1955.00,
                        'low_20': 1930.00,
                        ...
                    }
                }
            criteria: Specific criteria to use (defaults to all configured)
            min_strength: Minimum strength to include in results

        Returns:
            List of ScanResult objects, sorted by strength
        """
        min_strength = min_strength or self._min_strength
        results = []

        # Determine which criteria to use
        active_criteria = self._criteria
        if criteria:
            active_criteria = [
                c for c in self._criteria
                if c.type in criteria
            ]

        if not active_criteria:
            logger.warning("No scan criteria configured")
            return []

        with self._lock:
            if self._parallel_scan:
                results = self._scan_parallel(market_data, active_criteria)
            else:
                results = self._scan_sequential(market_data, active_criteria)

            # Filter by minimum strength
            results = [r for r in results if r.signal_strength >= min_strength]

            # Sort by strength
            results.sort(key=lambda x: -x.signal_strength)

            # Store results
            for result in results:
                self._last_results[result.symbol] = result

            # Update stats
            self._stats['scans_performed'] += 1
            self._stats['last_scan_time'] = datetime.utcnow().isoformat()

        # Generate opportunities from results
        self._generate_opportunities(results)

        return results

    def _scan_sequential(
        self,
        market_data: Dict[str, Dict[str, Any]],
        criteria: List[ScanCriteria]
    ) -> List[ScanResult]:
        """Scan symbols sequentially."""
        results = []

        for symbol in self._symbols:
            if symbol not in market_data:
                continue

            result = self._scan_symbol(symbol, market_data[symbol], criteria)
            if result:
                results.append(result)

        return results

    def _scan_parallel(
        self,
        market_data: Dict[str, Dict[str, Any]],
        criteria: List[ScanCriteria]
    ) -> List[ScanResult]:
        """Scan symbols in parallel."""
        results = []

        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            futures = {
                executor.submit(
                    self._scan_symbol,
                    symbol,
                    market_data.get(symbol, {}),
                    criteria
                ): symbol
                for symbol in self._symbols
                if symbol in market_data
            }

            for future in as_completed(futures):
                try:
                    result = future.result()
                    if result:
                        results.append(result)
                except Exception as e:
                    symbol = futures[future]
                    logger.error(f"Error scanning {symbol}: {e}")

        return results

    def _scan_symbol(
        self,
        symbol: str,
        data: Dict[str, Any],
        criteria: List[ScanCriteria]
    ) -> Optional[ScanResult]:
        """Scan a single symbol against criteria."""
        if not data:
            return None

        criteria_met = []
        total_weight = 0
        met_weight = 0
        bullish_score = 0
        bearish_score = 0
        details = {}

        for criterion in criteria:
            met, detail = self._check_criterion(criterion, data)

            total_weight += criterion.weight

            if met:
                criteria_met.append(criterion.type.value)
                met_weight += criterion.weight

                # Determine direction contribution
                direction = detail.get('direction', 'neutral')
                if direction == 'bullish':
                    bullish_score += criterion.weight
                elif direction == 'bearish':
                    bearish_score += criterion.weight

                details[criterion.type.value] = detail
            elif criterion.required:
                # Required criterion not met, skip this symbol
                return None

        if not criteria_met:
            return None

        # Calculate scores
        match_score = met_weight / total_weight if total_weight > 0 else 0
        signal_strength = match_score * 100

        # Determine overall direction
        if bullish_score > bearish_score:
            direction = SignalDirection.BULLISH
        elif bearish_score > bullish_score:
            direction = SignalDirection.BEARISH
        else:
            direction = SignalDirection.NEUTRAL

        return ScanResult(
            symbol=symbol,
            criteria_met=criteria_met,
            total_criteria=len(criteria),
            match_score=round(match_score, 4),
            direction=direction,
            signal_strength=round(signal_strength, 2),
            details=details
        )

    def _check_criterion(
        self,
        criterion: ScanCriteria,
        data: Dict[str, Any]
    ) -> tuple:
        """
        Check if a criterion is met.

        Returns:
            (met: bool, details: dict)
        """
        ctype = criterion.type
        params = criterion.parameters

        price = data.get('price', data.get('close', 0))
        open_price = data.get('open', price)
        high = data.get('high', price)
        low = data.get('low', price)
        volume = data.get('volume', 0)

        # Moving averages
        ma_20 = data.get('ma_20', data.get('sma_20', price))
        ma_50 = data.get('ma_50', data.get('sma_50', price))
        ma_200 = data.get('ma_200', data.get('sma_200', price))

        # Indicators
        rsi = data.get('rsi', data.get('rsi_14', 50))
        macd = data.get('macd', 0)
        macd_signal = data.get('macd_signal', 0)
        stoch_k = data.get('stoch_k', 50)
        stoch_d = data.get('stoch_d', 50)
        atr = data.get('atr', 0)

        # Historical levels
        high_20 = data.get('high_20', high)
        low_20 = data.get('low_20', low)
        avg_volume = data.get('avg_volume', volume)

        # Check criteria
        if ctype == ScanCriteriaType.BREAKOUT:
            period = params.get('period', 20)
            high_key = f'high_{period}'
            high_period = data.get(high_key, high_20)

            if price > high_period:
                return True, {
                    'direction': 'bullish',
                    'level': high_period,
                    'breakout_pct': round((price - high_period) / high_period * 100, 2)
                }
            return False, {}

        elif ctype == ScanCriteriaType.PRICE_ABOVE_MA:
            ma_period = params.get('period', 20)
            ma_key = f'ma_{ma_period}'
            ma_value = data.get(ma_key, data.get(f'sma_{ma_period}', ma_20))

            if price > ma_value:
                return True, {
                    'direction': 'bullish',
                    'ma': ma_value,
                    'distance_pct': round((price - ma_value) / ma_value * 100, 2)
                }
            return False, {}

        elif ctype == ScanCriteriaType.PRICE_BELOW_MA:
            ma_period = params.get('period', 20)
            ma_key = f'ma_{ma_period}'
            ma_value = data.get(ma_key, data.get(f'sma_{ma_period}', ma_20))

            if price < ma_value:
                return True, {
                    'direction': 'bearish',
                    'ma': ma_value,
                    'distance_pct': round((ma_value - price) / ma_value * 100, 2)
                }
            return False, {}

        elif ctype == ScanCriteriaType.RSI_OVERBOUGHT:
            threshold = params.get('threshold', 70)
            if rsi > threshold:
                return True, {
                    'direction': 'bearish',
                    'rsi': rsi,
                    'threshold': threshold
                }
            return False, {}

        elif ctype == ScanCriteriaType.RSI_OVERSOLD:
            threshold = params.get('threshold', 30)
            if rsi < threshold:
                return True, {
                    'direction': 'bullish',
                    'rsi': rsi,
                    'threshold': threshold
                }
            return False, {}

        elif ctype == ScanCriteriaType.MOMENTUM:
            # Price change and RSI combination
            change_pct = params.get('min_change_pct', 1.0)
            price_change = ((price - open_price) / open_price) * 100 if open_price > 0 else 0

            if abs(price_change) >= change_pct:
                direction = 'bullish' if price_change > 0 else 'bearish'
                return True, {
                    'direction': direction,
                    'change_pct': round(price_change, 2),
                    'rsi': rsi
                }
            return False, {}

        elif ctype == ScanCriteriaType.VOLUME_SPIKE:
            multiplier = params.get('multiplier', 2.0)
            if avg_volume > 0 and volume > avg_volume * multiplier:
                return True, {
                    'direction': 'neutral',
                    'volume': volume,
                    'avg_volume': avg_volume,
                    'multiplier': round(volume / avg_volume, 2)
                }
            return False, {}

        elif ctype == ScanCriteriaType.MACD_BULLISH_CROSS:
            prev_macd = data.get('prev_macd', macd)
            prev_signal = data.get('prev_macd_signal', macd_signal)

            if prev_macd <= prev_signal and macd > macd_signal:
                return True, {
                    'direction': 'bullish',
                    'macd': macd,
                    'signal': macd_signal
                }
            return False, {}

        elif ctype == ScanCriteriaType.MACD_BEARISH_CROSS:
            prev_macd = data.get('prev_macd', macd)
            prev_signal = data.get('prev_macd_signal', macd_signal)

            if prev_macd >= prev_signal and macd < macd_signal:
                return True, {
                    'direction': 'bearish',
                    'macd': macd,
                    'signal': macd_signal
                }
            return False, {}

        elif ctype == ScanCriteriaType.UPTREND:
            # Price above MA20 > MA50 > MA200
            if price > ma_20 > ma_50:
                return True, {
                    'direction': 'bullish',
                    'ma_20': ma_20,
                    'ma_50': ma_50
                }
            return False, {}

        elif ctype == ScanCriteriaType.DOWNTREND:
            if price < ma_20 < ma_50:
                return True, {
                    'direction': 'bearish',
                    'ma_20': ma_20,
                    'ma_50': ma_50
                }
            return False, {}

        elif ctype == ScanCriteriaType.MA_CROSSOVER:
            fast = params.get('fast_period', 20)
            slow = params.get('slow_period', 50)
            fast_ma = data.get(f'ma_{fast}', ma_20)
            slow_ma = data.get(f'ma_{slow}', ma_50)
            prev_fast_ma = data.get(f'prev_ma_{fast}', fast_ma)
            prev_slow_ma = data.get(f'prev_ma_{slow}', slow_ma)

            if prev_fast_ma <= prev_slow_ma and fast_ma > slow_ma:
                return True, {
                    'direction': 'bullish',
                    'fast_ma': fast_ma,
                    'slow_ma': slow_ma,
                    'cross_type': 'golden_cross'
                }
            elif prev_fast_ma >= prev_slow_ma and fast_ma < slow_ma:
                return True, {
                    'direction': 'bearish',
                    'fast_ma': fast_ma,
                    'slow_ma': slow_ma,
                    'cross_type': 'death_cross'
                }
            return False, {}

        elif ctype == ScanCriteriaType.VOLATILITY_EXPANSION:
            atr_multiplier = params.get('multiplier', 1.5)
            avg_atr = data.get('avg_atr', atr)

            if avg_atr > 0 and atr > avg_atr * atr_multiplier:
                return True, {
                    'direction': 'neutral',
                    'atr': atr,
                    'avg_atr': avg_atr,
                    'expansion': round(atr / avg_atr, 2)
                }
            return False, {}

        elif ctype == ScanCriteriaType.NEW_HIGH:
            period = params.get('period', 20)
            high_key = f'high_{period}'
            period_high = data.get(high_key, high_20)

            if high >= period_high:
                return True, {
                    'direction': 'bullish',
                    'high': high,
                    'period_high': period_high
                }
            return False, {}

        elif ctype == ScanCriteriaType.NEW_LOW:
            period = params.get('period', 20)
            low_key = f'low_{period}'
            period_low = data.get(low_key, low_20)

            if low <= period_low:
                return True, {
                    'direction': 'bearish',
                    'low': low,
                    'period_low': period_low
                }
            return False, {}

        elif ctype == ScanCriteriaType.GAP_UP:
            gap_pct = params.get('min_gap_pct', 1.0)
            prev_close = data.get('prev_close', open_price)

            if prev_close > 0:
                gap = ((open_price - prev_close) / prev_close) * 100
                if gap >= gap_pct:
                    return True, {
                        'direction': 'bullish',
                        'gap_pct': round(gap, 2)
                    }
            return False, {}

        elif ctype == ScanCriteriaType.GAP_DOWN:
            gap_pct = params.get('min_gap_pct', 1.0)
            prev_close = data.get('prev_close', open_price)

            if prev_close > 0:
                gap = ((prev_close - open_price) / prev_close) * 100
                if gap >= gap_pct:
                    return True, {
                        'direction': 'bearish',
                        'gap_pct': round(gap, 2)
                    }
            return False, {}

        # Default: not met
        return False, {}

    # ================================================================
    # OPPORTUNITIES
    # ================================================================

    def _generate_opportunities(self, results: List[ScanResult]):
        """Generate trading opportunities from scan results."""
        for result in results:
            if result.signal_strength >= 70:  # Strong signals only
                opportunity = self._create_opportunity(result)
                if opportunity:
                    self._add_opportunity(opportunity)

    def _create_opportunity(self, result: ScanResult) -> Optional[MarketOpportunity]:
        """Create an opportunity from a scan result."""
        # Get price from details
        price = None
        for detail in result.details.values():
            if 'price' in detail:
                price = detail['price']
                break

        if not price:
            return None

        # Calculate basic levels
        atr = result.details.get('atr', 0)
        if not atr:
            atr = price * 0.01  # Default 1% ATR

        if result.direction == SignalDirection.BULLISH:
            stop_loss = price - (atr * 1.5)
            take_profit = price + (atr * 3)
        elif result.direction == SignalDirection.BEARISH:
            stop_loss = price + (atr * 1.5)
            take_profit = price - (atr * 3)
        else:
            stop_loss = None
            take_profit = None

        risk_reward = None
        if stop_loss and take_profit:
            risk = abs(price - stop_loss)
            reward = abs(take_profit - price)
            risk_reward = round(reward / risk, 2) if risk > 0 else None

        return MarketOpportunity(
            symbol=result.symbol,
            opportunity_type='/'.join(result.criteria_met[:2]),
            direction=result.direction,
            strength=result.signal_strength,
            entry_price=price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            risk_reward=risk_reward,
            triggers=result.criteria_met,
            analysis=result.details,
            expires_at=datetime.utcnow() + timedelta(hours=4)
        )

    def _add_opportunity(self, opportunity: MarketOpportunity):
        """Add an opportunity to storage."""
        with self._lock:
            self._opportunities.append(opportunity)

            # Trim if needed
            if len(self._opportunities) > self._max_opportunities:
                self._opportunities.pop(0)

            self._stats['opportunities_found'] += 1

            # Notify callbacks
            for callback in self._on_opportunity_callbacks:
                try:
                    callback(opportunity)
                except Exception as e:
                    logger.error(f"Opportunity callback error: {e}")

    def get_opportunities(
        self,
        symbol: Optional[str] = None,
        direction: Optional[SignalDirection] = None,
        min_strength: float = 0
    ) -> List[MarketOpportunity]:
        """Get stored opportunities with optional filters."""
        with self._lock:
            opportunities = [o for o in self._opportunities if o.is_valid]

            if symbol:
                opportunities = [o for o in opportunities if o.symbol == symbol]
            if direction:
                opportunities = [o for o in opportunities if o.direction == direction]
            if min_strength > 0:
                opportunities = [o for o in opportunities if o.strength >= min_strength]

            return sorted(opportunities, key=lambda x: -x.strength)

    def get_top_opportunities(self, limit: int = 10) -> List[MarketOpportunity]:
        """Get top opportunities by strength."""
        return self.get_opportunities()[:limit]

    def on_opportunity(self, callback: Callable):
        """Register callback for new opportunities."""
        self._on_opportunity_callbacks.append(callback)

    # ================================================================
    # RESULTS ACCESS
    # ================================================================

    def get_last_result(self, symbol: str) -> Optional[ScanResult]:
        """Get last scan result for a symbol."""
        return self._last_results.get(symbol)

    def get_all_results(self) -> Dict[str, ScanResult]:
        """Get all last scan results."""
        return self._last_results.copy()

    def get_stats(self) -> Dict:
        """Get scanner statistics."""
        return {
            **self._stats,
            'symbols_count': len(self._symbols),
            'criteria_count': len(self._criteria),
            'active_opportunities': len([o for o in self._opportunities if o.is_valid])
        }


# ================================================================
# FASTAPI INTEGRATION
# ================================================================

def create_scanner_router(scanner: MarketScanner):
    """
    Create FastAPI router with scanner endpoints.

    Args:
        scanner: MarketScanner instance

    Returns:
        FastAPI APIRouter
    """
    from fastapi import APIRouter, HTTPException
    from pydantic import BaseModel
    from typing import Optional, List

    router = APIRouter(prefix="/api/scanner", tags=["Market Scanner"])

    class ScanRequest(BaseModel):
        market_data: Dict[str, Dict[str, Any]]
        criteria: Optional[List[str]] = None
        min_strength: Optional[float] = None

    class AddCriteriaRequest(BaseModel):
        criteria_type: str
        parameters: Dict[str, Any] = {}
        weight: float = 1.0
        required: bool = False

    @router.post("/scan")
    async def run_scan(request: ScanRequest):
        """Run a market scan."""
        criteria = None
        if request.criteria:
            try:
                criteria = [ScanCriteriaType(c) for c in request.criteria]
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))

        results = scanner.scan(
            request.market_data,
            criteria=criteria,
            min_strength=request.min_strength
        )
        return [r.to_dict() for r in results]

    @router.get("/opportunities")
    async def get_opportunities(
        symbol: Optional[str] = None,
        direction: Optional[str] = None,
        min_strength: float = 0,
        limit: int = 20
    ):
        """Get trading opportunities."""
        dir_enum = SignalDirection(direction) if direction else None
        opportunities = scanner.get_opportunities(symbol, dir_enum, min_strength)
        return [o.to_dict() for o in opportunities[:limit]]

    @router.get("/opportunities/top")
    async def get_top_opportunities(limit: int = 10):
        """Get top opportunities."""
        return [o.to_dict() for o in scanner.get_top_opportunities(limit)]

    @router.get("/symbols")
    async def get_symbols():
        """Get scanned symbols."""
        return {"symbols": scanner.get_symbols()}

    @router.post("/symbols")
    async def add_symbols(symbols: List[str]):
        """Add symbols to scan."""
        scanner.add_symbols(symbols)
        return {"status": "added", "symbols": symbols}

    @router.get("/criteria")
    async def get_criteria():
        """Get scan criteria."""
        return [c.to_dict() for c in scanner.get_criteria()]

    @router.post("/criteria")
    async def add_criteria(request: AddCriteriaRequest):
        """Add scan criterion."""
        try:
            criteria_type = ScanCriteriaType(request.criteria_type)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid criteria type: {request.criteria_type}")

        scanner.add_criteria(
            criteria_type,
            request.parameters,
            request.weight,
            request.required
        )
        return {"status": "added"}

    @router.delete("/criteria")
    async def clear_criteria():
        """Clear all scan criteria."""
        scanner.clear_criteria()
        return {"status": "cleared"}

    @router.get("/results")
    async def get_results():
        """Get last scan results."""
        return {
            symbol: result.to_dict()
            for symbol, result in scanner.get_all_results().items()
        }

    @router.get("/results/{symbol}")
    async def get_symbol_result(symbol: str):
        """Get last result for a symbol."""
        result = scanner.get_last_result(symbol)
        if not result:
            raise HTTPException(status_code=404, detail=f"No result for {symbol}")
        return result.to_dict()

    @router.get("/stats")
    async def get_stats():
        """Get scanner statistics."""
        return scanner.get_stats()

    return router


# Global instance for easy access
_market_scanner: Optional[MarketScanner] = None


def get_market_scanner() -> MarketScanner:
    """Get the global market scanner instance."""
    global _market_scanner
    if _market_scanner is None:
        _market_scanner = MarketScanner()
    return _market_scanner
