# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Integration test: the OMS refuses to submit an order that lacks a risk-approval
token / decision id when invariant enforcement is in ENFORCE mode — and is
behaviour-neutral in the default MONITOR mode.

This proves the constitutional guarantee "No order reaches a broker without
passing the risk gate" is wired at the OMS choke point.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

pytestmark = pytest.mark.unit


def _oms():
    from execution.oms import OrderLifecycleManager

    return OrderLifecycleManager()


def _new_order(oms, **kw):
    return oms.create_order(symbol="XAUUSD", side="BUY", order_type="MARKET", quantity=Decimal("1"), **kw)


@pytest.mark.asyncio
async def test_monitor_mode_allows_unauthorized_order(monkeypatch):
    # Default/monitor mode must not change OMS behaviour — an order without a
    # token still submits (the violation is only logged).
    monkeypatch.setenv("HOPEFX_INVARIANT_MODE", "monitor")
    oms = _oms()
    o = _new_order(oms)
    assert oms.submit_order(o.id) is True


@pytest.mark.asyncio
async def test_enforce_mode_blocks_order_without_token(monkeypatch):
    monkeypatch.setenv("HOPEFX_INVARIANT_MODE", "enforce")
    oms = _oms()
    o = _new_order(oms)  # no risk_approval_token / decision_id
    assert oms.submit_order(o.id) is False


@pytest.mark.asyncio
async def test_enforce_mode_allows_authorized_order(monkeypatch):
    monkeypatch.setenv("HOPEFX_INVARIANT_MODE", "enforce")
    oms = _oms()
    o = _new_order(oms, risk_approval_token="rat-abc123", decision_id="dec-1")
    assert oms.submit_order(o.id) is True
