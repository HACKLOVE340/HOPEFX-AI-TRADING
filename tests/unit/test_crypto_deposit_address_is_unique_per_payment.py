# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Every crypto deposit request gets an address no other request has been given.

A deposit address is how an incoming on-chain payment is attributed to a user
and to a payment. Two requests that share an address cannot be told apart at
reconciliation: whoever sent the funds, the platform cannot say whose they were.

Three ways that was broken, each reproduced by execution before the fix:

1. **BTC was always index 0.** ``POST /api/payments/crypto/address`` built a
   fresh ``BitcoinClient`` per request, and the client chose its derivation
   index as ``len(self.user_addresses.get(user_id, []))`` -- per instance and
   per user, so it was 0 for every request from every user. Every BTC deposit
   request on the platform received ``m/84'/0'/0'/0/0``.
2. **The shared counter was per process.** ``AddressGenerator`` read the counter
   file once, at construction, and incremented in memory. Two uvicorn workers
   (or any two instances) each started from the same on-disk value and issued
   the same indices; the ``threading.Lock`` only serialised threads of one
   instance.
3. **ETH and USDT_ERC20 are one derivation chain with two counters.** Both
   derive ``m/44'/60'/0'/0/{index}`` from ``ETHEREUM_MNEMONIC``, so ETH index 0
   and USDT_ERC20 index 0 are the same address.

Only the BIP39 test mnemonic is used here -- it is published in the BIP
specifications and holds nothing.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
import threading
import time
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

pytestmark = pytest.mark.unit

pytest.importorskip("hdwallet")

TEST_MNEMONIC = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
REPO = Path(__file__).resolve().parents[2]


@pytest.fixture()
def counter(monkeypatch, tmp_path) -> Path:
    path = tmp_path / "crypto_counters.json"
    monkeypatch.setenv("HOPEFX_CRYPTO_COUNTER_PATH", str(path))
    monkeypatch.setenv("APP_ENV", "test")
    for var in ("BITCOIN_MNEMONIC", "ETHEREUM_MNEMONIC", "TRON_MNEMONIC"):
        monkeypatch.setenv(var, TEST_MNEMONIC)
    return path


def _btc_at(index: int) -> str:
    from payments.crypto.address_generator import AddressGenerator

    return AddressGenerator._derive("BTC", TEST_MNEMONIC, index)


# ── (a) sequential requests ──────────────────────────────────────────────────


def test_sequential_btc_requests_from_different_users_get_different_addresses(counter):
    from api.payments import _generate_address

    addresses = [_generate_address("BTC", f"user-{i}", "BTC") for i in range(8)]
    assert len(set(addresses)) == len(addresses), f"BTC addresses reused across users: {addresses}"


def test_the_same_user_asking_twice_gets_two_addresses(counter):
    """One address per payment, not per user: two payments by one user must be
    distinguishable too."""
    from api.payments import _generate_address

    first = _generate_address("BTC", "user-1", "BTC")
    second = _generate_address("BTC", "user-1", "BTC")
    assert first != second


def test_btc_indices_increase_monotonically_from_the_shared_counter(counter):
    from payments.crypto.bitcoin import BitcoinClient

    results = [BitcoinClient().generate_deposit_address(f"u{i}") for i in range(4)]
    assert [r["derivation_index"] for r in results] == [0, 1, 2, 3]
    assert [r["derivation_path"] for r in results] == [f"m/84'/0'/0'/0/{i}" for i in range(4)]
    assert [r["address"] for r in results] == [_btc_at(i) for i in range(4)]


def test_btc_shares_one_counter_with_the_address_generator(counter):
    """One mechanism, not two: the gateway path (``address_generator``) and the
    API path (``BitcoinClient``) draw BTC indices from the same counter."""
    from payments.crypto.address_generator import AddressGenerator
    from payments.crypto.bitcoin import BitcoinClient

    via_generator = AddressGenerator().generate_address("u1", "BTC")
    via_client = BitcoinClient().generate_deposit_address("u2")["address"]
    assert via_generator != via_client
    assert {via_generator, via_client} == {_btc_at(0), _btc_at(1)}


