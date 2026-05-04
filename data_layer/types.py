# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
data_layer/types.py
===================
Canonical data types shared across the entire data layer.

Every tick, bar, news article, macro event, and microstructure snapshot
is represented by one of these immutable dataclasses. No dict passing
between modules — typed contracts only.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):  # Python 3.10 compat
        pass

# ── Enumerations ──────────────────────────────────────────────────────────────


class FeedSource(StrEnum):
    GOLDAPI = "goldapi"
    METALPRICEAPI = "metalpriceapi"
    METALS_API = "metals_api"
    METALS_DEV = "metals_dev"
    COMMODITY_API = "commodity_api"
    AGGREGATED = "aggregated"  # computed mid price from multiple real sources
    SYNTHETIC = AGGREGATED  # backwards-compat alias — use AGGREGATED
    REPLAY = "replay"  # historical replay engine


class TickQuality(StrEnum):
    GOOD = "good"
    STALE = "stale"
    SUSPECT = "suspect"
    REJECTED = "rejected"


class NewsSource(StrEnum):
    FINNHUB = "finnhub"
    FMP = "fmp"
    NEWSDATA = "newsdata"
    ALPHA_VANTAGE = "alpha_vantage"
    NEWSAPI = "newsapi"
    NEWSAPI_AI = "newsapi_ai"


