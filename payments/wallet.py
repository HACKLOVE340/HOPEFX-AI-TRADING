"""
Wallet Management Module

Handles user wallet operations including balance management,
deposits, withdrawals, and transaction tracking.

Note: This wallet ONLY handles subscription fees and commission payments.
Trading capital is managed directly by brokers/prop firms.
"""

from datetime import datetime
from typing import Dict, List, Optional, Tuple
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)


class WalletType:
    """Wallet type constants"""
    SUBSCRIPTION = "subscription"
    COMMISSION = "commission"


class WalletStatus:
    """Wallet status constants"""
    ACTIVE = "active"
    FROZEN = "frozen"
    SUSPENDED = "suspended"
    CLOSED = "closed"


class Wallet:
    """Represents a user's wallet"""

    def __init__(
        self,
        wallet_id: str,
        user_id: str,
        subscription_balance: Decimal = Decimal('0.00'),
        commission_balance: Decimal = Decimal('0.00'),
        currency: str = 'USD',
        status: str = WalletStatus.ACTIVE,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None
    ):
        self.wallet_id = wallet_id
        self.user_id = user_id
        self.subscription_balance = subscription_balance
        self.commission_balance = commission_balance
        self.currency = currency
        self.status = status
        self.created_at = created_at or datetime.now()
        self.updated_at = updated_at or datetime.now()

    def to_dict(self) -> Dict:
        """Convert wallet to dictionary"""
        return {
            'wallet_id': self.wallet_id,
            'user_id': self.user_id,
            'subscription_balance': float(self.subscription_balance),
            'commission_balance': float(self.commission_balance),
            'total_balance': float(self.subscription_balance + self.commission_balance),
            'currency': self.currency,
            'status': self.status,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }


