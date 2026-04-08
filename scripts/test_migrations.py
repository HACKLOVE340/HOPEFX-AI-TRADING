#!/usr/bin/env python3
# Copyright (c) 2025-2026
# HOPEFX-AI-TRADING
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
scripts/test_migrations.py
===========================
Alembic migration smoke test — runs the full migration chain against a
temporary SQLite database and verifies every revision applies and rolls
back cleanly.

Use this before deploying to production to confirm no migration is broken.

Usage:
    # Against a temporary in-memory SQLite DB (default — safe, no side effects):
    python scripts/test_migrations.py

    # Against a real PostgreSQL DB (staging):
    DATABASE_URL=postgresql://user:pass@host:5432/hopefx_staging \
        python scripts/test_migrations.py

    # Verbose (show each revision):
    python scripts/test_migrations.py --verbose

Exit codes:
    0 — all migrations applied and rolled back cleanly
    1 — one or more migrations failed
"""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
import tempfile
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Load .env if present
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv

    load_dotenv(override=False)
except ImportError:
    ...  # nosec B110

PROJECT_ROOT = Path(__file__).parent.parent
_PASS = "  ✓"  # nosec B105 — status symbol, not a password
_FAIL = "  ✗"


def run(verbose: bool = False) -> int:
    """Run migration smoke test. Returns 0 on success, 1 on failure."""
    failures = 0

    logger.info("\n" + "=" * 60)
    logger.info("  Alembic Migration Smoke Test")
    logger.info("=" * 60)

    # ── Check alembic is installed ────────────────────────────────────────────
    try:
        from alembic.config import Config as AlembicConfig
        from alembic.runtime.migration import MigrationContext  # noqa: F401
        from alembic.script import ScriptDirectory
        from sqlalchemy import create_engine, inspect, text

        from alembic import command as alembic_command

        logger.info(f"{_PASS}  alembic + sqlalchemy importable")
    except ImportError as exc:
        logger.error(f"{_FAIL}  alembic/sqlalchemy not installed: {exc}")
        logger.info("  Install: pip install alembic sqlalchemy")
        return 1

    # ── Resolve database URL ──────────────────────────────────────────────────
    db_url = os.environ.get("DATABASE_URL", "").strip()
    _tmp_file = None

    if not db_url:
        # Use a temporary SQLite file so we can inspect it after migration
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as _tmp:
            _tmp_file = _tmp.name
        db_url = f"sqlite:///{_tmp_file}"
        logger.info(f"  Using temporary SQLite DB: {_tmp_file}")
    else:
        logger.info(f"  Using DATABASE_URL: {db_url[:40]}...")

    # ── Build Alembic config ──────────────────────────────────────────────────
    alembic_ini = PROJECT_ROOT / "alembic.ini"
    if not alembic_ini.exists():
        logger.error(f"{_FAIL}  alembic.ini not found at {alembic_ini}")
        return 1

    cfg = AlembicConfig(str(alembic_ini))
    cfg.set_main_option("sqlalchemy.url", db_url)
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))

    # ── List all revisions ────────────────────────────────────────────────────
    script = ScriptDirectory.from_config(cfg)
    revisions = list(script.walk_revisions())
    revisions.reverse()  # oldest first
    logger.info(f"  Found {len(revisions)} revision(s)")
    if verbose:
        for rev in revisions:
            logger.info(f"    {rev.revision[:8]}  {rev.doc or '(no description)'}")

    if not revisions:
        logger.error(f"{_FAIL}  No revisions found — check alembic/versions/")
        return 1

    # ── Apply all migrations (upgrade head) ───────────────────────────────────
    logger.info("\n  Running: alembic upgrade head ...")
    try:
        alembic_command.upgrade(cfg, "head")
        logger.info(f"{_PASS}  upgrade head completed")
    except Exception as exc:
        logger.error(f"{_FAIL}  upgrade head failed: {exc}")
        failures += 1

    if failures == 0:
        # ── Verify tables exist ───────────────────────────────────────────────
        try:
            engine = create_engine(db_url)
            inspector = inspect(engine)
            tables = inspector.get_table_names()
            logger.info(f"{_PASS}  Tables created: {sorted(tables)}")

            # alembic_version table must exist
            if "alembic_version" not in tables:
                logger.error(f"{_FAIL}  alembic_version table missing")
                failures += 1
            else:
                with engine.connect() as conn:
                    row = conn.execute(text("SELECT version_num FROM alembic_version")).fetchone()
                    current = row[0] if row else None
                head_rev = script.get_current_head()
                if current == head_rev:
                    logger.info(f"{_PASS}  DB at head revision: {current}")
                else:
                    logger.error(f"{_FAIL}  DB at {current!r}, expected head {head_rev!r}")
                    failures += 1
            engine.dispose()
        except Exception as exc:
            logger.error(f"{_FAIL}  Post-migration inspection failed: {exc}")
            failures += 1

        # ── Downgrade back to base ────────────────────────────────────────────
        logger.info("\n  Running: alembic downgrade base ...")
        try:
            alembic_command.downgrade(cfg, "base")
            logger.info(f"{_PASS}  downgrade base completed")
        except Exception as exc:
            logger.error(f"{_FAIL}  downgrade base failed: {exc}")
            failures += 1

        # ── Re-upgrade to confirm round-trip ─────────────────────────────────
        logger.info("\n  Running: alembic upgrade head (round-trip) ...")
        try:
            alembic_command.upgrade(cfg, "head")
            logger.info(f"{_PASS}  round-trip upgrade head completed")
        except Exception as exc:
            logger.error(f"{_FAIL}  round-trip upgrade failed: {exc}")
            failures += 1

    # ── Cleanup ───────────────────────────────────────────────────────────────
    if _tmp_file:
        with contextlib.suppress(OSError):
            os.unlink(_tmp_file)

    logger.info("\n" + "=" * 60)
    if failures == 0:
        logger.info("  ALL MIGRATION CHECKS PASSED")
    else:
        logger.error(f"  {failures} CHECK(S) FAILED — review output above")
    logger.info("=" * 60 + "\n")

    return 0 if failures == 0 else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Alembic migration smoke test")
    parser.add_argument("--verbose", "-v", action="store_true", help="List each revision before running")
    args = parser.parse_args()
    sys.exit(run(verbose=args.verbose))


if __name__ == "__main__":
    main()
