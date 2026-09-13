# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
A rotation helper that destroys credentials must not report success.

`docs/audit/AI_CORE_SPEC.md` open item 6 puts rotating the exposed superadmin
credential above everything else in the build. `AI_CORE_SPEC_INTAKE.md` §5 warns
about what sits on that path:

> **F180-F183** — `security/encryption.py` and `security/vault.py` are two
> unreferenced `SecureVault` classes whose `rotate_key()` **destroys every
> stored credential and returns `True`**. If any rotation tooling is written for
> this credential, it must not use those.

`security/encryption.py::SecureVault.rotate_key` promises, in its own docstring:

    Re-encrypt all credentials with new key

and does this:

    # Store old cipher          <- an orphan comment; nothing follows it
    self._master_key = new_master_key
    self._initialize_cipher()
    return True

It re-encrypts nothing. `SecureVault` holds no credentials to re-encrypt — only
`_master_key`, `_cipher` and `_salt` — so the promise is unimplementable by this
class as designed. Every ciphertext produced under the old key, wherever it is
stored, becomes permanently undecryptable, and the caller is told the rotation
succeeded. The class docstring's "Automatic key rotation support" is the same
claim one level up.

The live vault is `config/vault.py`, which is correct: it writes the new key to
a temporary keyring slot *before* swapping the active cipher, so a crash
mid-rotation leaves a recoverable state.

This is the audit's signature defect — success reported for work that did not
happen — sitting on the single highest-priority operation in the spec.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def vault():
    from security.encryption import CredentialCipher

    return CredentialCipher(master_key="original-master-key-for-tests")  # nosec B106


def test_rotation_does_not_silently_orphan_existing_ciphertext(vault):
    """The data-loss demonstrated, not described: encrypt, rotate, decrypt."""
    ciphertext = vault.encrypt("OANDA-LIVE-TOKEN")
    assert vault.decrypt(ciphertext) == "OANDA-LIVE-TOKEN"

    # Rotating must either re-encrypt (it cannot — there is nothing to
    # re-encrypt from) or refuse. What it must never do is change the key,
    # report success, and leave this ciphertext unreadable.
    with pytest.raises(RuntimeError) as excinfo:
        vault.rotate_key("a-new-master-key")

    assert vault.decrypt(ciphertext) == "OANDA-LIVE-TOKEN", (
        "the vault rotated its key and the credential encrypted before rotation is now unreadable"
    )
    assert "config/vault.py" in str(excinfo.value) or "config.vault" in str(excinfo.value), (
        f"the refusal does not point the operator at the vault that can rotate: {excinfo.value}"
    )


def test_rotation_never_returns_true(vault):
    """`return True` on a no-op is what made this dangerous: rotation tooling
    would record a successful rotation that never happened."""
    try:
        result = vault.rotate_key("another-key")
    except Exception:
        return  # refusing is the correct behaviour
    pytest.fail(f"rotate_key reported {result!r} for a rotation it did not perform")


def test_the_docstring_no_longer_promises_re_encryption(vault):
    """A docstring that describes the correct behaviour makes the wrong
    behaviour invisible in review — the reviewer reads the promise, not the
    body.

    Checked on the summary line, not the whole docstring. A first version
    searched the entire text for "re-encrypt all credentials" and failed against
    the corrected version, which *quotes* the old promise in past tense to
    explain what changed. Grepping prose cannot tell a promise from a quotation
    of one — the same mistake as F255, in the test rather than the analyzer.
    """
    doc = (type(vault).rotate_key.__doc__ or "").strip()
    summary = doc.splitlines()[0].lower() if doc else ""

    assert "re-encrypt all credentials" not in summary, (
        f"the summary line still promises work the method cannot do: {summary!r}"
    )
    assert "refuse" in summary or "cannot" in summary, f"the summary line does not say the method refuses: {summary!r}"


def test_the_class_does_not_advertise_automatic_rotation(vault):
    doc = (type(vault).__doc__ or "").lower()
    assert "automatic key rotation support" not in doc


def test_encryption_still_works_after_the_change(vault):
    """The fix must refuse rotation, not break the vault."""
    token = vault.encrypt("still-works")
    assert vault.decrypt(token) == "still-works"


def test_the_live_vault_is_the_one_that_can_rotate():
    """Named here so rotation tooling is written against the right object."""
    import inspect

    from config.vault import SecureVault as LiveVault

    source = inspect.getsource(LiveVault.rotate_key)
    assert "keyring" in source, "config/vault.py::rotate_key no longer stages the new key in the keyring"


# ── one name, one credential store ───────────────────────────────────────────
#
# Two classes were named `SecureVault`: the live one in `config/vault.py`
# (Argon2id, crash-safe rotation) and this module's, which cannot rotate at all.
# A name collision on a credential store is how the wrong one gets imported, and
# the failure is silent — both encrypt, both decrypt, and only one survives a
# key change.
#
# The fix is a rename rather than a deletion: `security/encryption.py` is
# load-bearing (`hash_password` has 31 production references, `verify_password`
# 18), so the module stays and only the misleading name goes. `CredentialCipher`
# is what it actually is — it holds no credentials and has no vault semantics,
# which is precisely why `rotate_key` raises.


def test_exactly_one_importable_class_is_named_SecureVault():
    """And it is the live one.

    Asserted against the source tree rather than by importing, because importing
    every module to find a class name would execute half the platform.
    """
    import pathlib
    import re
    import subprocess

    root = pathlib.Path(__file__).resolve().parents[2]
    tracked = subprocess.run(
        ["git", "ls-files", "*.py"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.split()
    assert len(tracked) > 100, "git ls-files returned almost nothing; this assertion would be vacuous"

    declaring = [
        rel
        for rel in tracked
        if re.search(r"(?m)^class SecureVault\b", (root / rel).read_text(encoding="utf-8", errors="replace"))
    ]
    assert declaring == ["config/vault.py"], (
        f"SecureVault is declared in {declaring}; exactly one credential store may carry that name, "
        "and it is the one in config/vault.py that can actually rotate a key"
    )


def test_the_renamed_cipher_is_still_reachable_under_its_new_name():
    """The rename must not quietly delete the behaviour the module still needs."""
    from security.encryption import CredentialCipher

    c = CredentialCipher(master_key="k")  # nosec B106
    assert c.decrypt(c.encrypt("OANDA-TOKEN")) == "OANDA-TOKEN"


def test_the_renamed_cipher_still_refuses_to_rotate():
    """The refusal is the point of the whole finding; a rename must not lose it."""
    import pytest as _pytest

    from security.encryption import CredentialCipher

    c = CredentialCipher(master_key="k")  # nosec B106
    with _pytest.raises(RuntimeError, match="cannot rotate"):
        c.rotate_key("new-key")
