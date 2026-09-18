# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
database/backup.py
==================
Database backup utilities.

Supports PostgreSQL (pg_dump) and SQLite (the online backup API).

SQLite backups previously copied the database file directly. That is unsafe here:
`database/connection.py` sets ``PRAGMA journal_mode=WAL``, so committed rows live
in the ``-wal`` sidecar until a checkpoint, and a file copy leaves them behind.
Reproduced before the fix — a database with one committed row produced a copy
where the table did not exist, while this module logged success. It now uses
:meth:`sqlite3.Connection.backup`, which is transactionally consistent and
includes WAL content. Restore and verification live in :mod:`database.restore`.
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
import sqlite3
import subprocess  # nosec B404 — used only for pg_dump with a fixed arg list, no shell=True
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_BACKUP_DIR = Path(os.getenv("BACKUP_DIR", "./backups"))
_BACKUP_KEEP = int(os.getenv("BACKUP_KEEP", "7"))


def _timestamp() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


#: Both extensions are rotated. SQLite artefacts were named `.sql.gz` while
#: containing a binary database; they are now `.db.gz`. Globbing only the new
#: name would silently stop rotating every backup already on disk, and the first
#: symptom of that is a full volume.
_BACKUP_SUFFIXES: tuple[str, ...] = (".sql.gz", ".db.gz")


def _rotate(backup_dir: Path, prefix: str, keep: int) -> None:
    """Remove oldest backups beyond the retention limit."""
    candidates = [p for suffix in _BACKUP_SUFFIXES for p in backup_dir.glob(f"{prefix}_*{suffix}")]
    files = sorted(candidates, key=lambda p: p.stat().st_mtime)
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
    # Streamed, not captured. `capture_output=True` buffers the entire dump in
    # memory before a byte is written, so a production-sized database would
    # exhaust the worker rather than back itself up — and the failure would
    # arrive during an incident, which is the worst possible time to discover it.
    try:
        with gzip.open(out_path, "wb") as gz:
            proc = subprocess.Popen(  # nosec B603 — fixed arg list from env, no shell
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
            assert proc.stdout is not None  # nosec B101 — guaranteed by stdout=PIPE
            while chunk := proc.stdout.read(1024 * 1024):
                gz.write(chunk)
            stderr = proc.stderr.read() if proc.stderr else b""
            returncode = proc.wait()
        if returncode != 0:
            out_path.unlink(missing_ok=True)
            raise RuntimeError(f"pg_dump failed (exit {returncode}): {stderr.decode(errors='replace')[:500]}")
    except OSError as exc:
        out_path.unlink(missing_ok=True)
        raise RuntimeError(f"pg_dump could not be run: {exc}") from exc

    logger.info("pg_dump complete: %s (%.1f KB)", out_path.name, out_path.stat().st_size / 1024)
    _rotate(backup_dir, safe_name, _BACKUP_KEEP)
    return out_path


def _backup_sqlite(database_url: str, backup_dir: Path) -> Path:
    """Snapshot the SQLite database consistently, then gzip it.

    Uses :meth:`sqlite3.Connection.backup` rather than copying the file. Under
    WAL — which this project enables — a file copy loses every committed row that
    has not been checkpointed, and produces an artefact that restores to an empty
    database without any error along the way.
    """
    # Strip driver prefix: sqlite:///./hopefx.db → ./hopefx.db
    path_str = re.sub(r"^sqlite(\+\w+)?:///", "", database_url)
    src = Path(path_str)
    if not src.exists():
        raise FileNotFoundError(f"SQLite database not found: {src}")

    safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", src.stem)
    # `.db.gz`, not `.sql.gz`: the artefact is a binary database, and the old
    # name told every reader it was SQL text.
    out_path = backup_dir / f"{safe_name}_{_timestamp()}.db.gz"

    logger.info("Backing up SQLite '%s' → %s", src, out_path.name)
    with tempfile.TemporaryDirectory(prefix="hopefx-backup-") as tmp:
        snapshot = Path(tmp) / "snapshot.db"
        source = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
        try:
            destination = sqlite3.connect(snapshot)
            try:
                source.backup(destination)
            finally:
                destination.close()
        finally:
            source.close()

        with open(snapshot, "rb") as f_in, gzip.open(out_path, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)

    logger.info("SQLite backup complete: %s (%.1f KB)", out_path.name, out_path.stat().st_size / 1024)
    _rotate(backup_dir, safe_name, _BACKUP_KEEP)
    return out_path


def run_backup(database_url: str | None = None, backup_dir: Path | None = None) -> Path:
    """
    Perform a database backup and return the path to the backup file.

    Reads DATABASE_URL from the environment if not supplied, and writes to
    ``BACKUP_DIR`` unless ``backup_dir`` is given. The explicit destination
    exists so the round trip can be exercised against a real database in a
    temporary directory — a backup nobody has restored is not a backup.

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

    destination = Path(backup_dir) if backup_dir is not None else _BACKUP_DIR
    destination.mkdir(parents=True, exist_ok=True)

    scheme = urlparse(database_url).scheme.split("+")[0]
    if scheme in ("postgresql", "postgres"):
        return _backup_postgres(database_url, destination)
    elif scheme == "sqlite":
        return _backup_sqlite(database_url, destination)
    else:
        raise ValueError(
            f"Unsupported database scheme '{scheme}'. Only postgresql and sqlite are supported for backup."
        )
