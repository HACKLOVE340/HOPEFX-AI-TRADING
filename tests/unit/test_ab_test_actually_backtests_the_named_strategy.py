"""
tests/unit/test_ab_test_actually_backtests_the_named_strategy.py
================================================================
Reported from the deployment::

    A/B test failed — check strategy names and data availability

Neither the strategy names nor the data were the problem. Three defects, all in
``api/advanced_trading.py::_run_real_backtest`` and the machinery it calls:

1. **The strategy name was accepted and never used.** No ``add_strategy()`` call
   was made. Both arms of every A/B test ran the same empty backtest, so the two
   results were identical and the winner fell out of the ``>=`` tie-break —
   always ``strategy_a``, whatever was compared.

2. **``asyncio.run()`` was called from inside a running event loop.**
   ``start_ab_test`` is ``async def``; it called ``_run_real_backtest``, which
   called ``asyncio.run(engine.run())``. That raises ``RuntimeError`` on every
   single request. The blanket ``except Exception`` turned it into the 422 above,
   whose text pointed at strategy names and data — the two things that were fine.

3. **Nothing in ``strategies/`` could be run by ``BacktestEngine`` anyway.** The
   engine calls ``strategy.generate_signals(timestamp=, prices=, data=)``; every
   class in ``strategies/`` implements ``generate_signal`` (singular). The
   ``AttributeError`` was caught per-bar by ``except Exception: logger.error(...)``
   and the backtest "succeeded" with zero trades and a 0.00% return — a failure
   reported as a result, which is the worst outcome a backtester can produce.

Four of the thirteen advertised strategies could not even be instantiated:
``BreakoutStrategy``, ``EMAcrossoverStrategy``, ``MeanReversionStrategy`` and
``StochasticStrategy`` never implemented ``BaseStrategy.analyze``, so
constructing one raised ``TypeError: Can't instantiate abstract class``.

These tests drive the real engine over synthetic bars — no network, no database.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest


# ── Synthetic bars ────────────────────────────────────────────────────────────


def _bars(n: int = 600, seed: int = 7) -> pd.DataFrame:
    """A trending-then-reverting series, so crossover strategies actually fire."""
    rng = np.random.default_rng(seed)
    drift = np.concatenate([np.full(n // 2, 0.8), np.full(n - n // 2, -0.8)])
    close = 4000 + np.cumsum(drift + rng.normal(0, 6, n))
    end = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    return pd.DataFrame(
        {
            "timestamp": pd.date_range(end=end, periods=n, freq="h", tz="UTC"),
            "open": close,
            "high": close + 4,
            "low": close - 4,
            "close": close,
            "volume": 1000.0,
        }
    )


@pytest.fixture
def stub_loader(monkeypatch):
    """Serve synthetic bars instead of the database/yfinance."""
    from backtesting.engine_config import HistoricalDataLoader

    async def _load(self, symbol, timeframe, start, end):
        return _bars()

    monkeypatch.setattr(HistoricalDataLoader, "load_data", _load)


# ── Every registered strategy can be built and run ────────────────────────────


def test_every_registered_strategy_can_be_instantiated():
    """Four of them raised TypeError: Can't instantiate abstract class."""
    from strategies.registry import available_strategies, build

    for name in available_strategies():
        strategy = build(name, "XAUUSD")
        assert hasattr(strategy, "generate_signal")


@pytest.mark.parametrize(
    "name",
    ["breakout", "emacrossover", "meanreversion", "stochastic"],
)
def test_the_four_abstract_strategies_now_implement_analyze(name):
    from strategies.registry import build

    strategy = build(name, "XAUUSD")
    result = strategy.analyze(_bars(120))
    assert isinstance(result, dict) and result, f"{name}.analyze returned {result!r}"


def test_an_unknown_strategy_name_says_what_is_available():
    from strategies.registry import UnknownStrategyError, build

    with pytest.raises(UnknownStrategyError) as exc:
        build("does-not-exist", "XAUUSD")
    assert "does-not-exist" in str(exc.value)
    assert "rsi" in str(exc.value)


