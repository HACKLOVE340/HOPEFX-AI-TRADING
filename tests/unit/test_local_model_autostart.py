# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The local model runtime starts with the application, and says so honestly.

Owner requirement, 2026-09-06: the local LLM and any other local models must
come up at application startup so they are running on the VPS without anyone
starting them by hand. See docs/audit/plans/2026-09-05-ai-core.md §1A.5.1.

Nothing did this. Every part of the local path assumed an Ollama server already
listening with the model already pulled, and after a reboot or a fresh deploy it
is neither. The sharp edge is `ai/gateway/providers.py`:

    "ollama": ("OLLAMA_BASE_URL",)
    def local_inference_enabled() -> bool:
        return is_credentialed("ollama")     # True because a STRING IS SET

Setting an environment variable is not evidence that a server is listening on
the other end of it, so the local leg could sit in a resolved chain, be counted
as available, and answer nothing. That is a control reporting success for work
that did not happen — this audit's signature defect, in the AI subsystem itself.

These tests therefore assert the two properties that are easy to fake and
expensive to get wrong:

* the runtime is reachable from a real call site (read out of the component
  registry, not asserted by a comment), and
* readiness is *measured* by probing the server, never declared by an env var.

Nothing here starts a real server, downloads a model, or touches the network.
"""

from __future__ import annotations

import logging

import pytest

from ai import local_model

pytestmark = pytest.mark.unit


# ── the resource gate ────────────────────────────────────────────────────────
# scripts/vps_capability_report.py states the reason this gate exists: "an
# oversized model does not degrade, it fails to load or swaps the box to a
# standstill." On a machine that also executes orders, swapping to a standstill
# is a trading outage, so the runtime refuses rather than tries and finds out.


@pytest.mark.parametrize(
    ("tier", "ram", "vram", "fits"),
    [
        ("1B-4B", 8.0, 0.0, True),
        ("1B-4B", 4.0, 0.0, False),
        ("7B-8B", 16.0, 0.0, True),
        ("7B-8B", 8.0, 0.0, False),
        ("7B-8B", 4.0, 8.0, True),  # VRAM satisfies it without the RAM floor
        ("70B+", 512.0, 0.0, False),  # no GPU: RAM alone never buys the top tier
        ("70B+", 64.0, 80.0, True),
    ],
)
def test_tier_fits_is_measured_against_real_capacity(tier, ram, vram, fits):
    assert local_model.tier_fits(tier, ram_gib=ram, vram_gib=vram) is fits


def test_an_unknown_tier_never_fits():
    """A typo in LOCAL_MODEL_TIER must refuse, not fall through to 'sure'."""
    assert local_model.tier_fits("enormous", ram_gib=1024.0, vram_gib=1024.0) is False


# ── off by default ───────────────────────────────────────────────────────────


def test_autostart_is_off_by_default(monkeypatch):
    """Upgrading a deployment must not start downloading a model on its own."""
    monkeypatch.delenv(local_model.AUTOSTART_ENV, raising=False)
    assert local_model.autostart_enabled() is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_autostart_honours_the_usual_truthy_spellings(monkeypatch, value):
    monkeypatch.setenv(local_model.AUTOSTART_ENV, value)
    assert local_model.autostart_enabled() is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "", "  "])
def test_autostart_treats_everything_else_as_off(monkeypatch, value):
    monkeypatch.setenv(local_model.AUTOSTART_ENV, value)
    assert local_model.autostart_enabled() is False


# ── models, plural ───────────────────────────────────────────────────────────


def test_model_list_defaults_to_the_single_configured_model(monkeypatch):
    monkeypatch.delenv(local_model.MODELS_ENV, raising=False)
    assert local_model.configured_models() == (local_model.DEFAULT_LOCAL_MODEL,)


def test_model_list_takes_several(monkeypatch):
    """The owner asked for "the local LLM and other local models" — plural."""
    monkeypatch.setenv(local_model.MODELS_ENV, "llama3, qwen2.5-coder ,nomic-embed-text")
    assert local_model.configured_models() == ("llama3", "qwen2.5-coder", "nomic-embed-text")


def test_blank_entries_in_the_model_list_are_dropped(monkeypatch):
    monkeypatch.setenv(local_model.MODELS_ENV, "llama3,,  ,qwen2.5")
    assert local_model.configured_models() == ("llama3", "qwen2.5")


# ── readiness is measured, not declared ──────────────────────────────────────


def test_ready_is_false_when_the_server_does_not_answer(monkeypatch):
    """The whole point. OLLAMA_BASE_URL set, nothing listening, ready is False."""
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    runtime = local_model.LocalModelRuntime(probe=lambda: False)
    assert runtime.is_ready() is False


def test_ready_is_true_only_when_the_probe_answers(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    runtime = local_model.LocalModelRuntime(probe=lambda: True)
    assert runtime.is_ready() is True


def test_a_probe_that_raises_is_not_ready(monkeypatch):
    """A probe blowing up is evidence of no server, not of an unknown state."""

    def boom() -> bool:
        raise OSError("connection refused")

    runtime = local_model.LocalModelRuntime(probe=boom)
    assert runtime.is_ready() is False


# ── start(): refuses what does not fit, never raises, never lies ─────────────


@pytest.mark.asyncio
async def test_start_refuses_a_tier_the_machine_cannot_hold(monkeypatch, caplog):
    monkeypatch.setenv(local_model.AUTOSTART_ENV, "true")
    started: list[str] = []
    runtime = local_model.LocalModelRuntime(
        models=("llama3:70b",),
        tier="70B+",
        capacity=lambda: (8.0, 0.0),  # 8 GiB RAM, no GPU
        probe=lambda: False,
        launch=lambda: started.append("server"),
        pull=lambda name: started.append(name),
    )
    with caplog.at_level(logging.ERROR):
        status = await runtime.start()

    assert status.started is False
    assert status.refusal is not None and "70B+" in status.refusal
    assert started == [], "a model the box cannot hold must not be launched or pulled"
    assert any(record.levelno >= logging.ERROR for record in caplog.records)


@pytest.mark.asyncio
async def test_start_does_nothing_when_autostart_is_off(monkeypatch):
    monkeypatch.delenv(local_model.AUTOSTART_ENV, raising=False)
    started: list[str] = []
    runtime = local_model.LocalModelRuntime(
        launch=lambda: started.append("server"),
        pull=lambda name: started.append(name),
    )
    status = await runtime.start()
    assert status.started is False
    assert status.refusal == "autostart_disabled"
    assert started == []


@pytest.mark.asyncio
async def test_start_warms_every_configured_model(monkeypatch):
    monkeypatch.setenv(local_model.AUTOSTART_ENV, "true")
    pulled: list[str] = []
    runtime = local_model.LocalModelRuntime(
        models=("llama3", "qwen2.5-coder"),
        tier="1B-4B",
        capacity=lambda: (32.0, 0.0),
        probe=lambda: True,
        launch=lambda: None,
        pull=pulled.append,
    )
    status = await runtime.start()
    assert status.started is True
    assert pulled == ["llama3", "qwen2.5-coder"]
    assert status.models_ready == ("llama3", "qwen2.5-coder")
    assert status.models_failed == ()


@pytest.mark.asyncio
async def test_one_model_failing_does_not_take_down_the_others(monkeypatch, caplog):
    monkeypatch.setenv(local_model.AUTOSTART_ENV, "true")

    def pull(name: str) -> None:
        if name == "broken":
            raise RuntimeError("manifest not found")

    runtime = local_model.LocalModelRuntime(
        models=("llama3", "broken", "qwen2.5"),
        tier="1B-4B",
        capacity=lambda: (32.0, 0.0),
        probe=lambda: True,
        launch=lambda: None,
        pull=pull,
    )
    with caplog.at_level(logging.ERROR):
        status = await runtime.start()

    assert status.models_ready == ("llama3", "qwen2.5")
    assert status.models_failed == ("broken",)
    assert any("broken" in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_a_server_that_will_not_start_is_reported_not_raised(monkeypatch, caplog):
    """Failure must never be fatal, and never silent — ERROR, not DEBUG."""
    monkeypatch.setenv(local_model.AUTOSTART_ENV, "true")

    def launch() -> None:
        raise OSError("ollama: command not found")

    runtime = local_model.LocalModelRuntime(
        models=("llama3",),
        tier="1B-4B",
        capacity=lambda: (32.0, 0.0),
        probe=lambda: False,
        launch=launch,
        pull=lambda name: None,
    )
    with caplog.at_level(logging.ERROR):
        status = await runtime.start()

    assert status.started is False
    assert status.refusal is not None
    assert any(record.levelno >= logging.ERROR for record in caplog.records)


@pytest.mark.asyncio
async def test_start_does_not_relaunch_a_server_that_is_already_running(monkeypatch):
    monkeypatch.setenv(local_model.AUTOSTART_ENV, "true")
    launched: list[str] = []
    runtime = local_model.LocalModelRuntime(
        models=("llama3",),
        tier="1B-4B",
        capacity=lambda: (32.0, 0.0),
        probe=lambda: True,  # already listening
        launch=lambda: launched.append("server"),
        pull=lambda name: None,
    )
    status = await runtime.start()
    assert status.started is True
    assert launched == [], "a second ollama on the same port is not an improvement"


# ── the call site, read from the registry rather than asserted in prose ──────


def test_the_runtime_is_registered_in_the_component_registry():
    """A supervisor nothing constructs is the defect this repository is full of."""
    import core.startup_factories as F

    assert hasattr(F, "init_local_model_runtime"), "no startup factory for the local runtime"


def test_the_registry_entry_is_optional_so_it_can_never_block_boot():
    from unittest.mock import MagicMock

    from core.startup_factories import build_component_registry

    registry = build_component_registry(MagicMock(), MagicMock())
    components = registry.components if hasattr(registry, "components") else registry._components
    assert "local_model_runtime" in components, (
        "the local model runtime is not registered, so app startup never starts it"
    )
    assert components["local_model_runtime"].required is False
