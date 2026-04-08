# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Tests for brokers/prop_firms/all_brokers.py

Covers: PropFirmMetrics, PropFirmTrade, RiskLimits, PropFirmType,
        TradingPhase, AccountStatus, BasePropFirmBroker abstract interface,
        FTMOBroker._generate_signature, PropFirmFactory.create_broker,
        BasePropFirmBroker.check_risk_violations.
"""

import asyncio
from datetime import datetime, timezone

import pytest

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPropFirmEnums:
    def test_prop_firm_type_values(self):
        from brokers.prop_firms.all_brokers import PropFirmType
        assert PropFirmType.FTMO.value == "ftmo"
        assert PropFirmType.THE5ERS.value == "the5ers"
        assert PropFirmType.MYFOREXFUNDS.value == "myforexfunds"
        assert PropFirmType.TOPSTEP.value == "topstep"

    def test_trading_phase_values(self):
        from brokers.prop_firms.all_brokers import TradingPhase
        assert TradingPhase.CHALLENGE.value == "challenge"
        assert TradingPhase.FUNDED.value == "funded"

    def test_account_status_values(self):
        from brokers.prop_firms.all_brokers import AccountStatus
        assert AccountStatus.ACTIVE.value == "active"
        assert AccountStatus.SUSPENDED.value == "suspended"
        assert AccountStatus.PASSED.value == "passed"


# ---------------------------------------------------------------------------
# PropFirmMetrics dataclass
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPropFirmMetrics:
    def _make_metrics(self, **kwargs):
        from brokers.prop_firms.all_brokers import (
            AccountStatus, PropFirmMetrics, PropFirmType, TradingPhase,
        )
        defaults = dict(
            account_id="ACC-001",
            firm_type=PropFirmType.FTMO,
            account_balance=100_000.0,
            equity=100_500.0,
            used_margin=2_000.0,
            available_margin=98_000.0,
            profit_loss=500.0,
            profit_loss_percentage=0.5,
            daily_drawdown=200.0,
            daily_drawdown_percentage=0.2,
            monthly_drawdown=500.0,
            monthly_drawdown_percentage=0.5,
            remaining_days=25,
            trading_phase=TradingPhase.CHALLENGE,
            trades_completed=10,
            win_rate=0.6,
            largest_win=300.0,
            largest_loss=150.0,
            consecutive_losses=1,
            max_consecutive_losses=3,
            account_status=AccountStatus.ACTIVE,
            daily_loss_limit=5_000.0,
            remaining_daily_loss=4_800.0,
            monthly_loss_limit=10_000.0,
            remaining_monthly_loss=9_500.0,
        )
        defaults.update(kwargs)
        return PropFirmMetrics(**defaults)

    def test_init(self):
        m = self._make_metrics()
        assert m.account_id == "ACC-001"
        assert m.account_balance == pytest.approx(100_000.0)

    def test_default_leverage(self):
        m = self._make_metrics()
        assert m.leverage == 100

    def test_last_update_is_datetime(self):
        m = self._make_metrics()
        assert isinstance(m.last_update, datetime)


# ---------------------------------------------------------------------------
# PropFirmTrade dataclass
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPropFirmTrade:
    def test_init_defaults(self):
        from brokers.prop_firms.all_brokers import PropFirmTrade
        trade = PropFirmTrade(
            trade_id="T001",
            symbol="EUR/USD",
            side="BUY",
            entry_price=1.1000,
        )
        assert trade.status == "open"
        assert trade.exit_price is None
        assert trade.pnl == pytest.approx(0.0)

    def test_custom_values(self):
        from brokers.prop_firms.all_brokers import PropFirmTrade
        trade = PropFirmTrade(
            trade_id="T002",
            symbol="XAU/USD",
            side="SELL",
            entry_price=1950.0,
            exit_price=1940.0,
            quantity=1.0,
            pnl=100.0,
            status="closed",
        )
        assert trade.pnl == pytest.approx(100.0)
        assert trade.status == "closed"


# ---------------------------------------------------------------------------
# RiskLimits dataclass
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestRiskLimits:
    def test_init(self):
        from brokers.prop_firms.all_brokers import RiskLimits
        rl = RiskLimits(
            daily_loss_limit=5_000.0,
            monthly_loss_limit=10_000.0,
            max_drawdown_percentage=10.0,
            max_consecutive_losses=5,
            max_position_size=10.0,
            min_days_required=10,
        )
        assert rl.daily_loss_limit == pytest.approx(5_000.0)
        assert rl.max_drawdown_percentage == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# BasePropFirmBroker — abstract interface
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestBasePropFirmBrokerAbstract:
    def test_cannot_instantiate_directly(self):
        from brokers.prop_firms.all_brokers import BasePropFirmBroker
        with pytest.raises(TypeError):
            BasePropFirmBroker("key", "secret", "acc", None)

    def test_concrete_without_methods_raises(self):
        from brokers.prop_firms.all_brokers import BasePropFirmBroker
        class Incomplete(BasePropFirmBroker):
            pass
        with pytest.raises(TypeError):
            Incomplete("key", "secret", "acc", None)

    def test_check_risk_violations_daily_loss_exceeded(self):
        """check_risk_violations returns True when remaining_daily_loss <= 0."""
        from brokers.prop_firms.all_brokers import (
            AccountStatus, BasePropFirmBroker, PropFirmMetrics,
            PropFirmType, TradingPhase,
        )

        class MockBroker(BasePropFirmBroker):
            async def get_metrics(self):
                return PropFirmMetrics(
                    account_id="A1", firm_type=PropFirmType.FTMO,
                    account_balance=100_000, equity=95_000,
                    used_margin=0, available_margin=95_000,
                    profit_loss=-5_000, profit_loss_percentage=-5.0,
                    daily_drawdown=5_000, daily_drawdown_percentage=5.0,
                    monthly_drawdown=5_000, monthly_drawdown_percentage=5.0,
                    remaining_days=20, trading_phase=TradingPhase.CHALLENGE,
                    trades_completed=5, win_rate=0.4,
                    largest_win=200, largest_loss=500,
                    consecutive_losses=3, max_consecutive_losses=5,
                    account_status=AccountStatus.ACTIVE,
                    daily_loss_limit=5_000, remaining_daily_loss=0.0,  # exhausted
                    monthly_loss_limit=10_000, remaining_monthly_loss=5_000,
                )
            async def place_order(self, *a, **kw): return {}
            async def close_trade(self, trade_id): return {}
            async def get_open_trades(self): return []
            async def get_trade_history(self, limit=100): return []

        broker = MockBroker("key", "secret", "acc", PropFirmType.FTMO)
        violated, reason = asyncio.run(broker.check_risk_violations())
        assert violated is True
        assert "daily" in reason.lower()

    def test_check_risk_violations_ok(self):
        from brokers.prop_firms.all_brokers import (
            AccountStatus, BasePropFirmBroker, PropFirmMetrics,
            PropFirmType, TradingPhase,
        )

        class MockBroker(BasePropFirmBroker):
            async def get_metrics(self):
                return PropFirmMetrics(
                    account_id="A1", firm_type=PropFirmType.FTMO,
                    account_balance=100_000, equity=101_000,
                    used_margin=0, available_margin=101_000,
                    profit_loss=1_000, profit_loss_percentage=1.0,
                    daily_drawdown=100, daily_drawdown_percentage=0.1,
                    monthly_drawdown=100, monthly_drawdown_percentage=0.1,
                    remaining_days=25, trading_phase=TradingPhase.CHALLENGE,
                    trades_completed=5, win_rate=0.6,
                    largest_win=500, largest_loss=100,
                    consecutive_losses=0, max_consecutive_losses=5,
                    account_status=AccountStatus.ACTIVE,
                    daily_loss_limit=5_000, remaining_daily_loss=4_900,
                    monthly_loss_limit=10_000, remaining_monthly_loss=9_900,
                )
            async def place_order(self, *a, **kw): return {}
            async def close_trade(self, trade_id): return {}
            async def get_open_trades(self): return []
            async def get_trade_history(self, limit=100): return []

        broker = MockBroker("key", "secret", "acc", PropFirmType.FTMO)
        violated, reason = asyncio.run(broker.check_risk_violations())
        assert violated is False
        assert reason is None


# ---------------------------------------------------------------------------
# FTMOBroker._generate_signature
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestFTMOBrokerSignature:
    def test_generate_signature_returns_dict(self):
        from brokers.prop_firms.all_brokers import FTMOBroker
        broker = FTMOBroker("test-api-key", "test-secret-key", "ACC-001", sandbox=True)
        headers = broker._generate_signature("GET", "/accounts/ACC-001/metrics")
        assert isinstance(headers, dict)

    def test_generate_signature_required_keys(self):
        from brokers.prop_firms.all_brokers import FTMOBroker
        broker = FTMOBroker("test-api-key", "test-secret-key", "ACC-001", sandbox=True)
        headers = broker._generate_signature("GET", "/test/endpoint")
        assert "Authorization" in headers
        assert "X-FTMO-TIMESTAMP" in headers
        assert "X-FTMO-NONCE" in headers
        assert "Content-Type" in headers

    def test_generate_signature_authorization_format(self):
        from brokers.prop_firms.all_brokers import FTMOBroker
        broker = FTMOBroker("my-api-key", "my-secret", "ACC-001", sandbox=True)
        headers = broker._generate_signature("POST", "/orders")
        assert headers["Authorization"].startswith("FTMO my-api-key:")

    def test_generate_signature_nonce_increments(self):
        from brokers.prop_firms.all_brokers import FTMOBroker
        broker = FTMOBroker("key", "secret", "acc", sandbox=True)
        broker._generate_signature("GET", "/ep1")
        broker._generate_signature("GET", "/ep2")
        assert broker._nonce == 2

    def test_generate_signature_with_data(self):
        from brokers.prop_firms.all_brokers import FTMOBroker
        broker = FTMOBroker("key", "secret", "acc", sandbox=True)
        headers = broker._generate_signature(
            "POST", "/orders", data={"symbol": "EUR/USD", "side": "BUY"}
        )
        assert "Authorization" in headers

    def test_signature_is_valid_hmac_sha256(self):
        """Verify the signature is a valid 64-char hex SHA-256 HMAC."""
        from brokers.prop_firms.all_brokers import FTMOBroker
        broker = FTMOBroker("key", "my-secret-key", "acc", sandbox=True)
        headers = broker._generate_signature("GET", "/test")
        auth = headers["Authorization"]
        # Format: "FTMO key:hexsig"
        sig_hex = auth.split(":")[1]
        assert len(sig_hex) == 64
        assert all(c in "0123456789abcdef" for c in sig_hex)

    def test_different_methods_produce_different_signatures(self):
        from brokers.prop_firms.all_brokers import FTMOBroker
        broker = FTMOBroker("key", "secret", "acc", sandbox=True)
        h_get = broker._generate_signature("GET", "/ep")
        broker2 = FTMOBroker("key", "secret", "acc", sandbox=True)
        h_post = broker2._generate_signature("POST", "/ep")
        assert h_get["Authorization"] != h_post["Authorization"]


# ---------------------------------------------------------------------------
# PropFirmFactory
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPropFirmFactory:
    def test_create_ftmo_broker(self):
        from brokers.prop_firms.all_brokers import FTMOBroker, PropFirmFactory, PropFirmType
        broker = PropFirmFactory.create_broker(
            PropFirmType.FTMO, "key", "secret", "acc", sandbox=True
        )
        assert isinstance(broker, FTMOBroker)

    def test_create_the5ers_broker(self):
        from brokers.prop_firms.all_brokers import PropFirmFactory, PropFirmType, The5ersBroker
        broker = PropFirmFactory.create_broker(
            PropFirmType.THE5ERS, "key", "secret", "acc", sandbox=True
        )
        assert isinstance(broker, The5ersBroker)

    def test_create_myforexfunds_broker(self):
        from brokers.prop_firms.all_brokers import MyForexFundsBroker, PropFirmFactory, PropFirmType
        broker = PropFirmFactory.create_broker(
            PropFirmType.MYFOREXFUNDS, "key", "secret", "acc", sandbox=True
        )
        assert isinstance(broker, MyForexFundsBroker)

    def test_create_topstep_broker(self):
        from brokers.prop_firms.all_brokers import PropFirmFactory, PropFirmType, TopStepBroker
        broker = PropFirmFactory.create_broker(
            PropFirmType.TOPSTEP, "key", "secret", "acc", sandbox=True
        )
        assert isinstance(broker, TopStepBroker)

    def test_unknown_type_raises(self):
        from brokers.prop_firms.all_brokers import PropFirmFactory
        with pytest.raises(ValueError, match="Unknown prop firm"):
            PropFirmFactory.create_broker("invalid_type", "k", "s", "a")

    def test_all_firm_types_covered(self):
        from brokers.prop_firms.all_brokers import PropFirmFactory, PropFirmType
        for firm_type in PropFirmType:
            broker = PropFirmFactory.create_broker(firm_type, "k", "s", "a", sandbox=True)
            assert broker is not None
