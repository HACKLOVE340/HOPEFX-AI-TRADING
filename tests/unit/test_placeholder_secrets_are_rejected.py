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

# There is deliberately no exemption set here.
#
# There used to be one -- five third-party credentials described as "guarded,
# but conditionally, so the unconditional sweep cannot assert on them". Not one
# of the five appears in `.env.example` with a CHANGE_ME placeholder, so the set
# excluded nothing and had never excluded anything. It read as a considered
# carve-out while doing nothing at all (F99).
#
# The validator now carries the classification instead, where a reviewer reading
# the validator can see it: `PLACEHOLDER_GUARDED` (rejected when set) and
# `PLACEHOLDER_NOT_A_SECRET` (declared harmless, with a reason). The sweep below
# requires every placeholder in `.env.example` to be in one or the other.


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


@pytest.mark.parametrize("name", sorted(_example_placeholders()))
def test_every_placeholder_is_rejected(monkeypatch, name):
    """The general property. A new secret added to .env.example with a
    placeholder is caught here rather than in production.

    This test used to end with::

        if f'"{name}"' not in src:
            pytest.skip(f"{name} is not read by the startup validator")

    which skipped when the validator did not mention the variable -- that is,
    it skipped in exactly the situation it existed to detect. A secret is
    unguarded *because* nobody wrote a validator for it, so the one condition
    that should have failed the test was the one that silenced it. Eight of the
    fourteen placeholders in `.env.example` were skipping, among them
    `DB_ENCRYPTION_KEY` and `BOOTSTRAP_SUPERADMIN_PASSWORD` (F99).

    A placeholder that is genuinely not a secret goes in
    `PLACEHOLDER_NOT_A_SECRET` with a reason, which is a decision on the record.
    Silence is not an option any more.
    """
    from config.startup_validator import PLACEHOLDER_NOT_A_SECRET

    if name in PLACEHOLDER_NOT_A_SECRET:
        pytest.skip(f"{name}: declared not a secret -- {PLACEHOLDER_NOT_A_SECRET[name]}")

    error = _validate_with(monkeypatch, {name: _example_placeholders()[name]})
    assert error is not None, (
        f"{name} placeholder accepted in production. Either add it to "
        "config.startup_validator.PLACEHOLDER_GUARDED, or declare it in "
        "PLACEHOLDER_NOT_A_SECRET with a reason."
    )
    assert name in error, f"validation failed but never named {name}: {error}"


def test_nothing_is_exempt_without_a_stated_reason():
    """An exemption with an empty reason is the dead _FEATURE_GATED set coming
    back under a new name."""
    from config.startup_validator import PLACEHOLDER_NOT_A_SECRET

    for name, reason in PLACEHOLDER_NOT_A_SECRET.items():
        assert reason.strip(), f"{name} is exempt with no reason given"


def test_the_sweep_still_covers_a_meaningful_number_of_variables():
    """Guards the sweep against being narrowed to nothing -- the failure mode
    the skip produced was invisible precisely because the test still passed."""
    from config.startup_validator import PLACEHOLDER_NOT_A_SECRET

    asserted = [n for n in _example_placeholders() if n not in PLACEHOLDER_NOT_A_SECRET]
    assert len(asserted) >= 14, f"the sweep asserts on only {len(asserted)} placeholders; it covered 14 when written"


def test_the_previously_skipped_secrets_are_named_explicitly():
    """The eight that were skipping, pinned by name. A count alone would let a
    regression hide behind a different variable taking the same slot."""
    from config.startup_validator import PLACEHOLDER_GUARDED

    for name in (
        "DB_ENCRYPTION_KEY",
        "BOOTSTRAP_SUPERADMIN_PASSWORD",
        "BOOTSTRAP_ADMIN_PASSWORD",
        "BOOTSTRAP_TRADER_PASSWORD",
        "POSTGRES_PASSWORD",
        "GRAFANA_ADMIN_PASSWORD",
        "BYBIT_API_KEY",
        "BYBIT_API_SECRET",
    ):
        assert name in PLACEHOLDER_GUARDED, f"{name} is unguarded again"


