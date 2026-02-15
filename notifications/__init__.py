"""
Notifications Module

This module provides notification and alerting functionality.

Notification channels:
- Discord (webhooks and bot)
- Telegram (bot API)
- Email (SMTP)
- SMS (Twilio)
- Slack (webhooks)

Notification types:
- Trade execution alerts
- Risk warnings
- System errors
- Performance reports
- Daily summaries
"""

from .manager import (
    NotificationManager,
    NotificationLevel,
    NotificationChannel,
)

__all__ = [
    'NotificationManager',
    'NotificationLevel',
    'NotificationChannel',
]

# Module metadata
__version__ = '1.0.0'
__author__ = 'HOPEFX Development Team'
__description__ = 'Multi-channel notification system with Discord, Telegram, Email, SMS support'
