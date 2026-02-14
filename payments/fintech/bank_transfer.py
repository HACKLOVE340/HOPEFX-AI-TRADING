"""
Bank Transfer Integration

Direct bank transfer handling for Nigerian banks.
"""

from datetime import datetime
from decimal import Decimal
from typing import Dict
import logging

logger = logging.getLogger(__name__)


class BankTransferClient:
    """Bank transfer client for Nigerian banks"""

    FLAT_FEE_NGN = Decimal('50.00')  # ₦50

    def __init__(self):
        self.transfers = {}
        self.nigerian_banks = {
            '058': 'GTBank',
            '011': 'First Bank',
            '033': 'United Bank for Africa',
            '044': 'Access Bank',
            '057': 'Zenith Bank'
        }

    def validate_account(self, bank_code: str, account_number: str) -> Dict:
        """Validate bank account"""
        try:
            bank_name = self.nigerian_banks.get(bank_code, 'Unknown Bank')

            # Simplified validation
            if len(account_number) != 10:
                return {'valid': False, 'message': 'Invalid account number length'}

            return {
                'valid': True,
                'account_number': account_number,
                'account_name': f'Account Holder {account_number[-4:]}',
                'bank_code': bank_code,
                'bank_name': bank_name
            }
        except Exception as e:
            logger.error(f"Error validating account: {e}")
            raise

    def initiate_transfer(self, user_id: str, amount: Decimal, bank_code: str, account_number: str) -> Dict:
        """Initiate bank transfer"""
        try:
            transfer_id = f"BT-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

            # Validate account
            validation = self.validate_account(bank_code, account_number)
            if not validation['valid']:
                raise ValueError(validation['message'])

            # Calculate fee
            fee_usd = self.FLAT_FEE_NGN / Decimal('775.00')  # Convert to USD

            transfer = {
                'transfer_id': transfer_id,
                'user_id': user_id,
                'amount': float(amount),
                'fee': float(fee_usd),
                'net_amount': float(amount - fee_usd),
                'bank_code': bank_code,
                'bank_name': validation['bank_name'],
                'account_number': account_number,
                'account_name': validation['account_name'],
                'status': 'pending',
                'created_at': datetime.utcnow().isoformat()
            }

            self.transfers[transfer_id] = transfer
            logger.info(f"Bank transfer initiated: {transfer_id}")

            return transfer
        except Exception as e:
            logger.error(f"Error initiating bank transfer: {e}")
            raise

    def get_transfer_status(self, transfer_id: str) -> Dict:
        """Get transfer status"""
        return self.transfers.get(transfer_id, {'status': 'not_found'})


bank_transfer_client = BankTransferClient()
