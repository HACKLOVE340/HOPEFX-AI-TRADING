# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_stack_dump_signal.py
=====================================
A hung production process must be able to say what it is doing.

The container's health probe began timing out with **zero bytes received** —
curl connected and the server never wrote a response — every 30 seconds:

    "ExitCode": -1
    "Output": "Health check exceeded timeout (10s)"   0 bytes, 0:00:09 elapsed

``/api/health/live`` returns a literal dict and cannot block, so something
upstream was preventing it from running. Finding out what should have taken one
command. Instead there was no way in at all:

* ``faulthandler`` was never registered, so no signal dumped anything;
* ``py-spy`` is not in the image, and installing it landed outside ``$PATH``;
* ``docker exec … python -c 'faulthandler.dump_traceback()'`` dumps the *new*
  process and says nothing about PID 1.

Every candidate explanation stayed a guess, including several that turned out to
be wrong. This arms SIGUSR1 at startup so the answer is one signal away:

    docker kill -s USR1 hopefx-ai-trading-app-1
    docker logs --tail 100 hopefx-ai-trading-app-1

These tests run the handler in a real subprocess, because that is the only way
to prove a signal handler works — asserting that ``faulthandler.register`` was
called would pass just as happily if the dump never appeared.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

pytestmark = pytest.mark.unit

_HARNESS = textwrap.dedent(
    """
    import os, signal, sys, threading, time
    sys.path.insert(0, {repo!r})
    import faulthandler

    # Arm it exactly as app.py does.
    faulthandler.register(signal.SIGUSR1, file=sys.stderr, all_threads=True, chain=False)

    def stuck():
        time.sleep(4)

    threading.Thread(target=stuck, name="hopefx-stuck-thread", daemon=True).start()
    time.sleep(0.2)
    os.kill(os.getpid(), signal.SIGUSR1)
    time.sleep(0.3)
    print("STILL-ALIVE", flush=True)
    """
)


def _run_harness() -> subprocess.CompletedProcess:
    import pathlib

    repo = str(pathlib.Path(__file__).resolve().parents[2])
    return subprocess.run(
        [sys.executable, "-c", _HARNESS.format(repo=repo)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,  # the return code is an assertion below, not a precondition
    )


@pytest.mark.skipif(not hasattr(__import__("signal"), "SIGUSR1"), reason="SIGUSR1 is POSIX-only")
def test_the_signal_dumps_a_traceback():
    result = _run_harness()
    assert "Thread" in result.stderr or "Current thread" in result.stderr, (
        f"SIGUSR1 produced no traceback. stderr was:\n{result.stderr[:500]}"
    )


@pytest.mark.skipif(not hasattr(__import__("signal"), "SIGUSR1"), reason="SIGUSR1 is POSIX-only")
def test_it_names_the_blocked_thread():
    """The point of the dump: identify what is holding things up. A dump of only
    the signalled thread would show the handler and nothing useful, which is why
    all_threads=True matters."""
    result = _run_harness()
    assert "stuck" in result.stderr, (
        f"the blocked worker does not appear — all_threads may be off. stderr:\n{result.stderr[:800]}"
    )


@pytest.mark.skipif(not hasattr(__import__("signal"), "SIGUSR1"), reason="SIGUSR1 is POSIX-only")
def test_the_process_survives_the_dump():
    """SIGUSR1's default disposition terminates the process. Dumping stacks must
    never be the thing that kills a trading process — the whole point is to
    inspect it while it is still running."""
    result = _run_harness()
    assert "STILL-ALIVE" in result.stdout, (
        f"the process died on SIGUSR1 (rc={result.returncode}). stderr:\n{result.stderr[:400]}"
    )
    assert result.returncode == 0


def test_app_arms_it_during_startup():
    """Guard against the helper being defined and never called."""
    import inspect

    import app as app_module

    assert hasattr(app_module, "_enable_stack_dump_signal")
    src = inspect.getsource(app_module.startup_event)
    assert "_enable_stack_dump_signal()" in src, "startup_event no longer arms the stack-dump signal"


def test_arming_never_raises(monkeypatch):
    """A diagnostic aid must not be able to prevent the app from starting."""
    import app as app_module

    def _boom(*a, **k):
        raise OSError("no fileno")

    import faulthandler

    monkeypatch.setattr(faulthandler, "register", _boom)
    app_module._enable_stack_dump_signal()  # must not raise
