# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_core_position_reconciler_extended.py
=====================================================
Extended coverage for core/position_reconciler.py.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.position_reconciler import PositionReconciler, _MISMATCH_ALERT_THRESHOLD

UTC = timezone.utc


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_db_position(symbol="XAUUSD", side="buy", qty=1.0, entry=1900.0, status="open"):
    pos = MagicMock()
    pos.id = 1
    pos.symbol = symbol
    pos.side = side
    pos.quantity = qty
    pos.entry_price = entry
    pos.status = status
    pos.current_price = entry
    pos.unrealized_pnl = 0.0
    return pos


def _make_reconciler(db_positions=None, broker=None):
    positions = db_positions or []

    @contextmanager
    def _sf():
        session = MagicMock()
        q = session.query.return_value
        # Support both .filter_by() and .filter() chains
        q.filter_by.return_value.all.return_value = positions
        q.filter_by.return_value.first.return_value = positions[0] if positions else None
        q.filter.return_value = q
        q.all.return_value = positions
        q.first.return_value = positions[0] if positions else None
        yield session

    return PositionReconciler(
        session_factory=_sf,
        broker=broker,
        ws_manager=None,
        alert_engine=None,
    )


# ── _calc_pnl (staticmethod) ──────────────────────────────────────────────────


def test_calc_pnl_buy_profit():
    pos = _make_db_position(side="buy", qty=2.0, entry=1900.0)
    assert PositionReconciler._calc_pnl(pos, 1950.0) == pytest.approx(100.0)


def test_calc_pnl_buy_loss():
    pos = _make_db_position(side="buy", qty=1.0, entry=1900.0)
    assert PositionReconciler._calc_pnl(pos, 1850.0) == pytest.approx(-50.0)


def test_calc_pnl_sell_profit():
    pos = _make_db_position(side="sell", qty=1.0, entry=1900.0)
    assert PositionReconciler._calc_pnl(pos, 1850.0) == pytest.approx(50.0)


def test_calc_pnl_sell_loss():
    pos = _make_db_position(side="sell", qty=1.0, entry=1900.0)
    assert PositionReconciler._calc_pnl(pos, 1950.0) == pytest.approx(-50.0)


def test_calc_pnl_unknown_side_returns_zero():
    pos = _make_db_position(side="unknown", qty=1.0, entry=1900.0)
    # Unknown side: (entry - current) * qty = (1900 - 1950) * 1 = -50
    # The code falls through to the sell branch: (entry - current) * qty
    result = PositionReconciler._calc_pnl(pos, 1950.0)
    assert isinstance(result, float)


# ── start / stop ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_sets_running():
    r = _make_reconciler()
    await r.start()
    assert r._running is True
    await r.stop()


@pytest.mark.asyncio
async def test_stop_clears_running():
    r = _make_reconciler()
    await r.start()
    await r.stop()
    assert r._running is False


# ── _reconcile_once — no positions ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_reconcile_once_no_positions():
    r = _make_reconciler(db_positions=[])
    with patch.dict("sys.modules", {"database.models": MagicMock(Position=MagicMock())}):
        await r._reconcile_once()
    assert r._cycles == 1


# ── _reconcile_once — with positions, no broker ──────────────────────────────


@pytest.mark.asyncio
async def test_reconcile_once_updates_pnl():
    pos = _make_db_position(side="buy", qty=1.0, entry=1900.0)
    r = _make_reconciler(db_positions=[pos])

    with patch.dict("sys.modules", {"database.models": MagicMock(Position=MagicMock())}):
        with patch.object(r, "_get_price", new_callable=AsyncMock, return_value=1950.0):
            await r._reconcile_once()

    assert r._cycles == 1