def test_a_dict_only_strategy_is_refused_with_a_reason_not_as_unknown():
    """ "Exists but cannot be backtested" and "no such strategy" are different."""
    from strategies.registry import UnknownStrategyError, build

    with pytest.raises(UnknownStrategyError) as exc:
        build("MovingAverageCrossover", "XAUUSD")
    assert "not backtestable" in str(exc.value)


def test_name_normalisation_accepts_the_forms_a_user_would_type():
    from strategies.registry import normalise

    for spelling in ["RSI", "rsi", "RSIStrategy", "rsi_strategy", "RSI Strategy"]:
        assert normalise(spelling) == "rsi"


# ── The adapter bridges the two signal contracts ──────────────────────────────


def test_adapter_translates_a_dict_signal_into_an_engine_signal():
    from backtesting.strategy_adapter import BacktestStrategyAdapter

    class _AlwaysBuy:
        name = "always-buy"

        def generate_signal(self, frame):
            return {"type": "BUY", "confidence": 0.9}

    frame = _bars(60)
    adapter = BacktestStrategyAdapter(_AlwaysBuy(), "XAUUSD")
    ts = frame["timestamp"].iloc[-1]
    signals = adapter.generate_signals(ts, {"XAUUSD": 4000.0}, {"XAUUSD": frame})

    assert len(signals) == 1
    assert signals[0]["symbol"] == "XAUUSD"
    assert signals[0]["action"] == "buy"
    assert signals[0]["stop_distance"] > 0


def test_adapter_does_not_pyramid_on_a_repeated_condition():
    """These strategies report a condition per bar, not a transition."""
    from backtesting.strategy_adapter import BacktestStrategyAdapter

    class _AlwaysBuy:
        def generate_signal(self, frame):
            return {"type": "BUY", "confidence": 0.9}

    frame = _bars(60)
    adapter = BacktestStrategyAdapter(_AlwaysBuy(), "XAUUSD")
    emitted = 0
    for ts in frame["timestamp"].tail(20):
        emitted += len(adapter.generate_signals(ts, {"XAUUSD": 4000.0}, {"XAUUSD": frame}))
    assert emitted == 1, f"opened {emitted} positions on one continuous condition"


def test_adapter_marks_exits_so_the_whole_position_is_closed():
    from backtesting.strategy_adapter import BacktestStrategyAdapter

    class _Flip:
        def __init__(self):
            self.calls = 0

        def generate_signal(self, frame):
            self.calls += 1
            return {"type": "BUY" if self.calls == 1 else "SELL", "confidence": 0.9}

    frame = _bars(60)
    adapter = BacktestStrategyAdapter(_Flip(), "XAUUSD")
    ts = list(frame["timestamp"].tail(2))
    first = adapter.generate_signals(ts[0], {"XAUUSD": 4000.0}, {"XAUUSD": frame})
    second = adapter.generate_signals(ts[1], {"XAUUSD": 4000.0}, {"XAUUSD": frame})

    assert first[0]["action"] == "buy"
    assert second[0]["action"] == "sell"
    assert second[0]["exit"] is True


def test_adapter_ignores_a_sell_while_flat_rather_than_shorting():
    from backtesting.strategy_adapter import BacktestStrategyAdapter

    class _AlwaysSell:
        def generate_signal(self, frame):
            return {"type": "SELL", "confidence": 0.9}

    frame = _bars(60)
    adapter = BacktestStrategyAdapter(_AlwaysSell(), "XAUUSD")
    ts = frame["timestamp"].iloc[-1]
    assert adapter.generate_signals(ts, {"XAUUSD": 4000.0}, {"XAUUSD": frame}) == []


