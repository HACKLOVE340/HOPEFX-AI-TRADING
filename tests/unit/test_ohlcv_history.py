"""Tests for the deep-history CSV fallback behind /api/trading/ohlcv.

Locks in the fix that lets daily/weekly gold charts render decades of
history (back past 2000) when the live price engine and yfinance are
unavailable, instead of returning a blank 503.
"""

import datetime as dt

from api.trading import _load_gold_history_csv


def test_daily_history_reaches_back_decades():
    bars = _load_gold_history_csv("1d", 8000)
    assert len(bars) > 1000
    first = dt.datetime.fromtimestamp(bars[0]["timestamp"], tz=dt.timezone.utc).year
    assert first <= 2000, f"expected daily history before 2000, got {first}"
    # Bars carry full OHLCV and are chronologically ordered.
    assert {"timestamp", "open", "high", "low", "close", "volume"} <= bars[0].keys()
    assert bars[0]["timestamp"] < bars[-1]["timestamp"]


def test_weekly_resample_returns_bars():
    bars = _load_gold_history_csv("1w", 2000)
    assert len(bars) > 100
    assert bars[0]["timestamp"] < bars[-1]["timestamp"]


def test_intraday_returns_empty():
    # CSV is daily granularity — intraday must fall through to other feeds.
    assert _load_gold_history_csv("1h", 500) == []
    assert _load_gold_history_csv("5m", 500) == []


def test_limit_is_respected():
    assert len(_load_gold_history_csv("1d", 50)) == 50


# ── yfinance ticker resolution ────────────────────────────────────────────────
# Two bugs kept /api/trading/ohlcv from ever serving a live bar:
#   1. Ticker.history(..., progress=False) — `progress` belongs to yf.download().
#      history() raises TypeError on it *before* any network call, and the broad
#      `except Exception` swallowed it, silently disabling the whole fallback.
#   2. A hand-maintained symbol→ticker map that still pointed XAUUSD at "GC=F"
#      long after Yahoo delisted the futures contracts (see b439bef).


# Yahoo no longer serves these contracts — verified against production 2026-07-26.
DELISTED_YAHOO_FUTURES = frozenset({"GC=F", "SI=F", "PL=F", "CL=F", "BZ=F", "NQ=F", "YM=F", "ES=F"})


def test_ohlcv_ticker_map_has_no_delisted_futures():
    from api.trading import _yf_ticker_map

    offenders = {s: t for s, t in _yf_ticker_map().items() if t in DELISTED_YAHOO_FUTURES}
    assert not offenders, f"delisted Yahoo tickers still mapped: {offenders}"


def test_spot_metals_resolve_to_no_yfinance_ticker():
    """Metals must fall through to twelve_data/alpha_vantage, never to an ETF proxy.

    GLD trades near $390 against spot gold near $4,070 — quoting one as the other
    would be wrong by an order of magnitude on this platform's primary instrument.
    """
    from api.trading import _yf_ticker_map

    for symbol in ("XAUUSD", "XAGUSD", "XPTUSD"):
        assert _yf_ticker_map().get(symbol) == "", f"{symbol} must have no yfinance ticker"


def test_ticker_map_is_read_from_feed_config():
    """The map must come from multi_source_feed.yaml, not a second private copy."""
    from api.trading import _yf_ticker_map

    mapping = _yf_ticker_map()
    # Values that only exist in the YAML, so a hardcoded dict cannot satisfy this.
    assert mapping.get("EURUSD") == "EURUSD=X"
    assert mapping.get("US30") == "^DJI"
    assert mapping.get("NAS100") == "^NDX"


def test_no_ticker_history_call_passes_progress_kwarg():
    """`progress` is a yf.download() parameter. Ticker.history() rejects it.

    Scans the repo rather than a single line, because this failure mode is silent:
    the TypeError is raised before any network I/O and is typically swallowed by a
    broad `except Exception` that reads like a data-source outage.
    """
    import ast
    import pathlib

    repo_root = pathlib.Path(__file__).resolve().parents[2]
    skip_dirs = {".git", "node_modules", "venv", ".venv", "__pycache__", "frontend"}
    offenders = []

    for path in repo_root.rglob("*.py"):
        if skip_dirs & set(path.parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "history"
                and any(kw.arg == "progress" for kw in node.keywords)
            ):
                offenders.append(f"{path.relative_to(repo_root)}:{node.lineno}")

    assert not offenders, f".history() called with progress= (raises TypeError): {offenders}"
