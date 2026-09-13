"""The crypto payment record's persistence, and the webhook gate that guards it.

`api/payments.py` sat at 66% coverage, below the repository's 80% gate, so any
change to it was blocked until someone raised it. What was untested was not
incidental: the three functions that read and write `crypto_payments` — the
exact-`Decimal` boundary included — the per-currency address dispatch, and the
HMAC gate that decides whether an unsigned webhook may confirm a payment.

These cover them by execution against a real sqlite database and real HMAC
digests, rather than by asserting the code is shaped a certain way.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit

UTC = timezone.utc


@pytest.fixture()
def db(tmp_path):
    """A real session factory over the crypto_payments table."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from database.models import Base

    engine = create_engine(f"sqlite:///{tmp_path}/payments.db")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _payment(payment_id: str = "PAY-1", **over) -> dict:
    base = {
        "payment_id": payment_id,
        "user_id": "user-1",
        "plan_id": "professional",
        "currency": "BTC",
        "network": "BTC",
        "address": "bc1qtest",
        # Floats, as they arrive from the live quote — this is the boundary.
        "amount_usd": 99.99,
        "amount_crypto": 0.00199998,
        "rate_usd": 50000.0,
        "status": "pending",
        "confirmations": 0,
        "confirmations_required": 2,
        "expires_at": (datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
    }
    base.update(over)
    return base


class TestTheExactDecimalBoundary:
    def test_a_float_quote_is_stored_exactly(self, db):
        """`Decimal(str(x))`, never `Decimal(x)`.

        `crypto_payments.amount_usd` is NUMERIC. `Decimal(99.99)` is
        99.9899999999999948840923025272786617279052734375, and handing that to
        an exact column puts back the drift the column type exists to remove.
        """
        from api import payments as mod

        with patch.object(mod, "_get_db_session", lambda: db()):
            mod._save_payment(_payment())
            loaded = mod._load_payment("PAY-1")

        assert loaded is not None, "the payment was never persisted"
        assert Decimal(str(loaded["amount_usd"])) == Decimal("99.99")

    def test_exact_passes_decimals_through_and_none_stays_none(self):
        from api.payments import _exact

        assert _exact(None) is None
        assert _exact(Decimal("1.25")) == Decimal("1.25")
        assert _exact(0.1) == Decimal("0.1"), "a float went through repr, not str"


class TestTheRecordSurvivesAndUpdates:
    def test_an_update_changes_only_what_it_names(self, db):
        from api import payments as mod

        with patch.object(mod, "_get_db_session", lambda: db()):
            mod._save_payment(_payment())
            mod._update_payment("PAY-1", status="confirmed", confirmations=3)
            loaded = mod._load_payment("PAY-1")

        assert loaded["status"] == "confirmed"
        assert loaded["confirmations"] == 3
        assert loaded["address"] == "bc1qtest"

    def test_updating_an_unknown_payment_is_a_no_op(self, db):
        from api import payments as mod

        with patch.object(mod, "_get_db_session", lambda: db()):
            mod._update_payment("PAY-does-not-exist", status="confirmed")
            assert mod._load_payment("PAY-does-not-exist") is None

    def test_loading_an_unknown_payment_returns_none(self, db):
        from api import payments as mod

        with patch.object(mod, "_get_db_session", lambda: db()):
            assert mod._load_payment("nope") is None


class TestNoDatabaseIsSurvivedRatherThanCrashed:
    """A payment API that raises when the database is down is worse than one
    that logs and carries on — but it must not claim to have persisted."""

    def test_save_without_a_session_does_not_raise(self):
        from api import payments as mod

        with patch.object(mod, "_get_db_session", lambda: None):
            mod._save_payment(_payment("PAY-nodb"))

    def test_load_and_update_without_a_session_are_quiet(self):
        from api import payments as mod

        with patch.object(mod, "_get_db_session", lambda: None):
            assert mod._load_payment("PAY-nodb") is None
            mod._update_payment("PAY-nodb", status="confirmed")


class TestTheSessionResolution:
    def test_app_state_is_preferred(self, db):
        from api import payments as mod
        from core.app_state import app_state

        with patch.object(app_state, "db_session_factory", db, create=True):
            session = mod._get_db_session()
        assert session is not None
        session.close()

    def test_a_broken_app_state_falls_back_to_session_local(self, db):
        """The fallback exists because app_state is absent in workers."""
        from api import payments as mod
        from core.app_state import app_state

        with patch.object(app_state, "db_session_factory", None, create=True):
            with patch("database.connection.SessionLocal", db, create=True):
                session = mod._get_db_session()
        assert session is not None
        session.close()


class TestTheWebhookGate:
    """`_verify_webhook_hmac` decides whether an unsigned request may confirm a
    payment. Its production branch is the one that matters and the one that had
    no test."""

    def test_a_correct_signature_is_accepted(self, monkeypatch):
        from api import payments as mod

        body = b'{"payment_id": "PAY-1"}'
        monkeypatch.setattr(mod, "_WEBHOOK_SECRET", "s" * 32, raising=False)
        sig = hmac.new(b"s" * 32, body, hashlib.sha256).hexdigest()
        assert mod._verify_webhook_hmac(body, sig) is True

    def test_a_wrong_signature_is_rejected(self, monkeypatch):
        from api import payments as mod

        monkeypatch.setattr(mod, "_WEBHOOK_SECRET", "s" * 32, raising=False)
        assert mod._verify_webhook_hmac(b'{"payment_id": "PAY-1"}', "00" * 32) is False

    def test_production_without_a_secret_rejects(self, monkeypatch):
        """Fail closed: a missing secret must never mean 'accept everything'."""
        from api import payments as mod

        monkeypatch.setattr(mod, "_WEBHOOK_SECRET", "", raising=False)
        monkeypatch.setenv("APP_ENV", "production")
        assert mod._verify_webhook_hmac(b"{}", "anything") is False

    def test_development_without_a_secret_still_rejects_unless_opted_out(self, monkeypatch):
        from api import payments as mod

        monkeypatch.setattr(mod, "_WEBHOOK_SECRET", "", raising=False)
        monkeypatch.setenv("APP_ENV", "development")
        monkeypatch.delenv("CRYPTO_WEBHOOK_VERIFY", raising=False)
        assert mod._verify_webhook_hmac(b"{}", "anything") is False

    def test_the_dev_bypass_requires_an_explicit_opt_out(self, monkeypatch):
        from api import payments as mod

        monkeypatch.setattr(mod, "_WEBHOOK_SECRET", "", raising=False)
        monkeypatch.setenv("APP_ENV", "development")
        monkeypatch.setenv("CRYPTO_WEBHOOK_VERIFY", "false")
        assert mod._verify_webhook_hmac(b"{}", "anything") is True


class TestTheAddressDispatch:
    @pytest.mark.parametrize(
        ("currency", "module", "client_name"),
        [
            ("BTC", "payments.crypto.bitcoin", "BitcoinClient"),
            ("ETH", "payments.crypto.ethereum", "EthereumClient"),
        ],
    )
    def test_each_currency_reaches_its_own_client(self, currency, module, client_name):
        from api.payments import _generate_address

        fake = SimpleNamespace(generate_deposit_address=lambda *a, **k: {"address": f"{currency.lower()}-addr"})
        with patch(f"{module}.{client_name}", lambda *a, **k: fake):
            assert _generate_address(currency, "user-1", currency) == f"{currency.lower()}-addr"

    def test_usdt_defaults_to_trc20_for_an_unknown_network(self):
        """An unrecognised network must not raise — it falls back, and the
        fallback is a named chain rather than whatever the caller sent."""
        from api.payments import _generate_address

        seen: dict = {}

        def _gen(user_id, net):
            seen["net"] = net
            return {"address": "usdt-addr"}

        fake = SimpleNamespace(generate_deposit_address=_gen)
        with patch("payments.crypto.usdt.USDTClient", lambda *a, **k: fake):
            from payments.crypto.usdt import USDTNetwork

            assert _generate_address("USDT", "user-1", "NOT_A_CHAIN") == "usdt-addr"
            assert seen["net"] is USDTNetwork.TRC20

    def test_an_unsupported_currency_raises(self):
        from api.payments import _generate_address

        with pytest.raises(ValueError, match="Unsupported currency"):
            _generate_address("DOGE", "user-1", "DOGE")
