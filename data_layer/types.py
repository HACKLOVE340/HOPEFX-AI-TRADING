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
