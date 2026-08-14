"""
tests/unit/test_nginx_is_not_started_by_default.py
==================================================
A container audit of the production VPS reported::

    hopefx-ai-trading-nginx-1   Created

Created, never Running, no restart loop and no logs — which reads as "the
reverse proxy and frontend entry point is unavailable". It was not: Traefik on
the host network was serving the site the whole time.

The compose `nginx` service binds host ports 80 and 443. On a host that already
runs a proxy there — Traefik in `network_mode: host`, which is the production
setup — the bind fails and the container never leaves `Created`.

The workaround in circulation was to pass `--scale nginx=0` on every
`docker compose up`. That is folklore, not configuration: it lives in a runbook
and in whoever's shell history, and forgetting it once produces a container that
cannot start. The service is now behind the `standalone-proxy` profile, so the
default `docker compose up -d` skips it and the rule lives in the file.

These tests parse the compose file rather than grepping it, so a reformat or a
comment mentioning the profile cannot make them pass.
"""

from __future__ import annotations

import pathlib

import pytest

yaml = pytest.importorskip("yaml")

ROOT = pathlib.Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker-compose.yml"

_PROFILE = "standalone-proxy"


@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def test_nginx_is_behind_a_profile(compose):
    nginx = compose["services"]["nginx"]
    assert nginx.get("profiles") == [_PROFILE], (
        "nginx must be profile-gated. Without it, `docker compose up -d` creates a "
        "container that cannot bind 80/443 on a host already running a proxy, and "
        "it sits in `Created` looking like an outage."
    )


def test_no_other_service_is_accidentally_gated(compose):
    """A profile on `app` or `postgres` would silently stop the stack starting."""
    gated = {name: svc.get("profiles") for name, svc in compose["services"].items() if svc.get("profiles")}
    assert gated == {"nginx": [_PROFILE]}, f"unexpected profile-gated services: {gated}"


def test_nginx_is_the_only_service_claiming_ports_80_and_443(compose):
    """If a second service grabbed them, gating nginx would not fix the clash."""
    claimants = []
    for name, svc in compose["services"].items():
        for mapping in svc.get("ports", []) or []:
            host_port = str(mapping).split(":")[0].strip('"')
            if host_port in ("80", "443"):
                claimants.append(name)
    assert set(claimants) == {"nginx"}, f"services binding 80/443: {sorted(set(claimants))}"


def test_the_app_still_publishes_its_own_port(compose):
    """The host proxy routes to it directly, so this must not be gated away."""
    published = [str(p) for p in (compose["services"]["app"].get("ports") or [])]
    assert any("8000" in p for p in published), f"app ports: {published}"
    assert not compose["services"]["app"].get("profiles")


def test_the_runbook_no_longer_teaches_the_scale_workaround():
    """The flag was the thing being forgotten; it must stop being prescribed."""
    runbook = (ROOT / "docs/UPDATE_RUNBOOK.md").read_text(encoding="utf-8")

    # Command lines only — the note explaining that the flag is obsolete
    # legitimately contains the string, and matching prose is how five earlier
    # tests in this repo passed for the wrong reason.
    commands = [line for line in runbook.splitlines() if line.strip().startswith("docker compose")]
    offenders = [line for line in commands if "--scale nginx=0" in line]
    assert offenders == [], f"runbook still prescribes the workaround: {offenders}"

    assert "--profile standalone-proxy" in runbook, (
        "the runbook must say how to start nginx deliberately, or the service "
        "becomes unreachable rather than merely opt-in"
    )
