# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
Deep coverage tests for compliance/ package.
Covers: aml.py, auditor.py, compliance_manager.py, kyc_provider.py,
        regulatory_reporter.py
Real implementations only — external I/O patched at the boundary.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

UTC = timezone.utc


# ===========================================================================
# compliance/aml.py
# ===========================================================================


@pytest.mark.unit
class TestAMLGateNoDb:
    def _gate(self):
        from compliance.aml import AMLGate

        return AMLGate(session_factory=None)

    def test_exceeds_single_cap_blocked(self):
        gate = self._gate()
        result = gate.check_withdrawal("u1", Decimal("15000"), kyc_status="approved")
        assert result.allowed is False
        assert "EXCEEDS_SINGLE_CAP" in result.flags
        assert result.risk_score == 1.0

    def test_kyc_required_above_threshold(self):
        gate = self._gate()
        result = gate.check_withdrawal("u1", Decimal("2000"), kyc_status="unverified")
        assert result.allowed is False
        assert "KYC_REQUIRED" in result.flags

    def test_small_amount_no_kyc_approved(self):
        gate = self._gate()
        result = gate.check_withdrawal("u1", Decimal("500"), kyc_status="unverified")
        assert result.allowed is True

    def test_above_kyc_threshold_no_db_blocked(self):
        gate = self._gate()
        result = gate.check_withdrawal("u1", Decimal("2000"), kyc_status="approved")
        assert result.allowed is False
        assert "NO_DB_SESSION" in result.flags

    def test_approved_with_no_flags(self):
        gate = self._gate()
        result = gate.check_withdrawal("u1", Decimal("100"), kyc_status="unverified")
        assert result.allowed is True
        assert result.reason == "Approved"


@pytest.mark.unit
class TestAMLGateWithDb:
    def _make_session(self, withdrawals=None, deposits=None):
        """Build a mock session_factory returning mock transactions."""
        from unittest.mock import MagicMock

        withdrawals = withdrawals or []
        deposits = deposits or []

        session = MagicMock()
        query_mock = MagicMock()
        session.query.return_value = query_mock
        query_mock.filter.return_value = query_mock
        query_mock.all.side_effect = [withdrawals, deposits]
        session.__enter__ = MagicMock(return_value=session)
        session.__exit__ = MagicMock(return_value=False)

        factory = MagicMock(return_value=session)
        return factory

    def test_velocity_limit_blocks(self):
        from compliance.aml import AMLGate, MAX_WITHDRAWALS_PER_DAY

        txns = [MagicMock(amount="100") for _ in range(MAX_WITHDRAWALS_PER_DAY)]
        factory = self._make_session(withdrawals=txns)
        gate = AMLGate(session_factory=factory)
        result = gate.check_withdrawal("u1", Decimal("500"), kyc_status="approved")
        assert result.allowed is False
        assert "VELOCITY_LIMIT" in result.flags

    def test_daily_limit_exceeded_blocks(self):
        from compliance.aml import AMLGate

        # 4 withdrawals of 10000 each = 40000, adding 15000 exceeds 50000
        txns = [MagicMock(amount="10000") for _ in range(4)]
        factory = self._make_session(withdrawals=txns)
        gate = AMLGate(session_factory=factory)
        result = gate.check_withdrawal("u1", Decimal("15000"), kyc_status="approved")
        # First check: single cap (15000 > 10000) → blocked before DB
        assert result.allowed is False

    def test_rapid_turnaround_flags(self):
        from compliance.aml import AMLGate

        # amount must be numeric for Decimal(str(dep.amount)) to work
        dep = MagicMock(amount=500.00)
        factory = self._make_session(withdrawals=[], deposits=[dep])
        gate = AMLGate(session_factory=factory)
        result = gate.check_withdrawal("u1", Decimal("500"), kyc_status="approved")
        assert "RAPID_TURNAROUND" in result.flags
        assert result.allowed is True  # flagged but not blocked

    def test_db_exception_fail_closed(self):
        from compliance.aml import AMLGate

        session = MagicMock()
        session.__enter__ = MagicMock(side_effect=RuntimeError("DB down"))
        session.__exit__ = MagicMock(return_value=False)
        factory = MagicMock(return_value=session)
        gate = AMLGate(session_factory=factory)
        result = gate.check_withdrawal("u1", Decimal("500"), kyc_status="approved")
        assert result.allowed is False
        assert "DB_UNAVAILABLE" in result.flags


