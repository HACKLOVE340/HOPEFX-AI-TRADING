"""
Order Flow Analysis Module

Professional order flow analysis tools:
- Volume profile calculation
- Order flow imbalance
- Delta (buy vs sell volume)
- Cumulative delta
- Volume-weighted price levels
- Support/resistance from order flow
- Absorption detection

Inspired by: Bookmap, Sierra Chart, OrderFlow.pro
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from collections import defaultdict
import math

logger = logging.getLogger(__name__)


@dataclass
class Trade:
    """Individual trade record."""
    timestamp: datetime
    price: float
    size: float
    side: str  # 'buy' or 'sell'
    trade_id: Optional[str] = None

    @property
    def is_buy(self) -> bool:
        return self.side.lower() == 'buy'

    @property
    def is_sell(self) -> bool:
        return self.side.lower() == 'sell'


@dataclass
class VolumeProfileLevel:
    """Single level in volume profile."""
    price: float
    total_volume: float
    buy_volume: float
    sell_volume: float
    trade_count: int
    delta: float  # buy_volume - sell_volume

    @property
    def buy_pct(self) -> float:
        if self.total_volume == 0:
            return 0
        return round((self.buy_volume / self.total_volume) * 100, 2)

    @property
    def sell_pct(self) -> float:
        if self.total_volume == 0:
            return 0
        return round((self.sell_volume / self.total_volume) * 100, 2)

    @property
    def imbalance(self) -> float:
        """Volume imbalance ratio (-1 to 1)."""
        if self.total_volume == 0:
            return 0
        return round(self.delta / self.total_volume, 4)

    def to_dict(self) -> Dict:
        return {
            'price': self.price,
            'total_volume': self.total_volume,
            'buy_volume': self.buy_volume,
            'sell_volume': self.sell_volume,
            'trade_count': self.trade_count,
            'delta': self.delta,
            'buy_pct': self.buy_pct,
            'sell_pct': self.sell_pct,
            'imbalance': self.imbalance
        }


@dataclass
class VolumeProfile:
    """Complete volume profile."""
    symbol: str
    start_time: datetime
    end_time: datetime
    levels: List[VolumeProfileLevel]
    total_volume: float
    total_buy_volume: float
    total_sell_volume: float
    total_delta: float
    poc_price: float  # Point of Control
    vah_price: float  # Value Area High
    val_price: float  # Value Area Low

    def to_dict(self) -> Dict:
        return {
            'symbol': self.symbol,
            'start_time': self.start_time.isoformat(),
            'end_time': self.end_time.isoformat(),
            'levels': [level.to_dict() for level in self.levels],
            'total_volume': self.total_volume,
            'total_buy_volume': self.total_buy_volume,
            'total_sell_volume': self.total_sell_volume,
            'total_delta': self.total_delta,
            'poc_price': self.poc_price,
            'vah_price': self.vah_price,
            'val_price': self.val_price,
            'value_area': {
                'high': self.vah_price,
                'low': self.val_price,
                'poc': self.poc_price
            }
        }


@dataclass
class OrderFlowAnalysis:
    """Order flow analysis results."""
    symbol: str
    timestamp: datetime

    # Volume metrics
    total_volume: float
    buy_volume: float
    sell_volume: float
    delta: float
    cumulative_delta: float

    # Imbalance analysis
    imbalance_ratio: float
    dominant_side: str  # 'buyers', 'sellers', 'neutral'
    imbalance_strength: str  # 'strong', 'moderate', 'weak'

    # Key levels
    high_volume_nodes: List[Dict]
    low_volume_nodes: List[Dict]
    absorption_levels: List[Dict]

    # Signals
    buying_pressure: float  # 0-100
    selling_pressure: float  # 0-100
    order_flow_signal: str  # 'bullish', 'bearish', 'neutral'

    def to_dict(self) -> Dict:
        return {
            'symbol': self.symbol,
            'timestamp': self.timestamp.isoformat(),
            'total_volume': self.total_volume,
            'buy_volume': self.buy_volume,
            'sell_volume': self.sell_volume,
            'delta': self.delta,
            'cumulative_delta': self.cumulative_delta,
            'imbalance_ratio': self.imbalance_ratio,
            'dominant_side': self.dominant_side,
            'imbalance_strength': self.imbalance_strength,
            'high_volume_nodes': self.high_volume_nodes,
            'low_volume_nodes': self.low_volume_nodes,
            'absorption_levels': self.absorption_levels,
            'buying_pressure': self.buying_pressure,
            'selling_pressure': self.selling_pressure,
            'order_flow_signal': self.order_flow_signal
        }


@dataclass
class Footprint:
    """
    Footprint chart data for a single bar.
    Shows buy/sell volume at each price level.
    """
    symbol: str
    timeframe: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    levels: Dict[float, Dict]  # price -> {buy_vol, sell_vol, delta}
    total_volume: float
    delta: float
    cumulative_delta: float

    def to_dict(self) -> Dict:
        return {
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'timestamp': self.timestamp.isoformat(),
            'ohlc': {
                'open': self.open,
                'high': self.high,
                'low': self.low,
                'close': self.close
            },
            'levels': self.levels,
            'total_volume': self.total_volume,
            'delta': self.delta,
            'cumulative_delta': self.cumulative_delta
        }


class OrderFlowAnalyzer:
    """
    Order flow analysis service.

    Features:
    - Volume profile calculation
    - Delta analysis
    - Footprint charts
    - Imbalance detection
    - High/low volume node detection
    - Absorption level detection
    - VWAP calculation
    - Point of Control (POC)
    - Value Area (VA)

    Usage:
        analyzer = OrderFlowAnalyzer()

        # Add trades
        for trade in trades:
            analyzer.add_trade(symbol, trade)

        # Get volume profile
        profile = analyzer.get_volume_profile('XAUUSD')

        # Get order flow analysis
        analysis = analyzer.analyze('XAUUSD')
    """

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize order flow analyzer.

        Args:
            config: Configuration options
        """
        self.config = config or {}

        # Trade storage by symbol
        self._trades: Dict[str, List[Trade]] = defaultdict(list)

        # Cumulative delta by symbol
        self._cumulative_delta: Dict[str, float] = defaultdict(float)

        # Configuration
        self._tick_size = self.config.get('tick_size', 0.01)
        self._value_area_pct = self.config.get('value_area_pct', 0.70)  # 70%
        self._max_trades = self.config.get('max_trades', 100000)
        self._imbalance_threshold = self.config.get('imbalance_threshold', 0.30)

        logger.info("Order Flow Analyzer initialized")

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
        trade_id: Optional[str] = None
    ):
        """
        Add a trade for analysis.

        Args:
            symbol: Trading symbol
            price: Trade price
            size: Trade size
            side: 'buy' or 'sell'
            timestamp: Trade timestamp
            trade_id: Optional trade ID
        """
        trade = Trade(
            timestamp=timestamp or datetime.utcnow(),
            price=price,
            size=size,
            side=side.lower(),
            trade_id=trade_id
        )

        self._trades[symbol].append(trade)

        # Update cumulative delta
        delta = size if trade.is_buy else -size
        self._cumulative_delta[symbol] += delta

        # Trim if needed
        if len(self._trades[symbol]) > self._max_trades:
            removed = self._trades[symbol].pop(0)
            # Adjust cumulative delta
            adj = removed.size if removed.is_buy else -removed.size
            self._cumulative_delta[symbol] -= adj

    def add_trades(self, symbol: str, trades: List[Dict]):
        """Add multiple trades."""
        for t in trades:
            self.add_trade(
                symbol=symbol,
                price=t['price'],
                size=t['size'],
                side=t['side'],
                timestamp=t.get('timestamp'),
                trade_id=t.get('trade_id')
            )

    def get_trades(
        self,
        symbol: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> List[Trade]:
        """Get trades with optional time filter."""
        trades = self._trades.get(symbol, [])

        if start_time:
            trades = [t for t in trades if t.timestamp >= start_time]
        if end_time:
            trades = [t for t in trades if t.timestamp <= end_time]

        return trades

    def clear_trades(self, symbol: str):
        """Clear trades for a symbol."""
        if symbol in self._trades:
            del self._trades[symbol]
        if symbol in self._cumulative_delta:
            del self._cumulative_delta[symbol]

    # ================================================================
    # VOLUME PROFILE
    # ================================================================

    def get_volume_profile(
        self,
        symbol: str,
        price_buckets: int = 50,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> Optional[VolumeProfile]:
        """
        Calculate volume profile for a symbol.

        Args:
            symbol: Trading symbol
            price_buckets: Number of price levels
            start_time: Start time filter
            end_time: End time filter

        Returns:
            VolumeProfile object
        """
        trades = self.get_trades(symbol, start_time, end_time)

        if not trades:
            return None

        # Get price range
        prices = [t.price for t in trades]
        min_price = min(prices)
        max_price = max(prices)

        if min_price == max_price:
            bucket_size = self._tick_size
        else:
            bucket_size = (max_price - min_price) / price_buckets

        # Aggregate volume by price level
        level_data: Dict[float, Dict] = defaultdict(lambda: {
            'total_volume': 0,
            'buy_volume': 0,
            'sell_volume': 0,
            'trade_count': 0
        })

        for trade in trades:
            # Round to bucket
            bucket_price = round(
                math.floor(trade.price / bucket_size) * bucket_size,
                5
            )

            data = level_data[bucket_price]
            data['total_volume'] += trade.size
            data['trade_count'] += 1

            if trade.is_buy:
                data['buy_volume'] += trade.size
            else:
                data['sell_volume'] += trade.size

        # Create levels
        levels = []
        total_volume = 0
        total_buy = 0
        total_sell = 0

        for price, data in sorted(level_data.items()):
            delta = data['buy_volume'] - data['sell_volume']
            level = VolumeProfileLevel(
                price=price,
                total_volume=data['total_volume'],
                buy_volume=data['buy_volume'],
                sell_volume=data['sell_volume'],
                trade_count=data['trade_count'],
                delta=delta
            )
            levels.append(level)
            total_volume += data['total_volume']
            total_buy += data['buy_volume']
            total_sell += data['sell_volume']

        # Calculate POC and Value Area
        poc_price = self._calculate_poc(levels)
        vah_price, val_price = self._calculate_value_area(levels, poc_price)

        return VolumeProfile(
            symbol=symbol,
            start_time=trades[0].timestamp,
            end_time=trades[-1].timestamp,
            levels=levels,
            total_volume=total_volume,
            total_buy_volume=total_buy,
            total_sell_volume=total_sell,
            total_delta=total_buy - total_sell,
            poc_price=poc_price,
            vah_price=vah_price,
            val_price=val_price
        )

    def _calculate_poc(self, levels: List[VolumeProfileLevel]) -> float:
        """Calculate Point of Control (highest volume price)."""
        if not levels:
            return 0

        max_level = max(levels, key=lambda x: x.total_volume)
        return max_level.price

    def _calculate_value_area(
        self,
        levels: List[VolumeProfileLevel],
        poc_price: float
    ) -> Tuple[float, float]:
        """
        Calculate Value Area High and Low.

        The Value Area contains 70% of the volume,
        starting from the POC and expanding outward.
        """
        if not levels:
            return 0, 0

        total_volume = sum(l.total_volume for l in levels)
        target_volume = total_volume * self._value_area_pct

        # Sort by price
        sorted_levels = sorted(levels, key=lambda x: x.price)

        # Find POC index
        poc_idx = next(
            (i for i, l in enumerate(sorted_levels) if l.price == poc_price),
            len(sorted_levels) // 2
        )

        # Expand from POC
        va_volume = sorted_levels[poc_idx].total_volume
        low_idx = poc_idx
        high_idx = poc_idx

        while va_volume < target_volume and (low_idx > 0 or high_idx < len(sorted_levels) - 1):
            # Check which direction has more volume
            low_vol = sorted_levels[low_idx - 1].total_volume if low_idx > 0 else 0
            high_vol = sorted_levels[high_idx + 1].total_volume if high_idx < len(sorted_levels) - 1 else 0

            if low_vol >= high_vol and low_idx > 0:
                low_idx -= 1
                va_volume += sorted_levels[low_idx].total_volume
            elif high_idx < len(sorted_levels) - 1:
                high_idx += 1
                va_volume += sorted_levels[high_idx].total_volume
            else:
                break

        return sorted_levels[high_idx].price, sorted_levels[low_idx].price

    # ================================================================
    # ORDER FLOW ANALYSIS
    # ================================================================

    def analyze(
        self,
        symbol: str,
        lookback_minutes: int = 60
    ) -> Optional[OrderFlowAnalysis]:
        """
        Perform comprehensive order flow analysis.

        Args:
            symbol: Trading symbol
            lookback_minutes: Analysis window

        Returns:
            OrderFlowAnalysis object
        """
        start_time = datetime.utcnow() - timedelta(minutes=lookback_minutes)
        trades = self.get_trades(symbol, start_time=start_time)

        if not trades:
            return None

        # Calculate volumes
        buy_volume = sum(t.size for t in trades if t.is_buy)
        sell_volume = sum(t.size for t in trades if t.is_sell)
        total_volume = buy_volume + sell_volume
        delta = buy_volume - sell_volume

        # Imbalance
        imbalance_ratio = delta / total_volume if total_volume > 0 else 0

        if imbalance_ratio > self._imbalance_threshold:
            dominant_side = 'buyers'
        elif imbalance_ratio < -self._imbalance_threshold:
            dominant_side = 'sellers'
        else:
            dominant_side = 'neutral'

        abs_imbalance = abs(imbalance_ratio)
        if abs_imbalance > 0.5:
            imbalance_strength = 'strong'
        elif abs_imbalance > 0.25:
            imbalance_strength = 'moderate'
        else:
            imbalance_strength = 'weak'

        # Get volume profile for key levels
        profile = self.get_volume_profile(symbol, price_buckets=20, start_time=start_time)

        # High volume nodes
        high_volume_nodes = []
        low_volume_nodes = []
        if profile:
            avg_volume = profile.total_volume / len(profile.levels) if profile.levels else 0
            for level in profile.levels:
                if level.total_volume > avg_volume * 1.5:
                    high_volume_nodes.append({
                        'price': level.price,
                        'volume': level.total_volume,
                        'type': 'HVN'
                    })
                elif level.total_volume < avg_volume * 0.5:
                    low_volume_nodes.append({
                        'price': level.price,
                        'volume': level.total_volume,
                        'type': 'LVN'
                    })

        # Detect absorption
        absorption_levels = self._detect_absorption(trades)

        # Calculate pressures
        buying_pressure = (buy_volume / total_volume * 100) if total_volume > 0 else 50
        selling_pressure = (sell_volume / total_volume * 100) if total_volume > 0 else 50

        # Signal
        if imbalance_ratio > 0.3:
            signal = 'bullish'
        elif imbalance_ratio < -0.3:
            signal = 'bearish'
        else:
            signal = 'neutral'

        return OrderFlowAnalysis(
            symbol=symbol,
            timestamp=datetime.utcnow(),
            total_volume=total_volume,
            buy_volume=buy_volume,
            sell_volume=sell_volume,
            delta=delta,
            cumulative_delta=self._cumulative_delta.get(symbol, 0),
            imbalance_ratio=round(imbalance_ratio, 4),
            dominant_side=dominant_side,
            imbalance_strength=imbalance_strength,
            high_volume_nodes=high_volume_nodes[:5],
            low_volume_nodes=low_volume_nodes[:5],
            absorption_levels=absorption_levels[:3],
            buying_pressure=round(buying_pressure, 2),
            selling_pressure=round(selling_pressure, 2),
            order_flow_signal=signal
        )

    def _detect_absorption(self, trades: List[Trade]) -> List[Dict]:
        """
        Detect absorption levels.

        Absorption occurs when large volume trades happen
        but price doesn't move significantly.
        """
        if len(trades) < 10:
            return []

        # Group trades by time windows
        window_size = timedelta(seconds=30)
        absorptions = []

        current_window_start = trades[0].timestamp
        window_trades = []

        for trade in trades:
            if trade.timestamp - current_window_start <= window_size:
                window_trades.append(trade)
            else:
                # Analyze window
                if len(window_trades) >= 5:
                    absorption = self._analyze_window_for_absorption(window_trades)
                    if absorption:
                        absorptions.append(absorption)

                # Start new window
                current_window_start = trade.timestamp
                window_trades = [trade]

        # Analyze last window
        if len(window_trades) >= 5:
            absorption = self._analyze_window_for_absorption(window_trades)
            if absorption:
                absorptions.append(absorption)

        return absorptions

    def _analyze_window_for_absorption(self, trades: List[Trade]) -> Optional[Dict]:
        """Analyze a time window for absorption."""
        if not trades:
            return None

        prices = [t.price for t in trades]
        volumes = [t.size for t in trades]

        price_range = max(prices) - min(prices)
        total_volume = sum(volumes)
        avg_price = sum(prices) / len(prices)

        # High volume but low price movement = absorption
        # This is a simplified heuristic
        if total_volume > 0 and price_range / avg_price < 0.001:  # < 0.1% move
            buy_vol = sum(t.size for t in trades if t.is_buy)
            sell_vol = sum(t.size for t in trades if t.is_sell)

            return {
                'price': round(avg_price, 5),
                'total_volume': total_volume,
                'buy_volume': buy_vol,
                'sell_volume': sell_vol,
                'price_range': price_range,
                'side': 'buy_absorption' if sell_vol > buy_vol else 'sell_absorption',
                'timestamp': trades[0].timestamp.isoformat()
            }

        return None

    # ================================================================
    # FOOTPRINT CHARTS
    # ================================================================

    def get_footprint(
        self,
        symbol: str,
        timeframe: str = '5m',
        bars: int = 20
    ) -> List[Footprint]:
        """
        Generate footprint chart data.

        Args:
            symbol: Trading symbol
            timeframe: Bar timeframe (1m, 5m, 15m, etc.)
            bars: Number of bars

        Returns:
            List of Footprint objects
        """
        # Parse timeframe
        tf_minutes = self._parse_timeframe(timeframe)
        tf_delta = timedelta(minutes=tf_minutes)

        trades = self._trades.get(symbol, [])
        if not trades:
            return []

        # Group trades into bars
        footprints = []
        current_bar_start = None
        bar_trades = []
        cumulative_delta = 0

        for trade in sorted(trades, key=lambda t: t.timestamp):
            bar_start = self._floor_timestamp(trade.timestamp, tf_minutes)

            if current_bar_start is None:
                current_bar_start = bar_start
                bar_trades = [trade]
            elif bar_start == current_bar_start:
                bar_trades.append(trade)
            else:
                # Create footprint for previous bar
                if bar_trades:
                    fp, cumulative_delta = self._create_footprint(
                        symbol, timeframe, current_bar_start,
                        bar_trades, cumulative_delta
                    )
                    footprints.append(fp)

                current_bar_start = bar_start
                bar_trades = [trade]

        # Last bar
        if bar_trades:
            fp, _ = self._create_footprint(
                symbol, timeframe, current_bar_start,
                bar_trades, cumulative_delta
            )
            footprints.append(fp)

        return footprints[-bars:]

    def _create_footprint(
        self,
        symbol: str,
        timeframe: str,
        timestamp: datetime,
        trades: List[Trade],
        prev_cumulative_delta: float
    ) -> Tuple[Footprint, float]:
        """Create a single footprint bar."""
        prices = [t.price for t in trades]

        # OHLC
        open_price = trades[0].price
        high_price = max(prices)
        low_price = min(prices)
        close_price = trades[-1].price

        # Volume by price level
        levels: Dict[float, Dict] = defaultdict(lambda: {
            'buy_vol': 0,
            'sell_vol': 0,
            'delta': 0
        })

        bar_delta = 0
        for trade in trades:
            price = round(trade.price, 2)  # Round to tick
            if trade.is_buy:
                levels[price]['buy_vol'] += trade.size
                levels[price]['delta'] += trade.size
                bar_delta += trade.size
            else:
                levels[price]['sell_vol'] += trade.size
                levels[price]['delta'] -= trade.size
                bar_delta -= trade.size

        total_volume = sum(t.size for t in trades)
        cumulative_delta = prev_cumulative_delta + bar_delta

        return Footprint(
            symbol=symbol,
            timeframe=timeframe,
            timestamp=timestamp,
            open=open_price,
            high=high_price,
            low=low_price,
            close=close_price,
            levels=dict(levels),
            total_volume=total_volume,
            delta=bar_delta,
            cumulative_delta=cumulative_delta
        ), cumulative_delta

    def _parse_timeframe(self, timeframe: str) -> int:
        """Parse timeframe string to minutes."""
        tf_map = {
            '1m': 1, '5m': 5, '15m': 15, '30m': 30,
            '1h': 60, '4h': 240, '1d': 1440
        }
        return tf_map.get(timeframe, 5)

    def _floor_timestamp(self, ts: datetime, minutes: int) -> datetime:
        """Floor timestamp to timeframe boundary."""
        return ts.replace(
            minute=(ts.minute // minutes) * minutes,
            second=0,
            microsecond=0
        )

    # ================================================================
    # KEY LEVELS
    # ================================================================

    def get_key_levels(self, symbol: str) -> Dict:
        """
        Get key price levels from order flow analysis.

        Returns support/resistance levels based on volume profile.
        """
        profile = self.get_volume_profile(symbol, price_buckets=30)

        if not profile:
            return {'support': [], 'resistance': [], 'poc': None}

        # POC is a key level
        poc = profile.poc_price

        # High volume nodes are S/R
        hvns = sorted(
            [l for l in profile.levels if l.total_volume > profile.total_volume / len(profile.levels) * 1.3],
            key=lambda x: -x.total_volume
        )[:5]

        # Current price approximation
        trades = self._trades.get(symbol, [])
        current_price = trades[-1].price if trades else poc

        support = [
            {'price': l.price, 'volume': l.total_volume, 'type': 'HVN'}
            for l in hvns if l.price < current_price
        ]

        resistance = [
            {'price': l.price, 'volume': l.total_volume, 'type': 'HVN'}
            for l in hvns if l.price > current_price
        ]

        # Add value area levels
        support.append({'price': profile.val_price, 'volume': 0, 'type': 'VAL'})
        resistance.append({'price': profile.vah_price, 'volume': 0, 'type': 'VAH'})

        return {
            'support': sorted(support, key=lambda x: -x['price']),
            'resistance': sorted(resistance, key=lambda x: x['price']),
            'poc': {'price': poc, 'type': 'POC'}
        }

    # ================================================================
    # STATISTICS
    # ================================================================

    def get_stats(self) -> Dict:
        """Get analyzer statistics."""
        return {
            'symbols_tracked': list(self._trades.keys()),
            'total_trades': sum(len(t) for t in self._trades.values()),
            'trades_by_symbol': {
                s: len(t) for s, t in self._trades.items()
            },
            'cumulative_delta': dict(self._cumulative_delta)
        }


# ================================================================
# FASTAPI INTEGRATION
# ================================================================

def create_order_flow_router(analyzer: OrderFlowAnalyzer):
    """
    Create FastAPI router with order flow endpoints.

    Args:
        analyzer: OrderFlowAnalyzer instance

    Returns:
        FastAPI APIRouter
    """
    from fastapi import APIRouter, HTTPException

    router = APIRouter(prefix="/api/orderflow", tags=["Order Flow"])

    @router.get("/{symbol}/profile")
    async def get_volume_profile(symbol: str, buckets: int = 50):
        """Get volume profile for a symbol."""
        profile = analyzer.get_volume_profile(symbol, price_buckets=buckets)
        if not profile:
            raise HTTPException(status_code=404, detail=f"No data for {symbol}")
        return profile.to_dict()

    @router.get("/{symbol}/analysis")
    async def get_analysis(symbol: str, lookback_minutes: int = 60):
        """Get order flow analysis."""
        analysis = analyzer.analyze(symbol, lookback_minutes)
        if not analysis:
            raise HTTPException(status_code=404, detail=f"No data for {symbol}")
        return analysis.to_dict()

    @router.get("/{symbol}/footprint")
    async def get_footprint(symbol: str, timeframe: str = "5m", bars: int = 20):
        """Get footprint chart data."""
        footprints = analyzer.get_footprint(symbol, timeframe, bars)
        return [fp.to_dict() for fp in footprints]

    @router.get("/{symbol}/levels")
    async def get_key_levels(symbol: str):
        """Get key support/resistance levels."""
        return analyzer.get_key_levels(symbol)

    @router.get("/{symbol}/delta")
    async def get_delta(symbol: str):
        """Get cumulative delta."""
        return {
            'symbol': symbol,
            'cumulative_delta': analyzer._cumulative_delta.get(symbol, 0)
        }

    @router.get("/stats")
    async def get_stats():
        """Get analyzer statistics."""
        return analyzer.get_stats()

    return router


# Global instance for easy access
_order_flow_analyzer: Optional[OrderFlowAnalyzer] = None


def get_order_flow_analyzer() -> OrderFlowAnalyzer:
    """Get the global order flow analyzer instance."""
    global _order_flow_analyzer
    if _order_flow_analyzer is None:
        _order_flow_analyzer = OrderFlowAnalyzer()
    return _order_flow_analyzer
