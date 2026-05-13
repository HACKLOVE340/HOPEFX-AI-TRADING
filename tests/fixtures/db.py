# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/fixtures/db.py
====================
Real database fixtures for pytest.

Provides async and sync SQLAlchemy sessions backed by a real PostgreSQL
database (when DATABASE_URL is set) or an in-process SQLite database
(for CI / local runs without Postgres).

All fixtures use transaction rollback for isolation — each test gets a
clean slate without truncating tables.

Usage
-----
    from tests.fixtures.db import async_db_session, sync_db_session

    async def test_something(async_db_session):
        result = await async_db_session.execute(select(Trade))
        ...

Fixtures
--------
db_engine          — module-scoped async engine (shared across tests)
db_tables          — creates all tables once per session
async_db_session   — function-scoped async session, rolled back after each test
sync_db_session    — function-scoped sync session, rolled back after each test
db_user            — a persisted User row (rolled back after test)
db_trade           — a persisted Trade row linked to db_user
db_signal          — a persisted Signal row linked to db_user
db_position        — a persisted Position row linked to db_user
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator, Generator

import pytest
import pytest_asyncio

UTC = timezone.utc

# ── Database URL resolution ───────────────────────────────────────────────────
# Use the real DATABASE_URL when available; fall back to SQLite for CI.
_DATABASE_URL = os.environ.get("DATABASE_URL", "")
_ASYNC_URL: str
_SYNC_URL: str

if _DATABASE_URL.startswith("postgresql"):
    # Convert postgresql:// → postgresql+asyncpg:// for async engine
    _ASYNC_URL = _DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1).replace(
        "postgresql+psycopg2://", "postgresql+asyncpg://", 1
    )
    _SYNC_URL = _DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)
else:
    # SQLite in-memory for CI — uses aiosqlite for async
    _ASYNC_URL = "sqlite+aiosqlite:///:memory:"
    _SYNC_URL = "sqlite:///:memory:"

# ── SQLAlchemy imports (guarded) ──────────────────────────────────────────────
try:
    from sqlalchemy import create_engine, text  # noqa: F401
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )
    from sqlalchemy.orm import Session, sessionmaker
    from sqlalchemy.pool import NullPool, StaticPool

    _SA_AVAILABLE = True
except ImportError:
    _SA_AVAILABLE = False

# ── Model imports ─────────────────────────────────────────────────────────────
try:
    from database.models import (
        Base,
        Signal,
        Trade,
    )
    from database.user_models import User

    # Position model is optional — not all deployments have it yet
    try:
        from database.models import Position as _Position

        _POSITION_MODEL_AVAILABLE = True
    except ImportError:
        _POSITION_MODEL_AVAILABLE = False

    _MODELS_AVAILABLE = True
except ImportError:
    _MODELS_AVAILABLE = False
    _POSITION_MODEL_AVAILABLE = False


