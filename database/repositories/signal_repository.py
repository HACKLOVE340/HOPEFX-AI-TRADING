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

    async def get_by_signal_id(
        self, session: AsyncSession, signal_id: str
    ) -> Signal | None:
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
        conditions = [Signal.executed == False]  # noqa: E712
        if symbol:
            conditions.append(Signal.symbol == symbol)
        stmt = (
            select(Signal)
            .where(and_(*conditions))
            .order_by(desc(Signal.created_at))
            .limit(limit)
        )
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
            conditions.append(Signal.created_at >= since)
        stmt = (
            select(Signal)
            .where(and_(*conditions))
            .order_by(desc(Signal.created_at))
            .limit(limit)
        )
        result = await session.execute(stmt)
        return result.scalars().all()

    async def get_by_source(
        self,
        session: AsyncSession,
        source: SignalSource,
        limit: int = 100,
    ) -> Sequence[Signal]:
        """Return signals from a specific source."""
        stmt = (
            select(Signal)
            .where(Signal.source == source)
            .order_by(desc(Signal.created_at))
            .limit(limit)
        )
        result = await session.execute(stmt)
        return result.scalars().all()

    async def mark_executed(
        self,
        session: AsyncSession,
        signal_id: str,
        trade_id: str,
    ) -> Signal | None:
        """Mark a signal as executed and link it to a trade."""
        signal = await self.get_by_signal_id(session, signal_id)
        if signal is None:
            logger.warning("mark_executed: signal_id=%s not found", signal_id)
            return None
        signal.executed = True
        signal.trade_id = trade_id
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
        stmt = (
            select(Signal)
            .where(Signal.symbol == symbol)
            .order_by(desc(Signal.created_at))
            .limit(limit)
        )
        result = await session.execute(stmt)
        return result.scalars().all()
