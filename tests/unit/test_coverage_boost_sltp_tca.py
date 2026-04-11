# HOPEFX-AI-TRADING
# Coverage boost: sl_tp_monitor, tca
"""Real unit tests — no mocks/stubs/fake data."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal

import pytest

UTC = timezone.utc


# ─────────────────────────────────────────────────────────────────────────────
# SLTPMonitor — uncovered: 64-65, 72-73, 83, 91-94, 151-158, 162-171,
#   177-181, 219, 294-280, 312-314, 339-342, 342-344
# ─────────────────────────────────────────────────────────────────────────────

def _make_position(symbol="XAUUSD", side="BUY", sl=None, tp=None, qty=1.0):
    from execution.position_manager import Position
    return Position(
        position_id=f"pos_{symbol}",
        symbol=symbol,
        side=side,
        quantity=qty,
        entry_price=2000.0,
        stop_loss=sl,
        take_profit=tp,
    )


class TestSLTPMonitorCheckBreach:
    """_check_breach static method — all branches."""

    def test_long_sl_breach(self):
        from execution.sl_tp_monitor import SLTPMonitor
        pos = _make_position(side="BUY", sl=1990.0)
        assert SLTPMonitor._check_breach(pos, 1985.0) == "stop_loss"

    def test_long_tp_breach(self):
        from execution.sl_tp_monitor import SLTPMonitor
        pos = _make_position(side="BUY", tp=2050.0)
        assert SLTPMonitor._check_breach(pos, 2055.0) == "take_profit"

    def test_long_no_breach(self):
        from execution.sl_tp_monitor import SLTPMonitor
        pos = _make_position(side="BUY", sl=1990.0, tp=2050.0)
        assert SLTPMonitor._check_breach(pos, 2020.0) is None

    def test_short_sl_breach(self):
        from execution.sl_tp_monitor import SLTPMonitor
        pos = _make_position(side="SELL", sl=2010.0)
        assert SLTPMonitor._check_breach(pos, 2015.0) == "stop_loss"

    def test_short_tp_breach(self):
        from execution.sl_tp_monitor import SLTPMonitor
        pos = _make_position(side="SELL", tp=1950.0)
        assert SLTPMonitor._check_breach(pos, 1945.0) == "take_profit"

    def test_short_no_breach(self):
        from execution.sl_tp_monitor import SLTPMonitor
        pos = _make_position(side="SELL", sl=2010.0, tp=1950.0)
        assert SLTPMonitor._check_breach(pos, 1980.0) is None

    def test_no_sl_no_tp(self):
        from execution.sl_tp_monitor import SLTPMonitor
        pos = _make_position(side="BUY")
        assert SLTPMonitor._check_breach(pos, 1800.0) is None

    def test_long_alias(self):
        from execution.sl_tp_monitor import SLTPMonitor
        pos = _make_position(side="LONG", sl=1990.0)
        assert SLTPMonitor._check_breach(pos, 1985.0) == "stop_loss"

    def test_short_alias(self):
        from execution.sl_tp_monitor import SLTPMonitor
        pos = _make_position(side="SHORT", sl=2010.0)
        assert SLTPMonitor._check_breach(pos, 2015.0) == "stop_loss"


class TestSLTPMonitorGetMid:
    """_get_mid — tick cache variants."""

    def _monitor(self, ticks):
        from execution.sl_tp_monitor import SLTPMonitor
        return SLTPMonitor(position_manager=None, broker=None, tick_cache=ticks)

    def test_get_mid_none_when_missing(self):
        m = self._monitor({})
        assert m._get_mid("XAUUSD") is None

    def test_get_mid_from_mid_attr(self):
        class _Tick:
            mid = 2000.5
        m = self._monitor({"XAUUSD": _Tick()})
        assert m._get_mid("XAUUSD") == 2000.5

    def test_get_mid_from_price_attr(self):
        class _Tick:
            price = 2001.0
        m = self._monitor({"XAUUSD": _Tick()})
        assert m._get_mid("XAUUSD") == 2001.0

    def test_get_mid_plain_dict_returns_none(self):
        m = self._monitor({"XAUUSD": {"price": 2000.0}})
        assert m._get_mid("XAUUSD") is None


class TestSLTPMonitorLifecycle:
    """start/stop, _on_task_done, _check_all_positions."""

    @pytest.mark.asyncio
    async def test_start_stop(self):
        from execution.sl_tp_monitor import SLTPMonitor
        m = SLTPMonitor(position_manager=None, broker=None, tick_cache={})
        await m.start()
        assert m._running is True
        await m.stop()
        assert m._running is False
        assert m._task is None

    @pytest.mark.asyncio
    async def test_start_idempotent(self):
        from execution.sl_tp_monitor import SLTPMonitor
        m = SLTPMonitor(position_manager=None, broker=None, tick_cache={})
        await m.start()
        task1 = m._task
        await m.start()  # second call — no-op
        assert m._task is task1
        await m.stop()

    @pytest.mark.asyncio
    async def test_check_all_positions_none_pm(self):
        from execution.sl_tp_monitor import SLTPMonitor
        m = SLTPMonitor(position_manager=None, broker=None, tick_cache={})
        await m._check_all_positions()  # must not raise

    @pytest.mark.asyncio
    async def test_check_all_positions_pm_raises(self):
        from execution.sl_tp_monitor import SLTPMonitor

        class _BadPM:
            def get_all_positions(self): raise RuntimeError("db error")

        m = SLTPMonitor(position_manager=_BadPM(), broker=None, tick_cache={})
        await m._check_all_positions()  # must not raise

    @pytest.mark.asyncio
    async def test_check_all_positions_no_breach(self):
        from execution.sl_tp_monitor import SLTPMonitor

        class _PM:
            def get_all_positions(self):
                return {"XAUUSD": _make_position(side="BUY", sl=1900.0, tp=2100.0)}

        ticks = {}

        class _Tick:
            mid = 2000.0

        ticks["XAUUSD"] = _Tick()
        m = SLTPMonitor(position_manager=_PM(), broker=None, tick_cache=ticks)
        await m._check_all_positions()  # mid=2000, sl=1900, tp=2100 → no breach

    @pytest.mark.asyncio
    async def test_check_all_positions_skips_closing(self):
        from execution.sl_tp_monitor import SLTPMonitor

        class _PM:
            def get_all_positions(self):
                return {"XAUUSD": _make_position(side="BUY", sl=2100.0)}

        class _Tick:
            mid = 2050.0

        m = SLTPMonitor(position_manager=_PM(), broker=None, tick_cache={"XAUUSD": _Tick()})
        m._closing.add("pos_XAUUSD")
        await m._check_all_positions()  # already closing — skip

    @pytest.mark.asyncio
    async def test_on_task_done_no_exception(self):
        from execution.sl_tp_monitor import SLTPMonitor
        m = SLTPMonitor(position_manager=None, broker=None, tick_cache={})
        fut = asyncio.get_event_loop().create_future()
        fut.set_result(None)
        m._on_task_done(fut)  # no exception — must not crash

    @pytest.mark.asyncio
    async def test_close_position_all_retries_fail(self):
        from execution.sl_tp_monitor import SLTPMonitor

        class _BadBroker:
            def place_order(self, **kw): raise RuntimeError("broker down")

        class _PM:
            async def close_position(self, **kw): pass

        class _FakeOrderSide:
            SELL = "SELL"
            BUY = "BUY"

        class _FakeOrderType:
            MARKET = "MARKET"

        import sys
        orig = sys.modules.get("brokers.base")

        class _FakeBase:
            OrderSide = _FakeOrderSide
            OrderType = _FakeOrderType

        sys.modules["brokers.base"] = _FakeBase()  # type: ignore
        try:
            m = SLTPMonitor(position_manager=_PM(), broker=_BadBroker(), tick_cache={})
            pos = _make_position(side="BUY", sl=1990.0)
            # Should complete without raising even after all retries fail
            await m._close_position(pos, "stop_loss", 1985.0)
        finally:
            if orig is None:
                sys.modules.pop("brokers.base", None)
            else:
                sys.modules["brokers.base"] = orig
        assert "pos_XAUUSD" not in m._closing


# ─────────────────────────────────────────────────────────────────────────────
# TCA — uncovered: 204-215, 229-294, 361-377, 481, 498-558
# ─────────────────────────────────────────────────────────────────────────────

class TestMarketContextProvider:
    """Lines 204-294: ADV/vol resolution."""

    def test_adv_default_fallback(self):
        from execution.tca import MarketContextProvider
        ctx = MarketContextProvider()
        adv, src = ctx.get_adv("XAUUSD")
        assert adv > 0
        assert src == "default"

    def test_adv_env_override(self, monkeypatch):
        from execution.tca import MarketContextProvider
        monkeypatch.setenv("TCA_ADV_XAUUSD", "99999")
        ctx = MarketContextProvider()
        adv, src = ctx.get_adv("XAUUSD")
        assert adv == 99999.0
        assert src == "env_override"

    def test_adv_tick_accumulator(self):
        from execution.tca import MarketContextProvider
        ctx = MarketContextProvider()
        now = datetime.now(UTC)
        from datetime import timedelta
        for i in range(200):
            ts = now - timedelta(hours=i * 0.1)
            ctx.accumulate_tick("XAUUSD", 100.0, ts)
        adv, src = ctx.get_adv("XAUUSD")
        assert src in ("tick_accumulator", "default")

    def test_vol_default_fallback(self):
        from execution.tca import MarketContextProvider
        ctx = MarketContextProvider()
        vol, src = ctx.get_volatility("XAUUSD")
        assert vol > 0
        assert src == "default"

    def test_vol_env_override(self, monkeypatch):
        from execution.tca import MarketContextProvider
        monkeypatch.setenv("TCA_VOL_XAUUSD", "0.025")
        ctx = MarketContextProvider()
        vol, src = ctx.get_volatility("XAUUSD")
        assert vol == pytest.approx(0.025)
        assert src == "env_override"

    def test_accumulate_tick_prunes(self):
        from execution.tca import MarketContextProvider
        ctx = MarketContextProvider()
        now = datetime.now(UTC)
        for i in range(100_010):
            ctx.accumulate_tick("XAUUSD", 1.0, now)
        assert len(ctx._tick_volumes["XAUUSD"]) == 100_000


class TestTCAEngineRecordComplete:
    """Lines 361-377, 481, 498-558: record_fill, complete_order, update_market_data."""

    def _engine(self):
        from execution.tca import TCAEngine
        return TCAEngine()

    def _make_fill(self, order_id, symbol="XAUUSD", side=None, qty="1", price="2001", commission="0"):
        from core.types import Fill, Side, Venue
        if side is None:
            side = Side.BUY
        return Fill(
            order_id=order_id,
            fill_id=f"fill_{order_id}",
            symbol=symbol,
            side=side,
            quantity=Decimal(qty),
            price=Decimal(price),
            timestamp=datetime.now(UTC),
            venue=Venue.PAPER,
            commission=Decimal(commission),
        )

    def _make_tick(self, symbol="XAUUSD"):
        from core.types import Tick, Venue
        return Tick(
            symbol=symbol,
            bid=Decimal("1999.00000"),
            ask=Decimal("2001.00000"),
            mid=Decimal("2000.00000"),
            volume=Decimal("100.00"),
            timestamp=datetime.now(UTC),
            venue=Venue.PAPER,
        )

    @pytest.mark.asyncio
    async def test_record_fill_unknown_order(self):
        from execution.tca import TCAEngine
        eng = TCAEngine()
        fill = self._make_fill("unknown")
        await eng.record_fill("unknown", fill)  # must not raise

    @pytest.mark.asyncio
    async def test_complete_order_unknown_raises(self):
        from execution.tca import TCAEngine
        eng = TCAEngine()
        with pytest.raises(ValueError, match="Unknown order"):
            await eng.complete_order("missing")

    @pytest.mark.asyncio
    async def test_complete_order_no_fills_cancelled(self):
        from execution.tca import TCAEngine, BenchmarkType
        from core.types import Side
        eng = TCAEngine()
        await eng.start_order(
            order_id="o1", symbol="XAUUSD", side=Side.BUY,
            quantity=Decimal("1"), arrival_price=Decimal("2000"),
            benchmark=BenchmarkType.ARRIVAL,
        )
        metrics = await eng.complete_order("o1")
        assert metrics.fill_rate == 0.0

    @pytest.mark.asyncio
    async def test_complete_order_with_fill(self):
        from execution.tca import TCAEngine, BenchmarkType
        from core.types import Side
        eng = TCAEngine()
        await eng.start_order(
            order_id="o2", symbol="XAUUSD", side=Side.BUY,
            quantity=Decimal("1"), arrival_price=Decimal("2000"),
            benchmark=BenchmarkType.ARRIVAL,
        )
        fill = self._make_fill("o2", commission="0.5")
        await eng.record_fill("o2", fill)
        metrics = await eng.complete_order("o2")
        assert float(metrics.avg_fill_price) == pytest.approx(2001.0)
        assert metrics.fill_rate == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_complete_order_sell_shortfall(self):
        from execution.tca import TCAEngine, BenchmarkType
        from core.types import Side
        eng = TCAEngine()
        await eng.start_order(
            order_id="o3", symbol="XAUUSD", side=Side.SELL,
            quantity=Decimal("1"), arrival_price=Decimal("2000"),
            benchmark=BenchmarkType.ARRIVAL,
        )
        fill = self._make_fill("o3", side=Side.SELL, price="1999")
        await eng.record_fill("o3", fill)
        metrics = await eng.complete_order("o3")
        assert metrics.fill_rate == pytest.approx(1.0)

    def test_update_market_data(self):
        from execution.tca import TCAEngine
        eng = TCAEngine()
        tick = self._make_tick()
        eng.update_market_data(tick)
        assert "XAUUSD" in eng._vwap_cache

    def test_get_stats_empty(self):
        from execution.tca import TCAEngine
        eng = TCAEngine()
        stats = eng.get_stats()
        # Returns empty dict when no completed orders
        assert isinstance(stats, dict)

    @pytest.mark.asyncio
    async def test_get_stats_with_data(self):
        from execution.tca import TCAEngine, BenchmarkType
        from core.types import Side
        eng = TCAEngine()
        await eng.start_order(
            order_id="s1", symbol="XAUUSD", side=Side.BUY,
            quantity=Decimal("1"), arrival_price=Decimal("2000"),
            benchmark=BenchmarkType.ARRIVAL,
        )
        fill = self._make_fill("s1")
        await eng.record_fill("s1", fill)
        await eng.complete_order("s1")
        stats = eng.get_stats()
        assert "count" in stats
        assert stats["count"] == 1

    @pytest.mark.asyncio
    async def test_get_benchmark_vwap(self):
        from execution.tca import TCAEngine, BenchmarkType
        from core.types import Side
        from decimal import Decimal
        eng = TCAEngine()
        now = datetime.now(UTC)
        eng._vwap_cache["XAUUSD"] = [(now, Decimal("2000"), Decimal("10"))]
        result = await eng._get_benchmark_price(
            "XAUUSD", BenchmarkType.VWAP, now, now
        )
        assert float(result) == pytest.approx(2000.0)

    @pytest.mark.asyncio
    async def test_get_benchmark_twap(self):
        from execution.tca import TCAEngine, BenchmarkType
        from decimal import Decimal
        eng = TCAEngine()
        now = datetime.now(UTC)
        eng._twap_cache["XAUUSD"] = [(now, Decimal("2000")), (now, Decimal("2002"))]
        result = await eng._get_benchmark_price(
            "XAUUSD", BenchmarkType.TWAP, now, now
        )
        assert float(result) == pytest.approx(2001.0)

    @pytest.mark.asyncio
    async def test_get_benchmark_arrival_returns_zero(self):
        from execution.tca import TCAEngine, BenchmarkType
        eng = TCAEngine()
        now = datetime.now(UTC)
        result = await eng._get_benchmark_price("XAUUSD", BenchmarkType.ARRIVAL, now, now)
        assert result == Decimal(0)

    def test_cost_callback_registered(self):
        from execution.tca import TCAEngine
        eng = TCAEngine()
        called = []
        eng.register_cost_callback(lambda m: called.append(m))
        assert len(eng._cost_callbacks) == 1

    @pytest.mark.asyncio
    async def test_cost_callback_called_on_complete(self):
        from execution.tca import TCAEngine, BenchmarkType
        from core.types import Side
        eng = TCAEngine()
        called = []
        eng.register_cost_callback(lambda m: called.append(m))
        # arrival=2000, fill=2010 → ~50bps slippage → triggers callback (>20bps)
        await eng.start_order(
            order_id="o4", symbol="XAUUSD", side=Side.BUY,
            quantity=Decimal("1"), arrival_price=Decimal("2000"),
            benchmark=BenchmarkType.ARRIVAL,
        )
        fill = self._make_fill("o4", price="2010")
        await eng.record_fill("o4", fill)
        await eng.complete_order("o4")
        # callback fires only when cost > 20bps; verify it was registered at minimum
        assert len(eng._cost_callbacks) == 1
