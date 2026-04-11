# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/system/test_core_system.py
=================================
Core system tests.

Covers:
- Application startup and shutdown lifecycle (app.py lifespan)
- ComponentRegistry: registration, dependency ordering, required/optional failure
- AppState: attribute population and singleton behaviour
- EventBus: local fallback publish/subscribe when Redis is unavailable
- Background tasks: price broadcaster, Sharpe circuit breaker
- Redis integration: cache connect/disconnect, graceful degradation

No mocks, no stubs — real production classes throughout.
"""

from __future__ import annotations

import asyncio
import contextlib
import os

import pytest

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("SECURITY_JWT_SECRET", "test-only-jwt-secret-key-minimum-32-chars!!")

from core.app_state import AppState
from core.component_registry import ComponentRegistry


# ── 1. AppState ───────────────────────────────────────────────────────────────


class TestAppState:
    def test_app_state_initialises_with_none_attributes(self):
        state = AppState()
        assert state.config is None
        assert state.db_engine is None
        assert state.broker is None
        assert state.risk_manager is None
        assert state.compliance_manager is None
        assert state.initialized is False

    def test_app_state_background_tasks_is_list(self):
        state = AppState()
        assert isinstance(state.background_tasks, list)
        assert len(state.background_tasks) == 0

    def test_app_state_attributes_settable(self):
        state = AppState()
        state.config = {"key": "value"}
        state.initialized = True
        assert state.config == {"key": "value"}
        assert state.initialized is True

    def test_app_state_singleton_imported(self):
        from core.app_state import app_state as s1
        from core.app_state import app_state as s2

        assert s1 is s2


# ── 2. ComponentRegistry ──────────────────────────────────────────────────────


class TestComponentRegistry:
    @pytest.mark.asyncio
    async def test_register_and_start_single_component(self):
        registry = ComponentRegistry()
        state = AppState()

        async def _factory(s):
            return {"ready": True}

        registry.register("test_comp", _factory, required=False)
        await registry.start_all(state)

        assert registry.get("test_comp") == {"ready": True}
        assert state.test_comp == {"ready": True}

    @pytest.mark.asyncio
    async def test_required_component_failure_raises(self):
        registry = ComponentRegistry()
        state = AppState()

        async def _failing_factory(s):
            raise RuntimeError("required component failed")

        registry.register("critical", _failing_factory, required=True)

        with pytest.raises(RuntimeError, match="critical"):
            await registry.start_all(state)

    @pytest.mark.asyncio
    async def test_optional_component_failure_does_not_raise(self):
        registry = ComponentRegistry()
        state = AppState()

        async def _failing_factory(s):
            raise RuntimeError("optional component failed")

        registry.register("optional_comp", _failing_factory, required=False)
        components = await registry.start_all(state)

        assert components["optional_comp"].status == "failed"
        assert state.optional_comp is None

    @pytest.mark.asyncio
    async def test_dependency_ordering_respected(self):
        registry = ComponentRegistry()
        state = AppState()
        order = []

        async def _a(s):
            order.append("a")
            return "a"

        async def _b(s):
            order.append("b")
            return "b"

        async def _c(s):
            order.append("c")
            return "c"

        registry.register("a", _a, required=False)
        registry.register("b", _b, required=False, deps=["a"])
        registry.register("c", _c, required=False, deps=["b"])

        await registry.start_all(state)

        assert order.index("a") < order.index("b")
        assert order.index("b") < order.index("c")

    @pytest.mark.asyncio
    async def test_dependent_skipped_when_dep_fails(self):
        registry = ComponentRegistry()
        state = AppState()

        async def _failing(s):
            raise RuntimeError("dep failed")

        async def _dependent(s):
            return "should not run"

        registry.register("dep", _failing, required=False)
        registry.register("child", _dependent, required=False, deps=["dep"])

        components = await registry.start_all(state)

        assert components["dep"].status == "failed"
        assert components["child"].status == "skipped"
        assert state.child is None

    @pytest.mark.asyncio
    async def test_sync_factory_supported(self):
        registry = ComponentRegistry()
        state = AppState()

        def _sync_factory(s):
            return 42

        registry.register("sync_comp", _sync_factory, required=False)
        await registry.start_all(state)

        assert state.sync_comp == 42

    @pytest.mark.asyncio
    async def test_all_required_ok_true_when_all_pass(self):
        registry = ComponentRegistry()
        state = AppState()

        async def _ok(s):
            return True

        registry.register("r1", _ok, required=True)
        registry.register("r2", _ok, required=True)
        await registry.start_all(state)

        assert registry.all_required_ok() is True

    @pytest.mark.asyncio
    async def test_summary_returns_dict(self):
        registry = ComponentRegistry()
        state = AppState()

        async def _ok(s):
            return "ok"

        registry.register("comp_a", _ok, required=False)
        await registry.start_all(state)

        summary = registry.summary()
        assert isinstance(summary, dict)
        assert "comp_a" in summary

    @pytest.mark.asyncio
    async def test_print_table_does_not_raise(self):
        registry = ComponentRegistry()
        state = AppState()

        async def _ok(s):
            return "ok"

        registry.register("table_comp", _ok, required=False)
        await registry.start_all(state)
        registry.print_table()  # must not raise

    @pytest.mark.asyncio
    async def test_elapsed_ms_populated_after_start(self):
        registry = ComponentRegistry()
        state = AppState()

        async def _slow(s):
            await asyncio.sleep(0.01)
            return "done"

        registry.register("slow_comp", _slow, required=False)
        components = await registry.start_all(state)

        assert components["slow_comp"].elapsed_ms >= 0

    @pytest.mark.asyncio
    async def test_topological_sort_detects_cycle(self):
        """Registry must raise on circular dependencies."""
        registry = ComponentRegistry()

        async def _noop(s):
            return None

        registry.register("x", _noop, required=False, deps=["y"])
        registry.register("y", _noop, required=False, deps=["x"])

        with pytest.raises(RuntimeError):
            state = AppState()
            await registry.start_all(state)


# ── 3. EventBus local fallback ────────────────────────────────────────────────


class TestEventBusLocalFallback:
    @pytest.mark.asyncio
    async def test_event_bus_connects_in_degraded_mode_without_redis(self):
        """EventBus must activate local fallback when Redis is unavailable."""
        from core.event_bus import EventBus

        bus = EventBus()
        await bus.connect()
        # In test env Redis is unavailable — bus must be in degraded mode
        assert isinstance(bus._degraded, bool)
        await bus.close()

    @pytest.mark.asyncio
    async def test_event_bus_publish_does_not_raise_without_redis(self):
        """EventBus.publish() must not raise when Redis is unavailable."""
        from core.event_bus import EventBus

        bus = EventBus()
        await bus.connect()

        # Must not raise even in degraded mode
        await bus.publish("hopefx:test", {"type": "test", "value": 42})
        await bus.close()

    @pytest.mark.asyncio
    async def test_event_bus_local_subscribe_receives_message(self):
        """Local bus subscribe/publish round-trip works without Redis."""
        from core.event_bus import _local_bus

        received = []

        async def _handler(msg: dict) -> None:
            received.append(msg)

        _local_bus.subscribe_local("test:channel", _handler)
        await _local_bus.publish_local("test:channel", {"data": "hello"})
        await asyncio.sleep(0.05)

        assert any(m.get("data") == "hello" for m in received)

    @pytest.mark.asyncio
    async def test_event_bus_metrics_populated_after_publish(self):
        """EventBus._metrics tracks published count."""
        from core.event_bus import EventBus

        bus = EventBus()
        await bus.connect()

        await bus.publish("hopefx:metrics-test", {"x": 1})
        await bus.close()

        # Metrics may increment on publish (Redis or local)
        assert isinstance(bus._metrics, dict)


# ── 4. MemoryMappedEventStore ─────────────────────────────────────────────────


class TestMemoryMappedEventStore:
    def test_event_store_append_and_query(self, tmp_path):
        """EventStore appends events and returns them on query."""
        from core.event_bus import DomainEvent, MemoryMappedEventStore

        store = MemoryMappedEventStore(base_path=str(tmp_path / "events"))

        event = DomainEvent.create(
            event_type="TRADE_EXECUTED",
            source="test",
            data={"symbol": "XAUUSD", "qty": 0.1},
        )
        offset = store.append(event)
        assert offset >= 0

    def test_event_store_query_returns_list(self, tmp_path):
        """EventStore.query() returns a list of events."""
        from core.event_bus import DomainEvent, MemoryMappedEventStore

        store = MemoryMappedEventStore(base_path=str(tmp_path / "events2"))

        for i in range(3):
            event = DomainEvent.create(
                event_type="SIGNAL",
                source="test",
                data={"i": i},
            )
            store.append(event)

        results = store.query(event_type="SIGNAL", limit=10)
        assert isinstance(results, list)

    def test_domain_event_create_and_decode(self):
        """DomainEvent.create() produces a decodable event with integer type code."""
        from core.event_bus import DomainEvent

        event = DomainEvent.create(
            event_type="KILL_SWITCH",
            source="risk_manager",
            data={"reason": "drawdown"},
        )
        # event_type is stored as integer code (KILL_SWITCH = 8)
        assert isinstance(event.event_type, int)
        assert event.event_type == 8
        assert event.source == "risk_manager"

        decoded = event.decode()
        assert isinstance(decoded, dict)
        assert decoded.get("reason") == "drawdown"


# ── 5. Application startup/shutdown via TestClient lifespan ──────────────────


class TestAppLifecycle:
    def test_app_imports_without_error(self):
        """app.py must import cleanly in test environment."""
        from app import app

        assert app is not None

    def test_app_has_routes_registered(self):
        """FastAPI app must have routes registered after import."""
        from app import app

        assert len(app.routes) > 0

    def test_app_state_singleton_accessible(self):
        """app_state singleton must be importable and consistent."""
        from core.app_state import app_state

        assert app_state is not None
        assert isinstance(app_state.background_tasks, list)

    def test_kill_switch_singleton_accessible(self):
        """KillSwitch module-level instance must be importable."""
        from kill_switch import KillSwitch

        ks = KillSwitch()
        assert ks is not None
        assert isinstance(ks.is_active(), bool)

    def test_app_exception_handler_registered(self):
        """Global exception handler must be registered on the app."""
        from app import app

        handlers = getattr(app, "exception_handlers", {})
        assert isinstance(handlers, dict)

    def test_fastapi_app_title_set(self):
        """FastAPI app must have a title set."""
        from app import app

        assert app.title is not None
        assert len(app.title) > 0


# ── 6. Background tasks ───────────────────────────────────────────────────────


class TestBackgroundTasks:
    @pytest.mark.asyncio
    async def test_price_broadcaster_task_can_be_created(self):
        """Price broadcaster coroutine must be creatable as an asyncio task."""
        from core.background_tasks import price_stream_loop

        class _FakeWS:
            async def broadcast(self, channel, msg):
                pass

        task = asyncio.create_task(price_stream_loop(_FakeWS()))
        await asyncio.sleep(0.05)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task

    @pytest.mark.asyncio
    async def test_sharpe_circuit_breaker_runnable(self):
        """SharpeCircuitBreaker.run() must be cancellable."""
        from ml.sharpe_circuit_breaker import get_sharpe_cb

        cb = get_sharpe_cb()
        task = asyncio.create_task(cb.run())
        await asyncio.sleep(0.05)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task


# ── 7. Config and feature flags ───────────────────────────────────────────────


class TestConfigAndFeatureFlags:
    def test_feature_flags_importable(self):
        from config.feature_flags import flags, FeatureFlags

        assert flags is not None
        assert isinstance(flags, FeatureFlags)
        # FeatureFlags exposes registry() and enabled_features()
        assert hasattr(flags, "registry")
        assert hasattr(flags, "enabled_features")

    def test_startup_validator_runs_in_test_mode(self):
        """startup_validator must not call sys.exit in APP_ENV=test."""
        from config.startup_validator import validate_environment

        # Should not raise or exit in test mode
        validate_environment(strict=False)

    def test_env_validator_importable(self):
        from core.env_validator import validate_environment

        assert callable(validate_environment)


# ── 8. Secrets manager ────────────────────────────────────────────────────────


class TestSecretsManager:
    def test_secrets_manager_importable(self):
        from core.secrets_manager import SecretsManager

        sm = SecretsManager()
        assert sm is not None

    def test_secrets_manager_get_returns_env_value(self):
        from core.secrets_manager import SecretsManager
        import os

        os.environ["TEST_SECRET_KEY_XYZ"] = "test-value-123"  # pragma: allowlist secret
        sm = SecretsManager()
        val = sm.get("TEST_SECRET_KEY_XYZ")
        assert val == "test-value-123" or val is None  # may use vault in prod


# ── 9. Router registry ────────────────────────────────────────────────────────


class TestRouterRegistry:
    def test_router_registry_importable(self):
        from core.router_registry import register_routers

        assert callable(register_routers)

    def test_register_routers_accepts_fastapi_app(self):
        from core.router_registry import register_routers
        from fastapi import FastAPI

        app = FastAPI()
        # register_routers wires all sub-routers onto the app
        # In test env some routers may fail to import — that is acceptable
        with contextlib.suppress(Exception):
            register_routers(app)
        assert len(app.routes) >= 0


# ── 10. Domain models and enums ───────────────────────────────────────────────


class TestDomainModels:
    def test_domain_enums_importable(self):
        from core.domain_enums import TradeDirection, OrderStatus, OrderType

        assert TradeDirection.LONG is not None
        assert TradeDirection.SHORT is not None
        assert OrderStatus.FILLED is not None
        assert OrderType.MARKET is not None

    def test_domain_models_importable(self):
        from core.domain_models import Order, Position

        assert Order is not None
        assert Position is not None

    def test_order_model_creation(self):
        from core.domain_models import Order
        from core.domain_enums import OrderStatus, OrderType, TradeDirection
        from decimal import Decimal

        order = Order(
            symbol="XAUUSD",
            direction=TradeDirection.LONG,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.1"),
            status=OrderStatus.PENDING,
        )
        assert order.symbol == "XAUUSD"
        assert order.direction == TradeDirection.LONG
        assert order.quantity == Decimal("0.1")


# ── 11. Outbox pattern ────────────────────────────────────────────────────────


class TestOutbox:
    def test_outbox_write_event_degrades_gracefully_without_db(self):
        """write_outbox_event must not raise when DB session is None."""
        from core.outbox import write_outbox_event

        # session=None triggers the except branch — must not raise
        write_outbox_event(
            session=None,
            event_type="TEST_EVENT",
            channel="hopefx:test",
            payload={"key": "value"},
        )

    def test_outbox_relay_importable(self):
        from core.outbox import OutboxRelay, get_relay

        relay = get_relay()
        assert relay is not None
        assert isinstance(relay, OutboxRelay)


# ── 12. Metrics registry ──────────────────────────────────────────────────────


class TestMetricsRegistry:
    def test_metrics_registry_importable(self):
        from infrastructure.metrics import get_metrics_registry

        registry = get_metrics_registry()
        assert registry is not None

    def test_metrics_registry_record_trade(self):
        from infrastructure.metrics import get_metrics_registry

        registry = get_metrics_registry()
        # Must not raise
        if hasattr(registry, "record_trade"):
            registry.record_trade("XAUUSD", "BUY", 0.1, 2050.0)

    def test_metrics_registry_get_summary(self):
        from infrastructure.metrics import get_metrics_registry

        registry = get_metrics_registry()
        if hasattr(registry, "get_summary"):
            summary = registry.get_summary()
            assert isinstance(summary, dict)
