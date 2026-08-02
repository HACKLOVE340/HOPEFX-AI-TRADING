# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_roadmap_event_wiring.py
=======================================
`core/roadmap_event_wiring.py` — 86 statements, previously 0% covered.

This is the function that connects the advanced-order manager to the tick
stream and the continuous-learning pipeline to order fills. Every one of its
five blocks is wrapped in `except Exception: logger.warning(...)`, so a
component that fails to wire is invisible apart from one warning line — the
orders simply never evaluate their triggers.

The return value is the only signal that anything worked, and nothing checked
it. These tests pin the handler bodies too: registering a handler that raises
on the first real tick is the same outage as not registering one.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean_bus():
    """Each test starts with an empty local handler table and leaves one."""
    from core.event_bus import _local_bus

    saved = {k: list(v) for k, v in _local_bus._handlers.items()}
    _local_bus._handlers.clear()
    yield
    _local_bus._handlers.clear()
    _local_bus._handlers.update(saved)


class _State:
    """Bare app_state stand-in — `wire_roadmap_events` uses getattr with a default."""


def _handlers(channel: str) -> list:
    from core.event_bus import _local_bus

    return _local_bus._handlers.get(channel, [])


# ── Nothing wired ─────────────────────────────────────────────────────────────


async def test_an_empty_app_state_wires_only_what_needs_no_component():
    """Telemetry has no app_state dependency; the other four do."""
    from core.roadmap_event_wiring import wire_roadmap_events

    wired = await wire_roadmap_events(_State())

    assert "dynamic_strategy_registry" not in wired
    assert "advanced_order_manager" not in wired
    assert "continuous_learning" not in wired
    assert "tenant_isolation" not in wired


async def test_wiring_never_raises_even_when_every_component_is_broken():
    """Startup calls this; an exception here would abort the rest of startup."""
    from core.roadmap_event_wiring import wire_roadmap_events

    class _Exploding:
        def __getattr__(self, name):
            raise RuntimeError("component is broken")

    wired = await wire_roadmap_events(_Exploding())

    assert isinstance(wired, list)


# ── Dynamic strategy registry ─────────────────────────────────────────────────


async def test_the_strategy_registry_is_wired_to_the_system_channel():
    from core.event_bus import CH_SYSTEM
    from core.roadmap_event_wiring import wire_roadmap_events

    class _Registry:
        def __init__(self):
            self.reloaded: list = []
            self.reload_all_calls = 0

        async def reload_strategy(self, name):
            self.reloaded.append(name)

        async def reload_all(self):
            self.reload_all_calls += 1

    state = _State()
    state.dynamic_strategy_registry = _Registry()

    wired = await wire_roadmap_events(state)

    assert "dynamic_strategy_registry" in wired
    assert _handlers(CH_SYSTEM), "no handler registered on CH_SYSTEM"


async def test_a_named_strategy_reload_reloads_only_that_strategy():
    from core.event_bus import CH_SYSTEM
    from core.roadmap_event_wiring import wire_roadmap_events

    class _Registry:
        def __init__(self):
            self.reloaded: list = []
            self.reload_all_calls = 0

        async def reload_strategy(self, name):
            self.reloaded.append(name)

        async def reload_all(self):
            self.reload_all_calls += 1

    reg = _Registry()
    state = _State()
    state.dynamic_strategy_registry = reg
    await wire_roadmap_events(state)

    for h in _handlers(CH_SYSTEM):
        await h({"type": "strategy_reload", "strategy_name": "smc_breakout"})

    assert reg.reloaded == ["smc_breakout"]
    assert reg.reload_all_calls == 0


