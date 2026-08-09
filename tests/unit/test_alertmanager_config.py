# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_alertmanager_config.py
=======================================
The alerting tier had never started. Not once, in any configuration.

``alertmanager-1`` was sitting in ``Restarting (1)`` on the deployed stack.
Rendering the shipped template and feeding it to a real ``prom/alertmanager
v0.27.0`` binary gives, in order as each is fixed::

    missing service or routing key in PagerDuty config
    field tls_config not found in type config.plain     (telegram_configs)
    field subject not found in type config.plain        (email_configs)
    field body not found in type config.plain           (email_configs)
    missing bot_token or bot_token_file on telegram_config
    missing chat_id on telegram_config
    missing to address in email config

The first is reachable by configuration — ``ALERTMANAGER_PAGERDUTY_KEY`` was
documented as optional, was absent from ``.env.example``, and was not even
passed through in ``docker-compose.yml``, so it was always empty. The last three
are the shipped defaults (empty token, ``chat_id: 0``, empty recipient).

The middle three are not fixable by any operator: ``subject``, ``body`` and a
top-level ``tls_config`` are not fields in alertmanager's schema. The correct
spellings are ``headers.subject``, ``text`` and ``http_config.tls_config``.
Loading the *old* template with every documented secret populated still fails::

    level=error component=configuration msg="Loading configuration file failed"
      err="yaml: unmarshal errors:
        line 94: field tls_config not found in type config.plain
        line 99: field subject not found in type config.plain
        ..."

So Prometheus scraped, the rules in ``monitoring/rules`` evaluated, and every
critical route — drawdown breach, circuit breaker open, P&L reconciliation
failure — fired into a container that was not running. The monitoring stack
looked complete from the outside, which is the only reason it survived this
long.

These tests render the template through the real scripts and validate the
result. When ``amtool`` is on PATH they hand it to alertmanager's own
validator; the structural assertions below encode the errors measured above and
run everywhere.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

_AM_DIR = Path(__file__).resolve().parents[2] / "monitoring" / "alertmanager"
_TMPL = _AM_DIR / "alertmanager.yml.tmpl"
_RENDER = _AM_DIR / "render-config.sh"
_CHANNELS = _AM_DIR / "channels.sh"

_TELEGRAM = {
    "ALERTMANAGER_TELEGRAM_BOT_TOKEN": "123456:fake-bot-token",  # pragma: allowlist secret
    "ALERTMANAGER_TELEGRAM_CHAT_ID": "-1001234567890",
}
_EMAIL = {
    "ALERTMANAGER_SMTP_TO": "ops@example.com",
    "ALERTMANAGER_SMTP_HOST": "smtp.example.com:587",
}
_PAGERDUTY = {"ALERTMANAGER_PAGERDUTY_KEY": "fake-pagerduty-routing-key"}  # pragma: allowlist secret

_ALL_COMBINATIONS = [
    pytest.param({}, id="nothing-configured-the-shipped-default"),
    pytest.param(_EMAIL, id="email-only"),
    pytest.param(_TELEGRAM, id="telegram-only"),
    pytest.param(_PAGERDUTY, id="pagerduty-only"),
    pytest.param({**_TELEGRAM, **_EMAIL}, id="telegram-and-email"),
    pytest.param({**_TELEGRAM, **_EMAIL, **_PAGERDUTY}, id="all-three"),
]


