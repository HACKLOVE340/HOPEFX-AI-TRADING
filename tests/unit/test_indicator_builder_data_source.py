# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_indicator_builder_data_source.py
================================================
The indicator builder had no data source in production either.

``_load_ohlcv_for_indicator`` tried two things:

1. ``data/XAU_USD_H1.csv`` / ``data/XAUUSD_H1.csv`` — neither is in the
   repository. The committed XAUUSD series are ``_2Y``, ``_5Y``, ``_40Y``,
   ``_50Y`` and ``XAU_USD_M``; none matches the ``_H1`` pattern the loader
   builds.
2. ``broker.get_market_data()`` — which ``PaperTradingBroker`` raises on under
   ``APP_ENV=production``, by design, so synthetic bars never reach the UI.

The RuntimeError from (2) was caught and logged at DEBUG, so at production log
levels neither attempt left a trace. The only thing anyone saw was::

    No OHLCV data available for XAUUSD.
    Connect a broker or add a CSV file to data/ to use the indicator builder.

on a deployment that had a connected broker and a working OHLCV source the
whole time — the same ``price_engine.get_ohlcv`` already serving
``/api/trading/ohlcv``. The advice in the message was wrong in both halves.

The engine is now tier 1. The broker tier is skipped outright in production
rather than called-and-caught, so the reason stays visible, and the failure
message names what was actually tried.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.unit


class _Bar:
    def __init__(self, close: float, volume: float = 100.0) -> None:
        self.timestamp = 0
        self.open = close
        self.high = close + 1
        self.low = close - 1
        self.close = close
        self.volume = volume


def _engine(bars):
    async def _get_ohlcv(symbol, timeframe, limit):
        return bars

    return SimpleNamespace(get_ohlcv=_get_ohlcv)


def _install(monkeypatch, *, engine=None, broker=None):
    """Set price_engine / broker on the real app_state singleton.

    Note `import core.app_state as st` does NOT give you the module here —
    core/__init__.py rebinds the name to the AppState instance, so patching
    "st.app_state" would set an attribute on the object rather than replace the
    singleton the loader imports. Reach the module through sys.modules.
    """
    import sys

    state = sys.modules["core.app_state"].app_state
    monkeypatch.setattr(state, "price_engine", engine, raising=False)
    monkeypatch.setattr(state, "broker", broker, raising=False)


def _no_csv(monkeypatch, tmp_path=None):
    """Make the ``_H1.csv`` tier miss, deterministically.

    Without this the result would depend on which CSVs happen to be checked
    out — exactly the ambiguity that let this defect sit unnoticed. Only the
    ``_H1`` names the loader builds are hidden; every other path check is
    delegated untouched.
    """
    import pathlib

    real_exists = pathlib.Path.exists

    def _exists(self, *args, **kwargs):
        if self.name.endswith("_H1.csv"):
            return False
        return real_exists(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "exists", _exists)


# ── The price engine is now the first source ─────────────────────────────────


async def test_the_price_engine_supplies_the_bars(monkeypatch, tmp_path):
    from api.advanced_trading import _load_ohlcv_for_indicator

    _no_csv(monkeypatch, tmp_path)
    _install(monkeypatch, engine=_engine([_Bar(4000.0 + i) for i in range(60)]))

    out = await _load_ohlcv_for_indicator("XAUUSD", 50)

    assert len(out["close"]) == 60
    assert out["close"][0] == 4000.0
    assert set(out) == {"close", "open", "high", "low", "volume"}


async def test_the_broker_is_not_consulted_when_the_engine_answers(monkeypatch, tmp_path):
    from api.advanced_trading import _load_ohlcv_for_indicator

    called: list[str] = []

    def _broker_get(symbol, timeframe, limit):
        called.append(symbol)
        raise RuntimeError("PaperTradingBroker.get_market_data() must not be called in production.")

    _no_csv(monkeypatch, tmp_path)
    _install(
        monkeypatch,
        engine=_engine([_Bar(4000.0 + i) for i in range(60)]),
        broker=SimpleNamespace(get_market_data=_broker_get),
    )

    assert await _load_ohlcv_for_indicator("XAUUSD", 50)
    assert called == []


async def test_a_production_deployment_no_longer_reports_no_data(monkeypatch, tmp_path):
    """The regression, end to end on the production configuration."""
    from api.advanced_trading import _load_ohlcv_for_indicator

    monkeypatch.setenv("APP_ENV", "production")
    _no_csv(monkeypatch, tmp_path)
    _install(
        monkeypatch,
        engine=_engine([_Bar(4000.0 + i) for i in range(60)]),
        broker=SimpleNamespace(
            get_market_data=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("must not be called in production"))
        ),
    )

    out = await _load_ohlcv_for_indicator("XAUUSD", 50)
    assert len(out["close"]) == 60


# ── The refusing broker is skipped, not called-and-caught ────────────────────


