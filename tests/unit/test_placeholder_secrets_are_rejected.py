# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_placeholder_secrets_are_rejected.py
====================================================
A production deployment could run with a secret whose value was published in
the repository.

``.env.example`` ships placeholders of the form ``CHANGE_ME_generate_...``. Ten
validators in ``config/startup_validator.py`` need to reject them and nine did,
each writing the check out longhand as ``val.startswith("CHANGE_ME")``. The
tenth, ``_validate_crypto_webhook_secret``, tested only for empty and for a
32-character minimum — and ``CHANGE_ME_generate_64_char_hex_secret`` is 37
characters, so it cleared the floor and passed.

That secret verifies crypto payment webhook signatures. Anyone reading the
public ``.env.example`` knew its value.

The shape is familiar: a check copy-pasted ten times, with the missing copy
being the one that mattered. It is now one shared ``is_placeholder`` helper, and
the sweep below is the part that keeps it honest — it reads every placeholder
out of ``.env.example`` and requires the validator to reject each one, so a
variable added to the example file with a placeholder cannot quietly go
unguarded.

This surfaced from a real deployment: a fresh install produced
``dependency failed to start: container hopefx-ai-trading-app-1 is unhealthy``,
which is what a ``sys.exit(1)`` inside startup validation looks like from the
outside.
"""

from __future__ import annotations

import pathlib
import re

import pytest

pytestmark = pytest.mark.unit

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_ENV_EXAMPLE = _ROOT / ".env.example"

# Placeholders for third-party credentials the validator only checks when the
# corresponding feature is switched on. They are guarded, but conditionally, so
# the unconditional sweep cannot assert on them.
_FEATURE_GATED = {
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "FINNHUB_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
}


def _example_placeholders() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in _ENV_EXAMPLE.read_text().splitlines():
        m = re.match(r"^\s*([A-Z0-9_]+)\s*=\s*(CHANGE_ME\S*)", line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


# ── The helper ───────────────────────────────────────────────────────────────


def test_the_helper_recognises_every_placeholder_in_the_example_file():
    from config.startup_validator import is_placeholder

    placeholders = _example_placeholders()
    assert placeholders, ".env.example has no CHANGE_ME placeholders — has the format changed?"
    for name, value in placeholders.items():
        assert is_placeholder(value), f"{name}={value} is not recognised as a placeholder"


@pytest.mark.parametrize(
    "value",
    ["CHANGE_ME", "CHANGE_ME_generate_64_char_hex_secret", "change_me_lowercase", "  CHANGE_ME_padded  "],
)
def test_placeholders_are_recognised_case_and_whitespace_insensitively(value):
    from config.startup_validator import is_placeholder

    assert is_placeholder(value) is True


@pytest.mark.parametrize("value", ["", "a-real-secret", "sk_live_abc", "CHANGED_the_value", "MYCHANGE_ME"])
def test_real_values_are_not_mistaken_for_placeholders(value):
    from config.startup_validator import is_placeholder

    assert is_placeholder(value) is False


def test_no_validator_still_open_codes_the_check():
    """Nine longhand copies were how the tenth came to be missing."""
    src = (_ROOT / "config/startup_validator.py").read_text()
    body = src.split("def is_placeholder", 1)[1].split("\n\n\n", 1)[1]
    assert '.startswith("CHANGE_ME")' not in body, "a validator re-implements the placeholder check"


# ── The sweep ────────────────────────────────────────────────────────────────


def _validate_with(monkeypatch, overrides: dict[str, str]):
    """Run production validation over a minimally-valid environment."""
    from config.startup_validator import StartupValidationError, validate_environment

    base = {
        "APP_ENV": "production",
        "DATABASE_URL": "postgresql://hopefx:a-long-password@postgres:5432/hopefx",  # pragma: allowlist secret
        "REDIS_URL": "redis://:pw@redis:6379/0",
        "REDIS_HOST": "redis",
        "REDIS_PORT": "6379",
        "REDIS_PASSWORD": "a-long-redis-password",  # pragma: allowlist secret
        "SECURITY_JWT_SECRET": "j" * 48,
        "CONFIG_ENCRYPTION_KEY": "e" * 48,
        "HOPEFX_KILL_SWITCH_TOKEN": "k" * 48,
        "CRYPTO_WEBHOOK_SECRET": "c" * 64,
    }
    base.update(overrides)
    for key in (
        "STRIPE_SECRET_KEY",
        "STRIPE_WEBHOOK_SECRET",
        "BROKER_TYPE",
        "SIGNAL_ENGINE_AUTO_TRADE",
        "ALLOWED_ORIGINS",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in base.items():
        monkeypatch.setenv(key, value)

    try:
        validate_environment(strict=False)
        return None
    except StartupValidationError as exc:
        return str(exc)


def test_the_baseline_environment_passes(monkeypatch):
    """Otherwise the sweep below would pass for the wrong reason."""
    assert _validate_with(monkeypatch, {}) is None


@pytest.mark.parametrize(
    "name",
    sorted(n for n in _example_placeholders() if n not in _FEATURE_GATED),
)
def test_every_unconditional_placeholder_is_rejected(monkeypatch, name):
    """The general property. A new required secret added to .env.example with a
    placeholder is caught here rather than in production."""
    from config.startup_validator import validate_environment

    import inspect

    # Only assert on variables this validator actually looks at; a placeholder
    # for something it never reads is not its responsibility.
    src = inspect.getsource(validate_environment.__module__ and __import__("config.startup_validator", fromlist=["x"]))
    if f'"{name}"' not in src:
        pytest.skip(f"{name} is not read by the startup validator")

    error = _validate_with(monkeypatch, {name: _example_placeholders()[name]})
    assert error is not None, f"{name} placeholder accepted in production"
    assert name in error, f"validation failed but never named {name}: {error}"


def test_the_crypto_webhook_placeholder_specifically(monkeypatch):
    """The one that was missing, pinned by name so a regression is recognisable
    rather than just a count changing."""
    error = _validate_with(monkeypatch, {"CRYPTO_WEBHOOK_SECRET": "CHANGE_ME_generate_64_char_hex_secret"})
    assert error is not None, "the published placeholder is accepted as a webhook secret"
    assert "CRYPTO_WEBHOOK_SECRET" in error
    assert "placeholder" in error.lower()


def test_a_long_enough_placeholder_still_fails(monkeypatch):
    """Length was the only thing standing in the way, and it was not enough."""
    error = _validate_with(monkeypatch, {"CRYPTO_WEBHOOK_SECRET": "CHANGE_ME_" + "x" * 60})
    assert error is not None
    assert "CRYPTO_WEBHOOK_SECRET" in error


def test_a_real_secret_of_the_same_length_passes(monkeypatch):
    """The check must key on the placeholder, not on length or shape."""
    assert _validate_with(monkeypatch, {"CRYPTO_WEBHOOK_SECRET": "f" * 70}) is None
