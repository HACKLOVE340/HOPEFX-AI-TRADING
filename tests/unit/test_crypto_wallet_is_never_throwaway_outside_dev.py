# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""No deposit address is ever derived from a throwaway wallet outside local dev/test.

MASTER_OUTSTANDING §A11, owner item (c). ``payments/crypto/bitcoin.py`` had its
own ``_load_mnemonic``::

    if env == "production":
        raise RuntimeError(...)
    mnemonic = generate_mnemonic(...)   # every other APP_ENV

so a **staging** deployment with no ``BITCOIN_MNEMONIC`` derived BTC deposit
addresses from a wallet generated at start-up and never stored. Its private
keys die with the process: a real deposit sent there is unrecoverable, and the
only signal was a WARNING. ``address_generator._load_mnemonic`` (ETH, USDT)
already refused staging, but treated an UNSET ``APP_ENV`` as development.

The rule now, for every chain: an ephemeral wallet only when ``APP_ENV`` says,
explicitly, that this is local development or a test run. Anything else --
staging, a typo, unset -- refuses and names the variable to set. ``APP_ENV`` is
read through ``utils.production_guard.current_env``, which treats unset as
``production``.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

pytest.importorskip("hdwallet")

TEST_MNEMONIC = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"

_REFUSED_ENVS = ["staging", "stage", "sandbox", "demo", "prod", "production", "Staging", ""]
_DEV_ENVS = ["development", "dev", "test", "testing", "local"]


@pytest.mark.parametrize("app_env", _REFUSED_ENVS)
def test_bitcoin_refuses_a_throwaway_wallet_outside_dev(monkeypatch, app_env):
    from payments.crypto import bitcoin

    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.delenv("BITCOIN_MNEMONIC", raising=False)
    with pytest.raises(RuntimeError, match="BITCOIN_MNEMONIC"):
        bitcoin._load_mnemonic()


def test_a_staging_bitcoin_client_cannot_be_built_without_a_mnemonic(monkeypatch):
    """The path a request takes: no client, so no address, so no deposit."""
    from payments.crypto.bitcoin import BitcoinClient

    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.delenv("BITCOIN_MNEMONIC", raising=False)
    with pytest.raises(RuntimeError, match="BITCOIN_MNEMONIC"):
        BitcoinClient()


@pytest.mark.parametrize(
    ("currency", "env_var"),
    [
        ("BTC", "BITCOIN_MNEMONIC"),
        ("ETH", "ETHEREUM_MNEMONIC"),
        ("USDT_ERC20", "ETHEREUM_MNEMONIC"),
        ("USDT_TRC20", "TRON_MNEMONIC"),
    ],
)
def test_an_unset_app_env_is_not_development(monkeypatch, currency, env_var):
    """Unset is not an explicit statement that this is a dev box. A deployment
    that forgot ``APP_ENV`` is far more likely than a developer who needs it."""
    from payments.crypto.address_generator import _load_mnemonic

    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv(env_var, raising=False)
    with pytest.raises(RuntimeError, match=env_var):
        _load_mnemonic(currency)


def test_an_unset_app_env_refuses_bitcoin_too(monkeypatch):
    from payments.crypto import bitcoin

    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("BITCOIN_MNEMONIC", raising=False)
    with pytest.raises(RuntimeError, match="BITCOIN_MNEMONIC"):
        bitcoin._load_mnemonic()


@pytest.mark.parametrize("app_env", _DEV_ENVS)
def test_local_development_and_tests_still_get_an_ephemeral_wallet(monkeypatch, app_env):
    """Not a regression to fix: a dev box or a test run with no secrets still works."""
    from payments.crypto import bitcoin
    from payments.crypto.address_generator import _load_mnemonic

    monkeypatch.setenv("APP_ENV", app_env)
    for var in ("BITCOIN_MNEMONIC", "ETHEREUM_MNEMONIC", "TRON_MNEMONIC"):
        monkeypatch.delenv(var, raising=False)
    assert len(bitcoin._load_mnemonic().split()) >= 12
    assert len(_load_mnemonic("ETH").split()) >= 12
    assert len(_load_mnemonic("USDT_TRC20").split()) >= 12


@pytest.mark.parametrize("app_env", ["staging", "production", ""])
def test_a_configured_mnemonic_is_used_everywhere(monkeypatch, app_env):
    from payments.crypto import bitcoin

    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv("BITCOIN_MNEMONIC", TEST_MNEMONIC)
    assert bitcoin._load_mnemonic() == TEST_MNEMONIC