class WalletManager:
    """Manages wallet operations"""

    def __init__(self):
        # In-memory storage (replace with database in production)
        self._wallets: Dict[str, Wallet] = {}
        self._transaction_history: Dict[str, List[Dict]] = {}
        logger.info("WalletManager initialized")

    def create_wallet(
        self,
        user_id: str,
        initial_balance: Decimal = Decimal('0.00'),
        currency: str = 'USD'
    ) -> Wallet:
        """
        Create a new wallet for a user

        Args:
            user_id: User identifier
            initial_balance: Starting balance
            currency: Wallet currency (default: USD)

        Returns:
            Created Wallet object
        """
        wallet_id = f"WAL-{user_id}"

        # Check if wallet already exists
        if wallet_id in self._wallets:
            logger.warning(f"Wallet already exists for user {user_id}")
            return self._wallets[wallet_id]

        wallet = Wallet(
            wallet_id=wallet_id,
            user_id=user_id,
            subscription_balance=initial_balance,
            commission_balance=Decimal('0.00'),
            currency=currency,
            status=WalletStatus.ACTIVE
        )

        self._wallets[wallet_id] = wallet
        self._transaction_history[user_id] = []

        logger.info(f"Created wallet {wallet_id} for user {user_id}")
        return wallet

    def get_wallet(self, user_id: str) -> Optional[Wallet]:
        """
        Get wallet for a user

        Args:
            user_id: User identifier

        Returns:
            Wallet object or None if not found
        """
        wallet_id = f"WAL-{user_id}"
        return self._wallets.get(wallet_id)

    def get_balance(
        self,
        user_id: str,
        wallet_type: Optional[str] = None
    ) -> Dict:
        """
        Get wallet balance(s)

        Args:
            user_id: User identifier
            wallet_type: Specific wallet type or None for all

        Returns:
            Balance information dictionary
        """
        wallet = self.get_wallet(user_id)

        if not wallet:
            return {
                'subscription_balance': 0.00,
                'commission_balance': 0.00,
                'total_balance': 0.00,
                'currency': 'USD'
            }

        if wallet_type == WalletType.SUBSCRIPTION:
            return {
                'balance': float(wallet.subscription_balance),
                'wallet_type': 'subscription',
                'currency': wallet.currency
            }
        elif wallet_type == WalletType.COMMISSION:
            return {
                'balance': float(wallet.commission_balance),
                'wallet_type': 'commission',
                'currency': wallet.currency
            }
        else:
            return {
                'subscription_balance': float(wallet.subscription_balance),
                'commission_balance': float(wallet.commission_balance),
                'total_balance': float(wallet.subscription_balance + wallet.commission_balance),
                'currency': wallet.currency
            }

    def credit_wallet(
        self,
        user_id: str,
        amount: Decimal,
        wallet_type: str = WalletType.SUBSCRIPTION,
        transaction_type: str = 'deposit',
        method: str = 'unknown',
        reference: Optional[str] = None
    ) -> Tuple[bool, str, Optional[Dict]]:
        """
        Credit (add funds to) a wallet

        Args:
            user_id: User identifier
            amount: Amount to credit
            wallet_type: Type of wallet to credit
            transaction_type: Type of transaction
            method: Payment method used
            reference: Transaction reference

        Returns:
            Tuple of (success, message, transaction_details)
        """
        if amount <= 0:
            return False, "Amount must be positive", None

        wallet = self.get_wallet(user_id)
        if not wallet:
            wallet = self.create_wallet(user_id)

        if wallet.status != WalletStatus.ACTIVE:
            return False, f"Wallet is {wallet.status}", None

        # Credit appropriate wallet
        if wallet_type == WalletType.SUBSCRIPTION:
            wallet.subscription_balance += amount
        elif wallet_type == WalletType.COMMISSION:
            wallet.commission_balance += amount
        else:
            return False, f"Invalid wallet type: {wallet_type}", None

        wallet.updated_at = datetime.now()

        # Record transaction
        transaction = {
            'transaction_id': f"TXN-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            'type': transaction_type,
            'wallet_type': wallet_type,
            'amount': float(amount),
            'method': method,
            'reference': reference,
            'balance_after': float(wallet.subscription_balance if wallet_type == WalletType.SUBSCRIPTION else wallet.commission_balance),
            'status': 'completed',
            'created_at': datetime.now().isoformat()
        }

        if user_id not in self._transaction_history:
            self._transaction_history[user_id] = []
        self._transaction_history[user_id].append(transaction)

        logger.info(f"Credited {amount} to {wallet_type} wallet for user {user_id}")
        return True, "Wallet credited successfully", transaction

    def debit_wallet(
        self,
        user_id: str,
        amount: Decimal,
        wallet_type: str = WalletType.SUBSCRIPTION,
        transaction_type: str = 'withdrawal',
        reference: Optional[str] = None
    ) -> Tuple[bool, str, Optional[Dict]]:
        """
        Debit (remove funds from) a wallet

        Args:
            user_id: User identifier
            amount: Amount to debit
            wallet_type: Type of wallet to debit
            transaction_type: Type of transaction
            reference: Transaction reference

        Returns:
            Tuple of (success, message, transaction_details)
        """
        if amount <= 0:
            return False, "Amount must be positive", None

        wallet = self.get_wallet(user_id)
        if not wallet:
            return False, "Wallet not found", None

        if wallet.status != WalletStatus.ACTIVE:
            return False, f"Wallet is {wallet.status}", None

        # Check sufficient balance
        if wallet_type == WalletType.SUBSCRIPTION:
            if wallet.subscription_balance < amount:
                return False, "Insufficient subscription balance", None
            wallet.subscription_balance -= amount
        elif wallet_type == WalletType.COMMISSION:
            if wallet.commission_balance < amount:
                return False, "Insufficient commission balance", None
            wallet.commission_balance -= amount
        else:
            return False, f"Invalid wallet type: {wallet_type}", None

        wallet.updated_at = datetime.now()

        # Record transaction
        transaction = {
            'transaction_id': f"TXN-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            'type': transaction_type,
            'wallet_type': wallet_type,
            'amount': float(amount),
            'reference': reference,
            'balance_after': float(wallet.subscription_balance if wallet_type == WalletType.SUBSCRIPTION else wallet.commission_balance),
            'status': 'completed',
            'created_at': datetime.now().isoformat()
        }

        if user_id not in self._transaction_history:
            self._transaction_history[user_id] = []
        self._transaction_history[user_id].append(transaction)

        logger.info(f"Debited {amount} from {wallet_type} wallet for user {user_id}")
        return True, "Wallet debited successfully", transaction

    def transfer_between_wallets(
        self,
        user_id: str,
        amount: Decimal,
        from_wallet: str,
        to_wallet: str
    ) -> Tuple[bool, str]:
        """
        Transfer funds between wallet types

        Args:
            user_id: User identifier
            amount: Amount to transfer
            from_wallet: Source wallet type
            to_wallet: Destination wallet type

        Returns:
            Tuple of (success, message)
        """
        if amount <= 0:
            return False, "Amount must be positive"

        if from_wallet == to_wallet:
            return False, "Cannot transfer to same wallet"

        # Debit from source
        success, message, _ = self.debit_wallet(
            user_id, amount, from_wallet, 'transfer', f"Transfer to {to_wallet}"
        )

        if not success:
            return False, message

        # Credit to destination
        success, message, _ = self.credit_wallet(
            user_id, amount, to_wallet, 'transfer', 'internal', f"Transfer from {from_wallet}"
        )

        if not success:
            # Rollback debit
            self.credit_wallet(
                user_id, amount, from_wallet, 'reversal', 'internal', "Transfer rollback"
            )
            return False, f"Transfer failed: {message}"

        logger.info(f"Transferred {amount} from {from_wallet} to {to_wallet} for user {user_id}")
        return True, "Transfer successful"

    def freeze_wallet(self, user_id: str) -> Tuple[bool, str]:
        """
        Freeze a wallet (prevent transactions)

        Args:
            user_id: User identifier

        Returns:
            Tuple of (success, message)
        """
        wallet = self.get_wallet(user_id)
        if not wallet:
            return False, "Wallet not found"

        wallet.status = WalletStatus.FROZEN
        wallet.updated_at = datetime.now()

        logger.warning(f"Wallet frozen for user {user_id}")
        return True, "Wallet frozen successfully"

    def unfreeze_wallet(self, user_id: str) -> Tuple[bool, str]:
        """
        Unfreeze a wallet

        Args:
            user_id: User identifier

        Returns:
            Tuple of (success, message)
        """
        wallet = self.get_wallet(user_id)
        if not wallet:
            return False, "Wallet not found"

        wallet.status = WalletStatus.ACTIVE
        wallet.updated_at = datetime.now()

        logger.info(f"Wallet unfrozen for user {user_id}")
        return True, "Wallet activated successfully"

    def get_transaction_history(
        self,
        user_id: str,
        limit: int = 50
    ) -> List[Dict]:
        """
        Get transaction history for a user

        Args:
            user_id: User identifier
            limit: Maximum number of transactions to return

        Returns:
            List of transaction dictionaries
        """
        if user_id not in self._transaction_history:
            return []

        # Return most recent transactions
        transactions = self._transaction_history[user_id]
        return transactions[-limit:] if len(transactions) > limit else transactions


# Global instance
wallet_manager = WalletManager()
