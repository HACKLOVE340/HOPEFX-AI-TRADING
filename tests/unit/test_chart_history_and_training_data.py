# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_chart_history_and_training_data.py
===================================================
"The chart only shows about a month" — and following that down found something
considerably worse underneath it.

**The chart.** ``api/trading.py`` pinned the hourly and 4-hourly yfinance fetch
to ``period="60d"``, annotated "~1440 bars — fast, plenty of history". Sixty
days of hourly candles is exactly the Jul→Aug window the deployed 1h chart
showed, and no amount of scrolling reached further back because the data had
never been requested. Yahoo serves hourly out to 730 days.

The frontend capped the same request at 1500 bars, which on its own would have
clipped a widened response straight back to ~60 days. Both ends had to move;
fixing only the server would have changed nothing and invited the conclusion
that the limit was external.

**The training data.** ``data/XAUUSD_50Y.csv`` spans 1968→2026 and is the first
cache candidate in ``ml/train_advanced.py``. 13.4% of its bars move more than
20% in a single session; the largest moves 519%. Its 1990 rows dip to $81 in a
year gold traded near $380, and its 1999 rows to $56.

``api/trading.py`` already refuses to serve that same file to charts:

    XAUUSD_50Y.csv is intentionally NOT used as the primary source: its
    pre-2000 bars are corrupted (isolated bad prints, e.g. $43 when gold was
    ~$270), which would feed bad data into charts.

So the corruption was known, the chart was defended from it, and the model was
trained on it. The production model's reported 57.34% out-of-sample accuracy
was measured across a history a substantial fraction of which never happened.

``validate_ohlcv`` could not have caught this: it checks absolute price bounds,
and $43 is a legitimate gold price — in 1971. Bounds wide enough to admit both
the 1968 and 2026 price levels span a factor of over a hundred. Returns are
scale-free, so a 474% one-day move is impossible regardless of era.

The gate raises rather than filtering. Dropping 13% of bars would leave silent
multi-year gaps and train on them anyway, replacing a visible problem with an
invisible one.
"""

from __future__ import annotations

import pandas as pd
import pytest

pytestmark = pytest.mark.unit


# ── Chart history depth ──────────────────────────────────────────────────────


def _tf_map() -> dict:
    """The timeframe → (interval, period) table from the OHLCV endpoint."""
    import ast
    import pathlib

    src = (pathlib.Path(__file__).resolve().parents[2] / "api/trading.py").read_text()
    block = src.split("_TF_MAP = ")[1]
    depth, end = 0, 0
    for i, ch in enumerate(block):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    return ast.literal_eval(block[:end])


def test_hourly_history_is_not_capped_at_two_months():
    """The user-visible symptom: a 1h chart that started six weeks ago."""
    tf = _tf_map()
    interval, period = tf["1h"]
    assert interval == "1h"
    assert period == "730d", f"1h still fetches {period}; Yahoo serves 730d"


def test_four_hourly_inherits_the_deeper_hourly_window():
    """4h is resampled from 1h, so it is limited by whatever 1h fetches."""
    tf = _tf_map()
    assert tf["4h"] == ("1h", "730d")


def test_daily_and_weekly_still_request_everything():
    tf = _tf_map()
    assert tf["1d"][1] == "max"
    assert tf["1w"][1] == "max"


@pytest.mark.parametrize("timeframe", ["1m", "5m", "15m", "30m"])
def test_sub_hourly_windows_are_left_at_the_sources_own_limits(timeframe):
    """These are Yahoo's constraints, not ours — widening them would just fail."""
    tf = _tf_map()
    assert tf[timeframe][1] in ("7d", "60d")


def _frontend_limits() -> dict[str, int]:
    import pathlib
    import re

    src = (
        pathlib.Path(__file__).resolve().parents[2] / "frontend/src/features/chart-bot/services/chart-api.ts"
    ).read_text()
    body = src.split("export function ohlcvLimitFor")[1].split("}")[0]
    return {m[0]: int(m[1]) for m in re.findall(r"case '([^']+)':\s*return (\d+)", body)}


def test_the_frontend_asks_for_as_much_as_the_backend_now_serves():
    """Raising only the server would have changed nothing on screen.

    730 days of hourly bars in a market trading ~23h/day, 5 days a week, is
    roughly 12,000 bars. A 1500-bar request truncates that to about 60 days —
    the original symptom, reproduced from the other end.
    """
    limits = _frontend_limits()
    assert limits["1h"] >= 12_000, f"1h limit {limits['1h']} clips 730d of hourly data"
    assert limits["4h"] >= 3_000, f"4h limit {limits['4h']} clips 730d of 4h data"
    assert limits["1d"] >= 6_500, "daily must cover the full 2000→today CSV"


# ── Price-history sanity ─────────────────────────────────────────────────────


