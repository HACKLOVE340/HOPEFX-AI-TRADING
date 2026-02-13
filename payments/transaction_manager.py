"""
Transaction Manager Module

Handles complete transaction lifecycle including recording, validation,
status tracking, reversal, and reporting.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
import logging
import uuid

logger = logging.getLogger(__name__)


class TransactionType(Enum):
    """Transaction types"""
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    PAYMENT = "payment"
    COMMISSION = "commission"
    TRANSFER = "transfer"
    REFUND = "refund"


class TransactionStatus(Enum):
    """Transaction status"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REVERSED = "reversed"


@dataclass
class Transaction:
    """Transaction record"""
    transaction_id: str
    user_id: str
    wallet_id: str
    type: TransactionType
    amount: Decimal
    currency: str
    method: str
    wallet_type: str  # subscription or commission
    status: TransactionStatus = TransactionStatus.PENDING
    reference: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    failed_reason: Optional[str] = None

    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'transaction_id': self.transaction_id,
            'user_id': self.user_id,
            'wallet_id': self.wallet_id,
            'type': self.type.value,
            'amount': float(self.amount),
            'currency': self.currency,
            'method': self.method,
            'wallet_type': self.wallet_type,
            'status': self.status.value,
            'reference': self.reference,
            'metadata': self.metadata,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'failed_reason': self.failed_reason
        }


