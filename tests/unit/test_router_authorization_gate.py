# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Integration test: the SmartRouter refuses to route an order that lacks a
risk-approval token / decision id in ENFORCE mode, and is behaviour-neutral in
the default MONITOR mode. Completes the No Unauthorized Trade guarantee across
the smart-router broker path (alongside the OMS path).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.unit


def _router_with_broker():
    from execution.smart_router import BrokerState, SmartRouter

    r = SmartRouter()
    broker = MagicMock()
    broker.place_order = AsyncMock(return_value={"status": "filled", "fill_price": 2350.0, "quantity": 0.01})
    r.add_broker("b1", broker)
    r._states["b1"] = BrokerState(broker_id="b1", ema_latency_ms=10.0, fill_rate=0.99)
    return r


def _order(**kw):
    base = {
        "symbol": "XAUUSD",
        "direction": "long",
        "quantity": 0.01,
        "order_type": "MARKET",
        "mid_price": 2350.0,
        "bid": 2349.0,
        "ask": 2351.0,
        "spread": 2.0,
        "confidence": 0.8,
        "sentiment": 0.0,
        "impact": 0.0,
        "features": {},
    }
    base.update(kw)
    return base


@pytest.mark.asyncio
async def test_monitor_mode_allows_unauthorized_route(monkeypatch):
    monkeypatch.setenv("HOPEFX_INVARIANT_MODE", "monitor")
    r = _router_with_broker()
    result = await r.route_and_execute(_order())  # no token — monitor allows
    assert result["status"] == "filled"


@pytest.mark.asyncio
async def test_enforce_mode_blocks_unauthorized_route(monkeypatch):
    monkeypatch.setenv("HOPEFX_INVARIANT_MODE", "enforce")
    r = _router_with_broker()
    result = await r.route_and_execute(_order())  # no token — enforce refuses
    assert result["status"] == "rejected"
    assert "unauthorized" in result["reason"]


@pytest.mark.asyncio
async def test_enforce_mode_allows_authorized_route(monkeypatch):
    monkeypatch.setenv("HOPEFX_INVARIANT_MODE", "enforce")
    r = _router_with_broker()
    result = await r.route_and_execute(_order(risk_approval_token="rat-1", decision_id="dec-1"))
    assert result["status"] == "filled"
