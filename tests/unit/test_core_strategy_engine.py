# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""`core/strategy_engine.py` — the event-driven ML signal engine.

Ticks in, OHLCV bars out, a prediction on bar close, and a `signal_event`
published to `hopefx:signal` when the engine is confident enough. Measured at 0%.

A published signal is the head of the order path, so the tests here are about
the three gates that stand between a tick and one: the warm-up gate (no
inference before `MIN_BARS`), the abstain gate (`HOLD`, or confidence below
`ML_MIN_TRADE_PROB`), and the bar-close gate (no signal mid-bar). Each is
exercised from both sides, because a gate only ever tested in the state where it
passes is a gate nobody has watched refuse.

`bus.publish_signal` is patched at the module seam rather than mocked deeper, so
every refusal above it runs through the real composition path.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest

pytestmark = pytest.mark.unit

REPO = pathlib.Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import core.strategy_engine as se


def _tick(mid: float = 2400.0, **over):
    base = {"mid": mid, "spread": 0.2, "symbol": "XAU/USD", "timestamp": "2026-09-11T10:00:00+00:00", "seq": 1}
    base.update(over)
    return base


def _bars(n: int, start: float = 2400.0) -> pd.DataFrame:
    rows = [
        {
            "open": start + i,
            "high": start + i + 1,
            "low": start + i - 1,
            "close": start + i,
            "volume": 10.0,
            "timestamp": pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(days=i),
        }
        for i in range(n)
    ]
    return pd.DataFrame(rows).set_index("timestamp")[["open", "high", "low", "close", "volume"]]


class TestTheOHLCVBuffer:
    def test_a_bar_closes_only_after_enough_ticks(self) -> None:
        buf = se._OHLCVBuffer()
        closes = [buf.push(2400.0 + i, 0.2, "2026-09-11T10:00:00+00:00") for i in range(se.TICKS_PER_BAR)]
        assert closes[:-1] == [False] * (se.TICKS_PER_BAR - 1)
        assert closes[-1] is True
        assert buf.bar_count == 1

    def test_a_closed_bar_records_the_real_high_and_low(self) -> None:
        """OHLC that did not come from the ticks would feed the model a candle
        the market never printed."""
        buf = se._OHLCVBuffer()
        prices = [2400.0, 2405.0, 2395.0, 2401.0]
        for i in range(se.TICKS_PER_BAR):
            buf.push(prices[i % len(prices)], 0.2, "2026-09-11T10:00:00+00:00")
        bar = buf._bars[-1]
        assert bar["high"] == max(prices)
        assert bar["low"] == min(prices)
        assert bar["volume"] == float(se.TICKS_PER_BAR)

    def test_it_is_not_ready_before_min_bars(self) -> None:
        buf = se._OHLCVBuffer()
        assert buf.ready() is False

    def test_ema_cross_is_zero_before_any_tick(self) -> None:
        """Unmeasured, not bullish. A non-zero default here would make the EMA
        fallback fire a direction on the first tick of the process."""
        assert se._OHLCVBuffer().ema_cross == 0.0

    def test_ema_cross_turns_positive_on_a_rising_market(self) -> None:
        buf = se._OHLCVBuffer()
        for i in range(200):
            buf.push(2400.0 + i, 0.2, "2026-09-11T10:00:00+00:00")
        assert buf.ema_cross > 0

    def test_ema_cross_turns_negative_on_a_falling_market(self) -> None:
        buf = se._OHLCVBuffer()
        for i in range(200):
            buf.push(2600.0 - i, 0.2, "2026-09-11T10:00:00+00:00")
        assert buf.ema_cross < 0

    def test_the_dataframe_carries_the_columns_the_model_expects(self) -> None:
        buf = se._OHLCVBuffer()
        for i in range(se.TICKS_PER_BAR * 2):
            buf.push(2400.0 + i, 0.2, "2026-09-11T10:00:00+00:00")
        df = buf.to_dataframe()
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]
        assert len(df) == 2


