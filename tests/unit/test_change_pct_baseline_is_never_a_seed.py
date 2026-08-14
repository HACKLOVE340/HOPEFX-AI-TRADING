"""
tests/unit/test_change_pct_baseline_is_never_a_seed.py
======================================================
The second leak of the synthetic 3300.0 gold seed.

`_seed_from_broker` was fixed to stop copying the paper broker's seed table
into `_open_prices` unless a feed had actually written the value. That closed
one writer and left another running unconditionally at import::

    _open_prices = {sym: cfg["price"] for sym, cfg in _SYMBOLS.items()}

`_SYMBOLS` is the pre-feed scratch table whose gold entry is ``3300.0``. So on
every fresh process the gold baseline was 3300.0, and the first real tick near
4,390 was rendered as roughly **+33%** — a fabricated number derived from a
price that was never quoted, displayed with two decimal places beside a real
mid.

`_open_prices` now starts empty and `_baseline_for()` seeds each symbol from its
first real price, so an unknown change reads 0.00% rather than a percentage
against an invented open.

These tests assert on module state and the tick payload, not on prose.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def ws(monkeypatch):
    from api import ws_live

    # Every test starts from a fresh baseline map.
    monkeypatch.setattr(ws_live, "_open_prices", {}, raising=False)
    return ws_live


# ── The baseline is not pre-populated from the seed table ─────────────────────


def test_open_prices_is_empty_at_import():
    """A fresh import must not carry a baseline for any symbol."""
    import importlib

    from api import ws_live

    reloaded = importlib.reload(ws_live)
    assert reloaded._open_prices == {}, (
        "_open_prices was pre-filled at import — from _SYMBOLS, whose gold entry "
        f"is a synthetic seed: {reloaded._open_prices}"
    )


def test_no_baseline_equals_any_seed_value(ws):
    """Belt and braces: no symbol's baseline may match its _SYMBOLS seed."""
    seeds = {sym: cfg["price"] for sym, cfg in ws._SYMBOLS.items()}
    for sym, seed in seeds.items():
        assert ws._open_prices.get(sym) != seed or sym not in ws._open_prices


# ── The first real price becomes the baseline, reporting 0.00% ────────────────


def test_first_real_price_reports_no_change_rather_than_a_jump(ws):
    change = ws._baseline_for("XAU/USD", 4390.20)
    assert change == 4390.20
    # The regression: 3300.0 baseline → (4390.20 - 3300)/3300 = +33.0%
    pct = (4390.20 - change) / change * 100
    assert pct == 0.0


def test_the_baseline_is_kept_once_set(ws):
    ws._baseline_for("XAU/USD", 4390.20)
    assert ws._baseline_for("XAU/USD", 4400.00) == 4390.20

    pct = (4400.00 - 4390.20) / 4390.20 * 100
    assert 0.2 < pct < 0.3, "a real intraday move must still be reported"


def test_a_zero_or_negative_stored_baseline_is_replaced(ws):
    ws._open_prices["XAU/USD"] = 0.0
    assert ws._baseline_for("XAU/USD", 4390.20) == 4390.20


# ── End to end through _make_tick ─────────────────────────────────────────────


def test_make_tick_does_not_report_a_percentage_against_the_seed(ws, monkeypatch):
    monkeypatch.setattr(ws, "_seed_from_broker", lambda: None)
    monkeypatch.setattr(ws, "_get_live_price", lambda sym: 4390.20)

    first = ws._make_tick("XAU/USD")
    assert first is not None
    assert first["data"]["mid"] == pytest.approx(4390.20)
    # Deployed behaviour was change_pct ≈ 33.0 on the very first tick.
    assert first["data"]["change_pct"] == 0.0


def test_make_tick_reports_a_real_move_on_the_second_tick(ws, monkeypatch):
    monkeypatch.setattr(ws, "_seed_from_broker", lambda: None)

    prices = iter([4390.20, 4412.00])
    monkeypatch.setattr(ws, "_get_live_price", lambda sym: next(prices))

    ws._make_tick("XAU/USD")
    second = ws._make_tick("XAU/USD")

    assert second["data"]["change_pct"] == pytest.approx((4412.00 - 4390.20) / 4390.20 * 100, abs=0.01)
    assert second["data"]["change_pct"] > 0


def test_a_freshly_imported_module_reports_no_change_on_its_first_tick(monkeypatch):
    """The deployed path, with no fixture clearing the baseline first.

    The `ws` fixture blanks `_open_prices` for isolation, which also hides the
    module-level initialisation that *was* the bug — under mutation, seven of
    these tests still passed. This one reloads the module and ticks it exactly
    as a freshly started process would, so it fails if the import-time fill
    ever comes back.
    """
    import importlib

    from api import ws_live

    ws_live = importlib.reload(ws_live)
    monkeypatch.setattr(ws_live, "_seed_from_broker", lambda: None)
    monkeypatch.setattr(ws_live, "_get_live_price", lambda sym: 4390.20)

    tick = ws_live._make_tick("XAU/USD")
    assert tick is not None
    assert tick["data"]["change_pct"] == 0.0, (
        f"first tick of a fresh process reported {tick['data']['change_pct']}% — the baseline came from the 3300.0 seed"
    )


def test_every_configured_symbol_starts_at_zero_change(ws, monkeypatch):
    """Not just gold — every seed in the table was a baseline."""
    monkeypatch.setattr(ws, "_seed_from_broker", lambda: None)

    for symbol, cfg in list(ws._SYMBOLS.items()):
        seed = cfg["price"]
        # A real price deliberately far from the seed, so a seed baseline would
        # show an obviously wrong percentage.
        real = seed * 1.33
        monkeypatch.setattr(ws, "_get_live_price", lambda sym, _r=real: _r)
        tick = ws._make_tick(symbol)
        assert tick is not None, symbol
        assert tick["data"]["change_pct"] == 0.0, (
            f"{symbol} reported {tick['data']['change_pct']}% on its first tick — the baseline came from the seed table"
        )
