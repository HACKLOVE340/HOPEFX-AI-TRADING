# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_orchestrator_symbol_isolation.py
================================================
``orchestrator.get_latest_tick(symbol)`` must never answer a non-gold request
with the gold price.

The orchestrator wraps a gold-only feed: ``_gold_feed.get_latest_tick()`` takes
no symbol and always returns XAU/USD. The in-memory fallback used to run for
any symbol, so a request that missed the Redis cache came back with the gold
tick relabelled as whatever was asked for, tagged ``"live"``.

That reached three places at once:

* ``api/ws_public.py`` — the public landing-page ticker showed one identical
  number for all eight of its symbols, because every one of them resolved to
  gold. The Redis lookup could never hit: the feed writes the compact form
  (``EURUSD``) while the ticker asks for the underscore form (``EUR_USD``).
* ``api/risk_calculator.py`` — position sizing against the wrong price.
* ``api/pnl_dashboard.py`` — per-symbol P&L against the wrong price.

A caller can handle "no price". It cannot detect a confidently wrong one.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


class _StubGoldFeed:
    """Mimics the real feed: get_latest_tick() takes no symbol argument."""

    def __init__(self, tick):
        self._tick = tick
        self.calls = 0

    def get_latest_tick(self):
        self.calls += 1
        return self._tick


def _orchestrator(monkeypatch, gold_tick):
    """A MarketDataOrchestrator with no Redis and a stubbed gold feed."""
    from data_layer.orchestrator import MarketDataOrchestrator

    orch = MarketDataOrchestrator.__new__(MarketDataOrchestrator)
    orch._gold_feed = _StubGoldFeed(gold_tick)

    class _NoRedis:
        _r = None

    orch._redis_store = _NoRedis()
    orch._norm = type("N", (), {"normalize_tick": staticmethod(lambda t: t)})()
    orch._on_tick = lambda _t: None
    return orch


@pytest.fixture
def gold_tick():
    from datetime import datetime, timezone

    from data_layer.orchestrator import FeedSource, GoldTick, TickQuality

    return GoldTick(
        symbol="XAU_USD",
        timestamp=datetime.now(timezone.utc),
        bid=4000.0,
        ask=4000.5,
        mid=4000.25,
        source=FeedSource.YAHOO,
        quality=TickQuality.GOOD,
        confidence=1.0,
        spread=0.5,
        lineage_id="test",
    )


@pytest.mark.parametrize("symbol", ["XAU_USD", "XAUUSD", "XAU/USD", "xau_usd", " XAU_USD "])
def test_gold_is_served_in_every_spelling(monkeypatch, gold_tick, symbol):
    """The gold path must keep working — this is the orchestrator's whole job."""
    orch = _orchestrator(monkeypatch, gold_tick)

    assert orch.get_latest_tick(symbol) is gold_tick


@pytest.mark.parametrize("symbol", ["EUR_USD", "GBP_USD", "BTC_USD", "USD_JPY", "XAG_USD", "EURUSD"])
def test_a_non_gold_symbol_never_receives_the_gold_price(monkeypatch, gold_tick, symbol):
    """The defect: every one of these used to come back priced as gold."""
    orch = _orchestrator(monkeypatch, gold_tick)

    result = orch.get_latest_tick(symbol)

    assert result is None, f"{symbol} was answered with the gold tick ({gold_tick.mid})"


def test_the_gold_feed_is_not_even_consulted_for_a_foreign_symbol(monkeypatch, gold_tick):
    """Guards the fix at the call site, not just the return value."""
    orch = _orchestrator(monkeypatch, gold_tick)

    orch.get_latest_tick("EUR_USD")

    assert orch._gold_feed.calls == 0


def test_public_ticker_symbols_do_not_all_collapse_to_one_price(monkeypatch, gold_tick):
    """End to end on the exact list the landing page subscribes to.

    Before the fix every symbol here returned the same gold tick, which is what
    made the public ticker show one number eight times.
    """
    from api.ws_public import PUBLIC_SYMBOLS

    orch = _orchestrator(monkeypatch, gold_tick)
    resolved = {s: orch.get_latest_tick(s) for s in PUBLIC_SYMBOLS}

    priced = {s: t for s, t in resolved.items() if t is not None}

    assert set(priced) == {"XAU_USD"}, (
        f"only gold may be served from the gold feed; these were also priced: {sorted(set(priced) - {'XAU_USD'})}"
    )


