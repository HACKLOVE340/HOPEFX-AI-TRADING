"""
tests/unit/test_risk_calculator_prices_the_symbol_asked_for.py
==============================================================
``GET /api/risk/live-price/{symbol}`` feeds the entry-price field of the
Risk/Reward calculator, and every number that page renders — lot size, risk
amount, R:R — is computed from that entry price. So the endpoint returning *a*
price rather than *the requested symbol's* price is a sizing error, not a
display error.

Its first level was:

    state = get_app_state()
    if state and hasattr(state, "latest_tick") and state.latest_tick:
        tick = state.latest_tick
        if hasattr(tick, "mid") and tick.mid:
            return float(tick.mid)

``latest_tick`` is the engine's single most recent tick — XAUUSD in every
deployment — and ``symbol`` is never consulted. Two consequences:

  1. Asking for EUR/USD returned the price of gold.
  2. app_state is always present, so this level short-circuited the two
     symbol-aware levels below it on every single request.

Third level mapped to Yahoo with
``sym.replace("_", "=X") if "_" in sym else sym + "=X"``. ``canonical()``
strips separators, so the first branch was unreachable and BTCUSD became
``BTCUSD=X``, which Yahoo does not list — the fallback could never price
either crypto instrument the terminal offers.

These tests use the real module functions with the price sources stubbed; they
do not assert on prose.
"""

from __future__ import annotations

import sys
import types

import pytest


@pytest.fixture
def risk_calc():
    import api.risk_calculator as rc

    return rc


# ── The requested symbol is the one that gets priced ──────────────────────────


def test_a_eurusd_request_does_not_return_the_gold_price(risk_calc, monkeypatch):
    """The regression: one global tick answering for every instrument."""
    from api import ws_live

    quotes = {"XAU/USD": 4390.20, "EUR/USD": 1.08512}
    monkeypatch.setattr(ws_live, "_get_live_price", lambda s: quotes.get(s))

    assert risk_calc._get_live_price("EUR_USD") == pytest.approx(1.08512)
    assert risk_calc._get_live_price("XAU/USD") == pytest.approx(4390.20)


def test_each_offered_instrument_resolves_to_its_own_quote(risk_calc, monkeypatch):
    from api import ws_live

    quotes = {
        "XAU/USD": 4390.20,
        "EUR/USD": 1.08512,
        "GBP/USD": 1.27340,
        "USD/JPY": 157.412,
        "BTC/USD": 96_250.0,
        "ETH/USD": 3_410.5,
    }
    monkeypatch.setattr(ws_live, "_get_live_price", lambda s: quotes.get(s))

    for slash, expected in quotes.items():
        # The client sends the underscore form: symbol.replace('/', '_').
        assert risk_calc._get_live_price(slash.replace("/", "_")) == pytest.approx(expected)


@pytest.fixture
def yfinance_prices_nothing(monkeypatch):
    """Stub level 3 so it cannot answer, whatever the network can reach.

    Both tests below used to do this by pointing `_yahoo_ticker` at the string
    `"NOPE"` and assuming Yahoo does not list it. NOPE *is* a listed ticker, so
    on a runner with network access level 3 returned 8.3715 and the assertions
    failed — green locally where yfinance cannot reach the internet, red in CI.
    A test must not depend on which symbols a third party happens to quote.
    """

    class _NoQuote:
        # Attribute names mirror yfinance's own `fast_info`.
        class fast_info:
            last_price = None
            regularMarketPrice = None

        def __init__(self, _symbol):
            pass

    stub = types.ModuleType("yfinance")
    stub.Ticker = _NoQuote  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "yfinance", stub)


def test_an_unknown_symbol_returns_none_rather_than_someone_elses_price(
    risk_calc, monkeypatch, yfinance_prices_nothing
):
    from api import ws_live

    monkeypatch.setattr(ws_live, "_get_live_price", lambda s: 4390.20 if s == "XAU/USD" else None)

    # The point is that the XAUUSD price must not leak out for a different symbol.
    assert risk_calc._get_live_price("ZZZ_QQQ") is None


# ── The shared chain is used, not a second private copy ───────────────────────


def test_it_defers_to_the_ws_live_chain(risk_calc, monkeypatch):
    """Falling back to a private copy is how the two disagreed in the first place."""
    from api import ws_live

    calls: list[str] = []

    def _spy(sym):
        calls.append(sym)
        return 4390.20

    monkeypatch.setattr(ws_live, "_get_live_price", _spy)
    assert risk_calc._get_live_price("XAUUSD") == pytest.approx(4390.20)
    assert calls == ["XAU/USD"], (
        "risk_calculator must call ws_live._get_live_price with the slash form "
        f"that its _last_mid cache is keyed by; it called {calls!r}"
    )


