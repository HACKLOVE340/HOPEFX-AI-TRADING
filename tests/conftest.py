# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
HOPEFX Test Configuration
Pytest fixtures and test utilities
"""

import os
import tempfile

# Set test environment before any app module is imported.
# APP_ENV=test makes startup_validator skip production-only checks
# (DB_HOST, REDIS_URL, CONFIG_ENCRYPTION_KEY, etc.) so the app can
# be imported in CI without a full infrastructure stack.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault(
    "SECURITY_JWT_SECRET",
    "test-only-jwt-secret-key-minimum-32-chars!!",
)

import asyncio
from datetime import UTC, datetime

import numpy as np
import pytest

# Import core components for testing
from brokers import PaperTradingBroker
from data.real_time_price_engine import OHLCV, Tick
from risk.manager import RiskConfig, RiskManager
from strategies.manager import StrategyManager


@pytest.fixture
def event_loop():
    """Create event loop for async tests"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


_CANONICAL_JWT_SECRET = os.environ.get(
    "SECURITY_JWT_SECRET",
    "test-only-jwt-secret-key-minimum-32-chars!!",
)


@pytest.fixture(autouse=True)
def _restore_critical_env_vars():
    """
    Snapshot and restore critical environment variables after every test.

    Prevents test-ordering pollution from tests that mutate env vars without
    using monkeypatch (e.g. setting SECURITY_JWT_SECRET to a short value to
    test validation, then failing to restore it).
    """
    _KEYS = (
        "SECURITY_JWT_SECRET",
        "JWT_SECRET",
        "APP_ENV",
        "BROKER",
    )
    snapshot = {k: os.environ.get(k) for k in _KEYS}
    # Ensure canonical JWT secret is always set going into each test
    os.environ.setdefault("SECURITY_JWT_SECRET", _CANONICAL_JWT_SECRET)
    yield
    # Restore exact pre-test state
    for k, v in snapshot.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    # Always guarantee a valid JWT secret after teardown
    if len(os.environ.get("SECURITY_JWT_SECRET", "")) < 32:
        os.environ["SECURITY_JWT_SECRET"] = _CANONICAL_JWT_SECRET


@pytest.fixture(autouse=True)
def _reset_global_kill_switch():
    """
    Reset the global kill switch singleton after every test.

    Tests that activate the kill switch (e.g. drawdown breach tests) write
    a flag file to disk.  Without cleanup, subsequent tests that expect the
    kill switch to be inactive fail because the persisted state is restored
    on the next KillSwitch instantiation.
    """
    yield
    # Teardown: deactivate and remove flag/state files from the global instance
    try:
        from pathlib import Path

        flag = Path(__file__).parent.parent / "kill_switch.flag"
        state = flag.with_suffix(".state.json")
        for f in (flag, state):
            if f.exists():
                f.unlink(missing_ok=True)
        # Reset the in-memory singleton if already imported
        import sys

        ks_mod = sys.modules.get("kill_switch")
        if ks_mod is not None:
            ks = getattr(ks_mod, "kill_switch", None)
            if ks is not None and callable(getattr(ks, "_deactivate_internal", None)):
                ks._deactivate_internal()
            elif ks is not None:
                ks._active = False
                ks._reason = ""
        app_mod = sys.modules.get("app")
        if app_mod is not None:
            ks = getattr(app_mod, "kill_switch", None)
            if ks is not None:
                ks._active = False
                ks._reason = ""
    except Exception:
        pass


@pytest.fixture
async def paper_broker():
    """Create paper trading broker for tests"""
    broker = PaperTradingBroker(initial_balance=100000.0, commission_per_lot=3.5)
    await broker.connect()
    yield broker
    await broker.disconnect()


@pytest.fixture
def risk_manager(tmp_path):
    """Create risk manager for tests with isolated halt state."""
    return RiskManager(
        RiskConfig(max_position_size_pct=0.02, max_drawdown_pct=0.10),
        halt_state_file=tmp_path / "halt_state.json",
    )


@pytest.fixture
def strategy_manager():
    """Create strategy manager for tests"""
    return StrategyManager()


@pytest.fixture
def sample_tick():
    """Create sample price tick"""
    return Tick(
        symbol="EURUSD",
        timestamp=datetime.now(UTC).timestamp(),
        bid=1.0850,
        ask=1.0852,
        mid=1.0851,
        volume=1000,
    )


@pytest.fixture
def sample_ohlcv():
    """Create sample OHLCV data"""
    return [
        OHLCV(
            timestamp=datetime.now(UTC).timestamp() - i * 3600,
            open=1.0800 + i * 0.001,
            high=1.0810 + i * 0.001,
            low=1.0790 + i * 0.001,
            close=1.0805 + i * 0.001,
            volume=1000 + i * 100,
        )
        for i in range(100, 0, -1)  # 100 hours of data, oldest first
    ]


