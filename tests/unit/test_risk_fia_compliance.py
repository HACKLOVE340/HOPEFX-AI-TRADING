# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Tests for risk/fia_compliance.py — FIAComplianceManager, RiskControlStatus, RiskCheckResult."""

from __future__ import annotations

import time
from datetime import datetime, timezone

import pytest

from risk.fia_compliance import FIAComplianceManager, RiskCheckResult, RiskControlStatus

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mgr(**kwargs) -> FIAComplianceManager:
    config = {
        "max_order_size": 100,
        "max_order_notional": 1_000_000,
        "max_intraday_position": 500,
        "max_messages_per_second": 50,
        "daily_loss_limit": 0.03,
        "price_tolerance": 0.02,
    }
    config.update(kwargs)
    return FIAComplianceManager(config=config)


# ---------------------------------------------------------------------------
# RiskControlStatus enum
# ---------------------------------------------------------------------------


class TestRiskControlStatus:
    def test_values(self):
        assert RiskControlStatus.PASS.value == "pass"
        assert RiskControlStatus.WARNING.value == "warning"
        assert RiskControlStatus.BLOCK.value == "block"
        assert RiskControlStatus.KILL_SWITCH.value == "kill_switch"


# ---------------------------------------------------------------------------
# RiskCheckResult dataclass
# ---------------------------------------------------------------------------


class TestRiskCheckResult:
    def test_fields(self):
        r = RiskCheckResult(
            status=RiskControlStatus.PASS,
            rule="FIA_1.1",
            message="OK",
            timestamp=datetime.now(UTC),
        )
        assert r.status == RiskControlStatus.PASS
        assert r.rule == "FIA_1.1"
        assert r.metadata is None

    def test_with_metadata(self):
        r = RiskCheckResult(
            status=RiskControlStatus.BLOCK,
            rule="FIA_1.1",
            message="blocked",
            timestamp=datetime.now(UTC),
            metadata={"key": "value"},
        )
        assert r.metadata == {"key": "value"}


# ---------------------------------------------------------------------------
# FIAComplianceManager construction
# ---------------------------------------------------------------------------


class TestFIAComplianceManagerInit:
    def test_initial_state(self):
        mgr = _mgr()
        assert mgr.kill_switch_active is False
        assert mgr.daily_pnl == pytest.approx(0.0)
        assert mgr.orders_today == 0
        assert mgr.message_count == 0

    def test_config_stored(self):
        mgr = _mgr()
        assert mgr.config["max_order_size"] == 100


# ---------------------------------------------------------------------------
# FIA 1.1: check_max_order_size
# ---------------------------------------------------------------------------


class TestCheckMaxOrderSize:
    def test_within_limit_passes(self):
        mgr = _mgr()
        result = mgr.check_max_order_size(50.0, "XAUUSD")
        assert result.status == RiskControlStatus.PASS
        assert result.rule == "FIA_1.1_MAX_ORDER_SIZE"

    def test_at_limit_passes(self):
        mgr = _mgr()
        result = mgr.check_max_order_size(100.0, "XAUUSD")
        assert result.status == RiskControlStatus.PASS

    def test_exceeds_limit_blocks(self):
        mgr = _mgr()
        result = mgr.check_max_order_size(101.0, "XAUUSD")
        assert result.status == RiskControlStatus.BLOCK
        assert "FIA_1.1" in result.rule

    def test_negative_size_exceeds_limit(self):
        mgr = _mgr()
        result = mgr.check_max_order_size(-200.0, "XAUUSD")
        assert result.status == RiskControlStatus.BLOCK

    def test_metadata_on_block(self):
        mgr = _mgr()
        result = mgr.check_max_order_size(200.0, "XAUUSD")
        assert result.metadata is not None
        assert "requested" in result.metadata


# ---------------------------------------------------------------------------
# FIA 1.2: check_intraday_position
# ---------------------------------------------------------------------------


