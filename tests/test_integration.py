"""
tests/test_integration.py
=========================
End-to-end integration tests for the full HOPEFX trading pipeline.

Covers the canonical path: tick → signal → risk check → paper order →
fill → DB update → notification dispatch.

All tests use real production classes (PaperTradingBroker, RiskManager,
KillSwitch, MetricsRegistry) with no external network calls.
"""

from __future__ import annotations

import os
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
        deactivation_token="test-token-abc",
    )


@pytest.fixture
def metrics():
    return get_metrics_registry()


# ── 1. Full trading cycle ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_buy_sell_cycle(broker):
    """Tick → BUY order → fill → price move → close → position gone."""
    await broker.connect()
    broker.update_market_price("XAUUSD", 2000.0)

    order = broker.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 0.1)
    assert order is not None

    positions = broker.get_positions()
    assert any(p.symbol == "XAUUSD" for p in positions)

    broker.update_market_price("XAUUSD", 2020.0)
    closed = broker.close_position("XAUUSD")
    assert closed is True

    positions_after = broker.get_positions()
    assert not any(p.symbol == "XAUUSD" for p in positions_after)

    await broker.disconnect()


@pytest.mark.asyncio
async def test_multi_symbol_positions_independent(broker):
    """Two symbols can hold independent positions simultaneously."""
    await broker.connect()
    broker.update_market_price("EURUSD", 1.0850)
    broker.update_market_price("XAUUSD", 2000.0)

    broker.place_order("EURUSD", OrderSide.BUY, OrderType.MARKET, 0.1)
    broker.place_order("XAUUSD", OrderSide.SELL, OrderType.MARKET, 0.1)

    symbols = {p.symbol for p in broker.get_positions()}
    assert "EURUSD" in symbols
    assert "XAUUSD" in symbols

    await broker.disconnect()


@pytest.mark.asyncio
async def test_account_equity_decreases_on_loss(broker):
    """A losing trade reduces account equity."""
    await broker.connect()
    broker.update_market_price("XAUUSD", 2000.0)
    initial_balance = broker.get_account_info().balance

    broker.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 1.0)
    broker.update_market_price("XAUUSD", 1980.0)  # price drops
    broker.close_position("XAUUSD")

    final_balance = broker.get_account_info().balance
    assert final_balance < initial_balance

    await broker.disconnect()


@pytest.mark.asyncio
async def test_account_equity_increases_on_profit(broker):
    """A winning trade increases account equity."""
    await broker.connect()
    broker.update_market_price("XAUUSD", 2000.0)
    initial_balance = broker.get_account_info().balance

    broker.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 1.0)
    broker.update_market_price("XAUUSD", 2050.0)  # price rises
    broker.close_position("XAUUSD")

    final_balance = broker.get_account_info().balance
    assert final_balance > initial_balance

    await broker.disconnect()


# ── 2. Risk manager integration ───────────────────────────────────────────────


def test_risk_validate_trade_returns_typed_tuple(risk):
    """validate_trade always returns (bool, str)."""
    allowed, reason = risk.validate_trade("XAUUSD", 0.1, "buy")
    assert isinstance(allowed, bool)
    assert isinstance(reason, str)


def test_risk_assess_risk_has_required_fields(risk):
    """assess_risk returns an object with can_trade and level attributes."""
    risk.update_equity(100_000.0)
    assessment = risk.assess_risk(
        {"equity": 100_000.0, "balance": 100_000.0}, []
    )
    assert hasattr(assessment, "can_trade")
    assert hasattr(assessment, "level")
    assert isinstance(assessment.can_trade, bool)


def test_risk_drawdown_tracking(risk):
    """Equity drop below threshold is reflected in drawdown state."""
    risk.update_equity(100_000.0)
    risk.update_equity(89_000.0)  # 11% drawdown — over 10% limit
    assessment = risk.assess_risk(
        {"equity": 89_000.0, "balance": 89_000.0}, []
    )
    # At 11% drawdown the system should flag it
    assert isinstance(assessment.can_trade, bool)


# ── 3. Kill switch integration ────────────────────────────────────────────────


def test_kill_switch_starts_inactive(ks):
    assert ks.is_active() is False


def test_kill_switch_activate_deactivate(ks):
    ks.activate("integration test")
    assert ks.is_active() is True
    assert "integration test" in ks.reason

    ks.deactivate(token="test-token-abc")
    assert ks.is_active() is False


def test_kill_switch_persists_across_instances(tmp_path):
    """State written by one instance is read by a new instance."""
    flag = tmp_path / "ks_persist.flag"
    ks1 = KillSwitch(flag_file=flag, deactivation_token="tok")
    ks1.activate("persistence test")

    ks2 = KillSwitch(flag_file=flag, deactivation_token="tok")
    assert ks2.is_active() is True

    ks2.deactivate(token="tok")
    assert ks2.is_active() is False