def test_eth_and_usdt_erc20_never_share_an_address(counter):
    """Same mnemonic, same path template: they are one chain and must share one
    counter, or ETH index n and USDT_ERC20 index n are the same address."""
    from payments.crypto.address_generator import AddressGenerator

    gen = AddressGenerator()
    issued = [gen.generate_address(f"u{i}", c) for i, c in enumerate(["ETH", "USDT_ERC20", "ETH", "USDT_ERC20"])]
    assert len(set(issued)) == 4, f"an ERC-20 address was re-issued: {issued}"


def test_an_existing_split_counter_file_resumes_past_both(counter):
    """A counter file written before ETH and USDT_ERC20 were merged holds two
    keys. The next index on that chain must be past BOTH, or it re-issues an
    address the larger one already handed out."""
    import json

    from payments.crypto.address_generator import AddressGenerator

    counter.write_text(json.dumps({"ETH": 2, "USDT_ERC20": 5}))
    reserved = AddressGenerator().reserve_address("u", "ETH")
    assert reserved.index == 5
    assert json.loads(counter.read_text()) == {"ETH": 6, "USDT_ERC20": 6}


# ── (b) concurrent requests ──────────────────────────────────────────────────


def test_concurrent_btc_requests_get_distinct_addresses(counter):
    from api.payments import _generate_address

    n = 16
    barrier = threading.Barrier(n)
    out: list[str] = []
    errors: list[BaseException] = []

    def worker(i: int) -> None:
        try:
            barrier.wait()
            out.append(_generate_address("BTC", f"user-{i}", "BTC"))
        except BaseException as exc:  # surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    assert len(out) == n
    assert len(set(out)) == n, f"{n - len(set(out))} BTC addresses issued twice under concurrency"


def test_separate_generator_instances_never_reuse_an_index(counter):
    """Each instance stands in for a worker process: it has its own lock and its
    own memory, and shares only the counter file. Every instance is built
    BEFORE any reserves, which is how N workers look after a deploy."""
    from payments.crypto.address_generator import AddressGenerator

    n_instances, per = 8, 10
    gens = [AddressGenerator() for _ in range(n_instances)]
    barrier = threading.Barrier(n_instances)
    out: list[int] = []
    lock = threading.Lock()

    def worker(gen) -> None:
        barrier.wait()
        for _ in range(per):
            idx = gen._next_index("BTC")
            with lock:
                out.append(idx)

    threads = [threading.Thread(target=worker, args=(g,)) for g in gens]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(out) == list(range(n_instances * per)), f"indices reused: {sorted(out)}"


def test_separate_processes_never_reuse_an_index(counter, tmp_path):
    """The real thing: OS processes sharing only the counter file. Each builds
    its generator, then waits for a start file, so all of them hold whatever
    they read at construction before any of them reserves."""
    go = tmp_path / "go"
    script = textwrap.dedent(
        f"""
        import sys, time
        from pathlib import Path
        sys.path.insert(0, {str(REPO)!r})
        from payments.crypto.address_generator import AddressGenerator
        gen = AddressGenerator()
        go = Path({str(go)!r})
        deadline = time.time() + 60
        while not go.exists() and time.time() < deadline:
            time.sleep(0.01)
        print(" ".join(str(gen._next_index("BTC")) for _ in range(15)))
        """
    )
    procs = [
        subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for _ in range(4)
    ]
    time.sleep(1.5)  # let every process import and construct its generator
    go.write_text("go")
    indices: list[int] = []
    for p in procs:
        stdout, stderr = p.communicate(timeout=120)
        assert p.returncode == 0, stderr
        indices.extend(int(x) for x in stdout.split())
    assert len(indices) == 60, indices
    assert sorted(indices) == list(range(60)), f"indices reused across processes: {sorted(indices)}"


# ── (c) durability across restart ────────────────────────────────────────────


def test_the_btc_counter_survives_a_new_client_and_generator(counter, monkeypatch):
    """A new BitcoinClient -- or a new process -- continues from the file."""
    import json

    from payments.crypto.bitcoin import BitcoinClient

    before = {BitcoinClient().generate_deposit_address("u")["address"] for _ in range(3)}
    assert json.loads(counter.read_text())["BTC"] == 3

    # Drop every module-level singleton, as a restart would (restored after).
    for name in [m for m in sys.modules if m.startswith("payments.crypto")]:
        monkeypatch.delitem(sys.modules, name)
    from payments.crypto.bitcoin import BitcoinClient as Fresh

    after = Fresh().generate_deposit_address("u")
    assert after["derivation_index"] == 3
    assert after["address"] not in before