class TransactionManager:
    """Manages transaction lifecycle and tracking"""

    def __init__(self):
        self.transactions: Dict[str, Transaction] = {}
        self.user_transactions: Dict[str, List[str]] = {}  # user_id -> [transaction_ids]

    def record_transaction(
        self,
        user_id: str,
        wallet_id: str,
        type: TransactionType,
        amount: Decimal,
        currency: str,
        method: str,
        wallet_type: str,
        reference: Optional[str] = None,
        metadata: Optional[Dict] = None
    ) -> Transaction:
        """
        Record a new transaction

        Args:
            user_id: User ID
            wallet_id: Wallet ID
            type: Transaction type
            amount: Transaction amount
            currency: Currency code
            method: Payment method
            wallet_type: Wallet type (subscription or commission)
            reference: External reference
            metadata: Additional metadata

        Returns:
            Transaction object
        """
        try:
            # Validate amount
            if amount <= 0:
                raise ValueError("Amount must be positive")

            # Generate transaction ID
            transaction_id = f"TXN-{datetime.utcnow().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"

            # Create transaction
            transaction = Transaction(
                transaction_id=transaction_id,
                user_id=user_id,
                wallet_id=wallet_id,
                type=type,
                amount=amount,
                currency=currency,
                method=method,
                wallet_type=wallet_type,
                reference=reference,
                metadata=metadata or {}
            )

            # Store transaction
            self.transactions[transaction_id] = transaction

            # Add to user transactions
            if user_id not in self.user_transactions:
                self.user_transactions[user_id] = []
            self.user_transactions[user_id].append(transaction_id)

            logger.info(f"Transaction recorded: {transaction_id} for user {user_id}")
            return transaction

        except Exception as e:
            logger.error(f"Error recording transaction: {e}")
            raise

    def update_transaction_status(
        self,
        transaction_id: str,
        status: TransactionStatus,
        failed_reason: Optional[str] = None
    ) -> bool:
        """
        Update transaction status

        Args:
            transaction_id: Transaction ID
            status: New status
            failed_reason: Reason if failed

        Returns:
            Success boolean
        """
        try:
            transaction = self.transactions.get(transaction_id)
            if not transaction:
                logger.error(f"Transaction not found: {transaction_id}")
                return False

            transaction.status = status
            transaction.updated_at = datetime.utcnow()

            if status == TransactionStatus.COMPLETED:
                transaction.completed_at = datetime.utcnow()
            elif status == TransactionStatus.FAILED:
                transaction.failed_reason = failed_reason

            logger.info(f"Transaction {transaction_id} status updated to {status.value}")
            return True

        except Exception as e:
            logger.error(f"Error updating transaction status: {e}")
            return False

    def complete_transaction(self, transaction_id: str) -> bool:
        """Mark transaction as completed"""
        return self.update_transaction_status(transaction_id, TransactionStatus.COMPLETED)

    def fail_transaction(self, transaction_id: str, reason: str) -> bool:
        """Mark transaction as failed"""
        return self.update_transaction_status(transaction_id, TransactionStatus.FAILED, reason)

    def cancel_transaction(self, transaction_id: str) -> bool:
        """Cancel a pending transaction"""
        transaction = self.transactions.get(transaction_id)
        if not transaction:
            return False

        if transaction.status != TransactionStatus.PENDING:
            logger.error(f"Cannot cancel non-pending transaction: {transaction_id}")
            return False

        return self.update_transaction_status(transaction_id, TransactionStatus.CANCELLED)

    def reverse_transaction(
        self,
        transaction_id: str,
        reason: str
    ) -> Optional[Transaction]:
        """
        Reverse a completed transaction

        Creates a new reversal transaction and marks the original as reversed.

        Args:
            transaction_id: Original transaction ID
            reason: Reversal reason

        Returns:
            Reversal transaction or None
        """
        try:
            original = self.transactions.get(transaction_id)
            if not original:
                logger.error(f"Transaction not found for reversal: {transaction_id}")
                return None

            if original.status != TransactionStatus.COMPLETED:
                logger.error(f"Can only reverse completed transactions: {transaction_id}")
                return None

            # Create reversal transaction (opposite type)
            reversal_type = TransactionType.REFUND
            if original.type == TransactionType.DEPOSIT:
                reversal_type = TransactionType.WITHDRAWAL
            elif original.type == TransactionType.WITHDRAWAL:
                reversal_type = TransactionType.DEPOSIT

            reversal = self.record_transaction(
                user_id=original.user_id,
                wallet_id=original.wallet_id,
                type=reversal_type,
                amount=original.amount,
                currency=original.currency,
                method=original.method,
                wallet_type=original.wallet_type,
                reference=f"REVERSAL-{transaction_id}",
                metadata={
                    'original_transaction': transaction_id,
                    'reversal_reason': reason,
                    'reversed_at': datetime.utcnow().isoformat()
                }
            )

            # Mark original as reversed
            original.status = TransactionStatus.REVERSED
            original.updated_at = datetime.utcnow()
            original.metadata['reversed_by'] = reversal.transaction_id
            original.metadata['reversal_reason'] = reason

            logger.info(f"Transaction {transaction_id} reversed with {reversal.transaction_id}")
            return reversal

        except Exception as e:
            logger.error(f"Error reversing transaction: {e}")
            return None

    def get_transaction(self, transaction_id: str) -> Optional[Transaction]:
        """Get transaction by ID"""
        return self.transactions.get(transaction_id)

    def get_user_transactions(
        self,
        user_id: str,
        type: Optional[TransactionType] = None,
        status: Optional[TransactionStatus] = None,
        limit: int = 100
    ) -> List[Transaction]:
        """
        Get user's transactions

        Args:
            user_id: User ID
            type: Filter by type
            status: Filter by status
            limit: Maximum results

        Returns:
            List of transactions
        """
        transaction_ids = self.user_transactions.get(user_id, [])
        transactions = [self.transactions[tid] for tid in transaction_ids if tid in self.transactions]

        # Apply filters
        if type:
            transactions = [t for t in transactions if t.type == type]
        if status:
            transactions = [t for t in transactions if t.status == status]

        # Sort by created_at descending
        transactions.sort(key=lambda t: t.created_at, reverse=True)

        return transactions[:limit]

    def generate_statement(
        self,
        user_id: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict:
        """
        Generate transaction statement

        Args:
            user_id: User ID
            start_date: Start date (default: 30 days ago)
            end_date: End date (default: now)

        Returns:
            Statement dictionary
        """
        if not start_date:
            start_date = datetime.utcnow() - timedelta(days=30)
        if not end_date:
            end_date = datetime.utcnow()

        # Get all transactions in date range
        all_transactions = self.get_user_transactions(user_id, limit=10000)
        transactions = [
            t for t in all_transactions
            if start_date <= t.created_at <= end_date
        ]

        # Calculate totals
        total_deposits = sum(t.amount for t in transactions if t.type == TransactionType.DEPOSIT and t.status == TransactionStatus.COMPLETED)
        total_withdrawals = sum(t.amount for t in transactions if t.type == TransactionType.WITHDRAWAL and t.status == TransactionStatus.COMPLETED)
        total_payments = sum(t.amount for t in transactions if t.type == TransactionType.PAYMENT and t.status == TransactionStatus.COMPLETED)
        total_commissions = sum(t.amount for t in transactions if t.type == TransactionType.COMMISSION and t.status == TransactionStatus.COMPLETED)

        return {
            'user_id': user_id,
            'period': {
                'start': start_date.isoformat(),
                'end': end_date.isoformat()
            },
            'summary': {
                'total_deposits': float(total_deposits),
                'total_withdrawals': float(total_withdrawals),
                'total_payments': float(total_payments),
                'total_commissions': float(total_commissions),
                'net_flow': float(total_deposits - total_withdrawals)
            },
            'transaction_count': len(transactions),
            'transactions': [t.to_dict() for t in transactions]
        }

    def get_statistics(self) -> Dict:
        """Get overall transaction statistics"""
        total_transactions = len(self.transactions)

        if total_transactions == 0:
            return {
                'total_transactions': 0,
                'by_status': {},
                'by_type': {},
                'total_volume': 0.0
            }

        by_status = {}
        by_type = {}
        total_volume = Decimal('0')

        for txn in self.transactions.values():
            # Count by status
            status_key = txn.status.value
            by_status[status_key] = by_status.get(status_key, 0) + 1

            # Count by type
            type_key = txn.type.value
            by_type[type_key] = by_type.get(type_key, 0) + 1

            # Sum volume (completed only)
            if txn.status == TransactionStatus.COMPLETED:
                total_volume += txn.amount

        return {
            'total_transactions': total_transactions,
            'by_status': by_status,
            'by_type': by_type,
            'total_volume': float(total_volume),
            'success_rate': by_status.get('completed', 0) / total_transactions if total_transactions > 0 else 0
        }


# Global transaction manager instance
transaction_manager = TransactionManager()
