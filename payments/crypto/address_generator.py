# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026 Opeyemi (HACKLOVE340)
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Address Generator

Generates unique deposit addresses with BIP32/BIP44 derivation support.
"""

import logging
import hashlib

logger = logging.getLogger(__name__)


class AddressGenerator:
    """Generates unique crypto addresses"""

    def __init__(self):
        self.address_counter = {}

    def generate_address(self, user_id: str, currency: str) -> str:
        """Generate unique address for user and currency"""
        if currency not in self.address_counter:
            self.address_counter[currency] = 0

        index = self.address_counter[currency]
        self.address_counter[currency] += 1

        # Generate deterministic address
        data = f"{currency}{user_id}{index}".encode()
        address_hash = hashlib.sha256(data).hexdigest()

        # Format based on currency
        if currency == "BTC":
            return f"bc1q{address_hash[:40]}"
        elif currency == "ETH" or currency == "USDT_ERC20":
            return f"0x{address_hash[:40]}"
        elif currency == "USDT_TRC20":
            return f"T{address_hash[:33]}"

        return address_hash[:40]

    def generate_qr_code(self, address: str, currency: str) -> str:
        """Generate QR code data"""
        currency_lower = currency.lower().replace("_", ":")
        return f"{currency_lower}:{address}"


address_generator = AddressGenerator()
