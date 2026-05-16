# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
database/repositories/tick_data_repository.py
==============================================
Typed async repository for the TickData model.

TickData rows use nanosecond-epoch integers (ts_ns) for ordering and
range queries.  The table is designed for TimescaleDB hypertable
partitioning but works as a plain PostgreSQL / SQLite table.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Sequence

from sqlalchemy import and_, asc, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import TickData
from .base import AsyncRepository

logger = logging.getLogger(__name__)

UTC = timezone.utc


class TickDataRepository(AsyncRepository[TickData]):
    """Async repository for sub-millisecond TickData records."""

    model = TickData

    async def insert_tick(
        self,
        session: AsyncSession,
        symbol: str,
        bid: float,
        ask: float,
        ts_ns: int | None = None,
        last_price: float | None = None,
        volume: float = 0.0,
        source: str | None = None,
        quality: str = "good",
        confidence: float = 1.0,
        lineage_id: str | None = None,
    ) -> TickData:
        """Insert a single tick row."""
        now_ns = ts_ns if ts_ns is not None else time.time_ns()
        mid = (bid + ask) / 2.0
        spread = ask - bid
        tick = TickData(
            ts_ns=now_ns,
            symbol=symbol,
            bid=bid,
            ask=ask,
            mid=mid,
            spread=spread,
            last_price=last_price if last_price is not None else mid,
            volume=volume,
            timestamp=datetime.fromtimestamp(now_ns / 1e9, tz=UTC),
            source=source,
            quality=quality,
            confidence=confidence,
            lineage_id=lineage_id,
        )
        session.add(tick)
        await session.flush()
        import contextlib

        with contextlib.suppress(Exception):  # nosec B110 — BigInteger PK refresh may fail on SQLite
            await session.refresh(tick)
        return tick

    async def bulk_insert_ticks(
        self,
        session: AsyncSession,
        ticks: list[dict[str, Any]],
    ) -> int:
        """
        Bulk-insert tick rows.  Returns the number of rows inserted.

        Each dict must have: symbol, bid, ask, ts_ns.
        mid, spread, last_price, volume, source, quality, confidence,
        lineage_id are optional.
        """
        instances = []
        for t in ticks:
            bid = float(t["bid"])
            ask = float(t["ask"])
            ts_ns = int(t.get("ts_ns", time.time_ns()))
            instances.append(
                TickData(
                    ts_ns=ts_ns,
                    symbol=t["symbol"],
                    bid=bid,
                    ask=ask,
                    mid=t.get("mid", (bid + ask) / 2.0),
                    spread=t.get("spread", ask - bid),
                    last_price=t.get("last_price", (bid + ask) / 2.0),
                    volume=t.get("volume", 0.0),
                    timestamp=datetime.fromtimestamp(ts_ns / 1e9, tz=UTC),
                    source=t.get("source"),
                    quality=t.get("quality", "good"),
                    confidence=t.get("confidence", 1.0),
                    lineage_id=t.get("lineage_id"),
                )
            )
        session.add_all(instances)
        await session.flush()
        return len(instances)

    async def get_latest_ticks(
        self,
        session: AsyncSession,
        symbol: str,
        n: int = 100,
        source: str | None = None,
    ) -> Sequence[TickData]:
        """Return the *n* most recent ticks for *symbol* in chronological order."""
        conditions = [TickData.symbol == symbol]
        if source:
            conditions.append(TickData.source == source)
        stmt = select(TickData).where(and_(*conditions)).order_by(desc(TickData.ts_ns)).limit(n)
        result = await session.execute(stmt)
        rows = list(result.scalars().all())
        return list(reversed(rows))

    async def get_ticks_in_range(
        self,
        session: AsyncSession,
        symbol: str,
        start_ns: int,
        end_ns: int,
        source: str | None = None,
        quality: str | None = None,
    ) -> Sequence[TickData]:
        """Return ticks within a nanosecond timestamp range."""
        conditions = [
            TickData.symbol == symbol,
            TickData.ts_ns >= start_ns,
            TickData.ts_ns <= end_ns,
        ]
        if source:
            conditions.append(TickData.source == source)
        if quality:
            conditions.append(TickData.quality == quality)
        stmt = select(TickData).where(and_(*conditions)).order_by(asc(TickData.ts_ns))
        result = await session.execute(stmt)
        return result.scalars().all()

    async def get_ticks_since_datetime(
        self,
        session: AsyncSession,
        symbol: str,
        since: datetime,
        limit: int = 10000,
    ) -> Sequence[TickData]:
        """Return ticks since *since* (datetime) for *symbol*."""
        since_ns = int(since.timestamp() * 1_000_000_000)
        stmt = (
            select(TickData)
            .where(
                and_(
                    TickData.symbol == symbol,
                    TickData.ts_ns >= since_ns,
                )
            )
            .order_by(asc(TickData.ts_ns))
            .limit(limit)
        )
        result = await session.execute(stmt)
        return result.scalars().all()

    async def get_latest_tick(
        self,
        session: AsyncSession,
        symbol: str,
        source: str | None = None,
    ) -> TickData | None:
        """Return the single most recent tick for *symbol*."""
        conditions = [TickData.symbol == symbol]
        if source:
            conditions.append(TickData.source == source)
        stmt = select(TickData).where(and_(*conditions)).order_by(desc(TickData.ts_ns)).limit(1)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def count_ticks_since(
        self,
        session: AsyncSession,
        symbol: str,
        since_ns: int,
    ) -> int:
        """Return the number of ticks since *since_ns*."""
        from sqlalchemy import func as sa_func

        stmt = select(sa_func.count(TickData.id)).where(
            and_(
                TickData.symbol == symbol,
                TickData.ts_ns >= since_ns,
            )
        )
        result = await session.execute(stmt)
        return result.scalar_one() or 0

    async def delete_ticks_before(
        self,
        session: AsyncSession,
        symbol: str,
        before_ns: int,
    ) -> int:
        """Delete ticks older than *before_ns*. Returns count deleted."""
        from sqlalchemy import delete

        stmt = delete(TickData).where(
            and_(
                TickData.symbol == symbol,
                TickData.ts_ns < before_ns,
            )
        )
        result = await session.execute(stmt)
        return result.rowcount
