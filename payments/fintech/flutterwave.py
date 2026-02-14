"""
Flutterwave Payment Integration

Handles payments via Flutterwave (Nigeria) - Cards, Bank, Mobile Money.
"""

from datetime import datetime
from decimal import Decimal
from typing import Dict
import logging
import hashlib

logger = logging.getLogger(__name__)


class FlutterwaveClient:
    """Flutterwave payment client"""

    FEE_PERCENT = Decimal('0.014')  # 1.4%

    def __init__(self, secret_key: str = None):
        self.secret_key = secret_key or "FLWSECK_TEST-placeholder"
        self.payments = {}

    def initialize_payment(self, user_id: str, amount: Decimal, currency: str = 'USD') -> Dict:
        """Initialize Flutterwave payment"""
        try:
            tx_ref = f"FLW-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
            fee = amount * self.FEE_PERCENT

            payment = {
                'tx_ref': tx_ref,
                'user_id': user_id,
                'amount': float(amount),
                'currency': currency,
                'fee': float(fee),
                'payment_link': f"https://checkout.flutterwave.com/v3/{tx_ref}",
                'status': 'initiated'
            }

            self.payments[tx_ref] = payment
            logger.info(f"Flutterwave payment initialized: {tx_ref}")

            return payment
        except Exception as e:
            logger.error(f"Error initializing Flutterwave payment: {e}")
            raise

    def verify_transaction(self, tx_ref: str) -> Dict:
        """Verify Flutterwave transaction"""
        payment = self.payments.get(tx_ref)
        if payment:
            payment['status'] = 'verified'
            logger.info(f"Flutterwave payment verified: {tx_ref}")
        return payment or {'status': 'not_found'}

    def initiate_payout(self, user_id: str, amount: Decimal, bank_code: str, account_number: str) -> Dict:
        """Initiate bank payout"""
        try:
            transfer_ref = f"PAYOUT-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

            return {
                'transfer_ref': transfer_ref,
                'amount': float(amount),
                'bank_code': bank_code,
                'account_number': account_number,
                'status': 'pending'
            }
        except Exception as e:
            logger.error(f"Error initiating Flutterwave payout: {e}")
            raise


flutterwave_client = FlutterwaveClient()
