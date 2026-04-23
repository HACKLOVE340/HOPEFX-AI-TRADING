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
        from database.user_models import User

        svc = AuthService()

        # Check if superadmin already exists
        existing = svc.get_user_by_email(email)
        if existing is not None:
            logger.info("Superadmin already exists: %s — skipping seed.", email)
            return

        # Register the superadmin account
        ok, msg, user_id = svc.register(
            email=email,
            username=username,
            password=password,
            role="superadmin",
        )

        if not ok:
            logger.error("Superadmin registration failed: %s", msg)
            sys.exit(1)

        # Mark email as verified immediately — no verification email needed for
        # the initial superadmin created during deployment.
        with svc._sf() as session:
            user = session.query(User).filter_by(id=user_id).first()
            if user:
                user.is_email_verified = True
                session.commit()

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
