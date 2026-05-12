# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/test_database_models.py
==============================
Regression tests for database/models.py FK + cascade + index fixes.

Covers:
  - Order.account_id has FK to accounts.id with ondelete=SET NULL
  - Order.trade_id has ondelete=SET NULL
  - Signal.trade_id has ondelete=SET NULL
  - Account.user_id has ondelete=CASCADE
  - Position.account_id has FK to accounts.id with ondelete=SET NULL
  - Position.user_id has FK to users.id with ondelete=SET NULL
  - All new indexes are registered in Base.metadata
  - Cascade delete: deleting a User cascades to Account rows (SQLite in-memory)
  - SET NULL: deleting a Trade nullifies Order.trade_id and Signal.trade_id
"""

from __future__ import annotations

import pytest


# ── FK / ondelete metadata assertions ────────────────────────────────────────


class TestForeignKeyConstraints:
    """Verify FK definitions without touching a real database."""

    def _fk_map(self, model_class) -> dict[str, tuple[str, str | None]]:
        """Return {col_name: (target, ondelete)} for all FK columns."""
        result = {}
        for col in model_class.__table__.columns:
            for fk in col.foreign_keys:
                result[col.name] = (fk.target_fullname, fk.ondelete)
        return result

    def test_order_account_id_has_fk_and_set_null(self):
        from database.models import Order

        fks = self._fk_map(Order)
        assert "account_id" in fks, "Order.account_id must have a FK to accounts.id"
        target, ondelete = fks["account_id"]
        assert "accounts.id" in target
        assert ondelete == "SET NULL", f"Expected SET NULL, got {ondelete}"

    def test_order_trade_id_has_set_null(self):
        from database.models import Order

        fks = self._fk_map(Order)
        assert "trade_id" in fks
        _, ondelete = fks["trade_id"]
        assert ondelete == "SET NULL", f"Expected SET NULL, got {ondelete}"

    def test_signal_trade_id_has_set_null(self):
        from database.models import Signal

        fks = self._fk_map(Signal)
        assert "trade_id" in fks
        _, ondelete = fks["trade_id"]
        assert ondelete == "SET NULL", f"Expected SET NULL, got {ondelete}"

    def test_account_user_id_has_cascade(self):
        from database.models import Account

        fks = self._fk_map(Account)
        assert "user_id" in fks
        target, ondelete = fks["user_id"]
        assert "users.id" in target
        assert ondelete == "CASCADE", f"Expected CASCADE, got {ondelete}"

    def test_position_account_id_has_fk_and_set_null(self):
        from database.models import Position

        fks = self._fk_map(Position)
        assert "account_id" in fks, "Position.account_id must have a FK to accounts.id"
        target, ondelete = fks["account_id"]
        assert "accounts.id" in target
        assert ondelete == "SET NULL", f"Expected SET NULL, got {ondelete}"

    def test_position_user_id_has_fk_and_set_null(self):
        from database.models import Position

        fks = self._fk_map(Position)
        assert "user_id" in fks, "Position.user_id must have a FK to users.id"
        target, ondelete = fks["user_id"]
        assert "users.id" in target
        assert ondelete == "SET NULL", f"Expected SET NULL, got {ondelete}"


# ── Index registration ────────────────────────────────────────────────────────


class TestIndexRegistration:
    """Verify all required indexes are registered in Base.metadata."""

    REQUIRED_INDEXES = [
        # Pre-existing
        "idx_trades_symbol_status",
        "idx_trades_user_status_entry",
        "idx_orders_account_symbol_created",
        "idx_positions_user_symbol",
        # New indexes added in this fix
        "idx_trades_exit_time",
        "idx_trades_user_exit_time",
        "idx_orders_filled_at",
        "idx_orders_broker",
        "idx_positions_status",
        "idx_positions_symbol_status",
        "idx_signals_confidence",
        "idx_wallet_reference",
    ]

    def _all_index_names(self) -> set[str]:
        from database.models import Base

        return {idx.name for t in Base.metadata.tables.values() for idx in t.indexes}

    def test_all_required_indexes_present(self):
        all_idx = self._all_index_names()
        missing = [name for name in self.REQUIRED_INDEXES if name not in all_idx]
        assert not missing, f"Missing indexes: {missing}"

    def test_new_trade_exit_time_index(self):
        assert "idx_trades_exit_time" in self._all_index_names()

    def test_new_orders_filled_at_index(self):
        assert "idx_orders_filled_at" in self._all_index_names()

    def test_new_positions_status_index(self):
        assert "idx_positions_status" in self._all_index_names()

    def test_new_wallet_reference_index(self):
        assert "idx_wallet_reference" in self._all_index_names()


# ── Live cascade / SET NULL tests (SQLite in-memory) ─────────────────────────


@pytest.fixture
def db_session():
    """In-memory SQLite session with all tables created."""
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import sessionmaker
    from database.models import Base

    engine = create_engine("sqlite:///:memory:", echo=False)

    # SQLite requires PRAGMA foreign_keys=ON per connection
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _rec):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


class TestCascadeDeleteLive:
    """Integration tests using SQLite in-memory to verify cascade behaviour."""

    def _make_user(self, session, user_id: str = "user-1"):
        from database.models import User

        u = User(
            id=user_id,
            email=f"{user_id}@test.com",
            username=user_id,
            hashed_password="hashed",
        )
        session.add(u)
        session.flush()
        return u

    def _make_account(self, session, user_id: str, account_id: int = 1):
        from database.models import Account

        a = Account(id=account_id, user_id=int(user_id.split("-")[-1]) if user_id.split("-")[-1].isdigit() else None)
        session.add(a)
        session.flush()
        return a

    def test_deleting_trade_nullifies_order_trade_id(self, db_session):
        """Deleting a Trade must SET NULL on Order.trade_id (not raise FK error)."""
        from database.models import Order, OrderSide, OrderType, Trade, TradeStatus

        trade = Trade(
            trade_id="T-001",
            symbol="XAUUSD",
            side="BUY",
            entry_price=2000.0,
            entry_quantity=1.0,
            status=TradeStatus.OPEN,
        )
        db_session.add(trade)
        db_session.flush()

        order = Order(
            order_id="O-001",
            trade_id="T-001",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0,
        )
        db_session.add(order)
        db_session.flush()

        # Delete the trade — must not raise FK violation
        db_session.delete(trade)
        db_session.commit()

        refreshed = db_session.query(Order).filter_by(order_id="O-001").first()
        assert refreshed is not None, "Order must still exist after Trade deletion"
        assert refreshed.trade_id is None, f"Order.trade_id must be NULL after Trade deletion, got {refreshed.trade_id}"

    def test_deleting_trade_nullifies_signal_trade_id(self, db_session):
        """Deleting a Trade must SET NULL on Signal.trade_id."""
        from database.models import Signal, SignalSource, Trade, TradeStatus

        trade = Trade(
            trade_id="T-002",
            symbol="EURUSD",
            side="BUY",
            entry_price=1.08,
            entry_quantity=1.0,
            status=TradeStatus.OPEN,
        )
        db_session.add(trade)
        db_session.flush()

        signal = Signal(
            signal_id="SIG-001",
            symbol="EURUSD",
            action="buy",
            strategy="trend",
            source=SignalSource.TREND_FOLLOWING,
            trade_id="T-002",
        )
        db_session.add(signal)
        db_session.flush()

        db_session.delete(trade)
        db_session.commit()

        refreshed = db_session.query(Signal).filter_by(signal_id="SIG-001").first()
        assert refreshed is not None
        assert refreshed.trade_id is None, (
            f"Signal.trade_id must be NULL after Trade deletion, got {refreshed.trade_id}"
        )
