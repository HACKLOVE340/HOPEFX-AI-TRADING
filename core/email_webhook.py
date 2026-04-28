# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
core/email_webhook.py
=====================
SendGrid Event Webhook handler — ECDSA P-256 signature verification and
email suppression recording.

Extracted from app.py to keep the application entry point under 300 lines.

Register with:
    from core.email_webhook import register_email_webhook
    register_email_webhook(app)
"""

from __future__ import annotations

import logging
import os
from typing import ClassVar

from fastapi import FastAPI, HTTPException, Request

logger = logging.getLogger(__name__)


def _verify_sendgrid_signature(
    public_key_b64: str,
    payload: bytes,
    signature_b64: str,
    timestamp: str,
) -> bool:
    """
    Verify a SendGrid Event Webhook ECDSA P-256 signature.

    SendGrid signs (timestamp + payload) with an ECDSA P-256 private key.
    The matching public key is in the SendGrid dashboard under
    Settings → Mail Settings → Event Webhook → Signature Verification.
    """
    try:
        import base64

        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ec import (
            ECDSA,
            EllipticCurvePublicKey,
        )
        from cryptography.hazmat.primitives.hashes import SHA256
        from cryptography.hazmat.primitives.serialization import load_der_public_key

        der = base64.b64decode(public_key_b64)
        pub_key: EllipticCurvePublicKey = load_der_public_key(der)  # type: ignore[assignment]
        sig = base64.b64decode(signature_b64)
        signed_payload = timestamp.encode() + payload
        pub_key.verify(sig, signed_payload, ECDSA(SHA256()))
        return True
    except InvalidSignature:
        return False
    except Exception as exc:
        logger.error("SendGrid signature verification error: %s", exc)
        return False


def register_email_webhook(app: FastAPI) -> None:
    """Mount the SendGrid webhook handler on *app*."""

    @app.post("/api/email/webhook", tags=["Email"], include_in_schema=False)
    async def sendgrid_webhook(request: Request):
        """
        Receive SendGrid Event Webhook POSTs (bounce, spam_report, unsubscribe).

        Authentication:
          Verifies the ECDSA P-256 signature using the public key from
          SENDGRID_WEBHOOK_PUBLIC_KEY env var.  Requests without a valid
          signature are rejected with 403.  Set SENDGRID_WEBHOOK_VERIFY=false
          to disable verification during local development only.

        Suppression:
          Writes bounced/spam/unsubscribed addresses to email_suppressions.
          EmailChannel.send() checks this table before every dispatch.
        """
        raw_body = await request.body()

        verify = os.getenv("SENDGRID_WEBHOOK_VERIFY", "true").lower() != "false"
        webhook_pub_key = os.getenv("SENDGRID_WEBHOOK_PUBLIC_KEY", "")

        if verify:
            if not webhook_pub_key:
                logger.error(
                    "SendGrid webhook received but SENDGRID_WEBHOOK_PUBLIC_KEY is not set — "
                    "rejecting request. Set the key or SENDGRID_WEBHOOK_VERIFY=false for dev."
                )
                raise HTTPException(status_code=403, detail="Webhook signature key not configured")

            sig = request.headers.get("X-Twilio-Email-Event-Webhook-Signature", "")
            ts = request.headers.get("X-Twilio-Email-Event-Webhook-Timestamp", "")

            if not sig or not ts:
                logger.warning("SendGrid webhook missing signature headers — rejected")
                raise HTTPException(status_code=403, detail="Missing webhook signature headers")

            if not _verify_sendgrid_signature(webhook_pub_key, raw_body, sig, ts):
                logger.critical(
                    "SendGrid webhook SIGNATURE INVALID — possible spoofed request from %s",
                    request.client.host if request.client else "unknown",
                )
                raise HTTPException(status_code=403, detail="Invalid webhook signature")

        import json as _json

        try:
            events = _json.loads(raw_body)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid JSON payload") from None

        if not isinstance(events, list):
            events = [events]

        suppression_events = {
            "bounce",
            "spam_report",
            "unsubscribe",
            "group_unsubscribe",
        }
        suppressed: ClassVar[list[str]] = []

        for event in events:
            event_type = event.get("event", "")
            email = event.get("email", "").lower().strip()
            if not email or event_type not in suppression_events:
                continue

            try:
                from sqlalchemy.orm import sessionmaker

                from core.app_state import app_state
                from database.models import EmailSuppression

                if app_state.db_engine:
                    _Session = sessionmaker(bind=app_state.db_engine)
                    with _Session() as session:
                        exists = session.query(EmailSuppression).filter_by(email=email).first()
                        if not exists:
                            session.add(EmailSuppression(email=email, reason=event_type))
                            session.commit()
                            suppressed.append(email)
                            logger.info("Email suppressed: %s (reason: %s)", email, event_type)
            except Exception as exc:
                logger.error("Failed to record email suppression for %s: %s", email, exc)

        return {"suppressed": suppressed, "processed": len(events)}
