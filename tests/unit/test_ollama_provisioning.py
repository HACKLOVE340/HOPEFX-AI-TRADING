# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Ollama gets installed when the platform is deployed, on Linux and Windows.

Owner requirement, 2026-09-06: "make sure ollama is installed when deploying on
vps or windows".

The runtime added earlier starts the local server and warms its models, but it
assumed Ollama was already on the box. Measured on this machine:

    ollama     not installed

so `_default_launch` raised `OSError("ollama is not installed or not on PATH")`
and the local leg could never answer. Correct fail-safe behaviour, and a dead
end: nothing in `scripts/install.sh` or `scripts/install.ps1` ever installed it.

The install itself lives in one script per platform, and this module owns
*choosing* between them — so the choice is unit-testable while the platform
specifics stay where a person can read them.

**Installing software is not something an application does to a trading box on
its own.** `LOCAL_MODEL_AUTO_INSTALL` is off by default; the deploy scripts are
what install Ollama. When it is absent and auto-install is off, the runtime
refuses and the refusal names the script to run — a message an operator can act
on, rather than a bare "not installed".
"""

from __future__ import annotations

import pytest

from ai import local_model

pytestmark = pytest.mark.unit


# ── choosing the installer ───────────────────────────────────────────────────


def test_linux_installs_through_the_shell_script():
    command = local_model.install_command("Linux")
    assert command is not None
    assert command[0] == "bash"
    assert command[-1].endswith("install_ollama.sh")


def test_macos_uses_the_same_script_as_linux():
    assert local_model.install_command("Darwin")[-1].endswith("install_ollama.sh")


def test_windows_installs_through_the_powershell_script():
    command = local_model.install_command("Windows")
    assert command is not None
    assert command[0].lower().startswith("powershell")
    assert command[-1].endswith("install_ollama.ps1")


def test_an_unknown_platform_is_refused_not_guessed():
    """Guessing an install command for an unknown OS runs an unknown command."""
    assert local_model.install_command("Plan9") is None


def test_the_installer_scripts_exist_where_the_command_points():
    """A command naming a script that is not there is a broken install path."""
    import pathlib

    for system in ("Linux", "Windows"):
        target = pathlib.Path(local_model.install_command(system)[-1])
        assert target.is_file(), f"{system} installer missing at {target}"


# ── auto-install is opt-in ───────────────────────────────────────────────────


def test_auto_install_is_off_by_default(monkeypatch):
    monkeypatch.delenv(local_model.AUTO_INSTALL_ENV, raising=False)
    assert local_model.auto_install_enabled() is False


def test_auto_install_can_be_turned_on(monkeypatch):
    monkeypatch.setenv(local_model.AUTO_INSTALL_ENV, "true")
    assert local_model.auto_install_enabled() is True


# ── ensure_installed ─────────────────────────────────────────────────────────


def test_nothing_runs_when_ollama_is_already_present():
    calls: list[list[str]] = []
    ok, detail = local_model.ensure_installed(present=lambda: True, run=lambda cmd: calls.append(cmd))
    assert ok is True
    assert detail == "already_installed"
    assert calls == [], "installing over a working install is a way to break one"


def test_it_installs_when_absent_then_confirms_by_re_checking(monkeypatch):
    """The install is proved by looking again, not by the installer exiting 0."""
    monkeypatch.setattr(local_model.platform, "system", lambda: "Linux")
    seen = iter([False, True])  # absent, then present after the install
    calls: list[list[str]] = []
    ok, detail = local_model.ensure_installed(present=lambda: next(seen), run=lambda cmd: calls.append(cmd))
    assert ok is True
    assert detail == "installed"
    assert len(calls) == 1


def test_an_installer_that_exits_clean_but_installs_nothing_is_a_failure(monkeypatch):
    """The exact shape this repository keeps producing: success for no work."""
    monkeypatch.setattr(local_model.platform, "system", lambda: "Linux")
    ok, detail = local_model.ensure_installed(present=lambda: False, run=lambda cmd: None)
    assert ok is False
    assert "still_absent" in detail


def test_an_installer_that_fails_is_reported_not_raised(monkeypatch):
    monkeypatch.setattr(local_model.platform, "system", lambda: "Linux")

    def boom(cmd):
        raise OSError("network unreachable")

    ok, detail = local_model.ensure_installed(present=lambda: False, run=boom)
    assert ok is False
    assert "network unreachable" in detail


def test_an_unsupported_platform_reports_why(monkeypatch):
    monkeypatch.setattr(local_model.platform, "system", lambda: "Plan9")
    ok, detail = local_model.ensure_installed(present=lambda: False, run=lambda cmd: None)
    assert ok is False
    assert "unsupported_platform" in detail


# ── the runtime's refusal is actionable ──────────────────────────────────────


@pytest.mark.asyncio
async def test_a_missing_ollama_refusal_names_the_installer(monkeypatch, caplog):
    """ "not installed" is a dead end; naming the script is a next step."""
    monkeypatch.setenv(local_model.AUTOSTART_ENV, "true")
    monkeypatch.delenv(local_model.AUTO_INSTALL_ENV, raising=False)
    runtime = local_model.LocalModelRuntime(
        models=("llama3",),
        tier="1B-4B",
        capacity=lambda: (32.0, 0.0),
        probe=lambda: False,
        launch=lambda: (_ for _ in ()).throw(OSError("ollama is not installed or not on PATH")),
        pull=lambda name: None,
    )
    status = await runtime.start()
    assert status.started is False
    assert "install_ollama" in (status.refusal or ""), status.refusal


@pytest.mark.asyncio
async def test_with_auto_install_on_the_runtime_installs_before_launching(monkeypatch):
    monkeypatch.setenv(local_model.AUTOSTART_ENV, "true")
    monkeypatch.setenv(local_model.AUTO_INSTALL_ENV, "true")
    monkeypatch.setattr(local_model.platform, "system", lambda: "Linux")
    order: list[str] = []
    # Three values, not two: the runtime asks whether Ollama is present, then
    # ensure_installed asks again before it does anything, and the third answer
    # is the post-install verification. A two-value sequence made the second
    # question return "already installed" and the install never ran — the test
    # failing for a reason that was purely its own.
    presence = iter([False, False, True])
    # Not answering at first — an installed-but-stopped server would have
    # nothing to install, so a probe that says "ready" would skip the very
    # branch under test. That is how the first version of this test passed
    # for the wrong reason.
    probes = iter([False, True, True, True])

    runtime = local_model.LocalModelRuntime(
        models=("llama3",),
        tier="1B-4B",
        capacity=lambda: (32.0, 0.0),
        probe=lambda: next(probes, True),
        launch=lambda: order.append("launch"),
        pull=lambda name: order.append(f"pull:{name}"),
        present=lambda: next(presence, True),
        install_run=lambda cmd: order.append("install"),
    )
    status = await runtime.start()
    assert status.started is True
    assert order[:2] == ["install", "launch"], order
