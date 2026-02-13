"""
Compliance Module

AML (Anti-Money Laundering) monitoring and regulatory compliance.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)


class RiskLevel(Enum):
    """Risk assessment levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class AMLCheck:
    """AML check record"""
    check_id: str
    user_id: str
    transaction_id: Optional[str]
    check_type: str
    risk_level: RiskLevel
    reason: str
    checked_at: datetime = field(default_factory=datetime.utcnow)
    resolved: bool = False
    resolution_notes: Optional[str] = None


@dataclass
class ComplianceReport:
    """Compliance report"""
    report_id: str
    period_start: datetime
    period_end: datetime
    total_transactions: int
    flagged_transactions: int
    risk_breakdown: Dict[str, int]
    generated_at: datetime = field(default_factory=datetime.utcnow)


class ComplianceManager:
    """Manages AML and regulatory compliance"""
    
    def __init__(self):
        self.aml_checks: Dict[str, AMLCheck] = {}
        self.flagged_users: Dict[str, List[str]] = {}  # user_id -> [check_ids]
        self.blacklist: List[str] = []  # user_ids or addresses
        
        # Thresholds
        self.large_transaction_threshold = Decimal('10000.00')
        self.high_frequency_threshold = 10  # transactions per hour
        self.suspicious_pattern_threshold = 5  # similar transactions
    
    def run_aml_check(
        self,
        user_id: str,
        transaction_id: Optional[str],
        amount: Decimal,
        transaction_type: str
    ) -> Optional[AMLCheck]:
        """
        Run AML check on transaction
        
        Args:
            user_id: User ID
            transaction_id: Transaction ID
            amount: Transaction amount
            transaction_type: Type of transaction
            
        Returns:
            AMLCheck if flagged, None otherwise
        """
        check_id = f"AML-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        
        # Check if user is blacklisted
        if user_id in self.blacklist:
            return self._create_check(
                check_id, user_id, transaction_id,
                "blacklist", RiskLevel.CRITICAL,
                "User is blacklisted"
            )
        
        # Check for large transactions
        if amount >= self.large_transaction_threshold:
            return self._create_check(
                check_id, user_id, transaction_id,
                "large_transaction", RiskLevel.MEDIUM,
                f"Large transaction: ${amount}"
            )
        
        # Check for structured transactions (multiple small to avoid reporting)
        if self._check_structuring(user_id, amount):
            return self._create_check(
                check_id, user_id, transaction_id,
                "structuring", RiskLevel.HIGH,
                "Potential structuring detected"
            )
        
        # Check for rapid succession transactions
        if self._check_high_frequency(user_id):
            return self._create_check(
                check_id, user_id, transaction_id,
                "high_frequency", RiskLevel.MEDIUM,
                "High frequency transactions detected"
            )
        
        # Check for unusual patterns
        if self._check_unusual_pattern(user_id, amount):
            return self._create_check(
                check_id, user_id, transaction_id,
                "unusual_pattern", RiskLevel.MEDIUM,
                "Unusual transaction pattern detected"
            )
        
        return None
    
    def _create_check(
        self,
        check_id: str,
        user_id: str,
        transaction_id: Optional[str],
        check_type: str,
        risk_level: RiskLevel,
        reason: str
    ) -> AMLCheck:
        """Create and store an AML check"""
        check = AMLCheck(
            check_id=check_id,
            user_id=user_id,
            transaction_id=transaction_id,
            check_type=check_type,
            risk_level=risk_level,
            reason=reason
        )
        
        self.aml_checks[check_id] = check
        
        # Add to user's flagged list
        if user_id not in self.flagged_users:
            self.flagged_users[user_id] = []
        self.flagged_users[user_id].append(check_id)
        
        logger.warning(f"AML check flagged: {check_id} - {reason}")
        return check
    
    def _check_structuring(self, user_id: str, amount: Decimal) -> bool:
        """
        Check for structuring (breaking up large amounts)
        
        Multiple transactions just below reporting threshold
        """
        # Get recent checks for this user
        user_checks = self.flagged_users.get(user_id, [])
        recent_checks = [
            self.aml_checks[cid] for cid in user_checks
            if cid in self.aml_checks and
            datetime.utcnow() - self.aml_checks[cid].checked_at < timedelta(days=1)
        ]
        
        # Count transactions just below threshold
        near_threshold = [
            c for c in recent_checks
            if c.check_type == "large_transaction"
        ]
        
        return len(near_threshold) >= 3
    
    def _check_high_frequency(self, user_id: str) -> bool:
        """Check for unusually high transaction frequency"""
        user_checks = self.flagged_users.get(user_id, [])
        recent_checks = [
            cid for cid in user_checks
            if cid in self.aml_checks and
            datetime.utcnow() - self.aml_checks[cid].checked_at < timedelta(hours=1)
        ]
        
        return len(recent_checks) >= self.high_frequency_threshold
    
    def _check_unusual_pattern(self, user_id: str, amount: Decimal) -> bool:
        """Check for unusual transaction patterns"""
        # Simplified pattern detection
        # In production, would use ML models
        user_checks = self.flagged_users.get(user_id, [])
        
        if len(user_checks) < 5:
            return False
        
        # Check for many identical amounts (possible automation)
        recent_checks = [
            self.aml_checks[cid] for cid in user_checks[-10:]
            if cid in self.aml_checks
        ]
        
        # Count similar amounts (within 1%)
        similar_count = sum(
            1 for c in recent_checks
            if c.check_type in ["large_transaction", "structuring"]
        )
        
        return similar_count >= self.suspicious_pattern_threshold
    
    def calculate_risk_score(self, user_id: str) -> Dict:
        """
        Calculate overall risk score for user
        
        Args:
            user_id: User ID
            
        Returns:
            Risk score and details
        """
        user_checks = self.flagged_users.get(user_id, [])
        
        if not user_checks:
            return {
                'user_id': user_id,
                'risk_score': 0,
                'risk_level': RiskLevel.LOW.value,
                'total_flags': 0,
                'unresolved_flags': 0
            }
        
        checks = [self.aml_checks[cid] for cid in user_checks if cid in self.aml_checks]
        unresolved = [c for c in checks if not c.resolved]
        
        # Calculate score (0-100)
        score = 0
        for check in unresolved:
            if check.risk_level == RiskLevel.LOW:
                score += 10
            elif check.risk_level == RiskLevel.MEDIUM:
                score += 25
            elif check.risk_level == RiskLevel.HIGH:
                score += 50
            elif check.risk_level == RiskLevel.CRITICAL:
                score += 100
        
        score = min(score, 100)
        
        # Determine overall risk level
        if score >= 75:
            risk_level = RiskLevel.CRITICAL
        elif score >= 50:
            risk_level = RiskLevel.HIGH
        elif score >= 25:
            risk_level = RiskLevel.MEDIUM
        else:
            risk_level = RiskLevel.LOW
        
        return {
            'user_id': user_id,
            'risk_score': score,
            'risk_level': risk_level.value,
            'total_flags': len(checks),
            'unresolved_flags': len(unresolved),
            'breakdown': {
                'low': len([c for c in unresolved if c.risk_level == RiskLevel.LOW]),
                'medium': len([c for c in unresolved if c.risk_level == RiskLevel.MEDIUM]),
                'high': len([c for c in unresolved if c.risk_level == RiskLevel.HIGH]),
                'critical': len([c for c in unresolved if c.risk_level == RiskLevel.CRITICAL])
            }
        }
    
    def resolve_check(
        self,
        check_id: str,
        resolution_notes: str
    ) -> bool:
        """
        Resolve an AML check
        
        Args:
            check_id: Check ID
            resolution_notes: Notes about resolution
            
        Returns:
            Success boolean
        """
        check = self.aml_checks.get(check_id)
        if not check:
            logger.error(f"AML check not found: {check_id}")
            return False
        
        check.resolved = True
        check.resolution_notes = resolution_notes
        
        logger.info(f"AML check resolved: {check_id}")
        return True
    
    def add_to_blacklist(self, user_id: str) -> None:
        """Add user to blacklist"""
        if user_id not in self.blacklist:
            self.blacklist.append(user_id)
            logger.warning(f"User added to blacklist: {user_id}")
    
    def remove_from_blacklist(self, user_id: str) -> bool:
        """Remove user from blacklist"""
        if user_id in self.blacklist:
            self.blacklist.remove(user_id)
            logger.info(f"User removed from blacklist: {user_id}")
            return True
        return False
    
    def generate_compliance_report(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> ComplianceReport:
        """
        Generate compliance report for period
        
        Args:
            start_date: Report start date
            end_date: Report end date
            
        Returns:
            Compliance report
        """
        report_id = f"RPT-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        
        # Get checks in period
        period_checks = [
            check for check in self.aml_checks.values()
            if start_date <= check.checked_at <= end_date
        ]
        
        # Count by risk level
        risk_breakdown = {
            'low': len([c for c in period_checks if c.risk_level == RiskLevel.LOW]),
            'medium': len([c for c in period_checks if c.risk_level == RiskLevel.MEDIUM]),
            'high': len([c for c in period_checks if c.risk_level == RiskLevel.HIGH]),
            'critical': len([c for c in period_checks if c.risk_level == RiskLevel.CRITICAL])
        }
        
        # Get unique transactions
        transaction_ids = set(c.transaction_id for c in period_checks if c.transaction_id)
        
        report = ComplianceReport(
            report_id=report_id,
            period_start=start_date,
            period_end=end_date,
            total_transactions=len(transaction_ids),
            flagged_transactions=len(period_checks),
            risk_breakdown=risk_breakdown
        )
        
        logger.info(f"Compliance report generated: {report_id}")
        return report
    
    def get_flagged_users(self, min_risk_level: RiskLevel = RiskLevel.MEDIUM) -> List[Dict]:
        """
        Get list of flagged users
        
        Args:
            min_risk_level: Minimum risk level to include
            
        Returns:
            List of user risk summaries
        """
        flagged = []
        
        for user_id in self.flagged_users:
            risk_score = self.calculate_risk_score(user_id)
            
            # Filter by risk level
            if risk_score['risk_level'] == RiskLevel.LOW.value and min_risk_level != RiskLevel.LOW:
                continue
            if risk_score['risk_level'] == RiskLevel.MEDIUM.value and min_risk_level in [RiskLevel.HIGH, RiskLevel.CRITICAL]:
                continue
            if risk_score['risk_level'] == RiskLevel.HIGH.value and min_risk_level == RiskLevel.CRITICAL:
                continue
            
            flagged.append(risk_score)
        
        # Sort by risk score descending
        flagged.sort(key=lambda x: x['risk_score'], reverse=True)
        
        return flagged


# Global compliance manager instance
compliance_manager = ComplianceManager()