def _render(env: dict[str, str]) -> str:
    """Render through the real script, with only the given ALERTMANAGER_* set."""
    clean = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    clean.update(env)
    result = subprocess.run(
        ["sh", str(_RENDER), str(_TMPL), str(_CHANNELS)],
        capture_output=True,
        text=True,
        env=clean,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, f"render failed: {result.stderr}"
    return result.stdout


def _channels(env: dict[str, str]) -> tuple[str, str, str]:
    clean = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    clean.update(env)
    out = subprocess.run(
        [
            "sh",
            "-c",
            f'. "{_CHANNELS}"; printf "%s|%s|%s" "$HOPEFX_AM_TELEGRAM_ENABLED" '
            '"$HOPEFX_AM_EMAIL_ENABLED" "$HOPEFX_AM_PAGERDUTY_ENABLED"',
        ],
        capture_output=True,
        text=True,
        env=clean,
        timeout=30,
        check=True,
    ).stdout
    tg, em, pd = out.split("|")
    return tg, em, pd


def _integrations(cfg: dict, kind: str) -> list[dict]:
    out: list[dict] = []
    for receiver in cfg.get("receivers", []):
        out.extend(receiver.get(kind, []) or [])
    return out


# ── The config must be loadable in every combination ─────────────────────────


@pytest.mark.parametrize("env", _ALL_COMBINATIONS)
def test_the_rendered_config_is_valid_yaml(env):
    cfg = yaml.safe_load(_render(env))
    assert isinstance(cfg, dict)
    assert cfg["route"]["receiver"] == "email-default"


@pytest.mark.skipif(shutil.which("amtool") is None, reason="amtool not installed")
@pytest.mark.parametrize("env", _ALL_COMBINATIONS)
def test_alertmanagers_own_validator_accepts_it(env, tmp_path):
    """The only assertion that is not a model of alertmanager's rules."""
    path = tmp_path / "alertmanager.yml"
    path.write_text(_render(env))
    result = subprocess.run(
        ["amtool", "check-config", str(path)], capture_output=True, text=True, timeout=60, check=False
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"


# ── No blank credential ever reaches the file ────────────────────────────────


@pytest.mark.parametrize("env", _ALL_COMBINATIONS)
def test_no_integration_carries_a_blank_credential(env):
    """Each of these is a hard startup error in alertmanager, not a warning.
    An unconfigured channel must therefore be absent, never declared empty."""
    cfg = yaml.safe_load(_render(env))

    for tg in _integrations(cfg, "telegram_configs"):
        assert tg.get("bot_token"), "empty bot_token → 'missing bot_token or bot_token_file'"
        assert str(tg.get("chat_id", "0")) != "0", "chat_id 0 → 'missing chat_id on telegram_config'"
    for em in _integrations(cfg, "email_configs"):
        assert em.get("to"), "empty to → 'missing to address in email config'"
    for pd in _integrations(cfg, "pagerduty_configs"):
        assert pd.get("routing_key") or pd.get("service_key"), (
            "empty routing_key → 'missing service or routing key in PagerDuty config'"
        )


def test_the_shipped_default_declares_no_integrations_at_all(monkeypatch):
    """With no secrets set the stack must still come up. A receiver with zero
    integrations is valid; a receiver full of empty strings is not."""
    cfg = yaml.safe_load(_render({}))
    names = {r["name"] for r in cfg["receivers"]}
    assert names == {"critical", "email-default"}, "routes reference receivers that must exist"
    for kind in ("telegram_configs", "email_configs", "pagerduty_configs"):
        assert _integrations(cfg, kind) == [], f"{kind} present with nothing configured"


# ── Field names that no operator could have fixed ────────────────────────────


@pytest.mark.parametrize("env", _ALL_COMBINATIONS)
def test_email_uses_headers_and_text_not_subject_and_body(env):
    """``subject:`` and ``body:`` are not fields in ``config.plain``. They read
    as perfectly sensible YAML, which is why they survived: nothing about the
    file looks wrong until alertmanager unmarshals it."""
    cfg = yaml.safe_load(_render(env))
    for em in _integrations(cfg, "email_configs"):
        assert "subject" not in em, "field subject not found in type config.plain"
        assert "body" not in em, "field body not found in type config.plain"
        assert em.get("headers", {}).get("subject"), "the subject must move into headers"
        assert em.get("text") or em.get("html"), "the body must move into text (or html)"


@pytest.mark.parametrize("env", _ALL_COMBINATIONS)
def test_telegram_tls_config_is_nested_under_http_config(env):
    cfg = yaml.safe_load(_render(env))
    for tg in _integrations(cfg, "telegram_configs"):
        assert "tls_config" not in tg, "field tls_config not found in type config.plain"
        assert tg["http_config"]["tls_config"]["insecure_skip_verify"] is False


# ── Channel gating ───────────────────────────────────────────────────────────


def test_each_channel_appears_only_when_fully_configured():
    assert _channels({}) == ("", "", "")
    assert _channels(_TELEGRAM) == ("1", "", "")
    assert _channels(_EMAIL) == ("", "1", "")
    assert _channels(_PAGERDUTY) == ("", "", "1")
    assert _channels({**_TELEGRAM, **_EMAIL, **_PAGERDUTY}) == ("1", "1", "1")


def test_a_bot_token_without_a_chat_id_disables_telegram():
    """chat_id 0 is the compose default, and it is a startup error. Half-
    configured must mean off, not broken."""
    tg, _, _ = _channels({"ALERTMANAGER_TELEGRAM_BOT_TOKEN": "tok"})
    assert tg == ""
    tg, _, _ = _channels({"ALERTMANAGER_TELEGRAM_BOT_TOKEN": "tok", "ALERTMANAGER_TELEGRAM_CHAT_ID": "0"})
    assert tg == ""


def test_a_recipient_without_a_relay_disables_email():
    _, em, _ = _channels({"ALERTMANAGER_SMTP_TO": "ops@example.com"})
    assert em == ""


def test_configured_channels_carry_the_real_values_through():
    cfg = yaml.safe_load(_render({**_TELEGRAM, **_EMAIL, **_PAGERDUTY}))
    tg = _integrations(cfg, "telegram_configs")[0]
    assert tg["bot_token"] == _TELEGRAM["ALERTMANAGER_TELEGRAM_BOT_TOKEN"]
    assert str(tg["chat_id"]) == _TELEGRAM["ALERTMANAGER_TELEGRAM_CHAT_ID"]
    assert _integrations(cfg, "email_configs")[0]["to"] == _EMAIL["ALERTMANAGER_SMTP_TO"]
    assert _integrations(cfg, "pagerduty_configs")[0]["routing_key"] == _PAGERDUTY["ALERTMANAGER_PAGERDUTY_KEY"]
    assert cfg["global"]["smtp_smarthost"] == _EMAIL["ALERTMANAGER_SMTP_HOST"]


# ── The rendering must stay incapable of executing the template ──────────────


def test_a_dollar_sign_in_a_comment_cannot_break_startup(tmp_path):
    """The reason substitution uses awk and not `eval`. Two comment lines
    documenting P&L thresholds as "> $5" and "$1-$5" once crash-looped this
    container with ``eval: 5: parameter not set``."""
    tmpl = tmp_path / "t.tmpl"
    tmpl.write_text(
        "# divergence over $5 USD, warning band $1-$5\n"
        "# an apostrophe won't hurt; `backticks` and $(subshells) are inert\n"
        "route:\n  receiver: '${MISSING:-fallback}'\n"
    )
    out = subprocess.run(
        ["sh", str(_RENDER), str(tmpl), str(_CHANNELS)],
        capture_output=True,
        text=True,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
        timeout=30,
        check=False,
    )
    assert out.returncode == 0, out.stderr
    assert "$5" in out.stdout and "$1-$5" in out.stdout, "literal dollars must survive verbatim"
    assert "$(subshells)" in out.stdout, "no command substitution may occur"
    assert yaml.safe_load(out.stdout)["route"]["receiver"] == "fallback"


# ── Deployment plumbing ──────────────────────────────────────────────────────


def test_pagerduty_key_is_actually_passed_to_the_container():
    """It was referenced by the template and named nowhere else — not in
    docker-compose.yml's environment block, not in .env.example. Setting it was
    impossible, and leaving it unset made the config invalid."""
    compose = (Path(__file__).resolve().parents[2] / "docker-compose.yml").read_text()
    assert "ALERTMANAGER_PAGERDUTY_KEY" in compose
    env_example = (Path(__file__).resolve().parents[2] / ".env.example").read_text()
    assert "ALERTMANAGER_PAGERDUTY_KEY" in env_example


def test_every_script_the_image_needs_is_copied_into_it():
    dockerfile = (_AM_DIR / "Dockerfile").read_text()
    for script in ("entrypoint.sh", "render-config.sh", "channels.sh"):
        assert script in dockerfile, f"{script} is used at runtime but never COPYed"
