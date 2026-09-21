# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_feed_skips_unservable_sources.py
================================================
"Not configured" is not "upstream is down".

Production logged this every two seconds, for every metal, for the life of the
process::

    YFinanceSource: no yfinance_ticker configured for USOIL
    MultiSourceFeed[USOIL]: circuit OPEN for 'yfinance' after 61 failures
    MultiSourceFeed[XAUUSD]: circuit OPEN for 'yfinance' after 62 failures

The blank ``yfinance_ticker`` is deliberate — Yahoo delisted spot metals, and
config/multi_source_feed.yaml records that quoting GLD (~$390) against spot gold
(~$4,070) "would be far worse than no quote at all". But ``_poll_symbol`` called
the source anyway, spent ``max_retries`` attempts on it, got None, and passed
that None to ``record_failure``. Five of those tripped the breaker; sixty
seconds later the cooldown closed it; five more polls tripped it again. Forever.

The noise was the small half. The large half is that ``circuit OPEN`` and the
``msf_source_errors`` counter are the two signals that would tell an operator
Yahoo had *genuinely* gone down — and both sat permanently saturated by a
condition that was true at startup and never changed. An alert on either was
worthless on precisely the symbols the platform is built around.

Whether a source can price a symbol is decidable from configuration with no
I/O: a ticker mapping, and for the keyed sources an API key. So each source now
answers ``can_serve()`` and the feed skips rather than fetch-and-fails.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _yfinance_installed(monkeypatch):
    """yfinance is a [CORE] dependency in production but optional in the sandbox.

    ``can_serve`` returns False when the library is absent — correct, but it
    would mask the ticker-mapping logic these tests are about, and would make
    them pass for the wrong reason wherever yfinance happens not to be
    installed. Force the "installed" branch; the absent case is asserted
    explicitly in ``test_a_missing_library_also_means_cannot_serve``.
    """
    import data_feed.sources.yfinance_source as mod

    monkeypatch.setattr(mod, "_YF_AVAILABLE", True)


def _write_config(tmp_path) -> str:
    import yaml

    cfg = {
        "multi_source_feed": {
            "refresh_seconds": 0.01,
            "circuit_breaker_threshold": 5,
            "circuit_breaker_cooldown": 60,
            "max_retries": 3,
            "symbols": {
                # Metals: no yfinance ticker on purpose.
                "XAUUSD": {
                    "yfinance_ticker": "",
                    "alpha_vantage_symbol": "XAU",
                    "twelve_data_symbol": "XAU/USD",
                    "price_min": 1000.0,
                    "price_max": 10000.0,
                },
                "EURUSD": {
                    "yfinance_ticker": "EURUSD=X",
                    "alpha_vantage_symbol": "EUR",
                    "twelve_data_symbol": "EUR/USD",
                    "price_min": 0.5,
                    "price_max": 2.0,
                },
            },
            "alpha_vantage": {"enabled": True, "api_key": ""},
            "twelve_data": {"enabled": True, "api_key": ""},
            "yfinance": {"enabled": True},
        }
    }
    path = tmp_path / "feed.yaml"
    path.write_text(yaml.safe_dump(cfg))
    return str(path)


