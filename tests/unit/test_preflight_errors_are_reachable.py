# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_preflight_errors_are_reachable.py
==================================================
Every error message in preflight's database and Redis checks was unreachable.

``preflight.sh`` runs under ``set -euo pipefail`` and captured each probe as::

    DB_CHECK=$(python3 - <<'PYEOF' ... PYEOF
    )
    if [ "${DB_CHECK}" != "ok" ]; then
        ...diagnosis...
        fail "Database connection failed."
    fi

Under ``set -e``, a *variable assignment* whose command substitution fails
terminates the shell **at the assignment**. The ``if`` below it never runs. So
for every possible database fault the container printed

    [ 5/9 ] Database

and exited 1, with nothing after it — no error text, no diagnosis, no ``fail``
message. From outside, the only symptom was the healthcheck failing:

    dependency failed to start: container hopefx-ai-trading-app-1 is unhealthy

which is identical for all nine checks and for a crash in the app itself. A
production deployment spent a day on this, and each round the visible evidence
was the same three words.

The redirect added earlier to classify password failures made it worse: the
probe's stderr went to a temp file that is only printed inside the unreachable
branch, so the psycopg2 error that *had* been visible on the console stopped
appearing at all.

The Redis check carried the same bug with a sharper edge. Its branch reads:

    # Redis is OPTIONAL ... A failed check must NOT crash-loop the container
    # (previously `fail` → exit 1). Warn instead and continue.

That policy could not take effect. The shell exited at the assignment first, so
an unreachable Redis killed the container anyway — precisely the behaviour the
comment says was removed.

These tests execute the real blocks with the probe replaced by a failing
command. Reading the script would not have caught this; the bug is in what bash
does with the text, not in the text.
"""

from __future__ import annotations

import pathlib
import re
import subprocess

import pytest

pytestmark = pytest.mark.unit

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_PREFLIGHT = _ROOT / "scripts/preflight.sh"
_SRC = _PREFLIGHT.read_text()

_HARNESS = """#!/usr/bin/env bash
set -euo pipefail
ok(){ echo "  OK  $*"; }
warn(){ echo "  WARN $*"; }
fail(){ echo "  FAIL $*" >&2; exit 1; }
"""


def _block(start: str, end: str) -> str:
    assert start in _SRC, f"{start!r} not found — the harness is stale"
    return start + _SRC.split(start, 1)[1].split(end, 1)[0]


def _run(script: str, tmp_path: pathlib.Path, env: dict[str, str] | None = None):
    path = tmp_path / "block.sh"
    path.write_text(_HARNESS + script)
    return subprocess.run(
        ["bash", str(path)],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", **(env or {})},
        timeout=60,
        check=False,
    )


# ── The database check reaches its own error handling ────────────────────────


def _failing_db_block() -> str:
    """The real block with the probe swapped for one that fails.

    The message is passed through PROBE_MSG rather than embedded, so text
    containing quotes and parentheses — like a real psycopg2 error — cannot
    break the harness instead of the code under test.
    """
    block = _block('echo "[ 5/9 ] Database"', "# ── 6. Redis")
    probe = (
        "python3 -c \"import os, sys; print(os.environ['PROBE_MSG'], file=sys.stderr); sys.exit(1)\""
        " 2>\"${DB_ERR_FILE}\" <<'PYEOF'"
    )
    return block.replace("python3 - 2>\"${DB_ERR_FILE}\" <<'PYEOF'", probe)


def test_a_failing_probe_does_not_silently_end_the_script(tmp_path):
    """The whole defect in one assertion: something must be printed."""
    result = _run(_failing_db_block(), tmp_path, {"SKIP_MIGRATIONS": "true", "PROBE_MSG": "error: connection refused"})
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "[ 5/9 ] Database" in combined
    assert combined.strip() != "[ 5/9 ] Database", "the script exited at the assignment with no diagnosis"


def test_the_probes_own_error_text_is_shown(tmp_path):
    """It is the only evidence of what actually failed."""
    result = _run(_failing_db_block(), tmp_path, {"SKIP_MIGRATIONS": "true", "PROBE_MSG": "error: connection refused"})
    assert "connection refused" in result.stdout + result.stderr


def test_the_generic_failure_message_is_reached(tmp_path):
    result = _run(_failing_db_block(), tmp_path, {"SKIP_MIGRATIONS": "true", "PROBE_MSG": "error: some other problem"})
    assert "Database connection failed" in result.stdout + result.stderr


def test_the_password_diagnosis_is_reached(tmp_path):
    """Added a day before this bug was found, and never once executed."""
    message = 'error: (psycopg2.OperationalError) FATAL:  password authentication failed for user "hopefx"'
    result = _run(_failing_db_block(), tmp_path, {"SKIP_MIGRATIONS": "true", "PROBE_MSG": message})
    combined = result.stdout + result.stderr
    assert "Postgres rejected the password" in combined
    assert "docker volume rm" in combined
    assert "ALTER USER" in combined


# ── Redis stays optional, as documented ──────────────────────────────────────


def test_an_unreachable_redis_warns_and_continues(tmp_path):
    """The branch says Redis is optional and must not crash-loop the container.

    The shell exited at the assignment before reaching it, so an unreachable
    Redis killed the container regardless.
    """
    block = _block('echo "[ 6/9 ] Redis"', "# ── 7.")
    block = block.replace("python3 - <<'PYEOF'", "python3 -c 'import sys; sys.exit(1)' <<'PYEOF'")
    result = _run(block + '\necho "CONTINUED"\n', tmp_path)

    assert result.returncode == 0, f"an optional dependency ended the run: {result.stderr}"
    assert "CONTINUED" in result.stdout
    assert "Redis not reachable" in result.stdout


# ── Nothing else is left in the trap ─────────────────────────────────────────


def test_no_command_substitution_assignment_is_left_unguarded():
    """The general property, so a new check cannot reintroduce this.

    An assignment from `$(...)` under `set -e` must be followed by `|| VAR=$?`
    or `|| true`, or the script dies there with no message.
    """
    unguarded = []
    lines = _SRC.splitlines()
    for i, line in enumerate(lines):
        if not re.match(r"^\s*[A-Z_][A-Z0-9_]*=\$\(", line):
            continue
        # find where this substitution closes
        window = "\n".join(lines[i : i + 40])
        depth, end = 0, None
        for j, ch in enumerate(window):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    end = j
                    break
        tail = window[end : end + 30] if end is not None else ""
        if "||" not in tail and "|| true" not in line and not re.search(r"\|\|", line):
            unguarded.append(line.strip()[:70])
    assert unguarded == [], f"these exit the shell silently on failure: {unguarded}"


def test_the_script_still_parses():
    result = subprocess.run(["bash", "-n", str(_PREFLIGHT)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
