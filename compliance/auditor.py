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
import copy
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

UTC = timezone.utc
from enum import Enum
from typing import Any
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
        # Ensure the audit directory exists at construction time so that any
        # code that reads log_path (health checks, file listing) does not fail
        # with FileNotFoundError before the first append() call.
        Path(self.log_path).mkdir(parents=True, exist_ok=True)

    def append(self, level: AuditLevel, category: str, actor: str, action: str, data: dict):
        """Append immutable audit record."""
        self.sequence += 1

        # Capture timestamp once and reuse it in both the record and the hash.
        # Previously _calculate_hash() called datetime.now() independently,
        # producing a different timestamp than the one stored in the record,
        # which caused verify_integrity() to always return False.
        timestamp = datetime.now(UTC).isoformat()

        # Take ownership of the payload before hashing it.
        #
        # The record used to store the caller's dict by reference, so anything
        # the caller did to that dict afterwards — mutating it, or reusing one
        # scratch dict across several appends — retroactively changed
        # record.data. verify_integrity() then recomputed data_hash over the
        # mutated payload, disagreed with the stored hash, and reported
        # "INTEGRITY VIOLATION" for a log nobody had tampered with.
        #
        # That is the worst failure mode for a tamper-evidence mechanism: this
        # is the SEC/CFTC trade-reporting chain, and a detector that cries wolf
        # on ordinary caller aliasing trains operators to ignore it, so a real
        # violation lands in a channel that is already being tuned out.
        #
        # deepcopy (rather than a json round-trip) keeps the value types exactly
        # as they were, so nothing about serialisation behaviour changes.
        data = copy.deepcopy(data)

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
        """Write to append-only log (async when a loop is running, sync otherwise).

        Never raises. An audit write that fails must not crash the action it is
        recording — but it must be impossible to miss, because a compliance
        chain with a silent hole in it is worse than no chain: it still reports
        "verified".
        """
        filename = f"{self.log_path}audit_{datetime.now(UTC).strftime('%Y-%m')}.jsonl"

        # `mkdir` used to sit OUTSIDE this try. An unwritable location raised
        # FileNotFoundError straight into `append()`, so the audit write could
        # crash the superadmin action it was recording — while an ordinary
        # write failure two lines later was swallowed. One fault, two opposite
        # behaviours, neither designed.
        try:
            Path(self.log_path).mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            self._report_lost_record(record, exc, stage="mkdir")
            return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running event loop (e.g. called from sync context / tests)
            self._sync_write(filename, record)
            return

        task = loop.create_task(self._async_write(filename, record))
        task._hopefx_record = record  # so the callback can name what was lost
        # NOT `lambda _: None`. That callback threw the task's result away,
        # exceptions included, and under FastAPI this is the path production
        # takes. asyncio does eventually emit "Task exception was never
        # retrieved" when the task is garbage-collected, but that arrives at an
        # unpredictable time, from the `asyncio` logger, naming no record, no
        # actor and no action — nothing an operator would attribute to the
        # compliance chain.
        task.add_done_callback(self._report_write_task)

    def _report_write_task(self, task: Any) -> None:
        """Done-callback for the async write. Retrieves the result so a failure
        is reported here, with the record's identity, rather than surfacing as
        an anonymous asyncio warning whenever the task is collected."""
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            logger.error("Audit write task was cancelled; a record may not have been persisted")
            return
        except Exception:  # pragma: no cover - defensive
            return
        if exc is not None:
            self._report_lost_record(getattr(task, "_hopefx_record", None), exc, stage="async write")

    def _report_lost_record(self, record: AuditRecord | None, exc: BaseException, *, stage: str) -> None:
        """One place that says a record did not reach the log, and which one.

        The identity is the point. "Audit write failed: OSError" tells an
        operator nothing they can reconcile against; the sequence number, actor
        and action tell them exactly what is missing from the chain.
        """
        if record is None:
            logger.error("Audit record NOT PERSISTED (%s): %s — the chain on disk has a gap", stage, exc)
            return
        logger.error(
            "Audit record NOT PERSISTED (%s): seq=%s actor=%s action=%s — the chain on disk has a gap (%s)",
            stage,
            record.sequence_number,
            record.actor,
            record.action,
            exc,
        )

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
            self._report_lost_record(record, exc, stage="sync write")

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
                logger.error("❌ INTEGRITY VIOLATION at record %s", record.sequence_number)
                return False

            calculated_hash = record.hash_chain

        logger.info("✅ Audit log integrity verified")
        return True

    def verify_persisted_integrity(self, filename: str | None = None) -> bool | None:
        """Verify the chain in the LOG FILE — the artefact a regulator receives.

        `verify_integrity()` walks `self.records`, the in-memory list. That list
        still holds a record whose write failed, so it verifies clean over a
        chain the file does not contain: a check that reads its own memory
        cannot disagree with itself (F176). It also attests nothing about the
        file, which is the only thing anyone outside this process can inspect.

        Returns True (chain intact), False (a record is missing or altered), or
        **None when there is nothing to verify** — an empty or absent log is not
        a verified one, and reporting it as True is how an outage becomes a
        clean bill of health (Rule 2: an unmeasured value is absent, never
        best-case).
        """
        path = Path(filename) if filename else self._current_log_path()
        if path is None or not path.exists():
            logger.warning("Audit log not found at %s — nothing verified", path)
            return None

        rows: list[dict] = []
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                logger.error("Audit log line is not valid JSON (%s) — the chain cannot be verified", exc)
                return False
        if not rows:
            logger.warning("Audit log at %s is empty — nothing verified", path)
            return None

        prev = "0" * 64
        for row in sorted(rows, key=lambda r: r.get("seq", 0)):
            record_str = json.dumps(
                {
                    "seq": row.get("seq"),
                    "prev_hash": prev,
                    "timestamp": row.get("timestamp"),
                    "data_hash": hashlib.sha256(json.dumps(row.get("data"), sort_keys=True).encode()).hexdigest(),
                },
                sort_keys=True,
            )
            expected = hashlib.sha256(record_str.encode()).hexdigest()
            if row.get("hash") != expected:
                logger.error(
                    "PERSISTED AUDIT CHAIN BROKEN at seq=%s — a record is missing or was altered",
                    row.get("seq"),
                )
                return False
            prev = row["hash"]

        logger.info("Persisted audit chain verified over %d record(s)", len(rows))
        return True

    def _current_log_path(self) -> Path | None:
        """The file `_persist_record` is currently appending to."""
        try:
            return Path(f"{self.log_path}audit_{datetime.now(UTC).strftime('%Y-%m')}.jsonl")
        except Exception:  # pragma: no cover - defensive
            return None

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
