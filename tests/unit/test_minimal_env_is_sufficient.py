# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_minimal_env_is_sufficient.py
=============================================
``.env.example`` is ~900 lines. A control-panel environment editor takes one
Name/Value pair per row, and pasting the file into one produced rows literally
named ``#``, ``# REDIS_SENTINEL_HOSTS`` and ``# VITE_API_URL`` — every comment
line imported as a variable — alongside secrets still reading ``CHANGE_ME``.

``--minimal`` emits the ~28 variables a production deployment actually
requires. The number is only trustworthy if it is measured, so:

* ``test_the_minimal_set_passes_strict_production_validation`` sets exactly
  those variables and nothing else, then runs the real
  ``validate_environment(strict=True)`` — the check the container performs.
* ``test_it_covers_every_variable_compose_hard_requires`` parses
  docker-compose.yml for ``${VAR:?...}`` interpolations, which abort
  ``docker compose up`` before a container starts, and requires each to be
  present. That list is derived from the file rather than restated here, so a
  new hard-required variable fails this test instead of a deploy.

It also carries ``BOOTSTRAP_SUPERADMIN_EMAIL``, which ``.env.example`` never
declared. ``scripts/bootstrap_prod.py`` — the documented final step of a
deploy — reads it and exits(1) when empty, with "Set it in .env before running
this script". The template named the three accounts by address in a comment
block and declared no variable for any of them, so following that instruction
was impossible: the password shipped and the address it belongs to did not.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re

import pytest

pytestmark = pytest.mark.unit

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_TEMPLATE = (_ROOT / ".env.example").read_text()
_DOMAIN = "hopefx.example.com"


