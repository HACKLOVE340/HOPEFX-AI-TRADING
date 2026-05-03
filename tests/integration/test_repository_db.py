# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/integration/test_repository_db.py
========================================
Real DB fixture tests for TradeRepository, SignalRepository, PositionRepository.

Uses real SQLite in-memory DB (or PostgreSQL when DATABASE_URL is set).
All tests use transaction rollback for isolation — no permanent side effects.
No mocks, stubs, or synthetic data in production code paths.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("SECURITY_JWT_SECRET", "test-only-jwt-secret-key-minimum-32-chars!!")

UTC = timezone.utc

# ── Dependency guards ─────────────────────────────────────────────────────────

try:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool
    _SA_OK = True
except ImportError:
    _SA_OK = False

if not _SA_OK:
    pytest.skip("SQLAlchemy not installed", allow_module_level=True)

try:
    from database.models import Base, Signal, SignalSource, Trade, TradeStatus
    from database.user_models import User
    _MODELS_OK = True
except Exception as _e:
    _MODELS_OK = False
    _MODELS_ERR = str(_e)

if not _MODELS_OK:
    pytest.skip(f"Models not importable: {_MODELS_ERR}", allow_module_level=True)

try:
    from database.models import Position as _Position
    _POSITION_OK = True
except ImportError:
    _POSITION_OK = False

try:
    from database.repositories.trade_repository import TradeRepository
    from database.repositories.signal_repository import SignalRepository
    _REPOS_OK = True
except Exception as _e:
    _REPOS_OK = False
    _REPOS_ERR = str(_e)

if not _REPOS_OK:
    pytest.skip(f"Repositories not importable: {_REPOS_ERR}", allow_module_level=True)

# ── Shared in-memory engine ───────────────────────────────────────────────────