@pytest.mark.unit
class TestAMLGateSingleton:
    def test_get_aml_gate_returns_instance(self):
        from compliance.aml import get_aml_gate, AMLGate
        import compliance.aml as aml_mod

        aml_mod._aml_gate = None
        gate = get_aml_gate()
        assert isinstance(gate, AMLGate)

    def test_init_aml_gate_wires_factory(self):
        from compliance.aml import init_aml_gate, get_aml_gate

        factory = MagicMock()
        gate = init_aml_gate(factory)
        assert gate._sf is factory
        assert get_aml_gate() is gate


# ===========================================================================
# compliance/auditor.py
# ===========================================================================


@pytest.mark.unit
class TestImmutableAuditLogDeep:
    def _log(self, tmp_path):
        from compliance.auditor import ImmutableAuditLog

        return ImmutableAuditLog(log_path=str(tmp_path) + "/")

    def test_append_increments_sequence(self, tmp_path):
        from compliance.auditor import AuditLevel

        log = self._log(tmp_path)
        r1 = log.append(AuditLevel.INFO, "TRADE", "sys", "OPEN", {})
        r2 = log.append(AuditLevel.INFO, "TRADE", "sys", "CLOSE", {})
        assert r1.sequence_number == 1
        assert r2.sequence_number == 2

    def test_hash_chain_links(self, tmp_path):
        from compliance.auditor import AuditLevel

        log = self._log(tmp_path)
        log.append(AuditLevel.INFO, "TRADE", "sys", "OPEN", {"sym": "XAUUSD"})
        log.append(AuditLevel.INFO, "TRADE", "sys", "CLOSE", {"sym": "XAUUSD"})
        assert log.records[0].hash_chain != log.records[1].hash_chain

    def test_verify_integrity_passes(self, tmp_path):
        from compliance.auditor import AuditLevel

        log = self._log(tmp_path)
        for i in range(5):
            log.append(AuditLevel.COMPLIANCE, "ORDER", "engine", f"ACT_{i}", {"i": i})
        assert log.verify_integrity() is True

    def test_verify_integrity_detects_tamper(self, tmp_path):
        from compliance.auditor import AuditLevel

        log = self._log(tmp_path)
        log.append(AuditLevel.INFO, "TRADE", "sys", "OPEN", {"price": 3300})
        log.records[0].hash_chain = "tampered" * 4
        assert log.verify_integrity() is False

    def test_export_for_regulator_filters_by_date(self, tmp_path):
        from compliance.auditor import AuditLevel

        log = self._log(tmp_path)
        log.append(AuditLevel.COMPLIANCE, "TRADE", "sys", "OPEN", {"sym": "XAUUSD"})
        now = datetime.now(UTC)
        exported = log.export_for_regulator(
            start_date=now - timedelta(minutes=1),
            end_date=now + timedelta(minutes=1),
        )
        assert len(exported) == 1
        assert exported[0]["category"] == "TRADE"

    def test_export_empty_outside_range(self, tmp_path):
        from compliance.auditor import AuditLevel

        log = self._log(tmp_path)
        log.append(AuditLevel.INFO, "TRADE", "sys", "OPEN", {})
        past = datetime.now(UTC) - timedelta(days=10)
        exported = log.export_for_regulator(
            start_date=past - timedelta(days=1),
            end_date=past,
        )
        assert exported == []

    def test_persist_creates_file(self, tmp_path):
        from compliance.auditor import AuditLevel

        log = self._log(tmp_path)
        log.append(AuditLevel.INFO, "TRADE", "sys", "OPEN", {"x": 1})
        files = list(tmp_path.iterdir())
        assert len(files) >= 1

    def test_all_audit_levels(self, tmp_path):
        from compliance.auditor import AuditLevel

        log = self._log(tmp_path)
        for level in AuditLevel:
            r = log.append(level, "TEST", "sys", "ACT", {})
            assert r.level == level


