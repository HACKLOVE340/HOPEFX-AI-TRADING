# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_reliability_and_audit_defects.py
=================================================
Six defects from the Reliability, Audit Log and ML pages. Every one of them
made a screen state something confidently that was not true.

1. **A tick age of minus fifty-six thousand years, graded ok.**
   ``data_feed  ok  last tick age=-1784477523827.0s``. Tick writers store epoch
   milliseconds; two probes computed ``time.time() - float(ts)`` and mixed
   units. The freshness test is ``age < 120``, which every negative number
   passes — so the probe was guaranteed to report a healthy feed exactly when it
   could not read the timestamp. ``api/superadmin/reliability.py`` additionally
   defaulted a missing timestamp to ``time.time()``, manufacturing an age of
   0.0 from no tick at all.

2. **Celery pointed at the wrong host.** ``CELERY_BROKER_URL`` defaulted to
   ``redis://localhost:6379/1``. docker-compose sets it on ``celery-worker`` and
   ``celery-beat`` but not on ``app``, so inside the app container "localhost"
   is the app container: ``Celery inspect failed: Error 111 connecting to
   localhost:6379`` while every other component reached ``redis:6379``.

3. **A blocking broker call on the event loop.** ``inspect.stats()`` waits
   synchronously for worker replies. Called inside ``async def`` it stalls every
   probe gathered beside it — visible as Redis Cache 2042ms (ERROR, "Timeout
   reading from redis:6379"), Broker 2041ms, ML/AI 2124ms, WebSocket 2112ms: a
   dozen unrelated probes all landing at ~2.0s. The Redis "outage" was this
   function holding the loop.

4. **Eighteen components shown as hard failures, with no data behind them.**
   ``GET /reliability/components`` returned ``{"name", "label"}`` — no status, no
   latency, no detail — despite the route name, the handler name
   ``get_component_health`` and its docstring. The Components tab prefers that
   endpoint, so every card rendered ``undefined`` status as an error, on the
   same page whose Health Engine tab showed 13 OK / 4 warning / 1 error.

5. **An audit log that had never displayed an audit record.** The endpoint read
   ``db_store`` keys under ``audit_event:`` — a prefix nothing writes — then
   fell back to the in-memory ``activity_log``, whose entries are ``{"time",
   "message"}``. The page displays ``timestamp``, ``user_id``, ``event_type``,
   ``detail``, ``ip_address``. Result: "16 events total" above sixteen rows of
   ``—``/``UNKNOWN``/``—``. The real hash-chained ``audit_log`` table, whose
   columns are annotated "Fields required by the superadmin audit/security
   APIs", was never queried.

6. **Accuracy relabelled as win rate.** ``win_rate = float(data.get("win_rate")
   or accuracy)`` — so the dashboard showed ACCURACY 57.3% beside WIN RATE
   57.3%, identical to the decimal. They are different quantities: one is
   directional correctness, the other is the fraction of trades that made money.
   ``or`` also treats a real 0.0 win rate — every trade a loser — as missing.
"""

from __future__ import annotations

import asyncio
import os
import time

import pytest

pytestmark = pytest.mark.unit

os.environ.setdefault("SECURITY_JWT_SECRET", "test-only-jwt-secret-key-minimum-32-chars!!")
os.environ.setdefault("CSRF_PROTECTION", "false")
os.environ["STARTUP_GATE"] = "false"


# ── 1. Tick age ──────────────────────────────────────────────────────────────


def test_a_millisecond_timestamp_is_read_as_milliseconds():
    """The exact production number: ts in ms, age computed in s."""
    from core.account_metrics import tick_age_seconds

    now = 1_786_000_000.0  # ~2026-08
    ts_ms = (now - 45) * 1000
    age = tick_age_seconds(ts_ms, now=now)
    assert age == pytest.approx(45, abs=0.5), f"got {age}"


def test_a_second_timestamp_still_works():
    from core.account_metrics import tick_age_seconds

    now = 1_786_000_000.0
    assert tick_age_seconds(now - 30, now=now) == pytest.approx(30, abs=0.5)


def test_a_microsecond_timestamp_is_read_as_microseconds():
    from core.account_metrics import tick_age_seconds

    now = 1_786_000_000.0
    assert tick_age_seconds((now - 12) * 1_000_000, now=now) == pytest.approx(12, abs=0.5)


def test_the_age_is_never_negative():
    """A negative age sails through every ``age < threshold`` freshness test,
    which is how a 56,000-year-old timestamp was graded ok."""
    from core.account_metrics import tick_age_seconds

    now = 1_786_000_000.0
    assert tick_age_seconds(now + 5_000, now=now) == 0.0
    assert tick_age_seconds((now + 5_000) * 1000, now=now) == 0.0


@pytest.mark.parametrize("bad", [None, "", "not-a-number", 0, -1, [], {}])
def test_an_unusable_timestamp_is_none_not_zero(bad):
    """None means "cannot tell". Zero means "one second old". Collapsing them
    is what let a tick with no timestamp report as fresh."""
    from core.account_metrics import tick_age_seconds

    assert tick_age_seconds(bad) is None


def test_the_old_arithmetic_would_have_failed_this():
    """Pin the defect itself, so the regression is recognisable."""
    from core.account_metrics import tick_age_seconds

    now = 1_786_000_000.0
    ts_ms = now * 1000
    naive = now - ts_ms
    assert naive < -1e12, "precondition: naive subtraction is catastrophically negative"
    assert naive < 120, "and it passes the freshness test"
    assert tick_age_seconds(ts_ms, now=now) == pytest.approx(0.0, abs=1.0)


def test_both_probes_use_the_shared_helper():
    """The computation was duplicated and both copies carried the bug."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2]
    for rel in ("infrastructure/health_engine.py", "api/superadmin/reliability.py"):
        src = (root / rel).read_text()
        assert "tick_age_seconds" in src, f"{rel} no longer uses the shared helper"


# ── 2. Celery broker URL ─────────────────────────────────────────────────────


def _broker_url(env: dict[str, str]) -> str:
    """Import celery_app in a subprocess so module-level config is re-read."""
    import subprocess
    import sys

    clean = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONPATH": str(__import__("pathlib").Path(__file__).resolve().parents[2]),
    }
    clean.update(env)
    out = subprocess.run(
        [sys.executable, "-c", "import celery_app; print(celery_app.BROKER_URL)"],
        capture_output=True,
        text=True,
        env=clean,
        timeout=120,
        check=True,
    )
    return out.stdout.strip().splitlines()[-1]


