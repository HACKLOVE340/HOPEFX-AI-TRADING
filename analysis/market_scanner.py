# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
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
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
from enum import Enum
from typing import Any

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
    parameters: dict[str, Any] = field(default_factory=dict)
    weight: float = 1.0  # Importance weight
    required: bool = False  # Must be met?

    def to_dict(self) -> dict:
        return {
            "type": self.type.value,
            "parameters": self.parameters,
            "weight": self.weight,
            "required": self.required,
        }


@dataclass
class ScanResult:
    """Result for a single symbol from a scan."""

    symbol: str
    criteria_met: list[str]
    total_criteria: int
    match_score: float  # 0-1 weighted score
    direction: SignalDirection
    signal_strength: float  # 0-100
    details: dict[str, Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "criteria_met": self.criteria_met,
            "total_criteria": self.total_criteria,
            "match_score": self.match_score,
            "direction": self.direction.value,
            "signal_strength": self.signal_strength,
            "details": self.details,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class MarketOpportunity:
    """Trading opportunity identified by scanner."""

    symbol: str
    opportunity_type: str
    direction: SignalDirection
    strength: float  # 0-100
    entry_price: float | None
    stop_loss: float | None
    take_profit: float | None
    risk_reward: float | None
    triggers: list[str]
    analysis: dict[str, Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None

    @property
    def is_valid(self) -> bool:
        if not self.expires_at:
            return True
        return datetime.now(UTC) < self.expires_at

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "opportunity_type": self.opportunity_type,
            "direction": self.direction.value,
            "strength": self.strength,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "risk_reward": self.risk_reward,
            "triggers": self.triggers,
            "analysis": self.analysis,
            "timestamp": self.timestamp.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "is_valid": self.is_valid,
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

    def __init__(self, config: dict | None = None):
        """
        Initialize market scanner.

        Args:
            config: Configuration options
        """
        self.config = config or {}

        # Symbols to scan
        self._symbols: list[str] = []

        # Scan criteria
        self._criteria: list[ScanCriteria] = []

        # Results storage
        self._last_results: dict[str, ScanResult] = {}
        self._opportunities: list[MarketOpportunity] = []
        self._max_opportunities = self.config.get("max_opportunities", 100)

        # Data providers
        self._data_providers: dict[str, Callable] = {}

        # Callbacks
        self._on_opportunity_callbacks: list[Callable] = []

        # Thread safety
        self._lock = threading.RLock()

        # Configuration
        self._min_strength = self.config.get("min_strength", 50.0)
        self._parallel_scan = self.config.get("parallel_scan", True)
        self._max_workers = self.config.get("max_workers", 10)

        # Statistics
        self._stats = {
            "scans_performed": 0,
            "opportunities_found": 0,
            "last_scan_time": None,
        }

        logger.info("Market Scanner initialized")

    # ================================================================
    # SYMBOL MANAGEMENT
    # ================================================================

    def add_symbols(self, symbols: list[str]):
        """Add symbols to scan."""
        with self._lock:
            for symbol in symbols:
                if symbol not in self._symbols:
                    self._symbols.append(symbol)
        logger.info("Added %s symbols to scanner", len(symbols))

    def remove_symbol(self, symbol: str):
        """Remove a symbol from scanning."""
        with self._lock:
            if symbol in self._symbols:
                self._symbols.remove(symbol)

    def set_symbols(self, symbols: list[str]):
        """Set the complete list of symbols to scan."""
        with self._lock:
            self._symbols = list(symbols)

    def get_symbols(self) -> list[str]:
        """Get list of symbols being scanned."""
        return self._symbols.copy()

    # ================================================================
    # CRITERIA MANAGEMENT
    # ================================================================

    def add_criteria(
        self,
        criteria_type: ScanCriteriaType,
        parameters: dict | None = None,
        weight: float = 1.0,
        required: bool = False,
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
            required=required,
        )
        with self._lock:
            self._criteria.append(criteria)

    def clear_criteria(self):
        """Clear all scan criteria."""
        with self._lock:
            self._criteria.clear()

    def get_criteria(self) -> list[ScanCriteria]:
        """Get current scan criteria."""
        return self._criteria.copy()

    # ================================================================
    # SCANNING
    # ================================================================

    def scan(
        self,
        market_data: dict[str, dict[str, Any]],
        criteria: list[ScanCriteriaType] | None = None,
        min_strength: float | None = None,
    ) -> list[ScanResult]:
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
            active_criteria = [c for c in self._criteria if c.type in criteria]

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
            self._stats["scans_performed"] += 1
            self._stats["last_scan_time"] = datetime.now(UTC).isoformat()

        # Generate opportunities from results
        self._generate_opportunities(results)

        return results

    def _scan_sequential(
        self, market_data: dict[str, dict[str, Any]], criteria: list[ScanCriteria]
    ) -> list[ScanResult]:
        """Scan symbols sequentially."""
        results = []

        for symbol in self._symbols:
            if symbol not in market_data:
                continue

            result = self._scan_symbol(symbol, market_data[symbol], criteria)
            if result:
                results.append(result)

        return results

    def _scan_parallel(self, market_data: dict[str, dict[str, Any]], criteria: list[ScanCriteria]) -> list[ScanResult]:
        """Scan symbols in parallel."""
        results = []

        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            futures = {
                executor.submit(self._scan_symbol, symbol, market_data.get(symbol, {}), criteria): symbol
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
                    logger.error("Error scanning %s: %s", symbol, e)

        return results

    def _scan_symbol(self, symbol: str, data: dict[str, Any], criteria: list[ScanCriteria]) -> ScanResult | None:
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
                direction = detail.get("direction", "neutral")
                if direction == "bullish":
                    bullish_score += criterion.weight
                elif direction == "bearish":
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
            details=details,
        )

    # ----------------------------------------------------------------
    # Per-criterion check helpers
    # ----------------------------------------------------------------

    def _check_breakout(self, params: dict, data: dict, ctx: dict) -> tuple:
        period = params.get("period", 20)
        high_period = data.get(f"high_{period}", ctx["high_20"])
        price = ctx["price"]
        if price > high_period:
            return True, {
                "direction": "bullish",
                "level": high_period,
                "breakout_pct": round((price - high_period) / high_period * 100, 2),
            }
        return False, {}

    def _check_volume_spike(self, params: dict, ctx: dict) -> tuple:
        multiplier = params.get("multiplier", 2.0)
        volume, avg_volume = ctx["volume"], ctx["avg_volume"]
        if avg_volume > 0 and volume > avg_volume * multiplier:
            return True, {
                "direction": "neutral",
                "volume": volume,
                "avg_volume": avg_volume,
                "multiplier": round(volume / avg_volume, 2),
            }
        return False, {}

    def _check_volatility_expansion(self, params: dict, ctx: dict) -> tuple:
        atr_multiplier = params.get("multiplier", 1.5)
        atr = ctx["atr"]
        avg_atr = ctx.get("avg_atr", atr)
        if avg_atr > 0 and atr > avg_atr * atr_multiplier:
            return True, {"direction": "neutral", "atr": atr, "avg_atr": avg_atr, "expansion": round(atr / avg_atr, 2)}
        return False, {}

    def _check_gap(self, params: dict, data: dict, ctx: dict, gap_up: bool) -> tuple:
        gap_pct = params.get("min_gap_pct", 1.0)
        open_price = ctx["open_price"]
        prev_close = data.get("prev_close", open_price)
        if prev_close > 0:
            if gap_up:
                gap = (open_price - prev_close) / prev_close * 100
                if gap >= gap_pct:
                    return True, {"direction": "bullish", "gap_pct": round(gap, 2)}
            else:
                gap = (prev_close - open_price) / prev_close * 100
                if gap >= gap_pct:
                    return True, {"direction": "bearish", "gap_pct": round(gap, 2)}
        return False, {}

    def _check_rsi(self, params: dict, ctx: dict, *, overbought: bool) -> tuple:
        """Return True when RSI is in the overbought or oversold zone."""
        rsi = ctx.get("rsi")
        if rsi is None:
            return False, {}
        if overbought:
            threshold = params.get("threshold", 70)
            if rsi >= threshold:
                return True, {"direction": "bearish", "rsi": rsi, "threshold": threshold}
        else:
            threshold = params.get("threshold", 30)
            if rsi <= threshold:
                return True, {"direction": "bullish", "rsi": rsi, "threshold": threshold}
        return False, {}

    def _check_price_vs_ma(self, params: dict, data: dict, ctx: dict, *, above: bool) -> tuple:
        """Return True when price is above (or below) a moving average."""
        period = params.get("period", 20)
        ma_key = f"ma_{period}"
        ma = data.get(ma_key) or ctx.get(ma_key) or ctx.get(f"sma_{period}")
        price = ctx["price"]
        if ma is None or ma <= 0:
            return False, {}
        if above:
            if price > ma:
                return True, {"direction": "bullish", "price": price, "ma": ma, "period": period}
        elif price < ma:
            return True, {"direction": "bearish", "price": price, "ma": ma, "period": period}
        return False, {}

    def _check_momentum(self, params: dict, ctx: dict) -> tuple:
        """Return True when the candle's percentage gain exceeds *min_change_pct*."""
        min_change_pct = params.get("min_change_pct", 0.5)
        price = ctx["price"]
        open_price = ctx.get("open_price", price)
        if open_price <= 0:
            return False, {}
        change_pct = (price - open_price) / open_price * 100
        if abs(change_pct) >= min_change_pct:
            direction = "bullish" if change_pct > 0 else "bearish"
            return True, {"direction": direction, "change_pct": round(change_pct, 3)}
        return False, {}

    def _check_macd_cross(self, params: dict, data: dict, ctx: dict, *, bullish: bool) -> tuple:
        """Return True when MACD crosses its signal line in the given direction."""
        macd = data.get("macd")
        signal = data.get("macd_signal")
        prev_macd = data.get("prev_macd")
        prev_signal = data.get("prev_macd_signal")
        if any(v is None for v in (macd, signal, prev_macd, prev_signal)):
            return False, {}
        if bullish:
            # Previous: macd below signal; Current: macd above signal
            if prev_macd <= prev_signal and macd > signal:
                return True, {"direction": "bullish", "macd": macd, "signal": signal}
        # Previous: macd above signal; Current: macd below signal
        elif prev_macd >= prev_signal and macd < signal:
            return True, {"direction": "bearish", "macd": macd, "signal": signal}
        return False, {}

    def _check_trend(self, ctx: dict, *, uptrend: bool, data: dict | None = None) -> tuple:
        """Return True when the short MA is above (uptrend) or below (downtrend) the long MA."""
        _data = data or {}
        sma_short = _data.get("ma_20") or ctx.get("sma_20") or ctx.get("ma_20") or ctx.get("high_20")
        sma_long = _data.get("ma_50") or ctx.get("sma_50") or ctx.get("ma_50") or ctx.get("high_50")
        if sma_short is None or sma_long is None:
            # Fallback: compare current price to a single MA level
            price = ctx.get("price", 0)
            ma = _data.get("ma_50") or ctx.get("ma_50") or ctx.get("sma_50") or ctx.get("high_50")
            if ma is None or ma <= 0:
                return False, {}
            if uptrend:
                return (price > ma), {"direction": "bullish", "price": price, "ma": ma}
            return (price < ma), {"direction": "bearish", "price": price, "ma": ma}
        if uptrend:
            if sma_short > sma_long:
                return True, {"direction": "bullish", "sma_short": sma_short, "sma_long": sma_long}
        elif sma_short < sma_long:
            return True, {"direction": "bearish", "sma_short": sma_short, "sma_long": sma_long}
        return False, {}

    def _check_new_extreme(self, params: dict, data: dict, ctx: dict, *, new_high: bool) -> tuple:
        """Return True when price (or high/low) sets a new n-period extreme."""
        period = params.get("period", 20)
        price = ctx["price"]
        if new_high:
            level = data.get(f"high_{period}") or ctx.get(f"high_{period}")
            current = data.get("high", price)
            if level is not None and current > level:
                return True, {"direction": "bullish", "price": current, "period_high": level, "period": period}
        else:
            level = data.get(f"low_{period}") or ctx.get(f"low_{period}")
            current = data.get("low", price)
            if level is not None and current < level:
                return True, {"direction": "bearish", "price": current, "period_low": level, "period": period}
        return False, {}

    def _check_ma_crossover(self, params: dict, data: dict, ctx: dict) -> tuple:
        """Return True on a golden cross (fast MA crosses above slow MA) or death cross."""
        fast_period = params.get("fast_period", 20)
        slow_period = params.get("slow_period", 50)
        fast_key = f"ma_{fast_period}"
        slow_key = f"ma_{slow_period}"
        prev_fast_key = f"prev_ma_{fast_period}"
        prev_slow_key = f"prev_ma_{slow_period}"

        fast = data.get(fast_key) or ctx.get(fast_key)
        slow = data.get(slow_key) or ctx.get(slow_key)
        prev_fast = data.get(prev_fast_key)
        prev_slow = data.get(prev_slow_key)

        if any(v is None for v in (fast, slow, prev_fast, prev_slow)):
            return False, {}

        # Golden cross: prev_fast ≤ prev_slow and fast > slow
        if prev_fast <= prev_slow and fast > slow:
            return True, {"direction": "bullish", "fast_ma": fast, "slow_ma": slow, "cross": "golden"}
        # Death cross: prev_fast ≥ prev_slow and fast < slow
        if prev_fast >= prev_slow and fast < slow:
            return True, {"direction": "bearish", "fast_ma": fast, "slow_ma": slow, "cross": "death"}
        return False, {}

    def _check_criterion(self, criterion: ScanCriteria, data: dict[str, Any]) -> tuple:
        """Check if a criterion is met. Returns (met: bool, details: dict)."""
        ctype = criterion.type
        params = criterion.parameters

        price = data.get("price", data.get("close", 0))
        ctx = {
            "price": price,
            "open_price": data.get("open", price),
            "high": data.get("high", price),
            "low": data.get("low", price),
            "volume": data.get("volume", 0),
            "ma_20": data.get("ma_20", data.get("sma_20", price)),
            "ma_50": data.get("ma_50", data.get("sma_50", price)),
            "rsi": data.get("rsi", data.get("rsi_14", 50)),
            "macd": data.get("macd", 0),
            "macd_signal": data.get("macd_signal", 0),
            "atr": data.get("atr", 0),
            "avg_atr": data.get("avg_atr", data.get("atr", 0)),
            "high_20": data.get("high_20", data.get("high", price)),
            "low_20": data.get("low_20", data.get("low", price)),
            "avg_volume": data.get("avg_volume", data.get("volume", 0)),
        }

        dispatch = {
            ScanCriteriaType.BREAKOUT: lambda: self._check_breakout(params, data, ctx),
            ScanCriteriaType.PRICE_ABOVE_MA: lambda: self._check_price_vs_ma(params, data, ctx, above=True),
            ScanCriteriaType.PRICE_BELOW_MA: lambda: self._check_price_vs_ma(params, data, ctx, above=False),
            ScanCriteriaType.RSI_OVERBOUGHT: lambda: self._check_rsi(params, ctx, overbought=True),
            ScanCriteriaType.RSI_OVERSOLD: lambda: self._check_rsi(params, ctx, overbought=False),
            ScanCriteriaType.MOMENTUM: lambda: self._check_momentum(params, ctx),
            ScanCriteriaType.VOLUME_SPIKE: lambda: self._check_volume_spike(params, ctx),
            ScanCriteriaType.MACD_BULLISH_CROSS: lambda: self._check_macd_cross(params, data, ctx, bullish=True),
            ScanCriteriaType.MACD_BEARISH_CROSS: lambda: self._check_macd_cross(params, data, ctx, bullish=False),
            ScanCriteriaType.UPTREND: lambda: self._check_trend(ctx, uptrend=True, data=data),
            ScanCriteriaType.DOWNTREND: lambda: self._check_trend(ctx, uptrend=False, data=data),
            ScanCriteriaType.MA_CROSSOVER: lambda: self._check_ma_crossover(params, data, ctx),
            ScanCriteriaType.VOLATILITY_EXPANSION: lambda: self._check_volatility_expansion(params, ctx),
            ScanCriteriaType.NEW_HIGH: lambda: self._check_new_extreme(params, data, ctx, new_high=True),
            ScanCriteriaType.NEW_LOW: lambda: self._check_new_extreme(params, data, ctx, new_high=False),
            ScanCriteriaType.GAP_UP: lambda: self._check_gap(params, data, ctx, gap_up=True),
            ScanCriteriaType.GAP_DOWN: lambda: self._check_gap(params, data, ctx, gap_up=False),
        }

        handler = dispatch.get(ctype)
        if handler:
            return handler()
        return False, {}

    # ================================================================
    # OPPORTUNITIES
    # ================================================================

    def _generate_opportunities(self, results: list[ScanResult]):
        """Generate trading opportunities from scan results."""
        for result in results:
            if result.signal_strength >= 70:  # Strong signals only
                opportunity = self._create_opportunity(result)
                if opportunity:
                    self._add_opportunity(opportunity)

    def _create_opportunity(self, result: ScanResult) -> MarketOpportunity | None:
        """Create an opportunity from a scan result."""
        # Get price from details
        price = None
        for detail in result.details.values():
            if "price" in detail:
                price = detail["price"]
                break

        if not price:
            return None

        # Calculate basic levels
        atr = result.details.get("atr", 0)
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
            opportunity_type="/".join(result.criteria_met[:2]),
            direction=result.direction,
            strength=result.signal_strength,
            entry_price=price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            risk_reward=risk_reward,
            triggers=result.criteria_met,
            analysis=result.details,
            expires_at=datetime.now(UTC) + timedelta(hours=4),
        )

    def _add_opportunity(self, opportunity: MarketOpportunity):
        """Add an opportunity to storage."""
        with self._lock:
            self._opportunities.append(opportunity)

            # Trim if needed
            if len(self._opportunities) > self._max_opportunities:
                self._opportunities.pop(0)

            self._stats["opportunities_found"] += 1

            # Notify callbacks
            for callback in self._on_opportunity_callbacks:
                try:
                    callback(opportunity)
                except Exception as e:
                    logger.error("Opportunity callback error: %s", e)

    def get_opportunities(
        self,
        symbol: str | None = None,
        direction: SignalDirection | None = None,
        min_strength: float = 0,
    ) -> list[MarketOpportunity]:
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

    def get_top_opportunities(self, limit: int = 10) -> list[MarketOpportunity]:
        """Get top opportunities by strength."""
        return self.get_opportunities()[:limit]

    def on_opportunity(self, callback: Callable):
        """Register callback for new opportunities."""
        self._on_opportunity_callbacks.append(callback)

    # ================================================================
    # RESULTS ACCESS
    # ================================================================

    def get_last_result(self, symbol: str) -> ScanResult | None:
        """Get last scan result for a symbol."""
        return self._last_results.get(symbol)

    def get_all_results(self) -> dict[str, ScanResult]:
        """Get all last scan results."""
        return self._last_results.copy()

    def get_stats(self) -> dict:
        """Get scanner statistics."""
        return {
            **self._stats,
            "symbols_count": len(self._symbols),
            "criteria_count": len(self._criteria),
            "active_opportunities": len([o for o in self._opportunities if o.is_valid]),
        }


# ================================================================
# FASTAPI INTEGRATION
# ================================================================


def _build_scanner_models():
    """Return Pydantic request models for the scanner router."""
    from pydantic import BaseModel

    class ScanRequest(BaseModel):
        market_data: dict[str, dict[str, Any]]
        criteria: list[str] | None = None
        min_strength: float | None = None

    class AddCriteriaRequest(BaseModel):
        criteria_type: str
        parameters: dict[str, Any] = {}
        weight: float = 1.0
        required: bool = False

    return ScanRequest, AddCriteriaRequest


def _register_scanner_read_routes(router: Any, scanner: MarketScanner) -> None:
    """Register read-only GET routes on *router*."""
    from fastapi import HTTPException

    @router.get("/opportunities")
    async def get_opportunities(
        symbol: str | None = None,
        direction: str | None = None,
        min_strength: float = 0,
        limit: int = 20,
    ):
        dir_enum = SignalDirection(direction) if direction else None
        return [o.to_dict() for o in scanner.get_opportunities(symbol, dir_enum, min_strength)[:limit]]

    @router.get("/opportunities/top")
    async def get_top_opportunities(limit: int = 10):
        return [o.to_dict() for o in scanner.get_top_opportunities(limit)]

    @router.get("/symbols")
    async def get_symbols():
        return {"symbols": scanner.get_symbols()}

    @router.get("/criteria")
    async def get_criteria():
        return [c.to_dict() for c in scanner.get_criteria()]

    @router.get("/stats")
    async def get_stats():
        return scanner.get_stats()

    @router.get("/results/{symbol}")
    async def get_symbol_result_read(symbol: str):
        result = scanner.get_last_result(symbol)
        if not result:
            raise HTTPException(status_code=404, detail=f"No result for {symbol}")
        return result.to_dict()


def _register_scanner_write_routes(router: Any, scanner: MarketScanner) -> None:
    """Register mutating POST/DELETE routes on *router*."""
    from fastapi import HTTPException

    ScanRequest, AddCriteriaRequest = _build_scanner_models()

    @router.post("/scan")
    async def run_scan(request: ScanRequest):
        criteria = None
        if request.criteria:
            try:
                criteria = [ScanCriteriaType(c) for c in request.criteria]
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e)) from e
        results = scanner.scan(request.market_data, criteria=criteria, min_strength=request.min_strength)
        return [r.to_dict() for r in results]

    @router.post("/symbols")
    async def add_symbols(symbols: list[str]):
        scanner.add_symbols(symbols)
        return {"status": "added", "symbols": symbols}

    @router.post("/criteria")
    async def add_criteria(request: AddCriteriaRequest):
        try:
            criteria_type = ScanCriteriaType(request.criteria_type)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid criteria type: {request.criteria_type}",
            ) from None

        scanner.add_criteria(criteria_type, request.parameters, request.weight, request.required)
        return {"status": "added"}

    @router.delete("/criteria")
    async def clear_criteria():
        scanner.clear_criteria()
        return {"status": "cleared"}

    @router.get("/results")
    async def get_results():
        """Get last scan results."""
        return {symbol: result.to_dict() for symbol, result in scanner.get_all_results().items()}

    @router.get("/results/{symbol}")
    async def get_symbol_result(symbol: str):
        """Get last result for a symbol."""
        result = scanner.get_last_result(symbol)
        if not result:
            raise HTTPException(status_code=404, detail=f"No result for {symbol}")
        return result.to_dict()


def create_scanner_router(scanner: MarketScanner):
    """Create FastAPI router with scanner endpoints."""
    from fastapi import APIRouter

    router = APIRouter(prefix="/api/scanner", tags=["Market Scanner"])
    _register_scanner_read_routes(router, scanner)
    _register_scanner_write_routes(router, scanner)
    return router


# Global instance for easy access
_market_scanner: MarketScanner | None = None


def get_market_scanner() -> MarketScanner:
    """Get the global market scanner instance."""
    global _market_scanner
    if _market_scanner is None:
        _market_scanner = MarketScanner()
    return _market_scanner


# Module-level router — imported by core.router_registry
router = create_scanner_router(get_market_scanner())
