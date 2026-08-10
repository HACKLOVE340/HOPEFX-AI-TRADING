# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_diagnose_deploy_report.py
==========================================
``scripts/diagnose_deploy.sh`` exists because one error string covers a dozen
causes.

The app container runs ``preflight.sh && python app.py`` behind a healthcheck,
and every other service waits on it with ``depends_on: service_healthy``. A bad
env value, a rejected database password, a blocked migration, an OOM kill and a
crash during startup all surface as::

    dependency failed to start: container hopefx-ai-trading-app-1 is unhealthy

The evidence that separates them is spread across ``docker compose ps``,
``docker inspect`` (exit code and OOMKilled), the app log, ``pg_stat_activity``
and the host's free memory. Diagnosing a deployment one round-trip at a time,
guessing which of those to ask for next, is what made a single-day problem last
a day.

The property worth testing is that the report is **safe to paste**. It reads
``.env`` — the file holding every secret in the deployment — so a careless line
would turn a diagnostic into a disclosure. It must report names and counts, and
never a value.
"""

from __future__ import annotations

import pathlib
import re
import subprocess

import pytest

pytestmark = pytest.mark.unit

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts/diagnose_deploy.sh"


def _run() -> str:
    """Run the real script. Docker probes degrade gracefully when absent."""
    result = subprocess.run(
        ["bash", str(_SCRIPT)],
        capture_output=True,
        text=True,
        cwd=_ROOT,
        timeout=180,
        check=False,
    )
    return result.stdout + result.stderr


@pytest.fixture(scope="module")
def report() -> str:
    return _run()


def _env_secrets() -> dict[str, str]:
    """Values from the real .env long enough to be secrets."""
    env_path = _ROOT / ".env"
    if not env_path.exists():
        return {}
    out: dict[str, str] = {}
    for line in env_path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, _, value = stripped.partition("=")
        value = re.sub(r"\s+#.*$", "", value).strip()
        # Long enough to be a secret, and not a value so common that finding it
        # in prose would be a false positive.
        if len(value) >= 16 and value.lower() not in ("localhost", "development", "production"):
            out[name.strip()] = value
    return out


# ── Safe to paste ────────────────────────────────────────────────────────────


def test_no_secret_value_appears_in_the_report(report):
    """The report is meant to be pasted into a chat or an issue.

    It reads .env, so this is the difference between a diagnostic and a
    disclosure.
    """
    secrets = _env_secrets()
    if not secrets:
        pytest.skip("no .env present to leak from")
    leaked = [name for name, value in secrets.items() if value in report]
    assert leaked == [], f"these values were printed: {leaked}"


def test_it_reports_variable_names_so_it_is_still_useful(report):
    """Redacting everything would be safe and worthless."""
    assert "SECURITY_JWT_SECRET" in report
    assert "POSTGRES_PASSWORD" in report


def test_it_says_the_report_carries_no_secrets(report):
    """So the reader knows it can be shared without re-reading every line."""
    assert "Secrets are not included" in report


# ── The checks that matter ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "needle",
    [
        "CHANGE_ME",  # placeholders never replaced
        "really comments",  # NAME=   # comment shipping the comment as a value
        "POSTGRES_PASSWORD / DB_PASSWORD / DATABASE_URL",  # the three that must agree
        "BOOTSTRAP_SUPERADMIN_EMAIL",  # absent from .env.example until recently
    ],
)
def test_it_checks_each_failure_this_deployment_actually_hit(report, needle):
    assert needle in report


def test_it_explains_the_env_file_versus_flag_distinction():
    """The mistake that made three rounds of corrected secrets land nowhere."""
    src = _SCRIPT.read_text()
    assert "--env-file" in src
    assert "env_file" in src


def test_it_surfaces_oom_and_exit_code():
    """An OOM kill and a refused start are different problems with the same
    external symptom; the exit code separates them.

    Asserted against the source rather than a run, because these lines only
    appear when a container exists — and the test host has no daemon.
    """
    src = _SCRIPT.read_text()
    assert "OOMKilled" in src
    assert "exitCode" in src
    assert "137" in src, "the exit code for a killed container should be spelled out"


def test_it_looks_for_lock_waits(report):
    """A migration blocked on a lock is the one failure that produces no error
    at all — the deploy simply stops."""
    assert "pg_stat_activity" in report or "Lock" in report


# ── It must not fall over ────────────────────────────────────────────────────


def test_it_parses():
    result = subprocess.run(["bash", "-n", str(_SCRIPT)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_it_completes_even_with_no_docker_daemon(report):
    """Run on a box where the stack is down, it must still report on .env —
    which is exactly the case where .env is the likely problem."""
    assert "5. environment" in report
    assert "end" in report


def test_no_probe_can_abort_the_report():
    """`set -e` would stop at the first failing probe and hide everything after
    it, which on a broken host is most of the report."""
    src = _SCRIPT.read_text()
    assert re.search(r"^set -uo pipefail", src, re.MULTILINE), "must not use -e"


# ── Stale containers (the `restart` trap) ────────────────────────────────────


def test_it_compares_the_running_config_against_the_current_one():
    """`docker compose up -d` recreates when .env changes — the resolved service
    config hash moves with it, verified against two generated .env files.

    `docker compose restart` does not: it reuses the same container with the
    environment it was created with. Regenerate secrets, restart, and every
    value the app sees is the old one, with nothing reporting a problem.
    Compose labels each container with the hash it was created from, so the
    two can be compared.
    """
    src = _SCRIPT.read_text()
    assert "com.docker.compose.config-hash" in src
    assert "config --hash" in src
    assert "force-recreate" in src, "must give the command that fixes it"


def test_the_stale_check_appears_before_the_log_sections(report):
    """A stale container makes the log tail misleading — it is evidence about
    an older configuration — so this has to be read first."""
    assert report.index("2b. running config") < report.index("3. preflight progress")


# ── prop_firm_mode.json is tracked, whatever it used to claim ────────────────


def test_prop_firm_config_does_not_claim_to_be_gitignored():
    """It is committed deliberately (.gitignore says so) with placeholder
    credentials for CI. Its own _comment said "This file is gitignored", which
    invites typing real credentials into a tracked file.
    """
    import json

    config = json.loads((_ROOT / "prop_firm_mode.json").read_text())
    comment = config.get("_comment", "").lower()
    assert "not" in comment and "gitignore" in comment, f"still misleading: {comment!r}"


def test_prop_firm_config_carries_no_real_credentials():
    """The placeholders are the point — this file is in the repository."""
    import json
    import re

    config = json.loads((_ROOT / "prop_firm_mode.json").read_text())
    for key in ("telegram_token", "telegram_chat_id"):
        value = str(config.get(key, ""))
        assert not value or re.match(r"^CHANGE_ME", value), f"{key} looks like a real credential"