class TestCheckIntradayPosition:
    def test_within_limit_passes(self):
        mgr = _mgr()
        result = mgr.check_intraday_position("XAUUSD", 100.0)
        assert result.status == RiskControlStatus.PASS

    def test_accumulates_position(self):
        mgr = _mgr()
        mgr.check_intraday_position("XAUUSD", 200.0)
        result = mgr.check_intraday_position("XAUUSD", 200.0)
        assert result.status == RiskControlStatus.PASS
        assert mgr.positions_intraday["XAUUSD"] == pytest.approx(400.0)

    def test_exceeds_limit_blocks(self):
        mgr = _mgr()
        result = mgr.check_intraday_position("XAUUSD", 600.0)
        assert result.status == RiskControlStatus.BLOCK
        assert "FIA_1.2" in result.rule

    def test_different_symbols_independent(self):
        mgr = _mgr()
        mgr.check_intraday_position("XAUUSD", 400.0)
        result = mgr.check_intraday_position("EURUSD", 400.0)
        assert result.status == RiskControlStatus.PASS

    def test_metadata_on_block(self):
        mgr = _mgr()
        result = mgr.check_intraday_position("XAUUSD", 600.0)
        assert result.metadata is not None
        assert "projected" in result.metadata


# ---------------------------------------------------------------------------
# FIA 1.3: check_price_tolerance
# ---------------------------------------------------------------------------


class TestCheckPriceTolerance:
    def test_within_tolerance_passes(self):
        mgr = _mgr()
        result = mgr.check_price_tolerance(2000.0, 2000.0, tolerance_pct=0.02)
        assert result.status == RiskControlStatus.PASS

    def test_small_deviation_passes(self):
        mgr = _mgr()
        result = mgr.check_price_tolerance(2010.0, 2000.0, tolerance_pct=0.02)
        # 0.5% deviation < 2% tolerance
        assert result.status == RiskControlStatus.PASS

    def test_large_deviation_blocks(self):
        mgr = _mgr()
        result = mgr.check_price_tolerance(2100.0, 2000.0, tolerance_pct=0.02)
        # 5% deviation > 2% tolerance
        assert result.status == RiskControlStatus.BLOCK
        assert "FIA_1.3" in result.rule

    def test_zero_reference_price_blocks(self):
        mgr = _mgr()
        result = mgr.check_price_tolerance(2000.0, 0.0, tolerance_pct=0.02)
        assert result.status == RiskControlStatus.BLOCK

    def test_negative_reference_price_blocks(self):
        mgr = _mgr()
        result = mgr.check_price_tolerance(2000.0, -100.0, tolerance_pct=0.02)
        assert result.status == RiskControlStatus.BLOCK

    def test_metadata_on_block(self):
        mgr = _mgr()
        result = mgr.check_price_tolerance(2200.0, 2000.0, tolerance_pct=0.02)
        assert result.metadata is not None
        assert "deviation" in result.metadata


# ---------------------------------------------------------------------------
# FIA 1.5: check_kill_switch
# ---------------------------------------------------------------------------


class TestCheckKillSwitch:
    def test_within_threshold_passes(self):
        mgr = _mgr()
        result = mgr.check_kill_switch(daily_pnl=-1000.0, capital=100_000.0, threshold_pct=0.03)
        assert result.status == RiskControlStatus.PASS
        assert mgr.kill_switch_active is False

    def test_exceeds_threshold_activates_kill_switch(self):
        mgr = _mgr()
        result = mgr.check_kill_switch(daily_pnl=-4000.0, capital=100_000.0, threshold_pct=0.03)
        assert result.status == RiskControlStatus.KILL_SWITCH
        assert mgr.kill_switch_active is True

    def test_at_threshold_activates(self):
        mgr = _mgr()
        result = mgr.check_kill_switch(daily_pnl=-3000.0, capital=100_000.0, threshold_pct=0.03)
        assert result.status == RiskControlStatus.KILL_SWITCH

    def test_zero_capital_no_crash(self):
        mgr = _mgr()
        result = mgr.check_kill_switch(daily_pnl=-1000.0, capital=0.0, threshold_pct=0.03)
        assert result.status == RiskControlStatus.PASS  # loss_pct = 0 when capital=0

    def test_callback_fired_on_kill_switch(self):
        mgr = _mgr()
        fired = []
        mgr.register_kill_switch_callback(lambda pnl, pct: fired.append((pnl, pct)))
        mgr.check_kill_switch(daily_pnl=-5000.0, capital=100_000.0, threshold_pct=0.03)
        assert len(fired) == 1
        assert fired[0][0] == pytest.approx(-5000.0)

    def test_callback_exception_does_not_propagate(self):
        mgr = _mgr()
        mgr.register_kill_switch_callback(lambda pnl, pct: (_ for _ in ()).throw(RuntimeError("boom")))
        # Should not raise
        mgr.check_kill_switch(daily_pnl=-5000.0, capital=100_000.0, threshold_pct=0.03)

    def test_metadata_on_kill_switch(self):
        mgr = _mgr()
        result = mgr.check_kill_switch(daily_pnl=-5000.0, capital=100_000.0, threshold_pct=0.03)
        assert result.metadata is not None
        assert "daily_pnl" in result.metadata