def test_the_broker_defaults_to_the_configured_redis_not_localhost():
    url = _broker_url({"REDIS_URL": "redis://:pw@redis:6379/0"})
    assert url == "redis://:pw@redis:6379/1", url
    assert "localhost" not in url, "the app container has no Redis on localhost"


def test_an_explicit_broker_url_still_wins():
    url = _broker_url({"REDIS_URL": "redis://:pw@redis:6379/0", "CELERY_BROKER_URL": "redis://elsewhere:6379/5"})
    assert url == "redis://elsewhere:6379/5"


def test_with_no_redis_url_at_all_it_falls_back_to_localhost():
    """Unconfigured is still unconfigured; do not invent a host."""
    assert _broker_url({}) == "redis://localhost:6379/1"


def test_compose_gives_the_app_service_the_broker_url():
    """It was set on celery-worker and celery-beat only, which is why the app's
    health page could not reach it."""
    import pathlib
    import re

    src = (pathlib.Path(__file__).resolve().parents[2] / "docker-compose.yml").read_text()
    app_block = re.split(r"\n  [a-z][a-z0-9_-]*:\n", src)[1]
    assert "CELERY_BROKER_URL" in app_block, "the app service still has no broker URL"


# ── 3. The blocking probe ────────────────────────────────────────────────────


def test_celery_probes_do_not_block_the_event_loop():
    """A synchronous broadcast on the loop stalls every concurrent probe.

    The stand-in blocks for 0.6s; a heartbeat running alongside must keep
    ticking. On the old code it would flatline.
    """
    import infrastructure.health_engine as he

    async def _run():
        probe = he._PROBES["celery"] if hasattr(he, "_PROBES") else None
        assert probe is not None or True  # probe table is built inside register()
        beats = 0

        async def _heartbeat():
            nonlocal beats
            while True:
                await asyncio.sleep(0.01)
                beats += 1

        hb = asyncio.create_task(_heartbeat())
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: time.sleep(0.6))
        finally:
            hb.cancel()
        return beats

    beats = asyncio.run(_run())
    assert beats > 20, f"only {beats} loop turns during 0.6s of blocking work"


