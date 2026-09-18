# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
database/restore.py
===================
Restore a database from a backup written by :mod:`database.backup` — and, before
that, decide whether the backup is worth restoring at all.

    python -m database.restore --verify backups/hopefx_20260908T000000Z.sql.gz
    python -m database.restore backups/hopefx_...db.gz --target ./recovered.db

## Why this module exists

`database.backup` has been scheduled every 24 hours by
`celery_app.database_backup` with no way to restore what it wrote and no test of
either half. Group 2 ranks that first among all outstanding gaps: it is the only
one whose worst case is unrecoverable.

Two defects were found by running the old code rather than reading it, and both
are the reason this module verifies rather than trusts:

* **A WAL database backed up by file copy restores to nothing.**
  `database/connection.py` sets `PRAGMA journal_mode=WAL`, so committed rows sit
  in the `-wal` sidecar until a checkpoint. Copying the main file alone yielded a
  database where the table did not exist — while the job logged success.
* **The artefact's name lied about its format.** The SQLite path wrote a binary
  database under a `*.sql.gz` name.

Hence two rules here, both load-bearing:

1. **Format is read from the content, never the filename.** The filename has
   already been wrong in production-shaped output.
2. **Structural validity is not evidence of content.** A backup that opens
   cleanly and contains no tables is refused, because that is exactly what the
   WAL defect produced and exactly what a restore would happily "succeed" on.

## Fail closed

