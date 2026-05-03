# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
database/repositories/position_repository.py
=============================================
Typed async repository for the Position model.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Sequence

from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Position
from .base import AsyncRepository

logger = logging.getLogger(__name__)

UTC = timezone.utc


class PositionRepository(AsyncRepository[Position]):
    """Async repository for Position records."""

    model = Position

    async def get_open_positions(
        self,
        session: AsyncSession,
        user_id: str | None = None,
        symbol: str | None = None,
    ) -> Sequence[Position]:
        """Return all open positions, optionally filtered."""
        conditions = [Position.status == "open"]
        if user_id:
            conditions.append(Position.user_id == user_id)
        if symbol:
            conditions.append(Position.symbol == symbol)
        stmt = (
            select(Position)
            .where(and_(*conditions))
            .order_by(desc(Position.opened_at))
        )
        result = await session.execute(stmt)
        return result.scalars().all()

    async def get_by_symbol_and_user(
        self,
        session: AsyncSession,
        symbol: str,
        user_id: str,
    ) -> Position | None:
        """Return the open position for a (symbol, user) pair."""
        stmt = select(Position).where(
            and_(
                Position.symbol == symbol,
                Position.user_id == user_id,
                Position.status == "open",
            )
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_current_price(
        self,
        session: AsyncSession,
        position_id: str,
        current_price: float,
        unrealized_pnl: float | None = None,
    ) -> Position | None:
        """Update the mark-to-market price and unrealized PnL."""
        position = await self.get_by_id(session, position_id)
        if position is None:
            return None
        position.current_price = current_price
        if unrealized_pnl is not None:
            position.unrealized_pnl = unrealized_pnl
        # Recompute market value
        qty = position.quantity or position.size or 0.0
        position.market_value = current_price * qty
        session.add(position)
        await session.flush()
        return position

    async def close_position(
        self,
        session: AsyncSession,
        position_id: str,
        realized_pnl: float,
        closed_at: datetime | None = None,
    ) -> Position | None:
        """Mark a position as closed."""
        position = await self.get_by_id(session, position_id)
        if position is None:
            logger.warning("close_position: id=%s not found", position_id)
            return None
        position.status = "closed"
        position.realized_pnl = (position.realized_pnl or 0.0) + realized_pnl
        position.closed_at = closed_at or datetime.now(UTC)
        session.add(position)
        await session.flush()
        await session.refresh(position)
        return position

    async def get_portfolio_summary(
        self,
        session: AsyncSession,
        user_id: str,
    ) -> dict[str, Any]:
        """Return aggregate portfolio stats for a user's open positions."""
        from sqlalchemy import func as sa_func

        stmt = select(
            sa_func.count(Position.id).label("position_count"),
            sa_func.sum(Position.market_value).label("total_market_value"),
            sa_func.sum(Position.unrealized_pnl).label("total_unrealized_pnl"),
            sa_func.sum(Position.realized_pnl).label("total_realized_pnl"),
        ).where(
            and_(Position.user_id == user_id, Position.status == "open")
        )
        result = await session.execute(stmt)
        row = result.one()
        return {
            "position_count": row.position_count or 0,
            "total_market_value": float(row.total_market_value or 0),
            "total_unrealized_pnl": float(row.total_unrealized_pnl or 0),
            "total_realized_pnl": float(row.total_realized_pnl or 0),
        }