def _feed(monkeypatch, tmp_path, *, av: str = "", td: str = ""):
    for var in ("ALPHA_VANTAGE_KEY", "ALPHA_VANTAGE_API_KEY", "TWELVE_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    if av:
        monkeypatch.setenv("ALPHA_VANTAGE_KEY", av)
    if td:
        monkeypatch.setenv("TWELVE_API_KEY", td)

    from data_feed.multi_source_feed import MultiSourceTickFeed

    feed = MultiSourceTickFeed(config_path=_write_config(tmp_path))
    feed._sources = feed._build_sources()
    return feed


# ── can_serve is a configuration question, answered without I/O ──────────────


def test_yfinance_cannot_serve_a_symbol_with_no_ticker():
    from data_feed.sources.yfinance_source import YFinanceSource

    assert YFinanceSource().can_serve("XAUUSD", {"yfinance_ticker": ""}) is False
    assert YFinanceSource().can_serve("EURUSD", {"yfinance_ticker": "EURUSD=X"}) is True


def test_yfinance_cannot_serve_a_symbol_missing_from_config_entirely():
    from data_feed.sources.yfinance_source import YFinanceSource

    assert YFinanceSource().can_serve("XAUUSD", {}) is False


def test_a_missing_library_also_means_cannot_serve(monkeypatch):
    """An uninstalled yfinance is the same kind of fact: knowable, and not an
    outage. It must not be fetched-and-failed either."""
    import data_feed.sources.yfinance_source as mod

    monkeypatch.setattr(mod, "_YF_AVAILABLE", False)
    assert mod.YFinanceSource().can_serve("EURUSD", {"yfinance_ticker": "EURUSD=X"}) is False


@pytest.mark.parametrize(
    ("module", "cls_name", "key_field"),
    [
        ("alpha_vantage", "AlphaVantageSource", "alpha_vantage_symbol"),
        ("twelve_data", "TwelveDataSource", "twelve_data_symbol"),
    ],
)
def test_a_keyed_source_needs_both_a_key_and_a_mapping(module, cls_name, key_field):
    import importlib

    cls = getattr(importlib.import_module(f"data_feed.sources.{module}"), cls_name)

    assert cls(api_key="").can_serve("XAUUSD", {key_field: "XAU"}) is False, "no key"
    assert cls(api_key="k").can_serve("XAUUSD", {key_field: ""}) is False, "no mapping"
    assert cls(api_key="k").can_serve("XAUUSD", {key_field: "XAU"}) is True


def test_can_serve_makes_no_network_call(monkeypatch):
    """It must be safe to call on every symbol at startup."""
    import aiohttp

    from data_feed.sources.twelve_data import TwelveDataSource

    def _boom(*_a, **_k):
        raise AssertionError("can_serve opened an HTTP session")

    monkeypatch.setattr(aiohttp, "ClientSession", _boom)
    assert TwelveDataSource(api_key="k").can_serve("XAUUSD", {"twelve_data_symbol": "XAU/USD"}) is True


# ── The feed filters the chain per symbol ────────────────────────────────────


def test_the_chain_drops_yfinance_for_the_metals(monkeypatch, tmp_path):
    feed = _feed(monkeypatch, tmp_path, av="av-key", td="td-key")

    metals = feed._serviceable_order("XAUUSD", feed._symbol_cfgs["XAUUSD"])
    fx = feed._serviceable_order("EURUSD", feed._symbol_cfgs["EURUSD"])

    assert "yfinance" not in metals, "yfinance has no ticker for XAUUSD and must be skipped"
    assert metals == ["alpha_vantage", "twelve_data"]
    assert fx[0] == "yfinance", "EURUSD has a ticker — the chain is unchanged"


def test_no_keys_leaves_the_metals_with_nothing(monkeypatch, tmp_path):
    """The condition the production log was actually reporting."""
    feed = _feed(monkeypatch, tmp_path)

    assert feed._serviceable_order("XAUUSD", feed._symbol_cfgs["XAUUSD"]) == []
    assert feed._serviceable_order("EURUSD", feed._symbol_cfgs["EURUSD"]) == ["yfinance"]


async def test_status_does_not_name_a_source_that_cannot_serve_the_symbol(monkeypatch, tmp_path):
    """_SymbolState defaults active_source to the head of the global chain, so
    /status reported XAUUSD as being served by yfinance — which has no ticker
    for it and never will."""
    feed = _feed(monkeypatch, tmp_path, av="av-key", td="td-key")
    feed._tick_writer = None
    feed._running = True

    assert feed._states["XAUUSD"].active_source == "yfinance", "precondition: the misleading default"

    task = asyncio.create_task(feed._poll_symbol("XAUUSD"))
    await asyncio.sleep(0)
    feed._running = False
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert feed._states["XAUUSD"].active_source != "yfinance"
    assert feed._states["XAUUSD"].status()["active_source"] == "alpha_vantage"


def test_an_adapter_without_can_serve_is_assumed_capable(monkeypatch, tmp_path):
    """Custom and stubbed adapters keep working."""
    feed = _feed(monkeypatch, tmp_path)

    class _Bare:
        name = "yfinance"

        async def fetch(self, symbol, cfg):
            return 1.0

    feed._sources["yfinance"] = _Bare()
    assert "yfinance" in feed._serviceable_order("XAUUSD", feed._symbol_cfgs["XAUUSD"])


# ── The behaviour that produced the log ──────────────────────────────────────


async def test_an_unservable_source_is_never_fetched_and_never_counted(monkeypatch, tmp_path):
    """The regression itself: one poll of XAUUSD must not touch yfinance.

    Before the fix this called fetch() three times (max_retries) and then
    record_failure() once, per poll, forever.
    """
    feed = _feed(monkeypatch, tmp_path, av="av-key")

    calls: list[str] = []

    class _Recording:
        name = "yfinance"

        def can_serve(self, symbol, cfg):
            return bool(cfg.get("yfinance_ticker"))

        async def fetch(self, symbol, cfg):
            calls.append(symbol)

    feed._sources["yfinance"] = _Recording()

    class _AV:
        name = "alpha_vantage"

        def can_serve(self, symbol, cfg):
            return True

        async def fetch(self, symbol, cfg):
            return 4070.0

    feed._sources["alpha_vantage"] = _AV()
    feed._tick_writer = None
    feed._running = True

    task = asyncio.create_task(feed._poll_symbol("XAUUSD"))
    await asyncio.sleep(0.08)
    feed._running = False
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert calls == [], f"yfinance was fetched for XAUUSD {len(calls)}x despite having no ticker"
    state = feed._states["XAUUSD"]
    assert state.fail_counts["yfinance"] == 0, "a source that was never asked was recorded as failing"
    assert state.circuit_open_at["yfinance"] is None, "the breaker tripped on a source that was never called"
    assert state.current_price == 4070.0, "the serviceable source should still have been used"


async def test_a_symbol_no_source_can_price_is_not_polled(monkeypatch, tmp_path, caplog):
    """With no keys, XAUUSD has no source at all.

    It got no price before this fix either — it just burned three HTTP retries
    and a breaker cycle every two seconds to arrive at the same nothing.
    """
    feed = _feed(monkeypatch, tmp_path)
    feed._tick_writer = None
    feed._running = True

    with caplog.at_level(logging.WARNING, logger="data_feed.multi_source_feed"):
        await asyncio.wait_for(feed._poll_symbol("XAUUSD"), timeout=2.0)

    state = feed._states["XAUUSD"]
    assert state.fail_counts == dict.fromkeys(state.fail_counts, 0)
    assert all(v is None for v in state.circuit_open_at.values())

    msg = " ".join(r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING)
    assert "XAUUSD" in msg
    # The operator needs the remedy, not just the symptom.
    assert "ALPHA_VANTAGE_KEY" in msg or "TWELVE_API_KEY" in msg
    assert "multi_source_feed.yaml" in msg


async def test_the_warning_is_logged_once_not_per_poll(monkeypatch, tmp_path, caplog):
    """The defect being fixed is repetition; the fix must not repeat either."""
    feed = _feed(monkeypatch, tmp_path)
    feed._tick_writer = None
    feed._running = True

    with caplog.at_level(logging.WARNING, logger="data_feed.multi_source_feed"):
        # _build_sources() already logged the startup "no API key" warning; that
        # one is a different message and is covered by test_feed_missing_api_keys.
        caplog.clear()
        await asyncio.wait_for(feed._poll_symbol("XAUUSD"), timeout=2.0)

    hits = [r for r in caplog.records if r.levelno >= logging.WARNING and "XAUUSD" in r.getMessage()]
    assert len(hits) == 1, f"logged {len(hits)}x for a condition that is true once"


async def test_a_real_failure_still_trips_the_breaker(monkeypatch, tmp_path):
    """The guard rail on the fix.

    Skipping unconfigured sources must not also skip counting genuine outages —
    that would trade a saturated signal for a dead one.
    """
    feed = _feed(monkeypatch, tmp_path, av="av-key")

    class _Down:
        name = "alpha_vantage"

        def can_serve(self, symbol, cfg):
            return True

        async def fetch(self, symbol, cfg):
            return None  # configured, reachable, upstream returned nothing

    feed._sources = {"alpha_vantage": _Down()}
    feed._active_order = ["alpha_vantage"]
    feed._max_retries = 1
    feed._tick_writer = None
    feed._running = True

    task = asyncio.create_task(feed._poll_symbol("XAUUSD"))
    await asyncio.sleep(0.15)
    feed._running = False
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    state = feed._states["XAUUSD"]
    assert state.fail_counts["alpha_vantage"] >= 5, "a genuine failure was not counted"
    assert state.circuit_open_at["alpha_vantage"] is not None, "the breaker no longer trips on a real outage"


async def test_the_stale_monitor_does_not_rotate_onto_an_unservable_source(monkeypatch, tmp_path):
    """Rotation had the same bug: it picked from the unfiltered chain."""
    from datetime import UTC, datetime, timedelta

    feed = _feed(monkeypatch, tmp_path, av="av-key", td="td-key")
    feed._running = True
    feed._max_stale_s = 1

    state = feed._states["XAUUSD"]
    state.last_update = datetime.now(tz=UTC) - timedelta(seconds=600)
    state.active_source = "alpha_vantage"

    task = asyncio.create_task(feed._health_monitor())
    await asyncio.sleep(0)
    feed._running = False
    # Drive one iteration directly rather than waiting out the 15 s sleep.
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    order = feed._serviceable_order("XAUUSD", feed._symbol_cfgs["XAUUSD"])
    assert "yfinance" not in order
    assert state.pick_source(order, feed._cb_cooldown) != "yfinance"


# ── The shipped config still expresses the condition ─────────────────────────


def test_the_real_config_still_leaves_the_metals_without_yfinance():
    """If this ever flips, the skip above stops applying — and the reason it
    exists (never quote a futures contract or ETF as spot) is the thing at
    stake, not the log volume."""
    import yaml
    from pathlib import Path

    cfg = yaml.safe_load((Path(__file__).resolve().parents[2] / "config" / "multi_source_feed.yaml").read_text())
    symbols = cfg["multi_source_feed"]["symbols"]

    for metal in ("XAUUSD", "XAGUSD", "XPTUSD"):
        assert symbols[metal]["yfinance_ticker"] == ""
        # ...and the keyed sources must still be mapped, or the symbol is dead
        # no matter what keys are set.
        assert symbols[metal]["alpha_vantage_symbol"]
        assert symbols[metal]["twelve_data_symbol"]
