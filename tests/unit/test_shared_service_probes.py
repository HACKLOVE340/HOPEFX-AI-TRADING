# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_shared_service_probes.py
========================================
The failing Celery probes were right. The passing one was lucky.

Three pages reported three verdicts about the same broker within twelve
minutes::

    System Health   Celery DOWN — RuntimeError, 8ms
    Reliability     Celery WARNING — "inspect failed: Connection closed by server"
    Health Engine   Celery OK — workers=1 active, 3280ms

It is tempting to treat the green one as the truth and the red ones as noise.
That is backwards. The Redis service runs with ``--timeout 300`` — it closes
any connection idle for five minutes — and a Celery *control* connection from
the app container is idle far longer, because nothing touches it until an
operator opens a health page. The server had already hung up. The client only
discovers that when it writes.

**The 8ms proves it.** A probe with a 2-second inspect timeout that fails in
8ms never waited for anything; it wrote to a dead socket and got an instant
error. "Connection closed by server" is the same event named plainly. Health
Engine returned OK because its attempt happened to open a fresh connection.

So there were two real defects, and neither was a false alarm:

1. The broker connection had no idle-survival settings — no
   ``health_check_interval``, no ``socket_keepalive`` — so it was always going
   to be reaped between health checks.
2. Three separate implementations of "is Celery alive", with different
   timeouts and different execution models, cannot agree even when the
   component is healthy. One of them also blocked the event loop, which both
   others' docstrings already warn about.
