# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
api/schemas.py
==============
Shared Pydantic response models used across multiple API routers.

Centralising these here means:
- OpenAPI /docs shows accurate schemas for all 200 routes
- Integration partners can generate typed clients from the spec
- Response shape is enforced at the serialisation layer, not just docs

Import pattern:
    from api.schemas import AccountResponse, TradeResponse, RegimeResponse
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field, model_validator

# ── Generic wrappers ──────────────────────────────────────────────────────────


class OKResponse(BaseModel):
    """Generic success acknowledgement."""

    ok: bool = True
    message: str | None = None


class ErrorResponse(BaseModel):
    """Standard error envelope (mirrors FastAPI HTTPException detail)."""

    detail: str


# ── Pagination envelope ───────────────────────────────────────────────────────

T = TypeVar("T")


class PaginationMeta(BaseModel):
    """
    Pagination metadata included in every paginated list response.

    Supports both offset/page-based and cursor-based pagination:
    - Offset: use ``page`` + ``page_size`` + ``total`` + ``total_pages``.
    - Cursor: use ``next_cursor`` / ``prev_cursor`` (opaque strings).

    ``has_next`` and ``has_prev`` are always set regardless of pagination style.
    """

    total: int = Field(..., description="Total number of items across all pages")
    page: int = Field(1, ge=1, description="Current page number (1-based)")
    page_size: int = Field(50, ge=1, le=1000, description="Items per page")
    total_pages: int = Field(0, description="Total number of pages")
    has_next: bool = Field(False, description="Whether a next page exists")
    has_prev: bool = Field(False, description="Whether a previous page exists")
    next_cursor: str | None = Field(None, description="Opaque cursor for the next page")
    prev_cursor: str | None = Field(None, description="Opaque cursor for the previous page")

    @model_validator(mode="after")
    def _compute_derived(self) -> PaginationMeta:
        """Compute total_pages, has_next, has_prev from total/page/page_size."""
        if self.page_size > 0:
            self.total_pages = max(1, math.ceil(self.total / self.page_size))
        self.has_next = self.page < self.total_pages or self.next_cursor is not None
        self.has_prev = self.page > 1 or self.prev_cursor is not None
        return self


class PaginatedResponse(BaseModel, Generic[T]):
    """
    Generic paginated list envelope.

    Usage::

        @router.get("/trades", response_model=PaginatedResponse[TradeOut])
        def list_trades(page: int = 1, page_size: int = 50) -> PaginatedResponse[TradeOut]:
            items, total = trade_repo.list(page=page, page_size=page_size)
            return PaginatedResponse.build(items=items, total=total, page=page, page_size=page_size)
    """

    items: list[T]
    pagination: PaginationMeta

    @classmethod
    def build(
        cls,
        items: list[T],
        total: int,
        page: int = 1,
        page_size: int = 50,
        next_cursor: str | None = None,
        prev_cursor: str | None = None,
    ) -> PaginatedResponse[T]:
        """Convenience constructor that computes all pagination metadata."""
        meta = PaginationMeta(
            total=total,
            page=page,
            page_size=page_size,
            next_cursor=next_cursor,
            prev_cursor=prev_cursor,
        )
        return cls(items=items, pagination=meta)


# ── Account ───────────────────────────────────────────────────────────────────


class AccountResponse(BaseModel):
    """Broker account snapshot."""

    balance: float = Field(..., description="Cash balance in account currency")
    equity: float = Field(..., description="Balance + unrealised P&L")
    margin_used: float = Field(0.0, description="Margin currently in use")
    free_margin: float = Field(0.0, description="Available margin")
    unrealised_pnl: float = Field(0.0)
    currency: str = Field("USD")
    leverage: float = Field(1.0)
    broker: str = Field("paper")


# ── Positions ─────────────────────────────────────────────────────────────────


class PositionOut(BaseModel):
    """Open position summary."""

    id: str
    symbol: str
    side: str = Field(..., description="'buy' or 'sell'")
    quantity: float
    entry_price: float
    current_price: float = Field(0.0)
    unrealised_pnl: float = Field(0.0)
    stop_loss: float | None = None
    take_profit: float | None = None
    opened_at: datetime | None = None


# ── Trades ────────────────────────────────────────────────────────────────────


class TradeOut(BaseModel):
    """Closed trade record."""

    id: str
    symbol: str
    side: str
    quantity: float
    entry_price: float
    exit_price: float
    net_pnl: float
    commission: float = Field(0.0)
    opened_at: datetime | None = None
    closed_at: datetime | None = None
    result: str = Field(..., description="'win' or 'loss'")


