# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""`database/backup.py` — the scheduled snapshot, measured at last.

This file exists because the coverage gate started telling the truth. Before
Phase R5 it resolved `tests/unit/test_database.py` as this module's test — the
`test_{parent}.py` fallback — and that file never imports `database.backup`. So
coverage collected no data, produced no table, and the gate's parser returned
`None`, which took the "warn but don't block" branch.

The effect: **the module that takes every database backup had no effective
coverage check at all**, and nothing said so. Now that an unmeasurable module
fails, the gate resolves `test_database_backup.py` first and measures it.
"""

from __future__ import annotations

import gzip
import os
import sqlite3
from pathlib import Path

import pytest

from database.backup import _BACKUP_SUFFIXES, _rotate, _timestamp, run_backup

pytestmark = [pytest.mark.unit]


def _sqlite_with_rows(path: Path, rows: int = 3) -> None:
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, symbol TEXT)")
    con.executemany("INSERT INTO trades VALUES (?, ?)", [(i, "XAUUSD") for i in range(1, rows + 1)])
    con.commit()
    con.close()


class TestTheTimestamp:
    def test_it_is_utc_and_sortable(self) -> None:
        # Backups are rotated by mtime but named by timestamp; a name that does
        # not sort lexicographically makes a directory listing lie about order.
        stamp = _timestamp()
        assert stamp.endswith("Z") and "T" in stamp
        assert len(stamp) == len("20260908T120000Z")


class TestRotation:
    def test_it_keeps_the_newest_and_spans_both_suffixes(self, tmp_path: Path) -> None:
        names = [f"db_2026090{i}T000000Z.sql.gz" for i in range(1, 5)]
        names += [f"db_2026091{i}T000000Z.db.gz" for i in range(0, 3)]
        for i, name in enumerate(names):
            path = tmp_path / name
            path.write_bytes(b"x")
            os.utime(path, (1000 + i, 1000 + i))

        _rotate(tmp_path, "db", keep=2)
        remaining = sorted(p.name for p in tmp_path.iterdir())
        assert len(remaining) == 2, remaining
        assert all(n.endswith(".db.gz") for n in remaining), remaining

    def test_keep_zero_rotates_nothing(self, tmp_path: Path) -> None:
        for i in range(3):
            (tmp_path / f"db_20260{i}101T000000Z.db.gz").write_bytes(b"x")
        _rotate(tmp_path, "db", keep=0)
        assert len(list(tmp_path.iterdir())) == 3

    def test_both_suffixes_are_declared(self) -> None:
        # If a third artefact naming scheme appears, rotation must learn it or
        # the volume fills silently. Pinning the pair makes that a decision.
        assert set(_BACKUP_SUFFIXES) == {".sql.gz", ".db.gz"}


class TestTheSqlitePath:
    def test_it_writes_a_consistent_snapshot_of_a_live_wal_database(self, tmp_path: Path) -> None:
        source = tmp_path / "live.db"
        con = sqlite3.connect(source)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY)")
        con.execute("INSERT INTO trades VALUES (1)")
        con.commit()
        try:
            assert (tmp_path / "live.db-wal").exists(), "no WAL sidecar — this proves nothing"
            out = run_backup(f"sqlite:///{source}", backup_dir=tmp_path / "backups")
        finally:
            con.close()

        assert out.name.endswith(".db.gz"), f"misleading extension: {out.name}"
        with gzip.open(out, "rb") as fh:
            assert fh.read(16).startswith(b"SQLite format 3")

    def test_a_missing_source_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            run_backup(f"sqlite:///{tmp_path / 'absent.db'}", backup_dir=tmp_path)

    def test_the_destination_is_created_if_absent(self, tmp_path: Path) -> None:
        source = tmp_path / "live.db"
        _sqlite_with_rows(source)
        nested = tmp_path / "a" / "b" / "backups"
        assert run_backup(f"sqlite:///{source}", backup_dir=nested).parent == nested


class TestUrlHandling:
    def test_an_unsupported_scheme_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="Unsupported database scheme"):
            run_backup("mysql://user@host/db", backup_dir=tmp_path)

    def test_no_url_anywhere_is_refused(self, tmp_path: Path, monkeypatch) -> None:
        # Rule 3: backing up "whatever the default is" is how the wrong database
        # gets snapshotted and the right one is lost.
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setattr("database.backup._db_manager_url", lambda: None, raising=False)
        import database.connection as conn

        monkeypatch.setattr(conn, "_db_manager", None, raising=False)
        with pytest.raises(RuntimeError, match="DATABASE_URL is not set"):
            run_backup(backup_dir=tmp_path)

    def test_a_driver_suffix_is_stripped(self, tmp_path: Path) -> None:
        source = tmp_path / "live.db"
        _sqlite_with_rows(source)
        assert run_backup(f"sqlite+aiosqlite:///{source}", backup_dir=tmp_path).exists()


class _FakePgDump:
    """A stand-in for the `pg_dump` process.

    The real command is exercised against a live PostgreSQL server in
    `tests/integration/test_database_restore_postgres.py`, which is where "does
    pg_dump actually work" belongs. What is tested here is the logic around it —
    the argument list, the streaming, and what happens when it fails — none of
    which a server would exercise any better, and all of which a server would
    make slow and conditional.
    """

    instances: list[_FakePgDump] = []

    def __init__(self, cmd, stdout=None, stderr=None, env=None, **kwargs):
        self.cmd = cmd
        self.env = env or {}
        self.returncode_value = _FakePgDump.next_returncode
        self._chunks = list(_FakePgDump.next_chunks)
        self.stdout = self
        self.stderr = _Stream(_FakePgDump.next_stderr)
        _FakePgDump.instances.append(self)

    next_returncode = 0
    next_chunks: list[bytes] = [b"-- PostgreSQL database dump\nCREATE TABLE t ();\n"]
    next_stderr = b""

    def read(self, _size=-1):
        return self._chunks.pop(0) if self._chunks else b""

    def wait(self):
        return self.returncode_value


class _Stream:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self, _size=-1):
        return self._payload


@pytest.fixture
def fake_pg(monkeypatch):
    _FakePgDump.instances.clear()
    _FakePgDump.next_returncode = 0
    _FakePgDump.next_chunks = [b"-- PostgreSQL database dump\nCREATE TABLE t ();\n"]
    _FakePgDump.next_stderr = b""
    monkeypatch.setattr("database.backup.subprocess.Popen", _FakePgDump)
    return _FakePgDump


class TestThePostgresPath:
    def test_the_dump_is_written_gzipped(self, tmp_path: Path, fake_pg) -> None:
        out = run_backup("postgresql://u:p@host:5432/tradingdb", backup_dir=tmp_path)
        assert out.suffix == ".gz"
        with gzip.open(out, "rb") as fh:
            assert b"PostgreSQL database dump" in fh.read()

    def test_the_connection_details_reach_the_command(self, tmp_path: Path, fake_pg) -> None:
        run_backup("postgresql://alice:secret@db.internal:6543/tradingdb", backup_dir=tmp_path)
        cmd = fake_pg.instances[0].cmd
        assert cmd[0] == "pg_dump"
        assert "--no-password" in cmd, "pg_dump must never block on an interactive prompt"
        for expected in ("-h", "db.internal", "-p", "6543", "-U", "alice", "tradingdb"):
            assert expected in cmd, f"{expected!r} missing from {cmd}"

    def test_the_password_travels_in_the_environment_not_the_arguments(self, tmp_path: Path, fake_pg) -> None:
        # A password in argv is visible to every process on the host via `ps`.
        run_backup("postgresql://alice:hunter2@db.internal:5432/tradingdb", backup_dir=tmp_path)
        instance = fake_pg.instances[0]
        assert "hunter2" not in " ".join(instance.cmd)
        assert instance.env.get("PGPASSWORD") == "hunter2"

    def test_a_failing_dump_raises_and_leaves_no_artefact(self, tmp_path: Path, fake_pg) -> None:
        # A half-written .gz left behind after a failed dump is worse than none:
        # it looks like a backup, and rotation will happily keep it.
        fake_pg.next_returncode = 1
        fake_pg.next_stderr = b"FATAL: database does not exist"
        with pytest.raises(RuntimeError, match="pg_dump failed"):
            run_backup("postgresql://u@host/nope", backup_dir=tmp_path)
        assert list(tmp_path.glob("*.gz")) == [], "a failed dump left an artefact behind"

    def test_the_dump_is_streamed_rather_than_buffered(self, tmp_path: Path, fake_pg) -> None:
        # Several chunks must all reach the file. `capture_output=True` would
        # have held the whole dump in memory — the defect fixed in Phase R1.
        fake_pg.next_chunks = [b"-- dump\n", b"CREATE TABLE a ();\n", b"CREATE TABLE b ();\n"]
        out = run_backup("postgresql://u@host/db", backup_dir=tmp_path)
        with gzip.open(out, "rb") as fh:
            body = fh.read()
        assert b"CREATE TABLE a ();" in body and b"CREATE TABLE b ();" in body

    def test_pg_dump_missing_from_the_host_is_reported(self, tmp_path: Path, monkeypatch) -> None:
        def _boom(*_args, **_kwargs):
            raise OSError("No such file or directory: 'pg_dump'")

        monkeypatch.setattr("database.backup.subprocess.Popen", _boom)
        with pytest.raises(RuntimeError, match="could not be run"):
            run_backup("postgresql://u@host/db", backup_dir=tmp_path)
        assert list(tmp_path.glob("*.gz")) == []

    def test_a_non_postgres_scheme_reaches_the_guard(self, tmp_path: Path) -> None:
        from database.backup import _backup_postgres

        with pytest.raises(ValueError, match="Unsupported scheme"):
            _backup_postgres("mysql://u@host/db", tmp_path)