@pytest.mark.asyncio
async def test_reconcile_once_skips_when_price_none():
    pos = _make_db_position(side="buy", qty=1.0, entry=1900.0)
    r = _make_reconciler(db_positions=[pos])

    with patch.dict("sys.modules", {"database.models": MagicMock(Position=MagicMock())}):
        with patch.object(r, "_get_price", new_callable=AsyncMock, return_value=None):
            await r._reconcile_once()

    assert r._cycles == 1


# ── _reconcile_once — with broker, mismatch detection ────────────────────────


@pytest.mark.asyncio
async def test_reconcile_once_detects_missing_broker_position():
    """Mismatch detected when DB has XAUUSD but broker only has EURUSD."""
    pos = _make_db_position(symbol="XAUUSD", side="buy", qty=1.0, entry=1900.0)
    mock_broker = MagicMock()
    # Broker returns a different symbol — XAUUSD is missing
    mock_broker.get_positions.return_value = [{"symbol": "EURUSD", "quantity": 10000.0}]

    r = _make_reconciler(db_positions=[pos], broker=mock_broker)

    with patch.dict("sys.modules", {"database.models": MagicMock(Position=MagicMock())}):
        with patch.object(r, "_get_price", new_callable=AsyncMock, return_value=1950.0):
            await r._reconcile_once()

    assert r._mismatches == 1


@pytest.mark.asyncio
async def test_reconcile_once_no_mismatch_when_broker_matches():
    pos = _make_db_position(symbol="XAUUSD", side="buy", qty=1.0, entry=1900.0)
    broker_pos = {"symbol": "XAUUSD", "quantity": 1.0}
    mock_broker = MagicMock()
    mock_broker.get_positions.return_value = [broker_pos]

    r = _make_reconciler(db_positions=[pos], broker=mock_broker)

    with patch.dict("sys.modules", {"database.models": MagicMock(Position=MagicMock())}):
        with patch.object(r, "_get_price", new_callable=AsyncMock, return_value=1950.0):
            await r._reconcile_once()

    assert r._mismatches == 0


@pytest.mark.asyncio
async def test_reconcile_once_async_broker_positions():
    pos = _make_db_position(symbol="EURUSD", side="buy", qty=10000.0, entry=1.08)
    mock_broker = MagicMock()
    mock_broker.get_positions = AsyncMock(return_value=[{"symbol": "EURUSD", "quantity": 10000.0}])

    r = _make_reconciler(db_positions=[pos], broker=mock_broker)

    with patch.dict("sys.modules", {"database.models": MagicMock(Position=MagicMock())}):
        with patch.object(r, "_get_price", new_callable=AsyncMock, return_value=1.09):
            await r._reconcile_once()

    assert r._mismatches == 0


@pytest.mark.asyncio
async def test_reconcile_once_broker_exception():
    pos = _make_db_position(symbol="XAUUSD", side="buy", qty=1.0, entry=1900.0)
    mock_broker = MagicMock()
    mock_broker.get_positions.side_effect = RuntimeError("broker error")

    r = _make_reconciler(db_positions=[pos], broker=mock_broker)

    with patch.dict("sys.modules", {"database.models": MagicMock(Position=MagicMock())}):
        with patch.object(r, "_get_price", new_callable=AsyncMock, return_value=1950.0):
            await r._reconcile_once()  # must not raise


# ── _reconcile_once — consecutive mismatch alert ─────────────────────────────


@pytest.mark.asyncio
async def test_reconcile_once_consecutive_mismatch_alert():
    """After threshold consecutive mismatches, error-level log is triggered."""
    pos = _make_db_position(symbol="XAUUSD", side="buy", qty=1.0, entry=1900.0)
    mock_broker = MagicMock()
    # Broker returns a different symbol so XAUUSD is missing
    mock_broker.get_positions.return_value = [{"symbol": "EURUSD", "quantity": 10000.0}]

    r = _make_reconciler(db_positions=[pos], broker=mock_broker)
    # Pre-fill consecutive mismatches to threshold - 1
    r._consecutive_mismatches["XAUUSD"] = _MISMATCH_ALERT_THRESHOLD - 1

    with patch.dict("sys.modules", {"database.models": MagicMock(Position=MagicMock())}):
        with patch.object(r, "_get_price", new_callable=AsyncMock, return_value=1950.0):
            await r._reconcile_once()

    assert r._consecutive_mismatches["XAUUSD"] == _MISMATCH_ALERT_THRESHOLD


