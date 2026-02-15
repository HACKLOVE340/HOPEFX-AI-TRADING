"""
Mobile Applications Module

Provides mobile-optimized APIs and features.
"""

from .api import MobileAPI
from .auth import MobileAuth
from .push_notifications import PushNotificationManager
from .trading import MobileTradingEngine
from .analytics import MobileAnalytics

mobile_api = MobileAPI()
mobile_auth = MobileAuth()
push_notification_manager = PushNotificationManager()
mobile_trading_engine = MobileTradingEngine()
mobile_analytics = MobileAnalytics()

__all__ = [
    'MobileAPI',
    'MobileAuth',
    'PushNotificationManager',
    'MobileTradingEngine',
    'MobileAnalytics',
    'mobile_api',
    'mobile_auth',
    'push_notification_manager',
    'mobile_trading_engine',
    'mobile_analytics',
]

# Module metadata
__version__ = '1.0.0'
__author__ = 'HOPEFX Development Team'
__description__ = 'Mobile-optimized APIs with push notifications and trading features'