def _frame(prices: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2020-01-01", periods=len(prices), freq="D", tz="UTC")
    return pd.DataFrame({"close": prices}, index=idx)


def test_a_clean_series_reports_no_spikes():
    from data_layer.validation import detect_price_spikes

    report = detect_price_spikes(_frame([1800, 1810, 1795, 1820, 1840]))
    assert report["spike_count"] == 0
    assert report["spike_rate"] == 0.0


def test_a_bad_print_is_caught_regardless_of_price_level():
    """The case absolute bounds cannot see: $43 is a real gold price, just not
    the day after a $270 close."""
    from data_layer.validation import detect_price_spikes

    report = detect_price_spikes(_frame([270.0, 271.0, 43.0, 272.0, 273.0]))
    assert report["spike_count"] == 2  # into the bad print and back out of it
    assert report["max_abs_return"] > 0.8
    assert any(w["price"] == 43.0 for w in report["worst"])


def test_a_genuine_crisis_move_is_not_flagged():
    """Gold's worst real daily moves are around 10%. The threshold must leave
    room for them or it becomes another false alarm."""
    from data_layer.validation import detect_price_spikes

    assert detect_price_spikes(_frame([1800, 1980, 1960]))["spike_count"] == 0


def test_it_never_mutates_the_frame():
    from data_layer.validation import detect_price_spikes

    df = _frame([270.0, 43.0, 272.0])
    before = df.copy()
    detect_price_spikes(df)
    pd.testing.assert_frame_equal(df, before)


def test_it_suggests_where_the_series_becomes_usable():
    from data_layer.validation import detect_price_spikes

    report = detect_price_spikes(_frame([270.0, 43.0, 271.0, 272.0, 273.0, 274.0]))
    assert report["first_clean_index"] is not None


@pytest.mark.parametrize("frame", [pd.DataFrame(), pd.DataFrame({"close": [1800.0]})])
def test_degenerate_frames_do_not_raise(frame):
    from data_layer.validation import detect_price_spikes

    assert detect_price_spikes(frame)["spike_count"] == 0


# ── The training gate ────────────────────────────────────────────────────────


def test_training_refuses_the_corrupt_fifty_year_file():
    """The real file, not a fixture. This is the first cache candidate in
    ml/train_advanced.py, so this is what a retrain would have loaded."""
    import pathlib

    from ml.train_advanced import CorruptTrainingDataError, _assert_price_history_is_plausible

    path = pathlib.Path(__file__).resolve().parents[2] / "data/XAUUSD_50Y.csv"
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.columns = [c.lower() for c in df.columns]

    with pytest.raises(CorruptTrainingDataError) as excinfo:
        _assert_price_history_is_plausible(df, path)
    message = str(excinfo.value)
    assert "XAUUSD_40Y.csv" in message, "the error must name a source that works"
    assert "%" in message, "the error must quantify how bad it is"


def test_training_accepts_the_clean_forty_year_file():
    import pathlib

    from ml.train_advanced import _assert_price_history_is_plausible

    path = pathlib.Path(__file__).resolve().parents[2] / "data/XAUUSD_40Y.csv"
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.columns = [c.lower() for c in df.columns]
    _assert_price_history_is_plausible(df, path)  # must not raise


def test_an_isolated_bad_print_only_warns():
    """One bad tick in a long series is worth a warning, not a hard stop."""
    from ml.train_advanced import _assert_price_history_is_plausible

    prices = [1800.0 + i for i in range(2000)]
    prices[900] = 43.0
    _assert_price_history_is_plausible(_frame(prices), "synthetic")  # must not raise


def test_the_gate_can_be_overridden_deliberately(monkeypatch):
    """An operator who knows what they are doing must not be blocked, but they
    have to say so."""
    import pathlib

    from ml.train_advanced import _assert_price_history_is_plausible

    path = pathlib.Path(__file__).resolve().parents[2] / "data/XAUUSD_50Y.csv"
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.columns = [c.lower() for c in df.columns]

    monkeypatch.setenv("TRAIN_ALLOW_CORRUPT_HISTORY", "true")
    _assert_price_history_is_plausible(df, path)  # must not raise


def test_the_loader_actually_calls_the_gate():
    """Guard against the check existing and never running — which is how the
    corruption survived a codebase that already knew about it."""
    import ast
    import inspect
    import textwrap

    from ml import train_advanced

    src = textwrap.dedent(inspect.getsource(train_advanced.fetch_gold_ohlcv))
    calls = [n.func.id for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
    assert "_assert_price_history_is_plausible" in calls


def test_the_chart_and_the_trainer_now_agree_about_the_file():
    """They disagreed: one refused the file, the other preferred it."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2]
    chart = (root / "api/trading.py").read_text()
    assert "XAUUSD_50Y.csv is intentionally NOT used" in chart, "chart guard removed"

    trainer = (root / "ml/train_advanced.py").read_text()
    assert "_assert_price_history_is_plausible" in trainer, "trainer guard removed"