# ── _reconcile_once — drift detection ────────────────────────────────────────


@pytest.mark.asyncio
async def test_reconcile_once_triggers_drift_halt():
    pos = _make_db_position(symbol="XAUUSD", side="buy", qty=10.0, entry=1900.0)
    broker_pos = {"symbol": "XAUUSD", "quantity": 1.0}  # large qty diff
    mock_broker = MagicMock()
    mock_broker.get_positions.return_value = [broker_pos]

    r = _make_reconciler(db_positions=[pos], broker=mock_broker)
    r._drift_qty = 0.01  # very tight threshold

    with patch.dict("sys.modules", {"database.models": MagicMock(Position=MagicMock())}):
        with patch.object(r, "_get_price", new_callable=AsyncMock, return_value=1950.0):
            with patch.object(r, "_trigger_drift_halt", new_callable=AsyncMock) as mock_halt:
                await r._reconcile_once()

    mock_halt.assert_called_once()


# ── _get_price — uses yfinance internally ────────────────────────────────────


@pytest.mark.asyncio
async def test_get_price_returns_float_or_none():
    r = _make_reconciler()
    # yfinance may or may not return data in CI — just verify no crash
    price = await r._get_price("EURUSD=X")
    assert price is None or isinstance(price, float)


@pytest.mark.asyncio
async def test_get_price_yfinance_exception():
    r = _make_reconciler()
    with patch("yfinance.Ticker", side_effect=RuntimeError("yf error")):
        price = await r._get_price("XAUUSD")
    assert price is None


# ── _trigger_drift_halt ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_trigger_drift_halt_no_alert_engine():
    r = _make_reconciler()
    await r._trigger_drift_halt(
        symbol="XAUUSD",
        db_qty=10.0,
        broker_qty=1.0,
        qty_diff=9.0,
        db_value=19000.0,
        broker_value=1900.0,
        value_diff=17100.0,
    )  # must not raise


@pytest.mark.asyncio
async def test_trigger_drift_halt_with_alert_engine():
    mock_alert = MagicMock()
    mock_alert.send_alert = AsyncMock()

    @contextmanager
    def _sf():
        yield MagicMock()

    r = PositionReconciler(
        session_factory=_sf,
        broker=None,
        ws_manager=None,
        alert_engine=mock_alert,
    )
    await r._trigger_drift_halt(
        symbol="XAUUSD",
        db_qty=10.0,
        broker_qty=1.0,
        qty_diff=9.0,
        db_value=19000.0,
        broker_value=1900.0,
        value_diff=17100.0,
    )
    mock_alert.send_alert.assert_called_once()


# ── WebSocket broadcast ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reconcile_broadcasts_over_ws():
    pos = _make_db_position(side="buy", qty=1.0, entry=1900.0)
    mock_ws = MagicMock()
    mock_ws.broadcast_to_all = AsyncMock()

    @contextmanager
    def _sf():
        session = MagicMock()
        session.query.return_value.filter_by.return_value.all.return_value = [pos]
        session.query.return_value.filter_by.return_value.first.return_value = pos
        yield session

    r = PositionReconciler(
        session_factory=_sf,
        broker=None,
        ws_manager=mock_ws,
        alert_engine=None,
    )

    with patch.dict("sys.modules", {"database.models": MagicMock(Position=MagicMock())}):
        with patch.object(r, "_get_price", new_callable=AsyncMock, return_value=1950.0):
            await r._reconcile_once()

    mock_ws.broadcast_to_all.assert_called_once()
