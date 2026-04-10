# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/unit/test_compliance_full.py
====================================
Comprehensive tests for the compliance package.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

UTC = timezone.utc


# ===========================================================================
# compliance/compliance_manager.py
# ===========================================================================


class TestComplianceManagerInMemory:
    def _make_cm(self):
        from compliance.compliance_manager import ComplianceManager

        return ComplianceManager()

    def test_init_no_session_factory(self):
        cm = self._make_cm()
        assert cm._session_factory is None
        assert cm._kyc_records == {}
        assert cm._audit_log == []

    def test_submit_kyc_returns_record(self):
        cm = self._make_cm()
        record = cm.submit_kyc("user1", "passport")
        assert record["user_id"] == "user1"
        assert record["document_type"] == "passport"
        assert record["status"] == "pending"

    def test_submit_kyc_stores_record(self):
        cm = self._make_cm()
        cm.submit_kyc("user1", "passport")
        assert "user1" in cm._kyc_records

    def test_approve_kyc_changes_status(self):
        from compliance.compliance_manager import KYCStatus

        cm = self._make_cm()
        cm.submit_kyc("user1", "passport")
        cm.approve_kyc("user1")
        assert cm.get_kyc_status("user1") == KYCStatus.APPROVED

    def test_reject_kyc_changes_status(self):
        from compliance.compliance_manager import KYCStatus

        cm = self._make_cm()
        cm.submit_kyc("user1", "passport")
        cm.reject_kyc("user1", reason="document expired")
        assert cm.get_kyc_status("user1") == KYCStatus.REJECTED

    def test_is_kyc_approved_true(self):
        cm = self._make_cm()
        cm.submit_kyc("user1", "passport")
        cm.approve_kyc("user1")
        assert cm.is_kyc_approved("user1") is True

    def test_is_kyc_approved_false_pending(self):
        cm = self._make_cm()
        cm.submit_kyc("user1", "passport")
        assert cm.is_kyc_approved("user1") is False

    def test_get_kyc_status_unknown_user(self):
        from compliance.compliance_manager import KYCStatus

        cm = self._make_cm()
        assert cm.get_kyc_status("unknown") == KYCStatus.UNVERIFIED

    def test_log_trade_appends_audit(self):
        cm = self._make_cm()
        cm.log_trade("user1", {"symbol": "XAUUSD", "qty": 1.0})
        assert len(cm._audit_log) >= 1

    def test_audit_log_has_hash_chain(self):
        cm = self._make_cm()
        cm.submit_kyc("user1", "passport")
        entry = cm._audit_log[0]
        assert "hash_chain" in entry
        assert len(entry["hash_chain"]) == 64

    def test_audit_log_sequence_increments(self):
        cm = self._make_cm()
        cm.submit_kyc("user1", "passport")
        cm.approve_kyc("user1")
        seqs = [e["sequence_number"] for e in cm._audit_log]
        assert seqs == sorted(seqs)
        assert seqs[0] == 1

    def test_get_audit_log_returns_list(self):
        cm = self._make_cm()
        cm.submit_kyc("user1", "passport")
        log = cm.get_audit_log()
        assert isinstance(log, list)
        assert len(log) >= 1

    def test_get_audit_log_limit(self):
        cm = self._make_cm()
        for i in range(10):
            cm.submit_kyc(f"user{i}", "passport")
        log = cm.get_audit_log(limit=3)
        assert len(log) <= 3

    def test_set_session_factory(self):
        cm = self._make_cm()
        factory = MagicMock()
        cm.set_session_factory(factory)
        assert cm._session_factory is factory

    def test_approve_unknown_user_no_crash(self):
        cm = self._make_cm()
        result = cm.approve_kyc("nonexistent")
        assert result is True

    def test_reject_unknown_user_no_crash(self):
        cm = self._make_cm()
        result = cm.reject_kyc("nonexistent", reason="fraud")
        assert result is True


