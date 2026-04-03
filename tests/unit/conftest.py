# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""Unit test fixtures shared across test_all_strategies and test_strategies."""

import os

import numpy as np
import pandas as pd
import pytest


@pytest.fixture(autouse=True)
def _restore_feature_env_vars():
    """
    Snapshot all FEATURE_* env vars before each test and restore them after.

    Prevents test-ordering pollution: a test that sets FEATURE_X=false without
    using monkeypatch would otherwise corrupt subsequent tests that rely on the
    default value of that flag.
    """
    snapshot = {k: v for k, v in os.environ.items() if k.startswith("FEATURE_")}
    yield
    # Remove any FEATURE_* vars added during the test
    for key in list(os.environ.keys()):
        if key.startswith("FEATURE_") and key not in snapshot:
            del os.environ[key]
    # Restore original values (including deletions)
    for key, value in snapshot.items():
        os.environ[key] = value


@pytest.fixture
def test_config():
    """Minimal strategy config dict."""
    from strategies.base import StrategyConfig

    return StrategyConfig(name="TestStrategy", symbol="EUR_USD", timeframe="1H")


@pytest.fixture
def mock_strategy():
    """Factory that creates a mock BaseStrategy instance."""

    def _factory(name: str = "MockStrategy", symbol: str = "EUR_USD"):
        from strategies.base import BaseStrategy, StrategyConfig

        cfg = StrategyConfig(name=name, symbol=symbol, timeframe="1H")

        class _MockStrategy(BaseStrategy):
            def analyze(self, data):
                return {}

            def generate_signal(self, analysis):
                return None

        return _MockStrategy(cfg)

    return _factory


@pytest.fixture
def sample_market_data():
    """50-bar OHLCV DataFrame for strategy tests."""
    np.random.seed(42)
    n = 50
    close = 1.0850 + np.cumsum(np.random.randn(n) * 0.001)
    df = pd.DataFrame(
        {
            "open": close - np.abs(np.random.randn(n) * 0.0005),
            "high": close + np.abs(np.random.randn(n) * 0.001),
            "low": close - np.abs(np.random.randn(n) * 0.001),
            "close": close,
            "volume": np.random.randint(1000, 10000, n).astype(float),
        },
        index=pd.date_range("2024-01-01", periods=n, freq="1h"),
    )
    return df


@pytest.fixture
def clean_strategy_manager():
    """StrategyManager with no pre-registered strategies."""
    from strategies.manager import StrategyManager

    mgr = StrategyManager()
    mgr.strategies.clear()
    return mgr
