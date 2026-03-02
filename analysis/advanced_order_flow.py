"""
Advanced Order Flow Analyzer

Enhances the base OrderFlowAnalyzer with:
- Real-time aggression metrics (bid vs ask aggressor)
- Volume imbalance by price level
- Stacked imbalances (consecutive price levels)
- Delta divergence detection (price vs cumulative delta)
- Volume clusters (support/resistance from volume)
- Order flow oscillator
- Buy/sell pressure gauges
- Market absorption detection
"""

import logging
import math
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class AggressionMetrics:
    """Buy vs sell aggression score for a symbol."""

    symbol: str
    timestamp: datetime
    buy_aggression: float  # 0-100
    sell_aggression: float  # 0-100
    aggression_score: float  # -100 (bearish) to +100 (bullish)
    dominant_side: str
    aggression_strength: str  # 'strong', 'moderate', 'weak'

    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "buy_aggression": self.buy_aggression,
            "sell_aggression": self.sell_aggression,
            "aggression_score": self.aggression_score,
            "dominant_side": self.dominant_side,
            "aggression_strength": self.aggression_strength,
        }


@dataclass
class VolumeCluster:
    """A significant volume cluster acting as support or resistance."""

    price_level: float
    total_volume: float
    buy_volume: float
    sell_volume: float
    trade_count: int
    cluster_type: str  # 'support', 'resistance', 'neutral'
    strength: float  # 0-1

    def to_dict(self) -> Dict:
        return {
            "price_level": self.price_level,
            "total_volume": self.total_volume,
            "buy_volume": self.buy_volume,
            "sell_volume": self.sell_volume,
            "trade_count": self.trade_count,
            "cluster_type": self.cluster_type,
            "strength": self.strength,
        }


@dataclass
class DeltaDivergence:
    """Delta divergence between price and cumulative delta."""

    symbol: str
    timestamp: datetime
    divergence_type: str  # 'bullish', 'bearish'
    price_direction: str  # 'up', 'down', 'flat'
    delta_direction: str  # 'up', 'down', 'flat'
    strength: float  # 0-1
    confidence: float  # 0-1

    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "divergence_type": self.divergence_type,
            "price_direction": self.price_direction,
            "delta_direction": self.delta_direction,
            "strength": self.strength,
            "confidence": self.confidence,
        }


@dataclass
class OrderFlowOscillator:
    """Order flow oscillator value."""

    symbol: str
    timestamp: datetime
    value: float  # -100 to +100
    signal: str  # 'bullish', 'bearish', 'neutral'
    overbought: bool
    oversold: bool

    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "value": self.value,
            "signal": self.signal,
            "overbought": self.overbought,
            "oversold": self.oversold,
        }


@dataclass
class StackedImbalance:
    """Multiple consecutive price levels with same-direction imbalance."""

    symbol: str
    timestamp: datetime
    direction: str  # 'buy' or 'sell'
    levels: List[float]  # Price levels in the stack
    total_volume: float
    avg_imbalance: float
    strength: str  # 'strong', 'moderate', 'weak'

    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "direction": self.direction,
            "levels": self.levels,
            "total_volume": self.total_volume,
            "avg_imbalance": self.avg_imbalance,
            "strength": self.strength,
        }