class TestComplianceManagerWithDB:
    def _make_cm_with_db(self):
        from compliance.compliance_manager import ComplianceManager

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.query.return_value.filter_by.return_value.first.return_value = None
        factory = MagicMock(return_value=mock_session)
        return ComplianceManager(session_factory=factory), mock_session

    def test_submit_kyc_with_db_no_crash(self):
        cm, _ = self._make_cm_with_db()
        record = cm.submit_kyc("user1", "passport")
        assert record["user_id"] == "user1"

    def test_approve_kyc_with_db_existing_record(self):
        from compliance.compliance_manager import KYCStatus

        cm, mock_session = self._make_cm_with_db()
        cm.submit_kyc("user1", "passport")
        mock_db_rec = MagicMock()
        mock_session.query.return_value.filter_by.return_value.first.return_value = mock_db_rec
        cm.approve_kyc("user1")
        assert cm.get_kyc_status("user1") == KYCStatus.APPROVED

    def test_db_write_failure_degrades_gracefully(self):
        from compliance.compliance_manager import ComplianceManager

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(side_effect=RuntimeError("DB down"))
        mock_session.__exit__ = MagicMock(return_value=False)
        factory = MagicMock(return_value=mock_session)
        cm = ComplianceManager(session_factory=factory)
        record = cm.submit_kyc("user1", "passport")
        assert record["user_id"] == "user1"

    def test_get_audit_log_db_failure_falls_back(self):
        from compliance.compliance_manager import ComplianceManager

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(side_effect=RuntimeError("DB down"))
        mock_session.__exit__ = MagicMock(return_value=False)
        factory = MagicMock(return_value=mock_session)
        cm = ComplianceManager(session_factory=factory)
        cm.submit_kyc("user1", "passport")
        log = cm.get_audit_log()
        assert isinstance(log, list)


# ===========================================================================
# compliance/auditor.py
# ===========================================================================


class TestImmutableAuditLog:
    def _make_log(self, tmp_path):
        from compliance.auditor import ImmutableAuditLog

        return ImmutableAuditLog(log_path=str(tmp_path) + "/")

    def test_init_creates_log(self, tmp_path):
        log = self._make_log(tmp_path)
        assert log is not None
        assert log.records == []

    def test_append_record(self, tmp_path):
        from compliance.auditor import AuditLevel

        log = self._make_log(tmp_path)
        record = log.append(AuditLevel.COMPLIANCE, "TRADE", "user1", "buy", {"symbol": "XAUUSD", "qty": 1.0})
        assert record is not None
        assert len(log.records) == 1

    def test_append_multiple_records(self, tmp_path):
        from compliance.auditor import AuditLevel

        log = self._make_log(tmp_path)
        for i in range(5):
            log.append(AuditLevel.COMPLIANCE, "TRADE", f"user{i}", "buy", {})
        assert len(log.records) == 5

    def test_hash_chain_integrity(self, tmp_path):
        from compliance.auditor import AuditLevel

        log = self._make_log(tmp_path)
        log.append(AuditLevel.COMPLIANCE, "TRADE", "user1", "buy", {})
        log.append(AuditLevel.COMPLIANCE, "TRADE", "user1", "sell", {})
        assert log.verify_integrity() is True

    def test_verify_integrity_empty_log(self, tmp_path):
        log = self._make_log(tmp_path)
        assert log.verify_integrity() is True

    def test_export_for_regulator_returns_list(self, tmp_path):
        from compliance.auditor import AuditLevel

        log = self._make_log(tmp_path)
        log.append(AuditLevel.COMPLIANCE, "TRADE", "user1", "buy", {"symbol": "XAUUSD"})
        start = datetime(2020, 1, 1, tzinfo=UTC)
        end = datetime(2030, 1, 1, tzinfo=UTC)
        result = log.export_for_regulator(start, end)
        assert isinstance(result, list)

    def test_export_for_regulator_date_filter(self, tmp_path):
        from compliance.auditor import AuditLevel

        log = self._make_log(tmp_path)
        log.append(AuditLevel.COMPLIANCE, "TRADE", "user1", "buy", {})
        start = datetime(2099, 1, 1, tzinfo=UTC)
        end = datetime(2099, 12, 31, tzinfo=UTC)
        result = log.export_for_regulator(start, end)
        assert result == []

    def test_record_has_hash(self, tmp_path):
        from compliance.auditor import AuditLevel

        log = self._make_log(tmp_path)
        record = log.append(AuditLevel.COMPLIANCE, "TRADE", "user1", "buy", {})
        assert len(record.hash_chain) == 64

    def test_sequence_numbers_increment(self, tmp_path):
        from compliance.auditor import AuditLevel

        log = self._make_log(tmp_path)
        for _ in range(3):
            log.append(AuditLevel.COMPLIANCE, "TRADE", "u", "a", {})
        seqs = [r.sequence_number for r in log.records]
        assert seqs == [1, 2, 3]


