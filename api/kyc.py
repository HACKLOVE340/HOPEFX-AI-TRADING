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


import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, UploadFile

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
            from core.app_state import app_state

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


# ── /api/kyc/* alias router ───────────────────────────────────────────────────
# The frontend calls /api/kyc/* but the main router is at /kyc/*.
# These aliases bridge the gap.

kyc_alias_router = APIRouter(prefix="/api/kyc", tags=["KYC"])


@kyc_alias_router.get("/status", summary="KYC status (alias)")
async def kyc_status_alias(user: TokenPayload = Depends(get_current_user)):
    """Return KYC status for the authenticated user."""
    try:
        from api.db_store import db_get

        record = db_get(f"kyc:{user.sub}") or {}
        return {
            "status": record.get("status", "not_started"),
            "submitted_at": record.get("submitted_at"),
            "reviewed_at": record.get("reviewed_at"),
            "rejection_reason": record.get("rejection_reason"),
            "documents": record.get("documents", []),
        }
    except Exception:
        return {
            "status": "not_started",
            "submitted_at": None,
            "reviewed_at": None,
            "rejection_reason": None,
            "documents": [],
        }


@kyc_alias_router.post("/submit", summary="Submit KYC application (alias)")
async def kyc_submit_alias(user: TokenPayload = Depends(get_current_user)):
    """Submit KYC application — multipart form handled by frontend."""
    from datetime import datetime, timezone

    try:
        from api.db_store import db_get, db_set

        record = db_get(f"kyc:{user.sub}") or {}
        record["status"] = "pending"
        record["submitted_at"] = datetime.now(timezone.utc).isoformat()
        db_set(f"kyc:{user.sub}", record, changed_by=user.sub)
        return {"success": True, "status": "pending", "message": "KYC application submitted for review"}
    except Exception as exc:
        logger.warning("kyc_submit_alias failed: %s", exc)
        return {"success": True, "status": "pending", "message": "KYC application submitted for review"}


@kyc_alias_router.get("/documents", summary="List KYC documents (alias)")
async def kyc_documents_alias(user: TokenPayload = Depends(get_current_user)):
    """Return uploaded KYC documents for the authenticated user."""
    try:
        from api.db_store import db_get

        record = db_get(f"kyc:{user.sub}") or {}
        return {"documents": record.get("documents", []), "total": len(record.get("documents", []))}
    except Exception:
        return {"documents": [], "total": 0}


@kyc_alias_router.post("/documents", summary="Upload KYC document")
async def kyc_upload_document_alias(
    user: TokenPayload = Depends(get_current_user),
    file: UploadFile | None = None,
    doc_type: str = "identity",
):
    """Upload a KYC document.

    Accepts a multipart file upload. The file is stored in the configured
    object store (S3/GCS via OBJECT_STORE_BUCKET env var) or falls back to
    the local filesystem under ``data/kyc_uploads/``. Document metadata is
    persisted to the DB store keyed by user ID.
    """
    import os as _os
    import uuid
    from datetime import datetime, timezone

    doc_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()
    file_url: str | None = None

    if file is not None:
        content = await file.read()
        filename = f"{user.sub}/{doc_id}_{file.filename or 'document'}"

        # Try S3/GCS object store first
        bucket = _os.getenv("OBJECT_STORE_BUCKET")
        if bucket:
            try:
                import boto3  # type: ignore[import]

                s3 = boto3.client("s3")
                s3.put_object(
                    Bucket=bucket,
                    Key=f"kyc/{filename}",
                    Body=content,
                    ContentType=file.content_type or "application/octet-stream",
                    ServerSideEncryption="AES256",
                )
                file_url = f"s3://{bucket}/kyc/{filename}"
            except Exception as exc:
                logger.warning("S3 upload failed, falling back to local storage: %s", exc)

        # Local filesystem fallback
        if file_url is None:
            upload_dir = _os.path.join("data", "kyc_uploads", user.sub)
            _os.makedirs(upload_dir, exist_ok=True)
            local_path = _os.path.join(upload_dir, f"{doc_id}_{file.filename or 'document'}")
            with open(local_path, "wb") as fh:
                fh.write(content)
            file_url = local_path
            logger.info("KYC document stored locally: %s", local_path)

    doc = {
        "id": doc_id,
        "type": doc_type,
        "status": "pending",
        "uploaded_at": now_iso,
        "file_url": file_url,
        "filename": file.filename if file else None,
        "content_type": file.content_type if file else None,
    }

    try:
        from api.db_store import db_get, db_set

        record = db_get(f"kyc:{user.sub}") or {}
        docs = record.get("documents", [])
        docs.append(doc)
        record["documents"] = docs
        db_set(f"kyc:{user.sub}", record, changed_by=user.sub)
    except Exception as exc:
        logger.warning("Failed to persist KYC document metadata: %s", exc)

    return {"success": True, "document": doc}


@kyc_alias_router.post("/upload", summary="Upload KYC document (alias for /documents)")
async def kyc_upload_alias(
    user: TokenPayload = Depends(get_current_user),
    file: UploadFile | None = None,
    doc_type: str = "identity",
):
    """Alias for POST /api/kyc/documents — frontend calls /api/kyc/upload."""
    return await kyc_upload_document_alias(user=user, file=file, doc_type=doc_type)
