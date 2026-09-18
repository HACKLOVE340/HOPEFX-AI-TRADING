# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
The component that writes code to the running system must fail closed.

`security/self_healer.py` applies patches drawn from the Redis list
`fixes:approved` to the source tree. Two of its gates returned the permissive
value when they could not do their job.

**F130 — patch signing accepted everything.** The HMAC check is correctly built
(`hmac.new(key, payload, sha256)`, `hmac.compare_digest`, no timing leak). It
simply never ran:

    if not _PATCH_SIGNING_KEY:
        logger.warning("...trust verification disabled...")
        return True          # <- accepts the patch

and `HEAL_PATCH_SIGNING_KEY` appeared **only inside self_healer.py** — not in
`.env.example`, not in any compose file, not in either k8s ConfigMap. There was
no shipped configuration in which the control was on. The author's own comment
names the threat: "a compromised Redis instance cannot inject arbitrary code".
With the key unset, whatever can `RPUSH` to that list has its Python written
into the source tree.

**F184 — "could not run tests" counted as "tests passed".**

    except FileNotFoundError:
        self._log("warning", "...python not found on PATH — skipping test run")
        return True

`_run_tests()` gates patch application (`pre_ok`) and validates it afterwards
(`post_ok`). The rest of the function is careful — a timeout returns False, a
generic exception returns False — so this was one narrow branch, and the safe
value for "I could not verify" on a patch gate is False.

Both now refuse. Refusing is allowed to be inconvenient; applying unverified
code to a running money-moving system is not.
"""

from __future__ import annotations

import logging

import pytest

pytestmark = pytest.mark.unit


def _reload_healer(monkeypatch, **env):
    """Re-import the module so module-level key material is re-read."""
    import importlib

    for key in ("HEAL_PATCH_SIGNING_KEY", "HEAL_ALLOW_UNSIGNED_PATCHES"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    import security.self_healer as healer

    return importlib.reload(healer)


@pytest.fixture(autouse=True)
def _restore_module():
    """Reloading a module with module-level state leaks into later tests unless
    it is put back — this cost three unrelated singleton tests once already."""
    yield
    import importlib

    import security.self_healer as healer

    importlib.reload(healer)


# ── F130: patch signing ──────────────────────────────────────────────────────


def test_an_unsigned_patch_is_rejected_when_no_key_is_configured(monkeypatch, caplog):
    healer = _reload_healer(monkeypatch)

    with caplog.at_level(logging.DEBUG):
        trusted = healer._patch_entry_is_trusted('{"file": "x.py"}', {"file": "x.py"})

    assert trusted is False, (
        "with no signing key the patch queue accepted everything — anything that can "
        "write to Redis could write Python into the source tree (F130)"
    )
    assert any(r.levelno >= logging.ERROR for r in caplog.records), (
        "the disabled control was announced at WARNING or below"
    )


def test_a_correctly_signed_patch_is_accepted(monkeypatch):
    key = "a" * 32
    healer = _reload_healer(monkeypatch, HEAL_PATCH_SIGNING_KEY=key)

    raw = '{"file": "x.py", "patch": "print(1)"}'
    signature = healer._sign_patch(raw)

    assert healer._patch_entry_is_trusted(raw, {"_sig": signature}) is True


def test_a_tampered_patch_is_rejected(monkeypatch):
    healer = _reload_healer(monkeypatch, HEAL_PATCH_SIGNING_KEY="a" * 32)

    raw = '{"file": "x.py", "patch": "print(1)"}'
    signature = healer._sign_patch(raw)

    assert healer._patch_entry_is_trusted(raw + " ", {"_sig": signature}) is False
    assert healer._patch_entry_is_trusted(raw, {"_sig": "deadbeef"}) is False
    assert healer._patch_entry_is_trusted(raw, {}) is False


def test_running_unsigned_requires_an_explicit_opt_in(monkeypatch, caplog):
    """Refusing without a key is right, but a developer running the healer
    locally needs a way through that is a deliberate act, not a default."""
    healer = _reload_healer(monkeypatch, HEAL_ALLOW_UNSIGNED_PATCHES="true")

    with caplog.at_level(logging.DEBUG):
        trusted = healer._patch_entry_is_trusted('{"file": "x.py"}', {"file": "x.py"})

    assert trusted is True
    assert any(r.levelno >= logging.WARNING for r in caplog.records), (
        "an explicitly unsigned patch queue was accepted silently"
    )


def test_the_opt_in_does_not_bypass_a_configured_key(monkeypatch):
    """If a key IS set, the opt-out must not disable verification — otherwise a
    single environment variable turns the control off in production."""
    healer = _reload_healer(
        monkeypatch,
        HEAL_PATCH_SIGNING_KEY="a" * 32,
        HEAL_ALLOW_UNSIGNED_PATCHES="true",
    )

    assert healer._patch_entry_is_trusted('{"file": "x.py"}', {"_sig": "deadbeef"}) is False


def test_the_signing_key_is_reachable_from_shipped_configuration():
    """The finding's core complaint: the control existed in exactly one file, so
    there was no configuration in which it could be switched on."""
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    mentioned = [
        candidate.name
        for candidate in (repo / ".env.example", repo / ".env.production.example")
        if candidate.exists() and "HEAL_PATCH_SIGNING_KEY" in candidate.read_text(encoding="utf-8")
    ]
    assert mentioned, "HEAL_PATCH_SIGNING_KEY appears in no shipped example configuration"


# ── F184: "could not run tests" ──────────────────────────────────────────────


def test_a_test_run_that_could_not_start_is_not_a_pass(monkeypatch):
    """`_run_tests` gates patch application and validates the result. The safe
    value for 'I could not verify' is False, which is what the timeout and
    generic-exception branches already return."""
    import asyncio

    import security.self_healer as healer_mod

    # A real SelfHealer, not a hand-assembled shell. Building it attribute by
    # attribute means the test stops exercising the object as soon as the class
    # grows a field, which is how a mock quietly stops matching the thing it
    # stands for (F242).
    healer = healer_mod.SelfHealer()
    healer._log = lambda *a, **k: None
    healer._test_categories = {"unit": True}

    # A real path so the function reaches the subprocess call rather than
    # short-circuiting on "no test paths".
    monkeypatch.setattr(
        "security.test_scanner.get_test_index",
        lambda force_rescan=False: {"file_list": [{"path": "tests/unit", "category": "unit"}]},
    )

    async def _boom(*args, **kwargs):
        raise FileNotFoundError("python: No such file or directory")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _boom)

    assert asyncio.run(healer._run_tests("unit")) is False, (
        "a test run that never started was reported as passing, on the gate that admits a patch (F184)"
    )
