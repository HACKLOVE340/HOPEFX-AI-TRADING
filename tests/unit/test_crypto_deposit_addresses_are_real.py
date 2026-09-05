# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
A crypto deposit address must be an address, not a string of the right shape.

F222 observed that `payments/crypto/address_generator.py` -- 271 lines that
generate crypto deposit addresses -- was never named in a single test file, and
noted that "a wrong crypto deposit address is an irrecoverable loss". Reading it
against the pinned dependency showed the situation was worse than unverified.

What the deposit endpoint actually returned, measured by calling it:

    BTC          'hopefx_btc_user-abc'
    ETH          '0x' + sha256("ETH" + user_id).hexdigest()[:40]
    USDT_TRC20   'T'  + sha256("TRC20" + user_id).hexdigest()[:33]
    USDT_ERC20   '0x' + sha256("ERC20" + user_id).hexdigest()[:40]

Three separate defects produced that:

1. `address_generator.py` and `bitcoin.py` were written against the hdwallet
   v1/v2 API (``HDWallet(symbol=...)``, ``from_path()``, ``p2wpkh_address()``).
   `requirements.txt` pins ``hdwallet>=3.6.1,<4.0.0``, where none of those
   exist. `_HDWALLET_AVAILABLE` was set from ``import hdwallet`` succeeding, so
   the module reported itself healthy while every call raised TypeError.

2. `api/billing.py` caught that TypeError and substituted
   ``f"hopefx_{currency.lower()}_{user.sub[:8]}"``, returning it with HTTP 200.

3. `ethereum.py` and `usdt.py` never derived at all -- they returned a SHA-256
   digest with a prefix. The ERC-20 form is indistinguishable from a real
   Ethereum address: 40 hex characters, accepted by every wallet and every
   validator, and no private key exists for it anywhere. That is the one that
   loses money silently, because nothing about the value looks wrong.

