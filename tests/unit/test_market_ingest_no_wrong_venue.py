# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_market_ingest_no_wrong_venue.py
================================================
The gold feed substituted a crypto exchange and reconnected forever.

``INGEST_EXCHANGE`` defaults to ``oanda`` and ccxt.pro has no ``oanda``
exchange, so ``_build_exchange_ws`` took its fallback branch — described in the
comment as "a public exchange that carries XAU/USD" — and returned
``ccxtpro.bitfinex``. Bitfinex is a crypto exchange and does not list XAU/USD.
Production then produced this, indefinitely::

    ccxt.pro has no 'oanda' exchange — falling back to bitfinex for XAU/USD
    MarketIngest WS error: bitfinex does not have market symbol XAU/USD
      — reconnecting in 2.0 s        (then 4.0, 8.0, 16.0 …)
    STALE FEED: no tick for 10.2 s on XAU/USD

Two separate defects, and the second is the one that hid the first:

1. A fallback venue that cannot serve the symbol is not a fallback.
2. ``_ws_loop`` retried it with exponential back-off, so a configuration error
   presented as a flaky network. Waiting longer never makes an exchange exist.

Config errors now raise ``IngestConfigurationError`` and stop the loop; genuine
connection errors still retry.
"""

from __future__ import annotations

import asyncio

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def ingest_mod(monkeypatch):
    import data.market_ingest as mod

    monkeypatch.setattr(mod, "_INGEST_RUNNING", False, raising=False)
    return mod


def _new_ingest(mod):
    """Build a MarketIngest without touching credential resolution."""
    obj = mod.MarketIngest.__new__(mod.MarketIngest)
    obj._exchange = None
    obj._running = True
    obj._tick_count = 0
    obj._last_tick = None
    obj._api_key = ""
    obj._api_secret = ""
    obj._account_id = ""
    obj._practice = True
    obj._staleness = mod._StalenessGuard()
    return obj


# ── No silent substitution ───────────────────────────────────────────────────


def test_an_unknown_exchange_raises_instead_of_substituting(ingest_mod, monkeypatch):
    class _NoOanda:
        bitfinex = object()  # present, and must NOT be chosen

    monkeypatch.setattr(ingest_mod, "ccxtpro", _NoOanda())
    monkeypatch.setattr(ingest_mod, "EXCHANGE_ID", "oanda")

    with pytest.raises(ingest_mod.IngestConfigurationError) as exc:
        _new_ingest(ingest_mod)._build_exchange_ws()

    message = str(exc.value)
    assert "oanda" in message
    assert "INGEST_EXCHANGE" in message, "the error must say which setting to change"


def test_bitfinex_is_never_selected_for_a_metal(ingest_mod, monkeypatch):
    """The specific substitution that caused the outage."""
    chosen = []

    class _Fake:
        def bitfinex(self, *a, **k):
            chosen.append("bitfinex")
            return object()

    monkeypatch.setattr(ingest_mod, "ccxtpro", _Fake())
    monkeypatch.setattr(ingest_mod, "EXCHANGE_ID", "oanda")

    with pytest.raises(ingest_mod.IngestConfigurationError):
        _new_ingest(ingest_mod)._build_exchange_ws()
    assert chosen == [], "a crypto exchange was selected to stream XAU/USD"


def test_a_supported_exchange_is_still_built(ingest_mod, monkeypatch):
    built = {}

    class _Ex:
        def __init__(self, config):
            built["config"] = config

    class _Fake:
        binance = _Ex

    monkeypatch.setattr(ingest_mod, "ccxtpro", _Fake())
    monkeypatch.setattr(ingest_mod, "EXCHANGE_ID", "binance")

    obj = _new_ingest(ingest_mod)._build_exchange_ws()
    assert isinstance(obj, _Ex)
    assert "options" in built["config"]


# ── The loop must stop, not spin ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_configuration_error_stops_the_loop(ingest_mod, monkeypatch):
    """Without this, the better error message would simply be printed forever."""
    attempts = {"n": 0}

    def _boom(self):
        attempts["n"] += 1
        raise ingest_mod.IngestConfigurationError("no such exchange")

    monkeypatch.setattr(ingest_mod.MarketIngest, "_build_exchange_ws", _boom)

    ingest = _new_ingest(ingest_mod)
    await asyncio.wait_for(ingest._ws_loop(), timeout=5)

    assert attempts["n"] == 1, f"the loop retried a configuration error {attempts['n']} times"
    assert ingest._running is False


@pytest.mark.asyncio
async def test_a_transient_error_still_retries(ingest_mod, monkeypatch):
    """The back-off is right for a dropped socket — only config errors are fatal."""
    attempts = {"n": 0}

    def _flaky(self):
        attempts["n"] += 1
        if attempts["n"] >= 3:
            self._running = False
        raise ConnectionResetError("socket dropped")

    monkeypatch.setattr(ingest_mod.MarketIngest, "_build_exchange_ws", _flaky)
    monkeypatch.setattr(ingest_mod, "WS_RECONNECT_BASE", 0.001)
    monkeypatch.setattr(ingest_mod, "WS_RECONNECT_MAX", 0.002)

    ingest = _new_ingest(ingest_mod)
    await asyncio.wait_for(ingest._ws_loop(), timeout=5)

    assert attempts["n"] == 3, "a transient connection error should have been retried"
