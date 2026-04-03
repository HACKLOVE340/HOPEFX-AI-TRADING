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

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

# ── Generic wrappers ──────────────────────────────────────────────────────────


class OKResponse(BaseModel):
    """Generic success acknowledgement."""

    ok: bool = True
    message: str | None = None


class ErrorResponse(BaseModel):
    """Standard error envelope (mirrors FastAPI HTTPException detail)."""

    detail: str


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
    trades: list[TradeOut]
    total: int
    page: int = Field(1)
    page_size: int = Field(50)


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
    history: list[RegimeHistoryEntry]
    total: int


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
    signals: list[SignalOut]
    count: int


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
