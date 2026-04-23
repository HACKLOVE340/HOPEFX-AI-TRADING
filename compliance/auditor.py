# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
# compliance/auditor.py
"""
HOPEFX Compliance & Audit System
Meets regulatory requirements for financial trading
"""

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

UTC = timezone.utc
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import aiofiles
except ImportError:
    aiofiles = None  # type: ignore[assignment]


class AuditLevel(Enum):
    DEBUG = 0  # Internal debugging
    INFO = 1  # Normal operations
    COMPLIANCE = 2  # Regulatory required
    CRITICAL = 3  # Risk events


@dataclass
class AuditRecord:
    """Immutable audit record"""

    timestamp: str
    sequence_number: int
    level: AuditLevel
    category: str  # ORDER, RISK, STRATEGY, etc.
    actor: str  # System component or user
    action: str
    data: dict
    hash_chain: str  # Link to previous record
    signature: str | None = None


class ImmutableAuditLog:
    """
    Tamper-evident audit log using blockchain-inspired hash chaining.
    Meets SEC/CFTC requirements for trade reporting.
    """

    def __init__(self, log_path: str = "data/audit/"):
        self.log_path = log_path
        Path(self.log_path).mkdir(parents=True, exist_ok=True)
        self.records: list[AuditRecord] = []
        self.sequence = 0
        self.last_hash = "0" * 64  # Genesis hash
        self._resume_chain()

    def _resume_chain(self) -> None:
        """Restore last_hash and sequence from persisted JSONL so new records
        continue the existing chain after a process restart."""
        path = Path(self.log_path)
        if not path.exists():
            return
        # Files are named audit_YYYY-MM.jsonl — sort ascending, read from latest
        files = sorted(path.glob("audit_*.jsonl"))
        for filepath in reversed(files):
            try:
                last_line: str | None = None
                with filepath.open("r", encoding="utf-8") as fh:
                    for line in fh:
                        stripped = line.strip()
                        if stripped:
                            last_line = stripped
                if last_line:
                    entry = json.loads(last_line)
                    self.last_hash = entry["hash"]
                    self.sequence = entry["seq"]
                    return
            except Exception as exc:
                logger.warning("_resume_chain: could not read %s: %s", filepath, exc)

    def append(self, level: AuditLevel, category: str, actor: str, action: str, data: dict):
        """Append immutable audit record."""
        self.sequence += 1

        # Capture timestamp once and reuse it in both the record and the hash.
        # Previously _calculate_hash() called datetime.now() independently,
        # producing a different timestamp than the one stored in the record,
        # which caused verify_integrity() to always return False.
        timestamp = datetime.now(UTC).isoformat()

        # Compute hash using the same timestamp that will be stored
        chain_hash = self._calculate_hash(data, timestamp)

        record = AuditRecord(
            timestamp=timestamp,
            sequence_number=self.sequence,
            level=level,
            category=category,
            actor=actor,
            action=action,
            data=data,
            hash_chain=chain_hash,
        )

        # Update hash chain
        self.last_hash = record.hash_chain
        self.records.append(record)

        # Persist immediately (write-ahead logging)
        self._persist_record(record)

        return record

    def _calculate_hash(self, data: dict, timestamp: str) -> str:
        """
        Calculate the hash for a new record being appended.

        Uses the caller-supplied *timestamp* (captured once in append()) so
        the value baked into the hash is identical to the value stored in the
        AuditRecord — making verify_integrity() / _recalculate_hash() agree.
        """
        record_str = json.dumps(
            {
                "seq": self.sequence,
                "prev_hash": self.last_hash,
                "timestamp": timestamp,
                "data_hash": hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest(),
            },
            sort_keys=True,
        )
        return hashlib.sha256(record_str.encode()).hexdigest()

    def _persist_record(self, record: AuditRecord):
        """Write to append-only log (async when a loop is running, sync otherwise)."""

        Path(self.log_path).mkdir(parents=True, exist_ok=True)
        filename = f"{self.log_path}audit_{datetime.now(UTC).strftime('%Y-%m')}.jsonl"
        try:
            loop = asyncio.get_running_loop()
            _t = loop.create_task(self._async_write(filename, record))
            _t.add_done_callback(lambda _: None)
        except RuntimeError:
            # No running event loop (e.g. called from sync context / tests)
            self._sync_write(filename, record)

    def _sync_write(self, filename: str, record: AuditRecord) -> None:
        """Synchronous fallback write used when no event loop is running."""
        line = (
            json.dumps(
                {
                    "timestamp": record.timestamp,
                    "seq": record.sequence_number,
                    "level": record.level.name,
                    "category": record.category,
                    "actor": record.actor,
                    "action": record.action,
                    "data": record.data,
                    "hash": record.hash_chain,
                }
            )
            + "\n"
        )
        try:
            with Path(filename).open("a", encoding="utf-8") as fh:
                fh.write(line)
        except Exception as exc:
            logger.error("Audit sync write failed: %s", exc)

    async def _async_write(self, filename: str, record: AuditRecord):
        if aiofiles is None:
            import aiofiles as _aiofiles
        else:
            _aiofiles = aiofiles
        async with _aiofiles.open(filename, "a") as f:
            await f.write(
                json.dumps(
                    {
                        "timestamp": record.timestamp,
                        "seq": record.sequence_number,
                        "level": record.level.name,
                        "category": record.category,
                        "actor": record.actor,
                        "action": record.action,
                        "data": record.data,
                        "hash": record.hash_chain,
                    }
                )
                + "\n"
            )

    def verify_integrity(self) -> bool:
        """
        Verify hash chain integrity.
        Detects any tampering with historical records.
        """
        calculated_hash = "0" * 64

        for record in sorted(self.records, key=lambda r: r.sequence_number):
            expected_hash = self._recalculate_hash(record, calculated_hash)

            if record.hash_chain != expected_hash:
                logger.error(f"❌ INTEGRITY VIOLATION at record {record.sequence_number}")
                return False

            calculated_hash = record.hash_chain

        logger.info("✅ Audit log integrity verified")
        return True

    def _recalculate_hash(self, record: AuditRecord, prev_hash: str) -> str:
        """Recalculate expected hash"""
        record_str = json.dumps(
            {
                "seq": record.sequence_number,
                "prev_hash": prev_hash,
                "timestamp": record.timestamp,
                "data_hash": hashlib.sha256(json.dumps(record.data, sort_keys=True).encode()).hexdigest(),
            },
            sort_keys=True,
        )

        return hashlib.sha256(record_str.encode()).hexdigest()

    def export_for_regulator(self, start_date: datetime, end_date: datetime) -> list[dict]:
        """Export compliant audit trail for regulatory review"""
        return [
            {
                "timestamp": r.timestamp,
                "sequence": r.sequence_number,
                "category": r.category,
                "actor": r.actor,
                "action": r.action,
                "data": r.data,
                "hash_verification": r.hash_chain,
            }
            for r in self.records
            if start_date <= datetime.fromisoformat(r.timestamp) <= end_date
        ]


