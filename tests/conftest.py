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
# Disable the startup gate so tests don't receive 503 before app_state.initialized.
os.environ.setdefault("STARTUP_GATE", "false")
# Raise WS rate limits so the test suite (which opens many connections) is
# not blocked by the per-IP concurrent/rate caps.
os.environ.setdefault("WS_MAX_CONNECTIONS_PER_IP", "200")
os.environ.setdefault("WS_MAX_CONNECTIONS_PER_MINUTE", "500")

from datetime import datetime, timezone

UTC = timezone.utc

import pytest

# Register shared fixture modules — makes db_engine, async_db_session, db_user,
# db_trade, db_signal, and repository fixtures available to all test modules
# without explicit imports.
pytest_plugins = ["tests.fixtures.db"]

# Import core components for testing
from brokers import PaperTradingBroker
from data.real_time_price_engine import OHLCV, Tick
from risk.manager import RiskConfig, RiskManager
from strategies.manager import StrategyManager


# event_loop fixture removed: pytest-asyncio >= 0.23 manages the loop
# automatically when asyncio_mode = "auto" is set in pytest.ini.
# Defining a custom event_loop fixture here caused DeprecationWarnings and
# could interfere with loop teardown between async tests.


_CANONICAL_JWT_SECRET = os.environ.get(
    "SECURITY_JWT_SECRET",
    "test-only-jwt-secret-key-minimum-32-chars!!",
)


@pytest.fixture(autouse=True)
def _restore_env():
    """
    Snapshot and restore the **entire** environment around every test.

    This used to restore a hardcoded list of seven keys while its docstring
    claimed it "prevents test-ordering pollution from tests that mutate env
    vars". Everything outside that list leaked.

    The failure that exposed it: ``core/main_loop.py`` calls ``load_dotenv()``
    inside ``MainLoop.run()``, so a test exercising the main loop injected the
    developer's ``.env`` into ``os.environ`` for the rest of the session. That
    file sets ``PAPER_RAISE_ON_STALE=true``, and ``PaperTradingBroker`` reads it
    once in ``__init__`` — so every broker built afterwards refused every fill
    with ``StalePriceError``:

        pytest tests/unit/test_trading_auth.py                  -> 36 passed
        pytest tests/unit/test_core_main_loop.py \
               tests/unit/test_trading_auth.py                  -> 5 failed

    An allowlist can only cover the pollution someone already found. Snapshotting
    the whole mapping costs one dict copy per test and covers the pollution
    nobody has found yet — including anything a future ``.env`` gains.

    ``.env`` being gitignored made it worse: CI has no such file and stayed
    green, so the same commit passed remotely and failed locally, which reads as
    a broken machine rather than a leaking test.
    """
    snapshot = dict(os.environ)
    # A valid JWT secret must be present going in: several modules read it at
    # import time and a short one fails validation rather than defaulting.
    os.environ.setdefault("SECURITY_JWT_SECRET", _CANONICAL_JWT_SECRET)
    try:
        yield
    finally:
        # Restore exactly: put back what was there, drop what was added.
        # os.environ.clear() then update() would work, but mutating in place
        # keeps any os.environ reference a test is holding valid.
        for key in list(os.environ):
            if key not in snapshot:
                del os.environ[key]
        for key, value in snapshot.items():
            if os.environ.get(key) != value:
                os.environ[key] = value
        # Guarantee a usable JWT secret afterwards regardless of what the
        # snapshot held — an invalid one breaks every subsequent auth test with
        # an error that points nowhere near the test that caused it.
        if len(os.environ.get("SECURITY_JWT_SECRET", "")) < 32:
            os.environ["SECURITY_JWT_SECRET"] = _CANONICAL_JWT_SECRET
        for _alias in ("JWT_SECRET_KEY", "JWT_SECRET"):
            if 0 < len(os.environ.get(_alias, "")) < 32:
                os.environ.pop(_alias, None)


@pytest.fixture(autouse=True)
def _reset_account_registry():
    """
    Drop the process-wide per-user broker cache around every test.

    ``core/account_registry.py`` caches one ``PaperTradingBroker`` per user in a
    module-level singleton, and a broker reads its configuration **once, in
    __init__**. So restoring ``os.environ`` after a test does not undo a broker
    that already captured a polluted value: a broker built while
    ``PAPER_RAISE_ON_STALE`` was set keeps refusing every fill with
    ``StalePriceError`` for the rest of the session, from a cache no later test
    can see.

    The same cache also carries balances, open positions and order history
    between tests, which is its own quiet source of order-dependent failures.

    ``reset_account_registry()`` has existed all along with the docstring "For
    tests and shutdown". Nothing called it.
    """
    from core.account_registry import reset_account_registry

    reset_account_registry()
    try:
        yield
    finally:
        reset_account_registry()


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
        ...  # nosec B110


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


