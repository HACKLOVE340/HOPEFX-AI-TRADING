"""
Email delivery service.

Sends transactional emails (verification, password reset) via SMTP.
Falls back to logging when SMTP is not configured (dev mode).

Required env vars for live delivery:
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, FROM_EMAIL

Optional:
    APP_BASE_URL  — base URL for links (default: http://localhost:8000)
    APP_ENV       — set to "production" to suppress dev token logging
"""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

logger = logging.getLogger(__name__)

APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:8000")
APP_ENV = os.getenv("APP_ENV", "development")


def _smtp_config() -> Optional[dict]:
    host = os.getenv("SMTP_HOST")
    if not host:
        return None
    return {
        "host": host,
        "port": int(os.getenv("SMTP_PORT", "587")),
        "user": os.getenv("SMTP_USER", ""),
        "password": os.getenv("SMTP_PASSWORD", ""),
        "from_email": os.getenv("FROM_EMAIL", os.getenv("SMTP_USER", "noreply@hopefx.io")),
        "use_tls": os.getenv("SMTP_USE_TLS", "true").lower() == "true",
    }


def _send(to: str, subject: str, html: str, text: str) -> bool:
    """Send an email. Returns True on success, False on failure."""
    cfg = _smtp_config()
    if not cfg:
        # Dev mode: log instead of sending
        logger.info(
            "EMAIL (dev — SMTP not configured): to=%s subject=%s\n%s",
            to, subject, text,
        )
        return True

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
        logger.info("Email sent: to=%s subject=%s", to, subject)
        return True
    except Exception as exc:
        logger.error("Email delivery failed to %s: %s", to, exc)
        return False


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
    html = f"""
<html><body>
<h2>Verify your HOPEFX account</h2>
<p>Hi {username},</p>
<p>Please verify your email address:</p>
<p><a href="{link}" style="background:#1a73e8;color:#fff;padding:10px 20px;
   text-decoration:none;border-radius:4px;">Verify Email</a></p>
<p>Or copy this link: <code>{link}</code></p>
<p>This link expires in 24 hours.</p>
<p>If you did not create a HOPEFX account, ignore this email.</p>
</body></html>
"""
    if APP_ENV != "production":
        logger.info("VERIFY TOKEN (dev): %s", token)
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
    html = f"""
<html><body>
<h2>Reset your HOPEFX password</h2>
<p>Hi {username},</p>
<p>A password reset was requested for your account.</p>
<p><a href="{link}" style="background:#d93025;color:#fff;padding:10px 20px;
   text-decoration:none;border-radius:4px;">Reset Password</a></p>
<p>Or copy this link: <code>{link}</code></p>
<p>This link expires in 1 hour.</p>
<p>If you did not request a reset, ignore this email.</p>
</body></html>
"""
    if APP_ENV != "production":
        logger.info("RESET TOKEN (dev): %s", token)
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
    html = f"""
<html><body>
<h2>New login detected</h2>
<p>Hi {username},</p>
<p>A new login was detected on your HOPEFX account.</p>
<ul>
  <li><strong>IP:</strong> {ip}</li>
  <li><strong>Device:</strong> {device or 'unknown'}</li>
</ul>
<p>If this was not you, <a href="{APP_BASE_URL}/auth/forgot-password">reset your password</a> immediately.</p>
</body></html>
"""
    return _send(to_email, subject, html, text)