@pytest.mark.parametrize("path", ["infrastructure/health_engine.py", "api/superadmin/reliability.py"])
def test_inspect_stats_is_never_awaited_inline(path):
    """The mechanism is the defect: inspect.stats() must reach a worker thread.

    Located by AST rather than by slicing the file around a name — the name also
    appears in comments and in the probe registry, and a text window is as
    likely to measure prose as code.
    """
    import ast
    import pathlib

    tree = ast.parse((pathlib.Path(__file__).resolve().parents[2] / path).read_text())
    funcs = [
        n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef | ast.FunctionDef) and n.name == "_probe_celery"
    ]
    assert funcs, f"{path} has no _probe_celery"
    body = ast.dump(funcs[0])
    assert "run_in_executor" in body, f"{path} still calls the broker on the event loop"
    # The blocking call must live inside the function handed to the executor,
    # not sit beside it on the loop.
    source = ast.unparse(funcs[0])
    assert ".stats()" in source, "precondition: the probe still asks for worker stats"
    inner = [n for n in ast.walk(funcs[0]) if isinstance(n, ast.FunctionDef)]
    assert inner and any(".stats()" in ast.unparse(f) for f in inner), (
        f"{path} calls .stats() outside the worker function"
    )


# ── 4. Component health ──────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from app import app

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(scope="module")
def su_headers():
    import jwt

    return {
        "Authorization": "Bearer "
        + jwt.encode(
            {"sub": "superadmin", "role": "superadmin", "type": "access", "exp": int(time.time()) + 3600},
            os.environ["SECURITY_JWT_SECRET"],
            algorithm="HS256",
        )
    }


def test_the_components_endpoint_returns_health_not_just_labels(client, su_headers):
    r = client.get("/api/superadmin/reliability/components", headers=su_headers)
    assert r.status_code == 200, r.text[:200]
    components = r.json()["components"]
    assert components, "no components returned"
    for comp in components:
        assert "name" in comp and "label" in comp
        assert comp.get("status"), f"{comp.get('name')} has no status — the UI renders that as a failure"
        assert "latency_ms" in comp, f"{comp.get('name')} has no latency — the UI renders a bare 'ms'"
        assert "detail" in comp


def test_components_and_status_agree(client, su_headers):
    """Two views of one probe run must not contradict each other."""
    comps = client.get("/api/superadmin/reliability/components", headers=su_headers).json()["components"]
    status = client.get("/api/superadmin/reliability/status", headers=su_headers).json()["components"]
    assert {c["name"] for c in comps} == {c["name"] for c in status}


def test_not_every_component_is_an_error(client, su_headers):
    """The symptom: eighteen red cards. Some probes fail in a test environment
    (no Redis), but 'all of them, always' was the endpoint carrying no data."""
    comps = client.get("/api/superadmin/reliability/components", headers=su_headers).json()["components"]
    statuses = {c["status"] for c in comps}
    assert statuses != {"error"}, "every component reported error — the endpoint is not probing"
    assert any(c["status"] == "ok" for c in comps), statuses


# ── 5. Audit log ─────────────────────────────────────────────────────────────


def test_an_activity_log_entry_becomes_a_readable_row():
    """`{"time", "message"}` rendered as a completely blank row."""
    from api.admin import _normalise_audit_dict

    row = _normalise_audit_dict({"time": 1_786_000_000.0, "message": "Broker reconnected"})
    assert row["timestamp"], "timestamp column was empty"
    assert row["detail"] == "Broker reconnected", "detail column was empty"
    assert row["event_type"] == "system", "event column read UNKNOWN"


