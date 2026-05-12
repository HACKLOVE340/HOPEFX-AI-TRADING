"""
scripts/fix_db.py
=================
Checks the local SQLite database for missing columns and fixes them.
If the database is too broken to fix, backs it up and recreates it.

Called by start.bat before the server starts.
Safe to run repeatedly — idempotent.
"""

from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# Load .env so DATABASE_URL is available
try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
except ImportError:
    pass

DB_URL = os.environ.get("DATABASE_URL", f"sqlite:///{ROOT / 'hopefx.db'}")

# Only handle SQLite — Postgres manages its own schema
if not DB_URL.startswith("sqlite"):
    print(f"[fix_db] Non-SQLite DB ({DB_URL[:30]}...) — skipping column check")
    sys.exit(0)

# Extract file path from URL
db_path_str = DB_URL.replace("sqlite:///", "").replace("sqlite+aiosqlite:///", "")
db_path = Path(db_path_str)
if not db_path.is_absolute():
    db_path = ROOT / db_path_str

if not db_path.exists():
    print("[fix_db] No database file found — will be created on first startup")
    sys.exit(0)

import sqlite3

conn = sqlite3.connect(str(db_path))

# Required columns per table — derived from database/models.py ORM definitions
REQUIRED = {
    "users": [
        "id",
        "email",
        "username",
        "hashed_password",
        "role",
        "status",
        "is_email_verified",
        "email_verify_token",
        "email_verify_expires",
        "password_reset_token",
        "password_reset_expires",
        "totp_secret",
        "totp_enabled",
        "kyc_status",
        "kyc_submitted_at",
        "kyc_reviewed_at",
        "kyc_reviewer_id",
        "kyc_rejection_reason",
        "kyc_document_type",
        "plan",
        "country",
        "created_at",
        "updated_at",
        "last_login_at",
        "last_login_ip",
        # Extended user profile fields
        "is_banned",
        "ban_reason",
        "ban_expires_at",
        "failed_login_attempts",
        "locked_until",
        "stripe_customer_id",
        "referral_code",
        "affiliate_id",
        "phone",
        "full_name",
        "avatar_url",
    ],
    "user_sessions": [
        "id",
        "user_id",
        "refresh_token_hash",
        "device_info",
        "ip_address",
        "created_at",
        "expires_at",
        "revoked_at",
        "is_revoked",
        "last_active_at",
        "location",
    ],
    "login_attempts": [
        "id",
        "user_id",
        "email",
        "ip_address",
        "success",
        "failure_reason",
        "attempted_at",
    ],
    "trades": [
        "id",
        "trade_id",
        "symbol",
        "side",
        "entry_time",
        "entry_price",
        "entry_quantity",
        "exit_time",
        "exit_price",
        "exit_quantity",
        "realized_pnl",
        "unrealized_pnl",
        "commission",
        "swap",
        "total_pnl",
        "stop_loss",
        "take_profit",
        "risk_reward_ratio",
        "strategy",
        "signal_source",
        "signal_strength",
        "status",
        "is_open",
        "created_at",
        "updated_at",
        "notes",
        "client_order_id",
        "user_id",
        "account_id",
    ],
    "orders": [
        "id",
        "account_id",
        "user_id",
    ],
    "positions": [
        "id",
        "account_id",
    ],
}

# Column definitions for ADD COLUMN statements
COL_DEFS = {
    # users — core
    "kyc_submitted_at": "DATETIME",
    "kyc_reviewed_at": "DATETIME",
    "kyc_reviewer_id": "VARCHAR(100)",
    "kyc_rejection_reason": "TEXT",
    "kyc_document_type": "VARCHAR(50)",
    "plan": "VARCHAR(30) NOT NULL DEFAULT 'free'",
    "country": "VARCHAR(2)",
    "last_login_at": "DATETIME",
    "last_login_ip": "VARCHAR(45)",
    "totp_secret": "VARCHAR(64)",
    "totp_enabled": "BOOLEAN DEFAULT 0",
    "kyc_status": "VARCHAR(20) DEFAULT 'unverified'",
    "is_email_verified": "BOOLEAN NOT NULL DEFAULT 0",
    "email_verify_token": "VARCHAR(255)",
    "email_verify_expires": "DATETIME",
    "password_reset_token": "VARCHAR(255)",
    "password_reset_expires": "DATETIME",
    "updated_at": "DATETIME",
    # users — extended
    "is_banned": "BOOLEAN DEFAULT 0",
    "ban_reason": "TEXT",
    "ban_expires_at": "DATETIME",
    "failed_login_attempts": "INTEGER DEFAULT 0",
    "locked_until": "DATETIME",
    "stripe_customer_id": "VARCHAR(100)",
    "referral_code": "VARCHAR(50)",
    "affiliate_id": "VARCHAR(100)",
    "phone": "VARCHAR(30)",
    "full_name": "VARCHAR(200)",
    "avatar_url": "TEXT",
    # user_sessions
    "device_info": "VARCHAR(255)",
    "revoked_at": "DATETIME",
    "is_revoked": "BOOLEAN DEFAULT 0",
    "last_active_at": "DATETIME",
    "location": "TEXT",
    # login_attempts
    "failure_reason": "VARCHAR(100)",
    # trades / orders / positions
    "account_id": "INTEGER",
    "user_id": "VARCHAR(100)",
}

fixed = []
unfixable = []

for table, required_cols in REQUIRED.items():
    # Check table exists
    exists = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    if not exists:
        print(f"[fix_db] Table '{table}' missing — will be created at startup")
        continue

    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    missing = [c for c in required_cols if c not in existing]

    for col in missing:
        col_def = COL_DEFS.get(col, "TEXT")
        try:
            conn.execute(f'ALTER TABLE "{table}" ADD COLUMN "{col}" {col_def}')
            conn.commit()
            fixed.append(f"{table}.{col}")
            print(f"[fix_db] Added missing column: {table}.{col}")
        except Exception as e:
            unfixable.append(f"{table}.{col}: {e}")
            print(f"[fix_db] Could not add {table}.{col}: {e}")

conn.close()

if fixed:
    print(f"[fix_db] Fixed {len(fixed)} missing column(s): {', '.join(fixed)}")

if unfixable:
    # Back up and delete the DB so it gets recreated clean
    backup = db_path.with_suffix(f".backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
    print(f"[fix_db] Could not fix all columns. Backing up to {backup.name} and recreating DB.")
    shutil.copy2(str(db_path), str(backup))
    db_path.unlink()
    print(f"[fix_db] Old DB backed up to {backup.name} — will be recreated clean on startup")
    sys.exit(0)

print("[fix_db] Database OK")
sys.exit(0)
