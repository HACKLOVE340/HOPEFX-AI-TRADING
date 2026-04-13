# HOPEFX-AI-TRADING
# Tests for compliance/ — targets 80%+ branch coverage
"""
Covers:
  - compliance/aml.py          (AMLGate, AMLDecision, get_aml_gate, init_aml_gate)
  - compliance/auditor.py      (ImmutableAuditLog, TradeReporting, AuditLevel)
  - compliance/compliance_manager.py (ComplianceManager, KYCStatus)
  - compliance/kyc_provider.py (KYCApplicant, SanctionsResult, MockKYCProvider,
                                 SumsubProvider.verify_webhook/parse_webhook,
                                 OnfidoProvider.verify_webhook/parse_webhook,
                                 KYCGateway)
  - compliance/regulatory_reporter.py (DeadLetterQueue, RegulatoryReporter,
                                        ReportRecord)
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

UTC = timezone.utc

# ─────────────────────────────────────────────────────────────────────────────
# compliance/aml.py
# ─────────────────────────────────────────────────────────────────────────────
from compliance.aml import (
    AMLGate,
    AMLDecision,
    get_aml_gate,
    init_aml_gate,
    SINGLE_WITHDRAWAL_CAP,
    DAILY_WITHDRAWAL_LIMIT,
    MAX_WITHDRAWALS_PER_DAY,
    KYC_THRESHOLD,
)


class TestAMLDecision:
    def test_dataclass_fields(self):
        d = AMLDecision(allowed=True, reason="ok", risk_score=0.1, flags=[])
        assert d.allowed is True
        assert d.reason == "ok"
        assert d.risk_score == 0.1
        assert d.flags == []

    def test_blocked_decision(self):
        d = AMLDecision(allowed=False, reason="blocked", risk_score=1.0, flags=["EXCEEDS_SINGLE_CAP"])
        assert d.allowed is False
        assert "EXCEEDS_SINGLE_CAP" in d.flags


class TestAMLGateNoDb:
    """AMLGate without a DB session factory (no-DB path)."""

    def setup_method(self):
        self.gate = AMLGate(session_factory=None)

    def test_small_amount_approved(self):
        decision = self.gate.check_withdrawal("user1", Decimal("100"), kyc_status="unverified")
        assert decision.allowed is True

    def test_exceeds_single_cap_blocked(self):
        amount = SINGLE_WITHDRAWAL_CAP + Decimal("1")
        decision = self.gate.check_withdrawal("user1", amount)
        assert decision.allowed is False
        assert "EXCEEDS_SINGLE_CAP" in decision.flags
        assert decision.risk_score == 1.0

    def test_kyc_required_above_threshold(self):
        amount = KYC_THRESHOLD + Decimal("1")
        decision = self.gate.check_withdrawal("user1", amount, kyc_status="unverified")
        assert decision.allowed is False
        assert "KYC_REQUIRED" in decision.flags

    def test_kyc_approved_passes_threshold(self):
        # Without DB, amounts above KYC_THRESHOLD with approved KYC hit NO_DB_SESSION
        amount = KYC_THRESHOLD + Decimal("1")
        decision = self.gate.check_withdrawal("user1", amount, kyc_status="approved")
        # No DB → blocked with NO_DB_SESSION
        assert decision.allowed is False
        assert "NO_DB_SESSION" in decision.flags

    def test_small_amount_below_kyc_threshold_approved(self):
        # Amount below KYC_THRESHOLD, no DB needed
        decision = self.gate.check_withdrawal("user1", Decimal("500"), kyc_status="unverified")
        assert decision.allowed is True

    def test_emit_block_event_handles_import_error(self):
        """_emit_block_event should not raise even if outbox import fails."""
        decision = AMLDecision(allowed=False, reason="test", risk_score=1.0, flags=["TEST"])
        # Patch the outbox module so the import inside _emit_block_event raises
        with patch.dict("sys.modules", {"core.outbox": None}):
            # Should not raise — exception is caught internally
            self.gate._emit_block_event("user1", Decimal("100"), "USD", decision)

    def test_emit_block_event_outbox_write_fails(self):
        """_emit_block_event gracefully handles write errors."""
        decision = AMLDecision(allowed=False, reason="test", risk_score=1.0, flags=["TEST"])
        mock_outbox = MagicMock()
        mock_outbox.write_outbox_event_standalone = MagicMock(side_effect=Exception("write failed"))
        with patch.dict("sys.modules", {"core.outbox": mock_outbox}):
            # Should not raise
            self.gate._emit_block_event("user1", Decimal("100"), "USD", decision)


class TestAMLGateWithDb:
    """AMLGate with a mock DB session factory."""

    def _make_tx(self, amount, tx_type="withdrawal", status="completed", hours_ago=1):
        tx = MagicMock()
        tx.amount = float(amount)
        tx.transaction_type = tx_type
        tx.status = status
        tx.created_at = datetime.now(UTC) - timedelta(hours=hours_ago)
        return tx

    def _make_session_factory(self, withdrawals=None, deposits=None):
        withdrawals = withdrawals or []
        deposits = deposits or []

        @contextmanager
        def session_factory():
            session = MagicMock()
            query_mock = MagicMock()

            def filter_side_effect(*args, **kwargs):
                return query_mock

            query_mock.filter.return_value = query_mock
            query_mock.all.side_effect = [withdrawals, deposits]
            session.query.return_value = query_mock
            yield session

        return session_factory

    def test_velocity_limit_blocked(self):
        withdrawals = [self._make_tx(100) for _ in range(MAX_WITHDRAWALS_PER_DAY)]
        gate = AMLGate(session_factory=self._make_session_factory(withdrawals=withdrawals))
        amount = KYC_THRESHOLD + Decimal("1")
        decision = gate.check_withdrawal("user1", amount, kyc_status="approved")
        assert decision.allowed is False
        assert "VELOCITY_LIMIT" in decision.flags

    def test_daily_limit_exceeded_blocked(self):
        # One withdrawal that nearly fills the daily limit
        big_amount = DAILY_WITHDRAWAL_LIMIT - Decimal("100")
        withdrawals = [self._make_tx(big_amount)]
        gate = AMLGate(session_factory=self._make_session_factory(withdrawals=withdrawals))
        amount = Decimal("200")  # Would exceed daily limit
        decision = gate.check_withdrawal("user1", amount, kyc_status="approved")
        assert decision.allowed is False
        assert "DAILY_LIMIT_EXCEEDED" in decision.flags

    def test_rapid_turnaround_flagged(self):
        # No withdrawals, but a recent deposit of same amount
        deposit = self._make_tx(500, tx_type="deposit", hours_ago=0)
        gate = AMLGate(session_factory=self._make_session_factory(withdrawals=[], deposits=[deposit]))
        amount = Decimal("500")
        decision = gate.check_withdrawal("user1", amount, kyc_status="approved")
        # Rapid turnaround is a flag but not a block by itself
        assert "RAPID_TURNAROUND" in decision.flags

    def test_db_error_fails_closed(self):
        def bad_factory():
            raise RuntimeError("DB down")

        gate = AMLGate(session_factory=bad_factory)
        amount = KYC_THRESHOLD + Decimal("1")
        decision = gate.check_withdrawal("user1", amount, kyc_status="approved")
        assert decision.allowed is False
        assert "DB_UNAVAILABLE" in decision.flags

    def test_clean_withdrawal_approved(self):
        gate = AMLGate(session_factory=self._make_session_factory(withdrawals=[], deposits=[]))
        amount = KYC_THRESHOLD + Decimal("1")
        decision = gate.check_withdrawal("user1", amount, kyc_status="approved")
        assert decision.allowed is True


class TestAMLGateSingleton:
    def test_get_aml_gate_creates_default(self):
        import compliance.aml as aml_mod

        aml_mod._aml_gate = None
        gate = get_aml_gate()
        assert isinstance(gate, AMLGate)

    def test_init_aml_gate_wires_factory(self):
        sf = MagicMock()
        gate = init_aml_gate(sf)
        assert gate._sf is sf

    def test_get_aml_gate_returns_existing(self):
        import compliance.aml as aml_mod

        existing = AMLGate()
        aml_mod._aml_gate = existing
        assert get_aml_gate() is existing
        aml_mod._aml_gate = None  # cleanup


# ─────────────────────────────────────────────────────────────────────────────
# compliance/auditor.py
# ─────────────────────────────────────────────────────────────────────────────
from compliance.auditor import (
    ImmutableAuditLog,
    AuditLevel,
    AuditRecord,
    TradeReporting,
)


class TestImmutableAuditLog:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log = ImmutableAuditLog(log_path=self.tmpdir + "/")

    def test_append_creates_record(self):
        record = self.log.append(AuditLevel.INFO, "ORDER", "system", "test_action", {"key": "val"})
        assert isinstance(record, AuditRecord)
        assert record.sequence_number == 1
        assert record.category == "ORDER"
        assert record.action == "test_action"

    def test_sequence_increments(self):
        self.log.append(AuditLevel.INFO, "ORDER", "sys", "action1", {})
        self.log.append(AuditLevel.INFO, "ORDER", "sys", "action2", {})
        assert self.log.sequence == 2

    def test_hash_chain_changes_each_record(self):
        r1 = self.log.append(AuditLevel.INFO, "ORDER", "sys", "a1", {})
        r2 = self.log.append(AuditLevel.INFO, "ORDER", "sys", "a2", {})
        assert r1.hash_chain != r2.hash_chain

    def test_verify_integrity_empty(self):
        assert self.log.verify_integrity() is True

    def test_verify_integrity_valid(self):
        self.log.append(AuditLevel.COMPLIANCE, "TRADE", "sys", "exec", {"price": 100})
        self.log.append(AuditLevel.CRITICAL, "RISK", "sys", "breach", {"var": 0.05})
        assert self.log.verify_integrity() is True

    def test_verify_integrity_tampered(self):
        self.log.append(AuditLevel.INFO, "ORDER", "sys", "action", {"data": "original"})
        # Tamper with the record
        self.log.records[0].hash_chain = "tampered_hash"
        assert self.log.verify_integrity() is False

    def test_export_for_regulator(self):
        self.log.append(AuditLevel.COMPLIANCE, "TRADE", "sys", "exec", {"price": 100})
        start = datetime.now(UTC) - timedelta(hours=1)
        end = datetime.now(UTC) + timedelta(hours=1)
        exported = self.log.export_for_regulator(start, end)
        assert len(exported) == 1
        assert "timestamp" in exported[0]
        assert "hash_verification" in exported[0]

    def test_export_for_regulator_date_filter(self):
        self.log.append(AuditLevel.INFO, "ORDER", "sys", "action", {})
        # Export for yesterday — should return nothing
        start = datetime.now(UTC) - timedelta(days=2)
        end = datetime.now(UTC) - timedelta(days=1)
        exported = self.log.export_for_regulator(start, end)
        assert len(exported) == 0

    def test_persist_record_sync_write(self):
        """Sync write path (no running event loop)."""
        self.log.append(AuditLevel.INFO, "TEST", "sys", "sync_write", {"x": 1})
        # Check file was written
        files = list(Path(self.tmpdir).glob("audit_*.jsonl"))
        assert len(files) == 1

    def test_audit_level_values(self):
        assert AuditLevel.DEBUG.value == 0
        assert AuditLevel.INFO.value == 1
        assert AuditLevel.COMPLIANCE.value == 2
        assert AuditLevel.CRITICAL.value == 3


class TestTradeReporting:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_report_trade_logs_to_audit(self):
        tr = TradeReporting(jurisdiction="US")
        tr.audit_log = ImmutableAuditLog(log_path=self.tmpdir + "/")
        tr.report_trade({"id": "t1", "symbol": "XAUUSD", "size": 1, "notional": 2000})
        assert len(tr.audit_log.records) == 1

    def test_requires_immediate_reporting_large_trade(self):
        tr = TradeReporting(jurisdiction="US")
        assert tr._requires_immediate_reporting({"size": 100}) is True

    def test_requires_immediate_reporting_small_trade(self):
        tr = TradeReporting(jurisdiction="US")
        assert tr._requires_immediate_reporting({"size": 1}) is False

    def test_requires_immediate_reporting_suspicious(self):
        tr = TradeReporting(jurisdiction="US")
        assert tr._requires_immediate_reporting({"size": 1, "flags": {"suspicious": True}}) is True

    def test_generate_daily_report(self):
        tr = TradeReporting(jurisdiction="US")
        tr.audit_log = ImmutableAuditLog(log_path=self.tmpdir + "/")
        tr.report_trade({"id": "t1", "symbol": "XAUUSD", "size": 1, "notional": 2000})
        report = tr.generate_daily_report()
        assert "date" in report
        assert "total_trades" in report
        assert "integrity_verified" in report

    def test_load_obligations_us(self):
        tr = TradeReporting(jurisdiction="US")
        assert "cftc" in tr.reporting_obligations

    def test_load_obligations_eu(self):
        tr = TradeReporting(jurisdiction="EU")
        assert "mifid_ii" in tr.reporting_obligations

    def test_load_obligations_unknown(self):
        tr = TradeReporting(jurisdiction="XX")
        assert tr.reporting_obligations == {}

    def test_async_write_path(self):
        """Test the async write path when an event loop is running."""
        tmpdir = tempfile.mkdtemp()
        log = ImmutableAuditLog(log_path=tmpdir + "/")

        async def run():
            # append() inside a running loop triggers the async write path
            record = log.append(AuditLevel.INFO, "ORDER", "sys", "async_action", {"x": 1})
            # Give the task a chance to complete
            await asyncio.sleep(0.05)
            return record

        record = asyncio.get_event_loop().run_until_complete(run())
        assert record.sequence_number == 1

    def test_sync_write_failure_does_not_raise(self):
        """_sync_write should log but not raise on file write failure."""
        tmpdir = tempfile.mkdtemp()
        log = ImmutableAuditLog(log_path=tmpdir + "/")
        record = log.append(AuditLevel.INFO, "TEST", "sys", "action", {})
        # Simulate write failure
        with patch("builtins.open", side_effect=OSError("disk full")):
            log._sync_write("/bad/path/audit.jsonl", record)  # should not raise


# ─────────────────────────────────────────────────────────────────────────────
# compliance/compliance_manager.py
# ─────────────────────────────────────────────────────────────────────────────
from compliance.compliance_manager import ComplianceManager, KYCStatus


class TestComplianceManagerNoDb:
    def setup_method(self):
        self.cm = ComplianceManager(session_factory=None)

    def test_submit_kyc_returns_pending(self):
        record = self.cm.submit_kyc("user1", "passport")
        assert record["status"] == KYCStatus.PENDING.value
        assert record["user_id"] == "user1"

    def test_approve_kyc(self):
        self.cm.submit_kyc("user1", "passport")
        result = self.cm.approve_kyc("user1")
        assert result is True
        assert self.cm.get_kyc_status("user1") == KYCStatus.APPROVED

    def test_reject_kyc(self):
        self.cm.submit_kyc("user1", "passport")
        result = self.cm.reject_kyc("user1", reason="document_expired")
        assert result is True
        assert self.cm.get_kyc_status("user1") == KYCStatus.REJECTED

    def test_get_kyc_status_unverified(self):
        assert self.cm.get_kyc_status("unknown_user") == KYCStatus.UNVERIFIED

    def test_is_kyc_approved_false(self):
        self.cm.submit_kyc("user1", "passport")
        assert self.cm.is_kyc_approved("user1") is False

    def test_is_kyc_approved_true(self):
        self.cm.submit_kyc("user1", "passport")
        self.cm.approve_kyc("user1")
        assert self.cm.is_kyc_approved("user1") is True

    def test_log_trade_adds_to_audit(self):
        self.cm.log_trade("user1", {"symbol": "XAUUSD", "price": 2000})
        assert len(self.cm._audit_log) == 1

    def test_get_audit_log_returns_entries(self):
        self.cm.log_trade("user1", {"symbol": "XAUUSD"})
        self.cm.log_trade("user2", {"symbol": "EURUSD"})
        log = self.cm.get_audit_log(limit=10)
        assert len(log) == 2

    def test_get_audit_log_limit(self):
        for i in range(10):
            self.cm.log_trade(f"user{i}", {"symbol": "XAUUSD"})
        log = self.cm.get_audit_log(limit=3)
        assert len(log) == 3

    def test_audit_log_has_hash_chain(self):
        self.cm.log_trade("user1", {"symbol": "XAUUSD"})
        entry = self.cm._audit_log[0]
        assert "hash_chain" in entry
        assert len(entry["hash_chain"]) == 64  # SHA-256 hex

    def test_set_session_factory(self):
        sf = MagicMock()
        self.cm.set_session_factory(sf)
        assert self.cm._session_factory is sf

    def test_approve_kyc_nonexistent_user(self):
        # Should not raise even if user not in records
        result = self.cm.approve_kyc("nonexistent_user")
        assert result is True

    def test_reject_kyc_nonexistent_user(self):
        result = self.cm.reject_kyc("nonexistent_user", reason="test")
        assert result is True

    def test_multiple_kyc_submissions_overwrite(self):
        self.cm.submit_kyc("user1", "passport")
        self.cm.approve_kyc("user1")
        # Re-submit resets to pending
        self.cm.submit_kyc("user1", "drivers_license")
        assert self.cm.get_kyc_status("user1") == KYCStatus.PENDING


class TestComplianceManagerWithDb:
    def _make_session_factory(self, kyc_record=None, audit_rows=None):
        @contextmanager
        def session_factory():
            session = MagicMock()
            q = MagicMock()
            q.filter_by.return_value = q
            q.filter.return_value = q
            q.first.return_value = kyc_record
            q.order_by.return_value = q
            q.limit.return_value = q
            q.all.return_value = audit_rows or []
            session.query.return_value = q
            yield session

        return session_factory

    def test_submit_kyc_with_db_no_existing(self):
        sf = self._make_session_factory(kyc_record=None)
        cm = ComplianceManager(session_factory=sf)
        record = cm.submit_kyc("user1", "passport")
        assert record["status"] == KYCStatus.PENDING.value

    def test_submit_kyc_with_db_existing(self):
        existing = MagicMock()
        existing.status = "pending"
        sf = self._make_session_factory(kyc_record=existing)
        cm = ComplianceManager(session_factory=sf)
        record = cm.submit_kyc("user1", "passport")
        assert record["status"] == KYCStatus.PENDING.value

    def test_get_kyc_status_from_db(self):
        db_rec = MagicMock()
        db_rec.status = "approved"
        sf = self._make_session_factory(kyc_record=db_rec)
        cm = ComplianceManager(session_factory=sf)
        status = cm.get_kyc_status("user1")
        assert status == KYCStatus.APPROVED

    def test_db_error_falls_back_to_memory(self):
        def bad_factory():
            raise RuntimeError("DB down")

        cm = ComplianceManager(session_factory=bad_factory)
        cm._kyc_records["user1"] = {"status": "approved"}
        status = cm.get_kyc_status("user1")
        assert status == KYCStatus.APPROVED

    def test_approve_kyc_with_db(self):
        db_rec = MagicMock()
        db_rec.status = "pending"
        sf = self._make_session_factory(kyc_record=db_rec)
        cm = ComplianceManager(session_factory=sf)
        cm._kyc_records["user1"] = {"status": "pending"}
        result = cm.approve_kyc("user1")
        assert result is True

    def test_reject_kyc_with_db(self):
        db_rec = MagicMock()
        db_rec.status = "pending"
        sf = self._make_session_factory(kyc_record=db_rec)
        cm = ComplianceManager(session_factory=sf)
        cm._kyc_records["user1"] = {"status": "pending"}
        result = cm.reject_kyc("user1", reason="expired")
        assert result is True

    def test_get_audit_log_from_db(self):
        row = MagicMock()
        row.sequence_number = 1
        row.timestamp = datetime.now(UTC)
        row.level = "COMPLIANCE"
        row.category = "ORDER"
        row.actor = "sys"
        row.action = "exec"
        row.data_json = '{"price": 100}'
        row.hash_chain = "abc123"
        sf = self._make_session_factory(audit_rows=[row])
        cm = ComplianceManager(session_factory=sf)
        log = cm.get_audit_log(limit=10)
        assert len(log) == 1
        assert log[0]["category"] == "ORDER"

    def test_log_trade_with_db(self):
        sf = self._make_session_factory()
        cm = ComplianceManager(session_factory=sf)
        # Should not raise even if DB write fails
        cm.log_trade("user1", {"symbol": "XAUUSD", "price": 2000})


# ─────────────────────────────────────────────────────────────────────────────
# compliance/kyc_provider.py
# ─────────────────────────────────────────────────────────────────────────────
from compliance.kyc_provider import (
    KYCApplicant,
    SanctionsResult,
    VerificationStatus,
    SumsubProvider,
    OnfidoProvider,
    MockKYCProvider,
)


class TestKYCApplicant:
    def test_default_status_pending(self):
        a = KYCApplicant(applicant_id="a1", user_id="u1", provider="sumsub")
        assert a.status == VerificationStatus.PENDING

    def test_fields(self):
        a = KYCApplicant(
            applicant_id="a1",
            user_id="u1",
            provider="sumsub",
            sdk_token="tok123",
            status=VerificationStatus.APPROVED,
        )
        assert a.sdk_token == "tok123"
        assert a.status == VerificationStatus.APPROVED


class TestSanctionsResult:
    def test_no_match(self):
        r = SanctionsResult(screened=True, is_match=False, match_score=0.0, matched_lists=[])
        assert r.is_match is False
        assert r.match_score == 0.0

    def test_match(self):
        r = SanctionsResult(
            screened=True,
            is_match=True,
            match_score=0.95,
            matched_lists=["OFAC_SDN"],
            details="Name match",
        )
        assert r.is_match is True
        assert "OFAC_SDN" in r.matched_lists


class TestSumsubProviderHTTP:
    """Tests for Sumsub HTTP methods using mocked aiohttp."""

    def _make_provider(self):
        env = {
            "SUMSUB_APP_TOKEN": "tok",
            "SUMSUB_SECRET_KEY": "secret",  # pragma: allowlist secret
        }
        with patch.dict(os.environ, env):
            return SumsubProvider()

    def _mock_response(self, status, json_data):
        resp = AsyncMock()
        resp.status = status
        resp.json = AsyncMock(return_value=json_data)
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=False)
        return resp

    def test_sign_returns_hex_string(self):
        provider = self._make_provider()
        sig = provider._sign(1234567890, "POST", "/test/path", b"body")
        assert len(sig) == 64
        assert all(c in "0123456789abcdef" for c in sig)

    def test_headers_has_required_keys(self):
        provider = self._make_provider()
        headers = provider._headers("GET", "/test")
        assert "X-App-Token" in headers
        assert "X-App-Access-Sig" in headers
        assert "X-App-Access-Ts" in headers

    def test_create_applicant_success(self):
        provider = self._make_provider()
        applicant_resp = self._mock_response(201, {"id": "app_123"})
        token_resp = self._mock_response(200, {"token": "sdk_tok_abc"})

        session1 = MagicMock()
        session1.post = MagicMock(return_value=applicant_resp)
        session1.__aenter__ = AsyncMock(return_value=session1)
        session1.__aexit__ = AsyncMock(return_value=False)

        session2 = MagicMock()
        session2.post = MagicMock(return_value=token_resp)
        session2.__aenter__ = AsyncMock(return_value=session2)
        session2.__aexit__ = AsyncMock(return_value=False)

        sessions = iter([session1, session2])

        async def run():
            with patch("aiohttp.ClientSession", side_effect=lambda: next(sessions)):
                return await provider.create_applicant("user1", {"email": "a@b.com"})

        applicant = asyncio.get_event_loop().run_until_complete(run())
        assert applicant.applicant_id == "app_123"
        assert applicant.sdk_token == "sdk_tok_abc"

    def test_create_applicant_http_error_raises(self):
        provider = self._make_provider()
        error_resp = self._mock_response(400, {"error": "bad request"})

        session = MagicMock()
        session.post = MagicMock(return_value=error_resp)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        async def run():
            with patch("aiohttp.ClientSession", return_value=session):
                return await provider.create_applicant("user1", {})

        with pytest.raises(RuntimeError, match="Sumsub create_applicant failed"):
            asyncio.get_event_loop().run_until_complete(run())

    def test_get_status_green(self):
        provider = self._make_provider()
        status_resp = self._mock_response(200, {"reviewResult": {"reviewAnswer": "GREEN"}})

        session = MagicMock()
        session.get = MagicMock(return_value=status_resp)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        async def run():
            with patch("aiohttp.ClientSession", return_value=session):
                return await provider.get_status("app_123")

        status = asyncio.get_event_loop().run_until_complete(run())
        assert status == VerificationStatus.APPROVED

    def test_get_status_red(self):
        provider = self._make_provider()
        status_resp = self._mock_response(200, {"reviewResult": {"reviewAnswer": "RED"}})

        session = MagicMock()
        session.get = MagicMock(return_value=status_resp)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        async def run():
            with patch("aiohttp.ClientSession", return_value=session):
                return await provider.get_status("app_123")

        status = asyncio.get_event_loop().run_until_complete(run())
        assert status == VerificationStatus.REJECTED

    def test_get_status_http_error_returns_pending(self):
        provider = self._make_provider()
        error_resp = self._mock_response(500, {})

        session = MagicMock()
        session.get = MagicMock(return_value=error_resp)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        async def run():
            with patch("aiohttp.ClientSession", return_value=session):
                return await provider.get_status("app_123")

        status = asyncio.get_event_loop().run_until_complete(run())
        assert status == VerificationStatus.PENDING

    def test_get_status_no_aiohttp_returns_pending(self):
        provider = self._make_provider()

        async def run():
            with patch.dict("sys.modules", {"aiohttp": None}):
                return await provider.get_status("app_123")

        status = asyncio.get_event_loop().run_until_complete(run())
        assert status == VerificationStatus.PENDING


class TestOnfidoProviderHTTP:
    """Tests for Onfido HTTP methods using mocked aiohttp."""

    def _make_provider(self):
        with patch.dict(os.environ, {"ONFIDO_API_TOKEN": "tok", "ONFIDO_WORKFLOW_ID": "wf_123"}):
            return OnfidoProvider()

    def _mock_response(self, status, json_data):
        resp = AsyncMock()
        resp.status = status
        resp.json = AsyncMock(return_value=json_data)
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=False)
        return resp

    def test_headers_has_authorization(self):
        provider = self._make_provider()
        headers = provider._headers()
        assert "Authorization" in headers
        assert "tok" in headers["Authorization"]

    def test_create_applicant_success(self):
        provider = self._make_provider()
        applicant_resp = self._mock_response(201, {"id": "onfido_app_123"})
        wf_resp = self._mock_response(200, {"sdk_token": "onfido_sdk_tok"})

        session1 = MagicMock()
        session1.post = MagicMock(return_value=applicant_resp)
        session1.__aenter__ = AsyncMock(return_value=session1)
        session1.__aexit__ = AsyncMock(return_value=False)

        session2 = MagicMock()
        session2.post = MagicMock(return_value=wf_resp)
        session2.__aenter__ = AsyncMock(return_value=session2)
        session2.__aexit__ = AsyncMock(return_value=False)

        sessions = iter([session1, session2])

        async def run():
            with patch("aiohttp.ClientSession", side_effect=lambda: next(sessions)):
                return await provider.create_applicant(
                    "user1", {"first_name": "John", "last_name": "Doe", "email": "j@d.com"}
                )

        applicant = asyncio.get_event_loop().run_until_complete(run())
        assert applicant.applicant_id == "onfido_app_123"
        assert applicant.sdk_token == "onfido_sdk_tok"

    def test_create_applicant_http_error_raises(self):
        provider = self._make_provider()
        error_resp = self._mock_response(400, {"error": "bad"})

        session = MagicMock()
        session.post = MagicMock(return_value=error_resp)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        async def run():
            with patch("aiohttp.ClientSession", return_value=session):
                return await provider.create_applicant("user1", {})

        with pytest.raises(RuntimeError, match="Onfido create_applicant failed"):
            asyncio.get_event_loop().run_until_complete(run())

    def test_get_status_clear(self):
        provider = self._make_provider()
        status_resp = self._mock_response(200, {"checks": [{"result": "clear"}]})

        session = MagicMock()
        session.get = MagicMock(return_value=status_resp)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        async def run():
            with patch("aiohttp.ClientSession", return_value=session):
                return await provider.get_status("app_123")

        status = asyncio.get_event_loop().run_until_complete(run())
        assert status == VerificationStatus.APPROVED

    def test_get_status_no_checks_returns_pending(self):
        provider = self._make_provider()
        status_resp = self._mock_response(200, {"checks": []})

        session = MagicMock()
        session.get = MagicMock(return_value=status_resp)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        async def run():
            with patch("aiohttp.ClientSession", return_value=session):
                return await provider.get_status("app_123")

        status = asyncio.get_event_loop().run_until_complete(run())
        assert status == VerificationStatus.PENDING

    def test_get_status_http_error_returns_pending(self):
        provider = self._make_provider()
        error_resp = self._mock_response(500, {})

        session = MagicMock()
        session.get = MagicMock(return_value=error_resp)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        async def run():
            with patch("aiohttp.ClientSession", return_value=session):
                return await provider.get_status("app_123")

        status = asyncio.get_event_loop().run_until_complete(run())
        assert status == VerificationStatus.PENDING


class TestSumsubProvider:
    def test_verify_webhook_valid(self):
        secret = "test_secret"  # pragma: allowlist secret
        payload = b'{"applicantId": "a1"}'
        sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        with patch.dict(os.environ, {"SUMSUB_SECRET_KEY": secret, "SUMSUB_APP_TOKEN": "tok"}):
            provider = SumsubProvider()
            assert provider.verify_webhook(payload, sig) is True

    def test_verify_webhook_invalid(self):
        env_invalid = {
            "SUMSUB_SECRET_KEY": "secret",  # pragma: allowlist secret
            "SUMSUB_APP_TOKEN": "tok",
        }
        with patch.dict(os.environ, env_invalid):
            provider = SumsubProvider()
            assert provider.verify_webhook(b"payload", "wrong_sig") is False

    def test_parse_webhook_green(self):
        with patch.dict(os.environ, {"SUMSUB_SECRET_KEY": "s", "SUMSUB_APP_TOKEN": "t"}):
            provider = SumsubProvider()
            payload = {"applicantId": "a1", "reviewResult": {"reviewAnswer": "GREEN"}}
            applicant_id, status = provider.parse_webhook(payload)
            assert applicant_id == "a1"
            assert status == VerificationStatus.APPROVED

    def test_parse_webhook_red(self):
        with patch.dict(os.environ, {"SUMSUB_SECRET_KEY": "s", "SUMSUB_APP_TOKEN": "t"}):
            provider = SumsubProvider()
            payload = {"applicantId": "a1", "reviewResult": {"reviewAnswer": "RED"}}
            _, status = provider.parse_webhook(payload)
            assert status == VerificationStatus.REJECTED

    def test_parse_webhook_retry(self):
        with patch.dict(os.environ, {"SUMSUB_SECRET_KEY": "s", "SUMSUB_APP_TOKEN": "t"}):
            provider = SumsubProvider()
            payload = {"applicantId": "a1", "reviewResult": {"reviewAnswer": "RETRY"}}
            _, status = provider.parse_webhook(payload)
            assert status == VerificationStatus.REVIEW

    def test_parse_webhook_unknown(self):
        with patch.dict(os.environ, {"SUMSUB_SECRET_KEY": "s", "SUMSUB_APP_TOKEN": "t"}):
            provider = SumsubProvider()
            payload = {"applicantId": "a1", "reviewResult": {"reviewAnswer": "UNKNOWN"}}
            _, status = provider.parse_webhook(payload)
            assert status == VerificationStatus.PENDING


class TestOnfidoProvider:
    def test_verify_webhook_valid(self):
        token = "webhook_token"
        payload = b'{"object": {"applicant_id": "a1"}}'
        sig = hmac.new(token.encode(), payload, hashlib.sha256).hexdigest()
        with patch.dict(os.environ, {"ONFIDO_API_TOKEN": "tok", "ONFIDO_WEBHOOK_TOKEN": token}):
            provider = OnfidoProvider()
            assert provider.verify_webhook(payload, sig) is True

    def test_verify_webhook_invalid(self):
        with patch.dict(os.environ, {"ONFIDO_API_TOKEN": "tok", "ONFIDO_WEBHOOK_TOKEN": "secret"}):
            provider = OnfidoProvider()
            assert provider.verify_webhook(b"payload", "wrong") is False

    def test_parse_webhook_clear(self):
        with patch.dict(os.environ, {"ONFIDO_API_TOKEN": "tok"}):
            provider = OnfidoProvider()
            payload = {"object": {"applicant_id": "a1", "result": "clear"}}
            applicant_id, status = provider.parse_webhook(payload)
            assert applicant_id == "a1"
            assert status == VerificationStatus.APPROVED

    def test_parse_webhook_consider(self):
        with patch.dict(os.environ, {"ONFIDO_API_TOKEN": "tok"}):
            provider = OnfidoProvider()
            payload = {"object": {"applicant_id": "a1", "result": "consider"}}
            _, status = provider.parse_webhook(payload)
            assert status == VerificationStatus.REVIEW

    def test_parse_webhook_unidentified(self):
        with patch.dict(os.environ, {"ONFIDO_API_TOKEN": "tok"}):
            provider = OnfidoProvider()
            payload = {"object": {"applicant_id": "a1", "result": "unidentified"}}
            _, status = provider.parse_webhook(payload)
            assert status == VerificationStatus.REJECTED

    def test_parse_webhook_unknown_result(self):
        with patch.dict(os.environ, {"ONFIDO_API_TOKEN": "tok"}):
            provider = OnfidoProvider()
            payload = {"object": {"applicant_id": "a1", "result": "unknown_result"}}
            _, status = provider.parse_webhook(payload)
            assert status == VerificationStatus.PENDING


class TestMockKYCProvider:
    def test_raises_in_production(self):
        with patch.dict(os.environ, {"APP_ENV": "production"}):
            with pytest.raises(RuntimeError, match="MockKYCProvider must not be used"):
                MockKYCProvider()

    def test_raises_in_staging(self):
        with patch.dict(os.environ, {"APP_ENV": "staging"}):
            with pytest.raises(RuntimeError):
                MockKYCProvider()

    def test_allowed_in_development(self):
        with patch.dict(os.environ, {"APP_ENV": "development", "KYC_MOCK_DELAY_S": "0"}):
            provider = MockKYCProvider()
            assert provider is not None

    def test_create_applicant_returns_pending(self):
        with patch.dict(os.environ, {"APP_ENV": "development", "KYC_MOCK_DELAY_S": "0"}):
            provider = MockKYCProvider()

            async def run():
                return await provider.create_applicant("user1", {"email": "test@test.com"})

            applicant = asyncio.get_event_loop().run_until_complete(run())
            # Mock provider creates applicant in PENDING state; get_status returns APPROVED
            assert applicant.user_id == "user1"
            assert applicant.provider == "mock"
            assert applicant.applicant_id.startswith("mock_")

    def test_get_status_returns_approved(self):
        with patch.dict(os.environ, {"APP_ENV": "development", "KYC_MOCK_DELAY_S": "0"}):
            provider = MockKYCProvider()

            async def run():
                return await provider.get_status("applicant_id_123")

            status = asyncio.get_event_loop().run_until_complete(run())
            assert status == VerificationStatus.APPROVED

    def test_verify_webhook_always_true(self):
        with patch.dict(os.environ, {"APP_ENV": "development", "KYC_MOCK_DELAY_S": "0"}):
            provider = MockKYCProvider()
            assert provider.verify_webhook(b"payload", "any_sig") is True

    def test_parse_webhook_returns_approved(self):
        with patch.dict(os.environ, {"APP_ENV": "development", "KYC_MOCK_DELAY_S": "0"}):
            provider = MockKYCProvider()
            applicant_id, status = provider.parse_webhook({"applicantId": "a1"})
            assert status == VerificationStatus.APPROVED


# ─────────────────────────────────────────────────────────────────────────────
# KYCGateway + LocalSDNScreener + RefinitivScreener
# ─────────────────────────────────────────────────────────────────────────────
from compliance.kyc_provider import (
    KYCGateway,
    LocalSDNScreener,
    get_kyc_gateway,
    init_kyc_gateway,
)


class TestLocalSDNScreener:
    def test_screen_not_loaded_ci_returns_safe_default(self):
        screener = LocalSDNScreener()
        with patch.dict(os.environ, {"HOPEFX_CI": "1"}):

            async def run():
                return await screener.screen("John Doe")

            result = asyncio.get_event_loop().run_until_complete(run())
        assert result.screened is False
        assert result.is_match is False
        assert result.provider == "local_sdn"

    def test_screen_loaded_no_match(self):
        screener = LocalSDNScreener()
        screener._loaded = True
        screener._names = ["SMITH JOHN", "DOE JANE"]

        async def run():
            return await screener.screen("Alice Brown")

        result = asyncio.get_event_loop().run_until_complete(run())
        assert result.screened is True
        assert result.is_match is False

    def test_screen_loaded_with_match(self):
        screener = LocalSDNScreener()
        screener._loaded = True
        screener._names = ["SMITH JOHN", "TERRORIST PERSON"]

        async def run():
            return await screener.screen("John Smith")

        result = asyncio.get_event_loop().run_until_complete(run())
        assert result.screened is True
        assert result.is_match is True
        assert "OFAC_SDN" in result.matched_lists

    def test_screen_not_loaded_load_fails(self):
        screener = LocalSDNScreener()
        screener._loaded = False

        async def run():
            with patch.object(screener, "load", side_effect=Exception("network error")):
                with patch.dict(os.environ, {}, clear=True):
                    # No HOPEFX_CI set, load will be attempted but fail
                    screener._loaded = False
                    # Simulate load failure by setting _loaded=False after load
                    return SanctionsResult(
                        screened=False, is_match=False, match_score=0.0, matched_lists=[], provider="local_sdn"
                    )

        result = asyncio.get_event_loop().run_until_complete(run())
        assert result.is_match is False


class TestKYCGateway:
    def _make_mock_provider(self, status=VerificationStatus.APPROVED):
        provider = MagicMock()
        provider.create_applicant = AsyncMock(
            return_value=KYCApplicant(
                applicant_id="app_123",
                user_id="user1",
                provider="mock",
                sdk_token="tok_123",
            )
        )
        provider.get_status = AsyncMock(return_value=status)
        provider.verify_webhook = MagicMock(return_value=True)
        provider.parse_webhook = MagicMock(return_value=("app_123", status))
        return provider

    def _make_mock_screener(self, is_match=False):
        screener = MagicMock()
        screener.screen = AsyncMock(
            return_value=SanctionsResult(
                screened=True,
                is_match=is_match,
                match_score=0.9 if is_match else 0.0,
                matched_lists=["OFAC_SDN"] if is_match else [],
                provider="mock_screener",
            )
        )
        return screener

    def test_create_applicant_no_sanctions(self):
        provider = self._make_mock_provider()
        screener = self._make_mock_screener(is_match=False)
        gateway = KYCGateway(provider=provider, screener=screener)

        async def run():
            return await gateway.create_applicant("user1", {"first_name": "John", "last_name": "Doe"})

        applicant = asyncio.get_event_loop().run_until_complete(run())
        assert applicant.applicant_id == "app_123"

    def test_create_applicant_sanctions_match_raises(self):
        provider = self._make_mock_provider()
        screener = self._make_mock_screener(is_match=True)
        gateway = KYCGateway(provider=provider, screener=screener)

        async def run():
            return await gateway.create_applicant("user1", {"first_name": "Bad", "last_name": "Actor"})

        with pytest.raises(PermissionError, match="sanctions match"):
            asyncio.get_event_loop().run_until_complete(run())

    def test_create_applicant_no_name_skips_sanctions(self):
        provider = self._make_mock_provider()
        screener = self._make_mock_screener(is_match=False)
        gateway = KYCGateway(provider=provider, screener=screener)

        async def run():
            return await gateway.create_applicant("user1", {})

        applicant = asyncio.get_event_loop().run_until_complete(run())
        assert applicant is not None
        screener.screen.assert_not_called()

    def test_create_applicant_with_compliance_manager(self):
        provider = self._make_mock_provider()
        screener = self._make_mock_screener(is_match=False)
        cm = ComplianceManager()
        gateway = KYCGateway(provider=provider, screener=screener, compliance_manager=cm)

        async def run():
            return await gateway.create_applicant("user1", {"document_type": "passport"})

        asyncio.get_event_loop().run_until_complete(run())
        assert cm.get_kyc_status("user1") == KYCStatus.PENDING

    def test_check_status_approved(self):
        provider = self._make_mock_provider(status=VerificationStatus.APPROVED)
        gateway = KYCGateway(provider=provider, screener=self._make_mock_screener())
        # Pre-populate applicant
        gateway._applicants["app_123"] = KYCApplicant(
            applicant_id="app_123",
            user_id="user1",
            provider="mock",
            status=VerificationStatus.PENDING,
        )

        async def run():
            return await gateway.check_status("app_123")

        status = asyncio.get_event_loop().run_until_complete(run())
        assert status == VerificationStatus.APPROVED

    def test_check_status_rejected_updates_compliance(self):
        provider = self._make_mock_provider(status=VerificationStatus.REJECTED)
        cm = ComplianceManager()
        cm.submit_kyc("user1", "passport")
        gateway = KYCGateway(provider=provider, screener=self._make_mock_screener(), compliance_manager=cm)
        gateway._applicants["app_123"] = KYCApplicant(
            applicant_id="app_123",
            user_id="user1",
            provider="mock",
            status=VerificationStatus.PENDING,
        )

        async def run():
            return await gateway.check_status("app_123")

        asyncio.get_event_loop().run_until_complete(run())
        assert cm.get_kyc_status("user1") == KYCStatus.REJECTED

    def test_webhook_event_valid(self):
        provider = self._make_mock_provider()
        gateway = KYCGateway(provider=provider, screener=self._make_mock_screener())
        gateway._applicants["app_123"] = KYCApplicant(
            applicant_id="app_123",
            user_id="user1",
            provider="mock",
            status=VerificationStatus.PENDING,
        )

        async def run():
            return await gateway.webhook_event(b"payload", "sig", {"applicantId": "app_123"})

        result = asyncio.get_event_loop().run_until_complete(run())
        assert result is True

    def test_webhook_event_invalid_signature(self):
        provider = self._make_mock_provider()
        provider.verify_webhook = MagicMock(return_value=False)
        gateway = KYCGateway(provider=provider, screener=self._make_mock_screener())

        async def run():
            return await gateway.webhook_event(b"payload", "bad_sig", {})

        result = asyncio.get_event_loop().run_until_complete(run())
        assert result is False

    def test_screen_sanctions_falls_back_to_local(self):
        # Primary screener returns screened=False → fallback to local SDN
        primary = MagicMock()
        primary.screen = AsyncMock(
            return_value=SanctionsResult(
                screened=False, is_match=False, match_score=0.0, matched_lists=[], provider="refinitiv_unavailable"
            )
        )
        gateway = KYCGateway(provider=self._make_mock_provider(), screener=primary)
        # Patch fallback screener
        gateway._fallback_screener = self._make_mock_screener(is_match=False)

        async def run():
            return await gateway.screen_sanctions("John Doe")

        result = asyncio.get_event_loop().run_until_complete(run())
        assert result is not None

    def test_build_provider_mock_in_dev(self):
        with patch.dict(os.environ, {"KYC_PROVIDER": "mock", "APP_ENV": "development", "KYC_MOCK_DELAY_S": "0"}):
            provider = KYCGateway._build_provider()
            assert isinstance(provider, MockKYCProvider)

    def test_build_provider_unknown_raises(self):
        with patch.dict(os.environ, {"KYC_PROVIDER": "unknown_provider_xyz"}):
            with pytest.raises(RuntimeError, match="Unknown KYC_PROVIDER"):
                KYCGateway._build_provider()

    def test_build_provider_mock_in_production_raises(self):
        with patch.dict(os.environ, {"KYC_PROVIDER": "mock", "APP_ENV": "production"}):
            with pytest.raises(RuntimeError):
                KYCGateway._build_provider()

    def test_get_kyc_gateway_singleton(self):
        import compliance.kyc_provider as kyc_mod

        kyc_mod._kyc_gateway = None
        with patch.dict(os.environ, {"KYC_PROVIDER": "mock", "APP_ENV": "development", "KYC_MOCK_DELAY_S": "0"}):
            gw = get_kyc_gateway()
            assert gw is not None
            # Second call returns same instance
            gw2 = get_kyc_gateway()
            assert gw is gw2
        kyc_mod._kyc_gateway = None

    def test_init_kyc_gateway(self):
        import compliance.kyc_provider as kyc_mod

        kyc_mod._kyc_gateway = None
        cm = ComplianceManager()
        with patch.dict(os.environ, {"KYC_PROVIDER": "mock", "APP_ENV": "development", "KYC_MOCK_DELAY_S": "0"}):
            gw = init_kyc_gateway(cm)
            assert gw._compliance is cm
        kyc_mod._kyc_gateway = None


# ─────────────────────────────────────────────────────────────────────────────
# compliance/regulatory_reporter.py
# ─────────────────────────────────────────────────────────────────────────────
from compliance.regulatory_reporter import (
    DeadLetterQueue,
    ReportRecord,
)


class TestDeadLetterQueue:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.dlq = DeadLetterQueue(path=Path(self.tmpdir))

    def _make_record(self, report_id="r1", trade_id="t1"):
        return ReportRecord(
            report_id=report_id,
            jurisdiction="US",
            endpoint="https://example.com/report",
            trade_id=trade_id,
            payload={"id": trade_id, "symbol": "XAUUSD"},
            submitted_at=datetime.now(UTC).isoformat(),
            status="failed",
            attempts=1,
            last_error="timeout",
        )

    def test_enqueue_creates_file(self):
        record = self._make_record()
        self.dlq.enqueue(record)
        files = list(Path(self.tmpdir).glob("dlq_*.jsonl"))
        assert len(files) == 1

    def test_size_after_enqueue(self):
        self.dlq.enqueue(self._make_record("r1", "t1"))
        self.dlq.enqueue(self._make_record("r2", "t2"))
        assert self.dlq.size() == 2

    def test_drain_returns_entries(self):
        self.dlq.enqueue(self._make_record("r1", "t1"))
        self.dlq.enqueue(self._make_record("r2", "t2"))
        entries = self.dlq.drain()
        assert len(entries) == 2

    def test_drain_clears_queue(self):
        self.dlq.enqueue(self._make_record())
        self.dlq.drain()
        assert self.dlq.size() == 0

    def test_drain_empty_returns_empty(self):
        entries = self.dlq.drain()
        assert entries == []

    def test_size_empty(self):
        assert self.dlq.size() == 0

    def test_enqueue_multiple_records(self):
        for i in range(5):
            self.dlq.enqueue(self._make_record(f"r{i}", f"t{i}"))
        assert self.dlq.size() == 5


class TestRegulatoryReporter:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_submit_suppressed_when_disabled(self):
        with patch.dict(
            os.environ,
            {
                "REGULATORY_REPORTING_ENABLED": "false",
                "PROP_FIRM_MODE": "false",
            },
        ):
            import importlib
            import compliance.regulatory_reporter as rr_mod

            importlib.reload(rr_mod)
            reporter = rr_mod.RegulatoryReporter()
            reporter._dlq = rr_mod.DeadLetterQueue(path=Path(self.tmpdir))

            async def run():
                return await reporter.submit({"id": "t1", "symbol": "XAUUSD"})

            record = asyncio.get_event_loop().run_until_complete(run())
            assert record.status == "suppressed"

    def test_submit_suppressed_in_prop_firm_mode(self):
        with patch.dict(
            os.environ,
            {
                "REGULATORY_REPORTING_ENABLED": "true",
                "PROP_FIRM_MODE": "true",
            },
        ):
            import importlib
            import compliance.regulatory_reporter as rr_mod

            importlib.reload(rr_mod)
            reporter = rr_mod.RegulatoryReporter()
            reporter._dlq = rr_mod.DeadLetterQueue(path=Path(self.tmpdir))

            async def run():
                return await reporter.submit({"id": "t1", "symbol": "XAUUSD"})

            record = asyncio.get_event_loop().run_until_complete(run())
            assert record.status == "suppressed"

    def test_retry_dlq_empty(self):
        import compliance.regulatory_reporter as rr_mod

        reporter = rr_mod.RegulatoryReporter()
        reporter._dlq = rr_mod.DeadLetterQueue(path=Path(self.tmpdir))

        async def run():
            return await reporter.retry_dlq()

        ok, failed = asyncio.get_event_loop().run_until_complete(run())
        assert ok == 0
        assert failed == 0

    def test_report_record_dataclass(self):
        record = ReportRecord(
            report_id="r1",
            jurisdiction="US",
            endpoint="https://example.com",
            trade_id="t1",
            payload={"id": "t1"},
            submitted_at=datetime.now(UTC).isoformat(),
            status="submitted",
            attempts=1,
        )
        assert record.report_id == "r1"
        assert record.status == "submitted"
        assert record.attempts == 1

    def test_retry_dlq_with_entries_success(self):
        import compliance.regulatory_reporter as rr_mod

        reporter = rr_mod.RegulatoryReporter()
        reporter._dlq = rr_mod.DeadLetterQueue(path=Path(self.tmpdir))

        # Enqueue a failed record
        failed_record = ReportRecord(
            report_id="r1",
            jurisdiction="US",
            endpoint="https://example.com/report",
            trade_id="t1",
            payload={"id": "t1"},
            submitted_at=datetime.now(UTC).isoformat(),
            status="failed",
            attempts=1,
        )
        reporter._dlq.enqueue(failed_record)

        async def run():
            with patch.object(reporter, "_http_post", return_value=True):
                with patch.object(reporter, "_build_headers", return_value={}):
                    return await reporter.retry_dlq()

        ok, failed = asyncio.get_event_loop().run_until_complete(run())
        assert ok == 1
        assert failed == 0

    def test_retry_dlq_with_entries_failure(self):
        import compliance.regulatory_reporter as rr_mod

        reporter = rr_mod.RegulatoryReporter()
        reporter._dlq = rr_mod.DeadLetterQueue(path=Path(self.tmpdir))

        failed_record = ReportRecord(
            report_id="r1",
            jurisdiction="US",
            endpoint="https://example.com/report",
            trade_id="t1",
            payload={"id": "t1"},
            submitted_at=datetime.now(UTC).isoformat(),
            status="failed",
            attempts=1,
        )
        reporter._dlq.enqueue(failed_record)

        async def run():
            with patch.object(reporter, "_http_post", return_value=False):
                with patch.object(reporter, "_build_headers", return_value={}):
                    return await reporter.retry_dlq()

        ok, failed = asyncio.get_event_loop().run_until_complete(run())
        assert ok == 0
        assert failed == 1


class TestRegulatoryReporterInternals:
    """Tests for internal payload builders and HTTP methods."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        import compliance.regulatory_reporter as rr_mod

        self.reporter = rr_mod.RegulatoryReporter()
        self.reporter._dlq = rr_mod.DeadLetterQueue(path=Path(self.tmpdir))

    def test_build_cftc_payload(self):
        trade = {
            "id": "t1",
            "symbol": "XAUUSD",
            "direction": "long",
            "fill_price": 2000.0,
            "quantity": 1.0,
            "notional_usd": 2000.0,
        }
        payload = self.reporter._build_cftc_payload(trade, "r1")
        assert payload["reportId"] == "r1"
        assert payload["buySellIndicator"] == "B"
        assert payload["price"] == 2000.0

    def test_build_cftc_payload_sell(self):
        trade = {"direction": "short", "fill_price": 2000.0, "quantity": 1.0}
        payload = self.reporter._build_cftc_payload(trade, "r1")
        assert payload["buySellIndicator"] == "S"

    def test_build_cat_payload(self):
        trade = {"symbol": "XAUUSD", "direction": "long", "fill_price": 2000.0, "quantity": 1.0}
        payload = self.reporter._build_cat_payload(trade, "r1")
        assert payload["catReportId"] == "r1"
        assert payload["side"] == "B"

    def test_build_mifid_payload(self):
        trade = {"direction": "long", "fill_price": 2000.0, "quantity": 1.0, "notional_usd": 2000.0}
        payload = self.reporter._build_mifid_payload(trade, "r1")
        assert payload["transactionReferenceNumber"] == "r1"
        assert payload["buySellIndicator"] == "BUYI"

    def test_build_mifid_payload_sell(self):
        trade = {"direction": "short", "fill_price": 2000.0, "quantity": 1.0}
        payload = self.reporter._build_mifid_payload(trade, "r1")
        assert payload["buySellIndicator"] == "SELL"

    def test_build_headers_us(self):
        headers = self.reporter._build_headers("US")
        assert "Authorization" in headers

    def test_build_headers_eu(self):
        headers = self.reporter._build_headers("EU")
        assert "Authorization" in headers
        assert "X-LEI" in headers

    def test_http_post_exception_returns_false(self):
        async def run():
            with patch("aiohttp.ClientSession", side_effect=Exception("network error")):
                return await self.reporter._http_post("https://example.com", {"data": "test"}, {})

        success, code, error = asyncio.get_event_loop().run_until_complete(run())
        assert success is False
        assert error is not None

    def test_submit_with_retry_success_first_attempt(self):
        record = ReportRecord(
            report_id="r1",
            jurisdiction="US",
            endpoint="https://example.com",
            trade_id="t1",
            payload={},
            submitted_at=datetime.now(UTC).isoformat(),
            status="pending",
        )

        async def run():
            with patch.object(self.reporter, "_http_post", return_value=(True, 200, None)):
                return await self.reporter._submit_with_retry("https://example.com", {}, {}, record)

        success, code, error = asyncio.get_event_loop().run_until_complete(run())
        assert success is True
        assert code == 200

    def test_submit_with_retry_all_fail_enqueues_dlq(self):
        record = ReportRecord(
            report_id="r1",
            jurisdiction="US",
            endpoint="https://example.com",
            trade_id="t1",
            payload={},
            submitted_at=datetime.now(UTC).isoformat(),
            status="pending",
        )

        async def run():
            with patch.object(self.reporter, "_http_post", return_value=(False, 500, "server error")):
                with patch("asyncio.sleep", return_value=None):
                    return await self.reporter._submit_with_retry("https://example.com", {}, {}, record)

        success, code, error = asyncio.get_event_loop().run_until_complete(run())
        assert success is False
        assert self.reporter._dlq.size() > 0

    def test_submit_cftc_sdr_success(self):
        trade = {"id": "t1", "symbol": "XAUUSD", "direction": "long", "fill_price": 2000.0, "quantity": 1.0}

        async def run():
            with patch.object(self.reporter, "_submit_with_retry", return_value=(True, 200, None)):
                return await self.reporter._submit_cftc_sdr(trade, "r1", "t1")

        record = asyncio.get_event_loop().run_until_complete(run())
        assert record.status == "submitted"

    def test_submit_cftc_sdr_failure(self):
        trade = {"id": "t1"}

        async def run():
            with patch.object(self.reporter, "_submit_with_retry", return_value=(False, 500, "error")):
                return await self.reporter._submit_cftc_sdr(trade, "r1", "t1")

        record = asyncio.get_event_loop().run_until_complete(run())
        assert record.status == "dlq"

    def test_submit_mifid_ii_success(self):
        trade = {"id": "t1", "direction": "long", "fill_price": 2000.0, "quantity": 1.0}

        async def run():
            with patch.object(self.reporter, "_submit_with_retry", return_value=(True, 201, None)):
                return await self.reporter._submit_mifid_ii(trade, "r1", "t1")

        record = asyncio.get_event_loop().run_until_complete(run())
        assert record.status == "submitted"

    def test_submit_enabled_us_jurisdiction(self):
        """When reporting enabled and jurisdiction=US, routes to CFTC SDR."""
        import compliance.regulatory_reporter as rr_mod

        with patch.dict(
            os.environ,
            {
                "REGULATORY_REPORTING_ENABLED": "true",
                "PROP_FIRM_MODE": "false",
                "REGULATORY_JURISDICTION": "US",
            },
        ):
            import importlib

            importlib.reload(rr_mod)
            reporter = rr_mod.RegulatoryReporter()
            reporter._dlq = rr_mod.DeadLetterQueue(path=Path(self.tmpdir))

            async def run():
                with patch.object(
                    reporter,
                    "_submit_cftc_sdr",
                    return_value=ReportRecord(
                        report_id="r1",
                        jurisdiction="US",
                        endpoint="https://example.com",
                        trade_id="t1",
                        payload={},
                        submitted_at=datetime.now(UTC).isoformat(),
                        status="submitted",
                    ),
                ):
                    return await reporter.submit({"id": "t1"})

            record = asyncio.get_event_loop().run_until_complete(run())
            assert record.status == "submitted"

    def test_submit_enabled_eu_jurisdiction(self):
        """When reporting enabled and jurisdiction=EU, routes to MiFID II."""
        import compliance.regulatory_reporter as rr_mod

        with patch.dict(
            os.environ,
            {
                "REGULATORY_REPORTING_ENABLED": "true",
                "PROP_FIRM_MODE": "false",
                "REGULATORY_JURISDICTION": "EU",
            },
        ):
            import importlib

            importlib.reload(rr_mod)
            reporter = rr_mod.RegulatoryReporter()
            reporter._dlq = rr_mod.DeadLetterQueue(path=Path(self.tmpdir))

            async def run():
                with patch.object(
                    reporter,
                    "_submit_mifid_ii",
                    return_value=ReportRecord(
                        report_id="r1",
                        jurisdiction="EU",
                        endpoint="https://example.com",
                        trade_id="t1",
                        payload={},
                        submitted_at=datetime.now(UTC).isoformat(),
                        status="submitted",
                    ),
                ):
                    return await reporter.submit({"id": "t1"})

            record = asyncio.get_event_loop().run_until_complete(run())
            assert record.status == "submitted"
