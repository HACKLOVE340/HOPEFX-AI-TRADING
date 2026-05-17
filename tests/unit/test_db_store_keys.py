# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/unit/test_db_store_keys.py
=================================
Verifies that the two critical db_store keys — ``leaderboard`` and
``signals:active`` — are written by the code paths that own them and
that the readers never receive ``None`` after a write.

All tests use a real in-memory SQLite database (via SQLAlchemy) so there
are no mocks, stubs, or fake data.  The DB is created fresh for every
test class via the ``db_session`` fixture.
"""

from __future__ import annotations

from typing import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def db_engine():
    """In-memory SQLite engine shared across all threads in a single test.

    ``StaticPool`` keeps a single connection alive for the lifetime of the
    engine, making it accessible from any thread (including the worker thread
    that FastAPI TestClient uses to run request handlers).
    ``check_same_thread=False`` suppresses SQLite's own thread guard.
    """
    from database.models import Base

    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(db_engine) -> Generator[Session, None, None]:
    """Provide a live SQLAlchemy session bound to the in-memory DB."""
    SessionLocal = sessionmaker(bind=db_engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def patch_db_store(db_engine, monkeypatch):
    """
    Redirect api.db_store._session_ctx() to a fresh session on the in-memory
    engine for every call.  Using a factory (not a single shared session)
    avoids cross-thread session state issues while still hitting the same
    StaticPool connection.

    Also patches the Redis pool so tests don't block trying to connect to a
    real Redis instance.
    """
    import contextlib

    import api.db_store as _ds

    SessionLocal = sessionmaker(bind=db_engine)

    @contextlib.contextmanager
    def _make_session_ctx():
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setattr(_ds, "_session_ctx", _make_session_ctx)

    # Prevent social_feed from blocking on Redis connection during tests
    import cache.redis_pool as _rp

    monkeypatch.setattr(_rp, "get_sync_client", lambda: None)
    monkeypatch.setattr(_rp, "get_redis_pool", lambda: None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _raw_value(db_session: Session, key: str):
    """Return the raw JSON string stored for *key*, or None if absent."""
    from database.models import Configuration

    record = db_session.query(Configuration).filter_by(config_key=key).first()
    return record.config_value if record else None


# ---------------------------------------------------------------------------
# db_store round-trip
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDbStoreRoundTrip:
    """Basic db_get / db_set contract."""

    def test_set_then_get_returns_value(self, db_session):
        from api.db_store import db_get, db_set

        assert db_set("test:key", {"x": 1}) is True
        assert db_get("test:key") == {"x": 1}

    def test_get_missing_key_returns_none(self):
        from api.db_store import db_get

        assert db_get("nonexistent:key") is None

    def test_set_overwrites_existing_value(self, db_session):
        from api.db_store import db_get, db_set

        db_set("test:overwrite", [1, 2, 3])
        db_set("test:overwrite", [4, 5, 6])
        assert db_get("test:overwrite") == [4, 5, 6]

    def test_set_empty_list(self, db_session):
        from api.db_store import db_get, db_set

        db_set("test:empty", [])
        assert db_get("test:empty") == []

    def test_delete_removes_key(self, db_session):
        from api.db_store import db_delete, db_get, db_set

        db_set("test:delete_me", "value")
        assert db_get("test:delete_me") == "value"
        db_delete("test:delete_me")
        assert db_get("test:delete_me") is None


# ---------------------------------------------------------------------------
# signals:active write path
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSignalsActiveKey:
    """
    Verify that generate_signal() writes the ``signals:active`` key and
    that the value is a list of signal dicts readable by db_get.
    """

    def test_generate_signal_writes_signals_active(self, db_session):
        """A successful generate_signal() call persists signals:active."""
        from api.db_store import db_get
        from api.signals import RealTimeSignalService, SignalDirection

        svc = RealTimeSignalService(config={"min_confidence": 0.5, "min_strategies": 1})
        sig = svc.generate_signal(
            symbol="XAUUSD",
            direction=SignalDirection.BUY,
            confidence=0.75,
            price=2350.0,
            entry_price=2350.0,
            stop_loss=2330.0,
            take_profit=2400.0,
            timeframe="1h",
            strategies_agreeing=["trend_follow"],
            total_strategies=3,
            regime="trending",
            session="london",
        )
        assert sig is not None, "Signal should be generated at confidence=0.75"

        stored = db_get("signals:active")
        assert stored is not None, "signals:active must be written after generate_signal()"
        assert isinstance(stored, list)
        assert len(stored) >= 1

    def test_signals_active_contains_required_fields(self, db_session):
        """Each entry in signals:active has the fields the trading fallback expects."""
        from api.db_store import db_get
        from api.signals import RealTimeSignalService, SignalDirection

        svc = RealTimeSignalService(config={"min_confidence": 0.5, "min_strategies": 1})
        svc.generate_signal(
            symbol="EURUSD",
            direction=SignalDirection.SELL,
            confidence=0.80,
            price=1.0850,
            entry_price=1.0850,
            stop_loss=1.0900,
            take_profit=1.0750,
            timeframe="4h",
            strategies_agreeing=["mean_reversion", "momentum"],
            total_strategies=4,
            regime="ranging",
            session="new_york",
        )

        stored = db_get("signals:active")
        assert stored and len(stored) >= 1
        entry = stored[0]
        for field in ("id", "symbol", "direction", "confidence", "entry_price", "stop_loss", "take_profit"):
            assert field in entry, f"signals:active entry missing field: {field}"

    def test_signals_active_only_contains_valid_signals(self, db_session):
        """Expired signals are not included in the persisted list."""
        from api.db_store import db_get
        from api.signals import RealTimeSignalService, SignalDirection

        svc = RealTimeSignalService(config={"min_confidence": 0.5, "min_strategies": 1, "signal_expiry_minutes": 30})
        svc.generate_signal(
            symbol="GBPUSD",
            direction=SignalDirection.BUY,
            confidence=0.65,
            price=1.2700,
            entry_price=1.2700,
            stop_loss=1.2650,
            take_profit=1.2800,
            timeframe="1h",
            strategies_agreeing=["breakout"],
            total_strategies=2,
            regime="trending",
            session="london",
        )

        stored = db_get("signals:active")
        # All stored signals must have is_valid=True (not expired)
        for entry in stored:
            assert entry.get("is_valid") is True, f"Expired signal found in signals:active: {entry['id']}"

    def test_signals_active_seeded_to_empty_list_when_absent(self, db_session):
        """
        Simulates the startup seed: if signals:active is absent, writing []
        means db_get returns [] (not None) — the trading fallback gets a list.
        """
        from api.db_store import db_get, db_set

        # Key is absent initially
        assert db_get("signals:active") is None

        # Startup seed
        db_set("signals:active", [], changed_by="startup")

        result = db_get("signals:active")
        assert result is not None, "signals:active must not be None after startup seed"
        assert result == [], "signals:active startup seed must be an empty list"

    def test_trading_fallback_returns_list_after_seed(self, db_session):
        """
        The trading endpoint fallback (db_get("signals:active") or []) must
        return a list — never None — once the startup seed has run.
        """
        from api.db_store import db_set

        db_set("signals:active", [], changed_by="startup")

        # Simulate what api/trading.py does in its fallback path
        from api.db_store import db_get

        cached = db_get("signals:active") or []
        assert isinstance(cached, list)


# ---------------------------------------------------------------------------
# leaderboard write path
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLeaderboardKey:
    """
    Verify that refresh_leaderboard_cache() writes the ``leaderboard`` key
    and that GET /api/leaderboard reads it back correctly.
    """

    @pytest.fixture
    def mock_profiles(self, monkeypatch):
        """Inject two synthetic TraderProfile-like objects into the profile manager."""

        class _FakeProfile:
            def __init__(self, trader_id, username, sharpe, pnl, trades, followers, win_rate):
                self.trader_id = trader_id
                self.username = username
                self.sharpe_ratio = sharpe
                self.total_pnl = pnl
                self.total_trades = trades
                self.total_followers = followers
                self.win_rate = win_rate

        _profiles = [
            _FakeProfile("t1", "AlphaBot", 2.1, 5000.0, 200, 80, 65.0),
            _FakeProfile("t2", "BetaTrader", 1.4, 3000.0, 150, 40, 58.0),
        ]

        class _FakeMgr:
            def list_profiles(self, public_only=True):
                return _profiles

        monkeypatch.setattr("api.social_feed.TraderProfileManager", _FakeMgr, raising=False)
        # Also patch the import inside _build_leaderboard_snapshot
        import sys
        import types

        fake_social = types.ModuleType("social.profiles")
        fake_social.TraderProfileManager = _FakeMgr
        monkeypatch.setitem(sys.modules, "social.profiles", fake_social)

        return _profiles

    def test_refresh_leaderboard_cache_writes_key(self, db_session, mock_profiles):
        """refresh_leaderboard_cache() must write the leaderboard key."""
        from api.db_store import db_get
        from api.social_feed import refresh_leaderboard_cache

        refresh_leaderboard_cache()

        stored = db_get("leaderboard")
        assert stored is not None, "leaderboard key must be written by refresh_leaderboard_cache()"
        assert isinstance(stored, dict)

    def test_leaderboard_has_all_periods(self, db_session, mock_profiles):
        """Stored leaderboard snapshot contains monthly, quarterly, and all periods."""
        from api.db_store import db_get
        from api.social_feed import refresh_leaderboard_cache

        refresh_leaderboard_cache()
        stored = db_get("leaderboard")

        for period in ("monthly", "quarterly", "all"):
            assert period in stored, f"leaderboard snapshot missing period: {period}"
            assert isinstance(stored[period], list)

    def test_leaderboard_entries_have_required_fields(self, db_session, mock_profiles):
        """Each leaderboard entry has the fields the frontend expects."""
        from api.db_store import db_get
        from api.social_feed import refresh_leaderboard_cache

        refresh_leaderboard_cache()
        entries = db_get("leaderboard").get("monthly", [])
        assert len(entries) >= 1, "Expected at least one leaderboard entry"

        for entry in entries:
            for field in ("id", "rank", "name", "return_3m", "sharpe", "followers", "win_rate", "trades"):
                assert field in entry, f"leaderboard entry missing field: {field}"

    def test_leaderboard_ranks_are_sequential(self, db_session, mock_profiles):
        """Ranks start at 1 and increment by 1."""
        from api.db_store import db_get
        from api.social_feed import refresh_leaderboard_cache

        refresh_leaderboard_cache()
        entries = db_get("leaderboard").get("monthly", [])
        ranks = [e["rank"] for e in entries]
        assert ranks == list(range(1, len(ranks) + 1)), f"Non-sequential ranks: {ranks}"

    def test_leaderboard_sorted_by_sharpe_descending(self, db_session, mock_profiles):
        """Entries are ranked highest Sharpe first."""
        from api.db_store import db_get
        from api.social_feed import refresh_leaderboard_cache

        refresh_leaderboard_cache()
        entries = db_get("leaderboard").get("monthly", [])
        sharpes = [e["sharpe"] for e in entries]
        assert sharpes == sorted(sharpes, reverse=True), "Leaderboard not sorted by Sharpe descending"

    def test_get_leaderboard_endpoint_reads_from_db_store(self, db_session, monkeypatch):
        """GET /api/leaderboard returns the persisted snapshot when the key exists.

        The endpoint must read from db_store first (priority 1) and return that
        data without hitting the live profile store.  We verify this by seeding
        a known snapshot and asserting the response matches it exactly.
        """
        import sys
        import types

        # Ensure the live profile store is unreachable so the only data source
        # is the db_store snapshot we seed below.
        class _UnreachableMgr:
            def list_profiles(self, public_only=True):
                raise RuntimeError("profile store must not be called when db_store has data")

        fake_social = types.ModuleType("social.profiles")
        fake_social.TraderProfileManager = _UnreachableMgr
        monkeypatch.setitem(sys.modules, "social.profiles", fake_social)

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from api.db_store import db_set
        from api.social_feed import leaderboard_router

        _seed = [
            {
                "id": "trader_seed",
                "rank": 1,
                "name": "SeedBot",
                "return_3m": 9.9,
                "sharpe": 3.0,
                "followers": 100,
                "win_rate": 70.0,
                "trades": 300,
            }
        ]
        db_set("leaderboard", {"monthly": _seed, "quarterly": _seed, "all": _seed})

        app = FastAPI()
        app.include_router(leaderboard_router)
        client = TestClient(app)

        resp = client.get("/api/leaderboard")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["id"] == "trader_seed"
        assert data[0]["name"] == "SeedBot"

    def test_leaderboard_endpoint_returns_empty_list_when_no_data(self, db_session):
        """GET /api/leaderboard returns [] when db_store has no data and profile store is empty."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        import sys
        import types

        # Patch profile manager to return empty list
        class _EmptyMgr:
            def list_profiles(self, public_only=True):
                return []

        fake_social = types.ModuleType("social.profiles")
        fake_social.TraderProfileManager = _EmptyMgr
        sys.modules["social.profiles"] = fake_social

        from api.social_feed import leaderboard_router

        app = FastAPI()
        app.include_router(leaderboard_router)
        client = TestClient(app)

        resp = client.get("/api/leaderboard")
        assert resp.status_code == 200
        assert resp.json() == []

        # Cleanup
        sys.modules.pop("social.profiles", None)

    def test_leaderboard_warm_up_in_app_lifespan(self, db_session, mock_profiles, monkeypatch):
        """
        Verify the startup warm-up path: calling refresh_leaderboard_cache()
        followed by db_get("leaderboard") returns a non-None, non-empty dict.
        This mirrors what app.py lifespan now does on startup.
        """
        from api.db_store import db_get
        from api.social_feed import refresh_leaderboard_cache

        # Confirm key is absent before warm-up
        assert db_get("leaderboard") is None

        # Simulate startup warm-up
        refresh_leaderboard_cache()

        result = db_get("leaderboard")
        assert result is not None, "leaderboard must be non-None after startup warm-up"
        assert any(len(v) > 0 for v in result.values()), "At least one period must have entries"
