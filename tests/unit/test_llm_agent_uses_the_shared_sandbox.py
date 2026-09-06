# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""LLM-generated strategy code is smoke-tested with the network blocked.

`brain/llm_agent._compile_strategy` had its own inline sandbox: a subprocess
with rlimits (CPU, address space, file descriptors, NPROC=0) and an environment
stripped of secrets. Careful work — and it has no socket block. Measured by
reading its runner script: it imports the module and instantiates the class,
and nothing prevents that code from opening a connection.

`PYTHONPATH` is forwarded so imports resolve, so generated code could read files
and reach the network in the same breath. rlimits stop it burning CPU, forking
or exhausting memory; they do not stop it talking.

`ai/sandbox/runner.py` installs a socket block when `net=False`, and it already
had zero production callers. Two sandbox implementations in one repository is
also a maintenance hazard on its own: a fix to one does not reach the other, and
the weaker one is the one that runs model-produced code.

So the smoke test goes through the shared sandbox. The AST denylist stays — it
screens the strategy before anything is spawned — and the parent-process exec
stays gated off by `LLM_CODE_EXECUTION_ENABLED`, which the module's own comment
correctly calls the dangerous part.
"""

from __future__ import annotations

import inspect

import pytest

pytestmark = pytest.mark.unit


def test_the_inline_subprocess_sandbox_is_gone():
    """One implementation, so a fix reaches the code that needs it."""
    from brain import llm_agent

    source = inspect.getsource(llm_agent._compile_strategy)
    assert "subprocess.run" not in source, (
        "llm_agent still spawns its own sandbox subprocess; the shared sandbox is what blocks the network"
    )


def test_the_shared_sandbox_is_what_runs_the_smoke_test():
    from brain import llm_agent

    source = inspect.getsource(llm_agent._compile_strategy)
    assert "ai.sandbox" in source or "sandbox_run" in source


def test_the_smoke_test_runs_with_the_network_blocked():
    """The property this change exists for."""
    from brain import llm_agent

    source = inspect.getsource(llm_agent._compile_strategy)
    assert "net=False" in source, "the smoke test must run with the network blocked"


def test_the_ast_denylist_still_screens_the_source():
    """Defence in depth: the screen is not replaced by containment."""
    from brain import llm_agent

    source = inspect.getsource(llm_agent._compile_strategy)
    assert "_ast_safety_check" in source or "safety" in source.lower()


def test_parent_process_execution_is_still_gated_off_by_default(monkeypatch):
    """The genuinely dangerous step keeps its opt-in gate."""
    monkeypatch.delenv("LLM_CODE_EXECUTION_ENABLED", raising=False)
    import importlib

    from brain import llm_agent

    importlib.reload(llm_agent)
    assert llm_agent._LLM_CODE_EXEC_ENABLED is False


# ── executed, not asserted from source ───────────────────────────────────────


@pytest.mark.slow
def test_generated_code_that_opens_a_socket_is_refused_by_the_shared_sandbox():
    """The real containment, driven directly.

    Reading the source proves the call site says net=False. This proves the
    thing it calls actually refuses a connection.
    """
    from ai.sandbox import runner

    result = runner.run(
        "import socket; socket.socket().connect(('1.1.1.1', 80)); print('reached')",
        prefilter=False,
        net=False,
        timeout_s=10.0,
    )
    assert result.ok is False
    assert "reached" not in result.stdout


GOOD_STRATEGY = (
    "class GeneratedStrategy:\n"
    "    def __init__(self):\n"
    "        self.name = 'ok'\n"
    "    def generate_signal(self, bar):\n"
    "        return 'hold'\n"
)


def test_with_the_gate_off_nothing_is_compiled_at_all(monkeypatch):
    """The gate is the first thing checked, before the sandbox is even reached."""
    import importlib

    from brain import llm_agent

    monkeypatch.delenv("LLM_CODE_EXECUTION_ENABLED", raising=False)
    importlib.reload(llm_agent)
    instance, error = llm_agent._compile_strategy(GOOD_STRATEGY)
    assert instance is None
    assert "disabled" in (error or "").lower()


@pytest.mark.slow
def test_with_the_gate_on_a_well_formed_strategy_compiles(monkeypatch):
    """A containment layer that refuses every strategy is an outage.

    This asserts the gate ON, because with it off the function returns before
    the sandbox runs — an earlier version of this test passed for exactly that
    reason and proved nothing about containment.
    """
    import importlib

    from brain import llm_agent

    monkeypatch.setenv("LLM_CODE_EXECUTION_ENABLED", "true")
    importlib.reload(llm_agent)
    try:
        instance, error = llm_agent._compile_strategy(GOOD_STRATEGY)
        assert instance is not None, error
        assert error is None
    finally:
        monkeypatch.delenv("LLM_CODE_EXECUTION_ENABLED", raising=False)
        importlib.reload(llm_agent)


@pytest.mark.slow
def test_with_the_gate_on_a_networking_strategy_is_refused(monkeypatch):
    """The property the shared sandbox adds: the smoke test cannot talk out."""
    import importlib

    from brain import llm_agent

    monkeypatch.setenv("LLM_CODE_EXECUTION_ENABLED", "true")
    importlib.reload(llm_agent)
    try:
        hostile = (
            "import socket\n"
            "class GeneratedStrategy:\n"
            "    def __init__(self):\n"
            "        socket.socket().connect(('1.1.1.1', 80))\n"
        )
        instance, error = llm_agent._compile_strategy(hostile)
        assert instance is None
        assert error
    finally:
        monkeypatch.delenv("LLM_CODE_EXECUTION_ENABLED", raising=False)
        importlib.reload(llm_agent)
