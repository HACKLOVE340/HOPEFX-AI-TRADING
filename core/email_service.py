# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
core/email_service.py
=====================
Transactional email delivery (verification, password reset, login alerts).

Delivery priority:
  1. SendGrid API  — if SENDGRID_API_KEY is set (95-99% deliverability)
  2. Raw SMTP      — if SMTP_HOST + SMTP_USER + SMTP_PASSWORD are set (fallback)
  3. Dev log       — if neither is configured (logs token to stdout for local dev)

Required env vars for SendGrid:
    SENDGRID_API_KEY, FROM_EMAIL

Required env vars for SMTP fallback:
    SMTP_HOST, SMTP_PORT (default 587), SMTP_USER, SMTP_PASSWORD, FROM_EMAIL

Optional:
    APP_BASE_URL  — base URL for links (default: http://localhost:8000)
    APP_ENV       — set to "production" to suppress dev token logging
"""

from __future__ import annotations

import logging
import os
import ssl

logger = logging.getLogger(__name__)

APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:8000")
APP_ENV = os.getenv("APP_ENV", "development")


# ── Transport helpers ─────────────────────────────────────────────────────────


def _send_via_sendgrid(to: str, subject: str, html: str, text: str) -> bool:
    """Send via SendGrid API. Returns True on success."""
    api_key = os.getenv("SENDGRID_API_KEY", "")
    from_email = os.getenv("FROM_EMAIL", "noreply@hopefx.io")
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail

        sg = SendGridAPIClient(api_key=api_key)
        message = Mail(
            from_email=from_email,
            to_emails=to,
            subject=subject,
            plain_text_content=text,
            html_content=html,
        )
        response = sg.send(message)
        if response.status_code in (200, 202):
            logger.info("Email sent via SendGrid: to=%s subject=%s", to, subject)
            return True
        logger.error("SendGrid error %s: %s", response.status_code, response.body)
        return False
    except Exception as exc:
        logger.error("SendGrid delivery failed to %s: %s", to, exc)
        return False


def _smtp_config() -> dict | None:
    host = os.getenv("SMTP_HOST")
    if not host:
        return None
    return {
        "host": host,
        "port": int(os.getenv("SMTP_PORT", "587")),
        "user": os.getenv("SMTP_USER", ""),
        "password": os.getenv("SMTP_PASSWORD", ""),
        "from_email": os.getenv(
            "FROM_EMAIL",
            os.getenv("SMTP_USER", "noreply@hopefx.io"),
        ),
        "use_tls": os.getenv("SMTP_USE_TLS", "true").lower() == "true",
    }


def _send_via_smtp(to: str, subject: str, html: str, text: str) -> bool:
    """Send via raw SMTP (fallback). Returns True on success."""
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    cfg = _smtp_config()
    if not cfg:
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = cfg["from_email"]
    msg["To"] = to
    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        if cfg["use_tls"]:
            ctx = ssl.create_default_context()
            with smtplib.SMTP(cfg["host"], cfg["port"]) as server:
                server.ehlo()
                server.starttls(context=ctx)
                if cfg["user"]:
                    server.login(cfg["user"], cfg["password"])
                server.sendmail(cfg["from_email"], to, msg.as_string())
        else:
            with smtplib.SMTP_SSL(cfg["host"], cfg["port"]) as server:
                if cfg["user"]:
                    server.login(cfg["user"], cfg["password"])
                server.sendmail(cfg["from_email"], to, msg.as_string())
        logger.info("Email sent via SMTP: to=%s subject=%s", to, subject)
        return True
    except Exception as exc:
        logger.error("SMTP delivery failed to %s: %s", to, exc)
        return False


def active_transport() -> str | None:
    """Name the transport ``_send`` would use, or None if there is none.

    Shares the precedence below so the two cannot drift. This exists because
    ``_send`` returns ``True`` when nothing is configured — it logs the message
    instead, which is right for a signup email in dev and wrong for
    ``/admin/settings/test-smtp``, whose entire job is answering "is mail
    configured?". Without this, that endpoint reports a working SMTP setup on a
    box with no mail transport at all.
    """
    if os.getenv("SENDGRID_API_KEY"):
        return "sendgrid"
    if _smtp_config():
        return "smtp"
    return None


def _send(to: str, subject: str, html: str, text: str) -> bool:
    """Send an email using the best available transport."""
    # 1. SendGrid (primary — high deliverability)
    if os.getenv("SENDGRID_API_KEY"):
        return _send_via_sendgrid(to, subject, html, text)

    # 2. SMTP fallback
    if _smtp_config():
        return _send_via_smtp(to, subject, html, text)

    # 3. Dev mode — log instead of sending
    logger.info(
        "EMAIL (dev — no transport configured): to=%s subject=%s\n%s",
        to,
        subject,
        text,
    )
    return True


# ── Public API ────────────────────────────────────────────────────────────────


def send_verification_email(to_email: str, username: str, token: str) -> bool:
    """Send email address verification link."""
    link = f"{APP_BASE_URL}/auth/verify-email?token={token}"
    subject = "Verify your HOPEFX account"
    text = (
        f"Hi {username},\n\n"
        f"Please verify your email address by clicking the link below:\n\n"
        f"{link}\n\n"
        f"This link expires in 24 hours.\n\n"
        f"If you did not create a HOPEFX account, ignore this email.\n"
    )
    html = (
        f"<html><body>"
        f"<h2>Verify your HOPEFX account</h2>"
        f"<p>Hi {username},</p>"
        f"<p>Please verify your email address:</p>"
        f'<p><a href="{link}" style="background:#1a73e8;color:#fff;padding:10px 20px;'
        f'text-decoration:none;border-radius:4px;">Verify Email</a></p>'
        f"<p>Or copy this link: <code>{link}</code></p>"
        f"<p>This link expires in 24 hours.</p>"
        f"<p>If you did not create a HOPEFX account, ignore this email.</p>"
        f"</body></html>"
    )
    if APP_ENV != "production":
        # Log only the token length in dev — never the value — so logs are
        # useful for debugging without leaking the credential.
        logger.info("VERIFY TOKEN (dev): issued %d-char token for %s", len(token), to_email)
    return _send(to_email, subject, html, text)


def send_password_reset_email(to_email: str, username: str, token: str) -> bool:
    """Send password reset link."""
    link = f"{APP_BASE_URL}/auth/reset-password?token={token}"
    subject = "Reset your HOPEFX password"
    text = (
        f"Hi {username},\n\n"
        f"A password reset was requested for your account.\n\n"
        f"Click the link below to set a new password:\n\n"
        f"{link}\n\n"
        f"This link expires in 1 hour.\n\n"
        f"If you did not request a reset, ignore this email — your password is unchanged.\n"
    )
    html = (
        f"<html><body>"
        f"<h2>Reset your HOPEFX password</h2>"
        f"<p>Hi {username},</p>"
        f"<p>A password reset was requested for your account.</p>"
        f'<p><a href="{link}" style="background:#d93025;color:#fff;padding:10px 20px;'
        f'text-decoration:none;border-radius:4px;">Reset Password</a></p>'
        f"<p>Or copy this link: <code>{link}</code></p>"
        f"<p>This link expires in 1 hour.</p>"
        f"<p>If you did not request a reset, ignore this email.</p>"
        f"</body></html>"
    )
    if APP_ENV != "production":
        logger.info("RESET TOKEN (dev): issued %d-char token for %s", len(token), to_email)
    return _send(to_email, subject, html, text)


def send_login_alert(to_email: str, username: str, ip: str, device: str) -> bool:
    """Notify user of a new login from an unrecognised device/IP."""
    subject = "New login to your HOPEFX account"
    text = (
        f"Hi {username},\n\n"
        f"A new login was detected on your account.\n\n"
        f"IP address: {ip}\n"
        f"Device: {device or 'unknown'}\n\n"
        f"If this was you, no action is needed.\n"
        f"If not, change your password immediately at {APP_BASE_URL}/auth/forgot-password\n"
    )
    html = (
        f"<html><body>"
        f"<h2>New login detected</h2>"
        f"<p>Hi {username},</p>"
        f"<p>A new login was detected on your HOPEFX account.</p>"
        f"<ul><li><strong>IP:</strong> {ip}</li>"
        f"<li><strong>Device:</strong> {device or 'unknown'}</li></ul>"
        f'<p>If this was not you, <a href="{APP_BASE_URL}/auth/forgot-password">'
        f"reset your password</a> immediately.</p>"
        f"</body></html>"
    )
    return _send(to_email, subject, html, text)
