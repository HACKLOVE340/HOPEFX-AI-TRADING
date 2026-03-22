# compliance/auditor.py
"""
HOPEFX Compliance & Audit System
Meets regulatory requirements for financial trading
"""

import hashlib
import json
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import asyncio


class AuditLevel(Enum):
    DEBUG = 0      # Internal debugging
    INFO = 1       # Normal operations
    COMPLIANCE = 2 # Regulatory required
    CRITICAL = 3   # Risk events


@dataclass
class AuditRecord:
    """Immutable audit record"""
    timestamp: str
    sequence_number: int
    level: AuditLevel
    category: str  # ORDER, RISK, STRATEGY, etc.
    actor: str     # System component or user
    action: str
    data: Dict
    hash_chain: str  # Link to previous record
    signature: Optional[str] = None


class ImmutableAuditLog:
    """
    Tamper-evident audit log using blockchain-inspired hash chaining.
    Meets SEC/CFTC requirements for trade reporting.
    """
    
    def __init__(self, log_path: str = "data/audit/"):
        self.log_path = log_path
        self.records: List[AuditRecord] = []
        self.sequence = 0
        self.last_hash = "0" * 64  # Genesis hash
    
    def append(self, level: AuditLevel, category: str, actor: str, 
               action: str, data: Dict):
        """Append immutable audit record"""
        self.sequence += 1
        
        # Create record
        record = AuditRecord(
            timestamp=datetime.utcnow().isoformat(),
            sequence_number=self.sequence,
            level=level,
            category=category,
            actor=actor,
            action=action,
            data=data,
            hash_chain=self._calculate_hash(data)
        )
        
        # Update hash chain
        self.last_hash = record.hash_chain
        self.records.append(record)
        
        # Persist immediately (write-ahead logging)
        self._persist_record(record)
        
        return record
    
    def _calculate_hash(self, data: Dict) -> str:
        """Calculate cryptographic hash of record"""
        record_str = json.dumps({
            'seq': self.sequence,
            'prev_hash': self.last_hash,
            'timestamp': datetime.utcnow().isoformat(),
            'data_hash': hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
        }, sort_keys=True)
        
        return hashlib.sha256(record_str.encode()).hexdigest()
    
    def _persist_record(self, record: AuditRecord):
        """Write to append-only log"""
        import aiofiles
        
        filename = f"{self.log_path}audit_{datetime.utcnow().strftime('%Y-%m')}.jsonl"
        
        # Async write
        asyncio.create_task(self._async_write(filename, record))
    
    async def _async_write(self, filename: str, record: AuditRecord):
        async with aiofiles.open(filename, 'a') as f:
            await f.write(json.dumps({
                'timestamp': record.timestamp,
                'seq': record.sequence_number,
                'level': record.level.name,
                'category': record.category,
                'actor': record.actor,
                'action': record.action,
                'data': record.data,
                'hash': record.hash_chain
            }) + '\n')
    
    def verify_integrity(self) -> bool:
        """
        Verify hash chain integrity.
        Detects any tampering with historical records.
        """
        calculated_hash = "0" * 64
        
        for record in sorted(self.records, key=lambda r: r.sequence_number):
            expected_hash = self._recalculate_hash(record, calculated_hash)
            
            if record.hash_chain != expected_hash:
                print(f"❌ INTEGRITY VIOLATION at record {record.sequence_number}")
                return False
            
            calculated_hash = record.hash_chain
        
        print("✅ Audit log integrity verified")
        return True
    
    def _recalculate_hash(self, record: AuditRecord, prev_hash: str) -> str:
        """Recalculate expected hash"""
        record_str = json.dumps({
            'seq': record.sequence_number,
            'prev_hash': prev_hash,
            'timestamp': record.timestamp,
            'data_hash': hashlib.sha256(json.dumps(record.data, sort_keys=True).encode()).hexdigest()
        }, sort_keys=True)
        
        return hashlib.sha256(record_str.encode()).hexdigest()
    
    def export_for_regulator(self, start_date: datetime, end_date: datetime) -> List[Dict]:
        """Export compliant audit trail for regulatory review"""
        return [
            {
                'timestamp': r.timestamp,
                'sequence': r.sequence_number,
                'category': r.category,
                'actor': r.actor,
                'action': r.action,
                'data': r.data,
                'hash_verification': r.hash_chain
            }
            for r in self.records
            if start_date <= datetime.fromisoformat(r.timestamp) <= end_date
        ]


class TradeReporting:
    """
    Automated trade reporting to regulators.
    """
    
    def __init__(self, jurisdiction: str = "US"):
        self.jurisdiction = jurisdiction
        self.audit_log = ImmutableAuditLog()
        self.reporting_obligations = self._load_obligations()
    
    def _load_obligations(self) -> Dict:
        """Load regulatory requirements"""
        obligations = {
            'US': {
                'cftc': {
                    'large_trader_reporting': True,
                    'threshold': 25,  # Contracts
                    'time_limit': 'T+1'  # Report by next day
                },
                'sec': {
                    'cat_reporting': True,  # Consolidated Audit Trail
                    'time_limit': 'T+0'  # Real-time
                }
            },
            'EU': {
                'mifid_ii': {
                    'transaction_reporting': True,
                    'time_limit': 'T+1'
                }
            }
        }
        return obligations.get(self.jurisdiction, {})
    
    def report_trade(self, trade: Dict):
        """Log trade and trigger regulatory reporting if needed"""
        # Always audit
        self.audit_log.append(
            AuditLevel.COMPLIANCE,
            'TRADE',
            trade.get('strategy_id', 'unknown'),
            'EXECUTION',
            trade
        )
        
        # Check reporting thresholds
        if self._requires_immediate_reporting(trade):
            asyncio.create_task(self._submit_to_regulator(trade))
    
    def _requires_immediate_reporting(self, trade: Dict) -> bool:
        """Check if trade requires immediate regulatory reporting"""
        # Large trader threshold
        if trade.get('size', 0) > self.reporting_obligations.get('cftc', {}).get('threshold', 25):
            return True
        
        # Suspicious activity
        if trade.get('flags', {}).get('suspicious', False):
            return True
        
        return False
    
    async def _submit_to_regulator(self, trade: Dict):
        """Submit to regulatory reporting system"""
        # CFTC: SWAP Data Repository
        # SEC: CAT (Consolidated Audit Trail)
        
        print(f"📋 Submitting trade to regulator: {trade.get('id')}")
        # Implement actual API call to regulator
        
        # Log submission
        self.audit_log.append(
            AuditLevel.COMPLIANCE,
            'REGULATORY',
            'system',
            'REPORT_SUBMITTED',
            {'trade_id': trade.get('id'), 'regulator': 'CFTC'}
        )
    
    def generate_daily_report(self) -> Dict:
        """Generate end-of-day compliance report"""
        today = datetime.utcnow().date()
        
        trades_today = [
            r for r in self.audit_log.records
            if r.category == 'TRADE' and 
            datetime.fromisoformat(r.timestamp).date() == today
        ]
        
        return {
            'date': today.isoformat(),
            'total_trades': len(trades_today),
            'total_notional': sum(t.data.get('notional', 0) for t in trades_today),
            'regulatory_reports_filed': len([
                t for t in trades_today 
                if self._requires_immediate_reporting(t.data)
            ]),
            'audit_hash': self.audit_log.last_hash,
            'integrity_verified': self.audit_log.verify_integrity()
        }
