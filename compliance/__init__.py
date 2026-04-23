# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
compliance — KYC/AML, regulatory reporting, and audit trail.

Public API
----------
    KYCGateway              Multi-provider KYC (Sumsub, Onfido) with webhook handling.
    AMLEngine               Transaction monitoring, sanctions screening, PEP checks.
    ComplianceAuditor       Immutable audit trail for all compliance decisions.
    RegulatoryReporter      Automated regulatory report generation (MiFID II, etc.).
"""

from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

try:
    from compliance.kyc_provider import KYCGateway, get_kyc_gateway, init_kyc_gateway
except Exception as _exc:
    logger.debug("compliance.kyc_provider unavailable: %s", _exc)

try:
    from compliance.aml import AMLEngine
except Exception as _exc:
    logger.debug("compliance.aml unavailable: %s", _exc)

try:
    from compliance.auditor import ComplianceAuditor
except Exception as _exc:
    logger.debug("compliance.auditor unavailable: %s", _exc)

try:
    from compliance.regulatory_reporter import RegulatoryReporter
except Exception as _exc:
    logger.debug("compliance.regulatory_reporter unavailable: %s", _exc)

__all__ = [
    "AMLEngine",
    "ComplianceAuditor",
    "KYCGateway",
    "RegulatoryReporter",
    "get_kyc_gateway",
    "init_kyc_gateway",
]
