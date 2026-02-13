"""
Ethereum Payment Integration

Handles Ethereum (ETH) deposits and withdrawals.
"""

from datetime import datetime
from decimal import Decimal
from typing import Dict, Optional
import logging
import hashlib

logger = logging.getLogger(__name__)


class EthereumClient:
    """Ethereum payment client"""
    
    REQUIRED_CONFIRMATIONS = 12
    MIN_DEPOSIT = Decimal('0.01')  # ETH
    NETWORK_FEE = Decimal('0.005')  # ETH
    
    def __init__(self):
        self.addresses: Dict[str, Dict] = {}
        self.transactions: Dict[str, Dict] = {}
    
    def generate_deposit_address(self, user_id: str) -> Dict:
        """Generate Ethereum deposit address"""
        try:
            address_hash = hashlib.sha256(f"ETH{user_id}".encode()).hexdigest()
            address = f"0x{address_hash[:40]}"
            
            self.addresses[address] = {
                'user_id': user_id,
                'created_at': datetime.utcnow().isoformat()
            }
            
            logger.info(f"Generated Ethereum address for user {user_id}")
            
            return {
                'address': address,
                'network': 'ethereum',
                'qr_code': f"ethereum:{address}",
                'min_deposit': float(self.MIN_DEPOSIT),
                'confirmations_required': self.REQUIRED_CONFIRMATIONS
            }
        except Exception as e:
            logger.error(f"Error generating Ethereum address: {e}")
            raise
    
    def process_deposit(self, user_id: str, amount: Decimal, tx_hash: str, confirmations: int = 0) -> Optional[Dict]:
        """Process Ethereum deposit"""
        try:
            if amount < self.MIN_DEPOSIT:
                logger.warning(f"ETH deposit below minimum: {amount}")
                return None
            
            status = 'confirmed' if confirmations >= self.REQUIRED_CONFIRMATIONS else 'pending'
            
            transaction = {
                'tx_hash': tx_hash,
                'user_id': user_id,
                'amount': float(amount),
                'confirmations': confirmations,
                'status': status,
                'created_at': datetime.utcnow().isoformat()
            }
            
            self.transactions[tx_hash] = transaction
            logger.info(f"ETH deposit processed: {tx_hash} - {amount} ETH")
            
            return transaction
        except Exception as e:
            logger.error(f"Error processing ETH deposit: {e}")
            return None
    
    def process_withdrawal(self, user_id: str, amount: Decimal, destination: str) -> Dict:
        """Process Ethereum withdrawal"""
        try:
            total_fee = self.NETWORK_FEE
            net_amount = amount - total_fee
            
            if net_amount <= 0:
                raise ValueError("Amount too small after fees")
            
            tx_hash = hashlib.sha256(f"ETH{user_id}{amount}{destination}".encode()).hexdigest()
            
            return {
                'tx_hash': tx_hash,
                'amount': float(amount),
                'fee': float(total_fee),
                'net_amount': float(net_amount),
                'destination': destination,
                'status': 'broadcasting'
            }
        except Exception as e:
            logger.error(f"Error processing ETH withdrawal: {e}")
            raise


ethereum_client = EthereumClient()
