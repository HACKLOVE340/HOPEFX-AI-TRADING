# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_preflight_migration_is_bounded.py
==================================================
``alembic upgrade head`` ran with no time limit of any kind, inside a container
whose command is ``preflight.sh && python app.py``.

A migration that blocks therefore stops the deploy dead with no diagnosis
available: the last line of output stays ``[ 5/9 ] Database``, ``python app.py``
never runs, nothing listens on 8000, and the only external symptom is the
healthcheck failing — the same symptom produced by all nine checks and by a
crash in the app itself.

A migration blocks when another session holds a conflicting lock, and Postgres
waits for one indefinitely by default. The way that arises here is
self-sustaining: a container stopped part-way through a migration can leave a
backend holding locks, so the next attempt blocks on the previous attempt's
debris, and so does the one after that.

Three limits now apply, and each is overridable, because a genuinely long data
migration deserves explicit room rather than the removal of all bounds:

* ``lock_timeout`` (30s)      — the one that matters; unblocks the case above
* ``statement_timeout`` (300s) — bounds a single slow statement
* ``MIGRATION_TIMEOUT`` (900s) — bounds the whole run, for stalls libpq's own
  timeouts do not reach

The tests below execute the real block extracted from preflight.sh with the
alembic invocation substituted, rather than asserting on its text. Grepping for
``timeout`` would pass against a script that never reaches it.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import time

import pytest

pytestmark = pytest.mark.unit

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_PREFLIGHT = _ROOT / "scripts/preflight.sh"
_SRC = _PREFLIGHT.read_text()

_HARNESS_HEAD = """#!/usr/bin/env bash
set -euo pipefail
ok(){ echo "  OK  $*"; }
warn(){ echo "  WARN $*"; }
fail(){ echo "  FAIL $*" >&2; exit 1; }
if [ "${SKIP_MIGRATIONS:-false}" != "true" ]; then"""


def _migration_block() -> str:
    body = _SRC.split('if [ "${SKIP_MIGRATIONS:-false}" != "true" ]; then', 1)[1].split("# ── 6. Redis", 1)[0]
    assert "alembic upgrade head" in body, "the migration step moved — this harness is stale"
    return body


def _run(substitute: str, env: dict[str, str], tmp_path: pathlib.Path, timeout: int = 60):
    """Run the real migration block with alembic replaced by *substitute*."""
    script = tmp_path / "mig.sh"
    script.write_text(_HARNESS_HEAD + _migration_block().replace("python3 -m alembic upgrade head", substitute))
    return subprocess.run(
        ["bash", str(script)],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", **env},
        timeout=timeout,
        check=False,
    )


# ── The hang is bounded ──────────────────────────────────────────────────────


def test_a_blocked_migration_is_stopped_rather_than_waited_on(tmp_path):
    """Without this the deploy stops at [ 5/9 ] and never says why."""
    started = time.monotonic()
    result = _run("sleep 999", {"MIGRATION_TIMEOUT": "3"}, tmp_path)
    elapsed = time.monotonic() - started

    assert result.returncode != 0
    assert elapsed < 30, f"took {elapsed:.1f}s — the limit did not apply"
    assert "timed out" in result.stderr


def test_the_timeout_message_names_the_usual_cause_and_the_way_out(tmp_path):
    """A bounded hang with no explanation is only marginally better than a hang."""
    stderr = _run("sleep 999", {"MIGRATION_TIMEOUT": "2"}, tmp_path).stderr.lower()
    assert "lock" in stderr
    assert "pg_stat_activity" in stderr, "must show how to see what is blocking"
    assert "restart postgres" in stderr, "must give the usual remedy"


def test_the_whole_run_limit_is_overridable(tmp_path):
    """A long data migration needs room granted deliberately, not the limits
    removed."""
    started = time.monotonic()
    _run("sleep 999", {"MIGRATION_TIMEOUT": "1"}, tmp_path)
    quick = time.monotonic() - started

    started = time.monotonic()
    _run("sleep 999", {"MIGRATION_TIMEOUT": "4"}, tmp_path)
    slower = time.monotonic() - started

    assert slower > quick + 1.5, f"the override had no effect ({quick:.1f}s vs {slower:.1f}s)"


# ── The lock timeout reaches Postgres ────────────────────────────────────────


def test_pgoptions_reaches_the_migration_process(tmp_path):
    """Set on the wrong side of the pipeline it would silently not apply."""
    result = _run("printenv PGOPTIONS", {}, tmp_path)
    assert result.returncode == 0, result.stderr
    assert "lock_timeout" in result.stdout
    assert "statement_timeout" in result.stdout


@pytest.mark.parametrize(
    ("var", "value", "expected"),
    [
        ("MIGRATION_LOCK_TIMEOUT", "7s", "lock_timeout=7s"),
        ("MIGRATION_STATEMENT_TIMEOUT", "42s", "statement_timeout=42s"),
    ],
)
def test_each_postgres_timeout_is_overridable(tmp_path, var, value, expected):
    result = _run("printenv PGOPTIONS", {var: value}, tmp_path)
    assert expected in result.stdout


def test_the_lock_timeout_defaults_to_something_finite(tmp_path):
    """Postgres waits for a lock forever by default; that default is the bug."""
    result = _run("printenv PGOPTIONS", {}, tmp_path)
    match = re.search(r"lock_timeout=(\S+)", result.stdout)
    assert match and match.group(1) not in ("0", "0s"), "lock_timeout=0 means wait forever"


# ── Ordinary outcomes are unchanged ──────────────────────────────────────────


def test_a_successful_migration_still_succeeds(tmp_path):
    result = _run("true", {}, tmp_path)
    assert result.returncode == 0
    assert "Migrations up to date" in result.stdout


def test_an_ordinary_failure_is_not_reported_as_a_timeout(tmp_path):
    """Exit 124 means the limit fired; anything else is a real migration error
    and must keep its own message."""
    result = _run("false", {}, tmp_path)
    assert result.returncode != 0
    assert "Alembic migration failed" in result.stderr
    assert "timed out" not in result.stderr


def test_skipping_migrations_still_works(tmp_path):
    result = _run("false", {"SKIP_MIGRATIONS": "true"}, tmp_path)
    assert result.returncode == 0
    assert "SKIP_MIGRATIONS" in result.stdout


def test_the_script_still_parses():
    """This file is the container entrypoint; a syntax error fails every start."""
    result = subprocess.run(["bash", "-n", str(_PREFLIGHT)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
