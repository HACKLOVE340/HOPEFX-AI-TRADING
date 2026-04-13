# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_core_domain.py
===============================
Coverage tests for core/domain_enums.py and core/domain_models.py.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from core.domain_enums import (
    BrokerType,
    DataFrequency,
    OrderStatus,
    OrderType,
    PositionStatus,
    PropFirm,
    RiskLevel,
    SignalStrength,
    StrategyState,
    TimeInForce,
    TradeDirection,
)
from core.domain_models import (
    Account,
    OHLCV,
    Order,
    Position,
    Signal,
    TickData,
    MarketData,
)

UTC = timezone.utc


# ── domain_enums ──────────────────────────────────────────────────────────────


def test_trade_direction_values():
    assert TradeDirection.LONG == "LONG"
    assert TradeDirection.SHORT == "SHORT"
    assert TradeDirection.FLAT == "FLAT"


def test_order_type_values():
    assert OrderType.MARKET == "MARKET"
    assert OrderType.LIMIT == "LIMIT"
    assert OrderType.STOP == "STOP"
    assert OrderType.STOP_LIMIT == "STOP_LIMIT"
    assert OrderType.TRAILING_STOP == "TRAILING_STOP"
    assert OrderType.OCO == "OCO"


def test_order_status_values():
    assert OrderStatus.PENDING == "PENDING"
    assert OrderStatus.SUBMITTED == "SUBMITTED"
    assert OrderStatus.PARTIAL_FILL == "PARTIAL_FILL"
    assert OrderStatus.FILLED == "FILLED"
    assert OrderStatus.CANCELLED == "CANCELLED"
    assert OrderStatus.REJECTED == "REJECTED"
    assert OrderStatus.EXPIRED == "EXPIRED"


def test_time_in_force_values():
    assert TimeInForce.GTC == "GTC"
    assert TimeInForce.IOC == "IOC"
    assert TimeInForce.FOK == "FOK"
    assert TimeInForce.GTD == "GTD"
    assert TimeInForce.DAY == "DAY"


def test_position_status_values():
    assert PositionStatus.OPEN == "OPEN"
    assert PositionStatus.CLOSED == "CLOSED"
    assert PositionStatus.HEDGED == "HEDGED"


def test_signal_strength_ordering():
    assert SignalStrength.WEAK < SignalStrength.MODERATE
    assert SignalStrength.MODERATE < SignalStrength.STRONG
    assert SignalStrength.STRONG < SignalStrength.VERY_STRONG


def test_prop_firm_values():
    assert PropFirm.FTMO == "FTMO"
    assert PropFirm.MY_FOREX_FUNDS == "MFF"
    assert PropFirm.NONE == "NONE"


def test_data_frequency_values():
    assert DataFrequency.TICK == "TICK"
    assert DataFrequency.MINUTE_1 == "1M"
    assert DataFrequency.HOUR_1 == "1H"
    assert DataFrequency.DAILY == "1D"


def test_broker_type_values():
    assert BrokerType.OANDA == "OANDA"
    assert BrokerType.META_TRADER_5 == "MT5"
    assert BrokerType.PAPER == "PAPER"


def test_strategy_state_values():
    assert StrategyState.ACTIVE == "ACTIVE"
    assert StrategyState.PAUSED == "PAUSED"
    assert StrategyState.ERROR == "ERROR"


def test_risk_level_ordering():
    assert RiskLevel.LOW < RiskLevel.MEDIUM < RiskLevel.HIGH
    assert RiskLevel.HIGH < RiskLevel.CRITICAL < RiskLevel.EMERGENCY


# ── TickData ──────────────────────────────────────────────────────────────────


def test_tick_data_valid():
    tick = TickData(
        symbol="XAUUSD",
        bid=Decimal("1920.00000"),
        ask=Decimal("1920.50000"),
        mid=Decimal("1920.25000"),
        volume=1000,
    )
    assert tick.symbol == "XAUUSD"
    assert tick.bid < tick.ask


def test_tick_data_ask_must_exceed_bid():
    with pytest.raises(ValidationError):
        TickData(
            symbol="EURUSD",
            bid=Decimal("1.10000"),
            ask=Decimal("1.09000"),  # ask < bid — invalid
            mid=Decimal("1.09500"),
            volume=100,
        )


def test_tick_data_mid_must_be_midpoint():
    with pytest.raises(ValidationError):
        TickData(
            symbol="EURUSD",
            bid=Decimal("1.08000"),
            ask=Decimal("1.09000"),
            mid=Decimal("1.05000"),  # wrong midpoint
            volume=100,
        )


def test_tick_data_frozen():
    tick = TickData(
        symbol="GBPUSD",
        bid=Decimal("1.25000"),
        ask=Decimal("1.25100"),
        mid=Decimal("1.25050"),
        volume=500,
    )
    with pytest.raises(ValidationError):
        tick.volume = 999  # frozen model


# ── OHLCV ─────────────────────────────────────────────────────────────────────