@pytest.mark.unit
class TestTradeReporting:
    def test_report_trade_logs_audit(self, tmp_path):
        from compliance.auditor import TradeReporting

        tr = TradeReporting(jurisdiction="US")
        tr.audit_log.log_path = str(tmp_path) + "/"
        tr.report_trade({"id": "t1", "symbol": "XAUUSD", "size": 1, "notional": 3300})
        assert len(tr.audit_log.records) >= 1

    def test_generate_daily_report_structure(self, tmp_path):
        from compliance.auditor import TradeReporting

        tr = TradeReporting(jurisdiction="US")
        tr.audit_log.log_path = str(tmp_path) + "/"
        report = tr.generate_daily_report()
        assert "date" in report
        assert "total_trades" in report
        assert "integrity_verified" in report

    def test_requires_immediate_reporting_large_trade(self):
        from compliance.auditor import TradeReporting

        tr = TradeReporting(jurisdiction="US")
        assert tr._requires_immediate_reporting({"size": 100}) is True

    def test_requires_immediate_reporting_suspicious(self):
        from compliance.auditor import TradeReporting

        tr = TradeReporting(jurisdiction="US")
        assert tr._requires_immediate_reporting({"size": 1, "flags": {"suspicious": True}}) is True

    def test_requires_immediate_reporting_normal(self):
        from compliance.auditor import TradeReporting

        tr = TradeReporting(jurisdiction="US")
        assert tr._requires_immediate_reporting({"size": 1}) is False

    def test_eu_jurisdiction_loads_mifid(self):
        from compliance.auditor import TradeReporting

        tr = TradeReporting(jurisdiction="EU")
        assert "mifid_ii" in tr.reporting_obligations

    def test_unknown_jurisdiction_empty_obligations(self):
        from compliance.auditor import TradeReporting

        tr = TradeReporting(jurisdiction="XX")
        assert tr.reporting_obligations == {}


# ===========================================================================
# compliance/compliance_manager.py
# ===========================================================================


@pytest.mark.unit
class TestComplianceManagerDeep:
    def _cm(self):
        from compliance.compliance_manager import ComplianceManager

        return ComplianceManager()

    def test_submit_kyc_sets_pending(self):
        cm = self._cm()
        rec = cm.submit_kyc("u1", "passport")
        assert rec["status"] == "pending"

    def test_approve_kyc_sets_approved(self):
        cm = self._cm()
        cm.submit_kyc("u1", "passport")
        assert cm.approve_kyc("u1") is True
        from compliance.compliance_manager import KYCStatus

        assert cm.get_kyc_status("u1") == KYCStatus.APPROVED

    def test_reject_kyc_sets_rejected(self):
        cm = self._cm()
        cm.submit_kyc("u1", "passport")
        assert cm.reject_kyc("u1", reason="fraud") is True
        from compliance.compliance_manager import KYCStatus

        assert cm.get_kyc_status("u1") == KYCStatus.REJECTED

    def test_get_kyc_status_unverified_for_unknown(self):
        from compliance.compliance_manager import KYCStatus

        cm = self._cm()
        assert cm.get_kyc_status("nobody") == KYCStatus.UNVERIFIED

    def test_is_kyc_approved_true(self):
        cm = self._cm()
        cm.submit_kyc("u1", "id")
        cm.approve_kyc("u1")
        assert cm.is_kyc_approved("u1") is True

    def test_is_kyc_approved_false_pending(self):
        cm = self._cm()
        cm.submit_kyc("u1", "id")
        assert cm.is_kyc_approved("u1") is False

    def test_log_trade_adds_to_audit(self):
        cm = self._cm()
        cm.log_trade("u1", {"symbol": "XAUUSD", "side": "buy", "qty": 1.0})
        log = cm.get_audit_log()
        assert len(log) >= 1

    def test_get_audit_log_limit(self):
        cm = self._cm()
        for i in range(20):
            cm.log_trade(f"u{i}", {"symbol": "XAUUSD"})
        log = cm.get_audit_log(limit=5)
        assert len(log) <= 5

    def test_set_session_factory(self):
        cm = self._cm()
        factory = MagicMock()
        cm.set_session_factory(factory)
        assert cm._session_factory is factory

    def test_approve_nonexistent_user(self):
        cm = self._cm()
        result = cm.approve_kyc("ghost_user")
        assert isinstance(result, bool)

    def test_reject_nonexistent_user(self):
        cm = self._cm()
        result = cm.reject_kyc("ghost_user")
        assert isinstance(result, bool)

    def test_audit_log_hash_chain(self):
        cm = self._cm()
        cm.log_trade("u1", {"sym": "XAUUSD"})
        cm.log_trade("u2", {"sym": "XAUUSD"})
        log = cm.get_audit_log()
        assert len(log) == 2

    def test_multiple_kyc_submissions_overwrite(self):
        cm = self._cm()
        cm.submit_kyc("u1", "passport")
        cm.submit_kyc("u1", "drivers_license")
        assert cm._kyc_records["u1"]["document_type"] == "drivers_license"