def test_a_deleted_counter_file_is_refused_not_restarted_at_zero(counter):
    """If the file this process has been writing disappears, starting again at
    0 would re-issue every address already handed out. Refuse instead."""
    from payments.crypto.address_generator import AddressGenerator

    gen = AddressGenerator()
    gen.reserve_address("u", "BTC")
    counter.unlink()
    with pytest.raises(RuntimeError, match="Refusing to issue"):
        gen.reserve_address("u", "BTC")


def test_a_corrupt_counter_file_is_refused_not_restarted_at_zero(counter):
    from payments.crypto.address_generator import AddressGenerator

    counter.write_text("{not json")
    with pytest.raises(RuntimeError, match="Refusing to issue"):
        AddressGenerator().reserve_address("u", "BTC")


def test_an_unwritable_counter_refuses_btc_too(counter, monkeypatch):
    from payments.crypto.address_generator import AddressGenerator
    from payments.crypto.bitcoin import BitcoinClient

    def boom(self, *a, **k):
        raise OSError("read-only volume")

    monkeypatch.setattr(AddressGenerator, "_save_counters", boom)
    with pytest.raises(RuntimeError, match="Refusing to issue"):
        BitcoinClient().generate_deposit_address("u")


# ── (d) the endpoint: persisted index, fail-closed save, no reuse ────────────


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


def _factory(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from database.models import Base

    engine = create_engine(f"sqlite:///{tmp_path}/payments.db")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _post(client, session_source, payment_uuid: uuid.UUID):
    from api import payments as mod

    with (
        patch("payments.crypto.rate_feed.get_rates", AsyncMock(return_value={"BTC": 50_000.0})),
        patch.object(mod, "_get_db_session", session_source),
        patch.object(mod.uuid, "uuid4", return_value=payment_uuid),
    ):
        return client.post("/api/payments/crypto/address", json={"currency": "BTC", "plan_id": "professional"})


def test_the_endpoint_records_the_index_and_never_reuses_a_refused_one(counter, client, tmp_path):
    from api import payments as mod

    factory = _factory(tmp_path)
    ok1, refused, ok2 = (uuid.UUID(int=i + 1) for i in range(3))

    first = _post(client, lambda: factory(), ok1)
    assert first.status_code == 200, first.text
    assert first.json()["address"] == _btc_at(0)

    # The save fails: nothing is issued, and index 1 is spent.
    second = _post(client, lambda: None, refused)
    assert second.status_code == 503, second.text
    assert _btc_at(1) not in second.text

    third = _post(client, lambda: factory(), ok2)
    assert third.status_code == 200, third.text
    assert third.json()["address"] == _btc_at(2), "the refused request's index was reused"
    assert third.json()["address"] != first.json()["address"]

    with patch.object(mod, "_get_db_session", lambda: factory()):
        rec1 = mod._load_payment(f"PAY_{ok1.hex}")
        rec3 = mod._load_payment(f"PAY_{ok2.hex}")
        assert mod._load_payment(f"PAY_{refused.hex}") is None
    assert rec1["derivation_index"] == 0
    assert rec1["derivation_path"] == "m/84'/0'/0'/0/0"
    assert rec3["derivation_index"] == 2
    assert rec3["derivation_path"] == "m/84'/0'/0'/0/2"


def test_an_address_with_no_known_index_is_not_issued(counter, client, tmp_path):
    """A deposit address whose derivation index is unknown cannot be swept or
    reconciled. If a client ever returns one without it, refuse."""
    from api import payments as mod

    factory = _factory(tmp_path)
    bare = type("Bare", (), {"generate_deposit_address": lambda self, uid: {"address": _btc_at(0)}})
    with patch("payments.crypto.bitcoin.BitcoinClient", bare):
        response = _post(client, lambda: factory(), uuid.UUID(int=9))
    assert response.status_code == 503, response.text
    assert _btc_at(0) not in response.text
    with patch.object(mod, "_get_db_session", lambda: factory()):
        assert mod._load_payment(f"PAY_{uuid.UUID(int=9).hex}") is None