The tests below check derivation against the **published BIP test vectors** for
the standard BIP39 mnemonic, so they establish that the addresses are real
rather than merely well-formed. A shape check alone would have passed the
SHA-256 stub.
"""

from __future__ import annotations

import hashlib

import pytest

pytestmark = pytest.mark.unit

# The standard BIP39 test mnemonic. Its derived addresses are published in the
# BIP specifications and reproduced by every HD wallet implementation, which is
# what makes them usable as ground truth here.
TEST_MNEMONIC = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"

# Published vectors.
#   BTC: BIP84 specification, m/84'/0'/0'/0/0.
#   ETH: the canonical first account for this mnemonic, m/44'/60'/0'/0/0.
BIP84_BTC_INDEX_0 = "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu"
BIP44_ETH_INDEX_0 = "0x9858EfFD232B4033E47d90003D41EC34EcaEda94"

# The base58 alphabet. High-entropy by construction and not a secret; the
# detector cannot tell the difference, so it is marked rather than obfuscated.
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"  # pragma: allowlist secret


def _base58check_ok(address: str) -> bool:
    """Decode a base58check address and verify its checksum.

    Written out rather than imported so the test does not depend on the same
    library it is checking.
    """
    n = 0
    for ch in address:
        if ch not in _B58:
            return False
        n = n * 58 + _B58.index(ch)
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    raw = b"\x00" * (len(address) - len(address.lstrip("1"))) + raw
    if len(raw) < 5:
        return False
    body, checksum = raw[:-4], raw[-4:]
    return hashlib.sha256(hashlib.sha256(body).digest()).digest()[:4] == checksum


@pytest.fixture
def generator(monkeypatch, tmp_path):
    """An AddressGenerator with the test mnemonic and an isolated counter file."""
    import importlib

    monkeypatch.setenv("HOPEFX_CRYPTO_COUNTER_PATH", str(tmp_path / "counters.json"))
    for var in ("BITCOIN_MNEMONIC", "ETHEREUM_MNEMONIC", "TRON_MNEMONIC"):
        monkeypatch.setenv(var, TEST_MNEMONIC)
    module = importlib.import_module("payments.crypto.address_generator")
    monkeypatch.setattr(module, "_COUNTER_PATH", tmp_path / "counters.json")
    return module.AddressGenerator()


# ── Derivation is real ───────────────────────────────────────────────────────


def test_btc_matches_the_published_bip84_vector(generator):
    """If this fails, the wallet cannot spend what users deposit."""
    assert generator._derive("BTC", TEST_MNEMONIC, 0) == BIP84_BTC_INDEX_0


def test_eth_matches_the_published_bip44_vector(generator):
    assert generator._derive("ETH", TEST_MNEMONIC, 0) == BIP44_ETH_INDEX_0


def test_usdt_erc20_shares_the_ethereum_path(generator):
    """Documented behaviour: an ERC-20 token is received at the ETH address."""
    assert generator._derive("USDT_ERC20", TEST_MNEMONIC, 0) == BIP44_ETH_INDEX_0


def test_trc20_is_a_structurally_valid_tron_address(generator):
    """No published vector is pinned here on purpose.

    The Tron vector this test was almost written with turned out to be for a
    different derivation, and asserting a half-remembered constant against a
    library that had just reproduced two genuine published vectors would have
    been the test lying about the code. What *is* checkable without a vector is
    the Tron address format itself: base58check, 21 bytes, 0x41 version byte.
    """
    address = generator._derive("USDT_TRC20", TEST_MNEMONIC, 0)
    assert len(address) == 34
    assert address.startswith("T")
    assert _base58check_ok(address), f"{address} is not valid base58check"


def test_derivation_is_deterministic(generator):
    """Same mnemonic and index must always give the same address -- this is what
    makes the deposit history recoverable from the mnemonic alone."""
    assert generator._derive("BTC", TEST_MNEMONIC, 7) == generator._derive("BTC", TEST_MNEMONIC, 7)


def test_each_index_gives_a_different_address(generator):
    addresses = {generator._derive("ETH", TEST_MNEMONIC, i) for i in range(5)}
    assert len(addresses) == 5


# ── The specific fabricated values, pinned ───────────────────────────────────


def _executable_body(func) -> str:
    """The source of *func* with its docstring and comments removed.

    Both of the tests below nearly failed on their own explanations: the fixed
    code quotes the SHA-256 line it replaced, in a comment, so a plain
    substring search finds "hexdigest" and reports the defect it just verified
    was gone. Reading prose as if it were code is a mistake this audit has made
    four times (F255, F257, F262, F266); stripping the prose first is the fix.
    """
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    node = tree.body[0]
    if (
        node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    ):
        node.body = node.body[1:]  # drop the docstring
    return ast.unparse(node)  # comments are not represented in the AST at all


def test_the_sha256_stub_is_not_what_ethereum_returns_any_more():
    """The ERC-20 stub is the dangerous one: it is a valid-looking address."""
    stub = "0x" + hashlib.sha256(b"ETHuser-1").hexdigest()[:40]
    assert len(stub) == 42, "the stub was the right shape, which is why it survived"

    from payments.crypto.address_generator import _address_is_well_formed

    # It passes a shape check -- so a shape check was never going to catch it.
    assert _address_is_well_formed(stub, "ETH")

    import payments.crypto.ethereum as eth_mod

    body = _executable_body(eth_mod.EthereumClient.generate_deposit_address)
    assert "sha256" not in body, "generate_deposit_address still hashes instead of deriving"
    assert "address_generator" in body, "it no longer hashes, but it does not derive either"


def test_usdt_no_longer_hashes():
    import payments.crypto.usdt as usdt_mod

    body = _executable_body(usdt_mod.USDTClient.generate_deposit_address)
    assert "hexdigest" not in body, "generate_deposit_address still hashes instead of deriving"
    assert "address_generator" in body, "it no longer hashes, but it does not derive either"


def test_the_old_trc20_stub_was_not_even_base58():
    """Recorded because it changes the severity: a wallet would refuse to send
    to the TRC20 stub, so it broke deposits rather than losing funds. The ERC20
    stub had no such protection."""
    stub = "T" + hashlib.sha256(b"TRC20user-1").hexdigest()[:33]
    assert not _base58check_ok(stub)


# ── The clients the API actually calls ───────────────────────────────────────


def test_the_bitcoin_client_returns_a_real_address(monkeypatch, tmp_path):
    monkeypatch.setenv("HOPEFX_CRYPTO_COUNTER_PATH", str(tmp_path / "c.json"))
    monkeypatch.setenv("BITCOIN_MNEMONIC", TEST_MNEMONIC)
    from payments.crypto.bitcoin import BitcoinClient

    result = BitcoinClient().generate_deposit_address("user-1")
    assert result["address"].startswith("bc1"), result["address"]
    assert not result["address"].startswith("hopefx_")


def test_the_ethereum_client_returns_a_derived_address(monkeypatch, tmp_path):
    monkeypatch.setenv("HOPEFX_CRYPTO_COUNTER_PATH", str(tmp_path / "c.json"))
    monkeypatch.setenv("ETHEREUM_MNEMONIC", TEST_MNEMONIC)
    from payments.crypto.ethereum import EthereumClient

    address = EthereumClient().generate_deposit_address("user-1")["address"]
    stub = "0x" + hashlib.sha256(b"ETHuser-1").hexdigest()[:40]
    assert address != stub, "still returning the SHA-256 stub"
    assert address == BIP44_ETH_INDEX_0


def test_the_usdt_client_returns_a_derived_address(monkeypatch, tmp_path):
    monkeypatch.setenv("HOPEFX_CRYPTO_COUNTER_PATH", str(tmp_path / "c.json"))
    monkeypatch.setenv("TRON_MNEMONIC", TEST_MNEMONIC)
    from payments.crypto.usdt import USDTClient, USDTNetwork

    address = USDTClient().generate_deposit_address("user-1", USDTNetwork.TRC20)["address"]
    stub = "T" + hashlib.sha256(b"TRC20user-1").hexdigest()[:33]
    assert address != stub
    assert _base58check_ok(address)


# ── Refusing is the only safe failure ────────────────────────────────────────


def test_a_malformed_derived_address_is_never_returned(generator, monkeypatch):
    """The last line of defence. If derivation ever produces something that is
    not an address, raising is the only acceptable behaviour -- there is no
    value that can stand in for a deposit address."""
    monkeypatch.setattr(type(generator), "_derive", staticmethod(lambda *a, **k: "0xdeadbeef"))
    with pytest.raises(RuntimeError, match="Refusing to issue"):
        generator.generate_address("user-1", "ETH")


def test_an_unsupported_currency_is_rejected(generator):
    with pytest.raises(ValueError, match="Unsupported currency"):
        generator.generate_address("user-1", "DOGE")


def test_billing_does_not_fabricate_an_address_on_failure():
    """The `except Exception: address = f"hopefx_..."` branch, pinned so it
    cannot come back. A fabricated deposit address is worse than an error page:
    the user acts on it."""
    import inspect

    from api import billing

    src = inspect.getsource(billing)
    code = "\n".join(line for line in src.splitlines() if not line.lstrip().startswith("#"))
    assert 'f"hopefx_{currency.lower()}' not in code, "billing.py still fabricates a deposit address"


# ── Derivation-index durability ──────────────────────────────────────────────


def test_a_counter_that_cannot_be_written_refuses_to_issue(generator, monkeypatch):
    """`_save_counters` used to swallow the write error, with the comment "a
    failed write is recoverable on the next call". It is not: the in-memory
    counter has advanced, so a restart reloads the stale value and re-derives
    indices that were already handed out. Two users then share a deposit
    address and their funds cannot be told apart."""

    def boom(self):
        raise OSError("read-only volume")

    monkeypatch.setattr(type(generator), "_save_counters", boom)
    with pytest.raises(RuntimeError, match="Refusing to issue"):
        generator.generate_address("user-1", "ETH")


def test_a_failed_write_does_not_consume_the_index(generator, monkeypatch):
    """Rolled back, so a retry after the volume is fixed issues the index that
    was never handed out rather than skipping it."""
    before = generator._counters.get("ETH", 0)
    monkeypatch.setattr(type(generator), "_save_counters", lambda self: (_ for _ in ()).throw(OSError("full")))
    with pytest.raises(RuntimeError):
        generator.generate_address("user-1", "ETH")
    monkeypatch.undo()
    assert generator._counters.get("ETH", 0) == before


def test_indices_survive_a_restart(monkeypatch, tmp_path):
    """The module docstring promises "a process restart never reuses a
    derivation index and therefore never reuses a deposit address"."""
    import importlib

    counter = tmp_path / "counters.json"
    monkeypatch.setenv("HOPEFX_CRYPTO_COUNTER_PATH", str(counter))
    monkeypatch.setenv("ETHEREUM_MNEMONIC", TEST_MNEMONIC)
    module = importlib.import_module("payments.crypto.address_generator")
    monkeypatch.setattr(module, "_COUNTER_PATH", counter)

    first = {module.AddressGenerator().generate_address("u", "ETH") for _ in range(3)}
    # A fresh instance is what a process restart looks like to this class.
    second = {module.AddressGenerator().generate_address("u", "ETH") for _ in range(3)}
    assert not (first & second), f"addresses reissued after restart: {first & second}"


