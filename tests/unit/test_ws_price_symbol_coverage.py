# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_ws_price_symbol_coverage.py
===========================================
Every symbol the UI lets you select must be one the price channel can broadcast.

The live WebSocket broadcaster iterated a hardcoded six-entry ``_SYMBOLS`` dict
while ``config/multi_source_feed.yaml`` configured twelve symbols and
``Trade.tsx`` let you select all twelve. The missing six — XPT/USD, USD/CHF,
AUD/USD, USD/CAD, NZD/USD, ETH/USD — were fetched by the feed, validated,
range-checked and cached, and then never sent to a browser. Selecting one
showed "No feed" permanently, and Watchlist showed live prices for five of its
ten symbols.

Nothing in the type system or the wiring connected the two lists, so they
drifted silently. This test is that connection.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]
FEED_CONFIG = REPO / "config" / "multi_source_feed.yaml"
TRADE_PAGE = REPO / "frontend" / "src" / "pages" / "Trade.tsx"
WATCHLIST_PAGE = REPO / "frontend" / "src" / "pages" / "Watchlist.tsx"


def _slash(compact: str) -> str:
    """XAUUSD -> XAU/USD (6-char pairs only, which is all the feed configures)."""
    return f"{compact[:3]}/{compact[3:]}" if len(compact) == 6 else compact


def _feed_symbols() -> set[str]:
    """Symbols declared in the multi-source feed config, in slash form."""
    text = FEED_CONFIG.read_text()
    return {_slash(m) for m in re.findall(r"^    ([A-Z]{6,8}):", text, re.M)}


def _ts_string_list(path: Path, const: str) -> set[str]:
    """Extract a `const NAME = [ '...', ... ]` array from a .tsx file."""
    src = path.read_text()
    m = re.search(rf"const {const}\s*=\s*\[(.*?)\]", src, re.S)
    assert m, f"{const} not found in {path.name}"
    return set(re.findall(r"'([^']+)'", m.group(1)))


def test_broadcaster_covers_every_configured_feed_symbol():
    """A symbol the feed fetches must be one the browser can receive."""
    from api.ws_live import _SYMBOLS

    missing = _feed_symbols() - set(_SYMBOLS)

    assert not missing, (
        "config/multi_source_feed.yaml configures these symbols but the price "
        f"broadcaster will never send them: {sorted(missing)}. They are fetched "
        "and cached, then dropped."
    )


def test_trade_page_symbols_are_all_broadcastable():
    """Every symbol Trade.tsx offers must be broadcastable."""
    from api.ws_live import _SYMBOLS

    missing = _ts_string_list(TRADE_PAGE, "SYMBOLS") - set(_SYMBOLS)

    assert not missing, (
        f"Trade.tsx lets the user select {sorted(missing)}, which the price "
        "channel never broadcasts — the tile shows 'No feed' for ever."
    )


def test_watchlist_symbols_are_all_broadcastable():
    """Watchlist uses the compact form; normalise before comparing."""
    from api.ws_live import _SYMBOLS

    offered = {_slash(s) for s in _ts_string_list(WATCHLIST_PAGE, "AVAILABLE_SYMBOLS")}
    missing = offered - set(_SYMBOLS)

    assert not missing, (
        f"Watchlist offers {sorted(missing)}, which are never broadcast. "
        "This is why it showed live prices for five of its ten symbols."
    )


def test_every_symbol_has_a_usable_spread():
    """`_make_tick` derives bid/ask from the mid using the spread."""
    from api.ws_live import _SYMBOLS, _spread_for

    for symbol, cfg in _SYMBOLS.items():
        spread = _spread_for(symbol, float(cfg["price"]))
        assert spread > 0, f"{symbol} has a non-positive spread"
        # A spread wider than 1% of the mid would render a nonsensical book.
        assert spread < float(cfg["price"]) * 0.01, f"{symbol} spread is implausibly wide"


def test_spread_falls_back_for_an_unknown_symbol():
    """A symbol arriving from the price engine alone is still quotable."""
    from api.ws_live import _spread_for

    spread = _spread_for("XYZ/USD", 100.0)
    assert spread == pytest.approx(0.02)  # 2 bps of 100


def test_broker_key_does_not_keep_the_slash():
    """`BTC/USD` used to map to `BTC/USD`, unlike every other entry.

    Levels 1 and 2 of the price chain key on the compact form ("BTCUSD", as
    used in the feed config), so Bitcoin missed the two freshest sources and
    fell through to Redis or yfinance.
    """
    from api.ws_live import _BROKER_KEY, _get_live_price  # noqa: F401

    for slash_symbol, broker_key in _BROKER_KEY.items():
        assert "/" not in broker_key, (
            f"{slash_symbol} maps to {broker_key!r}, which keeps the slash — "
            "the price engine and broker both key on the compact form."
        )


def test_yfinance_fallback_never_quotes_a_proxy_for_spot_platinum():
    """The feed config is explicit that no Yahoo instrument may stand in for XPT.

    GLD trades near $390 against spot gold near $4,070; quoting one as the
    other is worse than quoting nothing.
    """
    from api.ws_live import _YF_SYMBOL_MAP

    assert "XPT/USD" not in _YF_SYMBOL_MAP


def test_broadcastable_symbols_includes_the_base_set():
    """With no price engine attached, the base set is still broadcast."""
    from api.ws_live import _SYMBOLS, _broadcastable_symbols

    resolved = set(_broadcastable_symbols())
    assert set(_SYMBOLS) <= resolved


def test_broadcastable_symbols_picks_up_engine_symbols(monkeypatch):
    """A symbol the engine carries is broadcast without editing _SYMBOLS."""
    from core.app_state import app_state

    class _Engine:
        symbols = ["USDSEK", "XAU/USD"]

    monkeypatch.setattr(app_state, "price_engine", _Engine(), raising=False)

    from api.ws_live import _broadcastable_symbols

    resolved = set(_broadcastable_symbols())
    assert "USD/SEK" in resolved, "engine symbols must be normalised and included"
    assert "XAU/USD" in resolved


def test_broadcastable_symbols_survives_a_broken_engine(monkeypatch):
    """A failure reading the engine must not stop the base set broadcasting."""
    from core.app_state import app_state

    class _Exploding:
        @property
        def symbols(self):
            raise RuntimeError("engine down")

    monkeypatch.setattr(app_state, "price_engine", _Exploding(), raising=False)

    from api.ws_live import _SYMBOLS, _broadcastable_symbols

    assert set(_SYMBOLS) <= set(_broadcastable_symbols())
