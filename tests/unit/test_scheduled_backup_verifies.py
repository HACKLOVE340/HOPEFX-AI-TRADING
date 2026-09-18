# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The scheduled backup must check what it wrote.

`celery_app.database_backup` runs every 24 hours and, before this change,
returned `{"status": "ok"}` on the strength of `run_backup()` not raising. That
is trust, not verification, and it is how the WAL defect survived: the SQLite
path wrote an artefact that restored to an empty database, the task logged
success, and nothing anywhere disagreed.

So the task now verifies its own output and reports `unverified` when it cannot.
Rule 2 applies: an unverified backup is **absent**, not assumed good. Rule 3
too — the status the operator reads must never be more confident than the
evidence behind it.
"""

from __future__ import annotations

import gzip
import sqlite3
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]


def _sqlite_with_rows(path: Path) -> None:
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY)")
    con.execute("INSERT INTO trades VALUES (1)")
    con.commit()
    con.close()


class TestASoundBackupIsReportedVerified:
    def test_the_result_carries_the_verification(self, tmp_path: Path, monkeypatch) -> None:
        from celery_app import database_backup

        source = tmp_path / "live.db"
        _sqlite_with_rows(source)
        backups = tmp_path / "backups"
        backups.mkdir()

        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{source}")
        monkeypatch.setattr("database.backup._BACKUP_DIR", backups)

        result = database_backup()
        assert result["status"] == "ok"
        assert result["verified"] is True
        assert result["tables"] >= 1
        assert Path(result["backup"]).exists()


class TestABadBackupIsNeverReportedOk:
    """The case that matters. A control that reports success on a worthless
    artefact is worse than no control, because it stops anyone looking."""

    def test_an_unrestorable_artefact_is_reported_unverified(self, tmp_path: Path, monkeypatch) -> None:
        import celery_app

        broken = tmp_path / "broken.db.gz"
        with gzip.open(broken, "wb") as fh:
            fh.write(b"\x00 this will never restore")

        monkeypatch.setattr(celery_app, "_redis_lock", _null_lock)
        monkeypatch.setattr("database.backup.run_backup", lambda *a, **k: broken)

        result = celery_app.database_backup()
        assert result["status"] == "unverified"
        assert result["verified"] is False
        assert "reason" in result and result["reason"]

    def test_the_wal_victim_artefact_is_reported_unverified(self, tmp_path: Path, monkeypatch) -> None:
        # The exact artefact the old SQLite backup produced: a structurally valid
        # database whose rows were left behind in the -wal sidecar.
        import celery_app

        live = tmp_path / "live.db"
        con = sqlite3.connect(live)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY)")
        con.execute("INSERT INTO trades VALUES (1)")
        con.commit()
        try:
            victim = tmp_path / "victim.db.gz"
            with open(live, "rb") as src, gzip.open(victim, "wb") as dst:
                dst.write(src.read())
        finally:
            con.close()

        monkeypatch.setattr(celery_app, "_redis_lock", _null_lock)
        monkeypatch.setattr("database.backup.run_backup", lambda *a, **k: victim)

        result = celery_app.database_backup()
        assert result["status"] == "unverified", "a backup that restores to nothing was reported ok"
        assert "no tables" in result["reason"]


class _null_lock:
    """`_redis_lock` without Redis. The lock is not what these tests are about."""

    def __init__(self, *args, **kwargs) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False