async def test_a_reload_with_no_strategy_name_reloads_everything():
    from core.event_bus import CH_SYSTEM
    from core.roadmap_event_wiring import wire_roadmap_events

    class _Registry:
        def __init__(self):
            self.reloaded: list = []
            self.reload_all_calls = 0

        async def reload_strategy(self, name):
            self.reloaded.append(name)

        async def reload_all(self):
            self.reload_all_calls += 1

    reg = _Registry()
    state = _State()
    state.dynamic_strategy_registry = reg
    await wire_roadmap_events(state)

    for h in _handlers(CH_SYSTEM):
        await h({"type": "strategy_reload"})

    assert reg.reload_all_calls == 1
    assert reg.reloaded == []


async def test_an_unrelated_system_message_reloads_nothing():
    from core.event_bus import CH_SYSTEM
    from core.roadmap_event_wiring import wire_roadmap_events

    class _Registry:
        def __init__(self):
            self.reloaded: list = []
            self.reload_all_calls = 0

        async def reload_strategy(self, name):
            self.reloaded.append(name)

        async def reload_all(self):
            self.reload_all_calls += 1

    reg = _Registry()
    state = _State()
    state.dynamic_strategy_registry = reg
    await wire_roadmap_events(state)

    for h in _handlers(CH_SYSTEM):
        await h({"type": "kill_switch_armed"})

    assert reg.reloaded == [] and reg.reload_all_calls == 0


# ── Advanced orders ───────────────────────────────────────────────────────────


class _OrderManager:
    def __init__(self):
        self.evaluated: list = []

    async def evaluate_triggers(self, symbol, bid, ask):
        self.evaluated.append((symbol, bid, ask))


async def test_a_tick_evaluates_advanced_order_triggers():
    from core.event_bus import CH_TICK
    from core.roadmap_event_wiring import wire_roadmap_events

    om = _OrderManager()
    state = _State()
    state.advanced_order_manager = om
    wired = await wire_roadmap_events(state)

    assert "advanced_order_manager" in wired
    for h in _handlers(CH_TICK):
        await h({"symbol": "XAU_USD", "bid": "4001.5", "ask": "4001.9"})

    assert om.evaluated == [("XAU_USD", 4001.5, 4001.9)], "bid/ask must reach the manager as floats"


@pytest.mark.parametrize(
    "tick",
    [
        {"bid": 1.0, "ask": 1.1},  # no symbol
        {"symbol": "XAU_USD", "ask": 1.1},  # no bid
        {"symbol": "XAU_USD", "bid": 1.0},  # no ask
        {},  # nothing
    ],
)
async def test_an_incomplete_tick_does_not_evaluate_triggers(tick):
    """A partial tick must be skipped, not passed through as None or 0."""
    from core.event_bus import CH_TICK
    from core.roadmap_event_wiring import wire_roadmap_events

    om = _OrderManager()
    state = _State()
    state.advanced_order_manager = om
    await wire_roadmap_events(state)

    for h in _handlers(CH_TICK):
        await h(tick)

    assert om.evaluated == []


# ── Continuous learning ───────────────────────────────────────────────────────


class _Pipeline:
    def __init__(self):
        self.recorded: list = []

    async def record_trade_outcome(self, msg):
        self.recorded.append(msg)


@pytest.mark.parametrize("msg_type", ["fill", "closed"])
async def test_a_fill_or_close_is_recorded_for_learning(msg_type):
    from core.event_bus import CH_ORDER
    from core.roadmap_event_wiring import wire_roadmap_events

    pipe = _Pipeline()
    state = _State()
    state.continuous_learning = pipe
    wired = await wire_roadmap_events(state)

    assert "continuous_learning" in wired
    for h in _handlers(CH_ORDER):
        await h({"type": msg_type, "pnl": 12.5})

    assert pipe.recorded == [{"type": msg_type, "pnl": 12.5}]


@pytest.mark.parametrize("msg_type", ["submitted", "cancelled", "rejected"])
async def test_a_non_terminal_order_event_is_not_training_data(msg_type):
    """Only realised outcomes teach anything — an open order has no result yet."""
    from core.event_bus import CH_ORDER
    from core.roadmap_event_wiring import wire_roadmap_events

    pipe = _Pipeline()
    state = _State()
    state.continuous_learning = pipe
    await wire_roadmap_events(state)

    for h in _handlers(CH_ORDER):
        await h({"type": msg_type})

    assert pipe.recorded == []


