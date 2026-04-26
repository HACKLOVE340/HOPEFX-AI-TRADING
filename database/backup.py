# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
database/backup.py
==================
Database backup utilities.

Supports PostgreSQL (pg_dump) and SQLite (.db file copy).
Backup files are written to BACKUP_DIR (default: ./backups/) with a
timestamp suffix and optionally compressed with gzip.

Environment variables:
  DATABASE_URL   — connection string (read from connection module)
  BACKUP_DIR     — destination directory (default: ./backups)
  BACKUP_KEEP    — number of backups to retain per database (default: 7)
"""

from __future__ import annotations

import gzip
import logging
import os
import re
import shutil
import subprocess  # nosec B404 — used only for pg_dump with a fixed arg list, no shell=True
import time
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_BACKUP_DIR = Path(os.getenv("BACKUP_DIR", "./backups"))
_BACKUP_KEEP = int(os.getenv("BACKUP_KEEP", "7"))


def _timestamp() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def _rotate(backup_dir: Path, prefix: str, keep: int) -> None:
    """Remove oldest backups beyond the retention limit."""
    files = sorted(backup_dir.glob(f"{prefix}_*.sql.gz"), key=lambda p: p.stat().st_mtime)
    for old in files[:-keep] if keep > 0 else []:
        try:
            old.unlink()
            logger.info("Removed old backup: %s", old.name)
        except OSError as exc:
            logger.warning("Could not remove old backup %s: %s", old.name, exc)


def _backup_postgres(database_url: str, backup_dir: Path) -> Path:
    """Run pg_dump and gzip the output."""
    parsed = urlparse(database_url)
    dbname = parsed.path.lstrip("/") or "hopefx"
    # Strip driver suffix (e.g. postgresql+psycopg2 → postgresql)
    scheme = parsed.scheme.split("+")[0]
    if scheme not in ("postgresql", "postgres"):
        raise ValueError(f"Unsupported scheme for pg_dump: {scheme}")

    safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", dbname)
    out_path = backup_dir / f"{safe_name}_{_timestamp()}.sql.gz"

    env = os.environ.copy()
    if parsed.password:
        env["PGPASSWORD"] = parsed.password

    cmd = ["pg_dump", "--no-password", "--format=plain"]
    if parsed.hostname:
        cmd += ["-h", parsed.hostname]
    if parsed.port:
        cmd += ["-p", str(parsed.port)]
    if parsed.username:
        cmd += ["-U", parsed.username]
    cmd.append(dbname)

    logger.info("Starting pg_dump for database '%s' → %s", dbname, out_path.name)
    with gzip.open(out_path, "wb") as gz:
        result = subprocess.run(  # nosec B603 — args are constructed from env, not user input
            cmd,
            capture_output=True,
            env=env,
            check=False,
        )
        if result.returncode != 0:
            out_path.unlink(missing_ok=True)
            raise RuntimeError(
                f"pg_dump failed (exit {result.returncode}): {result.stderr.decode(errors='replace')[:500]}"
            )
        gz.write(result.stdout)

    logger.info("pg_dump complete: %s (%.1f KB)", out_path.name, out_path.stat().st_size / 1024)
    _rotate(backup_dir, safe_name, _BACKUP_KEEP)
    return out_path


def _backup_sqlite(database_url: str, backup_dir: Path) -> Path:
    """Copy the SQLite file and gzip it."""
    # Strip driver prefix: sqlite:///./hopefx.db → ./hopefx.db
    path_str = re.sub(r"^sqlite(\+\w+)?:///", "", database_url)
    src = Path(path_str)
    if not src.exists():
        raise FileNotFoundError(f"SQLite database not found: {src}")

    safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", src.stem)
    out_path = backup_dir / f"{safe_name}_{_timestamp()}.sql.gz"

    logger.info("Backing up SQLite '%s' → %s", src, out_path.name)
    with open(src, "rb") as f_in, gzip.open(out_path, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)

    logger.info("SQLite backup complete: %s (%.1f KB)", out_path.name, out_path.stat().st_size / 1024)
    _rotate(backup_dir, safe_name, _BACKUP_KEEP)
    return out_path


def run_backup(database_url: str | None = None) -> Path:
    """
    Perform a database backup and return the path to the backup file.

    Reads DATABASE_URL from the environment if not supplied.
    Raises RuntimeError if the backup fails.
    """
    if database_url is None:
        # Try to read from the connection module first (respects fallback logic)
        try:
            from database.connection import _db_manager  # type: ignore[attr-defined]

            database_url = str(_db_manager.url) if _db_manager else None
        except Exception as _exc:  # nosec B110 — falls back to DATABASE_URL env var below
            logger.debug("backup: could not read db_manager URL: %s", _exc)

    if not database_url:
        database_url = os.getenv("DATABASE_URL", "")

    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is not set — cannot perform backup. Set DATABASE_URL=postgresql://user:pass@host:5432/dbname"
        )

    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    scheme = urlparse(database_url).scheme.split("+")[0]
    if scheme in ("postgresql", "postgres"):
        return _backup_postgres(database_url, _BACKUP_DIR)
    elif scheme == "sqlite":
        return _backup_sqlite(database_url, _BACKUP_DIR)
    else:
        raise ValueError(
            f"Unsupported database scheme '{scheme}'. Only postgresql and sqlite are supported for backup."
        )