class MacroImpact(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


class Direction(StrEnum):
    LONG = "long"
    SHORT = "short"
    NEUTRAL = "neutral"


# ── Core tick ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GoldTick:
    """
    Canonical gold price tick.

    All prices in USD per troy ounce.
    lineage_id links back to DataLineage record.

    Note: spread is computed as ask - bid when not explicitly provided.
    Because this is a frozen dataclass, spread must be passed explicitly
    or computed before construction. Use GoldTick.make() for auto-spread.
    """

    symbol: str  # always "XAU_USD"
    timestamp: datetime  # UTC, microsecond precision
    bid: float
    ask: float
    mid: float
    source: FeedSource
    quality: TickQuality = TickQuality.GOOD
    confidence: float = 1.0  # 0-1, multi-source weighted
    spread: float = 0.0
    lineage_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    raw: dict[str, Any] | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        # Auto-compute spread when not explicitly set (spread == 0 but ask > bid)
        if self.spread == 0.0 and self.ask > self.bid:
            object.__setattr__(self, "spread", round(self.ask - self.bid, 6))

    def is_valid(self) -> bool:
        return (
            self.quality not in (TickQuality.REJECTED, TickQuality.STALE)
            and self.mid > 0
            and self.bid > 0
            and self.ask >= self.bid
        )


# ── OHLCV bar ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class OHLCVBar:
    symbol: str
    timeframe: str  # "1m", "5m", "1h", "4h", "1d"
    open_time: datetime  # UTC bar open
    close_time: datetime  # UTC bar close
    open: float
    high: float
    low: float
    close: float
    volume: float
    tick_count: int = 0
    source: FeedSource = FeedSource.AGGREGATED
    lineage_id: str = field(default_factory=lambda: str(uuid.uuid4()))


# ── Microstructure snapshot ───────────────────────────────────────────────────


@dataclass
class MicrostructureSnapshot:
    symbol: str
    timestamp: datetime
    bid: float
    ask: float
    spread: float
    spread_pct: float
    volume_delta: float  # buy_vol - sell_vol (signed)
    cumulative_delta: float  # running sum of volume_delta
    buy_pressure: float  # 0-1
    sell_pressure: float  # 0-1
    order_flow_imbalance: float  # (buy_vol - sell_vol) / (buy_vol + sell_vol)
    trade_pressure: float  # EMA of signed trade flow
    bid_depth: float = 0.0
    ask_depth: float = 0.0
    depth_imbalance: float = 0.0
    vwap: float = 0.0
    tick_count: int = 0

    @property
    def mid(self) -> float:
        """Mid price computed from bid/ask."""
        if self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / 2.0
        return self.vwap


# ── News article ──────────────────────────────────────────────────────────────


@dataclass
class NewsArticle:
    article_id: str
    source: NewsSource
    headline: str
    summary: str
    url: str
    published_at: datetime
    fetched_at: datetime
    sentiment_score: float = 0.0  # -1 (bearish) to +1 (bullish) for gold
    sentiment_label: str = "neutral"
    gold_relevance: float = 0.0  # 0-1
    impact_score: float = 0.0  # 0-1 expected price impact
    keywords: list[str] = field(default_factory=list)
    lineage_id: str = field(default_factory=lambda: str(uuid.uuid4()))


# ── Macro event ───────────────────────────────────────────────────────────────


@dataclass
class MacroEvent:
    event_id: str
    name: str
    country: str
    currency: str
    scheduled_at: datetime
    actual: float | None
    forecast: float | None
    previous: float | None
    impact: MacroImpact
    gold_impact_score: float = 0.0  # historical gold reaction score
    surprise_pct: float | None = None  # (actual - forecast) / |forecast|
    lineage_id: str = field(default_factory=lambda: str(uuid.uuid4()))


# ── Feed health ───────────────────────────────────────────────────────────────


@dataclass
class FeedHealth:
    source: FeedSource
    is_alive: bool
    last_tick_at: datetime | None
    latency_ms: float
    error_rate: float  # rolling 1-min error rate
    tick_rate: float  # ticks/second
    confidence: float  # 0-1 quality score
    last_error: str | None = None


# ── Data quality report ───────────────────────────────────────────────────────


@dataclass
class QualityReport:
    timestamp: datetime
    symbol: str
    ticks_received: int
    ticks_accepted: int
    ticks_rejected: int
    stale_count: int
    jump_count: int
    anomaly_count: int
    active_sources: list[str]
    primary_source: str
    consensus_price: float
    price_spread_across_sources: float  # max - min across live feeds


# ── Sentiment signal ──────────────────────────────────────────────────────────


@dataclass
class SentimentSignal:
    """
    Aggregated sentiment signal produced by NewsSentimentEngine.

    score:    EMA-smoothed composite sentiment (-1 bearish → +1 bullish)
    momentum: rate of change of score over the last window
    label:    "bullish" | "bearish" | "neutral"
    article_count_1h: articles processed in the last hour
    bullish_ratio:    fraction of articles with positive sentiment
    regime:   "risk_on" | "risk_off" | "neutral" — macro sentiment regime
    """

    timestamp: datetime
    symbol: str
    score: float          # -1.0 to +1.0
    momentum: float       # score delta over last N articles
    label: str            # "bullish" | "bearish" | "neutral"
    article_count_1h: int
    bullish_ratio: float  # 0.0 to 1.0
    regime: str = "neutral"  # "risk_on" | "risk_off" | "neutral"
    source_breakdown: dict[str, float] = field(default_factory=dict)
    lineage_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    @property
    def is_bullish(self) -> bool:
        return self.score > 0.1

    @property
    def is_bearish(self) -> bool:
        return self.score < -0.1


# ── Volume delta bar ──────────────────────────────────────────────────────────


@dataclass
class VolumeDeltaBar:
    """
    Aggregated volume delta for a time bucket.

    Used by the chart-bot WebSocket to stream real-time order flow imbalance.

    buy_volume:  estimated buy-side volume (Lee-Ready classified)
    sell_volume: estimated sell-side volume
    delta:       buy_volume - sell_volume (positive = net buying)
    cumulative_delta: running sum of delta since session open
    """

    symbol: str
    bar_open: datetime    # UTC bar open time
    bar_close: datetime   # UTC bar close time
    timeframe_s: int      # bar duration in seconds
    open: float
    high: float
    low: float
    close: float
    volume: float
    buy_volume: float
    sell_volume: float
    delta: float          # buy_volume - sell_volume
    cumulative_delta: float
    tick_count: int = 0
    source: FeedSource = FeedSource.AGGREGATED
    lineage_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    @property
    def delta_pct(self) -> float:
        """Delta as a percentage of total volume (0 if volume is zero)."""
        if self.volume == 0:
            return 0.0
        return self.delta / self.volume

    @property
    def buy_pressure(self) -> float:
        """Buy volume fraction (0–1)."""
        total = self.buy_volume + self.sell_volume
        return self.buy_volume / total if total > 0 else 0.5


# ── Order book snapshot ───────────────────────────────────────────────────────


@dataclass
class OrderBookLevel:
    """A single price level in the order book."""

    price: float
    size: float
    order_count: int = 0


@dataclass
class OrderBookSnapshot:
    """
    Level-2 order book snapshot at a point in time.

    bids: sorted descending by price (best bid first)
    asks: sorted ascending by price (best ask first)
    """

    symbol: str
    timestamp: datetime
    bids: list[OrderBookLevel] = field(default_factory=list)
    asks: list[OrderBookLevel] = field(default_factory=list)
    sequence: int = 0       # exchange sequence number for gap detection
    source: str = ""
    lineage_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    @property
    def best_bid(self) -> float:
        return self.bids[0].price if self.bids else 0.0

    @property
    def best_ask(self) -> float:
        return self.asks[0].price if self.asks else 0.0

    @property
    def mid(self) -> float:
        if self.best_bid and self.best_ask:
            return (self.best_bid + self.best_ask) / 2.0
        return 0.0

    @property
    def spread(self) -> float:
        return self.best_ask - self.best_bid if self.best_bid and self.best_ask else 0.0

    @property
    def bid_depth(self) -> float:
        """Total bid-side size across all levels."""
        return sum(lvl.size for lvl in self.bids)

    @property
    def ask_depth(self) -> float:
        """Total ask-side size across all levels."""
        return sum(lvl.size for lvl in self.asks)

    @property
    def depth_imbalance(self) -> float:
        """(bid_depth - ask_depth) / (bid_depth + ask_depth); 0 if empty."""
        total = self.bid_depth + self.ask_depth
        if total == 0:
            return 0.0
        return (self.bid_depth - self.ask_depth) / total


# ── Data lineage record ───────────────────────────────────────────────────────


@dataclass
class DataLineageRecord:
    """
    Immutable audit record linking a processed data point back to its origin.

    Stored in DataLineageStore (SQLite WAL) for regulatory compliance and
    data quality investigations.

    lineage_id:   UUID linking this record to the GoldTick / NewsArticle / etc.
    parent_id:    lineage_id of the upstream record (None for raw ingestion)
    data_type:    "tick" | "ohlcv" | "news" | "macro" | "signal" | "prediction"
    source:       feed source name (e.g. "goldapi", "finnhub")
    operation:    transformation applied (e.g. "normalize", "quality_check", "aggregate")
    checksum:     SHA-256 of the serialised payload for tamper detection
    """

    lineage_id: str
    timestamp: datetime
    data_type: str        # "tick" | "ohlcv" | "news" | "macro" | "signal" | "prediction"
    source: str
    operation: str        # "ingest" | "normalize" | "quality_check" | "aggregate" | "publish"
    symbol: str = ""
    parent_id: str | None = None
    checksum: str = ""    # SHA-256 hex digest of payload
    payload_size_bytes: int = 0
    tags: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "lineage_id": self.lineage_id,
            "timestamp": self.timestamp.isoformat(),
            "data_type": self.data_type,
            "source": self.source,
            "operation": self.operation,
            "symbol": self.symbol,
            "parent_id": self.parent_id,
            "checksum": self.checksum,
            "payload_size_bytes": self.payload_size_bytes,
            "tags": self.tags,
        }

    @classmethod
    def for_tick(
        cls,
        tick: "GoldTick",
        operation: str = "ingest",
        parent_id: str | None = None,
    ) -> "DataLineageRecord":
        """Convenience factory for creating a lineage record from a GoldTick."""
        import hashlib
        import json as _json

        payload = f"{tick.symbol}:{tick.timestamp.isoformat()}:{tick.bid}:{tick.ask}"
        checksum = hashlib.sha256(payload.encode()).hexdigest()
        return cls(
            lineage_id=tick.lineage_id,
            timestamp=tick.timestamp,
            data_type="tick",
            source=str(tick.source),
            operation=operation,
            symbol=tick.symbol,
            parent_id=parent_id,
            checksum=checksum,
            payload_size_bytes=len(payload.encode()),
        )
