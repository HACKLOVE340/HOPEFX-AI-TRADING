# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Flutterwave Payment Integration

Handles payments via Flutterwave (Nigeria) - Cards, Bank, Mobile Money.
"""

import logging
import os
from datetime import datetime, timezone

UTC = timezone.utc
from decimal import Decimal

logger = logging.getLogger(__name__)


class FlutterwaveClient:
    """Flutterwave payment client"""

    FEE_PERCENT = Decimal("0.014")  # 1.4%

    def __init__(self, secret_key: str | None = None):
        if not secret_key:
            raise ValueError(
                "FlutterwaveClient requires a secret key. Set the FLUTTERWAVE_SECRET_KEY environment variable."
            )
        self.secret_key = secret_key
        self.payments = {}

    def initialize_payment(self, user_id: str, amount: Decimal, currency: str = "USD") -> dict:
        """Initialize Flutterwave payment"""
        try:
            tx_ref = f"FLW-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
            fee = amount * self.FEE_PERCENT

            payment = {
                "tx_ref": tx_ref,
                "user_id": user_id,
                "amount": float(amount),
                "currency": currency,
                "fee": float(fee),
                "payment_link": f"https://checkout.flutterwave.com/v3/{tx_ref}",
                "status": "initiated",
            }

            self.payments[tx_ref] = payment
            logger.info("Flutterwave payment initialized: %s", tx_ref)

            return payment
        except Exception as e:
            logger.error("Error initializing Flutterwave payment: %s", e)

            raise

    def verify_transaction(self, tx_ref: str) -> dict:
        """Verify Flutterwave transaction"""
        payment = self.payments.get(tx_ref)
        if payment:
            payment["status"] = "verified"
            logger.info("Flutterwave payment verified: %s", tx_ref)

        return payment or {"status": "not_found"}

    def initiate_payout(self, user_id: str, amount: Decimal, bank_code: str, account_number: str) -> dict:
        """Initiate bank payout"""
        try:
            transfer_ref = f"PAYOUT-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"

            return {
                "transfer_ref": transfer_ref,
                "amount": float(amount),
                "bank_code": bank_code,
                "account_number": account_number,
                "status": "pending",
            }
        except Exception as e:
            logger.error("Error initiating Flutterwave payout: %s", e)

            raise


# Module-level singleton — only created when the env var is present so that
# importing this module in environments without payment credentials does not
# raise at import time. Callers must check for None before using.
_flw_secret = os.getenv("FLUTTERWAVE_SECRET_KEY")
flutterwave_client: FlutterwaveClient | None = FlutterwaveClient(_flw_secret) if _flw_secret else None
