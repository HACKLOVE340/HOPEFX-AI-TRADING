"""Unit tests for the /api/trading/trendlines builder.

Locks in the fix for the endpoint that previously emitted a response shape
(support_slope/resistance_slope/start_index — none of which exist on the
detector's PatternSignal) that did not match the frontend TrendLine type.
"""

import numpy as np
import pandas as pd
import pytest

from api.trading import _build_trendlines_from_df, _df_timestamps_seconds

REQUIRED_KEYS = {"id", "startTime", "startPrice", "endTime", "endPrice", "type", "strength", "aiGenerated"}


def _rising_df(n: int = 120) -> pd.DataFrame:
    t = np.arange(n)
    close = 2000 + t * 0.4 + np.sin(t / 3) * 8
    return pd.DataFrame(
        {
            "timestamp": (1.7e9 + t * 3600).astype(float),
            "open": close,
            "high": close + 5,
            "low": close - 5,
            "close": close,
            "volume": np.ones(n) * 100,
        }
    )


def test_emits_trendline_shaped_objects():
    lines = _build_trendlines_from_df(_rising_df())
    assert lines, "expected at least one trendline"
    for ln in lines:
        assert REQUIRED_KEYS.issubset(ln.keys())
        assert ln["type"] in {"uptrend", "downtrend", "horizontal"}
        assert ln["startPrice"] > 0 and ln["endPrice"] > 0
        assert ln["endTime"] >= ln["startTime"]
        assert 0.0 <= ln["strength"] <= 1.0


def test_rising_series_yields_uptrend_lines():
    lines = _build_trendlines_from_df(_rising_df())
    assert any(ln["type"] == "uptrend" for ln in lines)


def test_insufficient_data_returns_empty():
    assert _build_trendlines_from_df(_rising_df(10)) == []


def test_timestamps_seconds_handles_ms_and_seconds():
    df_ms = pd.DataFrame({"timestamp": [1.7e12, 1.7e12 + 3600000], "high": [1, 2], "low": [0, 1], "close": [1, 2]})
    secs = _df_timestamps_seconds(df_ms)
    assert secs is not None and all(s < 1e11 for s in secs)


def test_timestamps_none_without_time_column():
    df = pd.DataFrame({"high": [1, 2], "low": [0, 1], "close": [1, 2]})
    assert _df_timestamps_seconds(df) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
