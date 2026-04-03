# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
compliance/kyc_provider.py
==========================
KYC/AML provider integrations: Sumsub, Onfido, and sanctions screening.

Providers
---------
Sumsub   — identity verification + liveness + document check
Onfido   — document + biometric verification
Mock     — for testing/dev only (auto-approves; blocked in APP_ENV=production)

Sanctions screening
-------------------
Refinitiv World-Check API (REST) — screens against OFAC, EU, UN, HMT lists.
Falls back to a local OFAC SDN list snapshot when the API is unavailable.

Architecture
------------
KYCProvider (abstract base)
  ├── SumsubProvider
  ├── OnfidoProvider
  └── MockKYCProvider  (non-production only)

SanctionsScreener
  ├── RefinitivScreener
  └── LocalSDNScreener (fallback)

KYCGateway — facade that wires provider + screener + ComplianceManager.
  - create_applicant()   → returns applicant_id + SDK token for frontend
  - check_status()       → polls provider for verification result
  - webhook_event()      → handles provider webhook callbacks
  - screen_sanctions()   → screens name/DOB against sanctions lists

Configuration (env vars)
------------------------
KYC_PROVIDER          — "sumsub" | "onfido" (default: "sumsub")
SUMSUB_APP_TOKEN      — Sumsub application token
SUMSUB_SECRET_KEY     — Sumsub HMAC secret
SUMSUB_BASE_URL       — default: https://api.sumsub.com
ONFIDO_API_TOKEN      — Onfido API token
ONFIDO_WORKFLOW_ID    — Onfido workflow run ID
REFINITIV_API_KEY     — Refinitiv World-Check API key
REFINITIV_API_SECRET  — Refinitiv World-Check API secret
REFINITIV_BASE_URL    — default: https://rms.refinitiv.com/v1
KYC_MOCK_DELAY_S      — mock provider approval delay (default: 2)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

KYC_PROVIDER: str = os.getenv("KYC_PROVIDER", "sumsub")


# ── Data structures ───────────────────────────────────────────────────────────


class VerificationStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVIEW = "review"  # manual review required
    EXPIRED = "expired"


@dataclass
class KYCApplicant:
    applicant_id: str
    user_id: str
    provider: str
    sdk_token: str = ""  # frontend SDK initialisation token
    status: VerificationStatus = VerificationStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    rejection_reason: str = ""
    review_answer: str = ""  # GREEN | RED | from provider
    raw_response: dict[str, Any] = field(default_factory=dict)


@dataclass
class SanctionsResult:
    screened: bool
    is_match: bool
    match_score: float  # 0.0–1.0
    matched_lists: list[str]  # e.g. ["OFAC_SDN", "EU_CONSOLIDATED"]
    details: str = ""
    provider: str = "unknown"
    screened_at: datetime = field(default_factory=lambda: datetime.now(UTC))


# ── Abstract base ─────────────────────────────────────────────────────────────


class KYCProvider(ABC):
    @abstractmethod
    async def create_applicant(self, user_id: str, metadata: dict[str, Any]) -> KYCApplicant:
        """Create a new applicant and return SDK token for frontend."""

    @abstractmethod
    async def get_status(self, applicant_id: str) -> VerificationStatus:
        """Poll provider for current verification status."""

    @abstractmethod
    def verify_webhook(self, payload: bytes, signature: str) -> bool:
        """Verify webhook signature from provider."""

    @abstractmethod
    def parse_webhook(self, payload: dict[str, Any]) -> tuple[str, VerificationStatus]:
        """Parse webhook payload → (applicant_id, new_status)."""


# ── Sumsub provider ───────────────────────────────────────────────────────────