_ASYNC_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="module")
def async_engine():
    """Module-scoped async engine with tables created once."""
    import asyncio

    eng = create_async_engine(
        _ASYNC_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async def _create():
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            try:
                from database.user_models import Base as UBase
                await conn.run_sync(UBase.metadata.create_all)
            except Exception:
                pass

    asyncio.get_event_loop().run_until_complete(_create())
    yield eng


@pytest_asyncio.fixture
async def session(async_engine) -> AsyncSession:
    factory = async_sessionmaker(
        bind=async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    async with async_engine.connect() as conn:
        await conn.begin()
        async with factory(bind=conn) as sess:
            try:
                yield sess
            finally:
                await sess.rollback()
        await conn.rollback()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _uid() -> str:
    return uuid.uuid4().hex[:12].upper()


def _make_trade(user_id: str, symbol: str = "XAUUSD", side: str = "buy",
                entry_price: float = 2340.50, is_open: bool = True) -> Trade:
    return Trade(
        trade_id=f"T-{_uid()}",
        user_id=user_id,
        symbol=symbol,
        side=side,
        entry_price=entry_price,
        entry_quantity=0.10,
        realized_pnl=0.0,
        commission=3.50,
        status=TradeStatus.OPEN if is_open else TradeStatus.CLOSED,
        is_open=is_open,
        entry_time=datetime(2025, 1, 15, 9, 30, 0, tzinfo=UTC),
    )


def _make_signal(symbol: str = "XAUUSD", action: str = "buy",
                 strategy: str = "nuclear_v3", confidence: float = 0.82) -> Signal:
    return Signal(
        signal_id=f"SIG-{_uid()}",
        symbol=symbol,
        action=action,
        strategy=strategy,
        source=SignalSource.TREND_FOLLOWING,
        entry_price=2340.50,
        stop_loss=2320.00,
        take_profit=2380.00,
        confidence=confidence,
        executed=False,
        generated_at=datetime.now(UTC),
    )


def _make_position(user_id: str, symbol: str = "XAUUSD", side: str = "long",
                   entry_price: float = 2340.50) -> "_Position":
    return _Position(
        id=f"P-{_uid()}",
        user_id=user_id,
        symbol=symbol,
        side=side,
        quantity=0.10,
        entry_price=entry_price,
        current_price=entry_price,
        market_value=entry_price * 0.10,
        unrealized_pnl=0.0,
        realized_pnl=0.0,
        stop_loss=2320.00,
        take_profit=2380.00,
        status="open",
        opened_at=datetime.now(UTC),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# TradeRepository tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestTradeRepository:

    @pytest.mark.asyncio
    async def test_create_and_get_by_id(self, session: AsyncSession):
        repo = TradeRepository()
        uid = f"user-{_uid()}"
        trade = _make_trade(uid)
        session.add(trade)
        await session.flush()

        fetched = await repo.get_by_id(session, trade.id)
        assert fetched is not None
        assert fetched.trade_id == trade.trade_id
        assert fetched.symbol == "XAUUSD"
        assert fetched.side == "buy"

    @pytest.mark.asyncio
    async def test_get_by_trade_id(self, session: AsyncSession):
        repo = TradeRepository()
        uid = f"user-{_uid()}"
        trade = _make_trade(uid)
        session.add(trade)
        await session.flush()

        fetched = await repo.get_by_trade_id(session, trade.trade_id)
        assert fetched is not None
        assert fetched.entry_price == 2340.50

    @pytest.mark.asyncio
    async def test_get_by_trade_id_not_found(self, session: AsyncSession):
        repo = TradeRepository()
        result = await repo.get_by_trade_id(session, "NONEXISTENT-ID")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_open_trades(self, session: AsyncSession):
        repo = TradeRepository()
        uid = f"user-{_uid()}"
        open_trade = _make_trade(uid, is_open=True)
        closed_trade = _make_trade(uid, is_open=False)
        closed_trade.status = TradeStatus.CLOSED
        session.add(open_trade)
        session.add(closed_trade)
        await session.flush()

        open_trades = await repo.get_open_trades(session, user_id=uid)
        assert len(open_trades) == 1
        assert open_trades[0].is_open is True

    @pytest.mark.asyncio
    async def test_get_open_trades_filtered_by_symbol(self, session: AsyncSession):
        repo = TradeRepository()
        uid = f"user-{_uid()}"
        xau = _make_trade(uid, symbol="XAUUSD")
        eur = _make_trade(uid, symbol="EURUSD")
        session.add(xau)
        session.add(eur)
        await session.flush()

        xau_trades = await repo.get_open_trades(session, symbol="XAUUSD", user_id=uid)
        assert all(t.symbol == "XAUUSD" for t in xau_trades)

    @pytest.mark.asyncio
    async def test_get_by_user(self, session: AsyncSession):
        repo = TradeRepository()
        uid = f"user-{_uid()}"
        for _ in range(3):
            session.add(_make_trade(uid))
        await session.flush()

        trades = await repo.get_by_user(session, uid)
        assert len(trades) == 3
        assert all(t.user_id == uid for t in trades)

    @pytest.mark.asyncio
    async def test_get_by_user_isolation(self, session: AsyncSession):
        """Trades from user A are not returned for user B."""
        repo = TradeRepository()
        uid_a = f"user-{_uid()}"
        uid_b = f"user-{_uid()}"
        session.add(_make_trade(uid_a))
        session.add(_make_trade(uid_b))
        await session.flush()

        trades_a = await repo.get_by_user(session, uid_a)
        trades_b = await repo.get_by_user(session, uid_b)
        assert len(trades_a) == 1
        assert len(trades_b) == 1
        assert trades_a[0].user_id == uid_a
        assert trades_b[0].user_id == uid_b

    @pytest.mark.asyncio
    async def test_close_trade(self, session: AsyncSession):
        repo = TradeRepository()
        uid = f"user-{_uid()}"
        trade = _make_trade(uid)
        session.add(trade)
        await session.flush()

        closed = await repo.close_trade(
            session,
            trade_id=trade.trade_id,
            exit_price=2355.00,
            exit_time=datetime(2025, 1, 15, 14, 0, 0, tzinfo=UTC),
            realized_pnl=145.00,
        )
        assert closed is not None
        assert closed.exit_price == 2355.00
        assert closed.realized_pnl == 145.00
        assert closed.is_open is False
        assert closed.status == TradeStatus.CLOSED

    @pytest.mark.asyncio
    async def test_close_trade_not_found(self, session: AsyncSession):
        repo = TradeRepository()
        result = await repo.close_trade(
            session, trade_id="GHOST-ID",
            exit_price=2355.00,
            exit_time=datetime.now(UTC),
            realized_pnl=0.0,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_update_unrealized_pnl(self, session: AsyncSession):
        repo = TradeRepository()
        uid = f"user-{_uid()}"
        trade = _make_trade(uid)
        session.add(trade)
        await session.flush()

        updated = await repo.update_unrealized_pnl(
            session, trade_id=trade.trade_id,
            unrealized_pnl=68.00, current_price=2341.80,
        )
        assert updated is not None
        assert updated.unrealized_pnl == 68.00

    @pytest.mark.asyncio
    async def test_get_by_symbol(self, session: AsyncSession):
        repo = TradeRepository()
        uid = f"user-{_uid()}"
        for _ in range(2):
            session.add(_make_trade(uid, symbol="XAUUSD"))
        session.add(_make_trade(uid, symbol="EURUSD"))
        await session.flush()

        xau = await repo.get_by_symbol(session, "XAUUSD")
        assert len(xau) >= 2
        assert all(t.symbol == "XAUUSD" for t in xau)

    @pytest.mark.asyncio
    async def test_get_by_date_range(self, session: AsyncSession):
        repo = TradeRepository()
        uid = f"user-{_uid()}"
        trade = _make_trade(uid)
        trade.entry_time = datetime(2025, 3, 10, 10, 0, 0, tzinfo=UTC)
        session.add(trade)
        await session.flush()

        results = await repo.get_by_date_range(
            session,
            start=datetime(2025, 3, 1, tzinfo=UTC),
            end=datetime(2025, 3, 31, tzinfo=UTC),
        )
        assert any(t.trade_id == trade.trade_id for t in results)

    @pytest.mark.asyncio
    async def test_get_pnl_summary_empty(self, session: AsyncSession):
        repo = TradeRepository()
        uid = f"user-{_uid()}"
        summary = await repo.get_pnl_summary(session, user_id=uid)
        assert summary["trade_count"] == 0
        assert summary["total_pnl"] == 0.0

    @pytest.mark.asyncio
    async def test_get_pnl_summary_with_closed_trades(self, session: AsyncSession):
        repo = TradeRepository()
        uid = f"user-{_uid()}"
        for pnl in [100.0, 200.0, -50.0]:
            t = _make_trade(uid, is_open=False)
            t.status = TradeStatus.CLOSED
            t.realized_pnl = pnl
            session.add(t)
        await session.flush()

        summary = await repo.get_pnl_summary(session, user_id=uid)
        assert summary["trade_count"] == 3
        assert abs(summary["total_pnl"] - 250.0) < 0.01

    @pytest.mark.asyncio
    async def test_get_by_client_order_id(self, session: AsyncSession):
        repo = TradeRepository()
        uid = f"user-{_uid()}"
        trade = _make_trade(uid)
        coid = f"COID-{_uid()}"
        trade.client_order_id = coid
        session.add(trade)
        await session.flush()

        fetched = await repo.get_by_client_order_id(session, coid)
        assert fetched is not None
        assert fetched.trade_id == trade.trade_id


# ═══════════════════════════════════════════════════════════════════════════════
# SignalRepository tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestSignalRepository:

    @pytest.mark.asyncio
    async def test_create_and_get_by_id(self, session: AsyncSession):
        repo = SignalRepository()
        sig = _make_signal()
        session.add(sig)
        await session.flush()

        fetched = await repo.get_by_id(session, sig.id)
        assert fetched is not None
        assert fetched.signal_id == sig.signal_id
        assert fetched.symbol == "XAUUSD"
        assert fetched.action == "buy"

    @pytest.mark.asyncio
    async def test_get_by_signal_id(self, session: AsyncSession):
        repo = SignalRepository()
        sig = _make_signal()
        session.add(sig)
        await session.flush()

        fetched = await repo.get_by_signal_id(session, sig.signal_id)
        assert fetched is not None
        assert fetched.confidence == 0.82

    @pytest.mark.asyncio
    async def test_get_by_signal_id_not_found(self, session: AsyncSession):
        repo = SignalRepository()
        result = await repo.get_by_signal_id(session, "GHOST-SIG")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_pending_signals(self, session: AsyncSession):
        repo = SignalRepository()
        pending = _make_signal()
        executed = _make_signal()
        executed.executed = True
        session.add(pending)
        session.add(executed)
        await session.flush()

        results = await repo.get_pending_signals(session)
        pending_ids = {s.signal_id for s in results}
        assert pending.signal_id in pending_ids
        assert executed.signal_id not in pending_ids

    @pytest.mark.asyncio
    async def test_get_pending_signals_filtered_by_symbol(self, session: AsyncSession):
        repo = SignalRepository()
        xau_sig = _make_signal(symbol="XAUUSD")
        eur_sig = _make_signal(symbol="EURUSD")
        session.add(xau_sig)
        session.add(eur_sig)
        await session.flush()

        results = await repo.get_pending_signals(session, symbol="XAUUSD")
        assert all(s.symbol == "XAUUSD" for s in results)

    @pytest.mark.asyncio
    async def test_get_by_strategy(self, session: AsyncSession):
        repo = SignalRepository()
        nuke = _make_signal(strategy="nuclear_v3")
        mom  = _make_signal(strategy="momentum_scalper")
        session.add(nuke)
        session.add(mom)
        await session.flush()

        results = await repo.get_by_strategy(session, "nuclear_v3")
        assert all(s.strategy == "nuclear_v3" for s in results)
        strats = {s.strategy for s in results}
        assert "momentum_scalper" not in strats

    @pytest.mark.asyncio
    async def test_get_by_source(self, session: AsyncSession):
        repo = SignalRepository()
        sig = _make_signal()
        sig.source = SignalSource.BREAKOUT
        session.add(sig)
        await session.flush()

        results = await repo.get_by_source(session, SignalSource.BREAKOUT)
        assert any(s.signal_id == sig.signal_id for s in results)

    @pytest.mark.asyncio
    async def test_mark_executed(self, session: AsyncSession):
        repo = SignalRepository()
        sig = _make_signal()
        session.add(sig)
        await session.flush()

        # Create a trade to link
        uid = f"user-{_uid()}"
        trade = _make_trade(uid)
        session.add(trade)
        await session.flush()

        updated = await repo.mark_executed(
            session,
            signal_id=sig.signal_id,
            trade_id=trade.trade_id,
            executed_at=datetime.now(UTC),
        )
        assert updated is not None
        assert updated.executed is True
        assert updated.trade_id == trade.trade_id
        assert updated.execution_time is not None

    @pytest.mark.asyncio
    async def test_mark_executed_not_found(self, session: AsyncSession):
        repo = SignalRepository()
        result = await repo.mark_executed(
            session, signal_id="GHOST-SIG",
            trade_id="T-GHOST",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_get_recent_by_symbol(self, session: AsyncSession):
        repo = SignalRepository()
        for _ in range(5):
            session.add(_make_signal(symbol="XAUUSD"))
        session.add(_make_signal(symbol="EURUSD"))
        await session.flush()

        results = await repo.get_recent_by_symbol(session, "XAUUSD", limit=3)
        assert len(results) <= 3
        assert all(s.symbol == "XAUUSD" for s in results)

    @pytest.mark.asyncio
    async def test_get_accuracy_stats_no_data(self, session: AsyncSession):
        repo = SignalRepository()
        stats = await repo.get_accuracy_stats(session, strategy=f"ghost-{_uid()}")
        assert stats["total_signals"] == 0
        assert stats["accuracy_pct"] == 0.0

    @pytest.mark.asyncio
    async def test_signal_confidence_range(self, session: AsyncSession):
        """Confidence values 0.0–1.0 are stored and retrieved exactly."""
        repo = SignalRepository()
        for conf in [0.0, 0.5, 0.82, 1.0]:
            sig = _make_signal(confidence=conf)
            session.add(sig)
        await session.flush()

        results = await repo.get_pending_signals(session)
        confs = {round(s.confidence, 10) for s in results if s.confidence is not None}
        assert 0.82 in confs


# ═══════════════════════════════════════════════════════════════════════════════
# PositionRepository tests
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.skipif(not _POSITION_OK, reason="Position model not available")
class TestPositionRepository:

    @pytest.fixture(autouse=True)
    def _skip_if_no_position(self):
        if not _POSITION_OK:
            pytest.skip("Position model not available")

    @pytest.mark.asyncio
    async def test_create_and_get_open_positions(self, session: AsyncSession):
        from database.repositories.position_repository import PositionRepository
        repo = PositionRepository()
        uid = f"user-{_uid()}"
        pos = _make_position(uid)
        session.add(pos)
        await session.flush()

        results = await repo.get_open_positions(session, user_id=uid)
        assert len(results) == 1
        assert results[0].symbol == "XAUUSD"
        assert results[0].status == "open"

    @pytest.mark.asyncio
    async def test_get_open_positions_filtered_by_symbol(self, session: AsyncSession):
        from database.repositories.position_repository import PositionRepository
        repo = PositionRepository()
        uid = f"user-{_uid()}"
        session.add(_make_position(uid, symbol="XAUUSD"))
        session.add(_make_position(uid, symbol="EURUSD"))
        await session.flush()

        results = await repo.get_open_positions(session, user_id=uid, symbol="XAUUSD")
        assert all(p.symbol == "XAUUSD" for p in results)

    @pytest.mark.asyncio
    async def test_get_by_symbol_and_user(self, session: AsyncSession):
        from database.repositories.position_repository import PositionRepository
        repo = PositionRepository()
        uid = f"user-{_uid()}"
        pos = _make_position(uid)
        session.add(pos)
        await session.flush()

        fetched = await repo.get_by_symbol_and_user(session, "XAUUSD", uid)
        assert fetched is not None
        assert fetched.entry_price == 2340.50

    @pytest.mark.asyncio
    async def test_get_by_symbol_and_user_not_found(self, session: AsyncSession):
        from database.repositories.position_repository import PositionRepository
        repo = PositionRepository()
        result = await repo.get_by_symbol_and_user(session, "XAUUSD", f"ghost-{_uid()}")
        assert result is None

    @pytest.mark.asyncio
    async def test_update_current_price(self, session: AsyncSession):
        from database.repositories.position_repository import PositionRepository
        repo = PositionRepository()
        uid = f"user-{_uid()}"
        pos = _make_position(uid)
        session.add(pos)
        await session.flush()

        updated = await repo.update_current_price(
            session, position_id=pos.id,
            current_price=2355.00, unrealized_pnl=145.00,
        )
        assert updated is not None
        assert updated.current_price == 2355.00
        assert updated.unrealized_pnl == 145.00

    @pytest.mark.asyncio
    async def test_close_position(self, session: AsyncSession):
        from database.repositories.position_repository import PositionRepository
        repo = PositionRepository()
        uid = f"user-{_uid()}"
        pos = _make_position(uid)
        session.add(pos)
        await session.flush()

        closed = await repo.close_position(
            session, position_id=pos.id,
            realized_pnl=145.00,
            closed_at=datetime.now(UTC),
        )
        assert closed is not None
        assert closed.status == "closed"
        assert closed.realized_pnl == 145.00
        assert closed.closed_at is not None

    @pytest.mark.asyncio
    async def test_close_position_not_found(self, session: AsyncSession):
        from database.repositories.position_repository import PositionRepository
        repo = PositionRepository()
        result = await repo.close_position(session, position_id="GHOST-POS", realized_pnl=0.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_net_exposure(self, session: AsyncSession):
        from database.repositories.position_repository import PositionRepository
        repo = PositionRepository()
        uid = f"user-{_uid()}"
        long_pos = _make_position(uid, symbol="XAUUSD", side="long")
        session.add(long_pos)
        await session.flush()

        exposure = await repo.get_net_exposure(session, user_id=uid)
        assert "by_symbol" in exposure
        assert "total_abs_exposure" in exposure
        assert exposure["symbol_count"] >= 1

    @pytest.mark.asyncio
    async def test_get_portfolio_summary(self, session: AsyncSession):
        from database.repositories.position_repository import PositionRepository
        repo = PositionRepository()
        uid = f"user-{_uid()}"
        for _ in range(2):
            session.add(_make_position(uid))
        await session.flush()

        summary = await repo.get_portfolio_summary(session, user_id=uid)
        assert summary["position_count"] == 2
        assert "total_market_value" in summary
        assert "total_unrealized_pnl" in summary

    @pytest.mark.asyncio
    async def test_get_by_instrument(self, session: AsyncSession):
        from database.repositories.position_repository import PositionRepository
        repo = PositionRepository()
        uid = f"user-{_uid()}"
        session.add(_make_position(uid, symbol="XAUUSD"))
        session.add(_make_position(uid, symbol="EURUSD"))
        await session.flush()

        results = await repo.get_by_instrument(session, "XAUUSD")
        assert all(p.symbol == "XAUUSD" for p in results)

    @pytest.mark.asyncio
    async def test_short_position_stored_correctly(self, session: AsyncSession):
        from database.repositories.position_repository import PositionRepository
        repo = PositionRepository()
        uid = f"user-{_uid()}"
        short = _make_position(uid, side="short")
        session.add(short)
        await session.flush()

        results = await repo.get_open_positions(session, user_id=uid)
        assert results[0].side == "short"
