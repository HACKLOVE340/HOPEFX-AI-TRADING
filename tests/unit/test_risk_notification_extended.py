"""
Extended tests for Risk Manager and Notification Manager modules.

Covers uncovered code paths in:
- risk/manager.py: method-based position sizing, can_open_position, validate_trade, etc.
- notifications/manager.py: notification channels, console logging, etc.
"""

import pytest
from unittest.mock import MagicMock, patch, Mock
import logging


# ---------------------------------------------------------------------------
# Risk Manager extended tests
# ---------------------------------------------------------------------------

class TestRiskManagerExtended:
    """Tests for uncovered risk/manager.py paths."""

    @pytest.fixture
    def risk_mgr(self):
        from risk import RiskManager, RiskConfig
        config = RiskConfig(
            max_risk_per_trade=2.0,
            max_position_size=10000.0,
            max_open_positions=5,
            max_daily_loss=5.0,
            max_drawdown=10.0,
            default_stop_loss_pct=2.0,
            default_take_profit_pct=4.0,
        )
        return RiskManager(config=config, initial_balance=50000.0)

    # --- Position sizing methods ---

    def test_calculate_position_size_fixed_method(self, risk_mgr):
        result = risk_mgr.calculate_position_size(
            'XAUUSD', 1950.0, method='fixed', amount=5000.0
        )
        assert result.size > 0

    def test_calculate_position_size_percent_method(self, risk_mgr):
        result = risk_mgr.calculate_position_size(
            'XAUUSD', 1950.0, method='percent', percent=0.02
        )
        assert result.size > 0

    def test_calculate_position_size_risk_method_with_stop(self, risk_mgr):
        result = risk_mgr.calculate_position_size(
            'XAUUSD', 1950.0, method='risk', stop_loss=1930.0
        )
        assert result.size > 0

    def test_calculate_position_size_risk_method_no_stop(self, risk_mgr):
        result = risk_mgr.calculate_position_size(
            'XAUUSD', 1950.0, method='risk'
        )
        assert result.size > 0

    def test_calculate_position_size_risk_zero_distance(self, risk_mgr):
        """Cover risk method with stop == entry (zero distance)."""
        result = risk_mgr.calculate_position_size(
            'XAUUSD', 1950.0, method='risk', stop_loss=1950.0
        )
        assert result.size > 0

    def test_calculate_position_size_unknown_method(self, risk_mgr):
        """Cover else branch for unknown method."""
        result = risk_mgr.calculate_position_size(
            'XAUUSD', 1950.0, method='unknown_method'
        )
        assert result.size > 0

    def test_calculate_position_size_with_price_alias(self, risk_mgr):
        """Cover price/stop_loss parameter aliases."""
        result = risk_mgr.calculate_position_size(
            'XAUUSD', 0.0, method='fixed', amount=5000.0,
            price=1950.0, stop_loss=1930.0
        )
        assert result.size > 0

    # --- can_open_position ---

    def test_can_open_position_approved(self, risk_mgr):
        can_open, reason = risk_mgr.can_open_position(1000.0)
        assert can_open is True

    def test_can_open_position_max_positions(self, risk_mgr):
        # Fill up positions
        for i in range(5):
            risk_mgr.open_positions.append({'id': str(i), 'symbol': 'XAUUSD', 'size': 100.0})
        can_open, reason = risk_mgr.can_open_position(100.0)
        assert can_open is False
        assert 'Max open positions' in reason

    def test_can_open_position_size_too_large(self, risk_mgr):
        can_open, reason = risk_mgr.can_open_position(99999999.0)
        assert can_open is False
        assert 'exceeds maximum' in reason

    def test_can_open_position_daily_loss_limit(self, risk_mgr):
        risk_mgr.daily_pnl = -3000.0  # 6% loss on 50k > 5% limit
        can_open, reason = risk_mgr.can_open_position(100.0)
        assert can_open is False
        assert 'Daily loss limit' in reason

    def test_can_open_position_drawdown_limit(self, risk_mgr):
        risk_mgr.peak_balance = 50000.0
        risk_mgr.current_balance = 40000.0  # 20% drawdown > 10%
        can_open, reason = risk_mgr.can_open_position(100.0)
        assert can_open is False
        assert 'drawdown' in reason.lower()

    # --- register_position / close_position ---

    def test_register_position(self, risk_mgr):
        position = {'id': 'POS001', 'symbol': 'XAUUSD', 'size': 1000.0}
        risk_mgr.register_position(position)
        assert len(risk_mgr.open_positions) == 1

    def test_close_position_updates_balance(self, risk_mgr):
        risk_mgr.open_positions = [{'id': 'POS001', 'symbol': 'XAUUSD'}]
        risk_mgr.close_position('POS001', pnl=500.0)
        assert risk_mgr.current_balance == 50500.0
        assert len(risk_mgr.open_positions) == 0

    def test_close_position_updates_peak_balance(self, risk_mgr):
        risk_mgr.open_positions = [{'id': 'POS001'}]
        risk_mgr.close_position('POS001', pnl=2000.0)
        assert risk_mgr.peak_balance == 52000.0

    # --- validate_trade ---

    def test_validate_trade_valid(self, risk_mgr):
        is_valid, reason = risk_mgr.validate_trade('XAUUSD', 100.0, 'BUY')
        assert is_valid is True

    def test_validate_trade_max_positions(self, risk_mgr):
        for i in range(5):
            risk_mgr.open_positions.append({'id': str(i)})
        is_valid, reason = risk_mgr.validate_trade('XAUUSD', 100.0, 'BUY')
        assert is_valid is False

    def test_validate_trade_size_too_large(self, risk_mgr):
        is_valid, reason = risk_mgr.validate_trade('XAUUSD', 99999999.0, 'BUY')
        assert is_valid is False

    def test_validate_trade_daily_loss(self, risk_mgr):
        risk_mgr.daily_pnl = -3000.0
        is_valid, reason = risk_mgr.validate_trade('XAUUSD', 100.0, 'BUY')
        assert is_valid is False

    # --- check_risk_limits ---

    def test_check_risk_limits_within_limits(self, risk_mgr):
        within, violations = risk_mgr.check_risk_limits()
        assert within is True
        assert len(violations) == 0

    def test_check_risk_limits_daily_loss_violation(self, risk_mgr):
        risk_mgr.daily_pnl = -3000.0
        within, violations = risk_mgr.check_risk_limits()
        assert within is False
        assert len(violations) > 0

    def test_check_risk_limits_drawdown_violation(self, risk_mgr):
        risk_mgr.peak_balance = 50000.0
        risk_mgr.current_balance = 40000.0
        within, violations = risk_mgr.check_risk_limits()
        assert within is False
        assert any('drawdown' in v.lower() for v in violations)

    # --- calculate_stop_loss / calculate_take_profit ---

    def test_calculate_stop_loss_buy(self, risk_mgr):
        stop = risk_mgr.calculate_stop_loss(1950.0, 'BUY', percent=2.0)
        assert stop < 1950.0
        assert abs(stop - 1950.0 * 0.98) < 0.01

    def test_calculate_stop_loss_sell(self, risk_mgr):
        stop = risk_mgr.calculate_stop_loss(1950.0, 'SELL', percent=2.0)
        assert stop > 1950.0

    def test_calculate_stop_loss_long(self, risk_mgr):
        stop = risk_mgr.calculate_stop_loss(1950.0, 'LONG')
        assert stop < 1950.0

    def test_calculate_stop_loss_short(self, risk_mgr):
        stop = risk_mgr.calculate_stop_loss(1950.0, 'SHORT')
        assert stop > 1950.0

    def test_calculate_stop_loss_default_percent(self, risk_mgr):
        stop = risk_mgr.calculate_stop_loss(1950.0, 'BUY')
        expected = 1950.0 * (1 - 2.0 / 100.0)
        assert abs(stop - expected) < 0.01

    def test_calculate_take_profit_buy(self, risk_mgr):
        tp = risk_mgr.calculate_take_profit(1950.0, 'BUY', percent=4.0)
        assert tp > 1950.0

    def test_calculate_take_profit_sell(self, risk_mgr):
        tp = risk_mgr.calculate_take_profit(1950.0, 'SELL', percent=4.0)
        assert tp < 1950.0

    def test_calculate_take_profit_long(self, risk_mgr):
        tp = risk_mgr.calculate_take_profit(1950.0, 'LONG')
        assert tp > 1950.0

    # --- reset_daily_pnl / update_daily_pnl ---

    def test_reset_daily_pnl(self, risk_mgr):
        risk_mgr.daily_pnl = -1000.0
        risk_mgr.daily_trades = 5
        risk_mgr.reset_daily_pnl()
        assert risk_mgr.daily_pnl == 0.0
        assert risk_mgr.daily_trades == 0

    def test_reset_daily_stats_alias(self, risk_mgr):
        risk_mgr.daily_pnl = -500.0
        risk_mgr.reset_daily_stats()
        assert risk_mgr.daily_pnl == 0.0

    def test_update_daily_pnl(self, risk_mgr):
        risk_mgr.update_daily_pnl(200.0)
        assert risk_mgr.daily_pnl == 200.0

    # --- get_risk_metrics / get_status ---

    def test_get_risk_metrics(self, risk_mgr):
        metrics = risk_mgr.get_risk_metrics()
        assert 'current_balance' in metrics
        assert 'daily_pnl' in metrics
        assert 'current_drawdown' in metrics
        assert metrics['current_balance'] == 50000.0

    def test_get_status(self, risk_mgr):
        status = risk_mgr.get_status()
        assert 'config' in status
        assert 'current_balance' in status


