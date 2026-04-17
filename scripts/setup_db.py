#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
scripts/setup_db.py
=====================
One-command database setup for HOPEFX.

Handles both environments:
  Development  — SQLite (no server required, instant setup)
  Production   — PostgreSQL (set DATABASE_URL in .env)

What it does
------------
1. Detects DATABASE_URL from .env
2. Uses the existing database specified by DATABASE_URL (PostgreSQL or SQLite)
3. Runs all Alembic migrations to bring schema to HEAD
4. Verifies all expected tables exist
5. Pings Redis and reports status
6. Prints a summary

Usage
-----
    python scripts/setup_db.py           # uses DATABASE_URL from .env
    python scripts/setup_db.py --check   # check only, no migrations
"""

from __future__ import annotations

import argparse
import os
import subprocess  # nosec B404
import sys
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
except ImportError:  # nosec B110 — dotenv is optional; env vars may already be set
    pass

OK = "✅"
WARN = "⚠️ "
FAIL = "❌"

EXPECTED_TABLES = {
    "users",
    "user_sessions",
    "login_attempts",
    "orders",
    "trades",
    "positions",
    "accounts",
    "signals",
    "predictions",
    "market_data",
    "audit_log",
    "system_events",
    "outbox_events",
    "tick_data",
    "order_book_snapshots",
    "account_snapshots",
    "performance_metrics",
    "watchlists",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="HOPEFX database setup")
    p.add_argument("--check", action="store_true", help="Check only — do not run migrations")
    return p.parse_args()


def get_sync_db_url() -> str:
    """Return sync DB URL (strip async driver prefix for Alembic/sqlite3)."""
    url = os.getenv("DATABASE_URL", "sqlite:///./hopefx.db")
    return url.replace("sqlite+aiosqlite:///", "sqlite:///").replace("postgresql+asyncpg://", "postgresql://")


def run_migrations() -> bool:
    """Run alembic upgrade head. Returns True on success."""
    logger.info(f"\n{OK}  Running Alembic migrations...")
    result = subprocess.run(  # nosec B603 — fixed args, no shell, no user input
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env={**os.environ, "DATABASE_URL": get_sync_db_url()},
        check=False,
    )
    if result.returncode != 0:
        logger.error(f"{FAIL}  Migration failed:\n{result.stderr}")
        return False
    for line in result.stdout.splitlines() + result.stderr.splitlines():
        if "Running upgrade" in line or "Context impl" in line:
            logger.info(f"       {line.strip()}")
    logger.info(f"{OK}  Migrations complete")
    return True


def verify_tables(db_url: str) -> tuple[set[str], set[str]]:
    """Return (found_tables, missing_tables)."""
    found: set[str] = set()

    if db_url.startswith("sqlite"):
        import sqlite3

        db_path = db_url.replace("sqlite:///", "").replace("./", "")
        if not Path(db_path).exists():
            return set(), EXPECTED_TABLES
        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        conn.close()
        found = {r[0] for r in rows}
    else:
        try:
            import psycopg2  # type: ignore

            conn = psycopg2.connect(db_url)
            cur = conn.cursor()
            cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
            found = {r[0] for r in cur.fetchall()}
            conn.close()
        except ImportError:
            logger.warning(f"{WARN}  psycopg2 not installed — cannot verify PostgreSQL tables")
            return set(), set()
        except Exception as exc:
            logger.error(f"{FAIL}  PostgreSQL connection failed: {exc}")
            return set(), EXPECTED_TABLES

    missing = EXPECTED_TABLES - found
    return found, missing


def check_redis() -> bool:
    """Ping Redis. Returns True if available."""
    try:
        import redis

        r = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
        r.ping()
        return True
    except Exception:
        return False


def main() -> int:
    args = parse_args()
    db_url = get_sync_db_url()
    is_sqlite = db_url.startswith("sqlite")

    logger.info("\n=== HOPEFX Database Setup ===")
    logger.info(f"  Database : {'SQLite (dev)' if is_sqlite else 'PostgreSQL (production)'}")
    logger.info(f"  URL      : {db_url[:60]}{'...' if len(db_url) > 60 else ''}")

    # ── Migrations ────────────────────────────────────────────────────────────
    if not args.check:
        ok = run_migrations()
        if not ok:
            return 1
    else:
        logger.warning(f"\n{WARN}  --check mode: skipping migrations")

    # ── Verify tables ─────────────────────────────────────────────────────────
    logger.info("\n=== Table verification ===")
    found, missing = verify_tables(db_url)

    if found:
        logger.info(f"  {OK}  {len(found)} tables present")
    if missing:
        logger.error(f"  {FAIL}  {len(missing)} expected tables missing: {', '.join(sorted(missing))}")
        if not args.check:
            logger.info("       Re-run without --check to apply migrations")
    else:
        logger.info(f"  {OK}  All {len(EXPECTED_TABLES)} expected tables verified")

    # ── Redis ─────────────────────────────────────────────────────────────────
    logger.info("\n=== Redis ===")
    if check_redis():
        logger.info(f"  {OK}  Redis connected — {os.getenv('REDIS_URL', 'redis://localhost:6379/0')}")
    else:
        logger.warning(f"  {WARN}  Redis not reachable — start with: redis-server")
        logger.info("       Paper trading will work without Redis but caching is disabled")

    # ── Summary ───────────────────────────────────────────────────────────────
    logger.info("\n=== Summary ===")
    if not missing:
        logger.info(f"  {OK}  Database ready for paper trading")
        if is_sqlite:
            logger.warning(f"  {WARN}  Using SQLite — switch to PostgreSQL for production")
            logger.info("       Set DATABASE_URL=postgresql+asyncpg://... in .env")
    else:
        logger.error(f"  {FAIL}  Database setup incomplete — {len(missing)} tables missing")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
