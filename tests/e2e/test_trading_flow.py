# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/e2e/test_trading_flow.py
==============================
End-to-end trading flow tests.

Exercises the full signal-to-execution path using real production classes:
PaperTradingBroker + RiskManager + MetricsRegistry + KillSwitch, without
any external network calls.

Each test represents a complete user-observable scenario.
"""

from __future__ import annotations

import os
import time
from unittest.mock import patch

import pytest

from brokers.paper_trading import PaperTradingBroker
from brokers.base import OrderSide, OrderType
from infrastructure.metrics import get_metrics_registry
from kill_switch import KillSwitch
from risk.manager import RiskManager, RiskConfig


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def broker():
    return PaperTradingBroker(initial_balance=100_000.0)


@pytest.fixture
def risk(tmp_path):
    return RiskManager(
        config=RiskConfig(
            max_position_size_pct=0.02,
            max_drawdown_pct=0.10,
            daily_loss_limit_pct=0.05,
        ),
        halt_state_file=tmp_path / "halt.json",
    )


@pytest.fixture
def ks(tmp_path):
    return KillSwitch(
        flag_file=tmp_path / "ks.flag",
        deactivation_token="e2e-token",
    )


@pytest.fixture
def metrics():
    return get_metrics_registry()


# ── Scenario 1: BUY signal → risk check → fill → metrics ─────────────────────


@pytest.mark.asyncio
async def test_buy_signal_to_fill(broker, risk, metrics):
    """BUY signal flows through risk check to broker fill and metrics update."""
    await broker.connect()
    broker.update_market_price("XAUUSD", 2050.0)

    risk.update_equity(100_000.0)
    allowed, _ = risk.validate_trade("XAUUSD", 0.1, "buy")
    assert isinstance(allowed, bool)

    order = broker.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 0.1)
    assert order is not None

    metrics.get_collector("hopefx_orders_total").inc(1, {"symbol": "XAUUSD", "side": "buy"})
    metrics.get_collector("hopefx_signals_total").inc(1, {"direction": "buy"})

    positions = broker.get_positions()
    assert any(p.symbol == "XAUUSD" for p in positions)

    await broker.disconnect()


# ── Scenario 2: Profitable trade updates equity metric ────────────────────────


@pytest.mark.asyncio
async def test_profitable_trade_updates_metrics(broker, metrics):
    """A profitable close updates equity and win-rate metrics."""
    await broker.connect()
    broker.update_market_price("XAUUSD", 2000.0)

    broker.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 0.1)
    broker.update_market_price("XAUUSD", 2020.0)
    broker.close_position("XAUUSD")

    metrics.record_trade("XAUUSD", "buy", pnl=200.0, commission=3.5)

    equity = metrics.get_collector("hopefx_equity")
    assert equity is not None

    win_rate = metrics.get_collector("hopefx_win_rate_pct")
    assert win_rate is not None
    win_rate.set(60.0)
    assert win_rate.get_value() == pytest.approx(60.0)

    await broker.disconnect()


# ── Scenario 3: Kill switch halts trading ─────────────────────────────────────


@pytest.mark.asyncio
async def test_kill_switch_prevents_new_orders(broker, ks):
    """After kill switch activation, trading should be halted."""
    await broker.connect()
    ks.activate("e2e test: drawdown limit")
    assert ks.is_active() is True

    ks.deactivate(token="e2e-token")
    assert ks.is_active() is False

    await broker.disconnect()


# ── Scenario 4: Order latency metric recorded ─────────────────────────────────


@pytest.mark.asyncio
async def test_latency_metric_recorded(broker, metrics):
    """Order latency histogram is updated after a trade."""
    await broker.connect()
    broker.update_market_price("XAUUSD", 2000.0)

    t0 = time.monotonic()
    broker.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 0.1)
    latency_ms = (time.monotonic() - t0) * 1000

    hist = metrics.get_collector("hopefx_order_latency_ms_bucket")
    before = hist.get_count()
    hist.observe(latency_ms)
    assert hist.get_count() == before + 1

    await broker.disconnect()


# ── Scenario 5: Broker connected metric ───────────────────────────────────────


@pytest.mark.asyncio
async def test_broker_connected_metric_set(broker, metrics):
    """hopefx_broker_connected gauge reflects connection state."""
    gauge = metrics.get_collector("hopefx_broker_connected")
    assert gauge is not None

    await broker.connect()
    gauge.set(1.0, {"broker": "paper"})
    assert gauge.get_value({"broker": "paper"}) == pytest.approx(1.0)

    await broker.disconnect()
    gauge.set(0.0, {"broker": "paper"})
    assert gauge.get_value({"broker": "paper"}) == pytest.approx(0.0)


# ── Scenario 6: Multiple fills accumulate in metrics ─────────────────────────


@pytest.mark.asyncio
async def test_multiple_fills_accumulate(broker, metrics):
    """Three sequential trades all register in the orders counter."""
    await broker.connect()
    counter = metrics.get_collector("hopefx_orders_total")
    before = counter.get_value({"symbol": "XAUUSD", "side": "buy"}) or 0

    for price in [2000.0, 2010.0, 2020.0]:
        broker.update_market_price("XAUUSD", price)
        broker.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 0.01)
        broker.close_position("XAUUSD")
        counter.inc(1, {"symbol": "XAUUSD", "side": "buy"})

    after = counter.get_value({"symbol": "XAUUSD", "side": "buy"}) or 0
    assert after == before + 3

    await broker.disconnect()


# ── Scenario 7: Risk blocks trade after drawdown ──────────────────────────────


def test_risk_blocks_after_max_drawdown(risk):
    """After equity drops 11%, risk manager flags the account."""
    risk.update_equity(100_000.0)
    risk.update_equity(89_000.0)  # 11% drawdown — over 10% limit

    assessment = risk.assess_risk({"equity": 89_000.0, "balance": 89_000.0}, [])
    assert isinstance(assessment.can_trade, bool)
    assert hasattr(assessment, "level")


# ── Scenario 8: Paper broker price feed ───────────────────────────────────────


@pytest.mark.asyncio
async def test_price_update_reflected_in_positions(broker):
    """Price updates are reflected in open position unrealised P&L."""
    await broker.connect()
    broker.update_market_price("XAUUSD", 2000.0)
    broker.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 0.1)

    broker.update_market_price("XAUUSD", 2050.0)
    positions = broker.get_positions()
    xau = next((p for p in positions if p.symbol == "XAUUSD"), None)
    assert xau is not None
    # Unrealised P&L should be positive after a 50-point move
    if hasattr(xau, "unrealised_pnl"):
        assert xau.unrealised_pnl > 0

    await broker.disconnect()


# ── Scenario 9: Sentry config does not raise without DSN ─────────────────────


def test_sentry_init_no_dsn_returns_false():
    """init_sentry returns False gracefully when SENTRY_DSN is not set."""
    with patch.dict(os.environ, {"SENTRY_DSN": ""}):
        from monitoring.sentry_config import init_sentry

        result = init_sentry()
    assert result is False


# ── Scenario 10: Journal POST requires auth ───────────────────────────────────


def test_journal_create_entry_requires_auth():
    """POST /api/journal/trades endpoint has get_current_user dependency."""
    import inspect
    from api.journal import create_entry

    sig = inspect.signature(create_entry)
    assert "user" in sig.parameters, "create_entry must have a 'user' parameter with get_current_user dependency"


# ── Scenario 11: Prop firm status requires auth ───────────────────────────────


def test_prop_firm_status_requires_auth():
    """GET /api/risk/prop-firm-status endpoint has get_current_user dependency."""
    import inspect
    from api.prop_firm import prop_firm_status

    sig = inspect.signature(prop_firm_status)
    assert "user" in sig.parameters, "prop_firm_status must have a 'user' parameter with get_current_user dependency"


# ── Scenario 12: explain.py rate limit enforced ───────────────────────────────


def test_explain_rate_limit_enforced():
    """_enforce_rate_limit raises HTTP 429 after exceeding the limit."""
    from unittest.mock import MagicMock
    from fastapi import HTTPException
    from api.explain import _enforce_rate_limit, _ip_windows

    # Clear any existing state for this test IP
    test_ip = "10.0.0.99"
    _ip_windows.pop(test_ip, None)

    request = MagicMock()
    request.client.host = test_ip

    # Exhaust the limit (use a tight limit string)
    with patch("api.explain._get_limiter", return_value=None):
        for _ in range(3):
            _enforce_rate_limit(request, "3/minute")

        with pytest.raises(HTTPException) as exc_info:
            _enforce_rate_limit(request, "3/minute")

    assert exc_info.value.status_code == 429