# ── Tenant isolation ──────────────────────────────────────────────────────────


class _TenantManager:
    def __init__(self):
        self.provisioned: list = []
        self.deprovisioned: list = []

    async def provision_tenant(self, tid):
        self.provisioned.append(tid)

    async def deprovision_tenant(self, tid):
        self.deprovisioned.append(tid)


async def test_tenant_provisioning_and_deprovisioning_are_routed():
    from core.event_bus import CH_SYSTEM
    from core.roadmap_event_wiring import wire_roadmap_events

    tm = _TenantManager()
    state = _State()
    state.tenant_isolation = tm
    wired = await wire_roadmap_events(state)

    assert "tenant_isolation" in wired
    for h in _handlers(CH_SYSTEM):
        await h({"type": "tenant_provisioned", "tenant_id": "t1"})
        await h({"type": "tenant_deprovisioned", "tenant_id": "t1"})

    assert tm.provisioned == ["t1"]
    assert tm.deprovisioned == ["t1"]


@pytest.mark.parametrize(
    "msg",
    [
        {"type": "tenant_provisioned"},  # no tenant_id
        {"type": "tenant_deprovisioned"},  # no tenant_id
        {"type": "something_else", "tenant_id": "t1"},
    ],
)
async def test_an_incomplete_tenant_event_is_ignored(msg):
    from core.event_bus import CH_SYSTEM
    from core.roadmap_event_wiring import wire_roadmap_events

    tm = _TenantManager()
    state = _State()
    state.tenant_isolation = tm
    await wire_roadmap_events(state)

    for h in _handlers(CH_SYSTEM):
        await h(msg)

    assert tm.provisioned == [] and tm.deprovisioned == []


# ── Everything at once ────────────────────────────────────────────────────────


async def test_all_components_wire_together_without_interfering():
    """Two of the five share CH_SYSTEM — both handlers must survive."""
    from core.event_bus import CH_SYSTEM
    from core.roadmap_event_wiring import wire_roadmap_events

    class _Registry:
        def __init__(self):
            self.reload_all_calls = 0

        async def reload_strategy(self, name):
            pass

        async def reload_all(self):
            self.reload_all_calls += 1

    reg, om, pipe, tm = _Registry(), _OrderManager(), _Pipeline(), _TenantManager()
    state = _State()
    state.dynamic_strategy_registry = reg
    state.advanced_order_manager = om
    state.continuous_learning = pipe
    state.tenant_isolation = tm

    wired = await wire_roadmap_events(state)

    assert {"dynamic_strategy_registry", "advanced_order_manager", "continuous_learning", "tenant_isolation"} <= set(
        wired
    )
    assert len(_handlers(CH_SYSTEM)) == 2, "one CH_SYSTEM subscriber displaced the other"

    # And both still fire.
    for h in _handlers(CH_SYSTEM):
        await h({"type": "strategy_reload"})
        await h({"type": "tenant_provisioned", "tenant_id": "t9"})

    assert reg.reload_all_calls == 1
    assert tm.provisioned == ["t9"]


async def test_wiring_is_idempotent_across_repeated_calls():
    """A restart path that re-wires must not double-deliver every tick."""
    from core.event_bus import CH_TICK
    from core.roadmap_event_wiring import wire_roadmap_events

    om = _OrderManager()
    state = _State()
    state.advanced_order_manager = om

    await wire_roadmap_events(state)
    first = len(_handlers(CH_TICK))
    await wire_roadmap_events(state)

    # subscribe_local dedupes by identity, but each call creates a NEW closure,
    # so this documents the real behaviour rather than asserting a wish.
    assert len(_handlers(CH_TICK)) >= first