class TestThePredictorFallsBackRatherThanFailing:
    """The engine must produce a decision on every closed bar. A predictor that
    raised into `_on_tick` would stop the signal loop on the tick after a real
    market move."""

    def _predictor(self, available: bool, result=None, raises=None):
        p = se._MLPredictor.__new__(se._MLPredictor)
        p._available = available

        class _Model:
            def predict_signal(self, *_a, **_k):
                if raises is not None:
                    raise raises
                return result

        p._predictor = _Model()
        return p

    def test_no_model_uses_the_ema_fallback(self) -> None:
        p = self._predictor(available=False)
        assert p.predict(_bars(se.MIN_BARS), ema_cross=1.0, symbol="XAU/USD") == ("BUY", 0.60)
        assert p.predict(_bars(se.MIN_BARS), ema_cross=-1.0, symbol="XAU/USD") == ("SELL", 0.60)

    def test_a_flat_ema_holds_rather_than_guessing(self) -> None:
        p = self._predictor(available=False)
        assert p.predict(_bars(se.MIN_BARS), ema_cross=0.0, symbol="XAU/USD") == ("HOLD", 0.50)

    def test_too_few_bars_uses_the_ema_fallback(self) -> None:
        """Even with a model loaded. The model needs its feature windows."""
        p = self._predictor(available=True, result={"direction": "long", "confidence": 0.99})
        assert p.predict(_bars(se.MIN_BARS - 1), ema_cross=1.0, symbol="XAU/USD") == ("BUY", 0.60)

    def test_a_raising_model_falls_back_and_does_not_propagate(self) -> None:
        p = self._predictor(available=True, raises=RuntimeError("model corrupt"))
        assert p.predict(_bars(se.MIN_BARS), ema_cross=-1.0, symbol="XAU/USD") == ("SELL", 0.60)

    @pytest.mark.parametrize(("raw", "expected"), [("long", "BUY"), ("short", "SELL"), ("neutral", "HOLD")])
    def test_the_model_direction_is_translated(self, raw: str, expected: str) -> None:
        p = self._predictor(available=True, result={"direction": raw, "confidence": 0.9})
        direction, confidence = p.predict(_bars(se.MIN_BARS), ema_cross=0.0, symbol="XAU/USD")
        assert (direction, confidence) == (expected, 0.9)

    def test_an_unknown_direction_is_held_not_guessed(self) -> None:
        """Anything the translation does not recognise is HOLD. Falling through
        to a direction would turn a model change into an unreviewed trade."""
        p = self._predictor(available=True, result={"direction": "sideways", "confidence": 0.95})
        assert p.predict(_bars(se.MIN_BARS), ema_cross=1.0, symbol="XAU/USD")[0] == "HOLD"

    def test_a_missing_confidence_reads_as_zero(self) -> None:
        """Absent is not confident. A default of 1.0 here would publish on a
        malformed model response."""
        p = self._predictor(available=True, result={"direction": "long"})
        assert p.predict(_bars(se.MIN_BARS), ema_cross=0.0, symbol="XAU/USD")[1] == 0.0


