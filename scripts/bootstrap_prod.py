# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
scripts/bootstrap_prod.py
=========================
Production-only superadmin seed.

Reads credentials from environment variables set by deploy.sh:
    BOOTSTRAP_SUPERADMIN_EMAIL     — superadmin email address
    BOOTSTRAP_SUPERADMIN_PASSWORD  — initial password (change after first login)

Behaviour:
- If the superadmin already exists, exits cleanly (idempotent).
- Never creates dev placeholder accounts (admin@hopefx.io, trader@hopefx.io).
- Fails loudly if required env vars are missing.
- Intended to be run once immediately after first deployment.

Usage:
    docker compose exec app python3 scripts/bootstrap_prod.py
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# Make project root importable
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    email = os.getenv("BOOTSTRAP_SUPERADMIN_EMAIL", "").strip()
    password = os.getenv("BOOTSTRAP_SUPERADMIN_PASSWORD", "").strip()

    if not email:
        logger.error("BOOTSTRAP_SUPERADMIN_EMAIL is not set. Set it in .env before running this script.")
        sys.exit(1)

    if not password:
        logger.error("BOOTSTRAP_SUPERADMIN_PASSWORD is not set. Set it in .env before running this script.")
        sys.exit(1)

    if len(password) < 12:
        logger.error(
            "BOOTSTRAP_SUPERADMIN_PASSWORD is too short (%d chars). Use at least 12 characters.",
            len(password),
        )
        sys.exit(1)

    # Derive username from email local part
    username = email.split("@")[0].lower().replace(".", "_").replace("+", "_")

    try:
        from auth.service import AuthService
        from database.connection import SessionLocal
        from database.user_models import User, UserStatus

        svc = AuthService(session_factory=SessionLocal)

        # Check if superadmin already exists
        existing = svc.get_user_by_email(email)
        if existing is not None:
            logger.info("Superadmin already exists: %s — skipping seed.", email)
            return

        # register() returns (success, message, email_verify_token). The third
        # value is a TOKEN, not a user id — see its docstring. This script
        # unpacked it as `user_id` and then looked the account up with
        # `filter_by(id=user_id)`, which matched nothing, so `if user:` was
        # always False and the verification flag was never set. The script
        # reported "Superadmin seeded successfully" regardless.
        #
        # In production that is fatal: REQUIRE_EMAIL_VERIFICATION defaults to
        # true when APP_ENV=production, so register() creates the account
        # PENDING_VERIFICATION, and login rejects it with "Please verify your
        # email before logging in." No verification email is sent during
        # deployment bootstrap, so there was no way through. Every fresh
        # production install produced a superadmin nobody could log in as.
        ok, msg, _verify_token = svc.register(
            email=email,
            username=username,
            password=password,
            role="superadmin",
        )

        if not ok:
            logger.error("Superadmin registration failed: %s", msg)
            sys.exit(1)

        # Look the account up by the identifier we actually have. Both fields
        # matter: login() checks is_email_verified AND status == ACTIVE, and
        # register() sets status to PENDING_VERIFICATION when verification is
        # required.
        with svc._sf() as session:
            user = session.query(User).filter_by(email=email).first()
            if user is None:
                logger.error(
                    "Registered %s but could not read it back — the account is not usable. "
                    "This should be impossible; do not treat the deployment as seeded.",
                    email,
                )
                sys.exit(1)
            user.is_email_verified = True
            user.status = UserStatus.ACTIVE.value
            session.commit()

        # Confirm the outcome rather than the action. The bug above survived
        # because the script verified that it had *run* the fix-up, not that the
        # fix-up had *worked*.
        check = svc.get_user_by_email(email)
        if check is None or not check.is_email_verified or check.status != UserStatus.ACTIVE.value:
            logger.error(
                "Superadmin %s cannot log in after seeding (verified=%s status=%s). Not reporting success.",
                email,
                getattr(check, "is_email_verified", None),
                getattr(check, "status", None),
            )
            sys.exit(1)

        logger.info("──────────────────────────────────────────────")
        logger.info("  Superadmin seeded successfully")
        logger.info("  Email    : %s", email)
        logger.info("  Username : %s", username)
        logger.info("  Role     : superadmin")
        logger.info("  ⚠  Change this password after first login!")
        logger.info("──────────────────────────────────────────────")

    except Exception as exc:
        logger.error("Superadmin seed failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