class AdvancedOrderFlowAnalyzer:
    """
    Advanced order flow analyzer with institutional-grade metrics.

    Extends the base order flow concept with:
    - Aggression metrics (who is driving the market)
    - Volume clusters for S/R levels
    - Delta divergence detection
    - Stacked imbalance identification
    - Order flow oscillator

    Usage:
        analyzer = AdvancedOrderFlowAnalyzer()

        for trade in trades:
            analyzer.add_trade('XAUUSD', trade['price'], trade['size'], trade['side'])

        metrics = analyzer.get_aggression_metrics('XAUUSD')
        clusters = analyzer.get_volume_clusters('XAUUSD')
        divergence = analyzer.detect_delta_divergence('XAUUSD')
    """

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize advanced analyzer.

        Args:
            config: Configuration options:
                - tick_size: Minimum price increment (default 0.01)
                - cluster_bins: Number of price bins for clustering (default 50)
                - max_trades: Max trades per symbol (default 100000)
                - imbalance_threshold: Ratio to flag imbalance (default 0.3)
                - divergence_lookback: Bars for divergence calculation (default 20)
                - oscillator_period: Trades to include in oscillator (default 100)
        """
        self.config = config or {}
        self._tick_size = self.config.get("tick_size", 0.01)
        self._cluster_bins = self.config.get("cluster_bins", 50)
        self._max_trades = self.config.get("max_trades", 100000)
        self._imbalance_threshold = self.config.get("imbalance_threshold", 0.3)
        self._divergence_lookback = self.config.get("divergence_lookback", 20)
        self._oscillator_period = self.config.get("oscillator_period", 100)

        # Trade storage: symbol -> list of (timestamp, price, size, side)
        self._trades: Dict[str, List] = defaultdict(list)
        self._cumulative_delta: Dict[str, float] = defaultdict(float)

        logger.info("Advanced Order Flow Analyzer initialized")

    # ================================================================
    # TRADE MANAGEMENT
    # ================================================================

    def add_trade(
        self,
        symbol: str,
        price: float,
        size: float,
        side: str,
        timestamp: Optional[datetime] = None,
    ) -> None:
        """Add a trade for analysis."""
        ts = timestamp or datetime.utcnow()
        s = side.lower()
        self._trades[symbol].append((ts, price, size, s))
        delta = size if s == "buy" else -size
        self._cumulative_delta[symbol] += delta

        if len(self._trades[symbol]) > self._max_trades:
            removed_ts, _, removed_size, removed_side = self._trades[symbol].pop(0)
            adj = removed_size if removed_side == "buy" else -removed_size
            self._cumulative_delta[symbol] -= adj

    def clear_trades(self, symbol: str) -> None:
        """Clear trades for a symbol."""
        self._trades.pop(symbol, None)
        self._cumulative_delta.pop(symbol, None)

    # ================================================================
    # AGGRESSION METRICS
    # ================================================================

    def get_aggression_metrics(
        self,
        symbol: str,
        lookback_minutes: int = 60,
    ) -> Optional[AggressionMetrics]:
        """
        Calculate real-time buy/sell aggression metrics.

        Args:
            symbol: Trading symbol
            lookback_minutes: Lookback window

        Returns:
            AggressionMetrics or None
        """
        cutoff = datetime.utcnow() - timedelta(minutes=lookback_minutes)
        trades = [t for t in self._trades.get(symbol, []) if t[0] >= cutoff]

        if not trades:
            return None

        buy_vol = sum(t[2] for t in trades if t[3] == "buy")
        sell_vol = sum(t[2] for t in trades if t[3] == "sell")
        total_vol = buy_vol + sell_vol

        if total_vol == 0:
            return None

        buy_aggression = round(buy_vol / total_vol * 100, 2)
        sell_aggression = round(sell_vol / total_vol * 100, 2)
        # Score: +100 = fully buy dominated, -100 = fully sell dominated
        score = round((buy_vol - sell_vol) / total_vol * 100, 2)
        dominant = "buyers" if score > 0 else ("sellers" if score < 0 else "neutral")
        abs_score = abs(score)
        strength = (
            "strong" if abs_score > 60 else ("moderate" if abs_score > 30 else "weak")
        )

        return AggressionMetrics(
            symbol=symbol,
            timestamp=datetime.utcnow(),
            buy_aggression=buy_aggression,
            sell_aggression=sell_aggression,
            aggression_score=score,
            dominant_side=dominant,
            aggression_strength=strength,
        )

    # ================================================================
    # VOLUME IMBALANCE
    # ================================================================

    def get_volume_imbalance_by_level(
        self,
        symbol: str,
        price_bins: int = 20,
        lookback_minutes: int = 60,
    ) -> List[Dict]:
        """
        Calculate volume imbalance at each price level.

        Args:
            symbol: Trading symbol
            price_bins: Number of price buckets
            lookback_minutes: Lookback window

        Returns:
            List of dicts with price/imbalance info per level
        """
        cutoff = datetime.utcnow() - timedelta(minutes=lookback_minutes)
        trades = [t for t in self._trades.get(symbol, []) if t[0] >= cutoff]

        if not trades:
            return []

        prices = [t[1] for t in trades]
        min_p, max_p = min(prices), max(prices)
        if min_p == max_p:
            return []

        bucket = (max_p - min_p) / price_bins
        levels: Dict[int, Dict] = {}

        for ts, price, size, side in trades:
            idx = min(int((price - min_p) / bucket), price_bins - 1)
            if idx not in levels:
                levels[idx] = {
                    "price": round(min_p + (idx + 0.5) * bucket, 5),
                    "buy_volume": 0.0,
                    "sell_volume": 0.0,
                }
            if side == "buy":
                levels[idx]["buy_volume"] += size
            else:
                levels[idx]["sell_volume"] += size

        result = []
        for idx in sorted(levels):
            d = levels[idx]
            total = d["buy_volume"] + d["sell_volume"]
            imbalance = (
                round((d["buy_volume"] - d["sell_volume"]) / total, 4)
                if total > 0
                else 0.0
            )
            result.append(
                {
                    "price": d["price"],
                    "buy_volume": d["buy_volume"],
                    "sell_volume": d["sell_volume"],
                    "total_volume": total,
                    "imbalance": imbalance,
                }
            )

        return result

    def get_stacked_imbalances(
        self,
        symbol: str,
        price_bins: int = 20,
        lookback_minutes: int = 60,
        min_stack_size: int = 3,
    ) -> List[StackedImbalance]:
        """
        Detect stacked imbalances - consecutive levels with same-direction imbalance.

        Args:
            symbol: Trading symbol
            price_bins: Number of price buckets
            lookback_minutes: Lookback window
            min_stack_size: Minimum consecutive levels to qualify

        Returns:
            List of StackedImbalance objects
        """
        imbalances = self.get_volume_imbalance_by_level(
            symbol, price_bins=price_bins, lookback_minutes=lookback_minutes
        )

        if not imbalances:
            return []

        results = []
        current_stack: List[Dict] = []
        current_dir: Optional[str] = None

        def _flush_stack(stack: List[Dict], direction: str) -> None:
            if len(stack) < min_stack_size:
                return
            prices = [s["price"] for s in stack]
            total_vol = sum(s["total_volume"] for s in stack)
            avg_imb = sum(abs(s["imbalance"]) for s in stack) / len(stack)
            strength = (
                "strong"
                if avg_imb > 0.5
                else ("moderate" if avg_imb > 0.25 else "weak")
            )
            results.append(
                StackedImbalance(
                    symbol=symbol,
                    timestamp=datetime.utcnow(),
                    direction=direction,
                    levels=prices,
                    total_volume=total_vol,
                    avg_imbalance=round(avg_imb, 4),
                    strength=strength,
                )
            )

        for level in imbalances:
            imb = level["imbalance"]
            if abs(imb) < self._imbalance_threshold:
                if current_stack:
                    _flush_stack(current_stack, current_dir or "buy")
                current_stack = []
                current_dir = None
                continue

            direction = "buy" if imb > 0 else "sell"
            if direction != current_dir:
                if current_stack:
                    _flush_stack(current_stack, current_dir or "buy")
                current_stack = [level]
                current_dir = direction
            else:
                current_stack.append(level)

        if current_stack:
            _flush_stack(current_stack, current_dir or "buy")

        return results

    # ================================================================
    # DELTA DIVERGENCE
    # ================================================================

    def detect_delta_divergence(
        self,
        symbol: str,
        lookback_minutes: int = 60,
        segment_minutes: int = 5,
    ) -> Optional[DeltaDivergence]:
        """
        Detect divergence between price direction and cumulative delta direction.

        A bullish divergence occurs when price falls but delta rises.
        A bearish divergence occurs when price rises but delta falls.

        Args:
            symbol: Trading symbol
            lookback_minutes: Total analysis window
            segment_minutes: Time granularity for comparison

        Returns:
            DeltaDivergence or None
        """
        cutoff = datetime.utcnow() - timedelta(minutes=lookback_minutes)
        trades = [t for t in self._trades.get(symbol, []) if t[0] >= cutoff]

        if len(trades) < 10:
            return None

        # Split into two halves and compare
        mid = len(trades) // 2
        first_half = trades[:mid]
        second_half = trades[mid:]

        def _half_stats(half: List) -> Tuple[float, float]:
            avg_price = sum(t[1] for t in half) / len(half)
            delta = sum(t[2] if t[3] == "buy" else -t[2] for t in half)
            return avg_price, delta

        p1, d1 = _half_stats(first_half)
        p2, d2 = _half_stats(second_half)

        price_dir = "up" if p2 > p1 else ("down" if p2 < p1 else "flat")
        delta_dir = "up" if d2 > d1 else ("down" if d2 < d1 else "flat")

        # No divergence if both move in same direction or either is flat
        if price_dir == "flat" or delta_dir == "flat":
            return None
        if price_dir == delta_dir:
            return None

        # Bullish divergence: price down but delta up
        # Bearish divergence: price up but delta down
        divergence_type = (
            "bullish" if price_dir == "down" and delta_dir == "up" else "bearish"
        )

        price_move = abs(p2 - p1) / p1 if p1 > 0 else 0.0
        delta_move = abs(d2 - d1) / (abs(d1) + 1)
        strength = min(1.0, (price_move * 1000 + delta_move) / 2)
        confidence = min(1.0, len(trades) / 100)

        return DeltaDivergence(
            symbol=symbol,
            timestamp=datetime.utcnow(),
            divergence_type=divergence_type,
            price_direction=price_dir,
            delta_direction=delta_dir,
            strength=round(strength, 4),
            confidence=round(confidence, 4),
        )

    # ================================================================
    # VOLUME CLUSTERS
    # ================================================================

    def get_volume_clusters(
        self,
        symbol: str,
        price_bins: int = 50,
        lookback_minutes: int = 240,
        current_price: Optional[float] = None,
        top_n: int = 10,
    ) -> List[VolumeCluster]:
        """
        Identify significant volume clusters acting as S/R levels.

        Args:
            symbol: Trading symbol
            price_bins: Number of price buckets
            lookback_minutes: Lookback window
            current_price: Current market price for S/R classification
            top_n: Return only top N clusters by volume

        Returns:
            List of VolumeCluster objects
        """
        cutoff = datetime.utcnow() - timedelta(minutes=lookback_minutes)
        trades = [t for t in self._trades.get(symbol, []) if t[0] >= cutoff]

        if not trades:
            return []

        prices = [t[1] for t in trades]
        min_p, max_p = min(prices), max(prices)
        if min_p == max_p:
            return []

        bucket = (max_p - min_p) / price_bins
        bins: Dict[int, Dict] = {}

        for ts, price, size, side in trades:
            idx = min(int((price - min_p) / bucket), price_bins - 1)
            if idx not in bins:
                bins[idx] = {
                    "price": round(min_p + (idx + 0.5) * bucket, 5),
                    "total": 0.0,
                    "buy": 0.0,
                    "sell": 0.0,
                    "count": 0,
                }
            bins[idx]["total"] += size
            bins[idx]["count"] += 1
            if side == "buy":
                bins[idx]["buy"] += size
            else:
                bins[idx]["sell"] += size

        if not bins:
            return []

        max_vol = max(b["total"] for b in bins.values())
        avg_vol = sum(b["total"] for b in bins.values()) / len(bins)

        # Only significant clusters
        significant = [b for b in bins.values() if b["total"] >= avg_vol * 1.5]
        significant.sort(key=lambda x: -x["total"])
        significant = significant[:top_n]

        cur = current_price or prices[-1]
        clusters = []
        for b in significant:
            strength = round(b["total"] / max_vol, 4) if max_vol > 0 else 0.0
            cluster_type = (
                "support"
                if b["price"] < cur
                else ("resistance" if b["price"] > cur else "neutral")
            )
            clusters.append(
                VolumeCluster(
                    price_level=b["price"],
                    total_volume=b["total"],
                    buy_volume=b["buy"],
                    sell_volume=b["sell"],
                    trade_count=b["count"],
                    cluster_type=cluster_type,
                    strength=strength,
                )
            )

        return clusters

    # ================================================================
    # ORDER FLOW OSCILLATOR
    # ================================================================

    def get_order_flow_oscillator(
        self,
        symbol: str,
        period: Optional[int] = None,
    ) -> Optional[OrderFlowOscillator]:
        """
        Calculate order flow oscillator from recent trades.

        The oscillator measures cumulative buy pressure minus sell
        pressure over the last ``period`` trades, normalised to -100/+100.

        Args:
            symbol: Trading symbol
            period: Number of recent trades to use (defaults to config)

        Returns:
            OrderFlowOscillator or None
        """
        n = period or self._oscillator_period
        trades = self._trades.get(symbol, [])[-n:]

        if not trades:
            return None

        buy_vol = sum(t[2] for t in trades if t[3] == "buy")
        sell_vol = sum(t[2] for t in trades if t[3] == "sell")
        total_vol = buy_vol + sell_vol

        if total_vol == 0:
            return None

        value = round((buy_vol - sell_vol) / total_vol * 100, 2)
        signal = "bullish" if value > 20 else ("bearish" if value < -20 else "neutral")

        return OrderFlowOscillator(
            symbol=symbol,
            timestamp=datetime.utcnow(),
            value=value,
            signal=signal,
            overbought=value > 70,
            oversold=value < -70,
        )

    # ================================================================
    # PRESSURE GAUGES
    # ================================================================

    def get_pressure_gauges(
        self,
        symbol: str,
        lookback_minutes: int = 15,
    ) -> Optional[Dict]:
        """
        Get buy/sell pressure gauge readings.

        Args:
            symbol: Trading symbol
            lookback_minutes: Lookback window

        Returns:
            Dict with buy_pressure and sell_pressure (0-100 each)
        """
        cutoff = datetime.utcnow() - timedelta(minutes=lookback_minutes)
        trades = [t for t in self._trades.get(symbol, []) if t[0] >= cutoff]

        if not trades:
            return None

        buy_vol = sum(t[2] for t in trades if t[3] == "buy")
        sell_vol = sum(t[2] for t in trades if t[3] == "sell")
        total_vol = buy_vol + sell_vol

        if total_vol == 0:
            return None

        buy_pressure = round(buy_vol / total_vol * 100, 2)
        sell_pressure = round(sell_vol / total_vol * 100, 2)

        return {
            "symbol": symbol,
            "timestamp": datetime.utcnow().isoformat(),
            "buy_pressure": buy_pressure,
            "sell_pressure": sell_pressure,
            "dominant": "buyers" if buy_pressure > sell_pressure else "sellers",
        }

    # ================================================================
    # STATISTICS
    # ================================================================

    def get_stats(self) -> Dict:
        """Get analyzer statistics."""
        return {
            "symbols_tracked": len(self._trades),
            "symbols": list(self._trades.keys()),
            "trade_counts": {s: len(t) for s, t in self._trades.items()},
            "cumulative_deltas": dict(self._cumulative_delta),
        }


# Global instance
_advanced_analyzer: Optional[AdvancedOrderFlowAnalyzer] = None


def get_advanced_order_flow_analyzer() -> AdvancedOrderFlowAnalyzer:
    """Get the global advanced order flow analyzer instance."""
    global _advanced_analyzer
    if _advanced_analyzer is None:
        _advanced_analyzer = AdvancedOrderFlowAnalyzer()
    return _advanced_analyzer