# ---------------------------------------------------------------------------
# FIA 3.1: validate_market_data
# ---------------------------------------------------------------------------


class TestValidateMarketData:
    def test_valid_tick_passes(self):
        mgr = _mgr()
        tick = {"bid": 1999.0, "ask": 2001.0, "timestamp": datetime.now(UTC)}
        result = mgr.validate_market_data(tick)
        assert result.status == RiskControlStatus.PASS

    def test_invalid_prices_blocks(self):
        mgr = _mgr()
        tick = {"bid": 0.0, "ask": 0.0}
        result = mgr.validate_market_data(tick)
        assert result.status == RiskControlStatus.BLOCK

    def test_ask_less_than_bid_blocks(self):
        mgr = _mgr()
        tick = {"bid": 2001.0, "ask": 1999.0}
        result = mgr.validate_market_data(tick)
        assert result.status == RiskControlStatus.BLOCK

    def test_wide_spread_blocks(self):
        mgr = _mgr()
        # spread > 1% of bid
        tick = {"bid": 2000.0, "ask": 2030.0}  # 1.5% spread
        result = mgr.validate_market_data(tick)
        assert result.status == RiskControlStatus.BLOCK

    def test_stale_datetime_timestamp_blocks(self):
        mgr = _mgr()
        from datetime import timedelta

        # Aware datetime 60 seconds ago
        tick = {
            "bid": 1999.0,
            "ask": 2001.0,
            "timestamp": datetime.now(UTC) - timedelta(seconds=60),
        }
        result = mgr.validate_market_data(tick)
        assert result.status == RiskControlStatus.BLOCK

    def test_fresh_datetime_timestamp_passes(self):
        mgr = _mgr()
        tick = {
            "bid": 1999.0,
            "ask": 2001.0,
            "timestamp": datetime.now(UTC),
        }
        result = mgr.validate_market_data(tick)
        assert result.status == RiskControlStatus.PASS

    def test_no_timestamp_still_checks_prices(self):
        mgr = _mgr()
        tick = {"bid": 1999.0, "ask": 2001.0}
        result = mgr.validate_market_data(tick)
        assert result.status == RiskControlStatus.PASS

    def test_metadata_on_block(self):
        mgr = _mgr()
        tick = {"bid": 0.0, "ask": 0.0}
        result = mgr.validate_market_data(tick)
        assert result.metadata is not None


# ---------------------------------------------------------------------------
# FIA 3.4: check_message_throttle
# ---------------------------------------------------------------------------


class TestCheckMessageThrottle:
    def test_first_message_passes(self):
        mgr = _mgr()
        result = mgr.check_message_throttle()
        assert result.status == RiskControlStatus.PASS

    def test_within_limit_passes(self):
        mgr = _mgr()
        for _ in range(50):
            result = mgr.check_message_throttle()
        assert result.status == RiskControlStatus.PASS

    def test_exceeds_limit_blocks(self):
        mgr = _mgr(**{"max_messages_per_second": 5})
        for _ in range(5):
            mgr.check_message_throttle()
        result = mgr.check_message_throttle()
        assert result.status == RiskControlStatus.BLOCK
        assert "FIA_3.4" in result.rule

    def test_metadata_on_block(self):
        mgr = _mgr(**{"max_messages_per_second": 2})
        mgr.check_message_throttle()
        mgr.check_message_throttle()
        result = mgr.check_message_throttle()
        assert result.metadata is not None
        assert "count" in result.metadata


