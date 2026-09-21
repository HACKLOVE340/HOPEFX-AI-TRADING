# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The PostgreSQL backup is restored into a real database, and the rows compared.

`tests/unit/test_database_restore.py` proves the SQLite round trip with no
external service, so it runs everywhere. This file proves the half that only a
real server can prove: that `pg_dump` output written by `database.backup`
actually loads, and that what comes back is what went in.

It is not a mock. It creates a scratch database, writes rows, backs it up,
restores into a second scratch database, and compares a checksum over the data.
CI runs `postgres:16` with `DATABASE_URL` set, so this executes there rather than
being skipped — an untested restore is the whole defect this phase exists to
close, and a test that always skips would recreate it in a new place.

Where no server is reachable the skip says so explicitly, because "0 failures"
from a suite that ran nothing is the reading this repository has been caught by
before.
"""

from __future__ import annotations

import gzip
import os
import subprocess  # nosec B404 — fixed argument lists, no shell
import uuid
from pathlib import Path
from urllib.parse import urlparse

import pytest

from database.backup import run_backup
from database.restore import BackupFormat, RestoreRefused, verify_backup

pytestmark = [pytest.mark.integration]

_CHECKSUM = "SELECT md5(string_agg(symbol || qty::text, ',' ORDER BY id)) FROM trades"


def _server_url() -> str | None:
    """A libpq URL for a reachable server, or None."""
    raw = os.getenv("HOPEFX_TEST_PG_URL") or os.getenv("DATABASE_URL") or ""
    if not raw:
        return None
    parsed = urlparse(raw)
    scheme = parsed.scheme.split("+")[0]
    if scheme not in ("postgresql", "postgres"):
        return None
    # Drop any SQLAlchemy driver suffix; pg_dump and psql speak libpq.
    return raw.replace(f"{parsed.scheme}://", "postgresql://", 1)


def _psql(url: str, database: str, sql: str, *, stdin: bytes | None = None) -> str:
    parsed = urlparse(url)
    cmd = ["psql", "--no-password", "-v", "ON_ERROR_STOP=1", "-tAq"]
    if parsed.hostname:
        cmd += ["-h", parsed.hostname]
    if parsed.port:
        cmd += ["-p", str(parsed.port)]
    if parsed.username:
        cmd += ["-U", parsed.username]
    cmd += ["-d", database]
    if sql:
        cmd += ["-c", sql]
    env = os.environ.copy()
    if parsed.password:
        env["PGPASSWORD"] = parsed.password
    result = subprocess.run(cmd, input=stdin, capture_output=True, env=env, check=False)  # nosec B603
    if result.returncode != 0:
        raise RuntimeError(f"psql failed: {result.stderr.decode(errors='replace')[:800]}")
    return result.stdout.decode(errors="replace").strip()


@pytest.fixture(scope="module")
def server() -> str:
    url = _server_url()
    if url is None:
        pytest.skip("no PostgreSQL URL in HOPEFX_TEST_PG_URL or DATABASE_URL — restore is UNPROVEN here")
    parsed = urlparse(url)
    admin = parsed.path.lstrip("/") or "postgres"
    try:
        _psql(url, admin, "SELECT 1")
    except (RuntimeError, FileNotFoundError) as exc:
        pytest.skip(f"PostgreSQL not reachable — restore is UNPROVEN here: {exc}")
    return url


@pytest.fixture
def scratch(server: str):
    """Two throwaway databases, dropped whatever the test does."""
    parsed = urlparse(server)
    admin = parsed.path.lstrip("/") or "postgres"
    tag = uuid.uuid4().hex[:10]
    live, restored = f"hopefx_bk_{tag}", f"hopefx_rs_{tag}"
    _psql(server, admin, f'CREATE DATABASE "{live}"')
    _psql(server, admin, f'CREATE DATABASE "{restored}"')
    try:
        yield server, live, restored
    finally:
        for name in (live, restored):
            try:
                _psql(server, admin, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            except RuntimeError:  # nosec B110 — cleanup must not mask the test result
                pass


def _url_for(server: str, database: str) -> str:
    parsed = urlparse(server)
    return parsed._replace(path=f"/{database}").geturl()


class TestTheRoundTripAgainstARealServer:
    def test_rows_survive_backup_and_restore(self, scratch, tmp_path: Path) -> None:
        server, live, restored = scratch
        _psql(
            server,
            live,
            "CREATE TABLE trades (id serial PRIMARY KEY, symbol text NOT NULL, "
            "qty numeric(12,4) NOT NULL);"
            "INSERT INTO trades (symbol, qty) "
            "SELECT 'XAUUSD', (n * 0.05)::numeric(12,4) FROM generate_series(1,7) n;",
        )
        before = _psql(server, live, _CHECKSUM)
        assert before, "the source database produced no checksum — the test would prove nothing"

        blob = run_backup(_url_for(server, live), backup_dir=tmp_path)
        report = verify_backup(blob)
        assert report.format is BackupFormat.POSTGRES_SQL
        assert report.tables >= 1

        with gzip.open(blob, "rb") as fh:
            _psql(server, restored, "", stdin=fh.read())

        after = _psql(server, restored, _CHECKSUM)
        assert after == before, f"restored data differs: {before} != {after}"
        assert _psql(server, restored, "SELECT count(*) FROM trades") == "7"


class TestTheVerifierRefusesARealDamagedDump:
    """Rule 1 against a genuine pg_dump rather than a fabricated string."""

    def test_a_truncated_real_dump_is_refused(self, scratch, tmp_path: Path) -> None:
        server, live, _ = scratch
        _psql(server, live, "CREATE TABLE trades (id serial PRIMARY KEY, symbol text, qty numeric);")
        blob = run_backup(_url_for(server, live), backup_dir=tmp_path)

        raw = blob.read_bytes()
        truncated = tmp_path / "truncated.sql.gz"
        truncated.write_bytes(raw[: len(raw) // 2])
        with pytest.raises(RestoreRefused):
            verify_backup(truncated)

    def test_a_dump_of_an_empty_database_is_refused(self, scratch, tmp_path: Path) -> None:
        # pg_dump against a database with no objects emits a banner and nothing
        # else. It compresses, it decompresses, and it restores to nothing —
        # the PostgreSQL twin of the SQLite WAL defect.
        server, _live, empty = scratch
        blob = run_backup(_url_for(server, empty), backup_dir=tmp_path)
        with pytest.raises(RestoreRefused, match="no statements"):
            verify_backup(blob)