class TestTradeReporting:
    def test_init(self):
        from compliance.auditor import TradeReporting

        tr = TradeReporting(jurisdiction="US")
        assert tr.jurisdiction == "US"

    def test_report_trade_no_crash(self):
        from compliance.auditor import TradeReporting

        tr = TradeReporting(jurisdiction="US")
        tr.report_trade(
            {
                "trade_id": str(uuid.uuid4()),
                "symbol": "XAUUSD",
                "side": "BUY",
                "quantity": 1.0,
                "price": 2000.0,
            }
        )

    def test_report_trade_eu_jurisdiction(self):
        from compliance.auditor import TradeReporting

        tr = TradeReporting(jurisdiction="EU")
        tr.report_trade({"trade_id": "t1", "symbol": "XAUUSD"})

    def test_report_trade_appends_to_audit_log(self):
        from compliance.auditor import TradeReporting

        tr = TradeReporting(jurisdiction="US")
        tr.report_trade({"trade_id": "t1", "symbol": "XAUUSD"})
        assert len(tr.audit_log.records) >= 1


# ===========================================================================
# compliance/regulatory_reporter.py
# ===========================================================================


class TestDeadLetterQueue:
    def test_enqueue_writes_file(self, tmp_path):
        from compliance.regulatory_reporter import DeadLetterQueue, ReportRecord

        dlq = DeadLetterQueue(path=tmp_path / "dlq")
        record = ReportRecord(
            report_id=str(uuid.uuid4()),
            jurisdiction="US",
            endpoint="test",
            trade_id="t1",
            payload={"symbol": "XAUUSD"},
            submitted_at=datetime.now(UTC).isoformat(),
            status="failed",
        )
        dlq.enqueue(record)
        # File should exist
        files = list((tmp_path / "dlq").glob("dlq_*.jsonl"))
        assert len(files) >= 1

    def test_enqueue_multiple(self, tmp_path):
        from compliance.regulatory_reporter import DeadLetterQueue, ReportRecord

        dlq = DeadLetterQueue(path=tmp_path / "dlq")
        for i in range(3):
            dlq.enqueue(
                ReportRecord(
                    report_id=str(uuid.uuid4()),
                    jurisdiction="US",
                    endpoint="test",
                    trade_id=f"t{i}",
                    payload={},
                    submitted_at=datetime.now(UTC).isoformat(),
                    status="failed",
                )
            )
        files = list((tmp_path / "dlq").glob("dlq_*.jsonl"))
        assert len(files) >= 1

    def test_drain_returns_dicts(self, tmp_path):
        from compliance.regulatory_reporter import DeadLetterQueue, ReportRecord

        dlq = DeadLetterQueue(path=tmp_path / "dlq")
        dlq.enqueue(
            ReportRecord(
                report_id=str(uuid.uuid4()),
                jurisdiction="US",
                endpoint="test",
                trade_id="t1",
                payload={},
                submitted_at=datetime.now(UTC).isoformat(),
                status="failed",
            )
        )
        records = dlq.drain()
        assert isinstance(records, list)
        assert len(records) >= 1

    def test_drain_empty_queue(self, tmp_path):
        from compliance.regulatory_reporter import DeadLetterQueue

        dlq = DeadLetterQueue(path=tmp_path / "dlq")
        records = dlq.drain()
        assert records == []