class TestTheGatesBetweenATickAndASignal:
    """Each gate from both sides. `bus.publish_signal` is patched at the seam."""

    @staticmethod
    def _engine():
        engine = se.StrategyEngine()
        engine._buffer = se._OHLCVBuffer()
        return engine

    def _run(self, engine, tick):
        with patch.object(se.bus, "publish_signal", new=AsyncMock()) as publish:
            asyncio.run(engine._on_tick(tick))
            return publish

    def test_a_non_positive_price_is_refused(self) -> None:
        """A zero or negative mid is a malformed tick, not a cheap gold price."""
        engine = self._engine()
        for bad in (0, -1.0):
            publish = self._run(engine, _tick(mid=bad))
            publish.assert_not_awaited()
        assert engine._tick_count == 0, "a refused tick must not be counted as processed"

    def test_a_tick_mid_bar_publishes_nothing(self) -> None:
        engine = self._engine()
        publish = self._run(engine, _tick())
        publish.assert_not_awaited()

    def test_a_closed_bar_during_warm_up_publishes_nothing(self) -> None:
        """The warm-up gate. Fewer than MIN_BARS and the engine has no basis."""
        engine = self._engine()
        for _ in range(se.TICKS_PER_BAR):
            publish = self._run(engine, _tick())
        publish.assert_not_awaited()
        assert engine._bar_count == 1

    def test_a_confident_signal_is_published_once_warm(self) -> None:
        engine = self._engine()
        for i in range(se.MIN_BARS):
            engine._buffer._bars.append(
                {
                    "open": 2400.0,
                    "high": 2401.0,
                    "low": 2399.0,
                    "close": 2400.0,
                    "volume": 10.0,
                    "timestamp": (pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(hours=i)).isoformat(),
                }
            )
        with patch.object(engine._predictor, "predict", return_value=("BUY", 0.91)):
            publish = self._run(engine, _tick())
            for _ in range(se.TICKS_PER_BAR - 1):
                publish = self._run(engine, _tick())
        publish.assert_awaited()
        signal = publish.await_args[0][0]
        assert signal["type"] == "signal_event"
        assert signal["direction"] == "BUY"
        assert signal["confidence"] == 0.91
        assert engine._signal_count == 1

    @pytest.mark.parametrize(
        ("direction", "confidence"),
        [("HOLD", 0.99), ("BUY", 0.0), ("BUY", 0.57), ("SELL", 0.1)],
    )
    def test_the_abstain_gate_refuses(self, direction: str, confidence: float) -> None:
        """`HOLD`, or confidence under ML_MIN_TRADE_PROB (0.58). The 0.57 case
        is the one that matters: a direction the model named, one point under
        the floor, must still not reach the order path."""
        engine = self._engine()
        for i in range(se.MIN_BARS):
            engine._buffer._bars.append(
                {
                    "open": 2400.0,
                    "high": 2401.0,
                    "low": 2399.0,
                    "close": 2400.0,
                    "volume": 10.0,
                    "timestamp": (pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(hours=i)).isoformat(),
                }
            )
        with patch.object(engine._predictor, "predict", return_value=(direction, confidence)):
            for _ in range(se.TICKS_PER_BAR):
                publish = self._run(engine, _tick())
        assert not [c for c in publish.await_args_list if c[0][0].get("type") == "signal_event"]
        assert engine._abstain_count == 1
        assert engine._signal_count == 0


class TestTheMetricsReportWhatHappened:
    def test_a_fresh_engine_reports_zeroes_and_not_ready(self) -> None:
        metrics = se.StrategyEngine().metrics()
        assert metrics["tick_count"] == 0
        assert metrics["signal_count"] == 0
        assert metrics["abstain_count"] == 0
        assert metrics["ml_ready"] is False

    def test_abstentions_are_counted_not_hidden(self) -> None:
        """An engine that abstains on everything and an engine that is not
        running look identical without this number."""
        engine = se.StrategyEngine()
        engine._abstain_count = 7
        assert engine.metrics()["abstain_count"] == 7


