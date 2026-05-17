# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
database/repositories/trade_repository.py
==========================================
Typed async repository for the Trade model.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Sequence

from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.models import Trade, TradeStatus
from .base import AsyncRepository

logger = logging.getLogger(__name__)


class TradeRepository(AsyncRepository[Trade]):
    """Async repository for Trade records."""

    model = Trade

    async def get_by_trade_id(self, session: AsyncSession, trade_id: str) -> Trade | None:
        """Return a trade by its external trade_id."""
        stmt = select(Trade).where(Trade.trade_id == trade_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_client_order_id(self, session: AsyncSession, client_order_id: str) -> Trade | None:
        """Return a trade by its idempotency client_order_id."""
        stmt = select(Trade).where(Trade.client_order_id == client_order_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_open_trades(
        self,
        session: AsyncSession,
        symbol: str | None = None,
        user_id: str | None = None,
        limit: int = 100,
    ) -> Sequence[Trade]:
        """Return open trades, optionally filtered by symbol and user."""
        conditions = [Trade.is_open == True]
        if symbol:
            conditions.append(Trade.symbol == symbol)
        if user_id:
            conditions.append(Trade.user_id == user_id)
        stmt = (
            select(Trade)
            .options(selectinload(Trade.account))
            .where(and_(*conditions))
            .order_by(desc(Trade.entry_time))
            .limit(limit)
        )
        result = await session.execute(stmt)
        return result.scalars().all()

    async def get_by_symbol(
        self,
        session: AsyncSession,
        symbol: str,
        status: TradeStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Trade]:
        """Return trades for a symbol, optionally filtered by status."""
        conditions = [Trade.symbol == symbol]
        if status:
            conditions.append(Trade.status == status)
        stmt = (
            select(Trade)
            .options(selectinload(Trade.account))
            .where(and_(*conditions))
            .order_by(desc(Trade.entry_time))
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(stmt)
        return result.scalars().all()

    async def get_by_user(
        self,
        session: AsyncSession,
        user_id: str,
        since: datetime | None = None,
        limit: int = 200,
    ) -> Sequence[Trade]:
        """Return trades for a user, optionally since a datetime."""
        conditions = [Trade.user_id == user_id]
        if since:
            conditions.append(Trade.entry_time >= since)
        stmt = (
            select(Trade)
            .options(selectinload(Trade.account))
            .where(and_(*conditions))
            .order_by(desc(Trade.entry_time))
            .limit(limit)
        )
        result = await session.execute(stmt)
        return result.scalars().all()

    async def get_by_date_range(
        self,
        session: AsyncSession,
        start: datetime,
        end: datetime,
        symbol: str | None = None,
    ) -> Sequence[Trade]:
        """Return trades within a date range."""
        conditions = [Trade.entry_time >= start, Trade.entry_time <= end]
        if symbol:
            conditions.append(Trade.symbol == symbol)
        stmt = select(Trade).options(selectinload(Trade.account)).where(and_(*conditions)).order_by(Trade.entry_time)
        result = await session.execute(stmt)
        return result.scalars().all()

    async def close_trade(
        self,
        session: AsyncSession,
        trade_id: str,
        exit_price: float,
        exit_time: datetime,
        realized_pnl: float,
        exit_quantity: float | None = None,
    ) -> Trade | None:
        """Mark a trade as closed and record exit details."""
        trade = await self.get_by_trade_id(session, trade_id)
        if trade is None:
            logger.warning("close_trade: trade_id=%s not found", trade_id)
            return None
        trade.exit_price = exit_price
        trade.exit_time = exit_time
        trade.realized_pnl = realized_pnl
        # Accumulate total_pnl rather than overwriting it — partial closes
        # may have already recorded P&L in previous calls.
        trade.total_pnl = (trade.total_pnl or 0.0) + realized_pnl
        trade.is_open = False
        trade.status = TradeStatus.CLOSED
        if exit_quantity is not None:
            trade.exit_quantity = exit_quantity
        session.add(trade)
        await session.flush()
        await session.refresh(trade)
        return trade

    async def update_unrealized_pnl(
        self,
        session: AsyncSession,
        trade_id: str,
        unrealized_pnl: float,
        current_price: float | None = None,
    ) -> Trade | None:
        """Update the unrealized PnL for an open trade."""
        trade = await self.get_by_trade_id(session, trade_id)
        if trade is None:
            return None
        trade.unrealized_pnl = unrealized_pnl
        if current_price is not None:
            trade.exit_price = current_price  # track last known price
        session.add(trade)
        await session.flush()
        return trade

    async def get_by_user_and_date_range(
        self,
        session: AsyncSession,
        user_id: str,
        start: datetime,
        end: datetime,
        symbol: str | None = None,
        status: TradeStatus | None = None,
        limit: int = 500,
    ) -> Sequence[Trade]:
        """Return trades for a user within a date range, optionally filtered."""
        conditions = [
            Trade.user_id == user_id,
            Trade.entry_time >= start,
            Trade.entry_time <= end,
        ]
        if symbol:
            conditions.append(Trade.symbol == symbol)
        if status:
            conditions.append(Trade.status == status)
        stmt = (
            select(Trade)
            .options(selectinload(Trade.account))
            .where(and_(*conditions))
            .order_by(Trade.entry_time)
            .limit(limit)
        )
        result = await session.execute(stmt)
        return result.scalars().all()

    async def get_pnl_summary(
        self,
        session: AsyncSession,
        user_id: str | None = None,
        symbol: str | None = None,
    ) -> dict[str, Any]:
        """Return aggregate PnL stats for closed trades."""
        from sqlalchemy import func as sa_func

        conditions = [Trade.status == TradeStatus.CLOSED]
        if user_id:
            conditions.append(Trade.user_id == user_id)
        if symbol:
            conditions.append(Trade.symbol == symbol)

        stmt = select(
            sa_func.count(Trade.id).label("trade_count"),
            sa_func.sum(Trade.realized_pnl).label("total_pnl"),
            sa_func.avg(Trade.realized_pnl).label("avg_pnl"),
            sa_func.max(Trade.realized_pnl).label("max_pnl"),
            sa_func.min(Trade.realized_pnl).label("min_pnl"),
        ).where(and_(*conditions))

        result = await session.execute(stmt)
        row = result.one()
        return {
            "trade_count": row.trade_count or 0,
            "total_pnl": float(row.total_pnl or 0),
            "avg_pnl": float(row.avg_pnl or 0),
            "max_pnl": float(row.max_pnl or 0),
            "min_pnl": float(row.min_pnl or 0),
        }