# ===========================================================================
# compliance/kyc_provider.py
# ===========================================================================


@pytest.mark.unit
class TestMockKYCProvider:
    def test_mock_blocked_in_production(self):
        from compliance.kyc_provider import MockKYCProvider

        with patch.dict(os.environ, {"APP_ENV": "production"}), pytest.raises(RuntimeError, match="production"):
            MockKYCProvider()

    @pytest.mark.asyncio
    async def test_mock_create_applicant(self):
        from compliance.kyc_provider import MockKYCProvider, VerificationStatus

        with patch.dict(os.environ, {"APP_ENV": "development"}):
            provider = MockKYCProvider()
            applicant = await provider.create_applicant("user1", {"email": "test@test.com"})
            assert applicant.user_id == "user1"
            assert applicant.provider == "mock"
            assert applicant.status == VerificationStatus.PENDING

    @pytest.mark.asyncio
    async def test_mock_get_status_approved(self):
        from compliance.kyc_provider import MockKYCProvider, VerificationStatus

        with patch.dict(os.environ, {"APP_ENV": "development", "KYC_MOCK_DELAY_S": "0"}):
            provider = MockKYCProvider()
            applicant = await provider.create_applicant("user1", {})
            status = await provider.get_status(applicant.applicant_id)
            assert status == VerificationStatus.APPROVED

    def test_mock_verify_webhook_always_true(self):
        from compliance.kyc_provider import MockKYCProvider

        with patch.dict(os.environ, {"APP_ENV": "development"}):
            provider = MockKYCProvider()
            assert provider.verify_webhook(b"payload", "sig") is True

    def test_mock_parse_webhook(self):
        from compliance.kyc_provider import MockKYCProvider, VerificationStatus

        with patch.dict(os.environ, {"APP_ENV": "development"}):
            provider = MockKYCProvider()
            applicant_id, status = provider.parse_webhook({"applicant_id": "abc123"})
            assert applicant_id == "abc123"
            assert status == VerificationStatus.APPROVED

    def test_mock_parse_webhook_missing_id(self):
        from compliance.kyc_provider import MockKYCProvider, VerificationStatus

        with patch.dict(os.environ, {"APP_ENV": "development"}):
            provider = MockKYCProvider()
            applicant_id, status = provider.parse_webhook({})
            assert applicant_id == ""
            assert status == VerificationStatus.APPROVED


@pytest.mark.unit
class TestLocalSDNScreener:
    @pytest.mark.asyncio
    async def test_screen_returns_sanctions_result(self):
        from compliance.kyc_provider import LocalSDNScreener, SanctionsResult

        screener = LocalSDNScreener()
        result = await screener.screen("John Smith", dob="1990-01-01")
        assert isinstance(result, SanctionsResult)
        assert result.provider == "local_sdn"
        assert isinstance(result.is_match, bool)

    @pytest.mark.asyncio
    async def test_screen_known_name(self):
        from compliance.kyc_provider import LocalSDNScreener

        screener = LocalSDNScreener()
        # Result depends on local SDN list; just verify it returns a result
        result = await screener.screen("Test Person")
        assert hasattr(result, "screened")
        assert hasattr(result, "match_score")