class TestTheHeartbeatAndLifecycle:
    """The heartbeat is how an operator tells "no signals because the market is
    quiet" from "no signals because the engine stopped consuming ticks"."""

    def test_a_heartbeat_is_published_on_the_interval(self) -> None:
        engine = se.StrategyEngine()
        engine._buffer = se._OHLCVBuffer()
        with patch.object(se.bus, "publish_signal", new=AsyncMock()) as publish:
            for _ in range(se.HEARTBEAT_INTERVAL):
                asyncio.run(engine._on_tick(_tick()))
        beats = [c[0][0] for c in publish.await_args_list if c[0][0].get("type") == "heartbeat"]
        assert len(beats) == 1
        assert beats[0]["source"] == "strategy_engine"
        assert beats[0]["tick_count"] == se.HEARTBEAT_INTERVAL

    def test_the_heartbeat_says_whether_the_model_is_ready(self) -> None:
        """A heartbeat that claimed ready while warming up would hide the
        reason no signals are arriving."""
        engine = se.StrategyEngine()
        engine._buffer = se._OHLCVBuffer()
        with patch.object(se.bus, "publish_signal", new=AsyncMock()) as publish:
            for _ in range(se.HEARTBEAT_INTERVAL):
                asyncio.run(engine._on_tick(_tick()))
        beat = next(c[0][0] for c in publish.await_args_list if c[0][0].get("type") == "heartbeat")
        assert beat["ml_ready"] is False

    def test_stop_is_safe_on_an_engine_that_never_started(self) -> None:
        """Shutdown runs on paths where startup failed half-way."""
        asyncio.run(se.StrategyEngine().stop())

    @staticmethod
    def _feed(*messages):
        """A stand-in for `bus.subscribe` yielding the given tick messages."""
        seen: list = []

        def subscribe(channel):
            seen.append(channel)

            async def _gen():
                for m in messages:
                    yield m

            return _gen()

        return subscribe, seen

    def test_it_consumes_the_tick_channel_and_not_another(self) -> None:
        """Subscribed to the wrong channel the engine simply never receives a
        tick — a silent failure with no error anywhere."""
        engine = se.StrategyEngine()
        engine._running = True
        subscribe, seen = self._feed()
        with patch.object(se.bus, "subscribe", new=subscribe):
            asyncio.run(engine._consume())
        assert seen == [se.CH_TICK]

    def test_each_message_reaches_the_tick_handler(self) -> None:
        engine = se.StrategyEngine()
        engine._running = True
        subscribe, _ = self._feed(_tick(), _tick())
        with (
            patch.object(se.bus, "subscribe", new=subscribe),
            patch.object(engine, "_on_tick", new=AsyncMock()) as on_tick,
        ):
            asyncio.run(engine._consume())
        assert on_tick.await_count == 2

    def test_one_bad_tick_does_not_stop_the_loop(self) -> None:
        """The property the `except` exists for. A single malformed message
        must not end the consumer, because nothing restarts it and the engine
        would go quiet with no further error."""
        engine = se.StrategyEngine()
        engine._running = True
        subscribe, _ = self._feed(_tick(), _tick(), _tick())
        calls: list[int] = []

        async def flaky(_msg):
            calls.append(1)
            if len(calls) == 1:
                raise ValueError("malformed tick")

        with patch.object(se.bus, "subscribe", new=subscribe), patch.object(engine, "_on_tick", new=flaky):
            asyncio.run(engine._consume())
        assert len(calls) == 3, "the consumer stopped on the first bad message"

    def test_a_stopped_engine_drains_no_further_messages(self) -> None:
        engine = se.StrategyEngine()
        engine._running = False
        subscribe, _ = self._feed(_tick(), _tick())
        with (
            patch.object(se.bus, "subscribe", new=subscribe),
            patch.object(engine, "_on_tick", new=AsyncMock()) as on_tick,
        ):
            asyncio.run(engine._consume())
        on_tick.assert_not_awaited()

    def test_start_marks_the_engine_running(self) -> None:
        engine = se.StrategyEngine()
        subscribe, seen = self._feed()
        with patch.object(se.bus, "subscribe", new=subscribe):
            asyncio.run(engine.start())
        assert engine._running is True
        assert seen == [se.CH_TICK]

    def test_stop_clears_running(self) -> None:
        engine = se.StrategyEngine()
        engine._running = True
        asyncio.run(engine.stop())
        assert engine._running is False