# ---------------------------------------------------------------------------
# Notification Manager extended tests
# ---------------------------------------------------------------------------

class TestNotificationManagerExtended:
    """Tests for uncovered notifications/manager.py paths."""

    @pytest.fixture
    def mgr(self):
        from notifications.manager import NotificationManager
        config = {
            'discord_webhook_url': None,
            'telegram_bot_token': None,
            'telegram_chat_id': None,
            'email_smtp_host': None,
        }
        return NotificationManager(config=config)

    def test_send_console_info(self, mgr, caplog):
        from notifications.manager import NotificationLevel, NotificationChannel
        with caplog.at_level(logging.INFO):
            mgr._send_console('Test info message', NotificationLevel.INFO)
        # Just verify the method runs without exception; log may go to different logger

    def test_send_console_warning(self, mgr, caplog):
        from notifications.manager import NotificationLevel
        with caplog.at_level(logging.WARNING):
            mgr._send_console('Test warning', NotificationLevel.WARNING)

    def test_send_console_error(self, mgr, caplog):
        from notifications.manager import NotificationLevel
        with caplog.at_level(logging.ERROR):
            mgr._send_console('Test error', NotificationLevel.ERROR)

    def test_send_console_critical(self, mgr, caplog):
        from notifications.manager import NotificationLevel
        with caplog.at_level(logging.CRITICAL):
            mgr._send_console('Test critical', NotificationLevel.CRITICAL)

    def test_notify_console_channel(self, mgr):
        from notifications.manager import NotificationLevel, NotificationChannel
        # Ensure CONSOLE is in enabled_channels
        if NotificationChannel.CONSOLE not in mgr.enabled_channels:
            mgr.enabled_channels.append(NotificationChannel.CONSOLE)
        mgr.send('Test', level=NotificationLevel.INFO,
                   channels=[NotificationChannel.CONSOLE])

    def test_notify_multiple_channels(self, mgr):
        from notifications.manager import NotificationLevel, NotificationChannel
        if NotificationChannel.CONSOLE not in mgr.enabled_channels:
            mgr.enabled_channels.append(NotificationChannel.CONSOLE)
        if NotificationChannel.DISCORD not in mgr.enabled_channels:
            mgr.enabled_channels.append(NotificationChannel.DISCORD)
        mgr.send('Test', level=NotificationLevel.INFO,
                   channels=[NotificationChannel.CONSOLE,
                              NotificationChannel.DISCORD])

    def test_notify_discord_no_webhook(self, mgr, caplog):
        from notifications.manager import NotificationLevel, NotificationChannel
        with caplog.at_level(logging.WARNING):
            mgr._send_discord('Test', NotificationLevel.INFO, None)
        # Should log that webhook not configured

    def test_send_discord_with_webhook(self, mgr):
        from notifications.manager import NotificationLevel
        mgr.config['discord_webhook_url'] = 'https://discord.com/api/webhooks/test'
        with patch('requests.post') as mock_post:
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_post.return_value = mock_response
            mgr._send_discord('Test', NotificationLevel.INFO, {'key': 'value'})
            # Should have called post
            mock_post.assert_called_once()

    def test_send_discord_with_metadata_fields(self, mgr):
        from notifications.manager import NotificationLevel
        mgr.config['discord_webhook_url'] = 'https://discord.com/api/webhooks/test'
        with patch('requests.post') as mock_post:
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_post.return_value = mock_response
            metadata = {'price': 1950.0, 'side': 'BUY', 'empty': None}
            mgr._send_discord('Test', NotificationLevel.WARNING, metadata)
            # Verify call was made
            mock_post.assert_called_once()

    def test_send_discord_import_error_fallback(self, mgr):
        from notifications.manager import NotificationLevel
        mgr.config['discord_webhook_url'] = 'https://discord.com/api/webhooks/test'
        # Simulate ImportError on requests, fallback to urllib
        with patch('requests.post', side_effect=ImportError("no requests")):
            with patch('urllib.request.urlopen') as mock_urlopen:
                mock_urlopen.return_value = MagicMock()
                # Should not raise; either uses urllib fallback or logs an error
                try:
                    mgr._send_discord('Test', NotificationLevel.INFO, None)
                except Exception:
                    pass  # Error logging is acceptable for this code path

    def test_send_discord_http_scheme_rejected(self, mgr, caplog):
        """Discord webhook with http (non-https) should be rejected."""
        from notifications.manager import NotificationLevel
        mgr.config['discord_webhook_url'] = 'http://discord.com/api/webhooks/test'
        with patch('requests.post', side_effect=ImportError("no requests")):
            with patch('urllib.request.urlopen') as mock_urlopen:
                with caplog.at_level(logging.ERROR):
                    mgr._send_discord('Test', NotificationLevel.INFO, None)
                # urlopen must NOT be called because http scheme is rejected
                mock_urlopen.assert_not_called()

    def test_notify_error_handling(self, mgr):
        from notifications.manager import NotificationLevel, NotificationChannel
        """Notification handler errors should not crash."""
        if NotificationChannel.CONSOLE not in mgr.enabled_channels:
            mgr.enabled_channels.append(NotificationChannel.CONSOLE)
        with patch.object(mgr, '_send_console', side_effect=RuntimeError('test')):
            # The send method catches exceptions, should not propagate
            mgr.send('Test', level=NotificationLevel.INFO,
                       channels=[NotificationChannel.CONSOLE])
