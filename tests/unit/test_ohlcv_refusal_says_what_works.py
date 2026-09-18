"""A 503 that names the timeframes it CAN serve is actionable; one that does not is a wall.

`/ai-chart-dashboard` renders six panels at 1h: XAU/USD, EUR/USD, GBP/USD,
USD/JPY, BTC/USD, ETH/USD. Measured 2026-09-15, five of those six have a working
yfinance ticker and one does not — **XAUUSD, the instrument this platform
actually trades**. Its ticker is deliberately empty because Yahoo delisted the
contract, and the bundled CSV is daily/weekly only. So on that dashboard the
gold panel is the one that fails, and it is the first in the grid.

The endpoint already refuses honestly rather than fabricating bars, and its
message names the symbol, the timeframe and the feed to configure. What it does
not say is that **daily and weekly are sitting right there**. An operator who
cannot get 1h gold has no way to learn from the error that 1d works — so they
read "no data" as "this instrument is broken" rather than "this timeframe is".

This asserts the refusal carries what would work. It does not change what is
served, what is refused, or the status code.
"""

from __future__ import annotations


from api.trading import _servable_fallback_timeframes


def test_gold_reports_the_timeframes_its_bundled_history_covers():
    tfs = _servable_fallback_timeframes("XAUUSD")
    assert "1d" in tfs
    assert "1w" in tfs


def test_gold_does_not_claim_intraday_it_cannot_serve():
    # The whole point. Listing 1h here would be worse than saying nothing.
    tfs = _servable_fallback_timeframes("XAUUSD")
    for intraday in ("1m", "5m", "15m", "30m", "1h", "4h"):
        assert intraday not in tfs, f"claimed {intraday}, which has no bundled source"


def test_a_symbol_with_no_bundled_history_claims_nothing():
    # The CSV is gold. Promising EURUSD daily from it would be a lie that sends
    # the operator to a timeframe that also fails.
    assert _servable_fallback_timeframes("EURUSD") == ()
    assert _servable_fallback_timeframes("BTCUSD") == ()


def test_the_refusal_carries_them():
    """The 503 detail must include the alternatives, not just the failure."""
    from api import trading

    detail = trading._ohlcv_unavailable_detail("XAUUSD", "1h")
    assert detail["error"] == "ohlcv_unavailable"
    assert detail["symbol"] == "XAUUSD"
    assert detail["timeframe"] == "1h"
    # Machine-readable for the chart, and in the sentence for the operator.
    assert "1d" in detail["available_timeframes"]
    assert "1d" in detail["message"]


def test_the_refusal_stays_honest_when_nothing_would_work():
    """No alternatives must read as none — never as an empty promise."""
    from api import trading

    detail = trading._ohlcv_unavailable_detail("EURUSD", "1h")
    assert detail["available_timeframes"] == []
    # It must not end up saying "try one of: " with nothing after it.
    assert "try" not in detail["message"].lower() or "1d" in detail["message"]
    assert detail["message"].strip().endswith((".", ")"))


def test_it_still_names_the_feed_to_configure():
    """The existing guidance is the actionable half for an operator who owns the deploy."""
    from api import trading

    for sym in ("XAUUSD", "EURUSD"):
        msg = trading._ohlcv_unavailable_detail(sym, "1h")["message"]
        assert "OANDA_API_KEY" in msg or "feed" in msg.lower()
