# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""`execution/execution.py` — the wiring that starts the execution pipeline.

The module is the single entry point for the live pipeline: orchestrator, risk
manager, gatekeeper, router, brokers, engine, health loop, signal handlers. It
measured 17.75% under the per-module gate, with 232 of 291 statements never
executed — the safety gate below among them, which had no test of any kind.

Mocks here are `create_autospec` rather than bare `MagicMock` wherever the
production call depends on a signature. A specless mock accepts arguments the
real object rejects, which is how F242 and F248 shipped: three alert call sites
passed keyword arguments the target did not accept, every call raised
`TypeError`, and the tests were green because the mock agreed with all of them.
"""

from __future__ import annotations

import asyncio
import json
import logging
import pathlib
import signal
import sys
from unittest.mock import create_autospec, patch

import pytest

pytestmark = pytest.mark.unit

REPO = pathlib.Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from execution import execution as ex


class _HasMetrics:
    """Signature source for `create_autospec`. `health()` calls `.metrics()` on
    four components; a specless mock would also accept `.metricts()`."""

    def metrics(self) -> dict:  # pragma: no cover - spec only
        return {}


class _HasHealth:
    def health(self) -> dict:  # pragma: no cover - spec only
        return {}


class TestTheLatencyOptimisationGateIsFailClosed:
    """`_check_latency_opt_gate` decides whether the C++ shim may load.

    Its own docstring states the reason it exists: "This prevents optimising
    latency before the first trade." Every one of its five paths returns False
    except the last, and nothing exercised any of them.

    The gate is read at import time into `_LATENCY_OPT_UNLOCKED`, so the tests
    patch the module attribute rather than the environment: setting the env var
    inside a test would change nothing, and a test that cannot fail is worse
    than no test.
    """

    def test_it_blocks_when_the_phase_flag_is_not_set(self) -> None:
        with patch.object(ex, "_LATENCY_OPT_UNLOCKED", False):
            assert ex._check_latency_opt_gate() is False

    def test_it_blocks_when_paper_fills_are_short_of_five_hundred(self) -> None:
        gate = type("G", (), {"_state": {"fill_count": 499}})
        module = type("M", (), {"PaperTradingGate": lambda self=None: gate()})
        with (
            patch.object(ex, "_LATENCY_OPT_UNLOCKED", True),
            patch.dict(sys.modules, {"research.pipeline.paper_trading_gate": module}),
        ):
            assert ex._check_latency_opt_gate() is False

    def test_an_unreadable_paper_gate_blocks_rather_than_passes(self) -> None:
        """Fail-closed. An unmeasured precondition is not a satisfied one."""

        class Boom:
            def __init__(self) -> None:
                raise RuntimeError("state file corrupt")

        module = type("M", (), {"PaperTradingGate": Boom})
        with (
            patch.object(ex, "_LATENCY_OPT_UNLOCKED", True),
            patch.dict(sys.modules, {"research.pipeline.paper_trading_gate": module}),
        ):
            assert ex._check_latency_opt_gate() is False

    def test_it_blocks_when_live_fills_are_short(self, monkeypatch) -> None:
        gate = type("G", (), {"_state": {"fill_count": 500}})
        module = type("M", (), {"PaperTradingGate": lambda self=None: gate()})
        monkeypatch.setenv("LIVE_FILL_COUNT", "99")
        with (
            patch.object(ex, "_LATENCY_OPT_UNLOCKED", True),
            patch.object(ex, "_LATENCY_OPT_MIN_LIVE_FILLS", 100),
            patch.dict(sys.modules, {"research.pipeline.paper_trading_gate": module}),
        ):
            assert ex._check_latency_opt_gate() is False

    def test_it_unlocks_only_when_all_three_conditions_hold(self, monkeypatch) -> None:
        gate = type("G", (), {"_state": {"fill_count": 500}})
        module = type("M", (), {"PaperTradingGate": lambda self=None: gate()})
        monkeypatch.setenv("LIVE_FILL_COUNT", "100")
        with (
            patch.object(ex, "_LATENCY_OPT_UNLOCKED", True),
            patch.object(ex, "_LATENCY_OPT_MIN_LIVE_FILLS", 100),
            patch.dict(sys.modules, {"research.pipeline.paper_trading_gate": module}),
        ):
            assert ex._check_latency_opt_gate() is True

    def test_a_missing_live_fill_count_reads_as_zero_not_as_enough(self, monkeypatch) -> None:
        """An absent measurement is the worst case, never the best one."""
        gate = type("G", (), {"_state": {"fill_count": 500}})
        module = type("M", (), {"PaperTradingGate": lambda self=None: gate()})
        monkeypatch.delenv("LIVE_FILL_COUNT", raising=False)
        with (
            patch.object(ex, "_LATENCY_OPT_UNLOCKED", True),
            patch.object(ex, "_LATENCY_OPT_MIN_LIVE_FILLS", 1),
            patch.dict(sys.modules, {"research.pipeline.paper_trading_gate": module}),
        ):
            assert ex._check_latency_opt_gate() is False


class TestTheSystemIsInertUntilStarted:
    """Construction must wire nothing. A constructor that connects a broker
    makes the object impossible to build in a test, and impossible to inspect
    before it is running."""

    def test_construction_holds_no_components(self) -> None:
        system = ExecutionSystem_or_skip()
        for attr in ("_orchestrator", "_lineage", "_risk", "_gatekeeper", "_router", "_engine"):
            assert getattr(system, attr) is None, f"{attr} was built in __init__"
        assert system._brokers == {}
        assert system._tasks == []

    def test_it_reports_not_started_before_start(self) -> None:
        assert ExecutionSystem_or_skip().health()["started"] is False

    def test_health_is_readable_before_anything_is_wired(self) -> None:
        """An operator reads health when things are wrong, which is exactly
        when half the components are absent. Every component slot is None here,
        so each of the five conditional branches takes its empty side; if any
        of them dereferenced unconditionally this would raise."""
        health = ExecutionSystem_or_skip().health()
        assert health["uptime_s"] == 0
        for key in ("engine", "risk", "gatekeeper", "router", "orchestrator"):
            assert health[key] == {}, f"{key} reported something while unwired"

    def test_an_inference_function_is_held_not_called(self) -> None:
        fn = create_autospec(lambda *a, **k: None)
        system = ExecutionSystem_or_skip(ml_inference_fn=fn)
        assert system._ml_inference_fn is fn
        fn.assert_not_called()

    def test_health_reports_each_component_once_it_is_wired(self) -> None:
        """The other side of every branch above, so the pairs are covered."""
        system = ExecutionSystem_or_skip()
        for attr, key in (
            ("_engine", "engine"),
            ("_risk", "risk"),
            ("_gatekeeper", "gatekeeper"),
            ("_router", "router"),
        ):
            component = create_autospec(_HasMetrics, instance=True)
            component.metrics.return_value = {"seen": key}
            setattr(system, attr, component)
        orchestrator = create_autospec(_HasHealth, instance=True)
        orchestrator.health.return_value = {"seen": "orchestrator"}
        system._orchestrator = orchestrator

        health = system.health()
        for key in ("engine", "risk", "gatekeeper", "router", "orchestrator"):
            assert health[key] == {"seen": key}


def ExecutionSystem_or_skip(**kwargs):
    """Build the system, or skip if construction needs more than the tree gives."""
    try:
        return ex.ExecutionSystem(**kwargs)
    except Exception as exc:  # pragma: no cover - environment guard
        pytest.skip(f"ExecutionSystem could not be constructed here: {exc}")


class _Redis:
    """Signature source: `notify_fill` uses exactly these three."""

    def lpush(self, key, value):  # pragma: no cover - spec only
        ...

    def ltrim(self, key, start, stop):  # pragma: no cover - spec only
        ...

    def expire(self, key, ttl):  # pragma: no cover - spec only
        ...


class _Replay:
    def on_fill(self, *, symbol, fill_price, quantity, direction, fill_id):  # pragma: no cover - spec only
        ...


class _Broker:
    """Signature source for the broker autospecs."""

    async def connect(self) -> bool:  # pragma: no cover - spec only
        return True


class _SyncBroker:
    """CME and the C++ shim call `connect()` synchronously."""

    def connect(self) -> bool:  # pragma: no cover - spec only
        return True


def _module_with(name: str, obj: object):
    """A stand-in module exposing one attribute, for `patch.dict(sys.modules)`."""
    return type("M", (), {name: obj})


class TestConnectingABrokerNeverRaisesIntoStartup:
    """The four connect helpers each return a broker or ``None``.

    Startup calls them in sequence, so a helper that raised would take the whole
    pipeline down because one venue was unreachable. Each has four paths —
    missing credentials, connected, refused, and raised — and none of them was
    executed by any test.

    A helper returning ``None`` is the signal that the venue is absent. Returning
    a half-built broker instead would put an object that cannot fill orders into
    the router's table, which is the failure this shape exists to prevent.
    """

    def test_oanda_is_skipped_when_credentials_are_absent(self) -> None:
        settings = _module_with("resolve_oanda_account", lambda: None)
        settings.resolve_oanda_token = lambda: None
        with patch.dict(sys.modules, {"config.settings": settings}):
            assert asyncio.run(ex._connect_oanda()) is None

    def test_oanda_is_skipped_when_only_the_token_is_present(self) -> None:
        """Both halves are required; one alone must not look like credentials."""
        settings = _module_with("resolve_oanda_account", lambda: None)
        settings.resolve_oanda_token = lambda: "tok"
        with patch.dict(sys.modules, {"config.settings": settings}):
            assert asyncio.run(ex._connect_oanda()) is None

    def test_oanda_returns_the_broker_when_the_connection_is_accepted(self) -> None:
        settings = _module_with("resolve_oanda_account", lambda: "acct")
        settings.resolve_oanda_token = lambda: "tok"
        broker = create_autospec(_Broker, instance=True)
        broker.connect.return_value = True
        with (
            patch.dict(sys.modules, {"config.settings": settings}),
            patch.dict(sys.modules, {"brokers.oanda": _module_with("OANDABroker", lambda cfg: broker)}),
        ):
            assert asyncio.run(ex._connect_oanda()) is broker

    def test_oanda_returns_none_when_the_connection_is_refused(self) -> None:
        settings = _module_with("resolve_oanda_account", lambda: "acct")
        settings.resolve_oanda_token = lambda: "tok"
        broker = create_autospec(_Broker, instance=True)
        broker.connect.return_value = False
        with (
            patch.dict(sys.modules, {"config.settings": settings}),
            patch.dict(sys.modules, {"brokers.oanda": _module_with("OANDABroker", lambda cfg: broker)}),
        ):
            assert asyncio.run(ex._connect_oanda()) is None

    def test_oanda_swallows_an_init_error_rather_than_failing_startup(self) -> None:
        settings = _module_with("resolve_oanda_account", lambda: "acct")
        settings.resolve_oanda_token = lambda: "tok"

        def boom(cfg):
            raise RuntimeError("bad config")

        with (
            patch.dict(sys.modules, {"config.settings": settings}),
            patch.dict(sys.modules, {"brokers.oanda": _module_with("OANDABroker", boom)}),
        ):
            assert asyncio.run(ex._connect_oanda()) is None

    def test_ibkr_returns_the_broker_when_connected(self) -> None:
        broker = create_autospec(_Broker, instance=True)
        broker.connect.return_value = True
        with patch.dict(sys.modules, {"brokers.ibkr": _module_with("IBKRBroker", lambda cfg: broker)}):
            assert asyncio.run(ex._connect_ibkr()) is broker

    def test_ibkr_returns_none_when_tws_refuses(self) -> None:
        broker = create_autospec(_Broker, instance=True)
        broker.connect.return_value = False
        with patch.dict(sys.modules, {"brokers.ibkr": _module_with("IBKRBroker", lambda cfg: broker)}):
            assert asyncio.run(ex._connect_ibkr()) is None

    def test_ibkr_swallows_an_init_error(self) -> None:
        def boom(cfg):
            raise ValueError("no port")

        with patch.dict(sys.modules, {"brokers.ibkr": _module_with("IBKRBroker", boom)}):
            assert asyncio.run(ex._connect_ibkr()) is None

    def test_cme_returns_the_connector_when_connected(self) -> None:
        broker = create_autospec(_SyncBroker, instance=True)
        broker.connect.return_value = True
        broker._fix_available = True
        broker._ibkr_available = False
        broker._paper_fallback = False
        connector = type("C", (), {"from_env": staticmethod(lambda: broker)})
        with patch.dict(sys.modules, {"brokers.cme_comex": _module_with("CMEComexConnector", connector)}):
            assert asyncio.run(ex._connect_cme()) is broker

    def test_cme_returns_none_when_refused(self) -> None:
        broker = create_autospec(_SyncBroker, instance=True)
        broker.connect.return_value = False
        connector = type("C", (), {"from_env": staticmethod(lambda: broker)})
        with patch.dict(sys.modules, {"brokers.cme_comex": _module_with("CMEComexConnector", connector)}):
            assert asyncio.run(ex._connect_cme()) is None

    def test_cme_swallows_an_init_error(self) -> None:
        def boom():
            raise RuntimeError("fix session refused")

        connector = type("C", (), {"from_env": staticmethod(boom)})
        with patch.dict(sys.modules, {"brokers.cme_comex": _module_with("CMEComexConnector", connector)}):
            assert asyncio.run(ex._connect_cme()) is None

    def test_the_cpp_shim_returns_the_connector_when_connected(self) -> None:
        broker = create_autospec(_SyncBroker, instance=True)
        broker.connect.return_value = True
        broker._cmd_addr = "tcp://127.0.0.1:5555"
        connector = type("C", (), {"from_env": staticmethod(lambda: broker)})
        with patch.dict(sys.modules, {"brokers.cpp_shim_connector": _module_with("CPPShimConnector", connector)}):
            assert asyncio.run(ex._connect_cpp_shim()) is broker

    def test_the_cpp_shim_returns_none_when_it_is_not_running(self) -> None:
        broker = create_autospec(_SyncBroker, instance=True)
        broker.connect.return_value = False
        connector = type("C", (), {"from_env": staticmethod(lambda: broker)})
        with patch.dict(sys.modules, {"brokers.cpp_shim_connector": _module_with("CPPShimConnector", connector)}):
            assert asyncio.run(ex._connect_cpp_shim()) is None

    def test_the_cpp_shim_swallows_an_init_error(self) -> None:
        def boom():
            raise ImportError("pyzmq missing")

        connector = type("C", (), {"from_env": staticmethod(boom)})
        with patch.dict(sys.modules, {"brokers.cpp_shim_connector": _module_with("CPPShimConnector", connector)}):
            assert asyncio.run(ex._connect_cpp_shim()) is None


class TestThePaperBrokerRefusesToBeHalfBuilt:
    """`_build_paper_broker` is the last resort when no venue connected, and it
    is the one helper that RAISES instead of returning ``None``.

    That asymmetry is deliberate and worth pinning: the others returning ``None``
    means "this venue is absent", and startup continues to the next. The paper
    broker is the floor. If it cannot be built there is nothing left to execute
    against, and returning ``None`` would let the pipeline start with an empty
    broker table — a system that looks running and can fill nothing.
    """

    def test_it_returns_the_broker(self) -> None:
        broker = object()
        with patch.dict(
            sys.modules,
            {"brokers.paper_trading": _module_with("PaperTradingBroker", lambda config: broker)},
        ):
            assert ex._build_paper_broker() is broker

    def test_it_raises_rather_than_returning_none(self) -> None:
        def boom(config):
            raise ImportError("paper broker missing")

        with patch.dict(
            sys.modules,
            {"brokers.paper_trading": _module_with("PaperTradingBroker", boom)},
        ):
            with pytest.raises(RuntimeError, match="Cannot start paper broker"):
                ex._build_paper_broker()


class TestTheFillNotificationKeepsTheCallerRunning:
    """`_wire_notify_fill` attaches the callback the engine invokes on every
    confirmed fill, to keep the Redis cache and the replay engine consistent
    with what actually executed.

    It is on the money path and none of it was executed by a test. The tests
    assert OUTCOMES — the record written, the replay engine told, the caller
    never interrupted — rather than the log level, so that raising the log
    level on the swallowed failures (see below) does not turn them red.

    Recorded and NOT changed here: both handlers log at `logger.debug`, which
    is off in production. A fill whose cache write or replay notification fails
    therefore corrects nothing and tells nobody, which is the exact state this
    function exists to prevent. That is `hopefx-dead-controls` sub-shape 4 and
    the F248 shape; changing it alters money-path behaviour, so it is reported
    rather than slipped into a coverage commit.
    """

    @staticmethod
    def _orchestrator(redis=None, replay=None):
        orch = type("O", (), {})()
        orch._redis = redis
        orch._replay = replay if replay is not None else create_autospec(_Replay, instance=True)
        return orch

    def test_an_orchestrator_that_already_has_one_is_left_alone(self) -> None:
        """Re-wiring would replace a live callback mid-session."""
        sentinel = object()
        orch = type("O", (), {})()
        orch.notify_fill = sentinel
        ex._wire_notify_fill(orch)
        assert orch.notify_fill is sentinel

    def test_it_attaches_a_callback_when_there_is_none(self) -> None:
        orch = self._orchestrator()
        ex._wire_notify_fill(orch)
        assert callable(orch.notify_fill)

    def test_a_fill_is_recorded_under_its_symbol_and_bounded(self) -> None:
        redis = create_autospec(_Redis, instance=True)
        orch = self._orchestrator(redis=redis)
        ex._wire_notify_fill(orch)

        orch.notify_fill("XAUUSD", "BUY", 1.5, 2401.25, "f1", "s1", "oanda", 12.0)

        key = redis.lpush.call_args[0][0]
        assert key == "hopefx:fills:XAUUSD"
        record = json.loads(redis.lpush.call_args[0][1])
        assert record["fill_id"] == "f1"
        assert record["fill_price"] == 2401.25
        assert record["quantity"] == 1.5
        assert record["broker"] == "oanda"
        # Bounded and expiring: an unbounded fill list is an OOM with a delay.
        redis.ltrim.assert_called_once_with(key, 0, 999)
        redis.expire.assert_called_once_with(key, 86400)

    def test_no_redis_means_no_write_and_no_error(self) -> None:
        orch = self._orchestrator(redis=None)
        ex._wire_notify_fill(orch)
        orch.notify_fill("XAUUSD", "BUY", 1.0, 2400.0, "f", "s", "paper", 1.0)

    def test_a_redis_failure_does_not_reach_the_caller(self) -> None:
        """The fill already happened. Raising here cannot un-fill it, and would
        break the engine loop on the tick after a real execution."""
        redis = create_autospec(_Redis, instance=True)
        redis.lpush.side_effect = RuntimeError("redis down")
        orch = self._orchestrator(redis=redis)
        ex._wire_notify_fill(orch)
        orch.notify_fill("XAUUSD", "SELL", 2.0, 2399.0, "f2", "s2", "ibkr", 8.0)

    def test_the_replay_engine_is_told_what_actually_filled(self) -> None:
        replay = create_autospec(_Replay, instance=True)
        orch = self._orchestrator(replay=replay)
        ex._wire_notify_fill(orch)

        orch.notify_fill("XAUUSD", "BUY", 3.0, 2402.5, "f3", "s3", "cme", 4.0)

        replay.on_fill.assert_called_once_with(
            symbol="XAUUSD", fill_price=2402.5, quantity=3.0, direction="BUY", fill_id="f3"
        )

    def test_a_replay_failure_does_not_reach_the_caller(self) -> None:
        replay = create_autospec(_Replay, instance=True)
        replay.on_fill.side_effect = ValueError("replay closed")
        orch = self._orchestrator(replay=replay)
        ex._wire_notify_fill(orch)
        orch.notify_fill("XAUUSD", "BUY", 1.0, 2400.0, "f4", "s4", "paper", 2.0)

    def test_the_cache_write_and_the_replay_call_are_independent(self) -> None:
        """A dead Redis must not cost the replay engine its notification: the
        two are separate `try` blocks and this pins that they stay separate."""
        redis = create_autospec(_Redis, instance=True)
        redis.lpush.side_effect = RuntimeError("redis down")
        replay = create_autospec(_Replay, instance=True)
        orch = self._orchestrator(redis=redis, replay=replay)
        ex._wire_notify_fill(orch)

        orch.notify_fill("XAUUSD", "BUY", 1.0, 2400.0, "f5", "s5", "oanda", 3.0)

        replay.on_fill.assert_called_once()


class _Engine:
    async def stop(self) -> None:  # pragma: no cover - spec only
        ...

    def metrics(self) -> dict:  # pragma: no cover - spec only
        return {}


class _Orchestrator:
    async def stop(self) -> None:  # pragma: no cover - spec only
        ...

    def health(self) -> dict:  # pragma: no cover - spec only
        return {}


class _DisconnectableBroker:
    async def disconnect(self) -> None:  # pragma: no cover - spec only
        ...


class TestShutdownRunsInReverseDependencyOrder:
    """`stop()` unwinds engine -> tasks -> brokers -> orchestrator.

    The order is the safety property: the engine stops first so no new order is
    placed against a broker that is about to disconnect, and the orchestrator
    stops last so nothing loses its market data while still trading.
    """

    def test_it_stops_the_engine_before_the_orchestrator(self) -> None:
        order: list[str] = []
        system = ExecutionSystem_or_skip()

        engine = create_autospec(_Engine, instance=True)
        orch = create_autospec(_Orchestrator, instance=True)

        async def engine_stop():
            order.append("engine")

        async def orch_stop():
            order.append("orchestrator")

        engine.stop.side_effect = engine_stop
        orch.stop.side_effect = orch_stop
        system._engine, system._orchestrator, system._started = engine, orch, True

        asyncio.run(system.stop())

        assert order == ["engine", "orchestrator"], "the engine must stop before its data source"
        assert system._started is False

    def test_a_broker_that_fails_to_disconnect_does_not_abandon_the_shutdown(self) -> None:
        """The dangerous shape: one venue refusing to close leaving the
        orchestrator running and `_started` still True."""
        system = ExecutionSystem_or_skip()
        bad = create_autospec(_DisconnectableBroker, instance=True)
        bad.disconnect.side_effect = ConnectionError("socket already gone")
        good = create_autospec(_DisconnectableBroker, instance=True)
        orch = create_autospec(_Orchestrator, instance=True)

        system._brokers = {"bad": bad, "good": good}
        system._orchestrator = orch
        system._started = True

        asyncio.run(system.stop())

        good.disconnect.assert_awaited_once()
        orch.stop.assert_awaited_once()
        assert system._started is False

    def test_a_broker_with_no_disconnect_is_skipped_not_crashed_on(self) -> None:
        system = ExecutionSystem_or_skip()
        system._brokers = {"paper": object()}
        system._started = True
        asyncio.run(system.stop())
        assert system._started is False

    def test_stopping_an_unstarted_system_is_safe(self) -> None:
        system = ExecutionSystem_or_skip()
        asyncio.run(system.stop())
        assert system._started is False

    def test_background_tasks_are_cancelled(self) -> None:
        system = ExecutionSystem_or_skip()

        async def run_and_stop():
            async def forever():
                await asyncio.sleep(3600)

            task = asyncio.create_task(forever())
            await asyncio.sleep(0)
            system._tasks = [task]
            await system.stop()
            return task

        task = asyncio.run(run_and_stop())
        assert task.cancelled() or task.done()


class TestHealthReportingSurvivesMissingComponents:
    def test_it_reports_nothing_when_there_is_no_engine(self) -> None:
        """No engine means nothing is trading; a HEALTH line would be noise."""
        system = ExecutionSystem_or_skip()
        system._log_health()

    def test_it_reports_with_only_an_engine_wired(self) -> None:
        """Every other component is None here, so each `if` takes its empty
        side. An unconditional dereference would raise."""
        system = ExecutionSystem_or_skip()
        engine = create_autospec(_Engine, instance=True)
        engine.metrics.return_value = {"tick_count": 7, "signal_count": 2}
        system._engine = engine
        system._log_health()
        engine.metrics.assert_called_once()

    def test_it_reports_with_every_component_wired(self) -> None:
        system = ExecutionSystem_or_skip()
        engine = create_autospec(_Engine, instance=True)
        engine.metrics.return_value = {"tick_count": 1, "fill_count": 1}
        system._engine = engine
        for attr in ("_risk", "_gatekeeper", "_router"):
            component = create_autospec(_HasMetrics, instance=True)
            component.metrics.return_value = {}
            setattr(system, attr, component)
        orch = create_autospec(_Orchestrator, instance=True)
        orch.health.return_value = {"is_safe": True, "gold_feeds": {"oanda": {}}}
        system._orchestrator = orch
        system._log_health()

    def test_the_loop_keeps_running_when_a_report_fails(self) -> None:
        """A health reporter that dies takes the only running signal with it."""
        system = ExecutionSystem_or_skip()
        system._started = True
        calls: list[int] = []

        def explode() -> None:
            calls.append(1)
            system._started = False
            raise RuntimeError("metrics unavailable")

        async def drive():
            with patch.object(ex, "_HEALTH_INTERVAL", 0):
                with patch.object(system, "_log_health", side_effect=explode):
                    await asyncio.wait_for(system._health_loop(), timeout=5)

        asyncio.run(drive())
        assert calls == [1], "the loop must have called the reporter and returned cleanly"


class TestSignalHandlersAreOptional:
    def test_installing_them_without_a_loop_raises_rather_than_pretending(self) -> None:
        with pytest.raises(RuntimeError):
            ExecutionSystem_or_skip()._install_signal_handlers()

    def test_a_platform_that_refuses_them_does_not_break_startup(self) -> None:
        """`add_signal_handler` is unavailable on some platforms; startup must
        continue rather than refusing to run at all."""
        system = ExecutionSystem_or_skip()

        async def drive():
            loop = asyncio.get_running_loop()
            with patch.object(loop, "add_signal_handler", side_effect=RuntimeError("unsupported")):
                system._install_signal_handlers()

        asyncio.run(drive())

    def test_they_are_registered_when_the_platform_allows(self) -> None:
        system = ExecutionSystem_or_skip()
        seen: list[int] = []

        async def drive():
            loop = asyncio.get_running_loop()
            with patch.object(loop, "add_signal_handler", side_effect=lambda s, cb: seen.append(s)):
                system._install_signal_handlers()

        asyncio.run(drive())
        assert signal.SIGTERM in seen and signal.SIGINT in seen


class TestBrokerWiringAlwaysLeavesSomethingToExecuteAgainst:
    """`_connect_brokers` registers whichever venues are configured and
    reachable, and falls back to the paper broker when none is.

    Two properties are worth more than the arithmetic: the system never
    finishes wiring with an empty broker table, and the C++ shim cannot be
    enabled by its own flag alone.
    """

    @staticmethod
    def _patched(**overrides):
        """Neutral defaults: every venue off, every connector unreachable."""
        base = {
            "_BROKER_PRIMARY": "none",
            "_BROKER_SECONDARY": "none",
            "_CME_ENABLED": False,
            "_CPP_SHIM_ENABLED": False,
        }
        base.update(overrides)
        return [patch.object(ex, k, v) for k, v in base.items()]

    def _run(self, system, patches):
        from contextlib import ExitStack

        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            asyncio.run(system._connect_brokers())

    def test_no_venue_configured_falls_back_to_paper(self) -> None:
        """The floor. Finishing with an empty table would be a system that
        looks started and can fill nothing."""
        system = ExecutionSystem_or_skip()
        paper = object()
        self._run(system, self._patched() + [patch.object(ex, "_build_paper_broker", return_value=paper)])
        assert system._brokers == {"paper": paper}

    def test_a_connected_oanda_is_registered_and_paper_is_not_built(self) -> None:
        system = ExecutionSystem_or_skip()
        broker = object()

        async def connected():
            return broker

        self._run(
            system,
            self._patched(_BROKER_PRIMARY="oanda")
            + [
                patch.object(ex, "_connect_oanda", side_effect=connected),
                patch.object(ex, "_build_paper_broker", side_effect=AssertionError("paper must not be built")),
            ],
        )
        assert system._brokers == {"oanda": broker}

    def test_a_refused_venue_still_falls_back_to_paper(self) -> None:
        system = ExecutionSystem_or_skip()
        paper = object()

        async def refused():
            return None

        self._run(
            system,
            self._patched(_BROKER_PRIMARY="oanda")
            + [
                patch.object(ex, "_connect_oanda", side_effect=refused),
                patch.object(ex, "_build_paper_broker", return_value=paper),
            ],
        )
        assert system._brokers == {"paper": paper}

    def test_the_secondary_venue_is_connected_too(self) -> None:
        system = ExecutionSystem_or_skip()
        oanda, ibkr = object(), object()

        async def got_oanda():
            return oanda

        async def got_ibkr():
            return ibkr

        self._run(
            system,
            self._patched(_BROKER_PRIMARY="oanda", _BROKER_SECONDARY="ibkr")
            + [
                patch.object(ex, "_connect_oanda", side_effect=got_oanda),
                patch.object(ex, "_connect_ibkr", side_effect=got_ibkr),
            ],
        )
        assert set(system._brokers) == {"oanda", "ibkr"}

    def test_cme_is_connected_when_enabled_by_its_flag(self) -> None:
        system = ExecutionSystem_or_skip()
        cme = object()

        async def got_cme():
            return cme

        self._run(system, self._patched(_CME_ENABLED=True) + [patch.object(ex, "_connect_cme", side_effect=got_cme)])
        assert system._brokers == {"cme": cme}

    def test_the_shim_flag_alone_does_not_open_the_latency_gate(self) -> None:
        """The property the gate exists for. `CPP_SHIM_ENABLED=true` is a
        request, not permission: with the phase gate closed the shim must not
        be connected at all, and the run falls through to paper."""
        system = ExecutionSystem_or_skip()
        paper = object()
        self._run(
            system,
            self._patched(_CPP_SHIM_ENABLED=True)
            + [
                patch.object(ex, "_check_latency_opt_gate", return_value=False),
                patch.object(ex, "_connect_cpp_shim", side_effect=AssertionError("shim must not be reached")),
                patch.object(ex, "_build_paper_broker", return_value=paper),
            ],
        )
        assert "cpp_shim" not in system._brokers
        assert system._brokers == {"paper": paper}

    def test_the_shim_is_connected_once_the_gate_opens(self) -> None:
        system = ExecutionSystem_or_skip()
        shim = object()

        async def got_shim():
            return shim

        self._run(
            system,
            self._patched(_CPP_SHIM_ENABLED=True)
            + [
                patch.object(ex, "_check_latency_opt_gate", return_value=True),
                patch.object(ex, "_connect_cpp_shim", side_effect=got_shim),
            ],
        )
        assert system._brokers == {"cpp_shim": shim}


class TestDiagnosticsAndEntryPoint:
    def test_logging_configuration_quiets_the_noisy_third_parties(self) -> None:
        """`asyncio` and `ib_insync` at DEBUG bury the HEALTH line that is the
        only routine signal this process emits."""
        ex._configure_logging()
        for noisy in ("urllib3", "aiohttp", "asyncio", "ib_insync"):
            assert logging.getLogger(noisy).level == logging.WARNING

    def test_an_unknown_log_level_falls_back_to_info(self) -> None:
        """A typo in LOG_LEVEL must not silence the process.

        Asserted on the level handed to `basicConfig` rather than on the root
        logger: `basicConfig` is a no-op once anything has configured logging,
        so reading the root level back would pass whatever the function
        resolved — a test that cannot fail.
        """
        with (
            patch.object(ex, "_LOG_LEVEL", "NOT_A_LEVEL"),
            patch.object(logging, "basicConfig") as configured,
        ):
            ex._configure_logging()
        assert configured.call_args.kwargs["level"] == logging.INFO

    def test_a_named_log_level_is_honoured(self) -> None:
        with (
            patch.object(ex, "_LOG_LEVEL", "debug"),
            patch.object(logging, "basicConfig") as configured,
        ):
            ex._configure_logging()
        assert configured.call_args.kwargs["level"] == logging.DEBUG

    def test_the_shutdown_signal_asks_the_system_to_stop(self) -> None:
        """The handler must hand the coroutine to the loop and return at once —
        a signal handler that awaits blocks the loop it is trying to unwind."""
        system = ExecutionSystem_or_skip()
        stopped: list[bool] = []

        async def fake_stop():
            stopped.append(True)

        async def drive():
            loop = asyncio.get_running_loop()
            captured = {}
            with patch.object(loop, "add_signal_handler", side_effect=lambda s, cb: captured.setdefault(s, cb)):
                system._install_signal_handlers()
            with patch.object(system, "stop", side_effect=fake_stop):
                captured[signal.SIGTERM]()
                await asyncio.sleep(0)

        asyncio.run(drive())
        assert stopped == [True]

    def test_the_entry_point_starts_stops_and_always_stops(self) -> None:
        """`_main` runs until `_started` goes false and stops in a `finally`,
        so a failure mid-run still unwinds rather than leaking brokers."""
        calls: list[str] = []

        class FakeSystem:
            def __init__(self) -> None:
                self._started = False

            async def start(self) -> None:
                calls.append("start")

            async def stop(self) -> None:
                calls.append("stop")

        with patch.object(ex, "ExecutionSystem", FakeSystem):
            asyncio.run(ex._main())

        assert calls == ["start", "stop"]