def test_a_zero_or_negative_price_is_not_accepted_as_live(risk_calc, monkeypatch, yfinance_prices_nothing):
    from api import ws_live

    monkeypatch.setattr(ws_live, "_get_live_price", lambda s: 0.0)
    assert risk_calc._get_live_price("XAU/USD") is None


# ── Yahoo tickers are the ones Yahoo actually lists ───────────────────────────


@pytest.mark.parametrize(
    ("canonical", "expected"),
    [
        ("EURUSD", "EURUSD=X"),
        ("GBPUSD", "GBPUSD=X"),
        ("USDJPY", "USDJPY=X"),
        ("XAUUSD", "XAUUSD=X"),
        ("BTCUSD", "BTC-USD"),
        ("ETHUSD", "ETH-USD"),
    ],
)
def test_yahoo_ticker_mapping(risk_calc, canonical, expected):
    assert risk_calc._yahoo_ticker(canonical) == expected


def test_crypto_does_not_get_the_fx_suffix(risk_calc):
    """`BTCUSD=X` is not a Yahoo ticker; this level 503'd for crypto."""
    assert not risk_calc._yahoo_ticker("BTCUSD").endswith("=X")
    assert not risk_calc._yahoo_ticker("ETHUSD").endswith("=X")


def test_yfinance_level_is_reached_and_uses_the_mapped_ticker(risk_calc, monkeypatch):
    """Prove level 3 runs — the old level 1 made it unreachable."""
    from api import ws_live

    monkeypatch.setattr(ws_live, "_get_live_price", lambda s: None)

    asked: list[str] = []

    class _FastInfo:
        last_price = 96_250.0

    class _Ticker:
        def __init__(self, sym):
            asked.append(sym)

        fast_info = _FastInfo()

    fake_yf = types.ModuleType("yfinance")
    fake_yf.Ticker = _Ticker  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)

    assert risk_calc._get_live_price("BTC_USD") == pytest.approx(96_250.0)
    assert asked == ["BTC-USD"]


# ── Level 2 exists ────────────────────────────────────────────────────────────


def test_the_orchestrator_level_actually_runs(risk_calc, monkeypatch, yfinance_prices_nothing):
    """It never had, until the import was fixed.

    Level 2 read `from data_layer.orchestrator import get_orchestrator`. No such
    factory exists — the module exposes the singleton directly, which is what
    `data_layer/__init__.py` documents — so the import raised ImportError on
    every call, the level's own `except Exception` logged it at debug, and the
    chain was really L1 → L3. A fallback that cannot fire is not a fallback.
    """
    import importlib

    from api import ws_live

    monkeypatch.setattr(ws_live, "_get_live_price", lambda s: None)

    orchestrator_module = importlib.import_module("data_layer.orchestrator")
    asked: list[str] = []

    def _tick(symbol: str = "XAU_USD"):
        asked.append(symbol)
        return types.SimpleNamespace(mid=4390.20)

    monkeypatch.setattr(orchestrator_module.orchestrator, "get_latest_tick", _tick)

    assert risk_calc._get_live_price("XAU_USD") == pytest.approx(4390.20)
    assert asked == ["XAUUSD"], f"level 2 did not run, or dropped the symbol: {asked!r}"


def test_the_orchestrator_level_is_asked_for_the_right_symbol(risk_calc, monkeypatch, yfinance_prices_nothing):
    """`get_latest_tick` defaults to XAU_USD, so a dropped argument would
    silently price everything as gold — the exact bug this module was rewritten
    to remove, one level further down."""
    import importlib

    from api import ws_live

    monkeypatch.setattr(ws_live, "_get_live_price", lambda s: None)

    orchestrator_module = importlib.import_module("data_layer.orchestrator")
    quotes = {"XAUUSD": 4390.20, "EURUSD": 1.08512}

    monkeypatch.setattr(
        orchestrator_module.orchestrator,
        "get_latest_tick",
        lambda symbol="XAU_USD": types.SimpleNamespace(mid=quotes[symbol]),
    )

    assert risk_calc._get_live_price("EUR_USD") == pytest.approx(1.08512)
    assert risk_calc._get_live_price("XAU_USD") == pytest.approx(4390.20)