def test_adapter_reads_both_direction_keys_in_use():
    """Seven strategies key it "type"; PullbackStrategy keys it "signal_type"."""
    from backtesting.strategy_adapter import normalise_signal

    assert normalise_signal({"type": "BUY", "confidence": 0.7}) == ("BUY", 0.7)
    assert normalise_signal({"signal_type": "SELL", "confidence": 0.4}) == ("SELL", 0.4)
    assert normalise_signal({"type": "HOLD", "confidence": 0.0})[0] == "HOLD"
    assert normalise_signal(None)[0] == "HOLD"
    assert normalise_signal({"type": "???"})[0] == "HOLD"


def test_adapter_records_a_raising_strategy_instead_of_swallowing_it():
    from backtesting.strategy_adapter import BacktestStrategyAdapter

    class _Broken:
        def generate_signal(self, frame):
            raise RuntimeError("boom")

    frame = _bars(60)
    adapter = BacktestStrategyAdapter(_Broken(), "XAUUSD")
    adapter.generate_signals(frame["timestamp"].iloc[-1], {"XAUUSD": 4000.0}, {"XAUUSD": frame})
    assert adapter.errors and "boom" in adapter.errors[0]


# ── The engine refuses to report an empty run as a result ─────────────────────


@pytest.mark.asyncio
async def test_a_backtest_with_no_strategy_raises_rather_than_returning_zero(stub_loader):
    from backtesting.engine_config import BacktestConfig, BacktestEngine

    end = datetime.now(UTC)
    config = BacktestConfig(start_date=end - timedelta(days=20), end_date=end, symbols=["XAUUSD"])
    engine = BacktestEngine(config=config)

    with pytest.raises(ValueError, match="No strategies"):
        await engine.run()


# ── End to end: the two arms differ, and the failure modes are honest ─────────


@pytest.mark.asyncio
async def test_the_two_arms_of_an_ab_test_are_actually_different(stub_loader):
    from api.advanced_trading import _run_real_backtest

    a = await _run_real_backtest("rsi", "XAU/USD", 30, 10_000.0)
    b = await _run_real_backtest("emacrossover", "XAU/USD", 30, 10_000.0)

    assert a["strategy"] == "rsi"
    assert b["strategy"] == "emacrossover"
    # The regression: both arms ran the same empty backtest and were identical.
    assert (a["total_trades"], a["total_return"]) != (b["total_trades"], b["total_return"]), (
        "Both arms produced identical results — the strategy is not reaching the engine"
    )


@pytest.mark.asyncio
async def test_at_least_one_strategy_actually_trades(stub_loader):
    """A zero-trade run for every strategy would make the test above vacuous."""
    from api.advanced_trading import _run_real_backtest

    traded = []
    for name in ["rsi", "emacrossover", "macd", "bollingerbands"]:
        result = await _run_real_backtest(name, "XAU/USD", 30, 10_000.0)
        traded.append((name, result["total_trades"]))

    assert any(n > 0 for _, n in traded), f"no strategy placed a trade: {traded}"


@pytest.mark.asyncio
async def test_it_does_not_call_asyncio_run_inside_the_running_loop(stub_loader):
    """The deployed failure: RuntimeError on every request, reported as a 422."""
    from api.advanced_trading import _run_real_backtest

    # Running inside pytest-asyncio means there IS a running loop, which is what
    # made asyncio.run() raise in production.
    result = await _run_real_backtest("rsi", "XAU/USD", 30, 10_000.0)
    assert "total_return" in result


@pytest.mark.asyncio
async def test_an_unknown_strategy_produces_a_message_naming_it(stub_loader):
    from api.advanced_trading import _run_real_backtest

    with pytest.raises(ValueError) as exc:
        await _run_real_backtest("no-such-strategy", "XAU/USD", 30, 10_000.0)

    message = str(exc.value)
    assert "no-such-strategy" in message
    # The old text pointed at "strategy names and data availability" for every
    # failure, including ones that were neither.
    assert "check strategy names and data availability" not in message
