"""Regression tests: TradeExecutor must maintain the risk state its gates read.

Round 3 audit findings S1-04 and S1-05 (docs/HARDENING_BACKLOG.md).

The recurring shape of that round: **the gate works, but nothing on the live
path populates the state it reads**, so the check runs, passes, and can never
fire. A gate whose input is never written is indistinguishable, in logs and
metrics, from a gate that is passing legitimately.

S1-04 — ``risk/manager.py`` ``size_order`` blocks when
``_state.open_positions >= _MAX_OPEN_POSITIONS`` (default 3). That counter is
incremented only by ``notify_position_opened()``, whose only production callers
were in the standalone ``hopefx_engine.py``. ``TradeExecutor`` — the path the
FastAPI app uses — never called it, so the counter stayed at 0 for the lifetime
of the process and the gate compared ``0 >= 3`` forever. The decision-engine
path could open unbounded concurrent positions.

S1-05 — ``risk_approval_token`` is documented as *"Proof this sizing passed the
full risk gate ... so the OMS can refuse any order that never went through
risk (No Unauthorized Trade)"*. ``TradeExecutor`` **minted** one when absent:
``signal.get("risk_approval_token") or f"rat-{signal.get('signal_id', 'te')}"``.
The decision engine's ``exec_signal`` carries neither key, so every order was
stamped with the literal constant ``"rat-te"`` and the authorization invariant
— a truthiness check — passed on the forged value. The control could not detect
the one thing it exists to detect, and flipping ``HOPEFX_INVARIANT_MODE`` to
``enforce`` would not have fixed it.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest


def _executor(broker=None, risk=None, tracker=None):
    from execution.trade_executor import TradeExecutor

    return TradeExecutor(
        broker=broker or MagicMock(),
        risk_manager=risk or MagicMock(),
        position_tracker=tracker or MagicMock(),
    )


@pytest.mark.unit
class TestOpenPositionAccounting:
    def test_executor_notifies_risk_manager_on_open(self):
        """Opening a position must increment the counter the gate reads (S1-04)."""
        import inspect

        from execution.trade_executor import TradeExecutor

        src = inspect.getsource(TradeExecutor)
        assert "notify_position_opened" in src, (
            "TradeExecutor must tell the RiskManager a position opened, or "
            "_MAX_OPEN_POSITIONS can never fire on this path (S1-04)."
        )
        assert "notify_position_closed" in src, (
            "TradeExecutor must tell the RiskManager a position closed, or the counter only ever grows (S1-04)."
        )

    def test_max_open_positions_gate_is_reachable(self):
        """End-to-end on RiskManager: the counter the gate reads must move.

        Uses the real RiskManager so this fails if notify_* stops updating the
        state that size_order snapshots.
        """
        from risk.manager import RiskManager

        rm = RiskManager()
        start = rm._state.open_positions

        rm.notify_position_opened("XAU_USD")
        assert rm._state.open_positions == start + 1

        rm.notify_position_closed("XAU_USD")
        assert rm._state.open_positions == start

    def test_size_order_blocks_at_the_position_cap(self):
        """With the counter at the cap, sizing must refuse."""
        from risk import manager as risk_manager_mod
        from risk.manager import RiskManager

        rm = RiskManager()
        rm.update_equity(100_000.0)

        for _ in range(risk_manager_mod._MAX_OPEN_POSITIONS):
            rm.notify_position_opened("XAU_USD")

        sizing = rm.calculate_position_size(
            symbol="XAU_USD",
            entry_price=3300.0,
            account_equity=100_000.0,
            signal_strength=0.9,
        )
        # The gate fired: zero size, and no approval token is issued for an
        # order that never passed sizing (which S1-05 then relies on).
        assert sizing.quantity == 0.0
        assert not sizing.risk_approval_token

        # One fewer open position and sizing succeeds again — proving it was
        # the cap that blocked, not some unrelated gate.
        rm.notify_position_closed("XAU_USD")
        ok = rm.calculate_position_size(
            symbol="XAU_USD",
            entry_price=3300.0,
            account_equity=100_000.0,
            signal_strength=0.9,
        )
        assert ok.quantity > 0.0


@pytest.mark.unit
class TestRiskApprovalTokenNotForged:
    def test_executor_does_not_mint_a_token(self):
        """The forged-token line must be gone (S1-05)."""
        import inspect

        from execution import trade_executor as te_mod

        src = inspect.getsource(te_mod)
        assert 'f"rat-{signal.get(' not in src, (
            "TradeExecutor must not manufacture a risk_approval_token — that "
            "makes the No Unauthorized Trade invariant unfalsifiable (S1-05)."
        )

    @pytest.mark.asyncio
    async def test_order_without_token_is_rejected(self):
        """An order that never passed sizing must not reach the broker."""
        from execution.trade_executor import TradeExecutor

        broker = MagicMock()
        broker.place_market_order = AsyncMock()

        # A real RiskManager in a healthy state, so every gate upstream of the
        # authorization check passes and the token is what blocks. With a
        # MagicMock the pre-trade gate fails closed on non-numeric attributes
        # and we would be asserting the wrong thing.
        import kill_switch as ks_module
        from risk.manager import RiskManager

        ks_module.kill_switch.reset_for_testing()
        risk = RiskManager()
        risk.update_equity(100_000.0)

        try:
            ex = TradeExecutor(broker=broker, risk_manager=risk, position_tracker=MagicMock())
            result = await ex.execute_signal(
                {"symbol": "XAU_USD", "action": "buy", "size": 1.0}  # no risk_approval_token
            )

            assert result.success is False
            assert "UNAUTHORIZED" in (result.message or ""), (
                f"expected an authorization rejection, got: {result.message}"
            )
            broker.place_market_order.assert_not_awaited()
        finally:
            ks_module.kill_switch.reset_for_testing()

    @pytest.mark.asyncio
    async def test_order_with_a_real_token_reaches_the_broker(self):
        """Control case: a properly sized order must still execute.

        Guards against over-correcting S1-05 into blocking everything.
        """
        import kill_switch as ks_module
        from execution.trade_executor import TradeExecutor
        from risk.manager import RiskManager

        ks_module.kill_switch.reset_for_testing()
        risk = RiskManager()
        risk.update_equity(100_000.0)

        sizing = risk.calculate_position_size(
            symbol="XAU_USD", entry_price=3300.0, account_equity=100_000.0, signal_strength=0.9
        )
        assert sizing.risk_approval_token, "sizing must issue a token for a valid order"

        broker = MagicMock()
        broker.place_market_order = AsyncMock(
            return_value=MagicMock(
                id="ord-1",
                status=MagicMock(value="filled"),
                average_fill_price=3300.0,
                filled_quantity=1.0,
                commission=0.0,
            )
        )
        tracker = MagicMock()
        tracker.add_position = AsyncMock()

        try:
            ex = TradeExecutor(broker=broker, risk_manager=risk, position_tracker=tracker)
            result = await ex.execute_signal(
                {
                    "symbol": "XAU_USD",
                    "action": "buy",
                    "size": 1.0,
                    "risk_approval_token": sizing.risk_approval_token,
                }
            )
            assert result.success is True, f"legitimate order was blocked: {result.message}"
            broker.place_market_order.assert_awaited_once()
        finally:
            ks_module.kill_switch.reset_for_testing()

    def test_decision_engine_propagates_the_real_token(self):
        """The decision engine must forward sizing's token, not drop it."""
        import inspect

        from core.decision import HOPEFXDecisionEngine as mod

        src = inspect.getsource(mod)
        assert "risk_approval_token" in src, (
            "HOPEFXDecisionEngine must copy sizing.risk_approval_token onto the "
            "execution signal, or TradeExecutor has nothing real to verify (S1-05)."
        )
