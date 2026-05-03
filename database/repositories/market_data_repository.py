# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
database/repositories/market_data_repository.py
================================================
Typed async repository for the MarketData (OHLCV bars) model.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Sequence

from sqlalchemy import and_, asc, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import MarketData
from .base import AsyncRepository

logger = logging.getLogger(__name__)


class MarketDataRepository(AsyncRepository[MarketData]):
    """Async repository for OHLCV MarketData records."""

    model = MarketData

    async def get_bars(
        self,
        session: AsyncSession,
        symbol: str,
        timeframe: str,
        limit: int = 200,
        offset: int = 0,
    ) -> Sequence[MarketData]:
        """Return OHLCV bars for a symbol/timeframe in chronological order."""
        stmt = (
            select(MarketData)
            .where(
                and_(
                    MarketData.symbol == symbol,
                    MarketData.timeframe == timeframe,
                )
            )
            .order_by(desc(MarketData.timestamp))
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(stmt)
        rows = list(result.scalars().all())
        return list(reversed(rows))  # chronological order

    async def get_bars_since(
        self,
        session: AsyncSession,
        symbol: str,
        timeframe: str,
        since: datetime,
    ) -> Sequence[MarketData]:
        """Return all bars since *since* in chronological order."""
        stmt = (
            select(MarketData)
            .where(
                and_(
                    MarketData.symbol == symbol,
                    MarketData.timeframe == timeframe,
                    MarketData.timestamp >= since,
                )
            )
            .order_by(asc(MarketData.timestamp))
        )
        result = await session.execute(stmt)
        return result.scalars().all()

    async def get_latest_bar(
        self,
        session: AsyncSession,
        symbol: str,
        timeframe: str,
    ) -> MarketData | None:
        """Return the most recent bar for a symbol/timeframe."""
        stmt = (
            select(MarketData)
            .where(
                and_(
                    MarketData.symbol == symbol,
                    MarketData.timeframe == timeframe,
                )
            )
            .order_by(desc(MarketData.timestamp))
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert_bar(
        self,
        session: AsyncSession,
        symbol: str,
        timeframe: str,
        timestamp: datetime,
        open_: float,
        high: float,
        low: float,
        close: float,
        volume: float = 0.0,
        spread: float | None = None,
        tick_count: int | None = None,
    ) -> MarketData:
        """
        Insert or update a bar.

        If a bar with the same (symbol, timeframe, timestamp) exists, it is
        updated in place.  Otherwise a new row is inserted.
        """
        stmt = select(MarketData).where(
            and_(
                MarketData.symbol == symbol,
                MarketData.timeframe == timeframe,
                MarketData.timestamp == timestamp,
            )
        )
        result = await session.execute(stmt)
        bar = result.scalar_one_or_none()

        if bar is None:
            bar = MarketData(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=timestamp,
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=volume,
                spread=spread,
                tick_count=tick_count,
            )
            session.add(bar)
        else:
            bar.open = open_
            bar.high = high
            bar.low = low
            bar.close = close
            bar.volume = volume
            if spread is not None:
                bar.spread = spread
            if tick_count is not None:
                bar.tick_count = tick_count
            session.add(bar)

        await session.flush()
        await session.refresh(bar)
        return bar

    async def bulk_insert_bars(
        self,
        session: AsyncSession,
        bars: list[dict[str, Any]],
    ) -> int:
        """
        Bulk-insert OHLCV bars.  Returns the number of rows inserted.

        Each dict must have: symbol, timeframe, timestamp, open, high, low,
        close.  volume, spread, tick_count are optional.
        """
        instances = [MarketData(**bar) for bar in bars]
        session.add_all(instances)
        await session.flush()
        return len(instances)

    async def delete_bars_before(
        self,
        session: AsyncSession,
        symbol: str,
        timeframe: str,
        before: datetime,
    ) -> int:
        """Delete bars older than *before*. Returns count deleted."""
        from sqlalchemy import delete

        stmt = delete(MarketData).where(
            and_(
                MarketData.symbol == symbol,
                MarketData.timeframe == timeframe,
                MarketData.timestamp < before,
            )
        )
        result = await session.execute(stmt)
        return result.rowcount
