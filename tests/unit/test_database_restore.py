# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""A backup that has never been restored is not a backup.

Group 2 ranks tested backup and restore first among all gaps, because it is the
only one whose worst case is unrecoverable. Before this module there was
`database/backup.py`, scheduled every 24 hours by `celery_app.database_backup`,
with **no restore path and no test of either**.

Two defects were found by executing the existing code, not by reading it:

1. **The SQLite backup of a WAL database restores to nothing.** `PRAGMA
   journal_mode=WAL` is set in `database/connection.py:250`, so committed rows
   live in the `-wal` sidecar until a checkpoint. The old backup copied the main
   file alone. Reproduced: a database with one committed row produced a copy
   where `SELECT count(*) FROM trades` raised *no such table: trades*. The
   scheduled job logged success either way.

2. **The artefact's name lies about its format.** The SQLite path wrote a binary
   database under a `*.sql.gz` name, so anything restoring by extension would
   feed a binary file to a SQL interpreter.

Both are the same failure in the end: a control that reports success while
producing a worthless artefact. So the rule here is Rule 1 at full strength —
**every refusal below is proven by handing the code the exact broken artefact it
must reject**, and the round trip is proven by restoring real rows, not by
checking that a file exists.
"""

from __future__ import annotations

import gzip
import sqlite3
from pathlib import Path

import pytest

from database.restore import (
    BackupFormat,
    RestoreRefused,
    detect_format,
    restore_sqlite,
    verify_backup,
)

pytestmark = [pytest.mark.unit]


def _make_wal_database(path: Path, rows: int = 3) -> None:
    """A database in the journal mode this project actually deploys."""
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, symbol TEXT, qty REAL)")
    con.executemany(
        "INSERT INTO trades VALUES (?, ?, ?)",
        [(i, "XAUUSD", 0.1 * i) for i in range(1, rows + 1)],
    )
    con.commit()
    con.close()


class TestTheFormatIsReadFromTheContent:
    """Never from the filename. The filename already lied once."""

    def test_a_sqlite_database_is_recognised(self, tmp_path: Path) -> None:
        db = tmp_path / "x.db"
        _make_wal_database(db)
        blob = tmp_path / "anything.sql.gz"
        with open(db, "rb") as src, gzip.open(blob, "wb") as dst:
            dst.write(src.read())
        assert detect_format(blob) is BackupFormat.SQLITE

    def test_postgres_plain_sql_is_recognised(self, tmp_path: Path) -> None:
        blob = tmp_path / "anything.db.gz"
        with gzip.open(blob, "wt", encoding="utf-8") as fh:
            fh.write("--\n-- PostgreSQL database dump\n--\nCREATE TABLE trades ();\n")
        assert detect_format(blob) is BackupFormat.POSTGRES_SQL

    def test_a_misnamed_sqlite_backup_is_still_read_as_sqlite(self, tmp_path: Path) -> None:
        # The exact artefact the old code produced: a binary database under a
        # `.sql.gz` name. Restoring this by extension would pipe it into psql.
        db = tmp_path / "x.db"
        _make_wal_database(db)
        blob = tmp_path / "hopefx_20260908T000000Z.sql.gz"
        with open(db, "rb") as src, gzip.open(blob, "wb") as dst:
            dst.write(src.read())
        assert detect_format(blob) is BackupFormat.SQLITE

    def test_unrecognised_content_is_refused_not_guessed(self, tmp_path: Path) -> None:
        blob = tmp_path / "junk.sql.gz"
        with gzip.open(blob, "wb") as fh:
            fh.write(b"\x00\x01\x02 this is not a backup of anything\n")
        with pytest.raises(RestoreRefused, match="unrecognised"):
            detect_format(blob)


class TestVerifyRefusesEveryBrokenArtefact:
    """Each case below is a real way a backup arrives worthless. The control has
    to say so; a control that accepts them all cannot fail."""

    def test_a_missing_file_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(RestoreRefused, match="does not exist"):
            verify_backup(tmp_path / "absent.sql.gz")

    def test_an_empty_file_is_refused(self, tmp_path: Path) -> None:
        blob = tmp_path / "empty.sql.gz"
        blob.write_bytes(b"")
        with pytest.raises(RestoreRefused, match="empty"):
            verify_backup(blob)

    def test_a_file_that_is_not_gzip_is_refused(self, tmp_path: Path) -> None:
        blob = tmp_path / "plain.sql.gz"
        blob.write_bytes(b"CREATE TABLE trades ();\n")
        with pytest.raises(RestoreRefused, match="gzip"):
            verify_backup(blob)

    def test_a_truncated_gzip_is_refused(self, tmp_path: Path) -> None:
        db = tmp_path / "x.db"
        _make_wal_database(db)
        good = tmp_path / "good.sql.gz"
        with open(db, "rb") as src, gzip.open(good, "wb") as dst:
            dst.write(src.read())
        truncated = tmp_path / "truncated.sql.gz"
        truncated.write_bytes(good.read_bytes()[: len(good.read_bytes()) // 2])
        with pytest.raises(RestoreRefused):
            verify_backup(truncated)

    def test_a_sqlite_backup_with_no_tables_is_refused(self, tmp_path: Path) -> None:
        # This is defect 1, bottled. A WAL database copied file-only decompresses
        # cleanly, opens cleanly, and contains nothing. Structural validity is
        # not evidence of content, and this is the case that would have shipped.
        live = tmp_path / "live.db"
        con = sqlite3.connect(live)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY)")
        con.execute("INSERT INTO trades VALUES (1)")
        con.commit()
        try:
            # Exactly what the old `_backup_sqlite` did: copy the main file and
            # leave the -wal sidecar, where the committed rows still are.
            blob = tmp_path / "wal_victim.sql.gz"
            with open(live, "rb") as src, gzip.open(blob, "wb") as dst:
                dst.write(src.read())
        finally:
            con.close()

        assert blob.stat().st_size > 0, "the victim artefact is empty — test proves nothing"
        with pytest.raises(RestoreRefused, match="no tables"):
            verify_backup(blob)

    def test_a_backup_that_decompresses_to_nothing_is_refused(self, tmp_path: Path) -> None:
        blob = tmp_path / "hollow.sql.gz"
        with gzip.open(blob, "wb") as fh:
            fh.write(b"")
        with pytest.raises(RestoreRefused, match="decompressed to nothing"):
            verify_backup(blob)

    def test_a_postgres_dump_with_no_statements_is_refused(self, tmp_path: Path) -> None:
        blob = tmp_path / "header_only.sql.gz"
        with gzip.open(blob, "wt", encoding="utf-8") as fh:
            fh.write("--\n-- PostgreSQL database dump\n--\n\n-- completed\n")
        with pytest.raises(RestoreRefused, match="no statements"):
            verify_backup(blob)

    def test_a_real_backup_verifies(self, tmp_path: Path) -> None:
        # The positive control. Every test above passes against a `verify_backup`
        # that refuses unconditionally.
        db = tmp_path / "x.db"
        _make_wal_database(db)
        blob = tmp_path / "good.sql.gz"
        con = sqlite3.connect(db)
        dest = sqlite3.connect(tmp_path / "consistent.db")
        con.backup(dest)
        dest.close()
        con.close()
        with open(tmp_path / "consistent.db", "rb") as src, gzip.open(blob, "wb") as dst:
            dst.write(src.read())
        report = verify_backup(blob)
        assert report.format is BackupFormat.SQLITE
        assert report.tables >= 1
        assert report.bytes_uncompressed > 0


class TestTheRoundTripRestoresRealRows:
    """Not "a file appeared". Rows, compared."""

    def test_rows_survive_backup_and_restore(self, tmp_path: Path) -> None:
        from database.backup import run_backup

        source = tmp_path / "live.db"
        _make_wal_database(source, rows=5)

        backups = tmp_path / "backups"
        backups.mkdir()
        blob = run_backup(f"sqlite:///{source}", backup_dir=backups)

        target = tmp_path / "recovered.db"
        result = restore_sqlite(blob, target)

        assert result.rows_restored == 5
        con = sqlite3.connect(target)
        rows = con.execute("SELECT id, symbol, qty FROM trades ORDER BY id").fetchall()
        con.close()
        assert rows == [(i, "XAUUSD", pytest.approx(0.1 * i)) for i in range(1, 6)]

    def test_a_wal_database_backed_up_live_still_restores(self, tmp_path: Path) -> None:
        # Defect 1's regression test. Against the old file-copy backup this
        # restores zero rows, because the committed rows are still in the -wal
        # sidecar. The connection is deliberately left open and uncheckpointed.
        from database.backup import run_backup

        source = tmp_path / "live.db"
        con = sqlite3.connect(source)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, symbol TEXT)")
        con.execute("INSERT INTO trades VALUES (1, 'XAUUSD')")
        con.commit()
        try:
            assert (source.parent / "live.db-wal").exists(), "no WAL sidecar — test proves nothing"

            backups = tmp_path / "backups"
            backups.mkdir()
            blob = run_backup(f"sqlite:///{source}", backup_dir=backups)
        finally:
            con.close()

        target = tmp_path / "recovered.db"
        assert restore_sqlite(blob, target).rows_restored == 1

    def test_restore_will_not_silently_overwrite(self, tmp_path: Path) -> None:
        from database.backup import run_backup

        source = tmp_path / "live.db"
        _make_wal_database(source)
        backups = tmp_path / "backups"
        backups.mkdir()
        blob = run_backup(f"sqlite:///{source}", backup_dir=backups)

        occupied = tmp_path / "occupied.db"
        occupied.write_bytes(b"something a human cares about")
        with pytest.raises(RestoreRefused, match="already exists"):
            restore_sqlite(blob, occupied)
        assert occupied.read_bytes() == b"something a human cares about"

    def test_overwrite_is_possible_when_stated(self, tmp_path: Path) -> None:
        from database.backup import run_backup

        source = tmp_path / "live.db"
        _make_wal_database(source)
        backups = tmp_path / "backups"
        backups.mkdir()
        blob = run_backup(f"sqlite:///{source}", backup_dir=backups)

        occupied = tmp_path / "occupied.db"
        occupied.write_bytes(b"stale")
        assert restore_sqlite(blob, occupied, overwrite=True).rows_restored == 3

    def test_a_failed_restore_leaves_the_existing_database_untouched(self, tmp_path: Path) -> None:
        """The case that actually happens at 3am.

        You are restoring over a damaged database with ``--overwrite`` because
        you have decided to lose what is there. The backup then turns out to be
        bad. You must still have what you had — an implementation that truncates
        the target before it reads the artefact destroys the only remaining copy.

        The first version of this test asserted "no partial file appears" using a
        garbage artefact. That passed against an implementation with the cleanup
        deleted, because verification refuses before the target is ever opened —
        a second code path satisfied the assertion. This one cannot: it fails
        unless the target is genuinely left alone.
        """
        live = tmp_path / "production.db"
        _make_wal_database(live, rows=4)
        before = live.read_bytes()

        bad = tmp_path / "bad.sql.gz"
        with gzip.open(bad, "wb") as fh:
            fh.write(b"\x00 not a database")

        with pytest.raises(RestoreRefused):
            restore_sqlite(bad, live, overwrite=True)

        assert live.read_bytes() == before
        con = sqlite3.connect(live)
        assert con.execute("SELECT count(*) FROM trades").fetchone()[0] == 4
        con.close()

    def test_no_partial_file_appears_at_a_fresh_target(self, tmp_path: Path) -> None:
        blob = tmp_path / "junk.sql.gz"
        with gzip.open(blob, "wb") as fh:
            fh.write(b"\x00 not a database")
        target = tmp_path / "recovered.db"
        with pytest.raises(RestoreRefused):
            restore_sqlite(blob, target)
        assert not target.exists()


class TestDecompressionCleansUpAfterItself:
    """`_decompress_to` is the one place that writes a file before knowing the
    artefact is sound, so its cleanup is tested directly rather than through a
    caller that never reaches it."""

    def test_a_truncated_stream_leaves_no_output_file(self, tmp_path: Path) -> None:
        from database.restore import _decompress_to

        db = tmp_path / "x.db"
        _make_wal_database(db, rows=200)
        good = tmp_path / "good.gz"
        with open(db, "rb") as src, gzip.open(good, "wb") as dst:
            dst.write(src.read())

        truncated = tmp_path / "truncated.gz"
        raw = good.read_bytes()
        truncated.write_bytes(raw[: len(raw) - 40])

        out = tmp_path / "staged.db"
        with pytest.raises(RestoreRefused):
            _decompress_to(truncated, out)
        assert not out.exists(), "a partial decompression was left on disk"

    def test_a_sound_stream_is_written_in_full(self, tmp_path: Path) -> None:
        from database.restore import _decompress_to

        db = tmp_path / "x.db"
        _make_wal_database(db, rows=200)
        blob = tmp_path / "good.gz"
        with open(db, "rb") as src, gzip.open(blob, "wb") as dst:
            dst.write(src.read())

        out = tmp_path / "staged.db"
        assert _decompress_to(blob, out) == db.stat().st_size
        assert out.stat().st_size == db.stat().st_size


class TestRotationSurvivedTheExtensionChange:
    """SQLite artefacts were renamed `.sql.gz` → `.db.gz` in the same change.

    A rotation that globbed only one of them would keep every old file forever
    and the first symptom would be a full backup volume — during, most likely,
    the incident that needed the space.
    """

    def test_both_extensions_rotate_together(self, tmp_path: Path) -> None:
        import os

        from database.backup import _rotate

        names = [f"hopefx_2026090{i}T000000Z.sql.gz" for i in range(1, 6)]
        names += [f"hopefx_2026091{i}T000000Z.db.gz" for i in range(0, 4)]
        for i, name in enumerate(names):
            path = tmp_path / name
            path.write_bytes(b"x")
            os.utime(path, (1000 + i, 1000 + i))

        _rotate(tmp_path, "hopefx", keep=3)
        remaining = sorted(p.name for p in tmp_path.iterdir())
        assert len(remaining) == 3, remaining
        assert all(n.endswith(".db.gz") for n in remaining), f"kept the older generation: {remaining}"

    def test_retention_of_zero_keeps_everything(self, tmp_path: Path) -> None:
        # `keep=0` reads as "keep nothing", and deleting every backup is not a
        # behaviour to arrive at by accident. The existing code treats it as
        # "do not rotate"; this pins that rather than leaving it to inference.
        from database.backup import _rotate

        for i in range(4):
            (tmp_path / f"hopefx_20260{i}101T000000Z.db.gz").write_bytes(b"x")
        _rotate(tmp_path, "hopefx", keep=0)
        assert len(list(tmp_path.iterdir())) == 4


class TestVerificationDoesNotLoadTheWholeDump:
    """The nightly job verifies every backup it writes, inside a Celery worker.

    An implementation that reads the decompressed dump into a string uses memory
    proportional to the database — which is the defect this phase already fixed
    once, in `pg_dump` itself. Fixing it there and reintroducing it in the
    verifier would have moved the outage rather than removed it.
    """

    def test_peak_memory_stays_far_below_the_dump_size(self, tmp_path: Path) -> None:
        import tracemalloc

        from database.restore import verify_backup

        blob = tmp_path / "big.sql.gz"
        row = "INSERT INTO trades VALUES (1, 'XAUUSD', 0.10);\n"
        payload = "--\n-- PostgreSQL database dump\n--\nCREATE TABLE trades ();\n" + row * 400_000
        uncompressed = len(payload.encode())
        with gzip.open(blob, "wt", encoding="utf-8") as fh:
            fh.write(payload)
        assert uncompressed > 16_000_000, f"the fixture is only {uncompressed} bytes — it proves nothing"

        tracemalloc.start()
        try:
            report = verify_backup(blob)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

        assert report.statements > 100_000
        # A whole-file read would peak at or above the dump size. Streaming peaks
        # at roughly one chunk, so a quarter of the file is a generous ceiling
        # that still fails loudly on a read_text() implementation.
        assert peak < uncompressed // 4, (
            f"peak {peak:,} bytes against a {uncompressed:,} byte dump — the verifier is buffering it"
        )


class TestTheCommandLineAnOperatorActuallyUses:
    """`python -m database.restore` is the interface in the runbook.

    It was untested — the module's logic was covered, its entry point was not,
    and the entry point is the part a person types at 3am under pressure. Every
    command in `docs/runbooks/database-restore.md` is exercised here.
    """

    def test_verify_reports_a_sound_backup_and_exits_zero(self, tmp_path: Path, capsys) -> None:
        from database.restore import main

        source = tmp_path / "live.db"
        _make_wal_database(source, rows=4)
        blob = run_backup_for(source, tmp_path / "backups")

        assert main([str(blob), "--verify"]) == 0
        out = capsys.readouterr().out
        assert "sqlite" in out and "table" in out

    def test_verify_refuses_the_wal_victim_and_exits_nonzero(self, tmp_path: Path, capsys) -> None:
        from database.restore import main

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

        assert main([str(victim), "--verify"]) == 1
        assert "REFUSED" in capsys.readouterr().err

    def test_a_restore_writes_the_target_and_reports_the_rows(self, tmp_path: Path, capsys) -> None:
        from database.restore import main

        source = tmp_path / "live.db"
        _make_wal_database(source, rows=6)
        blob = run_backup_for(source, tmp_path / "backups")
        target = tmp_path / "recovered.db"

        assert main([str(blob), "--target", str(target)]) == 0
        assert target.exists()
        assert "6 rows" in capsys.readouterr().out

    def test_restoring_without_a_target_is_refused(self, tmp_path: Path, capsys) -> None:
        from database.restore import main

        source = tmp_path / "live.db"
        _make_wal_database(source)
        blob = run_backup_for(source, tmp_path / "backups")

        assert main([str(blob)]) == 2
        assert "--target is required" in capsys.readouterr().err

    def test_an_existing_target_is_refused_without_overwrite(self, tmp_path: Path, capsys) -> None:
        from database.restore import main

        source = tmp_path / "live.db"
        _make_wal_database(source)
        blob = run_backup_for(source, tmp_path / "backups")
        occupied = tmp_path / "occupied.db"
        occupied.write_bytes(b"something a human cares about")

        assert main([str(blob), "--target", str(occupied)]) == 1
        assert occupied.read_bytes() == b"something a human cares about"
        assert "REFUSED" in capsys.readouterr().err

    def test_overwrite_is_honoured_when_stated(self, tmp_path: Path) -> None:
        from database.restore import main

        source = tmp_path / "live.db"
        _make_wal_database(source, rows=2)
        blob = run_backup_for(source, tmp_path / "backups")
        occupied = tmp_path / "occupied.db"
        occupied.write_bytes(b"stale")

        assert main([str(blob), "--target", str(occupied), "--overwrite"]) == 0
        assert sqlite3.connect(occupied).execute("SELECT count(*) FROM trades").fetchone()[0] == 2

    def test_a_postgres_backup_sends_the_operator_to_the_runbook(self, tmp_path: Path, capsys) -> None:
        # Restoring PostgreSQL is supervised; the CLI must say so rather than
        # half-doing it.
        from database.restore import main

        blob = tmp_path / "pg.sql.gz"
        with gzip.open(blob, "wt", encoding="utf-8") as fh:
            fh.write("--\n-- PostgreSQL database dump\n--\nCREATE TABLE trades ();\n")

        assert main([str(blob), "--target", str(tmp_path / "x.db")]) == 2
        assert "database-restore.md" in capsys.readouterr().err

    def test_a_missing_backup_exits_nonzero(self, tmp_path: Path, capsys) -> None:
        from database.restore import main

        assert main([str(tmp_path / "absent.db.gz"), "--verify"]) == 1
        assert "does not exist" in capsys.readouterr().err


def run_backup_for(source: Path, backups: Path) -> Path:
    from database.backup import run_backup

    backups.mkdir(parents=True, exist_ok=True)
    return run_backup(f"sqlite:///{source}", backup_dir=backups)
