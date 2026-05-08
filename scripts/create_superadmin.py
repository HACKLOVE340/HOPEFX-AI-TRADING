#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
scripts/create_superadmin.py
============================
Create or reset the superadmin account.

Usage
-----
    python scripts/create_superadmin.py
    python scripts/create_superadmin.py --email sa@hopefx.io --username superadmin
    python scripts/create_superadmin.py --reset   # reset password for existing superadmin

Password rules enforced:
  - Minimum 16 characters
  - At least 1 uppercase, 1 lowercase, 1 digit, 1 special character

Safe to run multiple times — updates the user if it already exists.
"""

from __future__ import annotations

import argparse
import os
import re
import secrets
import string
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("SECURITY_JWT_SECRET", "dev_secret_for_superadmin_seed_script_32c")
os.environ.setdefault("DATABASE_URL", "sqlite:///hopefx.db")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from auth.jwt import create_access_token, hash_password
from database.models import Base
from database.user_models import User, UserRole, UserStatus
import logging

logger = logging.getLogger(__name__)


# ── Password policy ───────────────────────────────────────────────────────────

_SPECIAL = "!@#$%^&*()-_=+[]{}|;:,.<>?"


def _generate_password() -> str:
    """
    Generate a cryptographically random password that satisfies the policy:
    16 chars, guaranteed uppercase + lowercase + digit + special.
    """
    while True:
        # Build from guaranteed character classes first
        parts = [
            secrets.choice(string.ascii_uppercase),
            secrets.choice(string.ascii_uppercase),
            secrets.choice(string.ascii_lowercase),
            secrets.choice(string.ascii_lowercase),
            secrets.choice(string.digits),
            secrets.choice(string.digits),
            secrets.choice(_SPECIAL),
            secrets.choice(_SPECIAL),
        ]
        # Fill remaining 8 chars from full pool
        pool = string.ascii_letters + string.digits + _SPECIAL
        parts += [secrets.choice(pool) for _ in range(8)]
        # Shuffle so the guaranteed chars aren't always at the front
        secrets.SystemRandom().shuffle(parts)
        pw = "".join(parts)
        if _validate_password(pw) is None:
            return pw


def _validate_password(pw: str) -> str | None:
    """Return an error message if the password fails policy, else None."""
    if len(pw) < 16:
        return "Password must be at least 16 characters."
    if not re.search(r"[A-Z]", pw):
        return "Password must contain at least one uppercase letter."
    if not re.search(r"[a-z]", pw):
        return "Password must contain at least one lowercase letter."
    if not re.search(r"\d", pw):
        return "Password must contain at least one digit."
    if not re.search(r"[!@#$%^&*()\-_=+\[\]{}|;:,.<>?]", pw):
        return "Password must contain at least one special character (!@#$%^&*…)."
    return None


# ── DB helpers ────────────────────────────────────────────────────────────────


def _get_engine():
    db_url = os.environ.get("DATABASE_URL", "sqlite:///hopefx.db")
    connect_args = {"check_same_thread": False} if db_url.startswith("sqlite") else {}
    return create_engine(db_url, connect_args=connect_args)


def _create_or_update(email: str, username: str, password: str, reset: bool) -> dict:
    engine = _get_engine()
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        existing = session.query(User).filter((User.email == email.lower()) | (User.username == username)).first()

        hashed = hash_password(password)

        if existing:
            if not reset:
                return {
                    "action": "exists",
                    "user_id": str(existing.id),
                    "username": existing.username,
                    "email": existing.email,
                    "role": existing.role,
                }
            existing.hashed_password = hashed
            existing.role = UserRole.SUPERADMIN.value
            existing.status = UserStatus.ACTIVE.value
            existing.is_email_verified = True
            existing.email_verify_token = None
            existing.email_verify_expires = None
            session.commit()
            return {
                "action": "reset",
                "user_id": str(existing.id),
                "username": existing.username,
                "email": existing.email,
                "role": existing.role,
            }

        user = User(
            id=str(uuid.uuid4()),
            email=email.lower().strip(),
            username=username.strip(),
            hashed_password=hashed,
            role=UserRole.SUPERADMIN.value,
            status=UserStatus.ACTIVE.value,
            is_email_verified=True,
            email_verify_token=None,
            email_verify_expires=None,
        )
        session.add(user)
        session.commit()
        return {
            "action": "created",
            "user_id": str(user.id),
            "username": user.username,
            "email": user.email,
            "role": user.role,
        }
    finally:
        session.close()


def _generate_token(user_id: str) -> str:
    """Generate a short-lived (15 min) JWT for immediate login verification."""
    from datetime import timedelta

    return create_access_token(
        data={"sub": user_id, "role": "superadmin", "type": "access"},
        expires_delta=timedelta(minutes=15),
    )


# ── Main ──────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Create or reset HOPEFX superadmin account")
    parser.add_argument("--email", default="superadmin@hopefx.io", help="Superadmin email")
    parser.add_argument("--username", default="superadmin", help="Superadmin username")
    parser.add_argument("--password", default=None, help="Password (auto-generated if omitted)")
    parser.add_argument("--reset", action="store_true", help="Reset password if user already exists")
    args = parser.parse_args()

    # ── Validate or generate password ─────────────────────────────────────────
    if args.password:
        err = _validate_password(args.password)
        if err:
            # Write validation error to stderr directly — not via the logger —
            # so the taint path from args.password never reaches a log sink.
            sys.stderr.write(f"\n[ERROR] {err}\n\n")
            sys.exit(1)
        password = args.password
        auto_generated = False
    else:
        password = _generate_password()
        auto_generated = True

    # ── Write to DB ───────────────────────────────────────────────────────────
    result = _create_or_update(args.email, args.username, password, args.reset)

    if result["action"] == "exists":
        logger.info("\n[INFO] Superadmin '%s' already exists (role=%s).", result['username'], result['role'])
        logger.info("       Use --reset to update the password.\n")
        return

    # ── Generate a verification token ─────────────────────────────────────────
    try:
        token = _generate_token(result["user_id"])
        token_line = f"  Bearer Token : {token}"  # nosec B105 — display string, not a credential
        token_note = "  (valid 15 min — use in Authorization: Bearer <token> header or Swagger UI)"  # nosec B105 — instructional text, not a secret
    except Exception:
        token_line = "  Bearer Token : (JWT secret not set — run app.py to generate)"  # nosec B105 — display string, not a credential
        token_note = ""  # nosec B105 — empty string, not a credential

    # ── Save credentials to restricted file ───────────────────────────────────
    pw_file = ROOT / "superadmin_credentials.txt"
    now_iso = datetime.now(timezone.utc).isoformat()
    file_content = (
        f"HOPEFX Superadmin Credentials — {now_iso}\n"
        f"{'=' * 60}\n"
        f"Email    : {args.email}\n"
        f"Username : {args.username}\n"
        f"Password : {password}\n"
        f"Role     : superadmin\n"
        f"Action   : {result['action']}\n"
        f"{'=' * 60}\n"
        f"DELETE THIS FILE after saving credentials to a password manager.\n"
    )
    fd = os.open(str(pw_file), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # nosec B106 - intentional credential file, mode 0o600 restricts to owner only
    try:
        os.write(fd, file_content.encode())
    finally:
        os.close(fd)

    # ── Print summary ─────────────────────────────────────────────────────────
    # Credential values are written to sys.stdout directly (not via the logger)
    # so that log-aggregation pipelines never capture plaintext secrets.
    action_label = "CREATED" if result["action"] == "created" else "RESET"

    def _out(line: str = "") -> None:
        sys.stdout.write(line + "\n")

    _out()
    _out("=" * 60)
    _out(f"  SUPERADMIN {action_label} SUCCESSFULLY")
    _out("=" * 60)
    _out(f"  Email    : {args.email}")
    _out(f"  Username : {args.username}")
    if auto_generated:
        # One-time display of auto-generated credential — intentional, goes to
        # stdout only (not the logging system) to avoid log-sink exposure.
        _out(f"  Password : {password}   <- SAVE THIS NOW")
    else:
        _out("  Password : (your supplied value)")
    _out("  Role     : superadmin")
    _out(f"  User ID  : {result['user_id']}")
    _out()
    _out(token_line)
    if token_note:
        _out(token_note)
    _out()
    _out("  Login endpoint : POST /api/auth/login")
    _out('  Body           : {"username": "' + args.username + '", "password": "<password>"}')
    _out("  Swagger UI     : /docs")
    _out("  Superadmin UI  : /api/superadmin/")
    _out()
    _out(f"  Credentials saved to: {pw_file}")
    _out("  WARNING: Delete that file after saving to a password manager.")
    _out("=" * 60)
    _out()


if __name__ == "__main__":
    main()
