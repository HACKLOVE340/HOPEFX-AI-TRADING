# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""A crypto order that cannot be saved must never reach the user.

``POST /api/billing/crypto/order`` derives a deposit address, builds an order
record, then persists it with ``api.db_store.db_set`` — twice: once into the
user's ``crypto_orders:{user_id}`` list, once under its own
``crypto_order:{order_id}`` key (the record ``GET /crypto/order/{order_id}``
reads back). ``db_set`` returns ``True``/``False`` and never raises (it swallows
every exception internally and returns ``False``), but the endpoint wrapped both
calls in::

    try:
        ...
        db_set(...)
        db_set(...)
    except Exception:  # nosec B110  # noqa: S110
        pass

so a ``False`` return — the normal, documented failure signal — was silently
discarded and the endpoint answered **200 with a live deposit address and
amount** for an order that exists nowhere. A user paying it sends funds to an
address ``GET /crypto/order/{order_id}`` can never look up, and the webhook (if
any) has no order to reconcile against.

Mirrors the decision and shape of
``test_crypto_payment_unpersisted_is_not_issued.py`` (api/payments.py,
§A11 item 1): fail closed, no address/amount reaches the client, and an ERROR
record names the order id.

This file does NOT touch ``payments/crypto/*`` or ``api/payments.py`` — those
are owned by a parallel fix (BTC address derivation).
"""

from __future__ import annotations

import logging
import uuid
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit

ADDRESS = "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh"  # pragma: allowlist secret  (public example, not a key)
FIXED_UUID = uuid.UUID("0123456789abcdef0123456789abcdef")
ORDER_ID = str(FIXED_UUID)


def _issued():
    """What the one issuing path returns: the address with its derivation."""
    from api.payments import IssuedAddress

    return IssuedAddress(ADDRESS, 7, "m/84'/0'/0'/0/7")


@pytest.fixture()
def client(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.auth import TokenPayload, get_current_user
    from api.billing import router

    # require_payments_configured() gates the route on a provider secret being set.
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_dummy")  # pragma: allowlist secret

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: TokenPayload(sub="payer-1", role="user")
    return TestClient(app)


def _create_order(client, *, db_set_result):
    """POST /api/billing/crypto/order with address derivation and db_set stubbed."""
    from api import billing as mod

    with (
        patch("api.payments._derive_deposit_address", return_value=_issued()),
        patch("api.db_store.db_set", return_value=db_set_result),
        patch.object(mod._uuid, "uuid4", return_value=FIXED_UUID),
    ):
        return client.post("/api/billing/crypto/order", json={"currency": "BTC", "amount_usd": 100.0})


def test_a_failed_save_issues_no_order(client, caplog):
    """``db_set`` returns False (its documented failure signal) for both writes.

    Pre-fix, this passed straight through a bare ``except Exception: pass`` and
    the endpoint returned 200 with the address and amount for an order that was
    never written anywhere.
    """
    with caplog.at_level(logging.DEBUG, logger="api.billing"):
        response = _create_order(client, db_set_result=False)

    assert response.status_code == 503, (
        f"an order that could not be saved was answered {response.status_code}: {response.text}"
    )
    body = response.text
    assert ADDRESS not in body, "the deposit address reached the user for an unrecorded order"
    for field in ("address", "amount_usd", "order_id"):
        assert field not in response.json(), f"{field} was returned for an unrecorded order"

    errors = [r for r in caplog.records if r.name == "api.billing" and r.levelno >= logging.ERROR]
    assert errors, "the refusal left no ERROR record"
    assert any(ORDER_ID in r.getMessage() for r in errors), (
        f"no ERROR record names {ORDER_ID}: {[r.getMessage() for r in errors]}"
    )


def test_a_persisted_order_is_still_issued_and_is_on_record(client):
    """The control must refuse the failure, not the flow: an order that WAS
    written is returned, and it can be read back by its id."""
    from api import db_store

    store: dict[str, object] = {}

    def _fake_db_set(key, value, changed_by="system"):
        store[key] = value
        return True

    def _fake_db_get(key):
        return store.get(key)

    from api import billing as mod

    with (
        patch("api.payments._derive_deposit_address", return_value=_issued()),
        patch("api.db_store.db_set", side_effect=_fake_db_set),
        patch("api.db_store.db_get", side_effect=_fake_db_get),
        patch.object(mod._uuid, "uuid4", return_value=FIXED_UUID),
    ):
        response = client.post("/api/billing/crypto/order", json={"currency": "BTC", "amount_usd": 100.0})

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["order_id"] == ORDER_ID
    assert data["address"] == ADDRESS
    assert data["amount_usd"] == 100.0

    assert store.get(f"crypto_order:{ORDER_ID}") is not None, "an order was issued that is not on record"
    assert store[f"crypto_order:{ORDER_ID}"]["address"] == ADDRESS
    assert db_store  # keep the import referenced (used only for its module identity above)