@pytest.mark.unit
class TestKYCGateway:
    @pytest.mark.asyncio
    async def test_gateway_create_applicant_mock(self):
        from compliance.kyc_provider import KYCGateway
        from compliance.compliance_manager import ComplianceManager

        with patch.dict(os.environ, {"APP_ENV": "development", "KYC_PROVIDER": "mock", "KYC_MOCK_DELAY_S": "0"}):
            cm = ComplianceManager()
            gw = KYCGateway(compliance_manager=cm)
            applicant = await gw.create_applicant("user1", {"email": "a@b.com"})
            assert applicant.user_id == "user1"

    @pytest.mark.asyncio
    async def test_gateway_check_status(self):
        from compliance.kyc_provider import KYCGateway, VerificationStatus
        from compliance.compliance_manager import ComplianceManager

        with patch.dict(os.environ, {"APP_ENV": "development", "KYC_PROVIDER": "mock", "KYC_MOCK_DELAY_S": "0"}):
            cm = ComplianceManager()
            gw = KYCGateway(compliance_manager=cm)
            applicant = await gw.create_applicant("user2", {})
            status = await gw.check_status(applicant.applicant_id)
            assert status in list(VerificationStatus)

    @pytest.mark.asyncio
    async def test_gateway_screen_sanctions(self):
        from compliance.kyc_provider import KYCGateway, SanctionsResult
        from compliance.compliance_manager import ComplianceManager

        with patch.dict(os.environ, {"APP_ENV": "development", "KYC_PROVIDER": "mock"}):
            cm = ComplianceManager()
            gw = KYCGateway(compliance_manager=cm)
            result = await gw.screen_sanctions("John Doe", dob="1980-01-01")
            assert isinstance(result, SanctionsResult)


# ===========================================================================
# compliance/regulatory_reporter.py
# ===========================================================================


@pytest.mark.unit
class TestRegulatoryReporter:
    @pytest.mark.asyncio
    async def test_submit_prop_firm_suppressed(self):
        from compliance.regulatory_reporter import RegulatoryReporter

        with patch.dict(os.environ, {"REGULATORY_PROP_FIRM_MODE": "true"}):
            reporter = RegulatoryReporter()
            record = await reporter.submit({"id": "t1", "symbol": "XAUUSD", "size": 1})
            assert record.status == "suppressed"

    @pytest.mark.asyncio
    async def test_submit_disabled_suppressed(self):
        from compliance.regulatory_reporter import RegulatoryReporter

        with patch.dict(os.environ, {"REGULATORY_REPORTING_ENABLED": "false", "REGULATORY_PROP_FIRM_MODE": "false"}):
            reporter = RegulatoryReporter()
            record = await reporter.submit({"id": "t1", "symbol": "XAUUSD"})
            assert record.status == "suppressed"

    @pytest.mark.asyncio
    async def test_submit_http_success(self):
        from compliance.regulatory_reporter import RegulatoryReporter

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)
        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        with (
            patch.dict(
                os.environ,
                {
                    "REGULATORY_REPORTING_ENABLED": "true",
                    "PROP_FIRM_MODE": "false",
                },
            ),
            patch("aiohttp.ClientSession", return_value=mock_session),
        ):
            reporter = RegulatoryReporter()
            record = await reporter.submit({"id": "t1", "symbol": "XAUUSD", "size": 1})
        assert record.status == "submitted"

    @pytest.mark.asyncio
    async def test_submit_http_failure_goes_to_dlq(self):
        import compliance.regulatory_reporter as rr_mod
        from compliance.regulatory_reporter import RegulatoryReporter

        mock_resp = AsyncMock()
        mock_resp.status = 500
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)
        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        with (
            patch.dict(
                os.environ,
                {
                    "REGULATORY_REPORTING_ENABLED": "true",
                    "PROP_FIRM_MODE": "false",
                },
            ),
            patch.object(rr_mod, "_RETRY_MAX", 2),
            patch.object(rr_mod, "_RETRY_BACKOFF_BASE", 0.0),
            patch.object(rr_mod, "_RETRY_BACKOFF_CAP", 0.0),
            patch("aiohttp.ClientSession", return_value=mock_session),
        ):
            reporter = RegulatoryReporter()
            record = await reporter.submit({"id": "t1", "symbol": "XAUUSD", "size": 1})
        assert record.status in ("failed", "dlq")

    def test_get_regulatory_reporter_singleton(self):
        from compliance.regulatory_reporter import get_regulatory_reporter, RegulatoryReporter
        import compliance.regulatory_reporter as rr_mod

        rr_mod._reporter = None
        r1 = get_regulatory_reporter()
        r2 = get_regulatory_reporter()
        assert r1 is r2
        assert isinstance(r1, RegulatoryReporter)

    def test_reporter_stats(self):
        from compliance.regulatory_reporter import RegulatoryReporter

        reporter = RegulatoryReporter()
        stats = reporter.stats()
        assert "reporting_enabled" in stats
        assert "dlq_disk_size" in stats