"""

from __future__ import annotations

import asyncio

import pytest

from infrastructure.service_probes import is_reconnectable, probe_celery

pytestmark = pytest.mark.unit


# ── The connection-drop signature is recognised ──────────────────────────────


@pytest.mark.parametrize(
    "message",
    [
        "Connection closed by server.",
        "Error while reading from socket: connection reset by peer",
        "Broken pipe",
        "Error 111 connecting to localhost:6379. Connection refused.",
        "Connection aborted",
        "EOF occurred in violation of protocol",
    ],
)
def test_dropped_connections_are_recognised(message):
    assert is_reconnectable(RuntimeError(message)) is True


@pytest.mark.parametrize(
    "message",
    ["No such queue", "AUTH failed: invalid password", "unknown command 'INSPECT'", ""],
)
def test_real_faults_are_not_mistaken_for_drops(message):
    """Retrying an authentication failure just fails twice."""
    assert is_reconnectable(RuntimeError(message)) is False


# ── The retry ────────────────────────────────────────────────────────────────


async def test_a_dropped_connection_is_retried_and_reported_as_healthy(monkeypatch):
    """The exact production sequence: first write fails on a reaped socket, the
    reconnect succeeds. Reporting the first failure as DOWN is what made three
    pages disagree."""
    import infrastructure.service_probes as probes

    calls = {"n": 0}

    def _flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("Connection closed by server.")
        return {"celery@worker1": {}}

    monkeypatch.setattr(probes, "_inspect_stats", _flaky)

    result = await probe_celery()
    assert result["status"] == "ok"
    assert result["worker_count"] == 1
    assert result["retried"] is True
    assert "after reconnect" in result["detail"], "a retried success must say so"
    assert calls["n"] == 2


async def test_a_genuine_outage_is_still_reported(monkeypatch):
    """The guard rail. Retrying must not turn a real outage green."""
    import infrastructure.service_probes as probes

    def _always_down():
        raise RuntimeError("Connection refused")

    monkeypatch.setattr(probes, "_inspect_stats", _always_down)

    result = await probe_celery()
    assert result["status"] == "error"
    assert result["worker_count"] == 0
    assert "retried once" in result["detail"]


async def test_a_non_connection_error_is_not_retried(monkeypatch):
    import infrastructure.service_probes as probes

    calls = {"n": 0}

    def _auth_failure():
        calls["n"] += 1
        raise RuntimeError("AUTH failed: invalid password")

    monkeypatch.setattr(probes, "_inspect_stats", _auth_failure)

    result = await probe_celery()
    assert result["status"] == "error"
    assert calls["n"] == 1, "an auth failure was retried — it will just fail twice"


async def test_no_workers_is_a_warning_not_an_error(monkeypatch):
    """A reachable broker with no workers is a different fact from an
    unreachable broker, and an operator needs to tell them apart."""
    import infrastructure.service_probes as probes

    monkeypatch.setattr(probes, "_inspect_stats", lambda: None)

    result = await probe_celery()
    assert result["status"] == "warning"
    assert "no workers" in result["detail"]


async def test_the_probe_never_raises(monkeypatch):
    """It is called from three health endpoints; an exception there becomes a
    500 on a page whose whole job is to report failures calmly."""
    import infrastructure.service_probes as probes

    def _explode():
        raise ValueError("something unexpected")

    monkeypatch.setattr(probes, "_inspect_stats", _explode)
    result = await probe_celery()
    assert result["status"] == "error"


async def test_the_broadcast_runs_off_the_event_loop(monkeypatch):
    """inspect.stats() blocks for its whole timeout. On the loop it stalls every
    probe gathered beside it — measured once as a dozen unrelated probes all
    landing at ~2.0s, including a Redis 'timeout' that was really this."""
    import threading

    import infrastructure.service_probes as probes

    main_thread = threading.get_ident()
    seen: dict[str, int] = {}

    def _record():
        seen["thread"] = threading.get_ident()
        return {"celery@w": {}}

    monkeypatch.setattr(probes, "_inspect_stats", _record)
    await probe_celery()

    assert seen["thread"] != main_thread, "the blocking broadcast ran on the event loop"


async def test_a_slow_broker_does_not_hang_the_page(monkeypatch):
    import infrastructure.service_probes as probes

    def _slow():
        import time as _t

        _t.sleep(10)

    monkeypatch.setattr(probes, "_inspect_stats", _slow)
    monkeypatch.setattr(probes, "CELERY_WAIT_TIMEOUT", 0.2)

    result = await asyncio.wait_for(probe_celery(), timeout=3.0)
    assert result["status"] == "error"


# ── One implementation, three pages ──────────────────────────────────────────


@pytest.mark.parametrize(
    "module_path",
    [
        "infrastructure/health_engine.py",
        "api/superadmin/reliability.py",
        "api/superadmin/system_health.py",
    ],
)
def test_every_page_uses_the_shared_probe(module_path):
    """Three copies with three timeouts cannot agree even when Celery is fine."""
    import pathlib

    from tests.support.source_text import code_only

    root = pathlib.Path(__file__).resolve().parents[2]
    src = code_only(root / module_path)
    assert "from infrastructure.service_probes import probe_celery" in src, (
        f"{module_path} has its own Celery check again"
    )


@pytest.mark.parametrize(
    "module_path",
    ["infrastructure/health_engine.py", "api/superadmin/reliability.py", "api/superadmin/system_health.py"],
)
def test_no_page_calls_inspect_directly(module_path):
    import pathlib

    from tests.support.source_text import code_only

    root = pathlib.Path(__file__).resolve().parents[2]
    src = code_only(root / module_path)
    assert "control.inspect(" not in src, f"{module_path} bypasses the shared probe"


# ── The cause: broker connection settings ────────────────────────────────────


def test_the_broker_survives_the_redis_idle_timeout():
    """Redis closes connections idle for `--timeout 300`. Without a health
    check below that, the control connection is always reaped between page
    loads."""
    import celery_app

    if not getattr(celery_app, "_CELERY_AVAILABLE", False):
        pytest.skip("celery not installed")

    opts = celery_app.app.conf.broker_transport_options
    assert opts.get("socket_keepalive") is True
    assert opts.get("retry_on_timeout") is True
    interval = opts.get("health_check_interval")
    assert interval and interval < 300, (
        f"health_check_interval={interval} is not below the Redis server's --timeout 300"
    )


def test_the_compose_redis_still_has_the_timeout_this_defends_against():
    """Pins the constraint. If --timeout is removed or raised, the interval
    above can be revisited; until then it is load-bearing."""
    import pathlib

    import yaml

    root = pathlib.Path(__file__).resolve().parents[2]
    compose = yaml.safe_load((root / "docker-compose.yml").read_text())
    command = str(compose["services"]["redis"].get("command", ""))
    assert "--timeout 300" in command, (
        "the Redis idle timeout changed — re-check health_check_interval against the new value"
    )


# ── ML engine status: cache miss is not "unknown" ────────────────────────────


async def test_a_cold_status_cache_falls_back_to_the_predictor(monkeypatch):
    """System Health showed "ML Engine UNKNOWN" while the Health Engine showed
    "predictor ready=True" on the same deployment, because this row read a
    Redis key and gave up when it was absent.

    The key is published once at startup with a TTL and no refresh, so it is
    missing on any process older than the TTL. That means "nobody published it",
    not "the engine's state is unknown".
    """
    import api.superadmin.system_health as sh

    monkeypatch.setattr("cache.redis_client.get_sync_redis_client", lambda: None, raising=False)

    row = await sh._ml_engine_service_row()
    assert row["name"] == "ml_engine"
    assert row["status"] != "unknown", "a cold cache still reports unknown"
    assert "live check" in row["detail"]


async def test_a_warm_cache_is_used_and_labelled(monkeypatch):
    import json as _json
    from types import SimpleNamespace

    import api.superadmin.system_health as sh

    payload = _json.dumps({"model_available": True, "model_version": "advanced_oos_v2"})
    monkeypatch.setattr(
        "cache.redis_client.get_sync_redis_client",
        lambda: SimpleNamespace(get=lambda k: payload),
        raising=False,
    )

    row = await sh._ml_engine_service_row()
    assert row["status"] == "healthy"
    assert "advanced_oos_v2" in row["detail"]
    assert "from cache" in row["detail"]


def test_the_status_key_is_refreshed_not_written_once():
    """It was published exactly once, at startup, with ex=3600 and no refresher
    anywhere in the codebase — so every reader fell to "unknown" after an hour
    of uptime until the next restart."""
    import inspect

    import core.startup_factories as sf

    assert hasattr(sf, "_republish_ml_status"), "the refresher is gone"
    src = inspect.getsource(sf._republish_ml_status)
    assert 'set(\n                "ml:model:status"' in src or '"ml:model:status"' in src
    assert sf._ML_STATUS_REFRESH < sf._ML_STATUS_TTL, (
        "the refresh interval must be shorter than the TTL, or the key expires between refreshes"
    )


def test_the_refresher_is_registered_as_a_background_task():
    import inspect

    import core.startup_factories as sf

    src = inspect.getsource(sf.init_inference_engine)
    assert "_republish_ml_status" in src
    assert "background_tasks.append" in src, "the refresher is never started"


def test_a_failed_status_publish_is_reported_not_swallowed():
    """The publish uses the async Redis client, which returns None when the
    circuit breaker is open. Silently skipping it is how the key went missing
    without any log line naming the reason."""
    import inspect

    import core.startup_factories as sf

    src = inspect.getsource(sf.init_inference_engine)
    assert "ml:model:status not published" in src


def test_the_broker_options_are_correct_in_source_even_without_celery_installed():
    """The config assertion above skips when celery is not importable, which is
    the case in this sandbox — so a mutation raising health_check_interval above
    the server's --timeout survived it silently. A test that only runs where a
    dependency happens to be installed is not a test.

    This reads the source instead, so it runs everywhere.
    """
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2]
    tree = ast.parse((root / "celery_app.py").read_text())

    found: dict[str, object] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values, strict=False):
            if not isinstance(key, ast.Constant) or key.value != "health_check_interval":
                continue
            # int(os.getenv("...", "60")) — pull the literal default out.
            if isinstance(value, ast.Call) and value.args:
                inner = value.args[0]
                if isinstance(inner, ast.Call) and len(inner.args) >= 2 and isinstance(inner.args[1], ast.Constant):
                    found["default"] = int(inner.args[1].value)
            elif isinstance(value, ast.Constant):
                found["default"] = int(value.value)

    assert "default" in found, "health_check_interval is no longer set on the broker options"
    assert found["default"] < 300, (
        f"health_check_interval defaults to {found['default']}s, at or above the Redis "
        "server's --timeout 300 — the connection will be reaped before it is checked"
    )