class _AsyncCallable:
    """
    Real async callable for tests that need to inject an awaitable function.

    Tracks call count and arguments without using unittest.mock.
    Use this only when you need to inject a coroutine function into a component
    under test — prefer real implementations (PaperTradingBroker, etc.) instead.
    """

    def __init__(self, return_value=None):
        self.return_value = return_value
        self.call_count = 0
        self.calls: list = []

    async def __call__(self, *args, **kwargs):
        self.call_count += 1
        self.calls.append((args, kwargs))
        return self.return_value


# Backward-compatible alias — existing tests that reference AsyncMock from
# conftest get the real async callable, not unittest.mock.AsyncMock.
AsyncMock = _AsyncCallable


# Test data generators
def generate_price_series(start: float, volatility: float, n: int = 100) -> list:
    """Generate synthetic price series"""
    import numpy as np

    prices = [start]
    for _ in range(n - 1):
        change = np.random.normal(0, volatility)
        prices.append(prices[-1] * (1 + change))
    return prices


def generate_ohlcv_from_close(closes: list) -> list:
    """Generate OHLCV from close prices"""
    import numpy as np

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


# ── WebSocket limiter isolation ───────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_ws_limiter_state():
    """Clear the in-process WS connection limiter counters before every test.

    The limiter singleton accumulates open-connection counts when TestClient
    WS sessions close without triggering the handler's finally/release path.
    Clearing the counters prevents rate-limit rejections from polluting
    subsequent tests.
    """
    try:
        import rate_limiting.websocket_limiter as _wsl

        lim = _wsl.get_ws_limiter()
        lim._open_conns.clear()
        lim._rate_window.clear()
    except Exception:
        pass
    yield
    try:
        import rate_limiting.websocket_limiter as _wsl

        lim = _wsl.get_ws_limiter()
        lim._open_conns.clear()
        lim._rate_window.clear()
    except Exception:
        pass


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
        ...  # nosec B110
    yield
    # Also reset after the test in case it activated the switch
    try:
        from kill_switch import kill_switch as _ks

        _ks.reset_for_testing()
    except Exception:
        ...  # nosec B110


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
async def mock_broker():
    """Real PaperTradingBroker used as the shared broker fixture in unit tests.

    Uses PaperTradingBroker so tests exercise real order-placement, position
    tracking, and account-info logic without requiring live broker credentials.
    """
    broker = PaperTradingBroker(initial_balance=100_000.0, commission_per_lot=3.5)
    await broker.connect()
    yield broker
    await broker.disconnect()


@pytest.fixture
def temp_dir():
    """Temporary directory, cleaned up after the test."""
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture(autouse=True)
def _reset_circuit_breakers():
    """
    Reset all service circuit breakers to CLOSED state before every test.

    Circuit breakers are module-level singletons. Without this fixture a test
    that triggers broker/Redis/DB failures would leave the breaker OPEN and
    cause unrelated tests to fail with 'circuit breaker OPEN' errors.
    """
    try:
        from resilience.service_circuit_breakers import (
            redis_breaker,
            broker_breaker,
            ml_breaker,
            db_breaker,
        )

        for breaker in (redis_breaker, broker_breaker, ml_breaker, db_breaker):
            breaker.force_close()
    except Exception:  # nosec B110 — non-fatal if module unavailable
        pass
    yield
    # No teardown needed — next test's setup will reset again


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
    import numpy as np
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


# ── Auth-coverage fixture ─────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def app():
    """
    Session-scoped fixture that returns the live FastAPI application instance.

    Used by test_auth_coverage.py to iterate every registered route and assert
    that all mutating endpoints carry an auth dependency.  Session-scoped so
    the app is imported once per test session — importing it is expensive
    (registers all routers, wires all dependencies).

    Skips automatically if the app cannot be imported in the current
    environment (e.g. missing optional C-extensions in a minimal CI image).
    The skip is surfaced as a single ``pytest.skip`` rather than N individual
    test failures, keeping the CI output clean.

    Environment requirements
    ------------------------
    The following env vars must be set before this fixture is used.  They are
    set by the module-level ``os.environ.setdefault`` calls at the top of this
    conftest, so they are always present when running via ``pytest tests/``:

      APP_ENV=test
      SECURITY_JWT_SECRET=<>=32 chars>
      STARTUP_GATE=false
      CSRF_PROTECTION=false  (set by test_auth_coverage.py before import)
    """
    try:
        from app import app as _fastapi_app

        return _fastapi_app
    except Exception as exc:
        pytest.skip(
            f"app fixture: FastAPI app could not be imported — {exc}\n"
            "Install the full requirements-ci.txt to run auth-coverage tests."
        )