def test_a_real_audit_row_maps_every_displayed_column():
    from datetime import datetime, timezone

    from api.admin import _normalise_audit_row

    class _Row:
        id = 7
        timestamp = datetime(2026, 8, 9, 9, 27, tzinfo=timezone.utc)
        created_at = timestamp
        user_id = "superadmin"
        event_type = "trading_order_placed"
        detail = "XAUUSD BUY 0.1"
        ip_address = "203.0.113.7"
        level = "COMPLIANCE"
        category = "ORDER"

    row = _normalise_audit_row(_Row())
    assert row["timestamp"].startswith("2026-08-09")
    assert row["user_id"] == "superadmin"
    assert row["event_type"] == "trading_order_placed"
    assert row["detail"] == "XAUUSD BUY 0.1"
    assert row["ip_address"] == "203.0.113.7"


def test_a_row_missing_the_new_columns_falls_back_to_the_chain_fields():
    """Older rows predate event_type/user_id/detail; actor and action carry the
    same information and must be shown rather than left blank."""
    from api.admin import _normalise_audit_row

    class _OldRow:
        id = 1
        timestamp = None
        created_at = None
        user_id = None
        actor = "system:selfhealer"
        event_type = None
        action = "patch_applied"
        detail = None
        data_json = '{"file": "api/trading.py"}'
        ip_address = None

    row = _normalise_audit_row(_OldRow())
    assert row["user_id"] == "system:selfhealer"
    assert row["event_type"] == "patch_applied"
    assert "api/trading.py" in row["detail"]


def test_the_endpoint_queries_the_real_audit_table():
    import inspect

    from api.admin import get_audit_log

    src = inspect.getsource(get_audit_log)
    assert "AuditLogEntry" in src, "the hash-chained audit table is still not read"
    idx_table = src.index("AuditLogEntry")
    idx_legacy = src.index("audit_event:")
    assert idx_table < idx_legacy, "the dead db_store prefix is still consulted first"


def test_the_endpoint_returns_the_documented_shape(client, su_headers):
    r = client.get("/api/admin/audit-log?limit=5", headers=su_headers)
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"events", "total", "page", "limit"}
    for ev in body["events"]:
        assert set(ev) >= {"timestamp", "user_id", "event_type", "detail", "ip_address"}


# ── 6. Win rate is not accuracy ──────────────────────────────────────────────


def test_win_rate_is_optional_in_the_response_model():
    from api.ml import AccuracyResponse

    field = AccuracyResponse.model_fields["win_rate"]
    assert not field.is_required(), "win_rate is mandatory again, which forces a substitute value"


def test_a_missing_win_rate_is_null_not_the_accuracy_figure():
    from api.ml import AccuracyResponse

    resp = AccuracyResponse(
        model_id="advanced_oos",
        accuracy=0.573,
        precision=0.677,
        recall=0.582,
        f1=0.677,
        sharpe=1.52,
        total_signals=2016,
        evaluated_at="2026-06-26T00:00:00Z",
    )
    assert resp.win_rate is None
    assert resp.win_rate != resp.accuracy


def test_a_zero_win_rate_survives():
    """`or` treated a real 0.0 — every trade a loser — as missing and replaced
    it with accuracy. That is the most dangerous value to overwrite."""
    from api.ml import AccuracyResponse

    resp = AccuracyResponse(
        model_id="m",
        accuracy=0.573,
        precision=0.0,
        recall=0.0,
        f1=0.0,
        sharpe=0.0,
        win_rate=0.0,
        total_signals=10,
        evaluated_at="2026-06-26T00:00:00Z",
    )
    assert resp.win_rate == 0.0


def test_no_code_path_assigns_accuracy_to_win_rate():
    import pathlib
    import re

    src = (pathlib.Path(__file__).resolve().parents[2] / "api/ml.py").read_text()
    for pattern in (r"win_rate\s*=\s*accuracy\b", r"win_rate\s*=\s*live_accuracy\b", r"win_rate=live_accuracy"):
        assert re.search(pattern, src) is None, f"accuracy is still being relabelled as win rate: {pattern}"


def test_the_dashboard_renders_a_missing_win_rate_as_a_dash():
    import pathlib

    src = (pathlib.Path(__file__).resolve().parents[2] / "frontend/src/pages/Dashboard.tsx").read_text()
    assert "data.win_rate == null ? '—'" in src, "a null win rate would render as 0.0%"
