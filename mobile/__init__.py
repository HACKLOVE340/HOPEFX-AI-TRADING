# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Mobile Applications Module

Provides mobile-optimised APIs and features.

All classes accept an optional app_state parameter for wiring to real
data sources (broker, db, orchestrator). Without wiring they operate in
a safe degraded mode — no mocks, no synthetic data.
"""

from .analytics import MobileAnalytics
from .api import MobileAPI
from .auth import MobileAuth
from .push_notifications import PushNotificationManager
from .trading import MobileTradingEngine

# Unwired singletons — callers should instantiate with app_state for production
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


def create_wired_mobile(app_state: object) -> dict:
    """
    Create fully-wired mobile service instances from a live app_state.

    Usage:
        services = create_wired_mobile(app_state)
        engine   = services["trading_engine"]
        analytics = services["analytics"]
    """
    return {
        "trading_engine": MobileTradingEngine(app_state=app_state),
        "analytics": MobileAnalytics(app_state=app_state, enable_background_flush=True),
    }


__all__ = [
    "MobileAPI",
    "MobileAnalytics",
    "MobileAuth",
    "MobileTradingEngine",
    "PushNotificationManager",
    "create_wired_mobile",
    "mobile_analytics",
    "mobile_api",
    "mobile_auth",
    "mobile_trading_engine",
    "push_notification_manager",
]

__version__ = "2.0.0"
__author__ = "HOPEFX Development Team"
__description__ = "Mobile-optimised APIs with real broker/DB wiring"
