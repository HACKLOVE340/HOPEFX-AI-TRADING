"""Task 10 — the sandbox: where agent-authored code runs without a venue.

v0's `security/ai_repair_sandbox.py` is an AST screen plus `py_compile` in a
temp directory. That is a static filter, not a sandbox: `py_compile` never
executes the module body, so nothing is contained because nothing runs. It is
kept as the pre-filter; it is not the containment boundary.

What this module claims, and what it does not, is stated exactly -- a sandbox
that overstates its isolation is worse than none, because work gets trusted to
it. The boundary that makes "no route to a real venue" true is that the child
process carries NO broker credentials and no gateway: an order cannot be placed
without them.
"""

from __future__ import annotations

import pytest

from ai.sandbox.runner import SandboxResult, run


# ── it actually runs code ─────────────────────────────────────────────────────


def test_ordinary_code_runs_and_returns_its_output() -> None:
    result = run("print(2 + 2)")
    assert isinstance(result, SandboxResult)
    assert result.ok is True
    assert "4" in result.stdout


def test_a_raising_program_is_reported_not_swallowed() -> None:
    result = run("raise ValueError('boom')")
    assert result.ok is False
    assert "boom" in result.stderr


# ── no route to a venue ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "credential",
    [
        "OANDA_API_KEY",
        "OANDA_ACCOUNT_ID",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "SECURITY_JWT_SECRET",
        "DB_ENCRYPTION_KEY",
        "POSTGRES_PASSWORD",
    ],
)
def test_no_credential_reaches_the_child(credential: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(credential, "super-secret-value")
    # prefilter=False on purpose: the credential scrub must hold WITHOUT the
    # static screen, or it is a denylist rather than containment.
    result = run(f"import os; print(repr(os.environ.get({credential!r})))", prefilter=False)
    assert result.ok is True
    assert "super-secret-value" not in result.stdout
    assert "None" in result.stdout


def test_a_live_broker_call_from_inside_the_sandbox_fails() -> None:
    """The done-condition: agent code must not be able to reach a venue."""
    result = run(
        "import urllib.request\nurllib.request.urlopen('https://api-fxtrade.oanda.com/v3/accounts', timeout=2)\n",
        prefilter=False,
    )
    assert result.ok is False, "a live broker endpoint was reachable from the sandbox"


def test_network_is_refused_by_default() -> None:
    result = run("import socket; socket.socket().connect(('1.1.1.1', 80))", prefilter=False)
    assert result.ok is False
    assert "sandbox" in (result.stderr + " ".join(result.reason_codes)).lower()


# ── resource containment ──────────────────────────────────────────────────────


def test_an_endless_loop_is_killed() -> None:
    result = run("while True:\n    pass\n", timeout_s=2.0)
    assert result.ok is False
    assert "timeout" in result.reason_codes


def test_the_child_cannot_write_into_the_repository() -> None:
    result = run(
        "from pathlib import Path\n"
        "Path('SANDBOX_ESCAPE.txt').write_text('escaped')\n"
        "print(Path('SANDBOX_ESCAPE.txt').resolve())\n",
        prefilter=False,
    )
    # It may write inside its own disposable directory, but never into the repo.
    import pathlib

    assert not pathlib.Path("SANDBOX_ESCAPE.txt").exists()
    if result.ok:
        assert "SANDBOX_ESCAPE.txt" in result.stdout
        assert str(pathlib.Path().resolve()) not in result.stdout


# ── the pre-filter still applies ──────────────────────────────────────────────


def test_the_static_prefilter_rejects_before_anything_executes() -> None:
    result = run("import subprocess\nprint('should not get here')")
    assert result.ok is False
    assert "should not get here" not in result.stdout
    assert any("banned_import" in code for code in result.reason_codes)


def test_syntactically_invalid_code_is_refused_by_the_prefilter() -> None:
    result = run("def broken(:\n")
    assert result.ok is False
    assert "syntax_error" in result.reason_codes


# ── the module must state its limits ──────────────────────────────────────────


def test_the_module_documents_what_it_does_not_contain() -> None:
    """A sandbox that overstates its isolation gets work trusted to it."""
    from ai.sandbox import runner

    doc = (runner.__doc__ or "").lower()
    assert "not" in doc
    assert any(word in doc for word in ("defence in depth", "defense in depth", "does not"))
