"""
Marketplace and copy trading module.
"""

from src.marketplace.licensing import LicenseManager
from src.marketplace.replication import CopyTradingEngine
from src.marketplace.payments import PaymentProcessor

__all__ = ["LicenseManager", "CopyTradingEngine", "PaymentProcessor"]