Every ambiguity refuses. `RestoreRefused` is raised for a missing, empty,
non-gzip, truncated, unrecognised, or empty-of-content artefact, and for a target
that already exists unless overwriting is stated explicitly. A restore that
refuses leaves no partial file behind, because a half-written database at the
recovery path looks like a restore that worked.
"""

from __future__ import annotations

import argparse
import gzip
import logging
import shutil
import sqlite3
import sys
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final

logger = logging.getLogger(__name__)

#: Every SQLite file on disk starts with this. It is the format's own magic.
_SQLITE_MAGIC: Final = b"SQLite format 3\x00"

#: How much of the decompressed stream is enough to classify it. A pg_dump plain
#: text dump opens with a comment banner; the magic above is 16 bytes.
_SNIFF_BYTES: Final = 4096

#: Statements that carry schema or data. Everything a plain `pg_dump` emits for
#: an *empty* database is deliberately excluded.
#:
#: Measured against PostgreSQL 16.13 rather than assumed: a dump of a database
#: with no objects is not empty — it contains ten statements, nine `SET`s and a
#: `SELECT pg_catalog.set_config(...)`, wrapped in a banner. An earlier version
#: of this list included a bare `SELECT `, so it counted that boilerplate as
#: content and accepted a backup of nothing. The integration test against a real
#: server is what caught it; the unit tests could not, because a fabricated dump
#: never contained the preamble.
_PG_CONTENT_STATEMENTS: Final = (
    "CREATE ",
    "COPY ",
    "INSERT ",
    "ALTER TABLE ",
    "GRANT ",
    "REVOKE ",
)

#: Session boilerplate. Present in every dump, evidence of nothing.
_PG_BOILERPLATE: Final = ("SET ", "SELECT pg_catalog.set_config")


class BackupFormat(Enum):
    """What a backup artefact actually contains."""

    SQLITE = "sqlite"
    POSTGRES_SQL = "postgres_sql"


class RestoreRefused(RuntimeError):
    """The backup cannot be trusted, so nothing was restored.

    Raised in preference to returning a falsy result: a caller that ignores a
    return value still stops on an exception, and this is a data-recovery path
    where proceeding on a bad artefact is the catastrophic outcome.
    """


@dataclass(frozen=True)
class VerifyReport:
    path: Path
    format: BackupFormat
    bytes_uncompressed: int
    tables: int
    statements: int


@dataclass(frozen=True)
class RestoreResult:
    source: Path
    target: Path
    format: BackupFormat
    tables_restored: int
    rows_restored: int


def _read_head(path: Path, limit: int = _SNIFF_BYTES) -> bytes:
    """Decompress just enough of the artefact to classify it, refusing early."""
    if not path.exists():
        raise RestoreRefused(f"backup does not exist: {path}")
    if path.stat().st_size == 0:
        raise RestoreRefused(f"backup is empty: {path}")
    try:
        with gzip.open(path, "rb") as fh:
            head = fh.read(limit)
    except gzip.BadGzipFile as exc:
        raise RestoreRefused(f"backup is not gzip: {path} ({exc})") from exc
    except (EOFError, OSError) as exc:
        raise RestoreRefused(f"backup is truncated or unreadable: {path} ({exc})") from exc
    if not head:
        # Valid gzip wrapping zero bytes. `sqlite3.connect()` on a database
        # nothing has written yet leaves a zero-byte file, so this is a real
        # shape a backup arrives in, not a hypothetical one.
        raise RestoreRefused(f"backup decompressed to nothing: {path}")
    return head


def detect_format(path: Path) -> BackupFormat:
    """Classify a backup by its content.

    Deliberately ignores the file extension: `database.backup` shipped binary
    SQLite databases under `*.sql.gz` names, so extensions in existing backup
    directories are not evidence of anything.
    """
    head = _read_head(path)
    if head.startswith(_SQLITE_MAGIC):
        return BackupFormat.SQLITE
    text = head.decode("utf-8", errors="replace").lstrip()
    if text.startswith("--") or "PostgreSQL database dump" in text or text.upper().startswith("SET "):
        return BackupFormat.POSTGRES_SQL
    raise RestoreRefused(
        f"unrecognised backup content in {path.name}: "
        f"neither a SQLite database nor a plain SQL dump (first bytes: {head[:24]!r})"
    )


def _decompress_to(path: Path, destination: Path) -> int:
    """Stream the artefact out, so a multi-gigabyte dump does not enter memory."""
    written = 0
    try:
        with gzip.open(path, "rb") as src, open(destination, "wb") as dst:
            while chunk := src.read(1024 * 1024):
                dst.write(chunk)
                written += len(chunk)
    except (gzip.BadGzipFile, EOFError, OSError) as exc:
        destination.unlink(missing_ok=True)
        raise RestoreRefused(f"backup is truncated or unreadable: {path} ({exc})") from exc
    if written == 0:
        destination.unlink(missing_ok=True)
        raise RestoreRefused(f"backup decompressed to nothing: {path}")
    return written


def _sqlite_table_names(db_path: Path) -> list[str]:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return [
            row[0]
            for row in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        ]
    finally:
        con.close()


def _count_content_statements(dump_path: Path) -> tuple[int, int]:
    """Count content statements and CREATE TABLEs in a plain SQL dump.

    Streams the file. The nightly job verifies every backup it writes, inside a
    Celery worker, so an implementation that read the dump into a string would
    use memory proportional to the database — the same defect this phase already
    fixed in `pg_dump` itself. Fixing it there and reintroducing it here would
    have moved the outage rather than removed it.

    Line-oriented on purpose. Counting substrings anywhere in the text would
    match the word inside a `COPY` data block or a comment, so one table full of
    the word "CREATE" would look like a rich schema.
    """
    statements = create_tables = 0
    with open(dump_path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            stripped = line.lstrip()
            if any(stripped.startswith(noise) for noise in _PG_BOILERPLATE):
                continue
            if stripped.startswith("CREATE TABLE"):
                create_tables += 1
            if any(stripped.startswith(kw) for kw in _PG_CONTENT_STATEMENTS):
                statements += 1
    return statements, create_tables


def verify_backup(path: Path) -> VerifyReport:
    """Is this artefact restorable, and does it contain anything?

    Both halves matter. The WAL defect produced artefacts that were perfectly
    valid SQLite databases containing no tables at all, so a checker that stopped
    at "it opens" would have passed every one of them.
    """
    path = Path(path)
    fmt = detect_format(path)

    with tempfile.TemporaryDirectory(prefix="hopefx-verify-") as tmp:
        staged = Path(tmp) / "staged"
        size = _decompress_to(path, staged)

        if fmt is BackupFormat.SQLITE:
            try:
                tables = _sqlite_table_names(staged)
            except sqlite3.DatabaseError as exc:
                raise RestoreRefused(f"backup is not a readable SQLite database: {path} ({exc})") from exc
            if not tables:
                raise RestoreRefused(
                    f"backup contains no tables: {path.name}. A SQLite database in WAL mode "
                    "copied file-only produces exactly this — the rows are still in the -wal "
                    "sidecar. Treat this backup as lost."
                )
            return VerifyReport(path, fmt, size, tables=len(tables), statements=0)

        statements, create_tables = _count_content_statements(staged)
        if statements == 0:
            raise RestoreRefused(
                f"backup contains no statements: {path.name}. A plain pg_dump of the wrong "
                "database, or of one with no objects, emits only its banner and session "
                "settings — which compress, decompress and restore to nothing."
            )
        return VerifyReport(path, fmt, size, tables=create_tables, statements=statements)


def restore_sqlite(path: Path, target: Path, *, overwrite: bool = False) -> RestoreResult:
    """Restore a SQLite backup to ``target``, verifying it first.

    The target is written atomically: the artefact is staged and checked in a
    temporary directory and only moved into place once it is known good, so a
    refusal never leaves a partial database at the recovery path.
    """
    path, target = Path(path), Path(target)
    if target.exists() and not overwrite:
        raise RestoreRefused(f"target already exists: {target}. Pass overwrite=True (or --overwrite) to replace it.")

    report = verify_backup(path)
    if report.format is not BackupFormat.SQLITE:
        raise RestoreRefused(f"{path.name} is a {report.format.value} backup; use restore_postgres")

    with tempfile.TemporaryDirectory(prefix="hopefx-restore-") as tmp:
        staged = Path(tmp) / "restored.db"
        _decompress_to(path, staged)
        tables = _sqlite_table_names(staged)
        con = sqlite3.connect(f"file:{staged}?mode=ro", uri=True)
        try:
            rows = sum(con.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in tables)  # nosec B608
        finally:
            con.close()
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staged), str(target))

    logger.info("Restored %s → %s (%d tables, %d rows)", path.name, target, len(tables), rows)
    return RestoreResult(path, target, BackupFormat.SQLITE, len(tables), rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify or restore a HOPEFX database backup.")
    parser.add_argument("backup", type=Path, help="Path to a .gz backup artefact")
    parser.add_argument("--verify", action="store_true", help="Check the backup and exit without restoring")
    parser.add_argument("--target", type=Path, help="Where to restore (SQLite only)")
    parser.add_argument("--overwrite", action="store_true", help="Replace an existing target")
    args = parser.parse_args(argv)

    try:
        report = verify_backup(args.backup)
        # Only the fields that mean something for this format. "0 statements" on
        # a SQLite backup is noise, and noise in an incident is a cost.
        detail = f"{report.tables} table" + ("" if report.tables == 1 else "s")
        if report.format is BackupFormat.POSTGRES_SQL:
            detail += f" · {report.statements} content statement" + ("" if report.statements == 1 else "s")
        print(f"{args.backup.name}: {report.format.value} · {report.bytes_uncompressed:,} bytes · {detail}")
        if args.verify:
            return 0
        if report.format is not BackupFormat.SQLITE:
            print(
                "PostgreSQL restore is a supervised operation — see docs/runbooks/database-restore.md",
                file=sys.stderr,
            )
            return 2
        if args.target is None:
            print("--target is required to restore", file=sys.stderr)
            return 2
        result = restore_sqlite(args.backup, args.target, overwrite=args.overwrite)
        print(f"restored → {result.target} ({result.tables_restored} tables, {result.rows_restored} rows)")
        return 0
    except RestoreRefused as exc:
        print(f"REFUSED — {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
