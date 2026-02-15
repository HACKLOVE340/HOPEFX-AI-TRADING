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

Server-side alert engine:
- Persistent server-side alerts
- Complex condition monitoring
- Multiple condition types (price, indicator, volume)
- Alert expiration and cooldown
- Multi-channel notifications
"""

from .manager import (
    NotificationManager,
    NotificationLevel,
    NotificationChannel,
)
from .alert_engine import (
    AlertEngine,
    Alert,
    AlertCondition,
    AlertConditionType,
    AlertPriority,
    AlertStatus,
    AlertTrigger,
    get_alert_engine,
    create_alert_router,
)

__all__ = [
    'NotificationManager',
    'NotificationLevel',
    'NotificationChannel',
    # Alert engine
    'AlertEngine',
    'Alert',
    'AlertCondition',
    'AlertConditionType',
    'AlertPriority',
    'AlertStatus',
    'AlertTrigger',
    'get_alert_engine',
    'create_alert_router',
]

# Module metadata
__version__ = '2.0.0'
__author__ = 'HOPEFX Development Team'
__description__ = 'Multi-channel notification system with Discord, Telegram, Email, SMS support and server-side alert engine'
