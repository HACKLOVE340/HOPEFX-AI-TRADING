# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Crypto Wallet Manager

Manages hot/cold wallet separation and multi-currency support.
"""

import logging
from decimal import Decimal

logger = logging.getLogger(__name__)


class CryptoWalletManager:
    """Manages crypto wallets with hot/cold separation"""

    HOT_WALLET_THRESHOLD = Decimal("10000.00")  # USD

    def __init__(self):
        self.hot_wallet_balances = {
            "BTC": Decimal(0),
            "USDT": Decimal(0),
            "ETH": Decimal(0),
        }
        self.cold_wallet_balances = {
            "BTC": Decimal(0),
            "USDT": Decimal(0),
            "ETH": Decimal(0),
        }

    def get_balance(self, currency: str) -> dict:
        """Get wallet balances"""
        return {
            "currency": currency,
            "hot_wallet": float(self.hot_wallet_balances.get(currency, 0)),
            "cold_wallet": float(self.cold_wallet_balances.get(currency, 0)),
            "total": float(self.hot_wallet_balances.get(currency, 0) + self.cold_wallet_balances.get(currency, 0)),
        }

    def move_to_cold_storage(self, currency: str, amount: Decimal) -> bool:
        """Move funds from hot to cold wallet"""
        try:
            if self.hot_wallet_balances.get(currency, 0) >= amount:
                self.hot_wallet_balances[currency] -= amount
                self.cold_wallet_balances[currency] += amount
                logger.info("Moved %s %s to cold storage", amount, currency)

                return True
            return False
        except Exception as e:
            logger.error("Error moving to cold storage: %s", e)

            return False

    def move_to_hot_wallet(self, currency: str, amount: Decimal) -> bool:
        """Move funds from cold to hot wallet"""
        try:
            if self.cold_wallet_balances.get(currency, 0) >= amount:
                self.cold_wallet_balances[currency] -= amount
                self.hot_wallet_balances[currency] += amount
                logger.info("Moved %s %s to hot wallet", amount, currency)

                return True
            return False
        except Exception as e:
            logger.error("Error moving to hot wallet: %s", e)

            return False


crypto_wallet_manager = CryptoWalletManager()