# ── Engine fixtures ───────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def db_engine():
    """
    Session-scoped async engine.

    Uses NullPool so connections are not pooled — safe for test isolation.
    For SQLite in-memory, uses StaticPool so all connections share the same
    in-memory database (required for in-memory SQLite to be visible across
    multiple sessions).

    Disposal uses asyncio.run() (Python 3.7+) rather than the deprecated
    asyncio.get_event_loop().run_until_complete() which raises DeprecationWarning
    in Python 3.10+ and RuntimeError in 3.12+ when no running loop exists.
    """
    if not _SA_AVAILABLE:
        pytest.skip("SQLAlchemy not installed")

    if _ASYNC_URL.startswith("sqlite"):
        engine = create_async_engine(
            _ASYNC_URL,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    else:
        engine = create_async_engine(_ASYNC_URL, poolclass=NullPool)

    yield engine

    import asyncio

    async def _dispose():
        await engine.dispose()

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Inside an async context (e.g. pytest-asyncio) — schedule disposal
            loop.create_task(_dispose())
        else:
            loop.run_until_complete(_dispose())
    except RuntimeError:
        # No event loop — create a temporary one for cleanup
        asyncio.run(_dispose())


@pytest.fixture(scope="session")
def sync_db_engine():
    """Module-scoped sync engine for fixtures that need synchronous access."""
    if not _SA_AVAILABLE:
        pytest.skip("SQLAlchemy not installed")

    if _SYNC_URL.startswith("sqlite"):
        engine = create_engine(
            _SYNC_URL,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    else:
        engine = create_engine(_SYNC_URL, poolclass=NullPool)

    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def db_tables(db_engine, sync_db_engine):
    """
    Create all ORM tables once per test session.

    Uses the sync engine for DDL (simpler than async DDL).
    Drops and recreates to ensure a clean schema.

    Skips gracefully when ORM models are not importable (e.g. in CI
    environments where optional DB dependencies are not installed).
    """
    if not _MODELS_AVAILABLE:
        pytest.skip("Database models not available — install database dependencies")

    try:
        Base.metadata.create_all(bind=sync_db_engine)
    except Exception as exc:
        pytest.skip(f"Could not create DB tables: {exc}")

    yield

    try:
        Base.metadata.drop_all(bind=sync_db_engine)
    except Exception:
        pass  # Best-effort cleanup — don't fail teardown


# ── Session fixtures ──────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def async_db_session(db_engine, db_tables) -> AsyncGenerator[AsyncSession, None]:
    """
    Function-scoped async session with automatic rollback.

    Uses a nested transaction (SAVEPOINT) so each test gets a clean slate
    without committing any data to the database.  The outer transaction is
    rolled back on teardown regardless of whether the test passed or failed.

    Pattern:
      1. Begin outer transaction
      2. Create SAVEPOINT (nested transaction)
      3. Yield session to test
      4. Roll back to SAVEPOINT (discards all test writes)
      5. Roll back outer transaction
    """
    if not _SA_AVAILABLE:
        pytest.skip("SQLAlchemy not installed")

    factory = async_sessionmaker(
        bind=db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )

    async with db_engine.connect() as conn:
        await conn.begin()
        async with factory(bind=conn) as session:
            try:
                yield session
            finally:
                await session.rollback()
        await conn.rollback()


@pytest.fixture
def sync_db_session(sync_db_engine, db_tables) -> Generator[Session, None, None]:
    """
    Function-scoped sync session with automatic rollback.

    Wraps the test in a savepoint so the outer transaction can be rolled back
    without committing any test data to the database.
    """
    if not _SA_AVAILABLE:
        pytest.skip("SQLAlchemy not installed")

    factory = sessionmaker(bind=sync_db_engine)
    session = factory()
    session.begin_nested()  # savepoint

    yield session

    session.rollback()
    session.close()


# ── Domain object fixtures ────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db_user(async_db_session: AsyncSession) -> User:
    """
    Persist a real User row and return it.

    The row is rolled back after the test — no permanent side effects.
    """
    if not _MODELS_AVAILABLE:
        pytest.skip("User model not available")

    user = User(
        id=str(uuid.uuid4()),
        email=f"test-{uuid.uuid4().hex[:8]}@hopefx.test",
        hashed_password="$2b$12$" + "x" * 53,  # bcrypt placeholder — not used for auth
        full_name="Test User",
        role="trader",
        plan="free",
        is_active=True,
        is_verified=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    async_db_session.add(user)
    await async_db_session.flush()  # assign PK without committing
    return user


@pytest_asyncio.fixture
async def db_trade(async_db_session: AsyncSession, db_user: User) -> Trade:
    """
    Persist a real Trade row linked to db_user.

    Uses realistic field values — no synthetic or random data.
    """
    if not _MODELS_AVAILABLE:
        pytest.skip("Trade model not available")

    trade = Trade(
        trade_id=f"T-{uuid.uuid4().hex[:12].upper()}",
        user_id=db_user.id,
        symbol="XAUUSD",
        direction="buy",
        entry_price=2340.50,
        exit_price=2355.00,
        quantity=0.10,
        realized_pnl=145.00,
        commission=3.50,
        status="closed",
        broker="paper",
        entry_time=datetime(2025, 1, 15, 9, 30, 0, tzinfo=UTC),
        exit_time=datetime(2025, 1, 15, 14, 45, 0, tzinfo=UTC),
    )
    async_db_session.add(trade)
    await async_db_session.flush()
    return trade


@pytest_asyncio.fixture
async def db_signal(async_db_session: AsyncSession, db_user: User) -> Signal:
    """
    Persist a real Signal row linked to db_user.
    """
    if not _MODELS_AVAILABLE:
        pytest.skip("Signal model not available")

    signal = Signal(
        user_id=db_user.id,
        symbol="XAUUSD",
        direction="buy",
        confidence=0.82,
        strategy="nuclear_v3",
        entry_price=2340.50,
        stop_loss=2320.00,
        take_profit=2380.00,
        is_executed=False,
        created_at=datetime.now(UTC),
    )
    async_db_session.add(signal)
    await async_db_session.flush()
    return signal


@pytest_asyncio.fixture
async def db_position(async_db_session: AsyncSession, db_user: User):
    """
    Persist a real Position row linked to db_user.

    Skipped when the Position model is not available in the current schema.
    """
    if not _POSITION_MODEL_AVAILABLE:
        pytest.skip("Position model not available")

    position = _Position(
        position_id=f"P-{uuid.uuid4().hex[:12].upper()}",
        user_id=db_user.id,
        symbol="XAUUSD",
        direction="buy",
        entry_price=2340.50,
        current_price=2355.00,
        quantity=0.10,
        unrealized_pnl=145.00,
        stop_loss=2320.00,
        take_profit=2380.00,
        status="open",
        broker="paper",
        opened_at=datetime(2025, 1, 15, 9, 30, 0, tzinfo=UTC),
    )
    async_db_session.add(position)
    await async_db_session.flush()
    return position


# ── Repository fixtures ───────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def trade_repo(async_db_session: AsyncSession):
    """TradeRepository wired to the test session."""
    try:
        from database.repositories.trade_repository import TradeRepository

        return TradeRepository(async_db_session)
    except ImportError:
        pytest.skip("TradeRepository not available")


@pytest_asyncio.fixture
async def signal_repo(async_db_session: AsyncSession):
    """SignalRepository wired to the test session."""
    try:
        from database.repositories.signal_repository import SignalRepository

        return SignalRepository(async_db_session)
    except ImportError:
        pytest.skip("SignalRepository not available")


@pytest_asyncio.fixture
async def position_repo(async_db_session: AsyncSession):
    """PositionRepository wired to the test session."""
    try:
        from database.repositories.position_repository import PositionRepository

        return PositionRepository(async_db_session)
    except ImportError:
        pytest.skip("PositionRepository not available")


@pytest_asyncio.fixture
async def market_data_repo(async_db_session: AsyncSession):
    """MarketDataRepository wired to the test session."""
    try:
        from database.repositories.market_data_repository import MarketDataRepository

        return MarketDataRepository(async_db_session)
    except ImportError:
        pytest.skip("MarketDataRepository not available")
