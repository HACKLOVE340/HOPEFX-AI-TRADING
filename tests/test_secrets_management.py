# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/test_secrets_management.py
=================================
Verifies the production secrets management script:
  1. generate writes secrets to .env (never overwrites real values)
  2. validate returns 0 when all secrets are set, 1 when missing
  3. rotate replaces a specific key
  4. audit detects hardcoded secrets in source files
  5. check-env detects missing keys
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.manage_secrets import (
    REQUIRED_SECRETS,
    _generate,
    _is_placeholder,
    _load_env,
    _write_env,
    cmd_audit,
    cmd_check_env,
    cmd_generate,
    cmd_rotate,
    cmd_validate,
)

# ── unit: helpers ─────────────────────────────────────────────────────────────


def test_generate_token48_length():
    val = _generate("token48")
    # base64url: 48 bytes → 64 chars
    assert len(val) >= 60


def test_generate_token32_length():
    val = _generate("token32")
    assert len(val) >= 40


def test_is_placeholder_detects_change_me():  # healer: ignore
    assert _is_placeholder("CHANGE_ME_generate_a_random_48_char_secret")  # healer: ignore


def test_is_placeholder_detects_empty():
    assert _is_placeholder("")


def test_is_placeholder_passes_real_secret():
    real = _generate("token48")
    assert not _is_placeholder(real)


def test_load_env_parses_correctly(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("FOO=bar\n# comment\nBAZ=qux\n\nEMPTY=\n")
    result = _load_env(env_file)
    assert result["FOO"] == "bar"
    assert result["BAZ"] == "qux"
    assert result["EMPTY"] == ""
    assert "comment" not in result


def test_write_env_updates_existing_key(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("FOO=old\nBAR=keep\n")
    _write_env(env_file, {"FOO": "new", "BAR": "keep"})
    result = _load_env(env_file)
    assert result["FOO"] == "new"
    assert result["BAR"] == "keep"


def test_write_env_appends_new_key(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("FOO=bar\n")
    _write_env(env_file, {"FOO": "bar", "NEW_KEY": "value"})
    result = _load_env(env_file)
    assert result["NEW_KEY"] == "value"


# ── integration: generate command ─────────────────────────────────────────────


class _FakeArgs:
    key = None


def test_generate_writes_all_required_secrets(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("")
    monkeypatch.setattr("scripts.manage_secrets.ENV_FILE", env_file)

    rc = cmd_generate(_FakeArgs())
    assert rc == 0

    result = _load_env(env_file)
    for var, _, _ in REQUIRED_SECRETS:
        assert var in result, f"{var} not written"
        assert not _is_placeholder(result[var]), f"{var} is still a placeholder"


def test_generate_does_not_overwrite_real_value(tmp_path, monkeypatch):
    real_secret = _generate("token48")
    env_file = tmp_path / ".env"
    env_file.write_text(f"SECURITY_JWT_SECRET={real_secret}\n")
    monkeypatch.setattr("scripts.manage_secrets.ENV_FILE", env_file)

    cmd_generate(_FakeArgs())

    result = _load_env(env_file)
    assert result["SECURITY_JWT_SECRET"] == real_secret


# ── integration: validate command ─────────────────────────────────────────────


def test_validate_passes_when_all_set(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    lines = [f"{var}={_generate('token48')}" for var, _, _ in REQUIRED_SECRETS]
    env_file.write_text("\n".join(lines) + "\n")
    monkeypatch.setattr("scripts.manage_secrets.ENV_FILE", env_file)
    # Remove all required secrets from the process env so cmd_validate reads
    # only from the temp file (conftest.py sets SECURITY_JWT_SECRET globally).
    for var, _, _ in REQUIRED_SECRETS:
        monkeypatch.delenv(var, raising=False)

    rc = cmd_validate(_FakeArgs())
    assert rc == 0


def test_validate_fails_when_placeholder(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("SECURITY_JWT_SECRET=CHANGE_ME_generate_a_random_48_char_secret\n")  # pragma: allowlist secret  # healer: ignore
    monkeypatch.setattr("scripts.manage_secrets.ENV_FILE", env_file)

    rc = cmd_validate(_FakeArgs())
    assert rc == 1


def test_validate_fails_when_missing(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("")
    monkeypatch.setattr("scripts.manage_secrets.ENV_FILE", env_file)

    rc = cmd_validate(_FakeArgs())
    assert rc == 1


# ── integration: rotate command ───────────────────────────────────────────────


def test_rotate_replaces_key(tmp_path, monkeypatch):
    old_val = _generate("token48")
    env_file = tmp_path / ".env"
    env_file.write_text(f"SECURITY_JWT_SECRET={old_val}\n")
    monkeypatch.setattr("scripts.manage_secrets.ENV_FILE", env_file)

    args = _FakeArgs()
    args.key = "SECURITY_JWT_SECRET"
    rc = cmd_rotate(args)
    assert rc == 0

    result = _load_env(env_file)
    assert result["SECURITY_JWT_SECRET"] != old_val
    assert not _is_placeholder(result["SECURITY_JWT_SECRET"])


# ── integration: audit command ────────────────────────────────────────────────


def test_audit_detects_hardcoded_secret(tmp_path, monkeypatch):
    # Create a fake .py file with a hardcoded secret
    fake_py = tmp_path / "bad_code.py"
    fake_py.write_text('api_key = "sk-abcdefghijklmnopqrstuvwxyz123456"\n')  # pragma: allowlist secret
    monkeypatch.setattr("scripts.manage_secrets.ROOT", tmp_path)

    rc = cmd_audit(_FakeArgs())
    assert rc == 1


def test_audit_passes_clean_file(tmp_path, monkeypatch):
    clean_py = tmp_path / "clean_code.py"
    clean_py.write_text('api_key = os.getenv("API_KEY")\n')
    monkeypatch.setattr("scripts.manage_secrets.ROOT", tmp_path)

    rc = cmd_audit(_FakeArgs())
    assert rc == 0


# ── integration: check-env command ───────────────────────────────────────────


def test_check_env_detects_missing_key(tmp_path, monkeypatch):
    example = tmp_path / ".env.example"
    example.write_text("FOO=bar\nBAZ=qux\n")
    current = tmp_path / ".env"
    current.write_text("FOO=bar\n")  # BAZ missing

    monkeypatch.setattr("scripts.manage_secrets.ENV_EXAMPLE", example)
    monkeypatch.setattr("scripts.manage_secrets.ENV_FILE", current)

    rc = cmd_check_env(_FakeArgs())
    assert rc == 1


def test_check_env_passes_when_complete(tmp_path, monkeypatch):
    example = tmp_path / ".env.example"
    example.write_text("FOO=bar\nBAZ=qux\n")
    current = tmp_path / ".env"
    current.write_text("FOO=bar\nBAZ=qux\n")

    monkeypatch.setattr("scripts.manage_secrets.ENV_EXAMPLE", example)
    monkeypatch.setattr("scripts.manage_secrets.ENV_FILE", current)

    rc = cmd_check_env(_FakeArgs())
    assert rc == 0
