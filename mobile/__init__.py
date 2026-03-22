"""
Mobile Applications Module

Provides mobile-optimized APIs and features.
"""

from .api import MobileAPI
from .auth import MobileAuth
from .push_notifications import PushNotificationManager
from .trading import MobileTradingEngine
from .analytics import MobileAnalytics

try:
    mobile_api = MobileAPI()
except Exception:
    mobile_api = None
try:
    mobile_auth = MobileAuth()
except Exception:
    mobile_auth = None
try:
    push_notification_manager = PushNotificationManager()
except Exception:
    push_notification_manager = None
try:
    mobile_trading_engine = MobileTradingEngine()
except Exception:
    mobile_trading_engine = None
try:
    mobile_analytics = MobileAnalytics()
except Exception:
    mobile_analytics = None

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