# ---------------------------------------------------------------------------
# FIA 3.5: check_self_trade
# ---------------------------------------------------------------------------


class TestCheckSelfTrade:
    def test_no_resting_orders_passes(self):
        mgr = _mgr()
        order = {"side": "buy", "price": 2000.0}
        result = mgr.check_self_trade(order, resting_orders=[])
        assert result.status == RiskControlStatus.PASS

    def test_same_side_no_cross(self):
        mgr = _mgr()
        order = {"side": "buy", "price": 2000.0}
        resting = [{"side": "buy", "price": 2000.0}]
        result = mgr.check_self_trade(order, resting_orders=resting)
        assert result.status == RiskControlStatus.PASS

    def test_buy_crosses_resting_sell(self):
        mgr = _mgr()
        order = {"side": "buy", "price": 2000.0}
        resting = [{"side": "sell", "price": 1990.0}]
        result = mgr.check_self_trade(order, resting_orders=resting)
        assert result.status == RiskControlStatus.BLOCK
        assert "FIA_3.5" in result.rule

    def test_sell_crosses_resting_buy(self):
        mgr = _mgr()
        order = {"side": "sell", "price": 1990.0}
        resting = [{"side": "buy", "price": 2000.0}]
        result = mgr.check_self_trade(order, resting_orders=resting)
        assert result.status == RiskControlStatus.BLOCK

    def test_buy_below_resting_sell_no_cross(self):
        mgr = _mgr()
        order = {"side": "buy", "price": 1980.0}
        resting = [{"side": "sell", "price": 2000.0}]
        result = mgr.check_self_trade(order, resting_orders=resting)
        assert result.status == RiskControlStatus.PASS

    def test_sell_above_resting_buy_no_cross(self):
        mgr = _mgr()
        order = {"side": "sell", "price": 2010.0}
        resting = [{"side": "buy", "price": 2000.0}]
        result = mgr.check_self_trade(order, resting_orders=resting)
        assert result.status == RiskControlStatus.PASS

    def test_metadata_on_block(self):
        mgr = _mgr()
        order = {"side": "buy", "price": 2000.0}
        resting = [{"side": "sell", "price": 1990.0}]
        result = mgr.check_self_trade(order, resting_orders=resting)
        assert result.metadata is not None


# ---------------------------------------------------------------------------
# validate_order (async master validation)
# ---------------------------------------------------------------------------


class TestValidateOrder:
    @pytest.mark.asyncio
    async def test_valid_order_all_pass(self):
        mgr = _mgr()
        order = {"size": 10.0, "symbol": "XAUUSD", "price": 2000.0, "side": "buy"}
        market_data = {"bid": 1999.0, "ask": 2001.0, "mid": 2000.0}
        portfolio = {"daily_pnl": -100.0, "capital": 100_000.0}
        results = await mgr.validate_order(order, market_data, portfolio)
        assert all(r.status == RiskControlStatus.PASS for r in results)

    @pytest.mark.asyncio
    async def test_kill_switch_stops_further_checks(self):
        mgr = _mgr()
        order = {"size": 10.0, "symbol": "XAUUSD", "price": 2000.0, "side": "buy"}
        market_data = {"bid": 1999.0, "ask": 2001.0, "mid": 2000.0}
        # Trigger kill switch: -5% loss
        portfolio = {"daily_pnl": -5000.0, "capital": 100_000.0}
        results = await mgr.validate_order(order, market_data, portfolio)
        # Only kill switch result returned
        assert len(results) == 1
        assert results[0].status == RiskControlStatus.KILL_SWITCH

    @pytest.mark.asyncio
    async def test_oversized_order_blocked(self):
        mgr = _mgr()
        order = {"size": 200.0, "symbol": "XAUUSD", "price": 2000.0, "side": "buy"}
        market_data = {"bid": 1999.0, "ask": 2001.0, "mid": 2000.0}
        portfolio = {"daily_pnl": 0.0, "capital": 100_000.0}
        results = await mgr.validate_order(order, market_data, portfolio)
        statuses = [r.status for r in results]
        assert RiskControlStatus.BLOCK in statuses
