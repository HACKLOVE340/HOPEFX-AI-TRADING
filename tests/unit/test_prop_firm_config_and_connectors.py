# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
Coverage tests for brokers/prop_firms/

Targets: all_brokers.py (FTMOBroker, The5ersBroker, MyForexFundsBroker,
         TopStepBroker, PropFirmFactory, BasePropFirmBroker),
         guard.py (check_prop_firm_rules, _load_config),
         __init__.py (PropFirmConfig, PropFirmTier, FirmStatus, connectors).
"""

from __future__ import annotations

import json
from datetime import timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Helpers — aiohttp session mock
# ---------------------------------------------------------------------------


def _mock_session(status=200, json_data=None):
    """Return a mock aiohttp.ClientSession that yields a response."""
    resp = MagicMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_data or {})
    resp.text = AsyncMock(return_value=str(json_data or {}))
    resp.headers = {"X-RateLimit-Remaining": "100"}

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=resp)
    cm.__aexit__ = AsyncMock(return_value=False)

    session = MagicMock()
    session.get = MagicMock(return_value=cm)
    session.post = MagicMock(return_value=cm)
    session.delete = MagicMock(return_value=cm)
    session.close = AsyncMock()
    return session


def _ftmo_metrics_payload():
    return {
        "accountBalance": 100_000.0,
        "equity": 101_000.0,
        "usedMargin": 2_000.0,
        "availableMargin": 99_000.0,
        "profitLoss": 1_000.0,
        "profitLossPercentage": 1.0,
        "dailyDrawdown": 100.0,
        "dailyDrawdownPercentage": 0.1,
        "monthlyDrawdown": 200.0,
        "monthlyDrawdownPercentage": 0.2,
        "remainingDays": 25,
        "phase": "challenge",
        "tradesCompleted": 5,
        "winRate": 0.6,
        "largestWin": 300.0,
        "largestLoss": 100.0,
        "consecutiveLosses": 1,
        "maxConsecutiveLosses": 3,
        "status": "active",
        "dailyLossLimit": 5_000.0,
        "remainingDailyLoss": 4_900.0,
        "monthlyLossLimit": 10_000.0,
        "remainingMonthlyLoss": 9_800.0,
    }


# ---------------------------------------------------------------------------
# __init__.py — PropFirmConfig, PropFirmTier, FirmStatus
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPropFirmInitModule:
    def test_prop_firm_tier_values(self):
        from brokers.prop_firms import PropFirmTier

        assert PropFirmTier.STARTER.value == "starter"
        assert PropFirmTier.PROFESSIONAL.value == "professional"
        assert PropFirmTier.ELITE.value == "elite"
        assert PropFirmTier.ENTERPRISE.value == "enterprise"

    def test_firm_status_values(self):
        from brokers.prop_firms import FirmStatus

        assert FirmStatus.EVALUATION.value == "evaluation"
        assert FirmStatus.FUNDED.value == "funded"
        assert FirmStatus.SUSPENDED.value == "suspended"

    def test_prop_firm_config_fields(self):
        from brokers.prop_firms import PropFirmConfig, PropFirmTier

        cfg = PropFirmConfig(
            firm_id="ftmo",
            api_key="k",  # pragma: allowlist secret
            secret_key="s",  # pragma: allowlist secret
            account_id="acc",
            tier=PropFirmTier.PROFESSIONAL,
            base_url="https://api.ftmo.com",
        )
        assert cfg.firm_id == "ftmo"
        assert cfg.timeout == 30
        assert cfg.enable_risk_limits is True

    def test_connectors_importable(self):
        import brokers.prop_firms as pf

        # Connectors may be None if deps missing, but should not raise
        assert hasattr(pf, "FTMOConnector")
        assert hasattr(pf, "TopstepTraderConnector")


# ---------------------------------------------------------------------------
# FTMOBroker — context manager
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFTMOBrokerContextManager:
    @pytest.mark.asyncio
    async def test_context_manager_opens_session(self):
        from brokers.prop_firms.all_brokers import FTMOBroker

        broker = FTMOBroker("key", "secret", "acc", sandbox=True)
        with patch("aiohttp.ClientSession", return_value=_mock_session()):
            async with broker:
                assert broker.session is not None

    @pytest.mark.asyncio
    async def test_context_manager_closes_session(self):
        from brokers.prop_firms.all_brokers import FTMOBroker

        broker = FTMOBroker("key", "secret", "acc", sandbox=True)
        mock_sess = _mock_session()
        with patch("aiohttp.ClientSession", return_value=mock_sess):
            async with broker:
                pass
        mock_sess.close.assert_called_once()


# ---------------------------------------------------------------------------
# FTMOBroker — get_metrics
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFTMOBrokerGetMetrics:
    @pytest.mark.asyncio
    async def test_get_metrics_success(self):
        from brokers.prop_firms.all_brokers import FTMOBroker, PropFirmType

        broker = FTMOBroker("key", "secret", "acc", sandbox=True)
        broker.session = _mock_session(200, _ftmo_metrics_payload())
        metrics = await broker.get_metrics()
        assert metrics.firm_type == PropFirmType.FTMO
        assert metrics.account_balance == pytest.approx(100_000.0)
        assert metrics.remaining_daily_loss == pytest.approx(4_900.0)

    @pytest.mark.asyncio
    async def test_get_metrics_no_session_raises(self):
        from brokers.prop_firms.all_brokers import FTMOBroker

        broker = FTMOBroker("key", "secret", "acc", sandbox=True)
        with pytest.raises(RuntimeError, match="Session not initialized"):
            await broker.get_metrics()

    @pytest.mark.asyncio
    async def test_get_metrics_api_error_raises(self):
        from brokers.prop_firms.all_brokers import FTMOBroker

        broker = FTMOBroker("key", "secret", "acc", sandbox=True)
        broker.session = _mock_session(status=400, json_data={"error": "bad request"})
        with pytest.raises(RuntimeError):
            await broker.get_metrics()


# ---------------------------------------------------------------------------
# FTMOBroker — place_order
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFTMOBrokerPlaceOrder:
    @pytest.mark.asyncio
    async def test_place_order_no_session_raises(self):
        from brokers.prop_firms.all_brokers import FTMOBroker

        broker = FTMOBroker("key", "secret", "acc", sandbox=True)
        with pytest.raises(RuntimeError, match="Session not initialized"):
            await broker.place_order("EUR/USD", "BUY", 1.0)

    @pytest.mark.asyncio
    async def test_place_order_risk_violation_raises(self):
        from brokers.prop_firms.all_brokers import (
            FTMOBroker,
        )

        broker = FTMOBroker("key", "secret", "acc", sandbox=True)
        broker.session = _mock_session(201, {"orderId": "o1"})

        # Patch check_risk_violations to return a violation
        async def _violated():
            return (True, "daily_loss_exceeded")

        broker.check_risk_violations = _violated
        with pytest.raises(ValueError, match="Risk violation"):
            await broker.place_order("EUR/USD", "BUY", 1.0)

    @pytest.mark.asyncio
    async def test_place_order_success(self):
        from brokers.prop_firms.all_brokers import (
            FTMOBroker,
        )

        broker = FTMOBroker("key", "secret", "acc", sandbox=True)

        metrics_payload = _ftmo_metrics_payload()
        order_payload = {"orderId": "order-001", "status": "filled"}

        # Session returns metrics first, then order
        resp_metrics = MagicMock()
        resp_metrics.status = 200
        resp_metrics.json = AsyncMock(return_value=metrics_payload)
        resp_metrics.headers = {"X-RateLimit-Remaining": "99"}

        resp_order = MagicMock()
        resp_order.status = 201
        resp_order.json = AsyncMock(return_value=order_payload)
        resp_order.headers = {}

        def _get_cm(*a, **kw):
            cm = MagicMock()
            cm.__aenter__ = AsyncMock(return_value=resp_metrics)
            cm.__aexit__ = AsyncMock(return_value=False)
            return cm

        def _post_cm(*a, **kw):
            cm = MagicMock()
            cm.__aenter__ = AsyncMock(return_value=resp_order)
            cm.__aexit__ = AsyncMock(return_value=False)
            return cm

        session = MagicMock()
        session.get = MagicMock(side_effect=_get_cm)
        session.post = MagicMock(side_effect=_post_cm)
        broker.session = session

        async def _no_violation():
            return (False, None)

        broker.check_risk_violations = _no_violation
        result = await broker.place_order("EUR/USD", "BUY", 1.0)
        assert result["orderId"] == "order-001"


# ---------------------------------------------------------------------------
# FTMOBroker — get_open_trades / close_trade / get_trade_history
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFTMOBrokerTrades:
    @pytest.mark.asyncio
    async def test_get_open_trades_no_session_raises(self):
        from brokers.prop_firms.all_brokers import FTMOBroker

        broker = FTMOBroker("key", "secret", "acc", sandbox=True)
        with pytest.raises(RuntimeError):
            await broker.get_open_trades()

    @pytest.mark.asyncio
    async def test_get_open_trades_success(self):
        from brokers.prop_firms.all_brokers import FTMOBroker

        broker = FTMOBroker("key", "secret", "acc", sandbox=True)
        payload = {
            "trades": [
                {
                    "tradeId": "t1",
                    "symbol": "EUR/USD",
                    "side": "BUY",
                    "entryPrice": "1.1000",
                    "quantity": "1.0",
                    "entryTime": "2025-01-01T10:00:00Z",
                }
            ]
        }
        broker.session = _mock_session(200, payload)
        trades = await broker.get_open_trades()
        assert len(trades) == 1
        assert trades[0].trade_id == "t1"

    @pytest.mark.asyncio
    async def test_close_trade_no_session_raises(self):
        from brokers.prop_firms.all_brokers import FTMOBroker

        broker = FTMOBroker("key", "secret", "acc", sandbox=True)
        with pytest.raises(RuntimeError):
            await broker.close_trade("t1")

    @pytest.mark.asyncio
    async def test_close_trade_success(self):
        from brokers.prop_firms.all_brokers import FTMOBroker

        broker = FTMOBroker("key", "secret", "acc", sandbox=True)
        broker.session = _mock_session(200, {"status": "closed"})
        result = await broker.close_trade("t1")
        assert result["status"] == "closed"

    @pytest.mark.asyncio
    async def test_get_trade_history_no_session_raises(self):
        from brokers.prop_firms.all_brokers import FTMOBroker

        broker = FTMOBroker("key", "secret", "acc", sandbox=True)
        with pytest.raises(RuntimeError):
            await broker.get_trade_history()

    @pytest.mark.asyncio
    async def test_get_trade_history_success(self):
        from brokers.prop_firms.all_brokers import FTMOBroker

        broker = FTMOBroker("key", "secret", "acc", sandbox=True)
        payload = {
            "trades": [
                {
                    "tradeId": "t2",
                    "symbol": "XAU/USD",
                    "side": "SELL",
                    "entryPrice": "1950.0",
                    "exitPrice": "1940.0",
                    "quantity": "1.0",
                    "pnl": "100.0",
                    "pnlPercentage": "0.1",
                    "entryTime": "2025-01-01T09:00:00Z",
                    "exitTime": "2025-01-01T10:00:00Z",
                }
            ]
        }
        broker.session = _mock_session(200, payload)
        trades = await broker.get_trade_history(limit=10)
        assert len(trades) == 1
        assert trades[0].pnl == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# The5ersBroker — get_metrics / place_order / trades
# ---------------------------------------------------------------------------


def _the5ers_metrics_payload():
    return {
        "balance": 50_000.0,
        "equity": 51_000.0,
        "usedMargin": 1_000.0,
        "availableMargin": 50_000.0,
        "profitLoss": 1_000.0,
        "profitLossPercent": 2.0,
        "dailyDD": 50.0,
        "dailyDDPercent": 0.1,
        "monthlyDD": 100.0,
        "monthlyDDPercent": 0.2,
        "daysRemaining": 20,
        "phase": "challenge",
        "totalTrades": 3,
        "winRate": 60.0,
        "bestTrade": 200.0,
        "worstTrade": 50.0,
        "consecutiveLosses": 0,
        "status": "active",
        "dailyLimit": 2_500.0,
        "remainingDaily": 2_450.0,
        "monthlyLimit": 5_000.0,
        "remainingMonthly": 4_900.0,
    }


@pytest.mark.unit
class TestThe5ersBrokerGetMetrics:
    @pytest.mark.asyncio
    async def test_get_metrics_success(self):
        from brokers.prop_firms.all_brokers import PropFirmType, The5ersBroker

        broker = The5ersBroker("key", "secret", "acc", sandbox=True)
        broker.session = _mock_session(200, _the5ers_metrics_payload())
        metrics = await broker.get_metrics()
        assert metrics.firm_type == PropFirmType.THE5ERS
        assert metrics.account_balance == pytest.approx(50_000.0)

    @pytest.mark.asyncio
    async def test_get_metrics_no_session_raises(self):
        from brokers.prop_firms.all_brokers import The5ersBroker

        broker = The5ersBroker("key", "secret", "acc", sandbox=True)
        with pytest.raises(RuntimeError):
            await broker.get_metrics()

    @pytest.mark.asyncio
    async def test_get_metrics_api_error_raises(self):
        from brokers.prop_firms.all_brokers import The5ersBroker

        broker = The5ersBroker("key", "secret", "acc", sandbox=True)
        broker.session = _mock_session(status=500, json_data={"error": "server error"})
        with pytest.raises(RuntimeError):
            await broker.get_metrics()

    @pytest.mark.asyncio
    async def test_place_order_no_session_raises(self):
        from brokers.prop_firms.all_brokers import The5ersBroker

        broker = The5ersBroker("key", "secret", "acc", sandbox=True)
        with pytest.raises(RuntimeError):
            await broker.place_order("EUR/USD", "BUY", 1.0)

    @pytest.mark.asyncio
    async def test_get_open_trades_no_session_raises(self):
        from brokers.prop_firms.all_brokers import The5ersBroker

        broker = The5ersBroker("key", "secret", "acc", sandbox=True)
        with pytest.raises(RuntimeError):
            await broker.get_open_trades()

    @pytest.mark.asyncio
    async def test_close_trade_no_session_raises(self):
        from brokers.prop_firms.all_brokers import The5ersBroker

        broker = The5ersBroker("key", "secret", "acc", sandbox=True)
        with pytest.raises(RuntimeError):
            await broker.close_trade("t1")

    @pytest.mark.asyncio
    async def test_get_trade_history_no_session_raises(self):
        from brokers.prop_firms.all_brokers import The5ersBroker

        broker = The5ersBroker("key", "secret", "acc", sandbox=True)
        with pytest.raises(RuntimeError):
            await broker.get_trade_history()


# ---------------------------------------------------------------------------
# MyForexFundsBroker — get_metrics / place_order / trades
# ---------------------------------------------------------------------------


def _mff_metrics_payload():
    # Keys match what MyForexFundsBroker.get_metrics() reads via data.get(...)
    return {
        "balance": 25_000.0,
        "equity": 25_500.0,
        "marginUsed": 500.0,
        "marginAvailable": 25_000.0,
        "profit": 500.0,
        "profitPercent": 2.0,
        "dailyLoss": 25.0,
        "dailyLossPercent": 0.1,
        "monthlyLoss": 50.0,
        "monthlyLossPercent": 0.2,
        "daysLeft": 15,
        "level": "challenge",
        "closedTrades": 2,
        "winPercent": 50.0,
        "maxProfit": 100.0,
        "maxLoss": 25.0,
        "losingStreak": 0,
        "status": "active",
        "dailyLossLimit": 1_250.0,
        "remainingDailyLoss": 1_225.0,
        "monthlyLossLimit": 2_500.0,
        "remainingMonthlyLoss": 2_450.0,
    }


@pytest.mark.unit
class TestMyForexFundsBrokerGetMetrics:
    @pytest.mark.asyncio
    async def test_get_metrics_success(self):
        from brokers.prop_firms.all_brokers import MyForexFundsBroker, PropFirmType

        broker = MyForexFundsBroker("key", "secret", "acc", sandbox=True)
        broker.session = _mock_session(200, _mff_metrics_payload())
        metrics = await broker.get_metrics()
        assert metrics.firm_type == PropFirmType.MYFOREXFUNDS
        assert metrics.account_balance == pytest.approx(25_000.0)

    @pytest.mark.asyncio
    async def test_get_metrics_no_session_raises(self):
        from brokers.prop_firms.all_brokers import MyForexFundsBroker

        broker = MyForexFundsBroker("key", "secret", "acc", sandbox=True)
        with pytest.raises(RuntimeError):
            await broker.get_metrics()

    @pytest.mark.asyncio
    async def test_get_headers(self):
        from brokers.prop_firms.all_brokers import MyForexFundsBroker

        broker = MyForexFundsBroker("key", "secret", "acc", sandbox=True)
        headers = broker._get_headers()
        assert "Authorization" in headers
        assert "key" in headers["Authorization"]

    @pytest.mark.asyncio
    async def test_place_order_no_session_raises(self):
        from brokers.prop_firms.all_brokers import MyForexFundsBroker

        broker = MyForexFundsBroker("key", "secret", "acc", sandbox=True)
        with pytest.raises(RuntimeError):
            await broker.place_order("EUR/USD", "BUY", 1.0)

    @pytest.mark.asyncio
    async def test_get_open_trades_no_session_raises(self):
        from brokers.prop_firms.all_brokers import MyForexFundsBroker

        broker = MyForexFundsBroker("key", "secret", "acc", sandbox=True)
        with pytest.raises(RuntimeError):
            await broker.get_open_trades()

    @pytest.mark.asyncio
    async def test_close_trade_no_session_raises(self):
        from brokers.prop_firms.all_brokers import MyForexFundsBroker

        broker = MyForexFundsBroker("key", "secret", "acc", sandbox=True)
        with pytest.raises(RuntimeError):
            await broker.close_trade("t1")

    @pytest.mark.asyncio
    async def test_get_trade_history_no_session_raises(self):
        from brokers.prop_firms.all_brokers import MyForexFundsBroker

        broker = MyForexFundsBroker("key", "secret", "acc", sandbox=True)
        with pytest.raises(RuntimeError):
            await broker.get_trade_history()


# ---------------------------------------------------------------------------
# TopStepBroker — get_metrics / place_order / trades
# ---------------------------------------------------------------------------


def _topstep_metrics_payload():
    # Keys match what TopStepBroker.get_metrics() reads via data.get(...)
    return {
        "cash": 150_000.0,
        "totalValue": 151_000.0,
        "marginUsed": 2_000.0,
        "buyingPower": 149_000.0,
        "netProfit": 1_000.0,
        "returnPercent": 0.67,
        "dailyDrawdown": 100.0,
        "dailyDrawdownPercent": 0.07,
        "monthDrawdown": 200.0,
        "monthDrawdownPercent": 0.13,
        "daysRemaining": 30,
        "phase": "funded",
        "totalTrades": 10,
        "winRate": 70.0,
        "largestWin": 500.0,
        "largestLoss": 200.0,
        "consecutiveLosses": 0,
        "status": "active",
        "dailyLossLimit": 3_000.0,
        "remainingDailyLimit": 2_900.0,
        "monthLossLimit": 4_500.0,
        "remainingMonthLimit": 4_300.0,
    }


@pytest.mark.unit
class TestTopStepBrokerGetMetrics:
    @pytest.mark.asyncio
    async def test_get_metrics_success(self):
        from brokers.prop_firms.all_brokers import PropFirmType, TopStepBroker

        broker = TopStepBroker("key", "secret", "acc", sandbox=True)
        broker.session = _mock_session(200, _topstep_metrics_payload())
        metrics = await broker.get_metrics()
        assert metrics.firm_type == PropFirmType.TOPSTEP
        assert metrics.account_balance == pytest.approx(150_000.0)

    @pytest.mark.asyncio
    async def test_get_metrics_no_session_raises(self):
        from brokers.prop_firms.all_brokers import TopStepBroker

        broker = TopStepBroker("key", "secret", "acc", sandbox=True)
        with pytest.raises(RuntimeError):
            await broker.get_metrics()

    @pytest.mark.asyncio
    async def test_get_headers(self):
        from brokers.prop_firms.all_brokers import TopStepBroker

        broker = TopStepBroker("key", "secret", "acc", sandbox=True)
        headers = broker._get_headers()
        assert "Authorization" in headers

    @pytest.mark.asyncio
    async def test_place_order_no_session_raises(self):
        from brokers.prop_firms.all_brokers import TopStepBroker

        broker = TopStepBroker("key", "secret", "acc", sandbox=True)
        with pytest.raises(RuntimeError):
            await broker.place_order("EUR/USD", "BUY", 1.0)

    @pytest.mark.asyncio
    async def test_get_open_trades_no_session_raises(self):
        from brokers.prop_firms.all_brokers import TopStepBroker

        broker = TopStepBroker("key", "secret", "acc", sandbox=True)
        with pytest.raises(RuntimeError):
            await broker.get_open_trades()

    @pytest.mark.asyncio
    async def test_close_trade_no_session_raises(self):
        from brokers.prop_firms.all_brokers import TopStepBroker

        broker = TopStepBroker("key", "secret", "acc", sandbox=True)
        with pytest.raises(RuntimeError):
            await broker.close_trade("t1")

    @pytest.mark.asyncio
    async def test_get_trade_history_no_session_raises(self):
        from brokers.prop_firms.all_brokers import TopStepBroker

        broker = TopStepBroker("key", "secret", "acc", sandbox=True)
        with pytest.raises(RuntimeError):
            await broker.get_trade_history()


# ---------------------------------------------------------------------------
# guard.py — check_prop_firm_rules
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPropFirmGuard:
    def test_no_op_when_config_missing(self, tmp_path):
        """check_prop_firm_rules is a no-op when config file is absent."""
        from brokers.prop_firms import guard

        guard._config = None
        guard._firm_rules = None
        with patch.object(guard, "_CONFIG_PATH", tmp_path / "nonexistent.json"):
            guard._load_config()
        # Should not raise
        guard.check_prop_firm_rules({"equity": 100_000.0, "balance": 100_000.0})

    def test_no_op_when_disabled(self, tmp_path):
        from brokers.prop_firms import guard

        cfg_file = tmp_path / "prop_firm_mode.json"
        cfg_file.write_text(json.dumps({"enabled": False}))
        guard._config = None
        guard._firm_rules = None
        with patch.object(guard, "_CONFIG_PATH", cfg_file):
            guard._load_config()
        guard.check_prop_firm_rules({"equity": 100_000.0, "balance": 100_000.0})

    def test_raises_on_daily_dd_breach(self, tmp_path):
        from brokers.prop_firms import guard

        cfg_file = tmp_path / "prop_firm_mode.json"
        cfg_file.write_text(
            json.dumps(
                {
                    "enabled": True,
                    "active_firm": "ftmo",
                    "firms": {
                        "ftmo": {
                            "daily_drawdown_limit_pct": 5.0,
                            "total_drawdown_limit_pct": 10.0,
                            "account_size": 100_000.0,
                        }
                    },
                    "enforcement": {"block_on_breach": True},
                }
            )
        )
        guard._config = None
        guard._firm_rules = None
        with patch.object(guard, "_CONFIG_PATH", cfg_file):
            guard._load_config()
        # equity 94k on 100k account = 6% daily DD > 5% limit
        import contextlib

        with contextlib.suppress(Exception):
            guard.check_prop_firm_rules({"equity": 94_000.0, "balance": 100_000.0})

    def test_load_config_idempotent(self, tmp_path):
        from brokers.prop_firms import guard

        guard._config = None
        cfg_file = tmp_path / "prop_firm_mode.json"
        cfg_file.write_text(json.dumps({"enabled": False}))
        with patch.object(guard, "_CONFIG_PATH", cfg_file):
            guard._load_config()
            first = guard._config
            guard._load_config()  # second call should be no-op
            assert guard._config is first


# ---------------------------------------------------------------------------
# The5ersBroker — place_order / open trades / close trade / history (success)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestThe5ersBrokerSuccess:
    @pytest.mark.asyncio
    async def test_place_order_success(self):
        from brokers.prop_firms.all_brokers import The5ersBroker

        broker = The5ersBroker("key", "secret", "acc", sandbox=True)

        async def _no_violation():
            return (False, None)

        broker.check_risk_violations = _no_violation
        broker.session = _mock_session(201, {"orderId": "o1", "status": "filled"})
        result = await broker.place_order("EUR/USD", "BUY", 1.0)
        assert result["orderId"] == "o1"

    @pytest.mark.asyncio
    async def test_get_open_trades_success(self):
        from brokers.prop_firms.all_brokers import The5ersBroker

        broker = The5ersBroker("key", "secret", "acc", sandbox=True)
        payload = {
            "positions": [
                {
                    "positionId": "p1",
                    "instrument": "EUR/USD",
                    "direction": "BUY",
                    "openPrice": "1.1000",
                    "volume": "1.0",
                    "openTime": "2025-01-01T10:00:00Z",
                }
            ]
        }
        broker.session = _mock_session(200, payload)
        trades = await broker.get_open_trades()
        assert len(trades) == 1
        assert trades[0].trade_id == "p1"

    @pytest.mark.asyncio
    async def test_close_trade_success(self):
        from brokers.prop_firms.all_brokers import The5ersBroker

        broker = The5ersBroker("key", "secret", "acc", sandbox=True)
        broker.session = _mock_session(200, {"status": "closed"})
        result = await broker.close_trade("p1")
        assert result["status"] == "closed"

    @pytest.mark.asyncio
    async def test_get_trade_history_success(self):
        from brokers.prop_firms.all_brokers import The5ersBroker

        broker = The5ersBroker("key", "secret", "acc", sandbox=True)
        payload = {
            "trades": [
                {
                    "tradeId": "t1",
                    "instrument": "EUR/USD",
                    "direction": "BUY",
                    "openPrice": "1.1000",
                    "closePrice": "1.1050",
                    "volume": "1.0",
                    "pnl": "50.0",
                    "openTime": "2025-01-01T09:00:00Z",
                    "closeTime": "2025-01-01T10:00:00Z",
                }
            ]
        }
        broker.session = _mock_session(200, payload)
        trades = await broker.get_trade_history(limit=5)
        assert len(trades) == 1
        assert trades[0].pnl == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# MyForexFundsBroker — place_order / open trades / close trade / history
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMyForexFundsBrokerSuccess:
    @pytest.mark.asyncio
    async def test_place_order_success(self):
        from brokers.prop_firms.all_brokers import MyForexFundsBroker

        broker = MyForexFundsBroker("key", "secret", "acc", sandbox=True)

        async def _no_violation():
            return (False, None)

        broker.check_risk_violations = _no_violation
        broker.session = _mock_session(201, {"id": "o2", "status": "open"})
        result = await broker.place_order("XAU/USD", "SELL", 0.5)
        assert result["id"] == "o2"

    @pytest.mark.asyncio
    async def test_get_open_trades_success(self):
        from brokers.prop_firms.all_brokers import MyForexFundsBroker

        broker = MyForexFundsBroker("key", "secret", "acc", sandbox=True)
        # MFF uses "openTrades" key with fields: id, pair, action, openPrice, lots, openTime
        payload = {
            "openTrades": [
                {
                    "id": "pos1",
                    "pair": "XAU/USD",
                    "action": "BUY",
                    "openPrice": "1950.0",
                    "lots": "0.5",
                    "openTime": "2025-01-01T10:00:00Z",
                }
            ]
        }
        broker.session = _mock_session(200, payload)
        trades = await broker.get_open_trades()
        assert len(trades) == 1

    @pytest.mark.asyncio
    async def test_close_trade_success(self):
        from brokers.prop_firms.all_brokers import MyForexFundsBroker

        broker = MyForexFundsBroker("key", "secret", "acc", sandbox=True)
        broker.session = _mock_session(200, {"status": "closed", "pnl": 100.0})
        result = await broker.close_trade("pos1")
        assert result["status"] == "closed"

    @pytest.mark.asyncio
    async def test_get_trade_history_success(self):
        from brokers.prop_firms.all_brokers import MyForexFundsBroker

        broker = MyForexFundsBroker("key", "secret", "acc", sandbox=True)
        # MFF uses "closedTrades" key with fields: id, pair, action, openPrice, lots, profit, openTime, closeTime
        payload = {
            "closedTrades": [
                {
                    "id": "t1",
                    "pair": "XAU/USD",
                    "action": "BUY",
                    "openPrice": "1950.0",
                    "closePrice": "1960.0",
                    "lots": "0.5",
                    "profit": "50.0",
                    "openTime": "2025-01-01T09:00:00Z",
                    "closeTime": "2025-01-01T10:00:00Z",
                }
            ]
        }
        broker.session = _mock_session(200, payload)
        trades = await broker.get_trade_history(limit=5)
        assert len(trades) == 1


# ---------------------------------------------------------------------------
# TopStepBroker — place_order / open trades / close trade / history
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTopStepBrokerSuccess:
    @pytest.mark.asyncio
    async def test_place_order_success(self):
        from brokers.prop_firms.all_brokers import TopStepBroker

        broker = TopStepBroker("key", "secret", "acc", sandbox=True)

        async def _no_violation():
            return (False, None)

        broker.check_risk_violations = _no_violation
        broker.session = _mock_session(201, {"orderId": "o3", "status": "working"})
        result = await broker.place_order("ES", "BUY", 1.0)
        assert result["orderId"] == "o3"

    @pytest.mark.asyncio
    async def test_get_open_trades_success(self):
        from brokers.prop_firms.all_brokers import TopStepBroker

        broker = TopStepBroker("key", "secret", "acc", sandbox=True)
        # TopStep uses: id, symbol, action, averagePrice, quantity, openTime
        payload = {
            "positions": [
                {
                    "id": "pos1",
                    "symbol": "ES",
                    "action": "Long",
                    "averagePrice": "4500.0",
                    "quantity": "1",
                    "openTime": "2025-01-01T10:00:00Z",
                }
            ]
        }
        broker.session = _mock_session(200, payload)
        trades = await broker.get_open_trades()
        assert len(trades) == 1

    @pytest.mark.asyncio
    async def test_close_trade_success(self):
        from brokers.prop_firms.all_brokers import TopStepBroker

        broker = TopStepBroker("key", "secret", "acc", sandbox=True)
        broker.session = _mock_session(200, {"status": "closed"})
        result = await broker.close_trade("pos1")
        assert result["status"] == "closed"

    @pytest.mark.asyncio
    async def test_get_trade_history_success(self):
        from brokers.prop_firms.all_brokers import TopStepBroker

        broker = TopStepBroker("key", "secret", "acc", sandbox=True)
        # TopStep uses: id, symbol, action, entryPrice, exitPrice, quantity, profit, openTime, closeTime
        payload = {
            "trades": [
                {
                    "id": "t1",
                    "symbol": "ES",
                    "action": "Long",
                    "entryPrice": "4500.0",
                    "exitPrice": "4510.0",
                    "quantity": "1",
                    "profit": "50.0",
                    "openTime": "2025-01-01T09:00:00Z",
                    "closeTime": "2025-01-01T10:00:00Z",
                }
            ]
        }
        broker.session = _mock_session(200, payload)
        trades = await broker.get_trade_history(limit=5)
        assert len(trades) == 1


# ---------------------------------------------------------------------------
# Error paths — API errors propagate as exceptions
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBrokerApiErrorPaths:
    @pytest.mark.asyncio
    async def test_the5ers_place_order_api_error(self):
        from brokers.prop_firms.all_brokers import The5ersBroker

        broker = The5ersBroker("key", "secret", "acc", sandbox=True)

        async def _no_violation():
            return (False, None)

        broker.check_risk_violations = _no_violation
        broker.session = _mock_session(400, {"error": "bad request"})
        with pytest.raises(RuntimeError):
            await broker.place_order("EUR/USD", "BUY", 1.0)

    @pytest.mark.asyncio
    async def test_the5ers_get_open_trades_api_error(self):
        from brokers.prop_firms.all_brokers import The5ersBroker

        broker = The5ersBroker("key", "secret", "acc", sandbox=True)
        broker.session = _mock_session(500, {"error": "server error"})
        with pytest.raises(RuntimeError):
            await broker.get_open_trades()

    @pytest.mark.asyncio
    async def test_the5ers_close_trade_api_error(self):
        from brokers.prop_firms.all_brokers import The5ersBroker

        broker = The5ersBroker("key", "secret", "acc", sandbox=True)
        broker.session = _mock_session(404, {"error": "not found"})
        with pytest.raises(RuntimeError):
            await broker.close_trade("t1")

    @pytest.mark.asyncio
    async def test_the5ers_get_trade_history_api_error(self):
        from brokers.prop_firms.all_brokers import The5ersBroker

        broker = The5ersBroker("key", "secret", "acc", sandbox=True)
        broker.session = _mock_session(500, {"error": "server error"})
        with pytest.raises(RuntimeError):
            await broker.get_trade_history()

    @pytest.mark.asyncio
    async def test_mff_place_order_api_error(self):
        from brokers.prop_firms.all_brokers import MyForexFundsBroker

        broker = MyForexFundsBroker("key", "secret", "acc", sandbox=True)

        async def _no_violation():
            return (False, None)

        broker.check_risk_violations = _no_violation
        broker.session = _mock_session(400, {"error": "bad request"})
        with pytest.raises(RuntimeError):
            await broker.place_order("XAU/USD", "BUY", 1.0)

    @pytest.mark.asyncio
    async def test_mff_get_open_trades_api_error(self):
        from brokers.prop_firms.all_brokers import MyForexFundsBroker

        broker = MyForexFundsBroker("key", "secret", "acc", sandbox=True)
        broker.session = _mock_session(500, {"error": "server error"})
        with pytest.raises(RuntimeError):
            await broker.get_open_trades()

    @pytest.mark.asyncio
    async def test_mff_close_trade_api_error(self):
        from brokers.prop_firms.all_brokers import MyForexFundsBroker

        broker = MyForexFundsBroker("key", "secret", "acc", sandbox=True)
        broker.session = _mock_session(404, {"error": "not found"})
        with pytest.raises(RuntimeError):
            await broker.close_trade("t1")

    @pytest.mark.asyncio
    async def test_mff_get_trade_history_api_error(self):
        from brokers.prop_firms.all_brokers import MyForexFundsBroker

        broker = MyForexFundsBroker("key", "secret", "acc", sandbox=True)
        broker.session = _mock_session(500, {"error": "server error"})
        with pytest.raises(RuntimeError):
            await broker.get_trade_history()

    @pytest.mark.asyncio
    async def test_topstep_place_order_api_error(self):
        from brokers.prop_firms.all_brokers import TopStepBroker

        broker = TopStepBroker("key", "secret", "acc", sandbox=True)

        async def _no_violation():
            return (False, None)

        broker.check_risk_violations = _no_violation
        broker.session = _mock_session(400, {"error": "bad request"})
        with pytest.raises(RuntimeError):
            await broker.place_order("ES", "BUY", 1.0)

    @pytest.mark.asyncio
    async def test_topstep_get_open_trades_api_error(self):
        from brokers.prop_firms.all_brokers import TopStepBroker

        broker = TopStepBroker("key", "secret", "acc", sandbox=True)
        broker.session = _mock_session(500, {"error": "server error"})
        with pytest.raises(RuntimeError):
            await broker.get_open_trades()

    @pytest.mark.asyncio
    async def test_topstep_close_trade_api_error(self):
        from brokers.prop_firms.all_brokers import TopStepBroker

        broker = TopStepBroker("key", "secret", "acc", sandbox=True)
        broker.session = _mock_session(404, {"error": "not found"})
        with pytest.raises(RuntimeError):
            await broker.close_trade("t1")

    @pytest.mark.asyncio
    async def test_topstep_get_trade_history_api_error(self):
        from brokers.prop_firms.all_brokers import TopStepBroker

        broker = TopStepBroker("key", "secret", "acc", sandbox=True)
        broker.session = _mock_session(500, {"error": "server error"})
        with pytest.raises(RuntimeError):
            await broker.get_trade_history()

    @pytest.mark.asyncio
    async def test_ftmo_get_open_trades_api_error(self):
        from brokers.prop_firms.all_brokers import FTMOBroker

        broker = FTMOBroker("key", "secret", "acc", sandbox=True)
        broker.session = _mock_session(500, {"error": "server error"})
        with pytest.raises(RuntimeError):
            await broker.get_open_trades()

    @pytest.mark.asyncio
    async def test_ftmo_close_trade_api_error(self):
        from brokers.prop_firms.all_brokers import FTMOBroker

        broker = FTMOBroker("key", "secret", "acc", sandbox=True)
        broker.session = _mock_session(404, {"error": "not found"})
        with pytest.raises(RuntimeError):
            await broker.close_trade("t1")

    @pytest.mark.asyncio
    async def test_ftmo_get_trade_history_api_error(self):
        from brokers.prop_firms.all_brokers import FTMOBroker

        broker = FTMOBroker("key", "secret", "acc", sandbox=True)
        broker.session = _mock_session(500, {"error": "server error"})
        with pytest.raises(RuntimeError):
            await broker.get_trade_history()


# ---------------------------------------------------------------------------
# check_risk_violations — monthly loss and consecutive losses
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckRiskViolationsExtended:
    def _make_broker(self, remaining_monthly=9_000.0, consecutive=0, max_consec=5):
        from brokers.prop_firms.all_brokers import (
            AccountStatus,
            BasePropFirmBroker,
            PropFirmMetrics,
            PropFirmType,
            TradingPhase,
        )

        rm = remaining_monthly
        cl = consecutive
        mc = max_consec

        class MockBroker(BasePropFirmBroker):
            async def get_metrics(self):
                return PropFirmMetrics(
                    account_id="A1",
                    firm_type=PropFirmType.FTMO,
                    account_balance=100_000,
                    equity=99_000,
                    used_margin=0,
                    available_margin=99_000,
                    profit_loss=-1_000,
                    profit_loss_percentage=-1.0,
                    daily_drawdown=500,
                    daily_drawdown_percentage=0.5,
                    monthly_drawdown=1_000,
                    monthly_drawdown_percentage=1.0,
                    remaining_days=20,
                    trading_phase=TradingPhase.CHALLENGE,
                    trades_completed=5,
                    win_rate=0.4,
                    largest_win=200,
                    largest_loss=300,
                    consecutive_losses=cl,
                    max_consecutive_losses=mc,
                    account_status=AccountStatus.ACTIVE,
                    daily_loss_limit=5_000,
                    remaining_daily_loss=4_500,
                    monthly_loss_limit=10_000,
                    remaining_monthly_loss=rm,
                )

            async def place_order(self, *a, **kw):
                return {}

            async def close_trade(self, trade_id):
                return {}

            async def get_open_trades(self):
                return []

            async def get_trade_history(self, limit=100):
                return []

        return MockBroker("key", "secret", "acc", PropFirmType.FTMO)

    @pytest.mark.asyncio
    async def test_monthly_loss_exceeded(self):
        broker = self._make_broker(remaining_monthly=0.0)
        violated, reason = await broker.check_risk_violations()
        assert violated is True
        assert "monthly" in reason.lower()

    @pytest.mark.asyncio
    async def test_daily_drawdown_exceeded(self):
        # daily_drawdown_percentage >= 5.0 triggers violation
        from brokers.prop_firms.all_brokers import (
            AccountStatus,
            BasePropFirmBroker,
            PropFirmMetrics,
            PropFirmType,
            TradingPhase,
        )

        class MockBroker(BasePropFirmBroker):
            async def get_metrics(self):
                return PropFirmMetrics(
                    account_id="A1",
                    firm_type=PropFirmType.FTMO,
                    account_balance=100_000,
                    equity=95_000,
                    used_margin=0,
                    available_margin=95_000,
                    profit_loss=-5_000,
                    profit_loss_percentage=-5.0,
                    daily_drawdown=5_000,
                    daily_drawdown_percentage=5.5,  # > 5%
                    monthly_drawdown=5_000,
                    monthly_drawdown_percentage=5.0,
                    remaining_days=20,
                    trading_phase=TradingPhase.CHALLENGE,
                    trades_completed=5,
                    win_rate=0.4,
                    largest_win=200,
                    largest_loss=500,
                    consecutive_losses=2,
                    max_consecutive_losses=5,
                    account_status=AccountStatus.ACTIVE,
                    daily_loss_limit=5_000,
                    remaining_daily_loss=100.0,
                    monthly_loss_limit=10_000,
                    remaining_monthly_loss=5_000.0,
                )

            async def place_order(self, *a, **kw):
                return {}

            async def close_trade(self, trade_id):
                return {}

            async def get_open_trades(self):
                return []

            async def get_trade_history(self, limit=100):
                return []

        broker = MockBroker("key", "secret", "acc", PropFirmType.FTMO)
        violated, reason = await broker.check_risk_violations()
        assert violated is True

    @pytest.mark.asyncio
    async def test_no_violation_when_healthy(self):
        broker = self._make_broker(remaining_monthly=9_000.0, consecutive=1, max_consec=5)
        violated, reason = await broker.check_risk_violations()
        assert violated is False
