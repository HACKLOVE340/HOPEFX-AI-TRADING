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
from dataclasses import dataclass
from typing import Any, Generic, Sequence, Type, TypeVar

from sqlalchemy import func, inspect, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

ModelT = TypeVar("ModelT")


@dataclass
class Page(Generic[ModelT]):
    """Paginated result envelope."""

    items: Sequence[ModelT]
    total: int
    page: int
    page_size: int

    @property
    def total_pages(self) -> int:
        if self.page_size == 0:
            return 0
        import math

        return math.ceil(self.total / self.page_size)

    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages

    @property
    def has_prev(self) -> bool:
        return self.page > 1


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

    async def bulk_create(self, session: AsyncSession, rows: list[dict[str, Any]]) -> list[ModelT]:
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

    async def update(self, session: AsyncSession, instance: ModelT, **kwargs: Any) -> ModelT:
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

    # ── Pagination ─────────────────────────────────────────────────────────────

    async def paginate(
        self,
        session: AsyncSession,
        page: int = 1,
        page_size: int = 20,
        *,
        stmt=None,
    ) -> Page[ModelT]:
        """
        Return a paginated result for the model.

        ``stmt`` — optional pre-filtered select statement.  When omitted,
        all rows are returned.  The caller is responsible for applying
        WHERE / ORDER BY clauses before passing the statement in.

        Usage::

            page = await repo.paginate(session, page=2, page_size=25,
                                       stmt=select(Trade).where(Trade.user_id == uid))
        """
        if stmt is None:
            stmt = select(self.model)

        # Total count via subquery
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_result = await session.execute(count_stmt)
        total = total_result.scalar_one()

        offset = (page - 1) * page_size
        paged_stmt = stmt.limit(page_size).offset(offset)
        rows_result = await session.execute(paged_stmt)
        items = rows_result.scalars().all()

        return Page(items=items, total=total, page=page, page_size=page_size)

    # ── Bulk upsert ────────────────────────────────────────────────────────────

    def _dialect_name(self, session: AsyncSession) -> str:
        """
        Return the dialect name for the session's underlying engine.

        Works with both sync-wrapped and native async sessions.
        Uses the engine URL string rather than calling get_bind() (which is
        synchronous and raises on async sessions in SQLAlchemy 2.x).
        """
        try:
            # SQLAlchemy 2.x async session exposes .bind (the async engine)
            engine = session.bind
            if engine is not None:
                return engine.dialect.name
        except Exception:  # nosec B110  # noqa: S110
            pass
        try:
            # Fallback: inspect the engine URL from the session's sync session
            sync_session = session.sync_session
            if sync_session.bind is not None:
                return sync_session.bind.dialect.name
        except Exception:  # nosec B110  # noqa: S110
            pass
        return "unknown"

    async def bulk_upsert(
        self,
        session: AsyncSession,
        rows: list[dict[str, Any]],
        conflict_columns: list[str] | None = None,
        update_columns: list[str] | None = None,
    ) -> int:
        """
        PostgreSQL INSERT … ON CONFLICT DO UPDATE for a batch of rows.

        ``conflict_columns`` — columns that form the unique constraint
            (defaults to the model's primary key column names).
        ``update_columns``   — columns to overwrite on conflict
            (defaults to all non-PK columns present in the first row).

        Returns the number of rows affected.

        Falls back to individual upserts on non-PostgreSQL dialects (SQLite
        for tests) using a simple get-or-create pattern.
        """
        if not rows:
            return 0

        dialect_name = self._dialect_name(session)

        if dialect_name == "postgresql":
            return await self._pg_bulk_upsert(session, rows, conflict_columns, update_columns)
        # Fallback for SQLite / other dialects
        return await self._fallback_bulk_upsert(session, rows)

    async def _pg_bulk_upsert(
        self,
        session: AsyncSession,
        rows: list[dict[str, Any]],
        conflict_columns: list[str] | None,
        update_columns: list[str] | None,
    ) -> int:
        mapper = inspect(self.model)
        pk_names = [col.key for col in mapper.mapper.primary_key]  # type: ignore[attr-defined]

        if conflict_columns is None:
            conflict_columns = pk_names

        if update_columns is None:
            all_cols = set(rows[0].keys())
            update_columns = [c for c in all_cols if c not in pk_names]

        stmt = pg_insert(self.model).values(rows)
        if update_columns:
            stmt = stmt.on_conflict_do_update(
                index_elements=conflict_columns,
                set_={col: stmt.excluded[col] for col in update_columns},
            )
        else:
            stmt = stmt.on_conflict_do_nothing(index_elements=conflict_columns)

        result = await session.execute(stmt)
        await session.flush()
        return result.rowcount

    async def _fallback_bulk_upsert(
        self,
        session: AsyncSession,
        rows: list[dict[str, Any]],
    ) -> int:
        """Simple upsert fallback for non-PostgreSQL dialects."""
        mapper = inspect(self.model)
        pk_names = [col.key for col in mapper.mapper.primary_key]  # type: ignore[attr-defined]
        count = 0
        for row in rows:
            pk_vals = {k: row[k] for k in pk_names if k in row}
            if pk_vals:
                existing = await session.get(
                    self.model, tuple(pk_vals.values()) if len(pk_vals) > 1 else list(pk_vals.values())[0]
                )
                if existing is not None:
                    for k, v in row.items():
                        setattr(existing, k, v)
                    session.add(existing)
                    count += 1
                    continue
            instance = self.model(**row)
            session.add(instance)
            count += 1
        await session.flush()
        return count
