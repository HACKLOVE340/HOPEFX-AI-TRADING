"""
Compliance & Regulatory Management

Persists KYC records and audit log to the database.
Falls back to in-memory storage when no DB session factory is available.
"""

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


class KYCStatus(Enum):
    UNVERIFIED = "unverified"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ComplianceManager:
    """
    Manages KYC verification and audit logging with DB persistence.
    Degrades gracefully to in-memory when no session_factory is provided.
    """

    def __init__(self, session_factory=None):
        self._session_factory = session_factory
        self._kyc_records: Dict[str, Dict] = {}
        self._audit_log: List[Dict] = []
        self._sequence = 0
        self._last_hash = "0" * 64

    def set_session_factory(self, session_factory):
        """Wire in DB session factory after construction (called from app startup)."""
        self._session_factory = session_factory

    # ── KYC ──────────────────────────────────────────────────────────────────

    def submit_kyc(self, user_id: str, document_type: str) -> Dict:
        now = datetime.now(timezone.utc)
        record = {
            "user_id": user_id,
            "status": KYCStatus.PENDING.value,
            "document_type": document_type,
            "submitted_at": now.isoformat(),
            "verified_at": None,
        }
        self._kyc_records[user_id] = record

        if self._session_factory:
            try:
                from database.models import KYCRecord
                with self._session_factory() as session:
                    existing = session.query(KYCRecord).filter_by(user_id=user_id).first()
                    if existing:
                        existing.status = KYCStatus.PENDING.value
                        existing.document_type = document_type
                        existing.submitted_at = now
                        existing.updated_at = now
                    else:
                        session.add(KYCRecord(
                            user_id=user_id,
                            status=KYCStatus.PENDING.value,
                            document_type=document_type,
                            submitted_at=now,
                        ))
                    session.commit()
            except Exception as exc:
                logger.error("KYC DB write failed: %s", exc)

        self._log_audit("KYC", user_id, "kyc_submitted", {"document_type": document_type})
        return record

    def approve_kyc(self, user_id: str) -> bool:
        now = datetime.now(timezone.utc)
        if user_id in self._kyc_records:
            self._kyc_records[user_id]["status"] = KYCStatus.APPROVED.value
            self._kyc_records[user_id]["verified_at"] = now.isoformat()

        if self._session_factory:
            try:
                from database.models import KYCRecord
                with self._session_factory() as session:
                    rec = session.query(KYCRecord).filter_by(user_id=user_id).first()
                    if rec:
                        rec.status = KYCStatus.APPROVED.value
                        rec.verified_at = now
                        rec.updated_at = now
                        session.commit()
            except Exception as exc:
                logger.error("KYC approve DB write failed: %s", exc)

        self._log_audit("KYC", "system", "kyc_approved", {"user_id": user_id})
        return True

    def reject_kyc(self, user_id: str, reason: str = "") -> bool:
        now = datetime.now(timezone.utc)
        if user_id in self._kyc_records:
            self._kyc_records[user_id]["status"] = KYCStatus.REJECTED.value

        if self._session_factory:
            try:
                from database.models import KYCRecord
                with self._session_factory() as session:
                    rec = session.query(KYCRecord).filter_by(user_id=user_id).first()
                    if rec:
                        rec.status = KYCStatus.REJECTED.value
                        rec.rejected_at = now
                        rec.rejection_reason = reason
                        rec.updated_at = now
                        session.commit()
            except Exception as exc:
                logger.error("KYC reject DB write failed: %s", exc)

        self._log_audit("KYC", "system", "kyc_rejected", {"user_id": user_id, "reason": reason})
        return True

    def get_kyc_status(self, user_id: str) -> KYCStatus:
        if self._session_factory:
            try:
                from database.models import KYCRecord
                with self._session_factory() as session:
                    rec = session.query(KYCRecord).filter_by(user_id=user_id).first()
                    if rec:
                        return KYCStatus(rec.status)
            except Exception as exc:
                logger.error("KYC status DB read failed: %s", exc)

        rec = self._kyc_records.get(user_id)
        return KYCStatus(rec["status"]) if rec else KYCStatus.UNVERIFIED

    def is_kyc_approved(self, user_id: str) -> bool:
        return self.get_kyc_status(user_id) == KYCStatus.APPROVED

    # ── Trade logging ─────────────────────────────────────────────────────────

    def log_trade(self, user_id: str, trade_data: Dict):
        self._log_audit("ORDER", user_id, "trade_executed", trade_data)

    # ── Audit log ─────────────────────────────────────────────────────────────

    def _log_audit(self, category: str, actor: str, action: str, data: Dict):
        self._sequence += 1
        record_str = json.dumps({
            "seq": self._sequence,
            "prev": self._last_hash,
            "ts": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }, sort_keys=True, default=str)
        chain_hash = hashlib.sha256(record_str.encode()).hexdigest()
        self._last_hash = chain_hash

        entry = {
            "sequence_number": self._sequence,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": "COMPLIANCE",
            "category": category,
            "actor": actor,
            "action": action,
            "data": data,
            "hash_chain": chain_hash,
        }
        self._audit_log.append(entry)

        if self._session_factory:
            try:
                from database.models import AuditLogEntry
                with self._session_factory() as session:
                    session.add(AuditLogEntry(
                        sequence_number=self._sequence,
                        level="COMPLIANCE",
                        category=category,
                        actor=actor,
                        action=action,
                        data_json=json.dumps(data, default=str),
                        hash_chain=chain_hash,
                    ))
                    session.commit()
            except Exception as exc:
                logger.error("Audit log DB write failed: %s", exc)

    def get_audit_log(self, limit: int = 100) -> List[Dict]:
        if self._session_factory:
            try:
                from database.models import AuditLogEntry
                with self._session_factory() as session:
                    rows = (
                        session.query(AuditLogEntry)
                        .order_by(AuditLogEntry.id.desc())
                        .limit(limit)
                        .all()
                    )
                    return [
                        {
                            "sequence_number": r.sequence_number,
                            "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                            "level": r.level,
                            "category": r.category,
                            "actor": r.actor,
                            "action": r.action,
                            "data": json.loads(r.data_json) if r.data_json else {},
                            "hash_chain": r.hash_chain,
                        }
                        for r in reversed(rows)
                    ]
            except Exception as exc:
                logger.error("Audit log DB read failed: %s", exc)

        return self._audit_log[-limit:]