async def test_the_broker_tier_is_skipped_entirely_in_production(monkeypatch, tmp_path):
    from api.advanced_trading import _load_ohlcv_for_indicator

    called: list[str] = []

    monkeypatch.setenv("APP_ENV", "production")
    _no_csv(monkeypatch, tmp_path)
    _install(
        monkeypatch,
        engine=None,
        broker=SimpleNamespace(get_market_data=lambda s, *a, **k: called.append(s) or []),
    )

    with pytest.raises(ValueError):
        await _load_ohlcv_for_indicator("XAUUSD", 50)

    assert called == [], "the broker was called in production despite refusing by design"


async def test_the_broker_still_serves_development(monkeypatch, tmp_path):
    from api.advanced_trading import _load_ohlcv_for_indicator

    monkeypatch.setenv("APP_ENV", "development")
    _no_csv(monkeypatch, tmp_path)
    bars = [
        {"open": 4000.0 + i, "high": 4001.0 + i, "low": 3999.0 + i, "close": 4000.0 + i, "volume": 5.0}
        for i in range(60)
    ]
    _install(monkeypatch, engine=None, broker=SimpleNamespace(get_market_data=lambda *a, **k: bars))

    out = await _load_ohlcv_for_indicator("XAUUSD", 50)
    assert len(out["close"]) == 60


# ── Synthetic bars must not reach the chart ──────────────────────────────────


async def test_flat_engine_bars_are_rejected(monkeypatch, tmp_path, caplog):
    """Every indicator over a flat series is zero or undefined, which the user
    reads as a broken formula rather than as missing data."""
    from api.advanced_trading import _load_ohlcv_for_indicator

    monkeypatch.setenv("APP_ENV", "production")
    _no_csv(monkeypatch, tmp_path)
    _install(monkeypatch, engine=_engine([_Bar(4000.0, volume=0.0) for _ in range(60)]))

    with caplog.at_level(logging.WARNING, logger="api.advanced_trading"), pytest.raises(ValueError):
        await _load_ohlcv_for_indicator("XAUUSD", 50)

    assert "flat" in " ".join(r.getMessage() for r in caplog.records).lower()


async def test_too_few_bars_are_rejected(monkeypatch, tmp_path):
    from api.advanced_trading import _load_ohlcv_for_indicator

    monkeypatch.setenv("APP_ENV", "production")
    _no_csv(monkeypatch, tmp_path)
    _install(monkeypatch, engine=_engine([_Bar(4000.0 + i) for i in range(5)]))

    with pytest.raises(ValueError):
        await _load_ohlcv_for_indicator("XAUUSD", 50)


# ── The message tells the truth ──────────────────────────────────────────────


async def test_the_failure_message_names_what_was_actually_tried(monkeypatch, tmp_path):
    from api.advanced_trading import _load_ohlcv_for_indicator

    monkeypatch.setenv("APP_ENV", "production")
    _no_csv(monkeypatch, tmp_path)
    _install(monkeypatch, engine=None, broker=None)

    with pytest.raises(ValueError) as excinfo:
        await _load_ohlcv_for_indicator("XAUUSD", 50)

    msg = str(excinfo.value)
    assert "price engine" in msg.lower()
    # The old advice was wrong in production: a broker WAS connected, and no
    # CSV in the repository matches the _H1 name this loader builds.
    assert "Connect a broker" not in msg
    assert "multi_source_feed.yaml" in msg


async def test_an_engine_failure_is_logged_at_warning_not_debug(monkeypatch, tmp_path, caplog):
    """The DEBUG level on the old broker path is what made this invisible."""
    from api.advanced_trading import _load_ohlcv_for_indicator

    async def _boom(symbol, timeframe, limit):
        raise ConnectionError("upstream down")

    monkeypatch.setenv("APP_ENV", "production")
    _no_csv(monkeypatch, tmp_path)
    _install(monkeypatch, engine=SimpleNamespace(get_ohlcv=_boom))

    with caplog.at_level(logging.WARNING, logger="api.advanced_trading"), pytest.raises(ValueError):
        await _load_ohlcv_for_indicator("XAUUSD", 50)

    assert [r for r in caplog.records if r.levelno >= logging.WARNING], "the reason was logged below WARNING again"


# ── The CSV names the loader builds must actually exist to be a real tier ────


def test_the_h1_csv_tier_is_documented_as_absent():
    """Pins the finding rather than the filesystem.

    If someone adds data/XAUUSD_H1.csv later this test tells them the tier just
    became live — which is fine, but it should be a decision, not a surprise.
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2] / "data"
    present = sorted(p.name for p in root.glob("XAU*_H1.csv"))
    assert present == [], (
        f"an _H1 CSV now exists ({present}) — the indicator builder's CSV tier is live again; "
        "confirm it carries real bars before relying on it"
    )
