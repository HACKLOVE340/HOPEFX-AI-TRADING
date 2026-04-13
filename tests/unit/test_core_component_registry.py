# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_core_component_registry.py
==========================================
Coverage tests for core/component_registry.py.
"""

from __future__ import annotations

import pytest

from core.component_registry import Component, ComponentRegistry


# ── helpers ───────────────────────────────────────────────────────────────────


class _AppState:
    """Minimal app-state stand-in."""
    pass


async def _ok_factory(app_state):
    return "instance"


async def _fail_factory(app_state):
    raise RuntimeError("factory error")


def _sync_factory(app_state):
    return "sync_instance"


# ── Component dataclass ───────────────────────────────────────────────────────


def test_component_defaults():
    c = Component(name="x", factory=_ok_factory)
    assert c.status == "pending"
    assert c.instance is None
    assert c.error is None
    assert c.elapsed_ms == 0.0
    assert c.deps == []
    assert not c.required


# ── Registration ──────────────────────────────────────────────────────────────


def test_register_returns_self():
    reg = ComponentRegistry()
    result = reg.register("a", _ok_factory)
    assert result is reg


def test_register_multiple():
    reg = ComponentRegistry()
    reg.register("a", _ok_factory).register("b", _ok_factory)
    assert "a" in reg._components
    assert "b" in reg._components


# ── start_all — happy path ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_all_sets_instance():
    reg = ComponentRegistry()
    reg.register("comp", _ok_factory)
    state = _AppState()
    result = await reg.start_all(state)
    assert result["comp"].status == "ok"
    assert result["comp"].instance == "instance"
    assert getattr(state, "comp") == "instance"


@pytest.mark.asyncio
async def test_start_all_sync_factory():
    reg = ComponentRegistry()
    reg.register("sync", _sync_factory)
    state = _AppState()
    await reg.start_all(state)
    assert getattr(state, "sync") == "sync_instance"


@pytest.mark.asyncio
async def test_start_all_elapsed_ms_positive():
    reg = ComponentRegistry()
    reg.register("comp", _ok_factory)
    state = _AppState()
    result = await reg.start_all(state)
    assert result["comp"].elapsed_ms >= 0


# ── Optional failure — skips, does not raise ──────────────────────────────────


@pytest.mark.asyncio
async def test_optional_failure_does_not_raise():
    reg = ComponentRegistry()
    reg.register("bad", _fail_factory, required=False)
    state = _AppState()
    result = await reg.start_all(state)
    assert result["bad"].status == "failed"
    assert "factory error" in result["bad"].error
    assert getattr(state, "bad") is None


# ── Required failure — raises RuntimeError ────────────────────────────────────


@pytest.mark.asyncio
async def test_required_failure_raises():
    reg = ComponentRegistry()
    reg.register("critical", _fail_factory, required=True)
    state = _AppState()
    with pytest.raises(RuntimeError, match="critical"):
        await reg.start_all(state)


# ── Dependency skipping ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dep_failed_skips_dependent():
    reg = ComponentRegistry()
    reg.register("base", _fail_factory, required=False)
    reg.register("child", _ok_factory, required=False, deps=["base"])
    state = _AppState()
    result = await reg.start_all(state)
    assert result["base"].status == "failed"
    assert result["child"].status == "skipped"
    assert "base" in result["child"].error


@pytest.mark.asyncio
async def test_dep_ok_allows_dependent():
    reg = ComponentRegistry()
    reg.register("base", _ok_factory)
    reg.register("child", _ok_factory, deps=["base"])
    state = _AppState()
    result = await reg.start_all(state)
    assert result["base"].status == "ok"
    assert result["child"].status == "ok"


@pytest.mark.asyncio
async def test_skipped_dep_skips_grandchild():
    reg = ComponentRegistry()
    reg.register("a", _fail_factory, required=False)
    reg.register("b", _ok_factory, required=False, deps=["a"])
    reg.register("c", _ok_factory, required=False, deps=["b"])
    state = _AppState()
    result = await reg.start_all(state)
    assert result["a"].status == "failed"
    assert result["b"].status == "skipped"
    assert result["c"].status == "skipped"


# ── Topological sort ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_topological_order_respected():
    order = []

    async def _factory_a(s):
        order.append("a")
        return "a"

    async def _factory_b(s):
        order.append("b")
        return "b"

    reg = ComponentRegistry()
    reg.register("b", _factory_b, deps=["a"])
    reg.register("a", _factory_a)
    state = _AppState()
    await reg.start_all(state)
    assert order.index("a") < order.index("b")


def test_circular_dependency_raises():
    reg = ComponentRegistry()
    reg.register("x", _ok_factory, deps=["y"])
    reg.register("y", _ok_factory, deps=["x"])
    with pytest.raises(RuntimeError, match="circular"):
        reg._topological_sort()


# ── Accessors ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_returns_instance():
    reg = ComponentRegistry()
    reg.register("comp", _ok_factory)
    await reg.start_all(_AppState())
    assert reg.get("comp") == "instance"


def test_get_missing_returns_none():
    reg = ComponentRegistry()
    assert reg.get("nonexistent") is None


@pytest.mark.asyncio
async def test_all_required_ok_true():
    reg = ComponentRegistry()
    reg.register("req", _ok_factory, required=True)
    await reg.start_all(_AppState())
    assert reg.all_required_ok()


@pytest.mark.asyncio
async def test_all_required_ok_false_when_optional_fails():
    reg = ComponentRegistry()
    reg.register("req", _ok_factory, required=True)
    reg.register("opt", _fail_factory, required=False)
    await reg.start_all(_AppState())
    # Required passed, optional failed — all_required_ok should still be True
    assert reg.all_required_ok()


@pytest.mark.asyncio
async def test_summary_returns_status_dict():
    reg = ComponentRegistry()
    reg.register("a", _ok_factory)
    reg.register("b", _fail_factory, required=False)
    await reg.start_all(_AppState())
    s = reg.summary()
    assert s["a"] == "ok"
    assert s["b"] == "failed"


# ── print_table — no crash ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_print_table_no_crash():
    reg = ComponentRegistry()
    reg.register("a", _ok_factory, required=True)
    reg.register("b", _fail_factory, required=False)
    await reg.start_all(_AppState())
    reg.print_table()  # must not raise