def _module():
    spec = importlib.util.spec_from_file_location("_bootstrap_env", _ROOT / "scripts/bootstrap_env.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


@pytest.fixture(scope="module")
def minimal() -> dict[str, str]:
    text, _ = _module().generate(_TEMPLATE, _DOMAIN, keep_comments=False, minimal=True)
    out: dict[str, str] = {}
    for line in text.splitlines():
        name, _, value = line.partition("=")
        out[name] = value
    return out


# ── Sufficiency ──────────────────────────────────────────────────────────────


def test_the_minimal_set_passes_strict_production_validation(monkeypatch, minimal):
    """Exactly these variables and nothing else. If this passes, the list is
    genuinely sufficient rather than merely short."""
    import os

    from config.startup_validator import StartupValidationError, validate_environment

    for key in list(os.environ):
        if key != "PATH":
            monkeypatch.delenv(key, raising=False)
    for key, value in minimal.items():
        monkeypatch.setenv(key, value)

    try:
        validate_environment(strict=True)
    except StartupValidationError as exc:
        pytest.fail(f"the minimal set does not start in production:\n{exc}")


def test_it_covers_every_variable_compose_hard_requires(minimal):
    """``${VAR:?msg}`` aborts `docker compose up` before any container starts.

    Derived from docker-compose.yml so a newly added one fails here.
    """
    compose = (_ROOT / "docker-compose.yml").read_text()
    required = set(re.findall(r"\$\{([A-Z0-9_]+):\?", compose))
    assert required, "no ${VAR:?} interpolations found — has the compose file changed shape?"
    assert required <= set(minimal), f"minimal env omits compose-required: {sorted(required - set(minimal))}"


def test_every_value_is_populated(minimal):
    """A name with an empty value is the same failure as a missing name, and
    reads as configured in a control panel."""
    empty = [k for k, v in minimal.items() if not v.strip()]
    assert empty == [], f"emitted with no value: {empty}"


def test_nothing_reads_change_me(minimal):
    assert [k for k, v in minimal.items() if "CHANGE_ME" in v] == []


# ── The shape a control panel can consume ────────────────────────────────────


def test_output_is_only_name_value_lines():
    """The panel imported every comment line as a variable named '#'."""
    text, _ = _module().generate(_TEMPLATE, _DOMAIN, keep_comments=False, minimal=True)
    for line in text.splitlines():
        assert re.fullmatch(r"[A-Z0-9_]+=.*", line), f"not a bare assignment: {line!r}"


def test_it_is_short_enough_to_paste(minimal):
    """The point of the mode. If this grows past ~40 the panel is unusable
    again and the list needs re-examining rather than the test relaxing."""
    assert len(minimal) <= 40, f"{len(minimal)} variables is too many to enter by hand"


# ── The relationships still hold in this mode ────────────────────────────────


def test_the_database_password_is_consistent(minimal):
    embedded = re.search(r"postgresql(?:\+\w+)?://[^:]+:([^@]+)@", minimal["DATABASE_URL"])
    assert embedded
    assert embedded.group(1) == minimal["POSTGRES_PASSWORD"] == minimal["DB_PASSWORD"]


def test_the_redis_password_is_consistent(minimal):
    embedded = re.search(r"redis://:([^@]+)@", minimal["REDIS_URL"])
    assert embedded
    assert embedded.group(1) == minimal["REDIS_PASSWORD"]


def test_independent_secrets_stay_independent(minimal):
    assert minimal["SECURITY_JWT_SECRET"] != minimal["CRYPTO_WEBHOOK_SECRET"]


def test_the_domain_is_applied(minimal):
    assert minimal["HOPEFX_DOMAIN"] == _DOMAIN
    assert "YOUR_DOMAIN" not in "\n".join(minimal.values())


# ── The undeclared bootstrap addresses ───────────────────────────────────────


def test_the_superadmin_email_is_emitted(minimal):
    """bootstrap_prod.py exits(1) without it, telling the operator to set it in
    a file that never had the variable."""
    assert minimal.get("BOOTSTRAP_SUPERADMIN_EMAIL"), "the documented seed step cannot run without this"
    assert "@" in minimal["BOOTSTRAP_SUPERADMIN_EMAIL"]


def test_the_addresses_match_the_ones_dev_seeds():
    """Two bootstrap paths seeding different accounts would be its own defect."""
    dev = (_ROOT / "scripts/bootstrap_dev.py").read_text()
    additions = _module()._ADDITIONS
    for name, address in additions.items():
        role = name.replace("BOOTSTRAP_", "").replace("_EMAIL", "").lower()
        assert f'"{address}"' in dev, f"{address} is not what bootstrap_dev.py seeds for {role}"


def test_every_bootstrap_password_has_a_matching_address(minimal):
    passwords = {k for k in minimal if k.endswith("_PASSWORD") and k.startswith("BOOTSTRAP_")}
    for password in passwords:
        assert password.replace("_PASSWORD", "_EMAIL") in minimal, f"{password} has no address to go with it"


# ── Drift ────────────────────────────────────────────────────────────────────


def test_minimal_names_only_variables_the_generator_produces():
    """A typo in _MINIMAL would silently drop a required variable."""
    module = _module()
    full, _ = module.generate(_TEMPLATE, _DOMAIN, keep_comments=False)
    produced = {line.split("=", 1)[0] for line in full.splitlines() if "=" in line}
    unknown = [n for n in module._MINIMAL if n not in produced]
    assert unknown == [], f"_MINIMAL names variables nothing produces: {unknown}"


def test_a_minimal_entry_the_template_lost_is_a_hard_error():
    """Delete a required line from the real template and generation must stop.

    The alternative — emitting a list quietly missing one variable — is the
    original failure mode wearing a different hat: an environment that looks
    complete and fails at container start.
    """
    module = _module()
    dropped = "HOPEFX_DOMAIN"
    crippled = "\n".join(line for line in _TEMPLATE.splitlines() if not re.match(rf"^\s*{dropped}\s*=", line))

    with pytest.raises(module.GenerationError) as excinfo:
        module.generate(crippled, _DOMAIN, minimal=True)
    message = str(excinfo.value)
    assert "_MINIMAL" in message
    assert dropped in message, f"the error must name what went missing: {message}"
