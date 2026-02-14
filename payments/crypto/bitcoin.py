"""
Bitcoin Payment Integration

Handles Bitcoin deposits and withdrawals with HD wallet support.
"""

from datetime import datetime
from decimal import Decimal
from typing import Dict, Optional, List
from dataclasses import dataclass
import logging
import hashlib
import secrets

logger = logging.getLogger(__name__)


@dataclass
class BitcoinAddress:
    """Bitcoin address information"""
    address: str
    user_id: str
    derivation_path: str
    created_at: datetime
    last_used: Optional[datetime] = None


@dataclass
class BitcoinTransaction:
    """Bitcoin transaction"""
    tx_hash: str
    address: str
    amount: Decimal
    confirmations: int
    status: str
    created_at: datetime


class BitcoinClient:
    """Bitcoin payment client with HD wallet support"""

    REQUIRED_CONFIRMATIONS = 3
    MIN_DEPOSIT = Decimal('0.001')  # BTC
    NETWORK_FEE = Decimal('0.0005')  # BTC

    def __init__(self):
        self.addresses: Dict[str, BitcoinAddress] = {}
        self.transactions: Dict[str, BitcoinTransaction] = {}
        self.user_addresses: Dict[str, List[str]] = {}

        # Master seed (in production, this would be securely stored)
        self.master_seed = secrets.token_hex(32)

    def generate_deposit_address(self, user_id: str) -> Dict:
        """
        Generate unique deposit address for user

        Args:
            user_id: User ID

        Returns:
            Address information with QR code
        """
        try:
            # Generate deterministic address (simplified)
            # In production, use proper BIP32/BIP44 derivation
            address_index = len(self.user_addresses.get(user_id, []))
            derivation_path = f"m/44'/0'/0'/0/{address_index}"

            # Generate address (simplified - in production use bitcoinlib)
            address_data = f"{self.master_seed}{user_id}{address_index}"
            address_hash = hashlib.sha256(address_data.encode()).hexdigest()
            address = f"bc1q{address_hash[:40]}"  # Bech32 format

            # Store address
            btc_address = BitcoinAddress(
                address=address,
                user_id=user_id,
                derivation_path=derivation_path,
                created_at=datetime.utcnow()
            )

            self.addresses[address] = btc_address

            if user_id not in self.user_addresses:
                self.user_addresses[user_id] = []
            self.user_addresses[user_id].append(address)

            logger.info(f"Generated Bitcoin address for user {user_id}: {address}")

            return {
                'address': address,
                'qr_code': f"bitcoin:{address}",  # QR code data
                'network': 'bitcoin',
                'min_deposit': float(self.MIN_DEPOSIT),
                'confirmations_required': self.REQUIRED_CONFIRMATIONS
            }

        except Exception as e:
            logger.error(f"Error generating Bitcoin address: {e}")
            raise

    def process_deposit(
        self,
        user_id: str,
        amount: Decimal,
        tx_hash: str,
        confirmations: int = 0
    ) -> Optional[BitcoinTransaction]:
        """
        Process Bitcoin deposit

        Args:
            user_id: User ID
            amount: Amount in BTC
            tx_hash: Transaction hash
            confirmations: Number of confirmations

        Returns:
            Transaction object or None
        """
        try:
            # Validate minimum deposit
            if amount < self.MIN_DEPOSIT:
                logger.warning(f"Deposit below minimum: {amount} BTC")
                return None

            # Check if transaction already exists
            if tx_hash in self.transactions:
                # Update confirmations
                self.transactions[tx_hash].confirmations = confirmations
                return self.transactions[tx_hash]

            # Get user's deposit address
            user_addrs = self.user_addresses.get(user_id, [])
            if not user_addrs:
                logger.error(f"No deposit address for user {user_id}")
                return None

            # Use latest address
            address = user_addrs[-1]

            # Determine status
            status = 'confirmed' if confirmations >= self.REQUIRED_CONFIRMATIONS else 'pending'

            # Create transaction
            transaction = BitcoinTransaction(
                tx_hash=tx_hash,
                address=address,
                amount=amount,
                confirmations=confirmations,
                status=status,
                created_at=datetime.utcnow()
            )

            self.transactions[tx_hash] = transaction

            # Update address last used
            if address in self.addresses:
                self.addresses[address].last_used = datetime.utcnow()

            logger.info(f"Bitcoin deposit processed: {tx_hash} - {amount} BTC - {confirmations} confirmations")

            return transaction

        except Exception as e:
            logger.error(f"Error processing Bitcoin deposit: {e}")
            return None

    def process_withdrawal(
        self,
        user_id: str,
        amount: Decimal,
        destination_address: str
    ) -> Dict:
        """
        Process Bitcoin withdrawal

        Args:
            user_id: User ID
            amount: Amount in BTC
            destination_address: Destination Bitcoin address

        Returns:
            Withdrawal information
        """
        try:
            # Validate destination address
            if not self._validate_address(destination_address):
                raise ValueError("Invalid Bitcoin address")

            # Calculate fees
            total_fee = self.NETWORK_FEE
            net_amount = amount - total_fee

            if net_amount <= 0:
                raise ValueError("Amount too small after fees")

            # Generate transaction ID (in production, broadcast to network)
            tx_hash = hashlib.sha256(
                f"{user_id}{amount}{destination_address}{datetime.utcnow()}".encode()
            ).hexdigest()

            withdrawal = {
                'tx_hash': tx_hash,
                'user_id': user_id,
                'amount': float(amount),
                'fee': float(total_fee),
                'net_amount': float(net_amount),
                'destination': destination_address,
                'status': 'broadcasting',
                'created_at': datetime.utcnow().isoformat()
            }

            logger.info(f"Bitcoin withdrawal processed: {tx_hash} - {amount} BTC to {destination_address}")

            return withdrawal

        except Exception as e:
            logger.error(f"Error processing Bitcoin withdrawal: {e}")
            raise

    def _validate_address(self, address: str) -> bool:
        """Validate Bitcoin address format"""
        # Simplified validation (in production use proper validation)
        if address.startswith('bc1'):  # Bech32
            return len(address) >= 42 and len(address) <= 62
        elif address.startswith('1') or address.startswith('3'):  # Legacy/P2SH
            return len(address) >= 26 and len(address) <= 35
        return False

    def get_transaction_status(self, tx_hash: str) -> Optional[Dict]:
        """Get Bitcoin transaction status"""
        transaction = self.transactions.get(tx_hash)
        if not transaction:
            return None

        return {
            'tx_hash': transaction.tx_hash,
            'address': transaction.address,
            'amount': float(transaction.amount),
            'confirmations': transaction.confirmations,
            'status': transaction.status,
            'created_at': transaction.created_at.isoformat()
        }

    def get_user_transactions(self, user_id: str) -> List[Dict]:
        """Get all Bitcoin transactions for user"""
        user_addrs = set(self.user_addresses.get(user_id, []))

        transactions = [
            {
                'tx_hash': tx.tx_hash,
                'amount': float(tx.amount),
                'confirmations': tx.confirmations,
                'status': tx.status,
                'created_at': tx.created_at.isoformat()
            }
            for tx in self.transactions.values()
            if tx.address in user_addrs
        ]

        # Sort by created_at descending
        transactions.sort(key=lambda x: x['created_at'], reverse=True)

        return transactions


# Global Bitcoin client instance
bitcoin_client = BitcoinClient()