class TradeListResponse(BaseModel):
    """
    Paginated trade list response.

    Wraps the generic PaginatedResponse envelope for backward compatibility
    with existing API consumers that expect a ``trades`` key.
    """

    trades: list[TradeOut]
    pagination: PaginationMeta

    @classmethod
    def build(
        cls,
        trades: list[TradeOut],
        total: int,
        page: int = 1,
        page_size: int = 50,
    ) -> TradeListResponse:
        meta = PaginationMeta(total=total, page=page, page_size=page_size)
        return cls(trades=trades, pagination=meta)


# ── Risk metrics ──────────────────────────────────────────────────────────────


class RiskMetricsResponse(BaseModel):
    """Current risk state snapshot."""

    can_trade: bool
    daily_pnl: float = Field(0.0)
    daily_pnl_pct: float = Field(0.0)
    drawdown_pct: float = Field(0.0)
    max_drawdown_pct: float = Field(0.0)
    open_positions: int = Field(0)
    risk_level: str = Field("low", description="low | medium | high | critical")
    halt_active: bool = Field(False)
    message: str | None = None


# ── Performance ───────────────────────────────────────────────────────────────


class PerformanceSummaryResponse(BaseModel):
    """Aggregated performance statistics."""

    total_trades: int = Field(0)
    win_rate_pct: float = Field(0.0)
    profit_factor: float = Field(0.0)
    total_pnl: float = Field(0.0)
    total_return_pct: float = Field(0.0)
    sharpe_ratio: float = Field(0.0)
    max_drawdown_pct: float = Field(0.0)
    avg_win: float = Field(0.0)
    avg_loss: float = Field(0.0)
    period_start: datetime | None = None
    period_end: datetime | None = None


# ── Market regime ─────────────────────────────────────────────────────────────


class RegimeResponse(BaseModel):
    """Current market regime classification."""

    regime: str = Field(..., description="trending_bull | trending_bear | ranging | volatile")
    confidence: float = Field(..., ge=0.0, le=1.0)
    active_strategy: str
    hurst_exponent: float | None = None
    adx: float | None = None
    timestamp: datetime | None = None


class RegimeHistoryEntry(BaseModel):
    regime: str
    strategy: str
    started_at: datetime
    ended_at: datetime | None = None
    duration_bars: int = Field(0)


class RegimeHistoryResponse(BaseModel):
    """Paginated regime history response."""

    history: list[RegimeHistoryEntry]
    pagination: PaginationMeta

    @classmethod
    def build(
        cls,
        history: list[RegimeHistoryEntry],
        total: int,
        page: int = 1,
        page_size: int = 50,
    ) -> RegimeHistoryResponse:
        meta = PaginationMeta(total=total, page=page, page_size=page_size)
        return cls(history=history, pagination=meta)


# ── Admin ─────────────────────────────────────────────────────────────────────


class SystemStatusResponse(BaseModel):
    """High-level system health."""

    status: str = Field(..., description="running | degraded | halted")
    uptime_seconds: float = Field(0.0)
    broker_connected: bool = Field(False)
    broker_type: str = Field("paper")
    active_strategies: int = Field(0)
    open_positions: int = Field(0)
    kill_switch_active: bool = Field(False)
    environment: str = Field("development")
    version: str = Field("unknown")


class SystemMetricsResponse(BaseModel):
    """Prometheus-style system metrics snapshot."""

    cpu_pct: float = Field(0.0)
    memory_pct: float = Field(0.0)
    disk_pct: float = Field(0.0)
    requests_per_minute: float = Field(0.0)
    avg_latency_ms: float = Field(0.0)
    error_rate_pct: float = Field(0.0)
    active_websockets: int = Field(0)
    cache_hit_rate_pct: float = Field(0.0)
    extra: dict[str, Any] = Field(default_factory=dict)


# ── Signals ───────────────────────────────────────────────────────────────────


class SignalOut(BaseModel):
    """A single trading signal."""

    id: str
    symbol: str
    direction: str = Field(..., description="'buy' or 'sell'")
    confidence: float = Field(..., ge=0.0, le=1.0)
    entry_price: float
    stop_loss: float | None = None
    take_profit: float | None = None
    strategy: str
    timeframe: str = Field("1h")
    generated_at: datetime | None = None
    expires_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SignalListResponse(BaseModel):
    """Paginated signal list response."""

    signals: list[SignalOut]
    pagination: PaginationMeta

    @classmethod
    def build(
        cls,
        signals: list[SignalOut],
        total: int,
        page: int = 1,
        page_size: int = 50,
    ) -> SignalListResponse:
        meta = PaginationMeta(total=total, page=page, page_size=page_size)
        return cls(signals=signals, pagination=meta)


# ── Broker ────────────────────────────────────────────────────────────────────


class BrokerStatusResponse(BaseModel):
    """Live broker connection status."""

    connected: bool
    broker_type: str
    account_id: str | None = None
    practice_mode: bool = Field(True)
    latency_ms: float | None = None
    last_heartbeat: datetime | None = None
    error: str | None = None
