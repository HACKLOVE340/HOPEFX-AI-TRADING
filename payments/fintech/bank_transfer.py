# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Bank Transfer Integration

Direct bank transfer handling for Nigerian banks.
"""

import logging
from datetime import datetime, timezone
UTC = timezone.utc
from decimal import Decimal

logger = logging.getLogger(__name__)


class BankTransferClient:
    """Bank transfer client for Nigerian banks"""

    FLAT_FEE_NGN = Decimal("50.00")  # ₦50

    def __init__(self):
        self.transfers = {}
        self.nigerian_banks = {
            "058": "GTBank",
            "011": "First Bank",
            "033": "United Bank for Africa",
            "044": "Access Bank",
            "057": "Zenith Bank",
        }

    def validate_account(self, bank_code: str, account_number: str) -> dict:
        """Validate bank account"""
        try:
            bank_name = self.nigerian_banks.get(bank_code, "Unknown Bank")

            # Simplified validation
            if len(account_number) != 10:
                return {"valid": False, "message": "Invalid account number length"}

            return {
                "valid": True,
                "account_number": account_number,
                "account_name": f"Account Holder {account_number[-4:]}",
                "bank_code": bank_code,
                "bank_name": bank_name,
            }
        except Exception as e:
            logger.error("Error validating account: %s", e)

            raise

    def initiate_transfer(self, user_id: str, amount: Decimal, bank_code: str, account_number: str) -> dict:
        """Initiate bank transfer"""
        try:
            transfer_id = f"BT-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"

            # Validate account
            validation = self.validate_account(bank_code, account_number)
            if not validation["valid"]:
                raise ValueError(validation["message"])

            # Calculate fee
            fee_usd = self.FLAT_FEE_NGN / Decimal("775.00")  # Convert to USD

            transfer = {
                "transfer_id": transfer_id,
                "user_id": user_id,
                "amount": float(amount),
                "fee": float(fee_usd),
                "net_amount": float(amount - fee_usd),
                "bank_code": bank_code,
                "bank_name": validation["bank_name"],
                "account_number": account_number,
                "account_name": validation["account_name"],
                "status": "pending",
                "created_at": datetime.now(UTC).isoformat(),
            }

            self.transfers[transfer_id] = transfer
            logger.info("Bank transfer initiated: %s", transfer_id)

            return transfer
        except Exception as e:
            logger.error("Error initiating bank transfer: %s", e)

            raise

    def get_transfer_status(self, transfer_id: str) -> dict:
        """Get transfer status"""
        return self.transfers.get(transfer_id, {"status": "not_found"})


bank_transfer_client = BankTransferClient()