# ── The ephemeral-wallet hole ────────────────────────────────────────────────


@pytest.mark.parametrize("app_env", ["staging", "sandbox", "demo", "prod", "Production", ""])
def test_a_missing_mnemonic_is_refused_outside_development(monkeypatch, app_env):
    """The check was ``if app_env == "production": raise``, so every other value
    -- staging, a typo, an unset variable defaulting oddly -- fell through to an
    ephemeral wallet whose keys are discarded on restart. A staging deployment
    that takes one real deposit loses it, and the only signal was a log line."""
    from payments.crypto.address_generator import _load_mnemonic

    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.delenv("ETHEREUM_MNEMONIC", raising=False)
    with pytest.raises(RuntimeError, match="required when APP_ENV"):
        _load_mnemonic("ETH")


@pytest.mark.parametrize("app_env", ["development", "dev", "test", "local"])
def test_development_still_gets_an_ephemeral_wallet(monkeypatch, app_env):
    """Not a regression to fix: a dev box with no secrets must still boot."""
    from payments.crypto.address_generator import _load_mnemonic

    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.delenv("ETHEREUM_MNEMONIC", raising=False)
    assert len(_load_mnemonic("ETH").split()) >= 12


def test_a_configured_mnemonic_is_used_in_every_environment(monkeypatch):
    from payments.crypto.address_generator import _load_mnemonic

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ETHEREUM_MNEMONIC", TEST_MNEMONIC)
    assert _load_mnemonic("ETH") == TEST_MNEMONIC


def test_the_module_is_shadowed_by_its_own_singleton():
    """Not a defect, but it costs the next reader ten minutes.

    `payments/crypto/__init__.py` does ``from .address_generator import
    address_generator``, which rebinds the package attribute
    ``payments.crypto.address_generator`` from the module to the singleton.
    ``import payments.crypto.address_generator as m`` still yields the module
    (sys.modules wins), but ``payments.crypto.address_generator`` accessed as an
    attribute is the instance.
    """
    import sys

    import payments.crypto as pkg

    assert not isinstance(pkg.address_generator, type(sys.modules["payments.crypto.address_generator"]))
