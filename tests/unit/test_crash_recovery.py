"""Regression tests: a filled order must never be abandoned or lost.

Round 3 audit findings S7-01, S7-03 and S7-04 (docs/HARDENING_BACKLOG.md).

S7-01 — the invalid-fill-price guard sat **inside** the ``filled``/``partial``
branch, so it only ran for orders the broker had **already executed**. Its
response was to log, skip ``add_position()``, and return ``success=False``.
Brokers that acknowledge a fill and deliver the execution price in a later
message — routine for async and FIX fill reports — hit this deterministically.
The result was a live, unprotected position with no stop armed, invisible to
risk and the dashboard and unrecoverable on restart, while the operator was
told the trade *failed*. Reporting failure for an order that filled is the
worst available outcome; it is strictly better to record the position at a
provisional price and alert.

S7-03 — ``restore_from_redis`` treated Redis as authoritative and never
consulted the broker, so positions closed while the process was down were
resurrected, positions opened while it was down stayed unmanaged, and partial
closes left stale quantities.

S7-04 — the restore loop mutated ``self._positions`` inside the ``try`` and
caught only ``(RuntimeError, OSError)``, so a malformed record aborted the
batch mid-way, leaving partial state with the success log line never reached.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest


def _filled_order(fill_price, order_id="ord-1", qty=1.0, status="filled"):
    order = MagicMock()
    order.id = order_id
    order.status = MagicMock(value=status)
    order.average_fill_price = fill_price
    order.filled_quantity = qty
    order.commission = 0.0
    return order


def _executor(order):
    import kill_switch as ks_module
    from execution.trade_executor import TradeExecutor
    from risk.manager import RiskManager

    ks_module.kill_switch.reset_for_testing()
    risk = RiskManager()
    risk.update_equity(100_000.0)

    broker = MagicMock()
    broker.place_market_order = AsyncMock(return_value=order)

    tracker = MagicMock()
    tracker.add_position = AsyncMock()

    return TradeExecutor(broker=broker, risk_manager=risk, position_tracker=tracker), tracker


def _signal():
    return {
        "symbol": "XAU_USD",
        "action": "buy",
        "size": 1.0,
        "risk_approval_token": "rat-test-fixture",
    }


@pytest.mark.unit
class TestFilledOrderIsNeverAbandoned:
    @pytest.mark.asyncio
    async def test_fill_without_price_still_records_the_position(self):
        """A broker-confirmed fill must be tracked even without a price (S7-01)."""
        import kill_switch as ks_module

        ex, tracker = _executor(_filled_order(fill_price=0.0))
        try:
            result = await ex.execute_signal(_signal())
        finally:
            ks_module.kill_switch.reset_for_testing()

        (
            tracker.add_position.assert_awaited(),
            (
                "The broker reported this order FILLED. Skipping add_position leaves "
                "a live, unmonitored position with no stop armed (S7-01)."
            ),
        )
        assert result.success is True, (
            "Reporting failure for an order the broker filled is the worst "
            "available outcome — the caller sizes the next signal as if flat."
        )

    @pytest.mark.asyncio
    async def test_unconfirmed_price_is_flagged(self):
        """The position must be marked so the bad price is not trusted."""
        import kill_switch as ks_module

        ex, tracker = _executor(_filled_order(fill_price=None))
        try:
            await ex.execute_signal(_signal())
        finally:
            ks_module.kill_switch.reset_for_testing()

        assert tracker.add_position.await_count == 1
        position = tracker.add_position.await_args.args[0]
        assert getattr(position, "price_unconfirmed", False) is True, (
            "A position opened at a provisional price must carry a flag so "
            "downstream P&L and SL/TP do not treat it as a confirmed fill."
        )

    @pytest.mark.asyncio
    async def test_good_fill_is_unaffected(self):
        """Control case: a normal fill must behave exactly as before."""
        import kill_switch as ks_module

        ex, tracker = _executor(_filled_order(fill_price=3300.0))
        try:
            result = await ex.execute_signal(_signal())
        finally:
            ks_module.kill_switch.reset_for_testing()

        assert result.success is True
        position = tracker.add_position.await_args.args[0]
        assert position.entry_price == 3300.0
        assert getattr(position, "price_unconfirmed", False) is False


@pytest.mark.unit
class TestBootReconcilesAgainstBroker:
    @pytest.mark.asyncio
    async def test_position_closed_while_down_is_not_resurrected(self):
        """Redis is not authoritative — the broker is (S7-03)."""
        from execution.position_manager import PositionManager

        pm = PositionManager()
        pm._redis_store = MagicMock()
        pm._redis_store.load_state_on_boot = AsyncMock(
            return_value={
                "positions": [
                    {"position_id": "p1", "symbol": "XAU_USD", "side": "long", "quantity": 1.0, "entry_price": 3300.0}
                ],
                "orders": [],
            }
        )

        broker = MagicMock()
        broker.get_positions = AsyncMock(return_value=[])  # broker is flat

        restored = await pm.restore_from_redis(broker=broker)

        assert restored == 0, (
            "A position closed while the process was down was restored from "
            "Redis; the system now believes it is exposed when it is flat (S7-03)."
        )
        assert "XAU_USD" not in pm._positions

    @pytest.mark.asyncio
    async def test_position_opened_while_down_is_adopted(self):
        """A broker position Redis never saw must not stay unmanaged (S7-03)."""
        from execution.position_manager import PositionManager

        pm = PositionManager()
        pm._redis_store = MagicMock()
        pm._redis_store.load_state_on_boot = AsyncMock(return_value={"positions": [], "orders": []})

        broker_pos = MagicMock()
        broker_pos.symbol = "XAU_USD"
        broker_pos.quantity = 2.0
        broker_pos.entry_price = 3305.0
        broker_pos.side = "long"

        broker = MagicMock()
        broker.get_positions = AsyncMock(return_value=[broker_pos])

        await pm.restore_from_redis(broker=broker)

        assert "XAU_USD" in pm._positions, (
            "A position the broker holds but Redis does not was left unmanaged — "
            "no SL/TP monitoring, absent from risk exposure (S7-03)."
        )

    @pytest.mark.asyncio
    async def test_reconciliation_is_optional(self):
        """Without a broker the old behaviour must still work."""
        from execution.position_manager import PositionManager

        pm = PositionManager()
        pm._redis_store = MagicMock()
        pm._redis_store.load_state_on_boot = AsyncMock(
            return_value={
                "positions": [
                    {"position_id": "p1", "symbol": "XAU_USD", "side": "long", "quantity": 1.0, "entry_price": 3300.0}
                ],
                "orders": [],
            }
        )

        restored = await pm.restore_from_redis()
        assert restored == 1

    @pytest.mark.asyncio
    async def test_malformed_record_does_not_abort_the_batch(self):
        """One bad record must not leave partial, unreported state (S7-04)."""
        from execution.position_manager import PositionManager

        pm = PositionManager()
        pm._redis_store = MagicMock()
        pm._redis_store.load_state_on_boot = AsyncMock(
            return_value={
                "positions": [
                    {"position_id": "p1", "symbol": "XAU_USD", "side": "long", "quantity": 1.0, "entry_price": 3300.0},
                    {"garbage": True},  # unparseable
                    {"position_id": "p2", "symbol": "EUR_USD", "side": "short", "quantity": 2.0, "entry_price": 1.08},
                ],
                "orders": [],
            }
        )

        restored = await pm.restore_from_redis()

        assert restored == 2, (
            "A malformed record aborted the restore mid-loop, leaving the "
            "already-inserted positions in place with no log line (S7-04)."
        )
        assert "XAU_USD" in pm._positions
        assert "EUR_USD" in pm._positions