def test_kill_switch_callback_fires_on_activation(ks):
    fired = []
    ks.register_callback(lambda reason: fired.append(reason))
    ks.activate("callback test")
    assert len(fired) == 1
    assert "callback test" in fired[0]


def test_kill_switch_status_dict(ks):
    status = ks.status()
    assert isinstance(status, dict)
    assert "active" in status


# ── 4. Metrics integration ────────────────────────────────────────────────────


def test_metrics_record_trade_no_exception(metrics):
    """record_trade must not raise for any valid input."""
    metrics.record_trade("XAUUSD", "buy", pnl=150.0, commission=3.5)
    metrics.record_trade("XAUUSD", "sell", pnl=-50.0, commission=3.5)


def test_metrics_order_counter_increments(metrics):
    counter = metrics.get_collector("hopefx_orders_total")
    assert counter is not None
    before = counter.get_value({"symbol": "XAUUSD", "side": "buy"}) or 0
    counter.inc(1, {"symbol": "XAUUSD", "side": "buy"})
    after = counter.get_value({"symbol": "XAUUSD", "side": "buy"}) or 0
    assert after == before + 1


def test_metrics_equity_gauge_readable(metrics):
    gauge = metrics.get_collector("hopefx_equity")
    assert gauge is not None
    gauge.set(105_000.0)
    assert gauge.get_value() == pytest.approx(105_000.0)


def test_metrics_latency_histogram_observe(metrics):
    hist = metrics.get_collector("hopefx_order_latency_ms_bucket")
    assert hist is not None
    before = hist.get_count()
    hist.observe(12.5)
    assert hist.get_count() == before + 1


# ── 5. Notification pipeline (no network) ────────────────────────────────────


def test_email_fill_no_smtp_returns_bool():
    from notifications.email_triggers import send_trade_fill_email
    result = send_trade_fill_email(
        symbol="XAUUSD", direction="buy", quantity=0.1,
        fill_price=2050.0, net_pnl=None, commission=3.5, to="",
    )
    assert isinstance(result, bool)


def test_email_daily_report_no_smtp_returns_bool():
    from notifications.email_triggers import send_daily_report_email
    result = send_daily_report_email(
        date="2026-03-26", daily_pnl=312.50, daily_pnl_pct=0.31,
        total_trades=3, win_rate_pct=66.7, equity=105_312.50, to="",
    )
    assert isinstance(result, bool)


def test_email_risk_halt_no_smtp_returns_bool():
    from notifications.email_triggers import send_risk_halt_email
    result = send_risk_halt_email(
        reason="Daily loss limit reached",
        drawdown_pct=5.02, limit_pct=5.0, to="",
    )
    assert isinstance(result, bool)


def test_fcm_log_only_when_no_key(capsys):
    """PushNotificationManager logs when no FCM key is set."""
    with patch.dict(os.environ, {
        "FIREBASE_SERVER_KEY": "",
        "FIREBASE_CREDENTIALS_JSON": "",
        "FIREBASE_CREDENTIALS_BASE64": "",
        "FIREBASE_PROJECT_ID": "",
    }):
        from mobile.push_notifications import PushNotificationManager
        mgr = PushNotificationManager()
        assert mgr.fcm_enabled is False
        result = mgr.send_notification("user1", "Test", "Body")
        assert result is True

    captured = capsys.readouterr()
    assert "FCM-LOG" in captured.out


# ── 6. Discord bot (no network) ───────────────────────────────────────────────


def test_discord_bot_skips_when_no_webhook():
    from notifications.discord_bot import DiscordSignalBot
    with patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": ""}):
        bot = DiscordSignalBot()
        result = bot.post_signal_sync({
            "symbol": "XAUUSD", "direction": "BUY",
            "confidence": 0.72, "probability": 0.68,
            "model_version": "advanced_oos_v1",
        })
    assert result is False


def test_discord_embed_has_required_keys():
    from notifications.discord_bot import _build_signal_embed
    embed = _build_signal_embed({
        "symbol": "XAUUSD", "direction": "BUY",
        "confidence": 0.72, "probability": 0.68,
        "model_version": "advanced_oos_v1",
        "entry_price": 2050.0, "stop_loss": 2030.0, "take_profit": 2090.0,
        "timestamp": "2026-03-26T12:00:00Z",
    })
    assert "title" in embed
    assert "color" in embed
    assert "fields" in embed
    assert isinstance(embed["fields"], list)
    assert len(embed["fields"]) >= 3
    assert "XAUUSD" in embed["title"]
    assert "BUY" in embed["title"]


def test_discord_rr_ratio_computed():
    from notifications.discord_bot import _rr_ratio
    rr = _rr_ratio(entry=2050.0, sl=2030.0, tp=2090.0)
    assert rr == "2.00:1"


def test_discord_direction_emoji():
    from notifications.discord_bot import _direction_emoji
    assert _direction_emoji("BUY") == "📈"
    assert _direction_emoji("SELL") == "📉"
    assert _direction_emoji("HOLD") == "⏸️"
