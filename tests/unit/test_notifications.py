"""
Tests for Notification Manager
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from notifications.manager import (
    NotificationManager,
    NotificationLevel,
    NotificationChannel
)


class TestNotificationManager:
    """Test notification manager functionality"""

    def test_manager_initialization(self):
        """Test notification manager initialization"""
        config = {
            'discord_enabled': True,
            'telegram_enabled': True,
            'email_enabled': True
        }
        manager = NotificationManager(config)
        
        assert NotificationChannel.CONSOLE in manager.enabled_channels
        assert NotificationChannel.DISCORD in manager.enabled_channels
        assert NotificationChannel.TELEGRAM in manager.enabled_channels
        assert NotificationChannel.EMAIL in manager.enabled_channels

    def test_console_notification(self):
        """Test console notification"""
        manager = NotificationManager()
        
        # Should not raise exception
        manager.send(
            message="Test message",
            level=NotificationLevel.INFO,
            channels=[NotificationChannel.CONSOLE]
        )
        
        assert len(manager.notification_history) == 1
        assert manager.notification_history[0]['message'] == "Test message"

    def test_discord_notification_without_config(self):
        """Test Discord notification without webhook URL"""
        config = {'discord_enabled': True}
        manager = NotificationManager(config)
        
        # Should not raise exception, just log warning
        manager.send(
            message="Test Discord message",
            level=NotificationLevel.INFO,
            channels=[NotificationChannel.DISCORD]
        )

    @patch('requests.post')
    def test_discord_notification_with_config(self, mock_post):
        """Test Discord notification with webhook URL"""
        config = {
            'discord_enabled': True,
            'discord_webhook_url': 'https://discord.com/api/webhooks/test'
        }
        manager = NotificationManager(config)
        
        # Setup mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response
        
        manager.send(
            message="Test Discord message",
            level=NotificationLevel.WARNING,
            channels=[NotificationChannel.DISCORD],
            metadata={'trade': 'EUR_USD', 'action': 'BUY'}
        )
        
        # Verify requests.post was called
        assert mock_post.called
        call_args = mock_post.call_args
        assert call_args is not None
        # Check that the request was made to the webhook URL
        assert call_args[0][0] == 'https://discord.com/api/webhooks/test'
        # Verify the payload contains the message
        payload = call_args[1]['json']
        assert 'embeds' in payload
        assert len(payload['embeds']) > 0
        assert payload['embeds'][0]['description'] == "Test Discord message"

    def test_telegram_notification_without_config(self):
        """Test Telegram notification without bot token"""
        config = {'telegram_enabled': True}
        manager = NotificationManager(config)
        
        # Should not raise exception, just log warning
        manager.send(
            message="Test Telegram message",
            level=NotificationLevel.ERROR,
            channels=[NotificationChannel.TELEGRAM]
        )

    @patch('urllib.request.urlopen')
    def test_telegram_notification_with_config(self, mock_urlopen):
        """Test Telegram notification with bot token and chat ID"""
        config = {
            'telegram_enabled': True,
            'telegram_bot_token': 'test_bot_token',
            'telegram_chat_id': 'test_chat_id'
        }
        manager = NotificationManager(config)
        
        mock_urlopen.return_value.__enter__ = Mock()
        mock_urlopen.return_value.__exit__ = Mock()
        
        manager.send(
            message="Test Telegram message",
            level=NotificationLevel.CRITICAL,
            channels=[NotificationChannel.TELEGRAM],
            metadata={'symbol': 'BTC/USD', 'price': 50000}
        )
        
        # Verify urlopen was called
        assert mock_urlopen.called

    def test_email_notification_without_config(self):
        """Test email notification without SMTP credentials"""
        config = {'email_enabled': True}
        manager = NotificationManager(config)
        
        # Should not raise exception, just log warning
        manager.send(
            message="Test email message",
            level=NotificationLevel.INFO,
            channels=[NotificationChannel.EMAIL]
        )

    @patch('smtplib.SMTP')
    def test_email_notification_with_config(self, mock_smtp):
        """Test email notification with SMTP credentials"""
        config = {
            'email_enabled': True,
            'smtp_username': 'test@example.com',
            'smtp_password': 'password',
            'smtp_to': 'recipient@example.com'
        }
        manager = NotificationManager(config)
        
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__ = Mock(return_value=mock_server)
        mock_smtp.return_value.__exit__ = Mock()
        
        manager.send(
            message="Test email message",
            level=NotificationLevel.WARNING,
            channels=[NotificationChannel.EMAIL],
            metadata={'alert': 'High volatility detected'}
        )
        
        # Verify SMTP methods were called
        assert mock_server.starttls.called
        assert mock_server.login.called
        assert mock_server.sendmail.called

    def test_trade_notification(self):
        """Test trade notification helper"""
        manager = NotificationManager()
        
        manager.notify_trade(
            action="BUY",
            symbol="EUR_USD",
            quantity=10000,
            price=1.1850,
            pnl=None
        )
        
        assert len(manager.notification_history) == 1
        notification = manager.notification_history[0]
        assert "BUY" in notification['message']
        assert "EUR_USD" in notification['message']
        assert notification['metadata']['action'] == "BUY"

    def test_signal_notification(self):
        """Test signal notification helper"""
        manager = NotificationManager()
        
        manager.notify_signal(
            strategy="MA Crossover",
            signal_type="SELL",
            symbol="GBP_USD",
            price=1.3500,
            confidence=0.85
        )
        
        assert len(manager.notification_history) == 1
        notification = manager.notification_history[0]
        assert "SELL" in notification['message']
        assert "GBP_USD" in notification['message']
        assert notification['metadata']['confidence'] == 0.85

    def test_notification_levels(self):
        """Test different notification levels"""
        manager = NotificationManager()
        
        for level in [NotificationLevel.INFO, NotificationLevel.WARNING,
                      NotificationLevel.ERROR, NotificationLevel.CRITICAL]:
            manager.send(
                message=f"Test {level.value} message",
                level=level
            )
        
        assert len(manager.notification_history) == 4

    def test_notification_with_metadata(self):
        """Test notification with metadata"""
        manager = NotificationManager()
        
        metadata = {
            'strategy': 'RSI Strategy',
            'symbol': 'EUR_USD',
            'signal': 'BUY',
            'confidence': 0.92,
            'price': 1.1850
        }
        
        manager.send(
            message="Trading signal generated",
            level=NotificationLevel.INFO,
            metadata=metadata
        )
        
        notification = manager.notification_history[0]
        assert notification['metadata'] == metadata

    def test_multiple_channels(self):
        """Test sending to multiple channels"""
        config = {
            'discord_enabled': True,
            'telegram_enabled': True
        }
        manager = NotificationManager(config)
        
        manager.send(
            message="Multi-channel test",
            level=NotificationLevel.INFO
        )
        
        # Should send to all enabled channels (console, discord, telegram)
        assert len(manager.notification_history) == 1
