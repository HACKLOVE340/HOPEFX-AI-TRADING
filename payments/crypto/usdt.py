# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
USDT Payment Integration

Handles USDT deposits and withdrawals on TRC20 (TRON) and ERC20 (Ethereum) networks.
"""

import hashlib
import logging
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import ClassVar

logger = logging.getLogger(__name__)


class USDTNetwork(Enum):
    """USDT networks"""

    TRC20 = "trc20"  # TRON
    ERC20 = "erc20"  # Ethereum


class USDTClient:
    """USDT payment client supporting multiple networks"""

    REQUIRED_CONFIRMATIONS: ClassVar[dict] = {USDTNetwork.TRC20: 19, USDTNetwork.ERC20: 12}
    MIN_DEPOSIT = Decimal("10.00")  # USD
    NETWORK_FEE = Decimal("2.00")  # USD

    def __init__(self):
        self.addresses: dict[str, dict] = {}
        self.transactions: dict[str, dict] = {}

    def generate_deposit_address(self, user_id: str, network: USDTNetwork = USDTNetwork.TRC20) -> dict:
        """Generate USDT deposit address"""
        try:
            # Generate network-specific address
            if network == USDTNetwork.TRC20:
                address_hash = hashlib.sha256(f"TRC20{user_id}".encode()).hexdigest()
                address = f"T{address_hash[:33]}"  # TRON address format
            else:  # ERC20
                address_hash = hashlib.sha256(f"ERC20{user_id}".encode()).hexdigest()
                address = f"0x{address_hash[:40]}"  # Ethereum address format

            self.addresses[address] = {
                "user_id": user_id,
                "network": network.value,
                "created_at": datetime.now(UTC).isoformat(),
            }

            logger.info("Generated USDT %s address for user %s", network.value, user_id)

            return {
                "address": address,
                "network": network.value,
                "qr_code": f"usdt:{address}?network={network.value}",
                "min_deposit": float(self.MIN_DEPOSIT),
                "confirmations_required": self.REQUIRED_CONFIRMATIONS[network],
            }
        except Exception as e:
            logger.error("Error generating USDT address: %s", e)

            raise

    def process_deposit(
        self,
        user_id: str,
        amount: Decimal,
        tx_hash: str,
        network: USDTNetwork,
        confirmations: int = 0,
    ) -> dict | None:
        """Process USDT deposit"""
        try:
            if amount < self.MIN_DEPOSIT:
                logger.warning("USDT deposit below minimum: %s", amount)

                return None

            required_conf = self.REQUIRED_CONFIRMATIONS[network]
            status = "confirmed" if confirmations >= required_conf else "pending"

            transaction = {
                "tx_hash": tx_hash,
                "user_id": user_id,
                "amount": float(amount),
                "network": network.value,
                "confirmations": confirmations,
                "status": status,
                "created_at": datetime.now(UTC).isoformat(),
            }

            self.transactions[tx_hash] = transaction
            logger.info("USDT deposit processed: %s - %s USDT on %s", tx_hash, amount, network.value)

            return transaction
        except Exception as e:
            logger.error("Error processing USDT deposit: %s", e)

            return None

    def process_withdrawal(self, user_id: str, amount: Decimal, destination: str, network: USDTNetwork) -> dict:
        """Process USDT withdrawal"""
        try:
            total_fee = self.NETWORK_FEE
            net_amount = amount - total_fee

            if net_amount <= 0:
                raise ValueError("Amount too small after fees")

            tx_hash = hashlib.sha256(f"USDT{user_id}{amount}{destination}".encode()).hexdigest()

            return {
                "tx_hash": tx_hash,
                "amount": float(amount),
                "fee": float(total_fee),
                "net_amount": float(net_amount),
                "destination": destination,
                "network": network.value,
                "status": "broadcasting",
            }
        except Exception as e:
            logger.error("Error processing USDT withdrawal: %s", e)

            raise


usdt_client = USDTClient()
