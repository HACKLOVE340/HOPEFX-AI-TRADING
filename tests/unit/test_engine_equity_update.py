# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_engine_equity_update.py
=======================================
Round 3 audit (docs/HARDENING_BACKLOG.md S12-04b).

Fourth instance of the never-awaited-broker-call family, and the worst placed.
`HopeFXEngine._update_equity` read the account like this:

    info = self._broker.get_account_info()      # async def on every broker
    equity = float(info.get("equity", 0))       # -> AttributeError on a coroutine

The `AttributeError` was caught by the method's own
`except Exception: logger.warning("Equity update failed: %s", exc)`, so it
failed silently at WARNING on every cycle and `equity` stayed 0.0.

`RiskManager.update_equity()` is not merely bookkeeping — it recomputes
drawdown and **auto-halts trading when the drawdown limit is breached**
(`risk/manager.py:1289`). Never calling it means peak equity, current drawdown
and daily drawdown never move off their initial values, so the drawdown circuit
breaker cannot trip no matter how much the account loses.

Three sibling calls in the same file were already guarded with
`inspect.isawaitable`; this one was not.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


def _engine_with(broker):
    """A HopeFXEngine with just enough wiring for _update_equity()."""
    from hopefx_engine import HopeFXEngine

    eng = HopeFXEngine.__new__(HopeFXEngine)  # skip __init__ side effects
    eng._broker = broker
    eng._risk_manager = MagicMock()
    eng._trade_logger = MagicMock()
    return eng


def _account(equity=87_500.0, balance=90_000.0, open_positions=2):
    from brokers.base import AccountInfo

    return AccountInfo(
        balance=balance,
        equity=equity,
        margin_used=0.0,
        margin_available=equity,
        positions_count=open_positions,
    )


@pytest.mark.asyncio
async def test_equity_reaches_the_risk_manager_from_an_async_broker():
    """The whole point: without this the drawdown breaker is frozen."""
    broker = MagicMock()
    broker.get_account_info = AsyncMock(return_value=_account(equity=87_500.0))
    eng = _engine_with(broker)

    await eng._update_equity()

    eng._risk_manager.update_equity.assert_called_once()
    assert eng._risk_manager.update_equity.call_args.args[0] == pytest.approx(87_500.0), (
        "the risk manager did not receive the account equity — _update_equity "
        "read a coroutine, and the drawdown circuit breaker stays frozen at its "
        "initial value (S12-04b)"
    )


@pytest.mark.asyncio
async def test_a_sync_broker_still_works():
    """The paper broker is synchronous; it must not regress."""
    broker = MagicMock()
    broker.get_account_info = MagicMock(return_value=_account(equity=50_000.0))
    eng = _engine_with(broker)

    await eng._update_equity()

    eng._risk_manager.update_equity.assert_called_once()
    assert eng._risk_manager.update_equity.call_args.args[0] == pytest.approx(50_000.0)


@pytest.mark.asyncio
async def test_plain_dict_account_still_works():
    """Some connectors return a dict rather than an AccountInfo."""
    broker = MagicMock()
    broker.get_account_info = AsyncMock(return_value={"equity": 12_345.0, "balance": 12_000.0, "open_positions": 1})
    eng = _engine_with(broker)

    await eng._update_equity()

    assert eng._risk_manager.update_equity.call_args.args[0] == pytest.approx(12_345.0)


@pytest.mark.asyncio
async def test_the_equity_snapshot_is_logged():
    """Operators read this line; it must carry the real numbers."""
    broker = MagicMock()
    broker.get_account_info = AsyncMock(return_value=_account(equity=87_500.0, balance=90_000.0))
    eng = _engine_with(broker)

    await eng._update_equity()

    eng._trade_logger.log_equity.assert_called_once()
    kwargs = eng._trade_logger.log_equity.call_args.kwargs
    assert kwargs["equity"] == pytest.approx(87_500.0)
    assert kwargs["balance"] == pytest.approx(90_000.0)


@pytest.mark.asyncio
async def test_a_broker_error_does_not_propagate():
    """Equity refresh is best-effort; it must not kill the engine loop."""
    broker = MagicMock()
    broker.get_account_info = AsyncMock(side_effect=RuntimeError("broker down"))
    eng = _engine_with(broker)

    await eng._update_equity()  # must not raise

    eng._risk_manager.update_equity.assert_not_called()


@pytest.mark.asyncio
async def test_zero_equity_is_not_written():
    """A zero reading is a failed read, not a wiped account."""
    broker = MagicMock()
    broker.get_account_info = AsyncMock(return_value=_account(equity=0.0, balance=0.0))
    eng = _engine_with(broker)

    await eng._update_equity()

    eng._risk_manager.update_equity.assert_not_called()


@pytest.mark.asyncio
async def test_open_position_count_survives_the_field_name_difference():
    """AccountInfo calls it positions_count; dict connectors say open_positions.

    `AccountInfo.get()` is getattr-based, so asking for the wrong name returns
    the caller's default rather than raising — the count would have been logged
    as 0 for every AccountInfo-returning broker.
    """
    broker = MagicMock()
    broker.get_account_info = AsyncMock(return_value=_account(equity=10_000.0, open_positions=3))
    eng = _engine_with(broker)

    await eng._update_equity()

    assert eng._trade_logger.log_equity.call_args.kwargs["open_positions"] == 3
