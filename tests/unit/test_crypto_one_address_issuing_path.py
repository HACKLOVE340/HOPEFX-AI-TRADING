# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Both crypto checkout routes issue addresses through ONE function, and both record the derivation.

MASTER_OUTSTANDING §A11, owner item (d). Two routes hand a user a deposit address:

* ``POST /api/payments/crypto/address`` -- stored the address with its HD
  derivation index and path (migration ``c8d9e0f1a2b3``);
* ``POST /api/billing/crypto/order`` -- stored the address only. It called
  ``api.payments._generate_address``, which threw the index and path away.

An address with no recorded derivation cannot be attributed to a payment
without re-deriving every index until one matches, and cannot be swept without
the same search. So both routes now call
``payments.crypto.address_generator.issue_deposit_address`` -- which reserves
the index, derives the address and returns address, index and path together --
and both persist all three. They draw from the same index space, so a payment
from one route and an order from the other can never share an address.

Only the BIP39 test mnemonic is used here; it is published and holds nothing.
"""

from __future__ import annotations

import importlib
from unittest.mock import AsyncMock, patch

import pytest
import sqlalchemy as sa

pytestmark = pytest.mark.unit

pytest.importorskip("hdwallet")

TEST_MNEMONIC = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"


@pytest.fixture()
def wallet(monkeypatch, tmp_path):
    """A test wallet on a SQLite database, so the index source is the file lock."""
    from sqlalchemy.orm import sessionmaker

    from core.app_state import app_state

    monkeypatch.setenv("HOPEFX_CRYPTO_COUNTER_PATH", str(tmp_path / "crypto_counters.json"))
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_dummy")  # pragma: allowlist secret
    for var in ("BITCOIN_MNEMONIC", "ETHEREUM_MNEMONIC", "TRON_MNEMONIC"):
        monkeypatch.setenv(var, TEST_MNEMONIC)
    engine = sa.create_engine(f"sqlite:///{tmp_path}/payments.db")
    monkeypatch.setattr(app_state, "db_engine", engine, raising=False)
    monkeypatch.setattr(app_state, "db_session_factory", sessionmaker(bind=engine), raising=False)
    yield
    engine.dispose()


@pytest.fixture()
def client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.auth import TokenPayload, get_current_user
    from api.billing import router as billing_router
    from api.payments import router as payments_router

    app = FastAPI()
    app.include_router(payments_router)
    app.include_router(billing_router)
    app.dependency_overrides[get_current_user] = lambda: TokenPayload(sub="payer-1", role="user")
    return TestClient(app)


@pytest.fixture()
def issuer_calls(monkeypatch):
    """Record every call to the one issuing function, and let it run."""
    # ``payments.crypto.address_generator`` the package attribute is the
    # singleton instance, not the module, so fetch the module itself.
    mod = importlib.import_module("payments.crypto.address_generator")

    real = getattr(mod, "issue_deposit_address", None)
    calls: list[tuple] = []
    if real is None:  # no single issuing function: nothing to spy on, and the call count says so
        return calls

    def spy(user_id, currency, network=None):
        result = real(user_id, currency, network)
        calls.append((currency, network, result))
        return result

    monkeypatch.setattr(mod, "issue_deposit_address", spy)
    return calls


@pytest.fixture()
def saved():
    """Capture what each route persists, without a schema."""
    payments: list[dict] = []
    store: dict[str, object] = {}

    def fake_db_set(key, value, changed_by="system"):
        store[key] = value
        return True

    with (
        patch("api.payments._save_payment", side_effect=payments.append),
        patch("api.db_store.db_set", side_effect=fake_db_set),
        patch("api.db_store.db_get", side_effect=store.get),
        patch(
            "payments.crypto.rate_feed.get_rates",
            AsyncMock(return_value={"BTC": 50_000.0, "ETH": 2_500.0, "USDT": 1.0}),
        ),
    ):
        yield payments, store


def _payment(client, currency):
    r = client.post("/api/payments/crypto/address", json={"currency": currency, "plan_id": "professional"})
    assert r.status_code == 200, r.text
    return r.json()


def _order(client, currency):
    r = client.post("/api/billing/crypto/order", json={"currency": currency, "amount_usd": 100.0})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize(
    ("currency", "path_prefix"),
    [("BTC", "m/84'/0'/0'/0/"), ("ETH", "m/44'/60'/0'/0/")],
)
def test_both_routes_draw_distinct_indices_from_one_space_and_record_them(
    wallet, client, issuer_calls, saved, currency, path_prefix
):
    payments, store = saved
    first = _payment(client, currency)
    order = _order(client, currency)
    second = _payment(client, currency)

    # Both routes went through the one issuing function, once per request.
    assert [c[0] for c in issuer_calls] == [currency] * 3, issuer_calls

    # The payment route recorded the derivation it issued.
    assert [p["derivation_index"] for p in payments] == [0, 2]
    assert [p["derivation_path"] for p in payments] == [f"{path_prefix}0", f"{path_prefix}2"]
    assert [p["address"] for p in payments] == [first["address"], second["address"]]

    # The billing route recorded it too -- on the order it can be read back by.
    recorded = store[f"crypto_order:{order['order_id']}"]
    assert recorded["derivation_index"] == 1, recorded
    assert recorded["derivation_path"] == f"{path_prefix}1"
    assert recorded["address"] == order["address"]
    assert "derivation_index" not in order and "derivation_path" not in order, (
        "the derivation is for reconciliation, not the payer -- the payments route does not return it either"
    )
    listed = store["crypto_orders:payer-1"]
    assert listed[-1]["derivation_index"] == 1

    # One space: three requests, three indices, three addresses.
    assert len({first["address"], order["address"], second["address"]}) == 3


def test_eth_and_usdt_erc20_across_the_two_routes_share_one_space(wallet, client, issuer_calls, saved):
    """ETH and USDT_ERC20 derive the same path from the same mnemonic, so a
    USDT_ERC20 payment and an ETH order must not both get index 0."""
    payments, store = saved
    r = client.post(
        "/api/payments/crypto/address", json={"currency": "USDT", "network": "ERC20", "plan_id": "professional"}
    )
    assert r.status_code == 200, r.text
    order = _order(client, "ETH")
    recorded = store[f"crypto_order:{order['order_id']}"]
    assert payments[0]["derivation_index"] == 0
    assert recorded["derivation_index"] == 1
    assert payments[0]["address"] != order["address"]


def test_the_issuing_function_returns_address_index_and_path_together(wallet):
    from payments.crypto.address_generator import AddressGenerator, issue_deposit_address

    issued = [issue_deposit_address("u", "BTC"), issue_deposit_address("u", "BTC")]
    assert [(d.index, d.path) for d in issued] == [(0, "m/84'/0'/0'/0/0"), (1, "m/84'/0'/0'/0/1")]
    assert [d.address for d in issued] == [AddressGenerator._derive("BTC", TEST_MNEMONIC, i) for i in (0, 1)]


@pytest.mark.parametrize(
    ("currency", "network", "chain_key"),
    [
        ("BTC", None, "BTC"),
        ("ETH", None, "ETH"),
        ("USDT", "ERC20", "USDT_ERC20"),
        ("USDT", "TRC20", "USDT_TRC20"),
        ("USDT", "mainnet", "USDT_TRC20"),  # billing's network; TRC20 as before
        ("USDT", None, "USDT_TRC20"),
    ],
)
def test_checkout_currencies_map_to_the_chain_they_always_used(currency, network, chain_key):
    from payments.crypto.address_generator import deposit_chain_key

    assert deposit_chain_key(currency, network) == chain_key


def test_an_unsupported_currency_is_refused():
    from payments.crypto.address_generator import deposit_chain_key

    with pytest.raises(ValueError, match="Unsupported currency"):
        deposit_chain_key("DOGE", None)


def test_the_billing_route_still_refuses_when_it_cannot_record(wallet, client):
    """Fail closed is unchanged: no record, no address."""
    with patch("api.db_store.db_set", return_value=False), patch("api.db_store.db_get", return_value=None):
        r = client.post("/api/billing/crypto/order", json={"currency": "BTC", "amount_usd": 100.0})
    assert r.status_code == 503, r.text
    assert "address" not in r.json()