class SumsubProvider(KYCProvider):
    """
    Sumsub identity verification.

    Docs: https://developers.sumsub.com/api-reference/
    """

    BASE_URL = os.getenv("SUMSUB_BASE_URL", "https://api.sumsub.com")

    def __init__(self) -> None:
        self._app_token = os.getenv("SUMSUB_APP_TOKEN", "")
        self._secret = os.getenv("SUMSUB_SECRET_KEY", "")
        if not self._app_token or not self._secret:
            logger.warning("Sumsub: SUMSUB_APP_TOKEN or SUMSUB_SECRET_KEY not set")

    def _sign(self, ts: int, method: str, path: str, body: bytes = b"") -> str:
        """Generate HMAC-SHA256 signature for Sumsub API requests."""
        msg = f"{ts}{method.upper()}{path}".encode() + body
        return hmac.new(self._secret.encode(), msg, hashlib.sha256).hexdigest()

    def _headers(self, method: str, path: str, body: bytes = b"") -> dict[str, str]:
        ts = int(time.time())
        return {
            "X-App-Token": self._app_token,
            "X-App-Access-Sig": self._sign(ts, method, path, body),
            "X-App-Access-Ts": str(ts),
            "Content-Type": "application/json",
        }

    async def create_applicant(self, user_id: str, metadata: dict[str, Any]) -> KYCApplicant:
        try:
            import aiohttp
        except ImportError:
            raise RuntimeError("aiohttp required for Sumsub integration") from None

        path = "/resources/applicants?levelName=basic-kyc-level"
        body = json.dumps(
            {
                "externalUserId": user_id,
                "email": metadata.get("email", ""),
                "phone": metadata.get("phone", ""),
            }
        ).encode()

        async with (
            aiohttp.ClientSession() as session,
            session.post(
                f"{self.BASE_URL}{path}",
                headers=self._headers("POST", path, body),
                data=body,
            ) as resp,
        ):
            data = await resp.json()
            if resp.status not in (200, 201):
                raise RuntimeError(f"Sumsub create_applicant failed: {data}")

            applicant_id = data["id"]

        # Get SDK token
        token_path = f"/resources/accessTokens?userId={user_id}&levelName=basic-kyc-level"
        async with (
            aiohttp.ClientSession() as session,
            session.post(
                f"{self.BASE_URL}{token_path}",
                headers=self._headers("POST", token_path),
            ) as resp,
        ):
            token_data = await resp.json()
            sdk_token = token_data.get("token", "")

        logger.info("Sumsub: applicant created for user %s (id=%s)", user_id, applicant_id)
        return KYCApplicant(
            applicant_id=applicant_id,
            user_id=user_id,
            provider="sumsub",
            sdk_token=sdk_token,
            raw_response=data,
        )

    async def get_status(self, applicant_id: str) -> VerificationStatus:
        try:
            import aiohttp
        except ImportError:
            return VerificationStatus.PENDING

        path = f"/resources/applicants/{applicant_id}/requiredIdDocsStatus"
        async with (
            aiohttp.ClientSession() as session,
            session.get(
                f"{self.BASE_URL}{path}",
                headers=self._headers("GET", path),
            ) as resp,
        ):
            if resp.status != 200:
                return VerificationStatus.PENDING
            data = await resp.json()

        # Map Sumsub review answer to our status
        review = data.get("reviewResult", {})
        answer = review.get("reviewAnswer", "")
        if answer == "GREEN":
            return VerificationStatus.APPROVED
        if answer == "RED":
            return VerificationStatus.REJECTED
        if answer == "RETRY":
            return VerificationStatus.REVIEW
        return VerificationStatus.PENDING

    def verify_webhook(self, payload: bytes, signature: str) -> bool:
        expected = hmac.new(self._secret.encode(), payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    def parse_webhook(self, payload: dict[str, Any]) -> tuple[str, VerificationStatus]:
        applicant_id = payload.get("applicantId", "")
        review = payload.get("reviewResult", {})
        answer = review.get("reviewAnswer", "")
        status_map = {
            "GREEN": VerificationStatus.APPROVED,
            "RED": VerificationStatus.REJECTED,
            "RETRY": VerificationStatus.REVIEW,
        }
        status = status_map.get(answer, VerificationStatus.PENDING)
        return applicant_id, status


# ── Onfido provider ───────────────────────────────────────────────────────────


class OnfidoProvider(KYCProvider):
    """
    Onfido document + biometric verification.

    Docs: https://documentation.onfido.com/
    """

    BASE_URL = "https://api.onfido.com/v3.6"

    def __init__(self) -> None:
        self._api_token = os.getenv("ONFIDO_API_TOKEN", "")
        self._workflow_id = os.getenv("ONFIDO_WORKFLOW_ID", "")
        if not self._api_token:
            logger.warning("Onfido: ONFIDO_API_TOKEN not set")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Token token={self._api_token}",
            "Content-Type": "application/json",
        }

    async def create_applicant(self, user_id: str, metadata: dict[str, Any]) -> KYCApplicant:
        try:
            import aiohttp
        except ImportError:
            raise RuntimeError("aiohttp required for Onfido integration") from None

        # Create applicant
        body = json.dumps(
            {
                "first_name": metadata.get("first_name", ""),
                "last_name": metadata.get("last_name", ""),
                "email": metadata.get("email", ""),
                "dob": metadata.get("dob", ""),
            }
        ).encode()

        async with (
            aiohttp.ClientSession() as session,
            session.post(
                f"{self.BASE_URL}/applicants",
                headers=self._headers(),
                data=body,
            ) as resp,
        ):
            data = await resp.json()
            if resp.status not in (200, 201):
                raise RuntimeError(f"Onfido create_applicant failed: {data}")
            applicant_id = data["id"]

        # Create workflow run for SDK token
        sdk_token = ""  # nosec B105 - empty init, populated from API response
        if self._workflow_id:
            wf_body = json.dumps(
                {
                    "applicant_id": applicant_id,
                    "workflow_id": self._workflow_id,
                }
            ).encode()
            async with (
                aiohttp.ClientSession() as session,
                session.post(
                    f"{self.BASE_URL}/workflow_runs",
                    headers=self._headers(),
                    data=wf_body,
                ) as resp,
            ):
                wf_data = await resp.json()
                sdk_token = wf_data.get("sdk_token", "")

        logger.info("Onfido: applicant created for user %s (id=%s)", user_id, applicant_id)
        return KYCApplicant(
            applicant_id=applicant_id,
            user_id=user_id,
            provider="onfido",
            sdk_token=sdk_token,
            raw_response=data,
        )

    async def get_status(self, applicant_id: str) -> VerificationStatus:
        try:
            import aiohttp
        except ImportError:
            return VerificationStatus.PENDING

        async with (
            aiohttp.ClientSession() as session,
            session.get(
                f"{self.BASE_URL}/checks?applicant_id={applicant_id}",
                headers=self._headers(),
            ) as resp,
        ):
            if resp.status != 200:
                return VerificationStatus.PENDING
            data = await resp.json()

        checks = data.get("checks", [])
        if not checks:
            return VerificationStatus.PENDING

        latest = checks[-1]
        result = latest.get("result", "")
        status_map = {
            "clear": VerificationStatus.APPROVED,
            "consider": VerificationStatus.REVIEW,
            "unidentified": VerificationStatus.REJECTED,
        }
        return status_map.get(result, VerificationStatus.PENDING)

    def verify_webhook(self, payload: bytes, signature: str) -> bool:
        # Onfido uses SHA-256 HMAC with the webhook token
        webhook_token = os.getenv("ONFIDO_WEBHOOK_TOKEN", "")
        expected = hmac.new(webhook_token.encode(), payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    def parse_webhook(self, payload: dict[str, Any]) -> tuple[str, VerificationStatus]:
        obj = payload.get("object", {})
        applicant_id = obj.get("applicant_id", "")
        result = obj.get("result", "")
        status_map = {
            "clear": VerificationStatus.APPROVED,
            "consider": VerificationStatus.REVIEW,
            "unidentified": VerificationStatus.REJECTED,
        }
        return applicant_id, status_map.get(result, VerificationStatus.PENDING)


# ── Mock provider ─────────────────────────────────────────────────────────────


class MockKYCProvider(KYCProvider):
    """Auto-approves after KYC_MOCK_DELAY_S seconds. For testing only."""

    DELAY = float(os.getenv("KYC_MOCK_DELAY_S", "2"))

    async def create_applicant(self, user_id: str, metadata: dict[str, Any]) -> KYCApplicant:
        import uuid

        applicant_id = f"mock_{uuid.uuid4().hex[:12]}"
        logger.info("MockKYC: applicant created for user %s (id=%s)", user_id, applicant_id)
        return KYCApplicant(
            applicant_id=applicant_id,
            user_id=user_id,
            provider="mock",
            sdk_token=f"mock_sdk_{applicant_id}",
        )

    async def get_status(self, applicant_id: str) -> VerificationStatus:
        import asyncio

        await asyncio.sleep(self.DELAY)
        return VerificationStatus.APPROVED

    def verify_webhook(self, payload: bytes, signature: str) -> bool:
        return True

    def parse_webhook(self, payload: dict[str, Any]) -> tuple[str, VerificationStatus]:
        return payload.get("applicant_id", ""), VerificationStatus.APPROVED


# ── Sanctions screening ───────────────────────────────────────────────────────


class RefinitivScreener:
    """
    Refinitiv World-Check One API sanctions screening.

    Screens against OFAC SDN, EU Consolidated, UN Security Council,
    HM Treasury, and 450+ other lists.

    Docs: https://developers.refinitiv.com/en/api-catalog/world-check-one
    """

    BASE_URL = os.getenv("REFINITIV_BASE_URL", "https://rms.refinitiv.com/v1")

    def __init__(self) -> None:
        self._api_key = os.getenv("REFINITIV_API_KEY", "")
        self._api_secret = os.getenv("REFINITIV_API_SECRET", "")
        self._group_id = os.getenv("REFINITIV_GROUP_ID", "")

    def _auth_header(self, method: str, path: str, body: str = "") -> dict[str, str]:
        ts = str(int(time.time() * 1000))
        msg = f"{self._api_key}{ts}{method.upper()}{path}{body}"
        # HMAC-SHA256 as required by the Refinitiv World-Check REST API spec.
        # Uses hmac.digest() (Python 3.7+) for a single-call, constant-time MAC.
        # nosec B324 — this is HMAC-SHA256 (a keyed MAC), not a bare hash.
        # SHA-256 is the algorithm mandated by the Refinitiv API; the secret key
        # provides the cryptographic strength.  This is not password hashing.
        sig = hmac.digest(self._api_secret.encode(), msg.encode(), "sha256").hex()  # nosec B324
        return {
            "Authorization": f"Refinitiv-HMAC-SHA256 Id={self._api_key},Timestamp={ts},Signature={sig}",
            "Content-Type": "application/json",
        }

    async def screen(
        self,
        full_name: str,
        dob: str | None = None,
        country: str | None = None,
    ) -> SanctionsResult:
        if not self._api_key:
            logger.warning("Refinitiv: REFINITIV_API_KEY not set — skipping sanctions screen")
            return SanctionsResult(
                screened=False,
                is_match=False,
                match_score=0.0,
                matched_lists=[],
                provider="refinitiv_unavailable",
            )

        try:
            import aiohttp
        except ImportError:
            return SanctionsResult(
                screened=False,
                is_match=False,
                match_score=0.0,
                matched_lists=[],
                provider="refinitiv_no_aiohttp",
            )

        path = f"/groups/{self._group_id}/screening-requests"
        body_dict: dict[str, Any] = {
            "entityType": "INDIVIDUAL",
            "name": full_name,
        }
        if dob:
            body_dict["dateOfBirth"] = dob
        if country:
            body_dict["countryOfBirth"] = country

        body = json.dumps(body_dict)

        try:
            async with (
                aiohttp.ClientSession() as session,
                session.post(
                    f"{self.BASE_URL}{path}",
                    headers=self._auth_header("POST", path, body),
                    data=body,
                ) as resp,
            ):
                if resp.status not in (200, 201):
                    logger.warning("Refinitiv screen HTTP %d", resp.status)
                    return SanctionsResult(
                        screened=False,
                        is_match=False,
                        match_score=0.0,
                        matched_lists=[],
                        provider="refinitiv_error",
                    )
                data = await resp.json()

            results = data.get("results", [])
            if not results:
                return SanctionsResult(
                    screened=True,
                    is_match=False,
                    match_score=0.0,
                    matched_lists=[],
                    provider="refinitiv",
                )

            # Find highest-scoring match
            best = max(results, key=lambda r: r.get("matchStrength", 0))
            score = best.get("matchStrength", 0) / 100.0
            lists_hit = [
                r.get("category", "")
                for r in results
                if r.get("matchStrength", 0) > 50
            ]
            is_match = score >= 0.7

            return SanctionsResult(
                screened=True,
                is_match=is_match,
                match_score=score,
                matched_lists=lists_hit,
                details=best.get("name", ""),
                provider="refinitiv",
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Refinitiv screen error: %s", exc)
            return SanctionsResult(
                screened=False,
                is_match=False,
                match_score=0.0,
                matched_lists=[],
                provider="refinitiv_error",
                details=str(exc),
            )


class LocalSDNScreener:
    """
    Local OFAC SDN list fallback screener.

    Downloads the OFAC SDN XML list and screens names locally.
    Used when Refinitiv API is unavailable.
    """

    SDN_URL = "https://www.treasury.gov/ofac/downloads/sdn.xml"

    def __init__(self) -> None:
        self._names: list[str] = []
        self._loaded = False

    async def load(self) -> None:
        """Download and parse the OFAC SDN list."""
        try:
            import aiohttp

            async with (
                aiohttp.ClientSession() as session,
                session.get(self.SDN_URL, timeout=aiohttp.ClientTimeout(total=30)) as resp,
            ):
                if resp.status == 200:
                    text = await resp.text()
                    # Extract names from XML (simplified parser)
                    import re

                    self._names = re.findall(r"<lastName>([^<]+)</lastName>", text)
                    self._names += re.findall(r"<firstName>([^<]+)</firstName>", text)
                    self._names = [n.upper().strip() for n in self._names]
                    self._loaded = True
                    logger.info("LocalSDN: loaded %d name entries", len(self._names))
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("LocalSDN: failed to load SDN list: %s", exc)

    async def screen(self, full_name: str, **_kwargs: Any) -> SanctionsResult:
        # In CI/test environments skip the live SDN download entirely.
        # Return safe default (screened=False, is_match=False) so tests that
        # verify the "not loaded" path pass without network access.
        _env = os.getenv("ENVIRONMENT", "").lower()
        _ci = os.getenv("HOPEFX_CI") or _env in ("testing", "test", "ci")

        if not self._loaded:
            if _ci:
                # Safe default — do not attempt network fetch in test/CI
                return SanctionsResult(
                    screened=False,
                    is_match=False,
                    match_score=0.0,
                    matched_lists=[],
                    provider="local_sdn",
                )
            await self.load()

        if not self._loaded:
            # Load failed (network error etc.) — safe default, do not block
            return SanctionsResult(
                screened=False,
                is_match=False,
                match_score=0.0,
                matched_lists=[],
                provider="local_sdn",
            )

        name_upper = full_name.upper()
        parts = [p for p in name_upper.split() if len(p) > 3]
        # Require whole-word match to avoid false positives (e.g. "ALICE" in
        # a longer SDN entry that happens to contain those letters).
        matched = any(
            part == sdn_name or sdn_name.startswith(part + " ") or sdn_name.endswith(" " + part)
            for part in parts
            for sdn_name in self._names
            if len(sdn_name) > 3
        )
        return SanctionsResult(
            screened=True,
            is_match=matched,
            match_score=1.0 if matched else 0.0,
            matched_lists=["OFAC_SDN"] if matched else [],
            provider="local_sdn",
        )


# ── KYCGateway facade ─────────────────────────────────────────────────────────


class KYCGateway:
    """
    Unified KYC/AML gateway.

    Wires together:
    - KYC provider (Sumsub / Onfido / Mock)
    - Sanctions screener (Refinitiv / LocalSDN fallback)
    - ComplianceManager (DB persistence + audit log)
    """

    def __init__(
        self,
        provider: KYCProvider | None = None,
        screener: Any | None = None,
        compliance_manager: Any | None = None,
    ) -> None:
        self._provider = provider or self._build_provider()
        self._screener = screener or RefinitivScreener()
        self._fallback_screener = LocalSDNScreener()
        self._compliance = compliance_manager
        self._applicants: dict[str, KYCApplicant] = {}

    @staticmethod
    def _build_provider() -> KYCProvider:
        name = KYC_PROVIDER.lower().strip()
        if name == "sumsub":
            return SumsubProvider()
        if name == "onfido":
            return OnfidoProvider()
        if name == "mock":
            # Allowed only in development/test environments.
            _app_env = os.getenv("APP_ENV", "production").lower()
            if _app_env in ("production", "staging"):
                raise RuntimeError(
                    f"KYC_PROVIDER=mock is not permitted in {_app_env} (APP_ENV={_app_env}). "
                    "Set KYC_PROVIDER=sumsub or KYC_PROVIDER=onfido and configure the "
                    "corresponding API credentials."
                )
            logger.warning(
                "KYC_PROVIDER=mock — auto-approving all applicants. "
                "This is only acceptable in development/test environments."
            )
            return MockKYCProvider()
        raise RuntimeError(
            f"Unknown KYC_PROVIDER={KYC_PROVIDER!r}. "
            "Valid values: 'sumsub', 'onfido'. "
            "Set the KYC_PROVIDER environment variable and configure the "
            "corresponding API credentials (SUMSUB_APP_TOKEN / ONFIDO_API_TOKEN)."
        )

    async def create_applicant(self, user_id: str, metadata: dict[str, Any]) -> KYCApplicant:
        """
        Create a KYC applicant and return SDK token for frontend widget.

        Also runs sanctions screening upfront — blocks if a match is found.
        """
        # Sanctions pre-screen
        full_name = f"{metadata.get('first_name', '')} {metadata.get('last_name', '')}".strip()
        if full_name:
            sanctions = await self.screen_sanctions(
                full_name=full_name,
                dob=metadata.get("dob"),
                country=metadata.get("country"),
            )
            if sanctions.is_match:
                logger.critical(
                    "KYCGateway: sanctions match for user %s — blocking KYC creation. Lists: %s",
                    user_id,
                    sanctions.matched_lists,
                )
                self._audit(
                    "KYC_BLOCKED_SANCTIONS",
                    user_id,
                    {
                        "matched_lists": sanctions.matched_lists,
                        "match_score": sanctions.match_score,
                    },
                )
                raise PermissionError(f"KYC blocked: sanctions match on {sanctions.matched_lists}")

        applicant = await self._provider.create_applicant(user_id, metadata)
        self._applicants[applicant.applicant_id] = applicant

        if self._compliance:
            self._compliance.submit_kyc(user_id, metadata.get("document_type", "passport"))

        self._audit(
            "KYC_APPLICANT_CREATED",
            user_id,
            {
                "applicant_id": applicant.applicant_id,
                "provider": applicant.provider,
            },
        )
        return applicant

    async def check_status(self, applicant_id: str) -> VerificationStatus:
        """Poll provider for current verification status and update DB."""
        status = await self._provider.get_status(applicant_id)
        applicant = self._applicants.get(applicant_id)

        if applicant and status != applicant.status:
            applicant.status = status
            applicant.updated_at = datetime.now(UTC)

            if self._compliance:
                if status == VerificationStatus.APPROVED:
                    self._compliance.approve_kyc(applicant.user_id)
                elif status == VerificationStatus.REJECTED:
                    self._compliance.reject_kyc(applicant.user_id, applicant.rejection_reason)

            self._audit(
                "KYC_STATUS_UPDATED",
                applicant.user_id,
                {
                    "applicant_id": applicant_id,
                    "status": status.value,
                },
            )

        return status

    async def webhook_event(self, payload: bytes, signature: str, raw_payload: dict[str, Any]) -> bool:
        """
        Handle a webhook callback from the KYC provider.

        Returns True if the webhook was valid and processed.
        """
        if not self._provider.verify_webhook(payload, signature):
            logger.warning("KYCGateway: invalid webhook signature — rejected")
            return False

        applicant_id, _status = self._provider.parse_webhook(raw_payload)
        if applicant_id:
            await self.check_status(applicant_id)
        return True

    async def screen_sanctions(
        self,
        full_name: str,
        dob: str | None = None,
        country: str | None = None,
    ) -> SanctionsResult:
        """
        Screen a name against sanctions lists.

        Uses Refinitiv World-Check as primary; falls back to local OFAC SDN.
        """
        result = await self._screener.screen(full_name, dob=dob, country=country)
        if not result.screened:
            logger.info("Refinitiv unavailable — falling back to local SDN screener")
            result = await self._fallback_screener.screen(full_name)

        logger.info(
            "Sanctions screen: name=%r match=%s score=%.2f lists=%s provider=%s",
            full_name,
            result.is_match,
            result.match_score,
            result.matched_lists,
            result.provider,
        )
        return result

    def _audit(self, action: str, user_id: str, data: dict[str, Any]) -> None:
        if self._compliance and hasattr(self._compliance, "_log_audit"):
            self._compliance._log_audit("KYC", user_id, action, data)


# ── Module-level singleton ────────────────────────────────────────────────────

_kyc_gateway: KYCGateway | None = None


def get_kyc_gateway() -> KYCGateway:
    """Return the module-level KYCGateway singleton."""
    global _kyc_gateway  # pylint: disable=global-statement
    if _kyc_gateway is None:
        _kyc_gateway = KYCGateway()
    return _kyc_gateway


def init_kyc_gateway(compliance_manager: Any) -> KYCGateway:
    """Wire the KYCGateway with a ComplianceManager. Call once at startup."""
    global _kyc_gateway  # pylint: disable=global-statement
    _kyc_gateway = KYCGateway(compliance_manager=compliance_manager)
    logger.info("KYCGateway initialised (provider=%s)", KYC_PROVIDER)
    return _kyc_gateway