def test_ohlcv_valid():
    bar = OHLCV(
        symbol="XAUUSD",
        timestamp=datetime.now(UTC),
        open=Decimal("1900.0"),
        high=Decimal("1920.0"),
        low=Decimal("1890.0"),
        close=Decimal("1910.0"),
        volume=5000,
        frequency=DataFrequency.HOUR_1,
    )
    assert bar.high >= bar.low
    assert bar.high >= bar.open
    assert bar.high >= bar.close


def test_ohlcv_high_below_open_raises():
    with pytest.raises(ValidationError):
        OHLCV(
            symbol="XAUUSD",
            timestamp=datetime.now(UTC),
            open=Decimal("1950.0"),
            high=Decimal("1900.0"),  # high < open — invalid
            low=Decimal("1880.0"),
            close=Decimal("1910.0"),
            volume=100,
            frequency=DataFrequency.DAILY,
        )


def test_ohlcv_low_above_close_raises():
    with pytest.raises(ValidationError):
        OHLCV(
            symbol="XAUUSD",
            timestamp=datetime.now(UTC),
            open=Decimal("1900.0"),
            high=Decimal("1950.0"),
            low=Decimal("1940.0"),  # low > close — invalid
            close=Decimal("1910.0"),
            volume=100,
            frequency=DataFrequency.DAILY,
        )


def test_market_data_alias():
    """MarketData must be the same class as OHLCV."""
    assert MarketData is OHLCV


# ── Order ─────────────────────────────────────────────────────────────────────


def test_order_defaults():
    order = Order(
        symbol="EURUSD",
        direction=TradeDirection.LONG,
        order_type=OrderType.MARKET,
        quantity=Decimal("10000"),
    )
    assert order.status == OrderStatus.PENDING
    assert order.time_in_force == TimeInForce.GTC
    assert order.filled_quantity == Decimal(0)
    assert order.id is not None


def test_order_is_filled_property():
    order = Order(
        symbol="EURUSD",
        direction=TradeDirection.LONG,
        order_type=OrderType.MARKET,
        quantity=Decimal("10000"),
    )
    assert not order.is_filled
    order.status = OrderStatus.FILLED
    assert order.is_filled


def test_order_remaining_property():
    order = Order(
        symbol="EURUSD",
        direction=TradeDirection.LONG,
        order_type=OrderType.MARKET,
        quantity=Decimal("10000"),
    )
    order.filled_quantity = Decimal("4000")
    assert order.remaining == Decimal("6000")


# ── Position ──────────────────────────────────────────────────────────────────


def test_position_long_pnl():
    pos = Position(
        symbol="XAUUSD",
        direction=TradeDirection.LONG,
        entry_price=Decimal("1900.0"),
        quantity=Decimal("1.0"),
    )
    pnl = pos.calculate_unrealized_pnl(Decimal("1950.0"))
    assert pnl == Decimal("50.0")


def test_position_short_pnl():
    pos = Position(
        symbol="XAUUSD",
        direction=TradeDirection.SHORT,
        entry_price=Decimal("1900.0"),
        quantity=Decimal("1.0"),
    )
    pnl = pos.calculate_unrealized_pnl(Decimal("1850.0"))
    assert pnl == Decimal("50.0")


def test_position_defaults():
    pos = Position(
        symbol="EURUSD",
        direction=TradeDirection.LONG,
        entry_price=Decimal("1.08"),
        quantity=Decimal("10000"),
    )
    assert pos.status == PositionStatus.OPEN
    assert pos.unrealized_pnl == Decimal(0)
    assert pos.realized_pnl == Decimal(0)
    assert pos.closed_at is None


# ── Signal ────────────────────────────────────────────────────────────────────


def test_signal_valid():
    sig = Signal(
        strategy_id="ma_cross",
        symbol="XAUUSD",
        direction=TradeDirection.LONG,
        strength=0.85,
        confidence=0.72,
    )
    assert sig.strength == 0.85
    assert sig.confidence == 0.72
    assert sig.features == {}


def test_signal_strength_bounds():
    with pytest.raises(ValidationError):
        Signal(
            strategy_id="s",
            symbol="X",
            direction=TradeDirection.LONG,
            strength=1.5,  # > 1.0 — invalid
            confidence=0.5,
        )


def test_signal_frozen():
    sig = Signal(
        strategy_id="s",
        symbol="XAUUSD",
        direction=TradeDirection.LONG,
        strength=0.5,
        confidence=0.5,
    )
    with pytest.raises(ValidationError):
        sig.strength = 0.9


# ── Account ───────────────────────────────────────────────────────────────────


def test_account_defaults():
    acc = Account(broker=BrokerType.PAPER, account_id="test-001")
    assert acc.balance == Decimal(0)
    assert acc.prop_firm == PropFirm.NONE
    assert acc.open_positions == {}


def test_account_mutable():
    acc = Account(broker=BrokerType.OANDA, account_id="live-001")
    acc.balance = Decimal("100000")
    assert acc.balance == Decimal("100000")
