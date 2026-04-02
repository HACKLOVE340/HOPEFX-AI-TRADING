#!/usr/bin/env python3
# Copyright (c) 2025-2026
# HOPEFX-AI-TRADING
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
scripts/create_admin.py
=======================
Create or reset an admin user for local / dev use.

Usage
-----
    python scripts/create_admin.py
    python scripts/create_admin.py --email admin@hopefx.io --username admin --password MyPass123!
    python scripts/create_admin.py --reset   # reset password for existing user

The user is created with:
  - role: admin
  - status: active
  - is_email_verified: True   (no email required)

Safe to run multiple times — updates the user if it already exists.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path

# ── Bootstrap path & env ─────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("SECURITY_JWT_SECRET", "dev_secret_for_admin_seed_script_32c")
os.environ.setdefault("DATABASE_URL", "sqlite:///hopefx.db")

# ── Imports ───────────────────────────────────────────────────────────────────
from database.models import Base
from database.user_models import User, UserRole, UserStatus

# Use the same hash_password as AuthService (auth.service uses pbkdf2_sha256 via passlib).
# auth.jwt uses bcrypt — a different scheme. Using the wrong one causes
# "hash could not be identified" at login time.
from auth.service import hash_password
from sqlalchemy import create_engine


def _get_engine():
    db_url = os.environ.get("DATABASE_URL", "sqlite:///hopefx.db")
    connect_args = {"check_same_thread": False} if db_url.startswith("sqlite") else {}
    return create_engine(db_url, connect_args=connect_args)


def create_or_update_admin(email: str, username: str, password: str, reset: bool) -> None:
    engine = _get_engine()
    Base.metadata.create_all(engine)

    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        existing = session.query(User).filter((User.email == email.lower()) | (User.username == username)).first()

        if existing and not reset:
            print(f"\n[INFO] User '{existing.username}' already exists.")
            print("       Use --reset to update the password.\n")
            return

        hashed = hash_password(password)

        if existing:
            existing.hashed_password = hashed
            existing.role = UserRole.ADMIN.value
            existing.status = UserStatus.ACTIVE.value
            existing.is_email_verified = True
            existing.email_verify_token = None
            existing.email_verify_expires = None
            session.commit()
            print(f"\n✅  Password reset for user '{existing.username}'")
        else:
            user = User(
                id=str(uuid.uuid4()),
                email=email.lower().strip(),
                username=username.strip(),
                hashed_password=hashed,
                role=UserRole.ADMIN.value,
                status=UserStatus.ACTIVE.value,
                is_email_verified=True,
                email_verify_token=None,
                email_verify_expires=None,
            )
            session.add(user)
            session.commit()
            print(f"\n✅  Admin user created: '{username}'")

        print("─" * 50)
        print(f"  Email    : {email}")
        print(f"  Username : {username}")
        # Do not echo the password here — it was either supplied by the caller
        # (who already knows it) or printed once by main() before this call.
        print("  Password : (set — use the value shown above or your supplied value)")
        print("  Role     : admin")
        print("  Status   : active (email pre-verified)")
        print("─" * 50)
        print("\n  Login endpoint: POST /api/auth/login")
        print('  Body: {"username": "<email or username>", "password": "<password>"}')
        print("\n  Swagger UI: /docs")
        print("  Dashboard : /app\n")

    finally:
        session.close()


def main():
    parser = argparse.ArgumentParser(description="Create or reset HOPEFX admin user")
    parser.add_argument("--email", default="admin@hopefx.io", help="Admin email")
    parser.add_argument("--username", default="admin", help="Admin username")
    parser.add_argument("--password", default=None, help="Password (auto-generated if omitted)")
    parser.add_argument("--reset", action="store_true", help="Reset password if user exists")
    args = parser.parse_args()

    if args.password is None:
        import secrets
        import stat
        import string

        alphabet = string.ascii_letters + string.digits + "!@#$%"
        args.password = "".join(secrets.choice(alphabet) for _ in range(16))

        # Write the generated password to a chmod-600 restricted local file so
        # it survives terminal scroll. The user is instructed to delete it
        # immediately after saving to a password manager.
        # nosec B106 — intentional clear-text storage: this is a one-time
        # bootstrap credential written to a local file that is immediately
        # chmod-600'd and never committed (admin_password.txt is gitignored).
        pw_file = ROOT / "admin_password.txt"
        pw_file.write_text(  # nosec B106
            f"Admin password (generated {__import__('datetime').datetime.now().isoformat()}):\n"
            f"{args.password}\n"
            "Delete this file after saving the password to a password manager.\n",
            encoding="utf-8",
        )
        try:
            pw_file.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except Exception:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            pass  # chmod may fail on Windows; non-fatal
        print(f"[INFO] Auto-generated password written to: {pw_file}")  # nosec B106
        print("[INFO] Delete that file after saving the password to a password manager.")

    create_or_update_admin(args.email, args.username, args.password, args.reset)


if __name__ == "__main__":
    main()