class TestReportRecord:
    def test_fields(self):
        from compliance.regulatory_reporter import ReportRecord

        r = ReportRecord(
            report_id="r1",
            jurisdiction="US",
            endpoint="cftc_sdr",
            trade_id="t1",
            payload={"symbol": "XAUUSD"},
            submitted_at=datetime.now(UTC).isoformat(),
            status="submitted",
        )
        assert r.report_id == "r1"
        assert r.status == "submitted"
        assert r.last_error is None


class TestRegulatoryReporterSuppressed:
    @pytest.mark.asyncio
    async def test_prop_firm_mode_suppresses_report(self):
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("PROP_FIRM_MODE", "true")
            mp.setenv("LIVE_TRADING_ENABLED", "false")
            import importlib
            import compliance.regulatory_reporter as rr_mod

            importlib.reload(rr_mod)
            reporter = rr_mod.RegulatoryReporter()
            record = await reporter.submit({"trade_id": "t1", "symbol": "XAUUSD"})
            assert record.status == "suppressed"

    @pytest.mark.asyncio
    async def test_reporting_disabled_suppresses_report(self):
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("REGULATORY_REPORTING_ENABLED", "false")
            mp.setenv("PROP_FIRM_MODE", "false")
            mp.setenv("LIVE_TRADING_ENABLED", "false")
            import importlib
            import compliance.regulatory_reporter as rr_mod

            importlib.reload(rr_mod)
            reporter = rr_mod.RegulatoryReporter()
            record = await reporter.submit({"trade_id": "t1", "symbol": "XAUUSD"})
            assert record.status == "suppressed"

    @pytest.mark.asyncio
    async def test_suppressed_record_stored(self):
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("PROP_FIRM_MODE", "true")
            mp.setenv("LIVE_TRADING_ENABLED", "false")
            import importlib
            import compliance.regulatory_reporter as rr_mod

            importlib.reload(rr_mod)
            reporter = rr_mod.RegulatoryReporter()
            await reporter.submit({"trade_id": "t1"})
            assert len(reporter._records) == 1

    @pytest.mark.asyncio
    async def test_retry_dlq_empty_returns_zero(self, tmp_path):
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("PROP_FIRM_MODE", "true")
            mp.setenv("LIVE_TRADING_ENABLED", "false")
            import importlib
            import compliance.regulatory_reporter as rr_mod

            importlib.reload(rr_mod)
            reporter = rr_mod.RegulatoryReporter()
            # Override DLQ path to empty tmp dir
            from compliance.regulatory_reporter import DeadLetterQueue

            reporter._dlq = DeadLetterQueue(path=tmp_path / "dlq")
            retried, failed = await reporter.retry_dlq()
            assert retried == 0
            assert failed == 0


# ===========================================================================
# compliance/kyc_provider.py — MockKYCProvider and KYCGateway
# ===========================================================================


class TestMockKYCProvider:
    def _make_provider(self):
        from compliance.kyc_provider import MockKYCProvider

        return MockKYCProvider()

    @pytest.mark.asyncio
    async def test_create_applicant_returns_applicant(self):
        from compliance.kyc_provider import KYCApplicant

        provider = self._make_provider()
        applicant = await provider.create_applicant("user1", {"email": "user1@test.com"})
        assert isinstance(applicant, KYCApplicant)
        assert applicant.user_id == "user1"

    @pytest.mark.asyncio
    async def test_get_status_returns_approved(self):
        from compliance.kyc_provider import VerificationStatus

        provider = self._make_provider()
        applicant = await provider.create_applicant("user1", {})
        status = await provider.get_status(applicant.applicant_id)
        assert status == VerificationStatus.APPROVED

    @pytest.mark.asyncio
    async def test_verify_webhook_returns_true(self):
        provider = self._make_provider()
        assert provider.verify_webhook(b"payload", "sig") is True

    @pytest.mark.asyncio
    async def test_parse_webhook_returns_tuple(self):
        from compliance.kyc_provider import VerificationStatus

        provider = self._make_provider()
        applicant_id, status = provider.parse_webhook({"applicant_id": "app1"})
        assert applicant_id == "app1"
        assert status == VerificationStatus.APPROVED

    @pytest.mark.asyncio
    async def test_sdk_token_in_applicant(self):
        provider = self._make_provider()
        applicant = await provider.create_applicant("user1", {})
        assert len(applicant.sdk_token) > 0


