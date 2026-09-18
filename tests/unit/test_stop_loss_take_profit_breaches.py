# tests/unit/test_execution_coverage6.py
"""Coverage tests for execution/sl_tp_monitor.py and execution/position_manager.py."""

from __future__ import annotations

import pytest


# ── SLTPMonitor ───────────────────────────────────────────────────────────────


class TestSLTPMonitorCheckBreach:
    """Unit tests for the static _check_breach method — no I/O needed."""

    def _pos(self, side, sl=None, tp=None):
        class FakePos:
            position_id = "p1"
            symbol = "XAUUSD"
            quantity = 0.1

        p = FakePos()
        p.side = side
        p.stop_loss = sl
        p.take_profit = tp
        return p

    def test_long_sl_breached(self):
        from execution.sl_tp_monitor import SLTPMonitor

        pos = self._pos("LONG", sl=2300.0)
        assert SLTPMonitor._check_breach(pos, 2299.0) == "stop_loss"

    def test_long_sl_not_breached(self):
        from execution.sl_tp_monitor import SLTPMonitor

        pos = self._pos("LONG", sl=2300.0)
        assert SLTPMonitor._check_breach(pos, 2301.0) is None

    def test_long_tp_breached(self):
        from execution.sl_tp_monitor import SLTPMonitor

        pos = self._pos("LONG", tp=2400.0)
        assert SLTPMonitor._check_breach(pos, 2400.0) == "take_profit"

    def test_long_tp_not_breached(self):
        from execution.sl_tp_monitor import SLTPMonitor

        pos = self._pos("LONG", tp=2400.0)
        assert SLTPMonitor._check_breach(pos, 2399.0) is None

    def test_short_sl_breached(self):
        from execution.sl_tp_monitor import SLTPMonitor

        pos = self._pos("SHORT", sl=2400.0)
        assert SLTPMonitor._check_breach(pos, 2401.0) == "stop_loss"

    def test_short_sl_not_breached(self):
        from execution.sl_tp_monitor import SLTPMonitor

        pos = self._pos("SHORT", sl=2400.0)
        assert SLTPMonitor._check_breach(pos, 2399.0) is None

    def test_short_tp_breached(self):
        from execution.sl_tp_monitor import SLTPMonitor

        pos = self._pos("SHORT", tp=2300.0)
        assert SLTPMonitor._check_breach(pos, 2300.0) == "take_profit"

    def test_short_tp_not_breached(self):
        from execution.sl_tp_monitor import SLTPMonitor

        pos = self._pos("SHORT", tp=2300.0)
        assert SLTPMonitor._check_breach(pos, 2301.0) is None

    def test_buy_side_alias(self):
        from execution.sl_tp_monitor import SLTPMonitor

        pos = self._pos("BUY", sl=2300.0)
        assert SLTPMonitor._check_breach(pos, 2299.0) == "stop_loss"

    def test_sell_side_alias(self):
        from execution.sl_tp_monitor import SLTPMonitor

        pos = self._pos("SELL", sl=2400.0)
        assert SLTPMonitor._check_breach(pos, 2401.0) == "stop_loss"

    def test_no_sl_no_tp(self):
        from execution.sl_tp_monitor import SLTPMonitor

        pos = self._pos("LONG")
        assert SLTPMonitor._check_breach(pos, 2350.0) is None

    def test_zero_sl_ignored(self):
        from execution.sl_tp_monitor import SLTPMonitor

        pos = self._pos("LONG", sl=0.0)
        assert SLTPMonitor._check_breach(pos, 1.0) is None

    def test_unknown_side_returns_none(self):
        from execution.sl_tp_monitor import SLTPMonitor

        pos = self._pos("UNKNOWN", sl=2300.0, tp=2400.0)
        assert SLTPMonitor._check_breach(pos, 2350.0) is None


class TestSLTPMonitorGetMid:
    def _monitor(self, ticks):
        from execution.sl_tp_monitor import SLTPMonitor

        return SLTPMonitor(None, None, ticks)

    def test_get_mid_with_mid_attr(self):
        class Tick:
            mid = 2350.0

        m = self._monitor({"XAUUSD": Tick()})
        assert m._get_mid("XAUUSD") == 2350.0

    def test_get_mid_with_price_attr(self):
        class Tick:
            price = 2351.0

        m = self._monitor({"XAUUSD": Tick()})
        assert m._get_mid("XAUUSD") == 2351.0

    def test_get_mid_missing_symbol(self):
        m = self._monitor({})
        assert m._get_mid("XAUUSD") is None


