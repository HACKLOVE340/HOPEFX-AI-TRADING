# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
database_init.py
================
Thin entry-point for database initialisation.

All real logic lives in the ``database/`` package:
  - database.connection  — connection pooling, retries, health checks
  - database.models      — SQLAlchemy ORM models (Configuration, AuditLog, …)
  - database.user_models — User, Session, APIKey models

This module provides:
  - initialize_database(db_url)  — create tables + run Alembic migrations
  - validate_schema(engine)      — assert all expected tables are present
  - recover_database(file_path)  — attempt SQLite WAL recovery or pg_dump restore
"""

from __future__ import annotations

import contextlib
import logging
import os
from pathlib import Path
from typing import ClassVar

logger = logging.getLogger(__name__)


def initialize_database(db_url: str | None = None) -> None:
    """Create all ORM tables and run pending Alembic migrations.

    Args:
        db_url: SQLAlchemy connection URL.  Defaults to the DATABASE_URL
                environment variable, then ``sqlite:///trading.db``.
    """
    if db_url is None:
        db_url = os.getenv("DATABASE_URL", "sqlite:///trading.db")

    from sqlalchemy import create_engine

    engine = create_engine(db_url)

    # Create tables defined in both model modules.
    try:
        from database.models import Base as CoreBase

        CoreBase.metadata.create_all(engine)
        logger.info("Core tables created/verified")
    except Exception as exc:
        logger.warning("Could not create core tables: %s", exc)

    try:
        from database.user_models import Base as UserBase

        UserBase.metadata.create_all(engine)
        logger.info("User tables created/verified")
    except Exception as exc:
        logger.warning("Could not create user tables: %s", exc)

    # Run Alembic migrations if alembic.ini is present.
    alembic_ini = os.path.join(Path(__file__).parent, "alembic.ini")
    if Path(alembic_ini).exists():
        try:
            from alembic.config import Config  # pylint: disable=no-name-in-module

            from alembic import command  # pylint: disable=no-name-in-module

            alembic_cfg = Config(alembic_ini)
            with engine.begin() as connection:
                alembic_cfg.attributes["connection"] = connection
                command.upgrade(alembic_cfg, "head")
            logger.info("Alembic migrations applied")
        except Exception as exc:
            logger.warning("Alembic migration failed (non-fatal in dev): %s", exc)
    else:
        logger.debug("alembic.ini not found — skipping migrations")

    engine.dispose()
    logger.info("Database initialised: %s", db_url.split("@")[-1])  # hide credentials


def validate_schema(engine) -> dict[str, list[str]]:
    """Verify that all expected tables exist in the database.

    Returns a dict with keys ``present`` and ``missing``.
    Raises ``RuntimeError`` if any required tables are absent.
    """
    from sqlalchemy import inspect as sa_inspect

    inspector = sa_inspect(engine)
    existing = set(inspector.get_table_names())

    required: ClassVar[set[str]] = set()
    for base_path in ("database.models", "database.user_models"):
        try:
            import importlib

            mod = importlib.import_module(base_path)
            base = getattr(mod, "Base", None)
            if base is not None:
                required.update(base.metadata.tables.keys())
        except Exception as exc:
            logger.debug("Could not inspect %s: %s", base_path, exc)

    present = sorted(required & existing)
    missing = sorted(required - existing)

    if missing:
        raise RuntimeError(
            f"Schema validation failed — missing tables: {missing}. "
            "Run initialize_database() or apply Alembic migrations."
        )

    logger.info("Schema validation passed: %d tables present", len(present))
    return {"present": present, "missing": missing}


def recover_database(file_path: str) -> bool:
    """Attempt to recover a corrupted SQLite database or restore from a dump.

    For SQLite: uses the ``.dump`` pragma to export and re-import data,
    which recovers from WAL corruption.

    For PostgreSQL dump files (.sql / .dump): delegates to ``psql`` /
    ``pg_restore`` via subprocess.

    Returns True on success, False on failure.
    """
    import pathlib
    import subprocess  # nosec B404 - controlled invocation for DB recovery only

    path = pathlib.Path(file_path)
    if not path.exists():
        logger.error("recover_database: file not found: %s", file_path)
        return False

    suffix = path.suffix.lower()

    # ── SQLite recovery via .dump pragma ──────────────────────────────────────
    if suffix in (".db", ".sqlite", ".sqlite3"):
        recovered = path.with_suffix(".recovered.db")
        try:
            import sqlite3

            src = sqlite3.connect(str(path))
            dst = sqlite3.connect(str(recovered))
            for line in src.iterdump():
                with contextlib.suppress(sqlite3.Error):
                    # skip rows that fail (e.g. constraint violations in corrupt data)
                    dst.execute(line)
            dst.commit()
            src.close()
            dst.close()
            logger.info("SQLite recovery complete: %s → %s", path, recovered)
            return True
        except Exception as exc:
            logger.error("SQLite recovery failed: %s", exc)
            return False

    # ── PostgreSQL plain-SQL dump (.sql) ──────────────────────────────────────
    if suffix == ".sql":
        db_url = os.getenv("DATABASE_URL", "")
        if not db_url.startswith("postgresql"):
            logger.error("recover_database: .sql restore requires DATABASE_URL=postgresql://...")
            return False
        try:
            result = subprocess.run(  # nosec B603 B607 - controlled args, no user input
                ["psql", db_url, "-f", str(path)],
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
            if result.returncode != 0:
                logger.error("psql restore failed: %s", result.stderr[:500])
                return False
            logger.info("PostgreSQL SQL restore complete from %s", path)
            return True
        except Exception as exc:
            logger.error("PostgreSQL restore failed: %s", exc)
            return False

    # ── PostgreSQL custom-format dump (.dump) ─────────────────────────────────
    if suffix == ".dump":
        db_url = os.getenv("DATABASE_URL", "")
        if not db_url.startswith("postgresql"):
            logger.error("recover_database: .dump restore requires DATABASE_URL=postgresql://...")
            return False
        try:
            result = subprocess.run(  # nosec B603 B607 - controlled args, no user input
                ["pg_restore", "--clean", "--if-exists", "-d", db_url, str(path)],
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
            if result.returncode != 0:
                logger.error("pg_restore failed: %s", result.stderr[:500])
                return False
            logger.info("PostgreSQL custom restore complete from %s", path)
            return True
        except Exception as exc:
            logger.error("pg_restore failed: %s", exc)
            return False

    logger.error("recover_database: unsupported file type '%s'", suffix)
    return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    db_url = os.getenv("DATABASE_URL", "sqlite:///trading.db")
    initialize_database(db_url)
