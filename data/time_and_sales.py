"""
Time & Sales Service

Real-time trade tape (time & sales) with:
- Circular buffer storage (configurable max trades, default 10,000)
- Aggressor side identification (BID/ASK)
- Historical trade queries with filtering
- Trade velocity calculation (trades per minute)
- Large trade alerts
- Trade statistics and analytics
- Thread-safe implementation
"""

import logging
import threading
from collections import deque
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ExecutedTrade:
    """Individual executed trade record from the tape."""

    timestamp: datetime
    symbol: str
    price: float
    size: float
    side: str  # 'buy' or 'sell' (aggressor side)
    trade_id: Optional[str] = None
    is_aggressive_buy: bool = False
    is_aggressive_sell: bool = False
    is_large_trade: bool = False

    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "symbol": self.symbol,
            "price": self.price,
            "size": self.size,
            "side": self.side,
            "trade_id": self.trade_id,
            "is_aggressive_buy": self.is_aggressive_buy,
            "is_aggressive_sell": self.is_aggressive_sell,
            "is_large_trade": self.is_large_trade,
        }


@dataclass
class TradeVelocity:
    """Trade velocity metrics over a rolling window."""

    symbol: str
    trades_per_minute: float
    volume_per_minute: float
    avg_trade_size: float
    buy_trades_pct: float
    sell_trades_pct: float

    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "trades_per_minute": self.trades_per_minute,
            "volume_per_minute": self.volume_per_minute,
            "avg_trade_size": self.avg_trade_size,
            "buy_trades_pct": self.buy_trades_pct,
            "sell_trades_pct": self.sell_trades_pct,
        }


@dataclass
class AggressorStats:
    """Buy vs sell aggressor statistics."""

    symbol: str
    total_trades: int
    buy_trades: int
    sell_trades: int
    buy_volume: float
    sell_volume: float
    buy_pct: float
    sell_pct: float
    net_aggression: float  # positive = buy-side dominant

    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "total_trades": self.total_trades,
            "buy_trades": self.buy_trades,
            "sell_trades": self.sell_trades,
            "buy_volume": self.buy_volume,
            "sell_volume": self.sell_volume,
            "buy_pct": self.buy_pct,
            "sell_pct": self.sell_pct,
            "net_aggression": self.net_aggression,
        }


