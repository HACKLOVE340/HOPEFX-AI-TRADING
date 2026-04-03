# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/integration/test_payments_integration.py
===============================================
Integration tests for the payments layer:
- CryptoPayment DB model round-trip (SQLite in-memory)
- OutboxEvent DB model round-trip
- ConfigStore DB model round-trip
- Rate feed → address generation → DB persistence flow
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
UTC = timezone.utc

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# ── DB fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def db_engine():
    """
    In-memory SQLite engine with all models created.

    Uses render_as_batch=True-compatible table creation.
    BigInteger maps to INTEGER in SQLite which supports autoincrement.
    """
    from sqlalchemy import event as sa_event

    from database.models import Base

    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
    )

    # Enable WAL mode and foreign keys for SQLite
    @sa_event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine):
    """Session with savepoint — rolled back after each test."""
    connection = db_engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection)
    session = Session()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


# ── CryptoPayment model tests ─────────────────────────────────────────────────


class TestCryptoPaymentModel:
    def _make_payment(self, payment_id: str = "PAY_int_001") -> dict:
        now = datetime.now(UTC)
        return {
            "payment_id": payment_id,
            "user_id": "user_int_001",
            "plan_id": "pro_monthly",
            "currency": "BTC",
            "network": "BTC",
            "address": "bc1qintegration123",
            "amount_usd": 99.0,
            "amount_crypto": 0.00147,
            "rate_usd": 67_500.0,
            "status": "pending",
            "confirmations": 0,
            "confirmations_required": 3,
            "expires_at": now + timedelta(minutes=30),
        }

    def test_create_and_retrieve_payment(self, db_session):
        """CryptoPayment can be created and retrieved by payment_id."""
        from database.models import CryptoPayment

        data = self._make_payment("PAY_create_001")
        record = CryptoPayment(**data)
        db_session.add(record)
        db_session.flush()

        retrieved = db_session.query(CryptoPayment).filter(CryptoPayment.payment_id == "PAY_create_001").first()
        assert retrieved is not None
        assert retrieved.currency == "BTC"
        assert retrieved.amount_usd == 99.0
        assert retrieved.status == "pending"

    def test_payment_id_is_unique(self, db_session):
        """Duplicate payment_id raises IntegrityError."""
        from sqlalchemy.exc import IntegrityError

        from database.models import CryptoPayment

        data = self._make_payment("PAY_unique_001")
        db_session.add(CryptoPayment(**data))
        db_session.flush()

        with pytest.raises(IntegrityError):
            db_session.add(CryptoPayment(**data))
            db_session.flush()

    def test_to_dict_returns_correct_fields(self, db_session):
        """CryptoPayment.to_dict() returns all expected fields."""
        from database.models import CryptoPayment

        data = self._make_payment("PAY_dict_001")
        record = CryptoPayment(**data)
        db_session.add(record)
        db_session.flush()

        d = record.to_dict()
        assert d["payment_id"] == "PAY_dict_001"
        assert d["currency"] == "BTC"
        assert d["status"] == "pending"
        assert d["confirmations"] == 0
        assert d["confirmations_required"] == 3
        assert "expires_at" in d

    def test_update_payment_status(self, db_session):
        """Payment status can be updated to 'complete'."""
        from database.models import CryptoPayment

        data = self._make_payment("PAY_update_001")
        record = CryptoPayment(**data)
        db_session.add(record)
        db_session.flush()

        record.status = "complete"
        record.confirmations = 3
        record.confirmed_at = datetime.now(UTC)
        db_session.flush()

        updated = db_session.query(CryptoPayment).filter(CryptoPayment.payment_id == "PAY_update_001").first()
        assert updated.status == "complete"
        assert updated.confirmations == 3
        assert updated.confirmed_at is not None

    def test_webhook_payload_stored_as_json(self, db_session):
        """webhook_payload field stores raw JSON string."""
        from database.models import CryptoPayment

        data = self._make_payment("PAY_webhook_001")
        record = CryptoPayment(**data)
        payload = {
            "payment_id": "PAY_webhook_001",
            "status": "complete",
            "tx_hash": "0xabc",
        }
        record.webhook_payload = json.dumps(payload)
        db_session.add(record)
        db_session.flush()

        retrieved = db_session.query(CryptoPayment).filter(CryptoPayment.payment_id == "PAY_webhook_001").first()
        stored = json.loads(retrieved.webhook_payload)
        assert stored["tx_hash"] == "0xabc"


# ── OutboxEvent model tests ───────────────────────────────────────────────────


