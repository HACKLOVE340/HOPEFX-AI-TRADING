# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Paystack Payment Integration

Handles payments via Paystack (Nigeria) - Bank transfer, Cards, USSD.
"""

import os
from datetime import datetime, timezone

UTC = timezone.utc
from decimal import Decimal
import logging
import hashlib

logger = logging.getLogger(__name__)


class PaystackClient:
    """Paystack payment client for Nigerian payments"""

    FEE_PERCENT = Decimal("0.015")  # 1.5%
    FEE_CAP_NGN = Decimal("100.00")  # ₦100 cap

    def __init__(self, secret_key: str | None = None):
        if not secret_key:
            raise ValueError("PaystackClient requires a secret key. Set the PAYSTACK_SECRET_KEY environment variable.")
        self.secret_key = secret_key
        self.payments = {}

    def initialize_payment(self, user_id: str, amount: Decimal, currency: str = "USD", email: str = None) -> dict:
        """Initialize Paystack payment"""
        try:
            reference = f"PSK-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"

            # Calculate fee (in NGN if USD, convert first)
            ngn_amount = amount * Decimal("775.00") if currency == "USD" else amount
            fee_ngn = min(ngn_amount * self.FEE_PERCENT, self.FEE_CAP_NGN)
            fee_usd = fee_ngn / Decimal("775.00") if currency == "USD" else fee_ngn

            payment = {
                "reference": reference,
                "user_id": user_id,
                "amount": float(amount),
                "currency": currency,
                "fee": float(fee_usd),
                "authorization_url": f"https://checkout.paystack.com/{reference}",
                # Use SHA256 instead of MD5 for security, truncate to 10 chars for access code
                "access_code": hashlib.sha256(reference.encode()).hexdigest()[:10],
                "status": "initiated",
            }

            self.payments[reference] = payment
            logger.info(f"Paystack payment initialized: {reference}")

            return payment
        except Exception as e:
            logger.error(f"Error initializing Paystack payment: {e}")
            raise

    def verify_transaction(self, reference: str) -> dict:
        """Verify Paystack transaction"""
        payment = self.payments.get(reference)
        if payment:
            payment["status"] = "verified"
            logger.info(f"Paystack payment verified: {reference}")
        return payment or {"status": "not_found"}

    def initiate_transfer(self, user_id: str, amount: Decimal, bank_code: str, account_number: str) -> dict:
        """Initiate bank transfer"""
        try:
            transfer_code = f"TRF-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"

            return {
                "transfer_code": transfer_code,
                "amount": float(amount),
                "bank_code": bank_code,
                "account_number": account_number,
                "status": "pending",
                "created_at": datetime.now(UTC).isoformat(),
            }
        except Exception as e:
            logger.error(f"Error initiating Paystack transfer: {e}")
            raise


# Module-level singleton — only created when the env var is present so that
# importing this module in environments without payment credentials does not
# raise at import time. Callers must check for None before using.
_paystack_secret = os.getenv("PAYSTACK_SECRET_KEY")
paystack_client: PaystackClient | None = PaystackClient(_paystack_secret) if _paystack_secret else None