def test_a_guarded_variable_that_is_unset_does_not_block_startup(monkeypatch):
    """The sweep is presence-conditional on purpose: covering a credential must
    not force every deployment to configure a feature it does not use."""
    assert _validate_with(monkeypatch, {}) is None


def test_a_real_value_for_a_guarded_variable_passes(monkeypatch):
    """The check keys on the placeholder, not on the variable being set."""
    # Not a credential: a literal chosen to be obviously non-secret, standing in
    # for one so the guard can be shown to pass a real value.
    fake_key = "a-real-exchange-key"  # pragma: allowlist secret
    assert _validate_with(monkeypatch, {"BYBIT_API_KEY": fake_key}) is None


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


# ── The one that was not merely unguarded ────────────────────────────────────
#
# The other seven previously-skipped placeholders are credentials: a published
# value is a weak secret. DB_ENCRYPTION_KEY was different in kind, because
# database/encryption.py treats an unloadable key as its documented dev/CI
# fallback and writes plaintext.


def test_the_db_encryption_placeholder_does_not_decode(monkeypatch):
    """Establish the mechanism before asserting on the fix, so the test cannot
    pass for an unrelated reason."""
    import base64
    import binascii

    with pytest.raises(binascii.Error):
        base64.urlsafe_b64decode("CHANGE_ME_generate_32byte_urlsafe_b64_key" + "==")


def test_an_unloadable_db_encryption_key_is_refused_at_startup(monkeypatch):
    """Not valid base64 -> `_load_key` logs and returns None -> every
    EncryptedString column is written in the clear, and the application starts
    normally. Silent plaintext is not an acceptable response to a
    misconfiguration in production, so it has to fail the boot instead."""
    error = _validate_with(monkeypatch, {"DB_ENCRYPTION_KEY": "not!!valid!!base64"})
    assert error is not None, "an unusable DB_ENCRYPTION_KEY starts the app with encryption off"
    assert "DB_ENCRYPTION_KEY" in error


def test_a_wrong_length_db_encryption_key_is_refused_at_startup(monkeypatch):
    """Decodes cleanly, wrong size: `_load_key`'s other silent-None path."""
    import base64

    sixteen = base64.urlsafe_b64encode(b"x" * 16).decode()
    error = _validate_with(monkeypatch, {"DB_ENCRYPTION_KEY": sixteen})
    assert error is not None, "a 16-byte DB_ENCRYPTION_KEY starts the app with encryption off"
    assert "DB_ENCRYPTION_KEY" in error


def test_a_valid_db_encryption_key_passes(monkeypatch):
    import base64
    import os

    good = base64.urlsafe_b64encode(os.urandom(32)).decode()
    assert _validate_with(monkeypatch, {"DB_ENCRYPTION_KEY": good}) is None


def test_an_absent_db_encryption_key_still_passes(monkeypatch):
    """The dev/CI plaintext fallback is deliberate and documented. Only a key
    that is present and unusable is a misconfiguration."""
    monkeypatch.delenv("DB_ENCRYPTION_KEY", raising=False)
    assert _validate_with(monkeypatch, {}) is None


def test_the_bootstrap_password_floor_is_not_what_guards_it(monkeypatch):
    """scripts/bootstrap_prod.py requires >= 12 characters. The published
    placeholder is 45, so the floor passed it -- the same way the webhook
    secret's 32-character floor passed a 37-character placeholder. Length was
    never the property being checked."""
    placeholder = _example_placeholders()["BOOTSTRAP_SUPERADMIN_PASSWORD"]
    assert len(placeholder) >= 12, "the placeholder no longer clears the floor; rewrite this test"
    error = _validate_with(monkeypatch, {"BOOTSTRAP_SUPERADMIN_PASSWORD": placeholder})
    assert error is not None, "the superadmin can be seeded with a password published in the repo"
