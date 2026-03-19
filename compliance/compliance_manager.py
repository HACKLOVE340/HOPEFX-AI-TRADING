"""
Compliance & Regulatory Management
- Trade logging
- Audit trails
- KYC tracking
"""

from dataclasses import dataclass
from typing import List, Dict
from datetime import datetime
from enum import Enum
import logging

logger = logging.getLogger(__name__)

class KYCStatus(Enum):
    """KYC verification status"""
    UNVERIFIED = "unverified"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"

@dataclass
class KYCRecord:
    """KYC record"""
    user_id: str
    status: KYCStatus
    submitted_at: datetime
    verified_at: datetime = None
    document_type: str = ""
    verification_method: str = ""

class ComplianceManager:
    """Manage compliance requirements"""
    
    def __init__(self):
        self.kyc_records: Dict[str, KYCRecord] = {}
        self.audit_log: List[Dict] = []
    
    def submit_kyc(self, user_id: str, document_type: str) -> KYCRecord:
        """Submit KYC documentation"""
        record = KYCRecord(
            user_id=user_id,
            status=KYCStatus.PENDING,
            submitted_at=datetime.now(),
            document_type=document_type
        )
        self.kyc_records[user_id] = record
        
        self._log_audit(f"KYC submitted for {user_id}")
        logger.info(f"KYC submitted: {user_id}")
        return record
    
    def approve_kyc(self, user_id: str) -> bool:
        """Approve KYC"""
        if user_id in self.kyc_records:
            record = self.kyc_records[user_id]
            record.status = KYCStatus.APPROVED
            record.verified_at = datetime.now()
            
            self._log_audit(f"KYC approved for {user_id}")
            logger.info(f"KYC approved: {user_id}")
            return True
        return False
    
    def get_kyc_status(self, user_id: str) -> KYCStatus:
        """Get KYC status"""
        if user_id in self.kyc_records:
            return self.kyc_records[user_id].status
        return KYCStatus.UNVERIFIED
    
    def log_trade(self, user_id: str, trade_data: Dict):
        """Log trade for compliance"""
        log_entry = {
            'timestamp': datetime.now(),
            'user_id': user_id,
            'trade': trade_data
        }
        self._log_audit(f"Trade executed for {user_id}: {trade_data}")
    
    def _log_audit(self, message: str):
        """Log audit event"""
        self.audit_log.append({
            'timestamp': datetime.now(),
            'message': message
        })
    
    def get_audit_log(self, limit: int = 100) -> List[Dict]:
        """Get audit log"""
        return self.audit_log[-limit:]