# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
api/kyc.py
==========
KYC/AML REST API endpoints.

Routes
------
POST /kyc/applicants              — create applicant + get SDK token
GET  /kyc/applicants/{id}/status  — poll verification status
POST /kyc/webhooks/sumsub         — Sumsub webhook callback
POST /kyc/webhooks/onfido         — Onfido webhook callback
POST /kyc/sanctions/screen        — manual sanctions screening (admin)
GET  /kyc/status                  — current user's KYC status

All endpoints require authentication except webhooks (verified by HMAC signature).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from api.auth import TokenPayload, get_current_user, require_role
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/kyc", tags=["kyc"])

# ── Request / response models ─────────────────────────────────────────────────


class CreateApplicantRequest(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    email: str = Field(..., min_length=3, max_length=254)
    dob: str | None = Field(None, description="Date of birth YYYY-MM-DD")
    country: str | None = Field(None, description="ISO 3166-1 alpha-2 country code")
    phone: str | None = None
    document_type: str = Field("passport", description="passport | driving_licence | id_card")


class ApplicantResponse(BaseModel):
    applicant_id: str
    sdk_token: str
    provider: str
    status: str


class SanctionsScreenRequest(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=200)
    dob: str | None = None
    country: str | None = None


class SanctionsScreenResponse(BaseModel):
    screened: bool
    is_match: bool
    match_score: float
    matched_lists: list[str]
    provider: str


# ── Dependency helpers ────────────────────────────────────────────────────────


def _get_gateway():
    from compliance.kyc_provider import get_kyc_gateway

    return get_kyc_gateway()


def _require_auth(request: Request) -> dict[str, Any]:
    """Minimal auth check — delegates to existing JWT middleware."""
    try:
        from auth.jwt_handler import verify_token as decode_token

        token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if not token:
            raise HTTPException(status_code=401, detail="Missing token")
        _creds_exc = HTTPException(status_code=401, detail="Invalid token")
        return decode_token(token, _creds_exc)
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("KYC auth token decode failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid or expired token") from None


def _require_admin(request: Request) -> dict[str, Any]:
    payload = _require_auth(request)
    if payload.get("role") not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin role required")
    return payload


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/applicants", response_model=ApplicantResponse, status_code=201)
async def create_applicant(
    body: CreateApplicantRequest,
    user: TokenPayload = Depends(get_current_user),
) -> ApplicantResponse:
    """
    Create a KYC applicant and return the provider SDK token.

    The frontend uses the SDK token to initialise the provider's verification
    widget (Sumsub WebSDK or Onfido SDK). The user completes verification
    in the widget; the provider calls our webhook when done.

    Also runs a sanctions pre-screen — returns 403 if a match is found.
    """
    user_id = user.sub

    gateway = _get_gateway()
    try:
        applicant = await gateway.create_applicant(
            user_id=user_id,
            metadata={
                "first_name": body.first_name,
                "last_name": body.last_name,
                "email": body.email,
                "dob": body.dob,
                "country": body.country,
                "phone": body.phone,
                "document_type": body.document_type,
            },
        )
    except PermissionError as exc:
        logger.warning("KYC create_applicant permission denied: %s", exc)
        raise HTTPException(status_code=403, detail="Permission denied") from None
    except Exception as exc:
        logger.error("KYC create_applicant error: %s", exc)
        raise HTTPException(status_code=502, detail="KYC provider error") from None

    return ApplicantResponse(
        applicant_id=applicant.applicant_id,
        sdk_token=applicant.sdk_token,
        provider=applicant.provider,
        status=applicant.status.value,
    )


@router.get("/applicants/{applicant_id}/status")
async def get_applicant_status(
    applicant_id: str,
    user: TokenPayload = Depends(get_current_user),
) -> dict[str, str]:
    """Poll the KYC provider for the current verification status."""
    gateway = _get_gateway()
    try:
        status_val = await gateway.check_status(applicant_id)
    except Exception as exc:
        logger.error("KYC check_status error: %s", exc)
        raise HTTPException(status_code=502, detail="KYC provider error") from None
    return {"applicant_id": applicant_id, "status": status_val.value}


@router.get("/status")
async def get_my_kyc_status(user: TokenPayload = Depends(get_current_user)) -> dict[str, str]:
    """Return the current user's KYC status from the compliance manager."""
    user_id = user.sub
    try:
        from compliance.compliance_manager import ComplianceManager

        # Use the app-level compliance manager if available
        try:
            from app import app_state

            cm = getattr(app_state, "compliance_manager", None)
        except ImportError:
            cm = None
        if cm is None:
            cm = ComplianceManager()
        kyc_status = cm.get_kyc_status(user_id)
        return {"user_id": user_id, "kyc_status": kyc_status.value}
    except Exception as exc:
        logger.error("KYC status lookup error: %s", exc)
        raise HTTPException(status_code=500, detail="Status lookup failed") from None


@router.post("/webhooks/sumsub", status_code=200)
async def sumsub_webhook(
    request: Request,
    x_payload_digest: str = Header(default="", alias="X-Payload-Digest"),
) -> dict[str, str]:
    """
    Sumsub webhook callback.

    Sumsub sends a POST with X-Payload-Digest header (SHA-256 HMAC).
    We verify the signature before processing.
    """
    payload_bytes = await request.body()
    try:
        import json

        raw = json.loads(payload_bytes)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from None

    gateway = _get_gateway()
    ok = await gateway.webhook_event(payload_bytes, x_payload_digest, raw)
    if not ok:
        # 400 (not 401) — the request is unauthenticated by HMAC signature,
        # but 401 implies HTTP Bearer auth which webhooks don't use.
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    return {"status": "processed"}


@router.post("/webhooks/onfido", status_code=200)
async def onfido_webhook(
    request: Request,
    x_sha2_signature: str = Header(default="", alias="X-SHA2-Signature"),
) -> dict[str, str]:
    """
    Onfido webhook callback.

    Onfido sends X-SHA2-Signature header (HMAC-SHA256 of payload).
    """
    payload_bytes = await request.body()
    try:
        import json

        raw = json.loads(payload_bytes)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from None

    gateway = _get_gateway()
    ok = await gateway.webhook_event(payload_bytes, x_sha2_signature, raw)
    if not ok:
        # 400 (not 401) — HMAC signature mismatch is a bad request, not missing auth.
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    return {"status": "processed"}


@router.post("/sanctions/screen", response_model=SanctionsScreenResponse)
async def screen_sanctions(
    body: SanctionsScreenRequest,
    user: TokenPayload = Depends(require_role("admin")),
) -> SanctionsScreenResponse:
    """
    Manual sanctions screening. Requires admin role.

    Screens a name against Refinitiv World-Check (OFAC, EU, UN, HMT lists).
    Falls back to local OFAC SDN snapshot if Refinitiv is unavailable.
    """
    gateway = _get_gateway()
    try:
        result = await gateway.screen_sanctions(
            full_name=body.full_name,
            dob=body.dob,
            country=body.country,
        )
    except Exception as exc:
        logger.error("Sanctions screen error: %s", exc)
        raise HTTPException(status_code=502, detail="Sanctions screening error") from None

    return SanctionsScreenResponse(
        screened=result.screened,
        is_match=result.is_match,
        match_score=result.match_score,
        matched_lists=result.matched_lists,
        provider=result.provider,
    )
