# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Multi-Gateway Payment Processor
- Stripe integration
- Crypto payments
- Bank transfers
"""

import logging
import os
import uuid
from datetime import datetime, timezone

UTC = timezone.utc
from decimal import Decimal
from enum import Enum

logger = logging.getLogger(__name__)


class PaymentMethod(Enum):
    """Payment methods"""

    CREDIT_CARD = "credit_card"
    CRYPTO = "crypto"
    BANK_TRANSFER = "bank_transfer"
    PAYPAL = "paypal"
    STRIPE = "stripe"


class PaymentStatus(Enum):
    """Payment status"""

    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    REFUNDED = "refunded"


class Payment:
    """Payment transaction"""

    def __init__(self, amount: float, method: PaymentMethod, user_id: str, description: str = ""):
        self.id = str(uuid.uuid4())
        self.amount = amount
        self.method = method
        self.user_id = user_id
        self.description = description
        self.status = PaymentStatus.PENDING
        self.created_at = datetime.now(UTC)
        self.completed_at = None
        self.transaction_id = None


class PaymentGateway:
    """Main payment gateway"""

    def __init__(self):
        self.payments: dict[str, Payment] = {}

    def create_payment(self, amount: float, method: PaymentMethod, user_id: str, description: str = "") -> Payment:
        """Create new payment"""
        payment = Payment(amount, method, user_id, description)
        self.payments[payment.id] = payment
        logger.info("Payment created: %s", payment.id)

        return payment

    def process_payment(self, payment_id: str) -> bool:
        """Process payment"""
        if payment_id not in self.payments:
            return False

        payment = self.payments[payment_id]
        payment.status = PaymentStatus.PROCESSING

        try:
            if payment.method == PaymentMethod.STRIPE:
                self._process_stripe(payment)
            elif payment.method == PaymentMethod.CRYPTO:
                self._process_crypto(payment)
            elif payment.method == PaymentMethod.BANK_TRANSFER:
                self._process_bank(payment)
            else:
                raise NotImplementedError(
                    f"Payment method {payment.method.value!r} is not implemented. "
                    "Payment cannot be collected. Do not mark as success."
                )

            payment.status = PaymentStatus.SUCCESS
            payment.completed_at = datetime.now(UTC)
            logger.info("Payment successful: %s", payment_id)

            return True

        except Exception as e:
            payment.status = PaymentStatus.FAILED
            logger.error("Payment failed: %s", e)

            return False

    def _process_stripe(self, payment: Payment) -> None:
        """Process Stripe payment via monetization.stripe_integration."""
        try:
            import stripe as _stripe  # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError(
                "stripe package is required for Stripe payments. Install it with: pip install stripe"
            ) from exc

        secret_key = os.getenv("STRIPE_SECRET_KEY", "")
        if not secret_key:
            raise RuntimeError("STRIPE_SECRET_KEY is not set. Configure it in .env before accepting Stripe payments.")

        _stripe.api_key = secret_key
        intent = _stripe.PaymentIntent.create(
            amount=int(payment.amount * 100),  # Stripe expects cents
            currency="usd",
            metadata={
                "hopefx_payment_id": payment.id,
                "user_id": payment.user_id,
                "description": payment.description,
            },
        )
        payment.transaction_id = intent["id"]
        logger.info(
            "Stripe PaymentIntent created: %s for payment %s",
            intent["id"],
            payment.id,
        )

    def _process_crypto(self, payment: Payment) -> None:
        """Process crypto payment via payments.crypto.address_generator.

        Assigns a unique deposit address for the user.  The currency is read
        from payment.description (e.g. "BTC", "ETH", "USDT_ERC20").
        Defaults to "BTC" when description is blank.
        """
        from payments.crypto.address_generator import address_generator

        currency = (payment.description or "BTC").strip().upper()
        deposit_address = address_generator.generate_address(
            user_id=payment.user_id,
            currency=currency,
        )
        payment.transaction_id = deposit_address
        logger.info(
            "Crypto deposit address assigned: %s (%s) for payment %s",
            deposit_address,
            currency,
            payment.id,
        )

    def _process_bank(self, payment: Payment) -> None:
        """Process bank transfer via payments.fintech.bank_transfer."""
        from payments.fintech.bank_transfer import bank_transfer_client

        # bank_code and account_number are passed via payment.description
        # as "bank_code:account_number" when this method is called.
        parts = (payment.description or "").split(":")
        if len(parts) < 2:
            raise ValueError(
                f"Bank transfer requires description in format 'bank_code:account_number'. Got: '{payment.description}'"
            )
        bank_code, account_number = parts[0].strip(), parts[1].strip()

        result = bank_transfer_client.initiate_transfer(
            user_id=payment.user_id,
            amount=Decimal(str(payment.amount)),
            bank_code=bank_code,
            account_number=account_number,
        )
        payment.transaction_id = result["transfer_id"]
        logger.info(
            "Bank transfer initiated: %s for payment %s",
            result["transfer_id"],
            payment.id,
        )

    def refund_payment(self, payment_id: str) -> bool:
        """Refund payment"""
        if payment_id not in self.payments:
            return False

        payment = self.payments[payment_id]
        if payment.status == PaymentStatus.SUCCESS:
            payment.status = PaymentStatus.REFUNDED
            logger.info("Payment refunded: %s", payment_id)

            return True

        return False

    def get_payment_status(self, payment_id: str) -> PaymentStatus | None:
        """Get payment status"""
        if payment_id in self.payments:
            return self.payments[payment_id].status
        return None


# Alias for backwards compatibility
PaymentInfo = Payment
payment_gateway = PaymentGateway()
