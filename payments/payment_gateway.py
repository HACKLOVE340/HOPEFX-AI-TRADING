"""
Payment Gateway Module

Unified interface for all payment methods (crypto and fintech).
Handles routing, fee calculation, currency conversion, and confirmation.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Dict, Optional, Any, List
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


class PaymentMethod(Enum):
    """Supported payment methods"""
    BITCOIN = "bitcoin"
    USDT = "usdt"
    ETHEREUM = "ethereum"
    PAYSTACK = "paystack"
    FLUTTERWAVE = "flutterwave"
    BANK_TRANSFER = "bank_transfer"


class PaymentStatus(Enum):
    """Payment status"""
    INITIATED = "initiated"
    PENDING = "pending"
    PROCESSING = "processing"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    EXPIRED = "expired"


@dataclass
class PaymentInfo:
    """Payment information"""
    payment_id: str
    user_id: str
    amount: Decimal
    currency: str
    method: PaymentMethod
    status: PaymentStatus
    wallet_type: str
    payment_details: Dict[str, Any]
    created_at: datetime
    expires_at: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None
    external_reference: Optional[str] = None


class PaymentGateway:
    """Unified payment gateway for all payment methods"""

    def __init__(self):
        self.payments: Dict[str, PaymentInfo] = {}
        self.exchange_rates = {
            'NGN_USD': Decimal('0.00129'),  # 1 NGN = 0.00129 USD (₦775 per $1)
            'USD_NGN': Decimal('775.00'),
            'BTC_USD': Decimal('45000.00'),  # Placeholder - should be real-time
            'ETH_USD': Decimal('2400.00'),
            'USDT_USD': Decimal('1.00')
        }

    def get_payment_fee(self, method: PaymentMethod, amount: Decimal) -> Decimal:
        """
        Calculate payment fee

        Args:
            method: Payment method
            amount: Amount

        Returns:
            Fee amount
        """
        if method == PaymentMethod.BITCOIN:
            return Decimal('0.0005')  # BTC (network + platform fee)
        elif method == PaymentMethod.USDT:
            return Decimal('2.00')  # USD (network + platform fee)
        elif method == PaymentMethod.ETHEREUM:
            return Decimal('0.005')  # ETH (network + platform fee)
        elif method == PaymentMethod.PAYSTACK:
            # 1.5% + ₦100 cap
            fee = amount * Decimal('0.015')
            ngn_fee = min(fee, Decimal('100.00'))  # Cap at ₦100
            return ngn_fee * self.exchange_rates['NGN_USD']  # Convert to USD
        elif method == PaymentMethod.FLUTTERWAVE:
            return amount * Decimal('0.014')  # 1.4%
        elif method == PaymentMethod.BANK_TRANSFER:
            return Decimal('50.00') * self.exchange_rates['NGN_USD']  # ₦50 flat

        return Decimal('0')

    def convert_currency(
        self,
        amount: Decimal,
        from_currency: str,
        to_currency: str
    ) -> Decimal:
        """
        Convert between currencies

        Args:
            amount: Amount to convert
            from_currency: Source currency
            to_currency: Target currency

        Returns:
            Converted amount
        """
        if from_currency == to_currency:
            return amount

        rate_key = f"{from_currency}_{to_currency}"
        if rate_key in self.exchange_rates:
            return amount * self.exchange_rates[rate_key]

        # Try reverse rate
        reverse_key = f"{to_currency}_{from_currency}"
        if reverse_key in self.exchange_rates:
            return amount / self.exchange_rates[reverse_key]

        logger.warning(f"No exchange rate for {from_currency} to {to_currency}")
        return amount

    def is_crypto_method(self, method: PaymentMethod) -> bool:
        """Check if method is crypto"""
        return method in [PaymentMethod.BITCOIN, PaymentMethod.USDT, PaymentMethod.ETHEREUM]

    def is_fintech_method(self, method: PaymentMethod) -> bool:
        """Check if method is fintech"""
        return method in [PaymentMethod.PAYSTACK, PaymentMethod.FLUTTERWAVE, PaymentMethod.BANK_TRANSFER]

    def initiate_deposit(
        self,
        user_id: str,
        amount: Decimal,
        currency: str,
        method: PaymentMethod,
        wallet_type: str = 'subscription'
    ) -> PaymentInfo:
        """
        Initiate a deposit

        Args:
            user_id: User ID
            amount: Deposit amount
            currency: Currency code
            method: Payment method
            wallet_type: Wallet type

        Returns:
            Payment information
        """
        try:
            payment_id = f"PAY-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

            # Calculate fees
            fee = self.get_payment_fee(method, amount)

            # Prepare payment details based on method
            payment_details = {
                'fee': float(fee),
                'net_amount': float(amount - fee)
            }

            if self.is_crypto_method(method):
                # Crypto payment details (address would be generated)
                payment_details.update({
                    'type': 'crypto',
                    'network': method.value,
                    'address': f"{method.value}_deposit_address_placeholder",
                    'confirmations_required': 3 if method == PaymentMethod.BITCOIN else 12
                })
            else:
                # Fintech payment details
                payment_details.update({
                    'type': 'fintech',
                    'provider': method.value,
                    'payment_link': f"https://{method.value}.example.com/pay/{payment_id}"
                })

            payment = PaymentInfo(
                payment_id=payment_id,
                user_id=user_id,
                amount=amount,
                currency=currency,
                method=method,
                status=PaymentStatus.INITIATED,
                wallet_type=wallet_type,
                payment_details=payment_details,
                created_at=datetime.utcnow()
            )

            self.payments[payment_id] = payment
            logger.info(f"Deposit initiated: {payment_id} for {user_id}")

            return payment

        except Exception as e:
            logger.error(f"Error initiating deposit: {e}")
            raise

    def process_withdrawal(
        self,
        user_id: str,
        amount: Decimal,
        currency: str,
        method: PaymentMethod,
        destination: Dict[str, Any]
    ) -> PaymentInfo:
        """
        Process a withdrawal

        Args:
            user_id: User ID
            amount: Withdrawal amount
            currency: Currency code
            method: Payment method
            destination: Destination details (address or bank account)

        Returns:
            Payment information
        """
        try:
            payment_id = f"WD-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

            # Calculate fees
            fee = self.get_payment_fee(method, amount)
            net_amount = amount - fee

            payment_details = {
                'fee': float(fee),
                'net_amount': float(net_amount),
                'destination': destination
            }

            if self.is_crypto_method(method):
                payment_details['type'] = 'crypto'
                payment_details['network'] = method.value
            else:
                payment_details['type'] = 'fintech'
                payment_details['provider'] = method.value

            payment = PaymentInfo(
                payment_id=payment_id,
                user_id=user_id,
                amount=amount,
                currency=currency,
                method=method,
                status=PaymentStatus.PENDING,
                wallet_type='subscription',  # Withdrawals from subscription wallet
                payment_details=payment_details,
                created_at=datetime.utcnow()
            )

            self.payments[payment_id] = payment
            logger.info(f"Withdrawal initiated: {payment_id} for {user_id}")

            return payment

        except Exception as e:
            logger.error(f"Error processing withdrawal: {e}")
            raise

    def confirm_payment(
        self,
        payment_id: str,
        external_reference: Optional[str] = None,
        status: PaymentStatus = PaymentStatus.CONFIRMED
    ) -> bool:
        """
        Confirm a payment

        Args:
            payment_id: Payment ID
            external_reference: External transaction reference
            status: New status

        Returns:
            Success boolean
        """
        try:
            payment = self.payments.get(payment_id)
            if not payment:
                logger.error(f"Payment not found: {payment_id}")
                return False

            payment.status = status
            payment.confirmed_at = datetime.utcnow()
            payment.external_reference = external_reference

            logger.info(f"Payment confirmed: {payment_id}")
            return True

        except Exception as e:
            logger.error(f"Error confirming payment: {e}")
            return False

    def get_payment(self, payment_id: str) -> Optional[PaymentInfo]:
        """Get payment by ID"""
        return self.payments.get(payment_id)

    def get_user_payments(self, user_id: str) -> List[PaymentInfo]:
        """Get all payments for a user"""
        return [p for p in self.payments.values() if p.user_id == user_id]

    def get_available_methods(self, user_id: str) -> List[str]:
        """
        Get available payment methods for user

        Args:
            user_id: User ID

        Returns:
            List of available method names
        """
        # In production, this would check user's KYC, region, etc.
        return [method.value for method in PaymentMethod]

    def get_statistics(self) -> Dict:
        """Get payment statistics"""
        total_payments = len(self.payments)

        if total_payments == 0:
            return {
                'total_payments': 0,
                'by_method': {},
                'by_status': {},
                'total_volume': 0.0
            }

        by_method = {}
        by_status = {}
        total_volume = Decimal('0')

        for payment in self.payments.values():
            # Count by method
            method_key = payment.method.value
            by_method[method_key] = by_method.get(method_key, 0) + 1

            # Count by status
            status_key = payment.status.value
            by_status[status_key] = by_status.get(status_key, 0) + 1

            # Sum volume
            if payment.status == PaymentStatus.CONFIRMED:
                total_volume += payment.amount

        return {
            'total_payments': total_payments,
            'by_method': by_method,
            'by_status': by_status,
            'total_volume': float(total_volume)
        }


# Global payment gateway instance
payment_gateway = PaymentGateway()
