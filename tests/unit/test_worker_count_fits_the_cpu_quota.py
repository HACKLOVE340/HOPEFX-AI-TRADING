# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_worker_count_fits_the_cpu_quota.py
===================================================
``.env.example`` shipped two defaults that contradicted each other, 380 lines
apart::

    line  961:  API_CPUS=1.0      # Docker CPU quota for API container
    line 1342:  API_WORKERS=4

``app.py`` passes ``API_WORKERS`` straight to ``uvicorn.run(workers=...)``, so
the API container ran four worker processes inside a one-CPU quota. Each worker
is a separate copy of the app — measured at 296 MiB resident from imports alone,
before a single model is loaded — and all four race a healthcheck with
``start_period: 60s`` and ``timeout: 10s``.

On a real deployment the app container sat ``Up 20 minutes (unhealthy)``
indefinitely, with uvicorn logging::

    INFO:     Waiting for child process [356]
    INFO:     Child process [356] died

between router-registration lines emitted by the workers still alive — workers
cycling rather than one clean crash, so the container never exited and never
became healthy. ``nginx`` stayed in ``Created`` the whole time, because it waits
on the app being healthy, so nothing was reachable.

The rule is one worker per available CPU. These tests derive both numbers from
the files that set them rather than restating either, so raising one without the
other fails here instead of on a VPS.
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

pytestmark = pytest.mark.unit

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_ENV_EXAMPLE = (_ROOT / ".env.example").read_text()
_COMPOSE_FILES = [
    _ROOT / "docker-compose.yml",
    _ROOT / "deployments/docker-compose.hostinger.yml",
]


def _env_number(name: str) -> float:
    match = re.search(rf"^{name}=([0-9.]+)", _ENV_EXAMPLE, re.MULTILINE)
    assert match, f"{name} is not set in .env.example"
    return float(match.group(1))


def _app_healthcheck(path: pathlib.Path) -> dict:
    spec = yaml.safe_load(path.read_text())
    return ((spec.get("services") or {}).get("app") or {}).get("healthcheck") or {}


def _seconds(value: str | None) -> float | None:
    if not value:
        return None
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([smh]?)", str(value).strip())
    assert match, f"unparsable duration {value!r}"
    return float(match.group(1)) * {"": 1, "s": 1, "m": 60, "h": 3600}[match.group(2)]


# ── Workers vs CPUs ──────────────────────────────────────────────────────────


def test_workers_do_not_exceed_the_cpu_quota():
    """The defect, stated as the rule that was broken."""
    workers = _env_number("API_WORKERS")
    cpus = _env_number("API_CPUS")
    assert workers <= cpus, (
        f"API_WORKERS={workers:g} on API_CPUS={cpus:g}: {workers:g} full copies of the app "
        f"competing for {cpus:g} core(s). Raise API_CPUS with it, or lower the workers."
    )


def test_the_compose_cpu_limit_agrees_with_api_cpus():
    """API_CPUS documents the quota; compose enforces it. If they disagree, the
    check above is measuring the wrong thing."""
    declared = _env_number("API_CPUS")
    spec = yaml.safe_load((_ROOT / "docker-compose.yml").read_text())
    limit = float(spec["services"]["app"]["deploy"]["resources"]["limits"]["cpus"])
    assert limit == declared, f"compose caps the app at {limit} CPU but .env.example says API_CPUS={declared}"


def test_at_least_one_worker_is_configured():
    """Zero would be its own outage."""
    assert _env_number("API_WORKERS") >= 1


def test_app_reads_the_variable_this_test_constrains():
    """If app.py stopped honouring API_WORKERS, this file would be guarding
    nothing."""
    src = (_ROOT / "app.py").read_text()
    assert 'os.getenv("API_WORKERS"' in src
    assert "workers=workers" in src


# ── The healthcheck has to survive a first boot ──────────────────────────────


@pytest.mark.parametrize("path", _COMPOSE_FILES, ids=lambda p: p.name)
def test_start_period_covers_a_first_boot(path):
    """First boot is the slowest: preflight runs 20 alembic migrations before
    `python app.py` starts at all (measured 23s on SQLite at full CPU; postgres
    is capped at 0.5 CPU here), and importing the app costs a further 10.5s.

    60s did not cover that, so a first deploy was declared unhealthy while still
    legitimately starting.
    """
    if not path.exists():
        pytest.skip(f"{path.name} not present")
    start_period = _seconds(_app_healthcheck(path).get("start_period"))
    assert start_period is not None, "the app healthcheck has no start_period"
    assert start_period >= 120, f"{start_period:g}s is too tight for a first boot with migrations"


@pytest.mark.parametrize("path", _COMPOSE_FILES, ids=lambda p: p.name)
def test_the_healthcheck_still_fails_a_genuinely_broken_app(path):
    """Raising start_period must not turn the healthcheck off. Retries and
    interval still have to bound how long a dead app looks alive."""
    if not path.exists():
        pytest.skip(f"{path.name} not present")
    check = _app_healthcheck(path)
    assert int(check.get("retries", 0)) >= 1
    assert _seconds(check.get("interval")) is not None
    assert _seconds(check.get("timeout")) is not None


# ── Both compose files, since production layers them ─────────────────────────


def test_the_overlay_is_covered_too():
    """The VPS runs `-f docker-compose.yml -f deployments/docker-compose.hostinger.yml`.
    Fixing only the base file would leave the deployment unchanged."""
    overlay = _ROOT / "deployments/docker-compose.hostinger.yml"
    if not overlay.exists():
        pytest.skip("overlay not present")
    assert _app_healthcheck(overlay), "the overlay redefines app but has no healthcheck to check"