class TestOutboxEventModel:
    def test_create_outbox_event(self, db_session):
        """OutboxEvent can be created and retrieved."""
        from database.models import OutboxEvent

        event = OutboxEvent(
            event_type="KILL_SWITCH",
            channel="hopefx:breach",
            payload=json.dumps({"reason": "drawdown exceeded"}),
            created_at=datetime.now(UTC),
            attempts=0,
        )
        db_session.add(event)
        db_session.flush()

        retrieved = db_session.query(OutboxEvent).filter(OutboxEvent.event_type == "KILL_SWITCH").first()
        assert retrieved is not None
        assert retrieved.channel == "hopefx:breach"
        assert retrieved.published_at is None
        assert retrieved.attempts == 0

    def test_outbox_event_published_at_update(self, db_session):
        """OutboxEvent.published_at can be set after relay."""
        from database.models import OutboxEvent

        event = OutboxEvent(
            event_type="AML_BLOCK",
            channel="hopefx:compliance",
            payload=json.dumps({"user_id": "u1", "amount": "5000"}),
            created_at=datetime.now(UTC),
            attempts=0,
        )
        db_session.add(event)
        db_session.flush()

        event.published_at = datetime.now(UTC)
        db_session.flush()

        retrieved = db_session.query(OutboxEvent).filter(OutboxEvent.event_type == "AML_BLOCK").first()
        assert retrieved.published_at is not None

    def test_unpublished_events_query(self, db_session):
        """Query for unpublished events returns only rows with published_at IS NULL."""
        from database.models import OutboxEvent

        published = OutboxEvent(
            event_type="ORDER_FILL",
            channel="hopefx:order",
            payload="{}",
            created_at=datetime.now(UTC),
            published_at=datetime.now(UTC),
            attempts=1,
        )
        unpublished = OutboxEvent(
            event_type="KILL_SWITCH",
            channel="hopefx:breach",
            payload="{}",
            created_at=datetime.now(UTC),
            attempts=0,
        )
        db_session.add_all([published, unpublished])
        db_session.flush()

        pending = db_session.query(OutboxEvent).filter(OutboxEvent.published_at.is_(None)).all()
        event_types = [e.event_type for e in pending]
        assert "KILL_SWITCH" in event_types
        assert "ORDER_FILL" not in event_types


# ── ConfigStore model tests ───────────────────────────────────────────────────


class TestConfigStoreModel:
    def test_create_and_retrieve_config(self, db_session):
        """ConfigStore can store and retrieve a JSON value."""
        from database.models import ConfigStore

        record = ConfigStore(
            key="risk_settings",
            value_json=json.dumps({"max_risk_per_trade": 2.0}),
            changed_by="admin",
        )
        db_session.add(record)
        db_session.flush()

        retrieved = db_session.query(ConfigStore).filter(ConfigStore.key == "risk_settings").first()
        assert retrieved is not None
        value = json.loads(retrieved.value_json)
        assert value["max_risk_per_trade"] == 2.0

    def test_config_key_is_unique(self, db_session):
        """Duplicate config key raises IntegrityError."""
        from sqlalchemy.exc import IntegrityError

        from database.models import ConfigStore

        db_session.add(ConfigStore(key="unique_key_test", value_json='{"a":1}'))
        db_session.flush()

        with pytest.raises(IntegrityError):
            db_session.add(ConfigStore(key="unique_key_test", value_json='{"b":2}'))
            db_session.flush()

    def test_update_config_value(self, db_session):
        """ConfigStore value can be updated in place."""
        from database.models import ConfigStore

        record = ConfigStore(
            key="auto_pause_config",
            value_json=json.dumps({"enabled": False, "minutes_before": 30}),
        )
        db_session.add(record)
        db_session.flush()

        record.value_json = json.dumps({"enabled": True, "minutes_before": 15})
        db_session.flush()

        updated = db_session.query(ConfigStore).filter(ConfigStore.key == "auto_pause_config").first()
        value = json.loads(updated.value_json)
        assert value["enabled"] is True
        assert value["minutes_before"] == 15


# ── Rate feed integration test ────────────────────────────────────────────────


class TestRateFeedIntegration:
    @pytest.mark.asyncio
    async def test_rate_feed_returns_positive_prices(self):
        """Live rate feed returns positive prices for all supported coins."""
        from unittest.mock import AsyncMock, patch

        mock_rates = {"BTC": 67_500.0, "ETH": 3_200.0, "USDT": 1.0}

        with patch(
            "payments.crypto.rate_feed._fetch_coingecko",
            new_callable=AsyncMock,
            return_value=mock_rates,
        ):
            from payments.crypto.rate_feed import get_rates

            rates = await get_rates(force_refresh=True)

        for coin, price in rates.items():
            assert price > 0, f"{coin} price must be positive"

    @pytest.mark.asyncio
    async def test_usdt_rate_is_approximately_one(self):
        """USDT rate is always 1.0."""
        from unittest.mock import AsyncMock, patch

        mock_rates = {"BTC": 67_500.0, "ETH": 3_200.0, "USDT": 1.0}

        with patch(
            "payments.crypto.rate_feed._fetch_coingecko",
            new_callable=AsyncMock,
            return_value=mock_rates,
        ):
            from payments.crypto.rate_feed import get_rates

            rates = await get_rates(force_refresh=True)

        assert abs(rates.get("USDT", 0) - 1.0) < 0.01
