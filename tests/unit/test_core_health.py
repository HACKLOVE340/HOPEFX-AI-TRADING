# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""`core/health.py` — what this process tells the world about itself.

Three surfaces, measured at 0%: `_probe_components` (per-component status),
`/health` (the operator's answer), and `/ready` (the Kubernetes readiness probe,
whose 503 removes the pod from the Service).

The defect these tests exist to prevent is one shape: a probe that reports
healthy for something it did not reach. A health check that cannot say "no" is
worse than no health check, because it converts an outage into a silent one —
and a readiness probe that cannot say "no" keeps a broken pod in the load
balancer.

So every component is driven through three states — present and working, absent,
and present but failing — and the assertions are that the last two never read as
healthy.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

pytestmark = pytest.mark.unit

REPO = pathlib.Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core.health import _probe_components, register_health_routes


class _KillSwitch:
    def __init__(self, active: bool = False) -> None:
        self._active = active

    def is_active(self) -> bool:
        return self._active


class _Conn:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, _stmt):
        return None


class _Engine:
    """A database engine whose connection works."""

    def connect(self):
        return _Conn()


class _BrokenEngine:
    """One that is configured and cannot be reached — the dangerous case."""

    def connect(self):
        raise OSError("connection refused")


def _state(**overrides):
    """An app_state with nothing wired unless a test wires it."""
    base = dict(
        config=None,
        db_engine=None,
        cache=None,
        auth_service=None,
        risk_manager=None,
        compliance_manager=None,
        prop_enforcer=None,
        strategy_brain=None,
        ws_manager=None,
        broker=None,
        initialized=True,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _route(app: FastAPI, path: str):
    return next(r for r in app.routes if getattr(r, "path", None) == path)


class TestAnAbsentComponentIsNeverHealthy:
    """Rule 2 of this repository: an unmeasured value is absent, never
    best-case. Reported as `unavailable`, which is a fact; `healthy` would be a
    claim nothing supports."""

    @pytest.mark.parametrize(
        "key",
        [
            "config",
            "database",
            "cache",
            "auth",
            "risk_manager",
            "compliance",
            "prop_enforcer",
            "strategy_brain",
            "websocket",
            "broker",
        ],
    )
    def test_nothing_wired_reports_unavailable(self, key: str, monkeypatch) -> None:
        monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
        monkeypatch.delenv("SMTP_HOST", raising=False)
        components = _probe_components(_state(), _KillSwitch())
        assert components[key] == "unavailable", f"{key} read as {components[key]!r} with nothing wired"

    def test_only_what_can_be_asserted_reads_healthy(self) -> None:
        """With nothing wired, exactly two things are honestly healthy: the API,
        because the process is answering, and the kill switch, because it is not
        active. Every other component is absent and says so.

        The list is asserted whole rather than per-key: a new component that
        defaulted to `healthy` when unwired would slip past any test that only
        checked the components it already knew about.
        """
        components = _probe_components(_state(), _KillSwitch())
        assert sorted(k for k, v in components.items() if v == "healthy") == ["api", "kill_switch"]


class TestAFailingComponentIsNeverHealthy:
    """Configured and unreachable is the case that matters. `unavailable` would
    understate it and `healthy` would hide it; both read as degraded."""

    def test_an_unreachable_database_is_degraded_not_unavailable(self) -> None:
        components = _probe_components(_state(db_engine=_BrokenEngine()), _KillSwitch())
        assert components["database"] == "degraded"

    def test_a_reachable_database_is_healthy(self) -> None:
        components = _probe_components(_state(db_engine=_Engine()), _KillSwitch())
        assert components["database"] == "healthy"

    def test_a_cache_reporting_unhealthy_is_degraded(self) -> None:
        cache = SimpleNamespace(health_check=lambda: False)
        assert _probe_components(_state(cache=cache), _KillSwitch())["cache"] == "degraded"

    def test_a_cache_whose_probe_raises_is_degraded(self) -> None:
        def boom():
            raise RuntimeError("redis gone")

        cache = SimpleNamespace(health_check=boom)
        assert _probe_components(_state(cache=cache), _KillSwitch())["cache"] == "degraded"

    def test_a_cache_with_no_probe_is_taken_at_its_word(self) -> None:
        """Documented behaviour, pinned rather than judged: an object with no
        `health_check` is assumed up, because there is nothing to ask."""
        assert _probe_components(_state(cache=SimpleNamespace()), _KillSwitch())["cache"] == "healthy"

    def test_a_disconnected_broker_is_degraded(self) -> None:
        broker = SimpleNamespace(connected=False)
        assert _probe_components(_state(broker=broker), _KillSwitch())["broker"] == "degraded"

    def test_a_connected_broker_is_healthy(self) -> None:
        broker = SimpleNamespace(connected=True)
        assert _probe_components(_state(broker=broker), _KillSwitch())["broker"] == "healthy"

    def test_a_broker_whose_probe_raises_is_degraded(self) -> None:
        class Broker:
            @property
            def connected(self):
                raise ConnectionError("socket closed")

        assert _probe_components(_state(broker=Broker()), _KillSwitch())["broker"] == "degraded"

    def test_a_halted_prop_enforcer_is_reported_as_halted(self) -> None:
        """Halted is not degraded and not healthy — it is a third thing, and an
        operator needs to see which."""
        enforcer = SimpleNamespace(status=lambda: {"halted": True})
        assert _probe_components(_state(prop_enforcer=enforcer), _KillSwitch())["prop_enforcer"] == "halted"

    def test_a_running_prop_enforcer_is_healthy(self) -> None:
        enforcer = SimpleNamespace(status=lambda: {"halted": False})
        assert _probe_components(_state(prop_enforcer=enforcer), _KillSwitch())["prop_enforcer"] == "healthy"


class TestTheKillSwitchIsAlwaysVisible:
    def test_an_active_kill_switch_is_reported(self) -> None:
        assert _probe_components(_state(), _KillSwitch(active=True))["kill_switch"] == "active"

    def test_an_inactive_kill_switch_reads_healthy(self) -> None:
        assert _probe_components(_state(), _KillSwitch(active=False))["kill_switch"] == "healthy"


class TestTheHealthEndpoint:
    @staticmethod
    def _health(app_state, kill_switch):
        app = FastAPI()
        register_health_routes(app, app_state, kill_switch)
        return asyncio.run(_route(app, "/health").endpoint())

    def test_everything_wired_and_reachable_is_healthy(self) -> None:
        state = _state(config=SimpleNamespace(environment="test", api_configs=[]), db_engine=_Engine())
        assert self._health(state, _KillSwitch()).status == "healthy"

    def test_an_unreachable_database_degrades_the_whole_report(self) -> None:
        """`database` is one of the three critical components."""
        state = _state(config=SimpleNamespace(environment="test", api_configs=[]), db_engine=_BrokenEngine())
        assert self._health(state, _KillSwitch()).status == "degraded"

    def test_missing_config_degrades_the_whole_report(self) -> None:
        assert self._health(_state(db_engine=_Engine()), _KillSwitch()).status == "degraded"

    def test_an_active_kill_switch_degrades_an_otherwise_healthy_process(self) -> None:
        """The property worth pinning: every component up and trading halted is
        NOT a healthy system, and a dashboard that showed green would be lying
        about the only thing that matters."""
        state = _state(config=SimpleNamespace(environment="test", api_configs=[]), db_engine=_Engine())
        assert self._health(state, _KillSwitch(active=True)).status == "degraded"

    def test_the_environment_is_unknown_rather_than_guessed(self) -> None:
        assert self._health(_state(), _KillSwitch()).environment == "unknown"


class TestTheReadinessProbe:
    """503 removes the pod from the Service. Each `no` must actually be a no."""

    @staticmethod
    def _ready(app_state, kill_switch=None):
        app = FastAPI()
        register_health_routes(app, app_state, kill_switch or _KillSwitch())
        return asyncio.run(_route(app, "/ready").endpoint())

    def test_an_uninitialised_process_is_not_ready(self) -> None:
        response = self._ready(_state(initialized=False))
        assert response.status_code == 503
        assert b"initializing" in response.body

    def test_a_missing_initialised_flag_is_not_ready(self) -> None:
        """Absent is not ready. A `getattr` default of True here would put every
        pod into rotation before startup finished."""
        state = SimpleNamespace(config=None, db_engine=None, cache=None)
        assert self._ready(state).status_code == 503

    def test_an_unreachable_database_is_not_ready(self) -> None:
        response = self._ready(_state(db_engine=_BrokenEngine()))
        assert response.status_code == 503
        assert b"database_unavailable" in response.body

    def test_an_initialised_process_with_a_reachable_database_is_ready(self) -> None:
        assert self._ready(_state(db_engine=_Engine())) == {"ready": True}

    def test_no_database_configured_does_not_block_readiness(self) -> None:
        assert self._ready(_state(db_engine=None)) == {"ready": True}

    def test_redis_being_unreachable_does_not_block_readiness(self, monkeypatch) -> None:
        """Deliberate, and documented in the source: Redis is not on the
        readiness path, so an outage there must not evict every pod from the
        load balancer at once."""
        monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
        assert self._ready(_state(db_engine=_Engine())) == {"ready": True}


class TestTheStatusEndpoint:
    @staticmethod
    def _status(app_state):
        app = FastAPI()
        register_health_routes(app, app_state, _KillSwitch())
        return asyncio.run(_route(app, "/api/system/status").endpoint())

    def test_it_reports_what_is_wired(self) -> None:
        state = _state(config=SimpleNamespace(environment="prod", api_configs=[1, 2]), db_engine=_Engine())
        status = self._status(state)
        assert status.config_loaded is True
        assert status.database_connected is True
        assert status.environment == "prod"
        assert status.api_configs == 2

    def test_nothing_wired_reports_false_rather_than_omitting(self) -> None:
        status = self._status(_state())
        assert status.config_loaded is False
        assert status.database_connected is False
        assert status.cache_connected is False
        assert status.api_configs == 0

    def test_a_cache_whose_probe_raises_reports_not_connected(self) -> None:
        def boom():
            raise RuntimeError("redis gone")

        status = self._status(_state(cache=SimpleNamespace(health_check=boom)))
        assert status.cache_connected is False


class TestTheLockdownPath:
    """The readiness probe's third check: during a nuclear lockdown the pod is
    removed from the load balancer rather than left serving traffic.

    Reached only when Redis answers, so it needs a Redis that does.
    """

    @staticmethod
    def _ready_with_redis(value, monkeypatch):
        import redis as redis_module

        class _FakeRedis:
            def get(self, _key):
                return value

            def close(self):
                return None

        monkeypatch.setattr(redis_module, "from_url", lambda *a, **k: _FakeRedis())
        app = FastAPI()
        register_health_routes(app, _state(db_engine=_Engine()), _KillSwitch())
        return asyncio.run(_route(app, "/ready").endpoint())

    def test_an_active_lockdown_takes_the_pod_out_of_rotation(self, monkeypatch) -> None:
        response = self._ready_with_redis(b"true", monkeypatch)
        assert response.status_code == 503
        assert b"lockdown_active" in response.body

    def test_an_inactive_lockdown_leaves_the_pod_serving(self, monkeypatch) -> None:
        """The other direction. A probe that evicted on any Redis value would
        take the whole fleet out the first time the key held something else."""
        assert self._ready_with_redis(b"false", monkeypatch) == {"ready": True}

    def test_no_lockdown_key_leaves_the_pod_serving(self, monkeypatch) -> None:
        assert self._ready_with_redis(None, monkeypatch) == {"ready": True}


class TestTheRemainingProbeBranches:
    def test_a_broker_exposing_only_health_check_is_probed_through_it(self) -> None:
        broker = SimpleNamespace(health_check=lambda: True)
        assert _probe_components(_state(broker=broker), _KillSwitch())["broker"] == "healthy"

    def test_a_broker_whose_health_check_says_no_is_degraded(self) -> None:
        broker = SimpleNamespace(health_check=lambda: False)
        assert _probe_components(_state(broker=broker), _KillSwitch())["broker"] == "degraded"

    def test_a_broker_with_neither_probe_is_taken_at_its_word(self) -> None:
        assert _probe_components(_state(broker=SimpleNamespace()), _KillSwitch())["broker"] == "healthy"

    def test_sendgrid_alone_makes_email_healthy(self, monkeypatch) -> None:
        monkeypatch.setenv("SENDGRID_API_KEY", "sg-key")
        assert _probe_components(_state(), _KillSwitch())["email"] == "healthy"

    def test_smtp_needs_both_a_host_and_a_user(self, monkeypatch) -> None:
        """A host with no user cannot send. Reporting healthy on half a
        configuration is how an alert channel is discovered to be dead during
        the incident it was meant to announce."""
        monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
        monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
        monkeypatch.delenv("SMTP_USER", raising=False)
        monkeypatch.delenv("SMTP_USERNAME", raising=False)
        assert _probe_components(_state(), _KillSwitch())["email"] == "unavailable"

        monkeypatch.setenv("SMTP_USER", "mailer")
        assert _probe_components(_state(), _KillSwitch())["email"] == "healthy"