@pytest.fixture
def mock_brain_config():
    """Brain configuration for testing"""
    return {
        "max_decision_history": 100,
        "regime_check_interval": 60,
        "circuit_breaker_threshold": 3,
    }


class AsyncMock:
    """Helper for creating async mocks"""

    def __init__(self, return_value=None):
        self.return_value = return_value
        self.call_count = 0
        self.calls = []

    async def __call__(self, *args, **kwargs):
        self.call_count += 1
        self.calls.append((args, kwargs))
        return self.return_value


# Test data generators
def generate_price_series(start: float, volatility: float, n: int = 100) -> list:
    """Generate synthetic price series"""
    prices = [start]
    for _ in range(n - 1):
        change = np.random.normal(0, volatility)
        prices.append(prices[-1] * (1 + change))
    return prices


def generate_ohlcv_from_close(closes: list) -> list:
    """Generate OHLCV from close prices"""
    ohlcv = []
    for i, close in enumerate(closes):
        high = close * (1 + abs(np.random.normal(0, 0.001)))
        low = close * (1 - abs(np.random.normal(0, 0.001)))
        open_price = closes[i - 1] if i > 0 else close

        ohlcv.append(
            OHLCV(
                timestamp=datetime.now(UTC).timestamp() - (len(closes) - i) * 3600,
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=np.random.randint(1000, 10000),
            )
        )

    return ohlcv


# ── CI speed flag ────────────────────────────────────────────────────────────
# Set HOPEFX_CI=1 so ml/train_advanced.py uses minimal estimators in tests.

os.environ.setdefault("HOPEFX_CI", "1")


# ── Kill switch isolation ─────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_kill_switch():
    """
    Reset the module-level KillSwitch singleton before every test.

    Without this, a test that activates the kill switch pollutes all
    subsequent tests that import the same singleton.
    """
    try:
        from kill_switch import kill_switch as _ks

        _ks.reset_for_testing()
    except Exception:
        pass
    yield
    # Also reset after the test in case it activated the switch
    try:
        from kill_switch import kill_switch as _ks

        _ks.reset_for_testing()
    except Exception:
        pass


# ── Additional fixtures required by root-level tests ─────────────────────────


@pytest.fixture
def test_config():
    """Generic test configuration dict."""
    return {
        "initial_balance": 100_000.0,
        "commission_per_lot": 3.5,
        "max_position_size_pct": 0.02,
        "max_drawdown_pct": 0.10,
        "environment": "testing",
    }


@pytest.fixture
def mock_broker():
    """Lightweight synchronous mock broker for unit tests."""
    from unittest.mock import AsyncMock as _AsyncMock
    from unittest.mock import MagicMock

    broker = MagicMock()
    broker.get_account_info = _AsyncMock(
        return_value={
            "balance": 100_000.0,
            "equity": 100_000.0,
            "margin_used": 0.0,
            "free_margin": 100_000.0,
        }
    )
    broker.place_market_order = _AsyncMock(
        return_value=MagicMock(
            id="mock_order_1",
            status=MagicMock(value="filled"),
            filled_quantity=10_000,
            average_fill_price=1.0851,
        )
    )
    broker.get_positions = _AsyncMock(return_value=[])
    broker.close_position = _AsyncMock(return_value=True)
    return broker


@pytest.fixture
def temp_dir():
    """Temporary directory, cleaned up after the test."""
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def mock_strategy():
    """
    Factory fixture returning a callable that produces concrete BaseStrategy
    instances for unit tests.

    Usage::

        def test_something(mock_strategy):
            strategy = mock_strategy()          # default name "MockStrategy"
            strategy2 = mock_strategy("Foo")    # custom name
    """
    from strategies.base import BaseStrategy, StrategyConfig

    def _factory(name: str = "MockStrategy", symbol: str = "EUR_USD"):
        config = StrategyConfig(
            name=name,
            symbol=symbol,
            timeframe="1H",
            parameters={},
        )

        class _MockStrategy(BaseStrategy):
            def analyze(self, data):
                return {}

            def generate_signal(self, analysis):
                return None

        return _MockStrategy(config_or_name=config)

    return _factory


@pytest.fixture
def sample_market_data():
    """Multi-asset OHLCV dict for portfolio tests."""
    import pandas as pd

    rng = np.random.default_rng(42)
    dates = pd.date_range("2023-01-01", periods=252, freq="B")
    data = {}
    for sym, base in [
        ("XAUUSD", 1900),
        ("EURUSD", 1.08),
        ("GBPUSD", 1.25),
        ("USDJPY", 130),
    ]:
        closes = base * np.cumprod(1 + rng.normal(0.0002, 0.01, 252))
        data[sym] = pd.DataFrame(
            {
                "open": closes * (1 + rng.uniform(-0.002, 0.002, 252)),
                "high": closes * (1 + rng.uniform(0, 0.005, 252)),
                "low": closes * (1 - rng.uniform(0, 0.005, 252)),
                "close": closes,
                "volume": rng.integers(5000, 50000, 252),
            },
            index=dates,
        )
    return data
