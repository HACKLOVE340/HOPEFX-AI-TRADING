# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""A crypto payment the platform has no record of must never reach the user.

``POST /api/payments/crypto/address`` derives a deposit address, prices it, and
calls ``api/payments.py::_save_payment``. That helper used to catch a failed
insert (logged at ERROR) or a missing session (logged at WARNING, "DB
unavailable — payment %s not persisted") and simply return, so the endpoint
answered **200 with a live address and amount** for a payment that existed
nowhere. A user paying it sends funds to an address the webhook cannot match to
any record — MASTER_OUTSTANDING §A11, "Still open" item 1.

The owner's decision is fail closed: if the record cannot be written, the
payment is not issued, and an ERROR names the payment id and the reason.

Both failure shapes are exercised by execution rather than by a mocked
``commit``: a real sqlite database whose ``crypto_payments`` table is absent
raises the genuine ``OperationalError`` an unmigrated or broken database raises,
and a ``None`` session is exactly what ``_get_db_session`` returns when neither
``app_state`` nor ``SessionLocal`` can supply one. A success case against a real
table sits beside them, so a fix that refuses everything cannot pass.
"""

from __future__ import annotations

import logging
import uuid
from unittest.mock import AsyncMock, patch

import pytest

pytestmark = pytest.mark.unit

# A public, well-formed bech32 example address (not a key, not ours).
ADDRESS = "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh"  # pragma: allowlist secret
FIXED_UUID = uuid.UUID("0123456789abcdef0123456789abcdef")
PAYMENT_ID = f"PAY_{FIXED_UUID.hex}"


@pytest.fixture()
def client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.auth import TokenPayload, get_current_user
    from api.payments import router

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: TokenPayload(sub="payer-1", role="user")
    return TestClient(app)


def _sessionmaker(tmp_path, *, with_tables: bool):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(f"sqlite:///{tmp_path}/payments.db")
    if with_tables:
        from database.models import Base

        Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _request_address(client, session_source):
    from api import payments as mod

    with (
        patch("payments.crypto.rate_feed.get_rates", AsyncMock(return_value={"BTC": 50_000.0})),
        patch.object(mod, "_generate_address", return_value=ADDRESS),
        patch.object(mod, "_get_db_session", session_source),
        patch.object(mod.uuid, "uuid4", return_value=FIXED_UUID),
    ):
        return client.post("/api/payments/crypto/address", json={"currency": "BTC", "plan_id": "professional"})


def _assert_refused_and_logged(response, caplog):
    assert response.status_code == 503, f"a payment with no record was answered {response.status_code}: {response.text}"
    body = response.text
    assert ADDRESS not in body, "the deposit address reached the user for an unrecorded payment"
    for field in ("amount_crypto", "min_deposit", "qr_code"):
        assert field not in response.json(), f"{field} was returned for an unrecorded payment"

    errors = [r for r in caplog.records if r.name == "api.payments" and r.levelno >= logging.ERROR]
    assert errors, "the refusal left no ERROR record"
    assert any(PAYMENT_ID in r.getMessage() for r in errors), (
        f"no ERROR record names {PAYMENT_ID}: {[r.getMessage() for r in errors]}"
    )


def test_a_failed_insert_issues_no_payment(client, tmp_path, caplog):
    """The database is reachable and the INSERT itself fails (no such table)."""
    factory = _sessionmaker(tmp_path, with_tables=False)

    with caplog.at_level(logging.DEBUG, logger="api.payments"):
        response = _request_address(client, lambda: factory())

    _assert_refused_and_logged(response, caplog)
    assert any("no such table" in r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR), (
        "the ERROR does not say why the payment was not persisted"
    )


def test_no_database_session_issues_no_payment(client, caplog):
    """``_get_db_session`` found neither app_state nor SessionLocal."""
    with caplog.at_level(logging.DEBUG, logger="api.payments"):
        response = _request_address(client, lambda: None)

    _assert_refused_and_logged(response, caplog)


def test_a_persisted_payment_is_still_issued_and_is_on_record(client, tmp_path):
    """The control must refuse the failure, not the flow: a payment that WAS
    written is returned, and the id the user sees is the id on record."""
    from api import payments as mod

    factory = _sessionmaker(tmp_path, with_tables=True)
    response = _request_address(client, lambda: factory())

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["payment_id"] == PAYMENT_ID
    assert data["address"] == ADDRESS

    with patch.object(mod, "_get_db_session", lambda: factory()):
        stored = mod._load_payment(PAYMENT_ID)
    assert stored is not None, "a payment was issued that is not on record"
    assert stored["address"] == ADDRESS
    assert stored["user_id"] == "payer-1"