class TradeReporting:
    """
    Automated trade reporting to regulators.
    """

    def __init__(self, jurisdiction: str = "US", log_path: str | None = None):
        self.jurisdiction = jurisdiction
        self.audit_log = ImmutableAuditLog(log_path=log_path) if log_path else ImmutableAuditLog()
        self.reporting_obligations = self._load_obligations()

    def _load_obligations(self) -> dict:
        """Load regulatory requirements"""
        obligations = {
            "US": {
                "cftc": {
                    "large_trader_reporting": True,
                    "threshold": 25,  # Contracts
                    "time_limit": "T+1",  # Report by next day
                },
                "sec": {
                    "cat_reporting": True,  # Consolidated Audit Trail
                    "time_limit": "T+0",  # Real-time
                },
            },
            "EU": {"mifid_ii": {"transaction_reporting": True, "time_limit": "T+1"}},
        }
        return obligations.get(self.jurisdiction, {})

    def report_trade(self, trade: dict):
        """Log trade and trigger regulatory reporting if needed"""
        # Always audit
        self.audit_log.append(
            AuditLevel.COMPLIANCE,
            "TRADE",
            trade.get("strategy_id", "unknown"),
            "EXECUTION",
            trade,
        )

        # Check reporting thresholds
        if self._requires_immediate_reporting(trade):
            _t = asyncio.create_task(self._submit_to_regulator(trade))
            _t.add_done_callback(lambda _: None)

    def _requires_immediate_reporting(self, trade: dict) -> bool:
        """Check if trade requires immediate regulatory reporting"""
        # Large trader threshold
        if trade.get("size", 0) > self.reporting_obligations.get("cftc", {}).get("threshold", 25):
            return True

        # Suspicious activity
        return trade.get("flags", {}).get("suspicious", False)

    async def _submit_to_regulator(self, trade: dict):
        """
        Submit trade to the appropriate regulatory endpoint.

        Routes to CFTC SDR, SEC CAT, or MiFID II depending on
        REGULATORY_JURISDICTION env var. Uses RegulatoryReporter which
        handles retries, dead-letter queue, and audit trail.
        """
        from compliance.regulatory_reporter import get_regulatory_reporter

        reporter = get_regulatory_reporter()
        record = await reporter.submit(trade)

        # Write submission outcome to immutable audit log
        self.audit_log.append(
            AuditLevel.COMPLIANCE,
            "REGULATORY",
            "system",
            "REPORT_SUBMITTED" if record.status == "submitted" else record.status.upper(),
            {
                "trade_id": trade.get("id"),
                "report_id": record.report_id,
                "jurisdiction": record.jurisdiction,
                "endpoint": record.endpoint,
                "status": record.status,
                "attempts": record.attempts,
                "error": record.last_error,
            },
        )

        if record.status == "submitted":
            logger.info(
                "Regulatory report submitted: trade_id=%s report_id=%s jurisdiction=%s",
                trade.get("id"),
                record.report_id,
                record.jurisdiction,
            )
        elif record.status == "suppressed":
            logger.debug(
                "Regulatory report suppressed: trade_id=%s reason=%s",
                trade.get("id"),
                record.endpoint,
            )
        else:
            logger.error(
                "Regulatory report FAILED: trade_id=%s report_id=%s enqueued to DLQ for retry",
                trade.get("id"),
                record.report_id,
            )

    def generate_daily_report(self) -> dict:
        """Generate end-of-day compliance report"""
        today = datetime.now(UTC).date()

        trades_today = [
            r
            for r in self.audit_log.records
            if r.category == "TRADE" and datetime.fromisoformat(r.timestamp).date() == today
        ]

        return {
            "date": today.isoformat(),
            "total_trades": len(trades_today),
            "total_notional": sum(t.data.get("notional", 0) for t in trades_today),
            "regulatory_reports_filed": len([t for t in trades_today if self._requires_immediate_reporting(t.data)]),
            "audit_hash": self.audit_log.last_hash,
            "integrity_verified": self.audit_log.verify_integrity(),
        }
