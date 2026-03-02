"""
Institutional Order Flow Detection

Identifies institutional vs retail trading activity through:
- Large order detection
- Iceberg order identification (repeated fills at same price)
- Volume spike detection
- Absorption level tracking
- Smart money flow classification
- Momentum divergence detection
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class InstitutionalTrade:
    """A trade classified as institutional."""

    timestamp: datetime
    symbol: str
    price: float
    size: float
    side: str
    classification: str  # 'institutional', 'retail', 'unknown'
    confidence: float  # 0-1
    indicators: List[str]  # Reasons for classification

    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "symbol": self.symbol,
            "price": self.price,
            "size": self.size,
            "side": self.side,
            "classification": self.classification,
            "confidence": self.confidence,
            "indicators": self.indicators,
        }


@dataclass
class FlowSignal:
    """A detected institutional flow signal."""

    symbol: str
    timestamp: datetime
    signal_type: str  # 'absorption', 'iceberg', 'volume_spike', 'smart_money'
    strength: str  # 'strong', 'moderate', 'weak'
    direction: str  # 'bullish', 'bearish', 'neutral'
    price_level: float
    volume: float
    details: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "signal_type": self.signal_type,
            "strength": self.strength,
            "direction": self.direction,
            "price_level": self.price_level,
            "volume": self.volume,
            "details": self.details,
        }


@dataclass
class SmartMoneyDirection:
    """Net smart money / institutional flow direction."""

    symbol: str
    timestamp: datetime
    direction: str  # 'bullish', 'bearish', 'neutral'
    institutional_buy_volume: float
    institutional_sell_volume: float
    net_flow: float
    confidence: float
    signal_count: int

    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "direction": self.direction,
            "institutional_buy_volume": self.institutional_buy_volume,
            "institutional_sell_volume": self.institutional_sell_volume,
            "net_flow": self.net_flow,
            "confidence": self.confidence,
            "signal_count": self.signal_count,
        }


class InstitutionalFlowDetector:
    """
    Institutional order flow detection system.

    Analyses trade flow to identify institutional vs retail activity.
    All trade data is provided via ``add_trade()`` and analyses are
    performed on-demand.

    Usage:
        detector = InstitutionalFlowDetector()

        # Feed trades
        for trade in trades:
            detector.add_trade('XAUUSD', trade['price'], trade['size'], trade['side'])

        # Analyse
        signals = detector.analyze_flow('XAUUSD')
        direction = detector.get_smart_money_direction('XAUUSD')
    """

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize detector.

        Args:
            config: Configuration options:
                - large_order_threshold: Size for institutional classification (default 200)
                - volume_spike_multiplier: Multiplier over avg to flag as spike (default 3.0)
                - iceberg_window_seconds: Window to detect repeated fills (default 60)
                - iceberg_min_fills: Minimum fills at same price for iceberg (default 3)
                - absorption_price_pct: Max price move % to classify as absorption (default 0.05)
                - max_trades: Max trades stored per symbol (default 50000)
        """
        self.config = config or {}
        self._large_threshold = self.config.get("large_order_threshold", 200)
        self._spike_multiplier = self.config.get("volume_spike_multiplier", 3.0)
        self._iceberg_window = self.config.get("iceberg_window_seconds", 60)
        self._iceberg_min_fills = self.config.get("iceberg_min_fills", 3)
        self._absorption_price_pct = self.config.get("absorption_price_pct", 0.05)
        self._max_trades = self.config.get("max_trades", 50000)

        # Trade storage: symbol -> list of (timestamp, price, size, side)
        self._trades: Dict[str, List] = defaultdict(list)

        logger.info("Institutional Flow Detector initialized")

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
    ) -> None:
        """Add a trade for analysis."""
        ts = timestamp or datetime.utcnow()
        self._trades[symbol].append((ts, price, size, side.lower()))
        # Trim buffer
        if len(self._trades[symbol]) > self._max_trades:
            self._trades[symbol] = self._trades[symbol][-self._max_trades :]

    # ================================================================
    # DETECTION METHODS
    # ================================================================

    def detect_large_orders(
        self,
        symbol: str,
        lookback_minutes: int = 60,
    ) -> List[InstitutionalTrade]:
        """
        Identify institutional-size trades.

        Args:
            symbol: Trading symbol
            lookback_minutes: Lookback window

        Returns:
            List of InstitutionalTrade objects above size threshold
        """
        cutoff = datetime.utcnow() - timedelta(minutes=lookback_minutes)
        results = []
        for ts, price, size, side in self._trades.get(symbol, []):
            if ts < cutoff:
                continue
            if size >= self._large_threshold:
                confidence = min(1.0, size / (self._large_threshold * 3))
                results.append(
                    InstitutionalTrade(
                        timestamp=ts,
                        symbol=symbol,
                        price=price,
                        size=size,
                        side=side,
                        classification="institutional",
                        confidence=round(confidence, 3),
                        indicators=["large_order_size"],
                    )
                )
        return results

    def detect_iceberg_orders(
        self,
        symbol: str,
        lookback_minutes: int = 60,
    ) -> List[FlowSignal]:
        """
        Find iceberg orders - repeated fills at (approximately) same price.

        Args:
            symbol: Trading symbol
            lookback_minutes: Lookback window

        Returns:
            List of FlowSignal objects for detected icebergs
        """
        cutoff = datetime.utcnow() - timedelta(minutes=lookback_minutes)
        trades = [
            (ts, price, size, side)
            for ts, price, size, side in self._trades.get(symbol, [])
            if ts >= cutoff
        ]

        if not trades:
            return []

        # Round prices to 2 dp to group near-same price levels
        price_groups: Dict[float, List] = defaultdict(list)
        for ts, price, size, side in trades:
            bucket = round(price, 2)
            price_groups[bucket].append((ts, price, size, side))

        signals = []
        for bucket_price, group in price_groups.items():
            if len(group) < self._iceberg_min_fills:
                continue

            # Check they occur within the iceberg window
            times = [t[0] for t in group]
            span = (max(times) - min(times)).total_seconds()
            if span > self._iceberg_window:
                continue

            total_vol = sum(t[2] for t in group)
            buy_vol = sum(t[2] for t in group if t[3] == "buy")
            sell_vol = total_vol - buy_vol
            direction = "bullish" if buy_vol >= sell_vol else "bearish"
            strength = (
                "strong"
                if len(group) >= self._iceberg_min_fills * 2
                else "moderate"
            )

            signals.append(
                FlowSignal(
                    symbol=symbol,
                    timestamp=min(times),
                    signal_type="iceberg",
                    strength=strength,
                    direction=direction,
                    price_level=bucket_price,
                    volume=total_vol,
                    details={
                        "fill_count": len(group),
                        "time_span_seconds": round(span, 1),
                        "buy_volume": buy_vol,
                        "sell_volume": sell_vol,
                    },
                )
            )

        return signals

    def detect_volume_spikes(
        self,
        symbol: str,
        lookback_minutes: int = 60,
        baseline_minutes: int = 30,
        window_seconds: int = 60,
    ) -> List[FlowSignal]:
        """
        Detect unusual volume spikes.

        Compares rolling per-minute volume windows to the baseline average.

        Args:
            symbol: Trading symbol
            lookback_minutes: Total lookback window
            baseline_minutes: Window used to compute baseline average
            window_seconds: Resolution of volume windows

        Returns:
            List of FlowSignal objects for detected volume spikes
        """
        now = datetime.utcnow()
        cutoff = now - timedelta(minutes=lookback_minutes)
        trades = [
            (ts, price, size, side)
            for ts, price, size, side in self._trades.get(symbol, [])
            if ts >= cutoff
        ]

        if len(trades) < 5:
            return []

        # Build volume windows
        windows: Dict[int, Dict] = defaultdict(
            lambda: {"volume": 0.0, "buy": 0.0, "sell": 0.0, "prices": []}
        )
        for ts, price, size, side in trades:
            epoch = int(ts.timestamp() // window_seconds)
            windows[epoch]["volume"] += size
            windows[epoch]["prices"].append(price)
            if side == "buy":
                windows[epoch]["buy"] += size
            else:
                windows[epoch]["sell"] += size

        if len(windows) < 2:
            return []

        volumes = [w["volume"] for w in windows.values()]
        avg_vol = sum(volumes) / len(volumes)
        if avg_vol == 0:
            return []

        signals = []
        for epoch, data in sorted(windows.items()):
            if data["volume"] >= avg_vol * self._spike_multiplier:
                ts = datetime.utcfromtimestamp(epoch * window_seconds)
                direction = (
                    "bullish"
                    if data["buy"] >= data["sell"]
                    else "bearish"
                )
                ratio = data["volume"] / avg_vol
                strength = (
                    "strong"
                    if ratio >= self._spike_multiplier * 2
                    else "moderate"
                )
                avg_price = (
                    sum(data["prices"]) / len(data["prices"])
                    if data["prices"]
                    else 0.0
                )
                signals.append(
                    FlowSignal(
                        symbol=symbol,
                        timestamp=ts,
                        signal_type="volume_spike",
                        strength=strength,
                        direction=direction,
                        price_level=round(avg_price, 5),
                        volume=data["volume"],
                        details={
                            "spike_ratio": round(ratio, 2),
                            "avg_volume": round(avg_vol, 2),
                            "buy_volume": data["buy"],
                            "sell_volume": data["sell"],
                        },
                    )
                )

        return signals

    def detect_absorption(
        self,
        symbol: str,
        lookback_minutes: int = 60,
        window_seconds: int = 30,
    ) -> List[FlowSignal]:
        """
        Detect absorption - high volume with low price movement.

        Args:
            symbol: Trading symbol
            lookback_minutes: Lookback window
            window_seconds: Time window to group trades

        Returns:
            List of FlowSignal objects for absorption levels
        """
        cutoff = datetime.utcnow() - timedelta(minutes=lookback_minutes)
        trades = [
            (ts, price, size, side)
            for ts, price, size, side in self._trades.get(symbol, [])
            if ts >= cutoff
        ]

        if len(trades) < 10:
            return []

        # Group trades into time windows
        windows: Dict[int, List] = defaultdict(list)
        for ts, price, size, side in trades:
            epoch = int(ts.timestamp() // window_seconds)
            windows[epoch].append((ts, price, size, side))

        # Compute average volume per window for context
        all_vols = [sum(t[2] for t in w) for w in windows.values()]
        avg_vol = sum(all_vols) / len(all_vols) if all_vols else 0.0

        signals = []
        for epoch, group in windows.items():
            if len(group) < 3:
                continue

            prices = [t[1] for t in group]
            avg_price = sum(prices) / len(prices)
            price_range = max(prices) - min(prices)
            price_range_pct = (
                price_range / avg_price * 100 if avg_price > 0 else 0.0
            )
            total_vol = sum(t[2] for t in group)

            # High volume, low price movement
            is_high_vol = total_vol >= avg_vol * 1.5 if avg_vol > 0 else False
            is_low_move = price_range_pct < self._absorption_price_pct

            if is_high_vol and is_low_move:
                buy_vol = sum(t[2] for t in group if t[3] == "buy")
                sell_vol = total_vol - buy_vol
                # Buyers absorbing selling = bullish; sellers absorbing buying = bearish
                direction = "bullish" if sell_vol > buy_vol else "bearish"
                strength = (
                    "strong"
                    if total_vol >= avg_vol * 3
                    else "moderate"
                )
                ts = datetime.utcfromtimestamp(epoch * window_seconds)

                signals.append(
                    FlowSignal(
                        symbol=symbol,
                        timestamp=ts,
                        signal_type="absorption",
                        strength=strength,
                        direction=direction,
                        price_level=round(avg_price, 5),
                        volume=total_vol,
                        details={
                            "price_range": round(price_range, 5),
                            "price_range_pct": round(price_range_pct, 4),
                            "buy_volume": buy_vol,
                            "sell_volume": sell_vol,
                            "volume_ratio": round(total_vol / avg_vol, 2)
                            if avg_vol > 0
                            else 0,
                        },
                    )
                )

        return signals

    def classify_trade(
        self,
        price: float,
        size: float,
        side: str,
        avg_trade_size: float = 0.0,
    ) -> InstitutionalTrade:
        """
        Classify a single trade as institutional or retail.

        Args:
            price: Trade price
            size: Trade size
            side: Trade side
            avg_trade_size: Average trade size for context

        Returns:
            InstitutionalTrade with classification
        """
        indicators: List[str] = []
        confidence = 0.0

        # Large order indicator
        if size >= self._large_threshold:
            indicators.append("large_order_size")
            confidence += 0.5

        # Above average size indicator
        if avg_trade_size > 0 and size >= avg_trade_size * 3:
            indicators.append("above_average_size")
            confidence += 0.3

        confidence = min(1.0, confidence)
        classification = (
            "institutional"
            if confidence >= 0.4
            else ("retail" if confidence < 0.2 else "unknown")
        )

        return InstitutionalTrade(
            timestamp=datetime.utcnow(),
            symbol="",
            price=price,
            size=size,
            side=side.lower(),
            classification=classification,
            confidence=round(confidence, 3),
            indicators=indicators,
        )

    def analyze_flow(
        self,
        symbol: str,
        lookback_minutes: int = 60,
    ) -> List[FlowSignal]:
        """
        Run complete flow analysis and return all detected signals.

        Args:
            symbol: Trading symbol
            lookback_minutes: Lookback window

        Returns:
            Combined list of all flow signals, sorted by timestamp
        """
        signals: List[FlowSignal] = []
        signals.extend(self.detect_iceberg_orders(symbol, lookback_minutes))
        signals.extend(self.detect_volume_spikes(symbol, lookback_minutes))
        signals.extend(self.detect_absorption(symbol, lookback_minutes))

        signals.sort(key=lambda s: s.timestamp)
        return signals

    def get_smart_money_direction(
        self,
        symbol: str,
        lookback_minutes: int = 60,
    ) -> Optional[SmartMoneyDirection]:
        """
        Determine the net institutional / smart-money flow direction.

        Args:
            symbol: Trading symbol
            lookback_minutes: Lookback window

        Returns:
            SmartMoneyDirection or None if insufficient data
        """
        institutional = self.detect_large_orders(symbol, lookback_minutes)
        if not institutional:
            return None

        signals = self.analyze_flow(symbol, lookback_minutes)
        bullish_signals = sum(1 for s in signals if s.direction == "bullish")
        bearish_signals = sum(1 for s in signals if s.direction == "bearish")

        buy_vol = sum(t.size for t in institutional if t.side == "buy")
        sell_vol = sum(t.size for t in institutional if t.side == "sell")
        total_vol = buy_vol + sell_vol
        net = (buy_vol - sell_vol) / total_vol if total_vol > 0 else 0.0

        if net > 0.1 or bullish_signals > bearish_signals:
            direction = "bullish"
        elif net < -0.1 or bearish_signals > bullish_signals:
            direction = "bearish"
        else:
            direction = "neutral"

        total_signals = len(signals)
        confidence = min(
            1.0,
            (len(institutional) / 10 + total_signals / 5) / 2,
        )

        return SmartMoneyDirection(
            symbol=symbol,
            timestamp=datetime.utcnow(),
            direction=direction,
            institutional_buy_volume=buy_vol,
            institutional_sell_volume=sell_vol,
            net_flow=round(net, 4),
            confidence=round(confidence, 3),
            signal_count=total_signals,
        )

    # ================================================================
    # UTILITY
    # ================================================================

    def get_stats(self) -> Dict:
        """Get detector statistics."""
        return {
            "symbols_tracked": len(self._trades),
            "symbols": list(self._trades.keys()),
            "trade_counts": {s: len(t) for s, t in self._trades.items()},
        }

    def clear_symbol(self, symbol: str) -> None:
        """Clear trade data for a symbol."""
        self._trades.pop(symbol, None)

    def clear_all(self) -> None:
        """Clear all trade data."""
        self._trades.clear()


# Global instance
_institutional_detector: Optional[InstitutionalFlowDetector] = None


def get_institutional_detector() -> InstitutionalFlowDetector:
    """Get the global institutional flow detector instance."""
    global _institutional_detector
    if _institutional_detector is None:
        _institutional_detector = InstitutionalFlowDetector()
    return _institutional_detector