def test_is_gold_symbol_rejects_lookalikes():
    """XAG is silver and XPT is platinum — neither is gold."""
    from data_layer.orchestrator import _is_gold_symbol

    assert _is_gold_symbol("XAU_USD")
    assert not _is_gold_symbol("XAG_USD")
    assert not _is_gold_symbol("XPT_USD")
    assert not _is_gold_symbol("")
    assert not _is_gold_symbol(None)


# ── Redis tick key resolution ─────────────────────────────────────────────────
# Stopping non-gold symbols from being served the gold price (above) is only
# half the job: they then have to get their *own* price. The multi-source feed
# writes all twelve configured symbols to Redis under the compact spelling the
# feed config uses (`hopefx:dl:tick:EURUSD`), while callers ask in the
# underscore form (`EUR_USD`). Every read missed, so live ticks were collected
# and discarded for everything except gold — which resolved only because
# cache/market_data_cache.py writes the literal `XAU_USD`.


class _FakeRedisStore:
    """RedisStore with a dict standing in for Redis."""

    def __init__(self, stored: dict[str, str]):
        from data_layer.cache.redis_store import DataLayerRedisStore as RedisStore

        self._store = stored
        self.gets: list[str] = []
        self._safe_get = self._fake_get
        self._key = RedisStore._key.__get__(self)
        self.get_tick = RedisStore.get_tick.__get__(self)
        self._r = None

    def _fake_get(self, key: str):
        self.gets.append(key)
        return self._store.get(key)


def test_a_tick_written_by_the_feed_is_found_from_the_underscore_form():
    """The reported symptom: EUR_USD never resolved to the feed's EURUSD tick."""
    import json

    store = _FakeRedisStore({"hopefx:dl:tick:EURUSD": json.dumps({"mid": 1.0921})})

    assert store.get_tick("EUR_USD") == {"mid": 1.0921}


def test_the_slash_form_resolves_too():
    import json

    store = _FakeRedisStore({"hopefx:dl:tick:BTCUSD": json.dumps({"mid": 61000.0})})

    assert store.get_tick("BTC/USD") == {"mid": 61000.0}


def test_an_exact_key_is_never_shadowed_by_the_normalised_one():
    """Gold has both spellings written by different writers; the caller's wins."""
    import json

    store = _FakeRedisStore(
        {
            "hopefx:dl:tick:XAU_USD": json.dumps({"mid": 4000.0, "writer": "market_data_cache"}),
            "hopefx:dl:tick:XAUUSD": json.dumps({"mid": 4001.0, "writer": "multi_source_feed"}),
        }
    )

    assert store.get_tick("XAU_USD")["writer"] == "market_data_cache"


def test_the_compact_form_costs_no_extra_lookup():
    """A caller already using the feed's spelling must not pay for a fallback."""
    store = _FakeRedisStore({})

    store.get_tick("EURUSD")

    assert store.gets == ["hopefx:dl:tick:EURUSD"]


def test_a_genuine_miss_still_returns_none():
    store = _FakeRedisStore({})

    assert store.get_tick("EUR_USD") is None
    assert store.gets == ["hopefx:dl:tick:EUR_USD", "hopefx:dl:tick:EURUSD"]


def test_every_configured_feed_symbol_is_reachable_from_the_public_spelling():
    """End to end over the real config: each feed symbol resolves from EUR_USD form."""
    import json
    import re
    from pathlib import Path

    cfg = (Path(__file__).resolve().parents[2] / "config" / "multi_source_feed.yaml").read_text()
    feed_symbols = re.findall(r"^    ([A-Z]{6,8}):", cfg, re.M)
    assert feed_symbols, "no symbols parsed from multi_source_feed.yaml"

    # Redis as the feed leaves it: compact keys only.
    stored = {f"hopefx:dl:tick:{s}": json.dumps({"symbol": s}) for s in feed_symbols}
    store = _FakeRedisStore(stored)

    unresolved = []
    for s in feed_symbols:
        underscore = f"{s[:3]}_{s[3:]}" if len(s) == 6 else s
        if store.get_tick(underscore) is None:
            unresolved.append(underscore)

    assert not unresolved, f"feed writes these but callers cannot read them: {unresolved}"
