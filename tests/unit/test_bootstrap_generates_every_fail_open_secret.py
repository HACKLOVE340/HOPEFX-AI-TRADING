# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""A secret whose absence silently disables a control must be generated.

`scripts/bootstrap_dev.py` writes the .env every developer machine runs on. Its
docstring says it generates "ALL secrets". Measured 2026-09-19: it writes 205
of the 945 keys `.env.example` documents, and `DB_ENCRYPTION_KEY` was not among
them.

That one is not a tunable. `database/encryption.py::_load_key` returns None when
it is absent and the column "degrades gracefully to plaintext" -- the module's
own words. The only column using `EncryptedString` is
`database/user_models.py::User.totp_secret`, the second-factor seed. So every
machine this bootstrap set up stored 2FA secrets in the clear, while the
bootstrap reported generating all secrets.

The distinction this file holds is between two kinds of missing key:

* absent and FAIL-CLOSED -- `HEAL_PATCH_SIGNING_KEY`. `security/self_healer.py`
  refuses unsigned patches without it (F130). Generating one would switch a
  working refusal into an acceptance. It is deliberately NOT generated, and
  `test_a_fail_closed_secret_is_not_generated` pins that.
* absent and FAIL-OPEN -- `DB_ENCRYPTION_KEY`. Nothing refuses; the protection
  just stops happening, with no error and no log line at any level.

Only the second kind belongs in the bootstrap. Adding the first kind would be
the defect this repository keeps finding, pointed the other way.
"""

from __future__ import annotations

import base64
import importlib.util
import sys
import tempfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = ROOT / "scripts" / "bootstrap_dev.py"


def _generated_env() -> dict[str, str]:
    """Run the bootstrap's env writer against a throwaway path and parse it."""
    spec = importlib.util.spec_from_file_location("_bd_under_test", BOOTSTRAP)
    module = importlib.util.module_from_spec(spec)
    sys.modules["_bd_under_test"] = module
    spec.loader.exec_module(module)

    target = Path(tempfile.mkdtemp()) / ".env"
    module.ENV_PATH = target
    created = module._generate_env()
    assert created is True, "the writer declined to write to a fresh path"

    out: dict[str, str] = {}
    for line in target.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, _, value = stripped.partition("=")
            out[key.strip()] = value.strip()
    return out


def test_the_generator_produced_something_to_examine():
    """Guard the harness before trusting what it reports."""
    env = _generated_env()
    assert len(env) > 150, f"only {len(env)} keys parsed out of the generated .env"
    assert "SECRET_KEY" in env, "the parse found no SECRET_KEY, so the extraction has broken"


def test_the_database_encryption_key_is_generated():
    env = _generated_env()

    assert "DB_ENCRYPTION_KEY" in env, (
        "the bootstrap does not generate DB_ENCRYPTION_KEY, so database/encryption.py "
        "degrades User.totp_secret to plaintext on every machine it sets up"
    )
    assert env["DB_ENCRYPTION_KEY"], "DB_ENCRYPTION_KEY was written empty, which reads as absent"


def test_the_generated_key_actually_enables_encryption():
    """Identity, not shape.

    A value of the right length that `_load_key` rejects leaves the column in
    plaintext exactly as an absent one does, and the .env would look correct.
    """
    import os

    from database import encryption

    env = _generated_env()
    previous = os.environ.get("DB_ENCRYPTION_KEY")
    os.environ["DB_ENCRYPTION_KEY"] = env.get("DB_ENCRYPTION_KEY", "")
    try:
        key = encryption._load_key()
    finally:
        if previous is None:
            os.environ.pop("DB_ENCRYPTION_KEY", None)
        else:
            os.environ["DB_ENCRYPTION_KEY"] = previous

    assert key is not None, (
        "database/encryption.py rejected the key the bootstrap generated -- encryption is "
        "still disabled, and the .env gives no sign of it"
    )
    assert len(key) == 32, f"decoded to {len(key)} bytes; AES-256-GCM needs exactly 32"


def test_the_generated_key_is_not_a_fixed_value():
    """Two runs must not produce the same key.

    A hardcoded key in a committed generator is a published key.
    """
    first = _generated_env()["DB_ENCRYPTION_KEY"]
    second = _generated_env()["DB_ENCRYPTION_KEY"]

    assert first != second, "the bootstrap emits a constant DB_ENCRYPTION_KEY"
    assert len(base64.urlsafe_b64decode(first + "==")) == 32


def test_a_fail_closed_secret_is_not_generated():
    """HEAL_PATCH_SIGNING_KEY must stay absent.

    `security/self_healer.py::_patch_entry_is_trusted` refuses every unsigned
    patch when this is unset. That refusal is the control. Generating a key here
    would mean the self-healer starts accepting patches signed with a secret the
    bootstrap invented, which is weaker than refusing outright -- and it is a
    control this repository already had to fix once (F130).
    """
    env = _generated_env()

    assert "HEAL_PATCH_SIGNING_KEY" not in env, (
        "the bootstrap now generates HEAL_PATCH_SIGNING_KEY. That turns the self-healer's "
        "refusal of unsigned patches into an acceptance. If this is intended, it is an owner "
        "decision about the patch-trust model, not a bootstrap completeness fix."
    )
