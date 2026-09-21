# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_preflight_db_password_hint.py
==============================================
The preflight database check answered a password failure with "Check
DATABASE_URL" — pointing at the one thing that was correct.

A real deployment hit this. Startup validation had just been satisfied (all
secrets present, no placeholders), and the next check produced::

    [ 5/9 ] Database
    error: (psycopg2.OperationalError) connection to server at "postgres"
    (172.18.0.2), port 5432 failed: FATAL:  password authentication failed
    for user "hopefx"

DATABASE_URL was correct. Postgres writes its password into the data directory
when it initialises an **empty** volume, and never again. The first deploy had
created the volume with the old password; the secrets were then regenerated;
the app presented the new password to a database still holding the old one.
Nothing in the output suggested the volume, so the advice sent the reader to
the wrong file.

``docker compose ps`` reports postgres as *healthy* throughout, because the
healthcheck is ``pg_isready`` — which tests that the server answers, not that
the credentials work. So the only failing container is the app, and the only
message names DATABASE_URL.

These tests execute the classification the way the script does: they read the
grep pattern out of preflight.sh and run grep against the error text as
captured from the deployment. Asserting on a copy of the pattern would pass
while the script did something else.
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

# Verbatim from the failing deployment.
_PSYCOPG2_ERROR = (
    'error: (psycopg2.OperationalError) connection to server at "postgres" '
    "(172.18.0.2), port 5432 failed: FATAL:  password authentication failed "
    'for user "hopefx"\n'
    "(Background on this error at: https://sqlalche.me/e/20/e3q8)\n"
)

# The async driver this project also uses raises its own wording.
_ASYNCPG_ERROR = 'asyncpg.exceptions.InvalidPasswordError: password authentication failed for user "hopefx"\n'

# A genuinely different failure — must NOT take the password branch.
_UNREACHABLE_ERROR = (
    'error: (psycopg2.OperationalError) connection to server at "postgres" '
    "(172.18.0.2), port 5432 failed: Connection refused\n"
)


def _grep_pattern() -> str:
    """The pattern the script actually greps with."""
    match = re.search(r'grep -qi "([^"]+)" "\$\{DB_ERR_FILE\}"', _SRC)
    assert match, "the password-failure branch is gone from preflight.sh"
    return match.group(1)


def _matches(text: str) -> bool:
    """Run the real grep, the same way the script does."""
    result = subprocess.run(
        ["grep", "-qi", _grep_pattern()],
        input=text,
        text=True,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def test_the_real_deployment_error_is_recognised():
    assert _matches(_PSYCOPG2_ERROR)


def test_the_async_driver_wording_is_recognised():
    """DATABASE_URL uses postgresql+asyncpg in .env.example, so both drivers
    can surface this."""
    assert _matches(_ASYNCPG_ERROR)


def test_an_unreachable_server_is_not_misreported_as_a_password_problem():
    """Connection refused is a different fault with different advice; telling
    someone to recreate their database volume for it would be worse than the
    message this replaces."""
    assert not _matches(_UNREACHABLE_ERROR)


def test_the_hint_names_the_actual_cause():
    """The message has to say 'volume', because that is the thing to act on."""
    branch = _SRC.split("password authentication failed", 1)[1].split("fail ", 1)[0]
    lowered = branch.lower()
    assert "volume" in lowered
    assert "docker volume rm" in lowered
    assert "alter user" in lowered, "the data-preserving path must be offered too"


def test_the_hint_explains_why_postgres_looks_healthy():
    """Otherwise the reader trusts 'healthy' and rules out the database."""
    branch = _SRC.split("password authentication failed", 1)[1].split("fail ", 1)[0]
    assert "pg_isready" in branch


def test_stderr_from_the_probe_is_shown_not_swallowed():
    """Redirecting stderr to a file to inspect it must not hide it — that error
    text is the only evidence of what actually failed."""
    assert 'cat "${DB_ERR_FILE}"' in _SRC


def test_the_generic_message_survives_for_other_failures():
    assert "Database connection failed. Check DATABASE_URL." in _SRC


def test_the_temp_file_is_cleaned_up_on_every_path():
    """fail() exits, so a missed rm leaks a file per failed start."""
    assert _SRC.count('rm -f "${DB_ERR_FILE}"') >= 3


def test_the_script_still_parses():
    """A heredoc plus nested quoting is easy to break, and this file is the
    container entrypoint — a syntax error here fails every start."""
    result = subprocess.run(["bash", "-n", str(_PREFLIGHT)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