class TestSLTPMonitorLifecycle:
    @pytest.mark.asyncio
    async def test_start_stop(self):
        from execution.sl_tp_monitor import SLTPMonitor

        m = SLTPMonitor(None, None, {})
        await m.start()
        assert m._running
        await m.stop()
        assert not m._running

    @pytest.mark.asyncio
    async def test_start_idempotent(self):
        from execution.sl_tp_monitor import SLTPMonitor

        m = SLTPMonitor(None, None, {})
        await m.start()
        await m.start()  # second call is no-op
        assert m._running
        await m.stop()

    @pytest.mark.asyncio
    async def test_check_all_positions_no_pm(self):
        from execution.sl_tp_monitor import SLTPMonitor

        m = SLTPMonitor(None, None, {})
        # Should not raise when pm is None
        await m._check_all_positions()

    @pytest.mark.asyncio
    async def test_check_all_positions_no_breach(self):
        from execution.sl_tp_monitor import SLTPMonitor

        class FakePM:
            def get_all_positions(self):
                class Pos:
                    position_id = "p1"
                    symbol = "XAUUSD"
                    side = "LONG"
                    stop_loss = 2300.0
                    take_profit = 2400.0
                    quantity = 0.1

                return {"p1": Pos()}

        ticks = {}

        class Tick:
            mid = 2350.0

        ticks["XAUUSD"] = Tick()
        m = SLTPMonitor(FakePM(), None, ticks)
        await m._check_all_positions()  # no breach → no close task

    @pytest.mark.asyncio
    async def test_check_all_positions_pm_raises(self):
        from execution.sl_tp_monitor import SLTPMonitor

        class BadPM:
            def get_all_positions(self):
                raise RuntimeError("redis down")

        m = SLTPMonitor(BadPM(), None, {})
        # Should not propagate
        await m._check_all_positions()


# ── PositionManager ───────────────────────────────────────────────────────────


class TestPositionManager:
    def setup_method(self):
        from execution.position_manager import PositionManager

        self.PM = PositionManager

    @pytest.mark.asyncio
    async def test_open_and_get_position(self):
        pm = self.PM()
        await pm.open_position(symbol="XAUUSD", side="BUY", quantity=0.1, entry_price=2350.0)
        pos = pm.get_position("XAUUSD")
        assert pos is not None
        assert pos.symbol == "XAUUSD"

    @pytest.mark.asyncio
    async def test_open_duplicate_raises(self):
        from execution.position_manager import PositionAlreadyOpenError

        pm = self.PM()
        await pm.open_position("XAUUSD", "BUY", 0.1, 2350.0)
        with pytest.raises(PositionAlreadyOpenError):
            await pm.open_position("XAUUSD", "BUY", 0.1, 2351.0)

    @pytest.mark.asyncio
    async def test_close_position(self):
        pm = self.PM()
        await pm.open_position("XAUUSD", "BUY", 0.1, 2350.0)
        result = await pm.close_position(symbol="XAUUSD", fill_price=2360.0)
        assert result is not None
        assert pm.get_position("XAUUSD") is None

    @pytest.mark.asyncio
    async def test_close_nonexistent_raises(self):
        from execution.position_manager import PositionNotFoundError

        pm = self.PM()
        with pytest.raises(PositionNotFoundError):
            await pm.close_position("XAUUSD", fill_price=2350.0)

    @pytest.mark.asyncio
    async def test_update_position(self):
        pm = self.PM()
        await pm.open_position("XAUUSD", "BUY", 0.1, 2350.0)
        await pm.update_position("XAUUSD", last_price=2360.0)
        pos = pm.get_position("XAUUSD")
        assert pos.last_price == pytest.approx(2360.0)

    @pytest.mark.asyncio
    async def test_update_nonexistent_raises(self):
        from execution.position_manager import PositionNotFoundError

        pm = self.PM()
        with pytest.raises(PositionNotFoundError):
            await pm.update_position("UNKNOWN", last_price=2350.0)

    def test_get_all_positions(self):
        pm = self.PM()
        positions = pm.get_all_positions()
        assert isinstance(positions, dict)

    def test_get_total_exposure_empty(self):
        pm = self.PM()
        assert pm.get_total_exposure() == 0.0

    @pytest.mark.asyncio
    async def test_get_total_exposure_with_position(self):
        pm = self.PM()
        await pm.open_position("XAUUSD", "BUY", 0.1, 2350.0)
        exposure = pm.get_total_exposure()
        assert exposure > 0

    @pytest.mark.asyncio
    async def test_get_unrealized_pnl(self):
        pm = self.PM()
        await pm.open_position("XAUUSD", "BUY", 0.1, 2350.0)
        await pm.update_position("XAUUSD", last_price=2360.0)
        pnl = pm.get_unrealized_pnl()
        assert "XAUUSD" in pnl

    def test_get_history_empty(self):
        pm = self.PM()
        assert pm.get_history() == []

    @pytest.mark.asyncio
    async def test_get_history_after_close(self):
        pm = self.PM()
        await pm.open_position("XAUUSD", "BUY", 0.1, 2350.0)
        await pm.close_position("XAUUSD", fill_price=2360.0)
        history = pm.get_history()
        assert len(history) == 1

    @pytest.mark.asyncio
    async def test_pnl_buy_profit(self):
        pm = self.PM()
        await pm.open_position("XAUUSD", "BUY", 1.0, 2350.0)
        result = await pm.close_position("XAUUSD", fill_price=2360.0)
        assert result.realized_pnl > 0

    @pytest.mark.asyncio
    async def test_pnl_buy_loss(self):
        pm = self.PM()
        await pm.open_position("XAUUSD", "BUY", 1.0, 2350.0)
        result = await pm.close_position("XAUUSD", fill_price=2340.0)
        assert result.realized_pnl < 0

    @pytest.mark.asyncio
    async def test_multiple_symbols(self):
        pm = self.PM()
        await pm.open_position("XAUUSD", "BUY", 0.1, 2350.0)
        await pm.open_position("EURUSD", "SELL", 0.2, 1.0850)
        assert len(pm.get_all_positions()) == 2

    @pytest.mark.asyncio
    async def test_restore_from_redis_no_redis(self):
        pm = self.PM()
        count = await pm.restore_from_redis()
        assert count == 0
