# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
database/repositories/base.py
================================
Generic async repository base class.

All concrete repositories inherit from ``AsyncRepository[ModelT]`` which
provides standard CRUD operations using SQLAlchemy 2.x async sessions.

Type parameters
---------------
ModelT:
    The SQLAlchemy ORM model class (must have a primary key column).

All methods accept an ``AsyncSession`` as the first argument so repositories
are stateless — the session lifecycle is managed by the caller (typically
via ``AsyncConnectionPool.session()`` or ``get_async_db()``).
"""

from __future__ import annotations

import logging
from typing import Any, Generic, Sequence, Type, TypeVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

ModelT = TypeVar("ModelT")


class AsyncRepository(Generic[ModelT]):
    """
    Generic async CRUD repository.

    Subclasses must set ``model`` to the SQLAlchemy ORM class.

    Usage::

        class TradeRepository(AsyncRepository[Trade]):
            model = Trade

        repo = TradeRepository()
        async with pool.session() as session:
            trade = await repo.get_by_id(session, 42)
    """

    model: Type[ModelT]

    # ── Create ─────────────────────────────────────────────────────────────────

    async def create(self, session: AsyncSession, **kwargs: Any) -> ModelT:
        """Create and persist a new model instance."""
        instance = self.model(**kwargs)
        session.add(instance)
        await session.flush()
        await session.refresh(instance)
        return instance

    async def bulk_create(
        self, session: AsyncSession, rows: list[dict[str, Any]]
    ) -> list[ModelT]:
        """Bulk-insert multiple rows and return the created instances."""
        instances = [self.model(**row) for row in rows]
        session.add_all(instances)
        await session.flush()
        return instances

    # ── Read ───────────────────────────────────────────────────────────────────

    async def get_by_id(self, session: AsyncSession, pk: Any) -> ModelT | None:
        """Return the row with the given primary key, or None."""
        return await session.get(self.model, pk)

    async def get_all(
        self,
        session: AsyncSession,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[ModelT]:
        """Return all rows with optional pagination."""
        stmt = select(self.model).limit(limit).offset(offset)
        result = await session.execute(stmt)
        return result.scalars().all()

    async def count(self, session: AsyncSession) -> int:
        """Return the total row count."""
        stmt = select(func.count()).select_from(self.model)
        result = await session.execute(stmt)
        return result.scalar_one()

    async def exists(self, session: AsyncSession, pk: Any) -> bool:
        """Return True if a row with the given primary key exists."""
        return await self.get_by_id(session, pk) is not None

    # ── Update ─────────────────────────────────────────────────────────────────

    async def update(
        self, session: AsyncSession, instance: ModelT, **kwargs: Any
    ) -> ModelT:
        """Update *instance* with the given keyword arguments."""
        for key, value in kwargs.items():
            setattr(instance, key, value)
        session.add(instance)
        await session.flush()
        await session.refresh(instance)
        return instance

    # ── Delete ─────────────────────────────────────────────────────────────────

    async def delete(self, session: AsyncSession, instance: ModelT) -> None:
        """Delete *instance* from the database."""
        await session.delete(instance)
        await session.flush()

    async def delete_by_id(self, session: AsyncSession, pk: Any) -> bool:
        """Delete the row with the given primary key. Returns True if deleted."""
        instance = await self.get_by_id(session, pk)
        if instance is None:
            return False
        await self.delete(session, instance)
        return True