class TimeAndSalesService:
    """
    Time & Sales (trade tape) service.

    Captures and analyzes real-time trade flow including aggressor side
    identification, velocity metrics, and large trade detection.

    Usage:
        service = TimeAndSalesService(config={'large_trade_threshold': 500})

        # Add a trade
        service.add_trade('XAUUSD', price=1950.0, size=100.0, side='buy')

        # Get recent trades
        trades = service.get_recent_trades('XAUUSD', n=50)

        # Get velocity
        velocity = service.get_trade_velocity('XAUUSD')
    """

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize Time & Sales service.

        Args:
            config: Configuration options:
                - max_trades: Maximum trades per symbol (default 10000)
                - large_trade_threshold: Size threshold for large trades (default 100)
                - velocity_window_minutes: Window for velocity calculation (default 5)
        """
        self.config = config or {}
        self._max_trades = self.config.get("max_trades", 10000)
        self._large_trade_threshold = self.config.get("large_trade_threshold", 100)
        self._velocity_window_minutes = self.config.get("velocity_window_minutes", 5)

        # Circular buffers per symbol
        self._trades: Dict[str, deque] = {}

        # Large trade alert callbacks
        self._large_trade_callbacks: List = []

        # Thread safety
        self._lock = threading.RLock()

        logger.info("Time & Sales Service initialized")

    # ================================================================
    # TRADE INGESTION
    # ================================================================

    def add_trade(
        self,
        symbol: str,
        price: float,
        size: float,
        side: str,
        timestamp: Optional[datetime] = None,
        trade_id: Optional[str] = None,
        ask_price: Optional[float] = None,
        bid_price: Optional[float] = None,
    ) -> ExecutedTrade:
        """
        Add a trade to the tape.

        Args:
            symbol: Trading symbol
            price: Execution price
            size: Trade size
            side: Aggressor side ('buy' or 'sell')
            timestamp: Trade timestamp (defaults to now)
            trade_id: Optional unique trade identifier
            ask_price: Current ask for aggressor determination
            bid_price: Current bid for aggressor determination

        Returns:
            ExecutedTrade object
        """
        side = side.lower()
        ts = timestamp or datetime.utcnow()

        # Determine aggressor flags
        is_aggressive_buy = False
        is_aggressive_sell = False
        if side == "buy":
            is_aggressive_buy = True
            # Confirm via ask price if provided
            if ask_price is not None:
                is_aggressive_buy = price >= ask_price
        elif side == "sell":
            is_aggressive_sell = True
            # Confirm via bid price if provided
            if bid_price is not None:
                is_aggressive_sell = price <= bid_price

        is_large = size >= self._large_trade_threshold

        trade = ExecutedTrade(
            timestamp=ts,
            symbol=symbol,
            price=price,
            size=size,
            side=side,
            trade_id=trade_id,
            is_aggressive_buy=is_aggressive_buy,
            is_aggressive_sell=is_aggressive_sell,
            is_large_trade=is_large,
        )

        with self._lock:
            if symbol not in self._trades:
                self._trades[symbol] = deque(maxlen=self._max_trades)
            self._trades[symbol].append(trade)

        # Fire large trade callbacks outside lock
        if is_large:
            for cb in self._large_trade_callbacks:
                try:
                    cb(trade)
                except Exception as exc:  # pragma: no cover
                    logger.error("Large trade callback error: %s", exc)

        logger.debug("Trade added: %s %s@%s x%s", symbol, side, price, size)
        return trade

    def register_large_trade_callback(self, callback) -> None:
        """Register a callback for large trade alerts."""
        self._large_trade_callbacks.append(callback)

    # ================================================================
    # TRADE RETRIEVAL
    # ================================================================

    def get_recent_trades(self, symbol: str, n: int = 100) -> List[ExecutedTrade]:
        """
        Get the most recent N trades for a symbol.

        Args:
            symbol: Trading symbol
            n: Number of trades to return

        Returns:
            List of ExecutedTrade objects (newest last)
        """
        with self._lock:
            buffer = self._trades.get(symbol)
            if buffer is None:
                return []
            trades = list(buffer)
        return trades[-n:]

    def get_trades_by_time(
        self,
        symbol: str,
        start_time: datetime,
        end_time: Optional[datetime] = None,
    ) -> List[ExecutedTrade]:
        """
        Filter trades by time range.

        Args:
            symbol: Trading symbol
            start_time: Start of time range (inclusive)
            end_time: End of time range (inclusive, defaults to now)

        Returns:
            List of matching ExecutedTrade objects
        """
        end = end_time or datetime.utcnow()
        with self._lock:
            buffer = self._trades.get(symbol)
            if buffer is None:
                return []
            trades = list(buffer)

        return [t for t in trades if start_time <= t.timestamp <= end]

    def get_large_trades(
        self,
        symbol: str,
        min_size: Optional[float] = None,
        lookback_minutes: int = 60,
    ) -> List[ExecutedTrade]:
        """
        Get large trades above a size threshold.

        Args:
            symbol: Trading symbol
            min_size: Minimum size threshold (defaults to configured threshold)
            lookback_minutes: How far back to look

        Returns:
            List of large ExecutedTrade objects
        """
        threshold = min_size if min_size is not None else self._large_trade_threshold
        start = datetime.utcnow() - timedelta(minutes=lookback_minutes)
        trades = self.get_trades_by_time(symbol, start_time=start)
        return [t for t in trades if t.size >= threshold]

    # ================================================================
    # ANALYTICS
    # ================================================================

    def get_trade_velocity(
        self,
        symbol: str,
        window_minutes: Optional[int] = None,
    ) -> Optional[TradeVelocity]:
        """
        Calculate trade velocity metrics over a rolling window.

        Args:
            symbol: Trading symbol
            window_minutes: Rolling window in minutes (defaults to configured value)

        Returns:
            TradeVelocity or None if insufficient data
        """
        window = window_minutes or self._velocity_window_minutes
        start = datetime.utcnow() - timedelta(minutes=window)
        trades = self.get_trades_by_time(symbol, start_time=start)

        if not trades:
            return None

        total = len(trades)
        total_volume = sum(t.size for t in trades)
        buy_count = sum(1 for t in trades if t.side == "buy")
        sell_count = total - buy_count

        trades_per_min = total / window
        volume_per_min = total_volume / window
        avg_size = total_volume / total if total > 0 else 0.0
        buy_pct = round(buy_count / total * 100, 2) if total > 0 else 0.0
        sell_pct = round(sell_count / total * 100, 2) if total > 0 else 0.0

        return TradeVelocity(
            symbol=symbol,
            trades_per_minute=round(trades_per_min, 4),
            volume_per_minute=round(volume_per_min, 4),
            avg_trade_size=round(avg_size, 4),
            buy_trades_pct=buy_pct,
            sell_trades_pct=sell_pct,
        )

    def get_aggressor_stats(
        self,
        symbol: str,
        lookback_minutes: int = 60,
    ) -> Optional[AggressorStats]:
        """
        Get buy vs sell aggressor statistics.

        Args:
            symbol: Trading symbol
            lookback_minutes: Lookback window in minutes

        Returns:
            AggressorStats or None if no data
        """
        start = datetime.utcnow() - timedelta(minutes=lookback_minutes)
        trades = self.get_trades_by_time(symbol, start_time=start)

        if not trades:
            return None

        total = len(trades)
        buy_trades = [t for t in trades if t.side == "buy"]
        sell_trades = [t for t in trades if t.side == "sell"]

        buy_vol = sum(t.size for t in buy_trades)
        sell_vol = sum(t.size for t in sell_trades)
        total_vol = buy_vol + sell_vol

        buy_pct = round(len(buy_trades) / total * 100, 2) if total > 0 else 0.0
        sell_pct = round(len(sell_trades) / total * 100, 2) if total > 0 else 0.0
        net = round((buy_vol - sell_vol) / total_vol, 4) if total_vol > 0 else 0.0

        return AggressorStats(
            symbol=symbol,
            total_trades=total,
            buy_trades=len(buy_trades),
            sell_trades=len(sell_trades),
            buy_volume=buy_vol,
            sell_volume=sell_vol,
            buy_pct=buy_pct,
            sell_pct=sell_pct,
            net_aggression=net,
        )

    def get_trade_histogram(
        self,
        symbol: str,
        bins: int = 20,
        lookback_minutes: int = 60,
    ) -> List[Dict]:
        """
        Get trade distribution by price level (histogram).

        Args:
            symbol: Trading symbol
            bins: Number of price bins
            lookback_minutes: Lookback window

        Returns:
            List of histogram buckets with price/volume info
        """
        start = datetime.utcnow() - timedelta(minutes=lookback_minutes)
        trades = self.get_trades_by_time(symbol, start_time=start)

        if not trades:
            return []

        prices = [t.price for t in trades]
        min_p, max_p = min(prices), max(prices)
        if min_p == max_p:
            return [
                {
                    "price_low": min_p,
                    "price_high": max_p,
                    "trade_count": len(trades),
                    "total_volume": sum(t.size for t in trades),
                    "buy_volume": sum(t.size for t in trades if t.side == "buy"),
                    "sell_volume": sum(t.size for t in trades if t.side == "sell"),
                }
            ]

        bucket_size = (max_p - min_p) / bins
        buckets: Dict[int, Dict] = {}

        for trade in trades:
            idx = min(int((trade.price - min_p) / bucket_size), bins - 1)
            if idx not in buckets:
                buckets[idx] = {
                    "price_low": round(min_p + idx * bucket_size, 5),
                    "price_high": round(min_p + (idx + 1) * bucket_size, 5),
                    "trade_count": 0,
                    "total_volume": 0.0,
                    "buy_volume": 0.0,
                    "sell_volume": 0.0,
                }
            b = buckets[idx]
            b["trade_count"] += 1
            b["total_volume"] += trade.size
            if trade.side == "buy":
                b["buy_volume"] += trade.size
            else:
                b["sell_volume"] += trade.size

        return [buckets[k] for k in sorted(buckets)]

    def get_trade_statistics(
        self,
        symbol: str,
        lookback_minutes: int = 60,
    ) -> Dict:
        """
        Get comprehensive trade statistics.

        Args:
            symbol: Trading symbol
            lookback_minutes: Lookback window

        Returns:
            Dict with trade statistics
        """
        start = datetime.utcnow() - timedelta(minutes=lookback_minutes)
        trades = self.get_trades_by_time(symbol, start_time=start)

        if not trades:
            return {"symbol": symbol, "trade_count": 0}

        sizes = [t.size for t in trades]
        prices = [t.price for t in trades]
        buy_vol = sum(t.size for t in trades if t.side == "buy")
        sell_vol = sum(t.size for t in trades if t.side == "sell")

        return {
            "symbol": symbol,
            "lookback_minutes": lookback_minutes,
            "trade_count": len(trades),
            "total_volume": sum(sizes),
            "buy_volume": buy_vol,
            "sell_volume": sell_vol,
            "avg_trade_size": round(sum(sizes) / len(sizes), 4),
            "min_trade_size": min(sizes),
            "max_trade_size": max(sizes),
            "price_high": max(prices),
            "price_low": min(prices),
            "price_range": round(max(prices) - min(prices), 5),
            "large_trade_count": sum(1 for t in trades if t.is_large_trade),
        }

    # ================================================================
    # UTILITY
    # ================================================================

    def get_symbols(self) -> List[str]:
        """Get list of symbols with trade data."""
        with self._lock:
            return list(self._trades.keys())

    def get_trade_count(self, symbol: str) -> int:
        """Get number of stored trades for a symbol."""
        with self._lock:
            buffer = self._trades.get(symbol)
            return len(buffer) if buffer else 0

    def clear_symbol(self, symbol: str) -> None:
        """Clear trade data for a symbol."""
        with self._lock:
            self._trades.pop(symbol, None)

    def clear_all(self) -> None:
        """Clear all trade data."""
        with self._lock:
            self._trades.clear()

    def get_stats(self) -> Dict:
        """Get service statistics."""
        with self._lock:
            return {
                "symbols_tracked": len(self._trades),
                "symbols": list(self._trades.keys()),
                "trade_counts": {s: len(b) for s, b in self._trades.items()},
                "max_trades_per_symbol": self._max_trades,
                "large_trade_threshold": self._large_trade_threshold,
            }


# ================================================================
# FASTAPI INTEGRATION
# ================================================================


def create_time_and_sales_router(service: TimeAndSalesService):
    """
    Create FastAPI router with Time & Sales endpoints.

    Args:
        service: TimeAndSalesService instance

    Returns:
        FastAPI APIRouter
    """
    from fastapi import APIRouter, HTTPException

    router = APIRouter(prefix="/api/timesales", tags=["Time & Sales"])

    @router.get("/{symbol}/recent")
    async def get_recent_trades(symbol: str, n: int = 100):
        """Get recent trades for a symbol."""
        trades = service.get_recent_trades(symbol, n=n)
        return [t.to_dict() for t in trades]

    @router.get("/{symbol}/large")
    async def get_large_trades(
        symbol: str, min_size: Optional[float] = None, lookback_minutes: int = 60
    ):
        """Get large trades for a symbol."""
        trades = service.get_large_trades(
            symbol, min_size=min_size, lookback_minutes=lookback_minutes
        )
        return [t.to_dict() for t in trades]

    @router.get("/{symbol}/velocity")
    async def get_velocity(symbol: str, window_minutes: int = 5):
        """Get trade velocity metrics."""
        velocity = service.get_trade_velocity(symbol, window_minutes=window_minutes)
        if not velocity:
            raise HTTPException(status_code=404, detail=f"No data for {symbol}")
        return velocity.to_dict()

    @router.get("/{symbol}/aggressor")
    async def get_aggressor_stats(symbol: str, lookback_minutes: int = 60):
        """Get aggressor statistics."""
        stats = service.get_aggressor_stats(symbol, lookback_minutes=lookback_minutes)
        if not stats:
            raise HTTPException(status_code=404, detail=f"No data for {symbol}")
        return stats.to_dict()

    @router.get("/{symbol}/histogram")
    async def get_histogram(
        symbol: str, bins: int = 20, lookback_minutes: int = 60
    ):
        """Get price/volume histogram."""
        return service.get_trade_histogram(
            symbol, bins=bins, lookback_minutes=lookback_minutes
        )

    @router.get("/{symbol}/statistics")
    async def get_statistics(symbol: str, lookback_minutes: int = 60):
        """Get trade statistics."""
        return service.get_trade_statistics(
            symbol, lookback_minutes=lookback_minutes
        )

    @router.get("/stats")
    async def get_service_stats():
        """Get service statistics."""
        return service.get_stats()

    return router


# Global instance
_time_and_sales_service: Optional[TimeAndSalesService] = None


def get_time_and_sales_service() -> TimeAndSalesService:
    """Get the global Time & Sales service instance."""
    global _time_and_sales_service
    if _time_and_sales_service is None:
        _time_and_sales_service = TimeAndSalesService()
    return _time_and_sales_service
