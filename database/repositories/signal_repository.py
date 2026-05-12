# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
database/repositories/signal_repository.py
===========================================
Typed async repository for the Signal model.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Sequence

from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Signal, SignalSource
from .base import AsyncRepository

logger = logging.getLogger(__name__)


class SignalRepository(AsyncRepository[Signal]):
    """Async repository for Signal records."""

    model = Signal

    async def get_by_signal_id(self, session: AsyncSession, signal_id: str) -> Signal | None:
        """Return a signal by its unique signal_id."""
        stmt = select(Signal).where(Signal.signal_id == signal_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_pending_signals(
        self,
        session: AsyncSession,
        symbol: str | None = None,
        limit: int = 50,
    ) -> Sequence[Signal]:
        """Return unexecuted signals, optionally filtered by symbol."""
        conditions = [Signal.executed == False]
        if symbol:
            conditions.append(Signal.symbol == symbol)
        stmt = select(Signal).where(and_(*conditions)).order_by(desc(Signal.generated_at)).limit(limit)
        result = await session.execute(stmt)
        return result.scalars().all()

    async def get_by_strategy(
        self,
        session: AsyncSession,
        strategy: str,
        since: datetime | None = None,
        limit: int = 100,
    ) -> Sequence[Signal]:
        """Return signals from a specific strategy."""
        conditions = [Signal.strategy == strategy]
        if since:
            conditions.append(Signal.generated_at >= since)
        stmt = select(Signal).where(and_(*conditions)).order_by(desc(Signal.generated_at)).limit(limit)
        result = await session.execute(stmt)
        return result.scalars().all()

    async def get_by_source(
        self,
        session: AsyncSession,
        source: SignalSource,
        limit: int = 100,
    ) -> Sequence[Signal]:
        """Return signals from a specific source."""
        stmt = select(Signal).where(Signal.source == source).order_by(desc(Signal.generated_at)).limit(limit)
        result = await session.execute(stmt)
        return result.scalars().all()

    async def get_by_user(
        self,
        session: AsyncSession,
        user_id: str,
        since: datetime | None = None,
        executed: bool | None = None,
        limit: int = 100,
    ) -> Sequence[Signal]:
        """Return signals associated with a user via their trades.

        Uses an INNER JOIN so only signals that are linked to a trade owned
        by the user are returned.  The previous LEFT OUTER JOIN put the
        Trade.user_id filter in the WHERE clause which turned the outer join
        into an implicit inner join while also excluding unlinked signals —
        the worst of both worlds.
        """
        from database.models import Trade

        conditions = [Trade.user_id == user_id]
        if since:
            conditions.append(Signal.generated_at >= since)
        if executed is not None:
            conditions.append(Signal.executed == executed)

        stmt = (
            select(Signal)
            .join(Trade, Signal.trade_id == Trade.trade_id)
            .where(and_(*conditions))
            .order_by(desc(Signal.generated_at))
            .limit(limit)
        )
        result = await session.execute(stmt)
        return result.scalars().all()

    async def get_accuracy_stats(
        self,
        session: AsyncSession,
        strategy: str | None = None,
        symbol: str | None = None,
        since: datetime | None = None,
    ) -> dict:
        """
        Compute signal accuracy statistics.

        Accuracy is measured by comparing signal action (buy/sell) against
        the realized PnL of the linked trade: positive PnL = correct direction.
        """
        from sqlalchemy import case, func as sa_func
        from database.models import Trade

        conditions = [Signal.executed == True, Signal.trade_id.isnot(None)]
        if strategy:
            conditions.append(Signal.strategy == strategy)
        if symbol:
            conditions.append(Signal.symbol == symbol)
        if since:
            conditions.append(Signal.generated_at >= since)

        stmt = (
            select(
                sa_func.count(Signal.id).label("total"),
                sa_func.sum(case((Trade.realized_pnl > 0, 1), else_=0)).label("winning"),
                sa_func.avg(Trade.realized_pnl).label("avg_pnl"),
                sa_func.sum(Trade.realized_pnl).label("total_pnl"),
                sa_func.avg(Signal.confidence).label("avg_confidence"),
            )
            .join(Trade, Signal.trade_id == Trade.trade_id, isouter=True)
            .where(and_(*conditions))
        )
        result = await session.execute(stmt)
        row = result.one()

        total = row.total or 0
        winning = int(row.winning or 0)
        return {
            "total_signals": total,
            "executed_signals": total,
            "winning_signals": winning,
            "losing_signals": total - winning,
            "accuracy_pct": round(winning / total * 100, 2) if total > 0 else 0.0,
            "avg_pnl": float(row.avg_pnl or 0),
            "total_pnl": float(row.total_pnl or 0),
            "avg_confidence": float(row.avg_confidence or 0),
        }

    async def mark_executed(
        self,
        session: AsyncSession,
        signal_id: str,
        trade_id: str,
        executed_at: datetime | None = None,
    ) -> Signal | None:
        """Mark a signal as executed, link it to a trade, and record execution time."""
        from datetime import timezone

        signal = await self.get_by_signal_id(session, signal_id)
        if signal is None:
            logger.warning("mark_executed: signal_id=%s not found", signal_id)
            return None
        signal.executed = True
        signal.trade_id = trade_id
        signal.execution_time = executed_at or datetime.now(timezone.utc)
        session.add(signal)
        await session.flush()
        await session.refresh(signal)
        return signal

    async def get_recent_by_symbol(
        self,
        session: AsyncSession,
        symbol: str,
        limit: int = 20,
    ) -> Sequence[Signal]:
        """Return the most recent signals for a symbol."""
        stmt = select(Signal).where(Signal.symbol == symbol).order_by(desc(Signal.generated_at)).limit(limit)
        result = await session.execute(stmt)
        return result.scalars().all()