class TestKYCGatewayMockProvider:
    def _make_gateway(self):
        os.environ["KYC_PROVIDER"] = "mock"
        os.environ["APP_ENV"] = "test"
        from compliance.kyc_provider import KYCGateway

        return KYCGateway()

    @pytest.mark.asyncio
    async def test_create_applicant_returns_applicant(self):
        from compliance.kyc_provider import KYCApplicant

        gw = self._make_gateway()
        result = await gw.create_applicant("user1", {"name": "Alice"})
        assert isinstance(result, KYCApplicant)

    @pytest.mark.asyncio
    async def test_check_status_after_create(self):
        from compliance.kyc_provider import VerificationStatus

        gw = self._make_gateway()
        applicant = await gw.create_applicant("user2", {})
        status = await gw.check_status(applicant.applicant_id)
        assert isinstance(status, VerificationStatus)

    @pytest.mark.asyncio
    async def test_screen_sanctions_returns_sanctions_result(self):
        from compliance.kyc_provider import SanctionsResult

        gw = self._make_gateway()
        result = await gw.screen_sanctions("Alice Smith", country="US")
        assert isinstance(result, SanctionsResult)

    @pytest.mark.asyncio
    async def test_screen_sanctions_clean_user_not_matched(self):
        gw = self._make_gateway()
        result = await gw.screen_sanctions("Alice Smith", country="US")
        assert result.is_match is False

    @pytest.mark.asyncio
    async def test_webhook_event_valid_signature(self):
        gw = self._make_gateway()
        applicant = await gw.create_applicant("user3", {})
        result = await gw.webhook_event(b"payload", "valid_sig", {"applicant_id": applicant.applicant_id})
        assert result is True

    @pytest.mark.asyncio
    async def test_full_kyc_flow(self):
        from compliance.kyc_provider import VerificationStatus

        gw = self._make_gateway()
        applicant = await gw.create_applicant("user4", {"email": "user4@test.com"})
        assert applicant.user_id == "user4"
        status = await gw.check_status(applicant.applicant_id)
        assert status == VerificationStatus.APPROVED

    @pytest.mark.asyncio
    async def test_sanctions_match_blocks_kyc(self):
        """KYCGateway blocks applicant creation when sanctions match is found."""
        from compliance.kyc_provider import SanctionsResult
        from unittest.mock import AsyncMock, patch

        gw = self._make_gateway()
        # Patch the screener to return a match
        matched_result = SanctionsResult(
            screened=True,
            is_match=True,
            match_score=0.95,
            matched_lists=["OFAC_SDN"],
            details="test match",
            provider="local_sdn",
        )
        with (
            patch.object(gw._screener, "screen", new=AsyncMock(return_value=matched_result)),
            pytest.raises(PermissionError, match="sanctions"),
        ):
            await gw.create_applicant("bad_user", {"first_name": "Sanctioned", "last_name": "Person"})


class TestKYCApplicant:
    def test_fields(self):
        from compliance.kyc_provider import KYCApplicant, VerificationStatus

        a = KYCApplicant(
            applicant_id="app1",
            user_id="user1",
            provider="mock",
            sdk_token="tok123",
            status=VerificationStatus.PENDING,
            created_at=datetime.now(UTC),
        )
        assert a.applicant_id == "app1"
        assert a.status == VerificationStatus.PENDING
        assert a.sdk_token == "tok123"
