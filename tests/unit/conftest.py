# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""Unit test fixtures shared across tests/unit/."""

import os
import sys
import types
import uuid
from dataclasses import dataclass

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


# ---------------------------------------------------------------------------
# CME/FIX stub fixture
# ---------------------------------------------------------------------------


def _build_fix_adapter_stub() -> types.ModuleType:
    """Return a minimal execution.fix_adapter stub for CME connector tests."""
    mod = types.ModuleType("execution.fix_adapter")

    class FIXSide:
        BUY = "BUY"
        SELL = "SELL"

    class FIXOrdType:
        MARKET = "MARKET"
        LIMIT = "LIMIT"
        STOP = "STOP"

    @dataclass
    class FIXOrder:
        symbol: str
        side: str
        quantity: float
        ord_type: str
        price: float | None = None
        stop_price: float | None = None
        account: str = ""

    @dataclass
    class FIXReport:
        order_id: str
        cl_ord_id: str
        cum_qty: float
        avg_px: float
        latency_ms: float = 1.0

    class FIXAdapter:
        def __init__(self, **kwargs):
            pass

        def start(self):
            pass

        async def send_order(self, order):
            return FIXReport(
                order_id=str(uuid.uuid4()),
                cl_ord_id=str(uuid.uuid4()),
                cum_qty=order.quantity,
                avg_px=2350.0,
                latency_ms=1.5,
            )

    mod.FIXSide = FIXSide
    mod.FIXOrdType = FIXOrdType
    mod.FIXOrder = FIXOrder
    mod.FIXReport = FIXReport
    mod.FIXAdapter = FIXAdapter
    return mod


@pytest.fixture(autouse=False, scope="module")
def _cme_fix_adapter_stub():
    """
    Module-scoped fixture that injects a minimal execution.fix_adapter stub
    for the duration of the requesting test module, then restores the original.

    Used by test_cme_comex_connector.py via pytestmark. Scoped to module so
    the stub is active only while that module's tests run and is removed before
    any other module (e.g. test_connector_hub.py) that needs the real adapter.
    """
    import execution  # ensure the real package is loaded first  # noqa: F401

    stub = _build_fix_adapter_stub()
    original = sys.modules.get("execution.fix_adapter")
    sys.modules["execution.fix_adapter"] = stub
    yield stub
    if original is None:
        sys.modules.pop("execution.fix_adapter", None)
    else:
        sys.modules["execution.fix_adapter"] = original
