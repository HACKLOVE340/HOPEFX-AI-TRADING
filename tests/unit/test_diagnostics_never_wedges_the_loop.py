# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_diagnostics_never_wedges_the_loop.py
=====================================================
The diagnostics suite took production down, and these tests pin the reasons.

Symptom: the container's health probe timed out with **zero bytes received**
every 30 seconds, the container went unhealthy, and nginx — which is gated on
``depends_on: app: condition: service_healthy`` — refused to start behind it::

    ✗ Container hopefx-ai-trading-app-1  Error
    dependency failed to start: container hopefx-ai-trading-app-1 is unhealthy

``/api/health/live`` returns a literal dict and cannot block, so it was never
getting to run. Five hypotheses were tried and disproved by measurement (health
path, missing curl, compose project labels, blocked egress, blocking HTTP in the
macro feeds). The answer came from a SIGUSR1 stack dump of the live process::

    Current thread (most recent call first):
      File "asyncio/subprocess.py", line 224 in create_subprocess_exec
      File "/app/security/diagnostics.py", line 390 in _test_import
      ...
      File "/app/app.py", line 1101 in run_server

which matched the log signature exactly: in two independent containers the
application log stopped, permanently, on the line immediately before —
``SelfHealer: running advanced diagnostics suite``.

Three defects, each tested below.

1. ``_check_import_chain`` spawned a fresh interpreter per package —
   ``sys.executable -c "import <pkg>"`` — ten at once, every
   ``HEAL_DIAG_INTERVAL`` seconds. ``asyncio.create_subprocess_exec`` performs
   the fork/exec *inline on the event loop thread*, so it can neither be
   cancelled nor timed out, and the old ``wait_for`` wrapped only
   ``communicate()`` — the part that was never the problem. ``_CORE_PACKAGES``
   begins with ``app``, so each child rebuilt the entire application.

2. ``run_full_diagnostic`` imposed no deadline on any check. The self-healer
   awaits it on the request-serving loop.

3. ``_check_route_health`` POSTed ``{}`` to every registered POST route not on a
   hand-maintained blocklist, with a header that bypasses CSRF.

Note the pre-existing comment in ``self_healer._diagnostics_loop``: *"Skip
diagnostics in development — they make blocking HTTP calls to localhost which
starve the single-worker event loop."* The starvation was known. It was
disabled in the one environment where it was harmless and left running in the
one where it wasn't.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
import time

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def engine():
    from security.diagnostics import DiagnosticsEngine

    return DiagnosticsEngine()


@pytest.fixture
def core_packages(monkeypatch):
    """Set _CORE_PACKAGES for one test and restore it afterwards."""
    import security.diagnostics as diag

    def _set(packages: list[str]) -> None:
        monkeypatch.setattr(diag, "_CORE_PACKAGES", list(packages))

    return _set


# ── 1. The import check must never spawn a process ───────────────────────────


@pytest.mark.asyncio
async def test_the_import_check_never_spawns_a_subprocess(engine, core_packages, monkeypatch):
    """The defect, stated as the mechanism — because here the mechanism *is* the
    defect. Every process-spawning primitive is booby-trapped; a check that
    reaches for one fails loudly instead of reporting a false 'critical'."""
    import subprocess

    def _forbidden(*args, **kwargs):
        raise AssertionError("diagnostics spawned a process from the event loop")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _forbidden)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", _forbidden)
    monkeypatch.setattr(subprocess, "Popen", _forbidden)
    monkeypatch.setattr(subprocess, "run", _forbidden)

    core_packages(["os", "sys", "json"])
    results = await engine._check_import_chain()

    assert len(results) == 1
    assert results[0].status == "ok", (
        f"the import check could not complete without forking: {results[0].message} {results[0].details}"
    )


@pytest.mark.asyncio
async def test_an_already_imported_package_costs_nothing(engine, core_packages, monkeypatch):
    """A module in ``sys.modules`` demonstrably imported — the process running
    this code is the proof. Re-deriving that by any means is waste, and the old
    means was a fresh interpreter."""
    calls: list[str] = []
    real_import = importlib.import_module

    def _counting_import(name, *a, **k):
        calls.append(name)
        return real_import(name, *a, **k)

    monkeypatch.setattr(importlib, "import_module", _counting_import)

    assert "json" in sys.modules and "os" in sys.modules
    core_packages(["os", "json"])
    results = await engine._check_import_chain()

    assert results[0].status == "ok"
    assert calls == [], f"re-imported already-loaded modules: {calls}"


# ── 2. The loop must keep running while the check does ───────────────────────


@pytest.mark.asyncio
async def test_a_slow_import_does_not_stall_the_event_loop(engine, core_packages, monkeypatch):
    """The property that actually mattered in production: whatever the import
    check is doing, ``/api/health/live`` must still get a turn.

    A synchronous 1 s import stands in for the fork that stalled under memory
    pressure. If the work happens on the loop thread the heartbeat flatlines; if
    it happens in a worker it keeps ticking.
    """
    import security.diagnostics as diag

    def _slow_import(name, *a, **k):
        time.sleep(1.0)
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(importlib, "import_module", _slow_import)
    monkeypatch.setenv("DIAG_IMPORT_TIMEOUT", "10")
    core_packages(["hopefx_probe_not_a_real_package"])

    beats = 0

    async def _heartbeat() -> None:
        nonlocal beats
        while True:
            await asyncio.sleep(0.01)
            beats += 1

    hb = asyncio.create_task(_heartbeat())
    try:
        results = await diag.DiagnosticsEngine._check_import_chain(engine)
    finally:
        hb.cancel()

    assert results[0].status == "critical", "a missing package must still be reported"
    assert beats > 20, f"the event loop only got {beats} turns during a 1s import — it was blocked"


@pytest.mark.asyncio
async def test_a_hanging_import_degrades_to_a_warning(engine, core_packages, monkeypatch):
    """A probe that never returns must cost one worker thread and one warning,
    never the application. The old code had no timeout on the spawn at all."""
    stop = __import__("threading").Event()

    def _hangs(name, *a, **k):
        stop.wait(30)
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(importlib, "import_module", _hangs)
    monkeypatch.setenv("DIAG_IMPORT_TIMEOUT", "0.5")
    core_packages(["hopefx_probe_that_hangs"])

    try:
        t0 = time.monotonic()
        results = await asyncio.wait_for(engine._check_import_chain(), timeout=10)
        elapsed = time.monotonic() - t0
    finally:
        stop.set()

    assert elapsed < 5, f"the check ran {elapsed:.1f}s despite a 0.5s budget"
    assert results[0].status == "warning"
    assert "did not finish" in results[0].message


# ── 3. Fidelity the fix must not lose ────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_package_that_raises_on_import_is_still_critical(engine, core_packages, tmp_path, monkeypatch):
    """The check's whole reason for existing. Locating a module is not the same
    as importing it, so the replacement performs a real import — a module that
    exists on disk and blows up when executed must still be caught."""
    (tmp_path / "hopefx_explodes_on_import.py").write_text("raise RuntimeError('boom at import time')\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop("hopefx_explodes_on_import", None)

    core_packages(["hopefx_explodes_on_import"])
    results = await engine._check_import_chain()

    assert results[0].status == "critical"
    broken = results[0].details["broken"]
    assert broken[0]["package"] == "hopefx_explodes_on_import"
    assert "boom at import time" in broken[0]["error"]


@pytest.mark.asyncio
async def test_a_missing_package_is_critical(engine, core_packages):
    core_packages(["this_package_does_not_exist_xyz_abc_123"])
    results = await engine._check_import_chain()
    assert results[0].status == "critical"
    assert len(results[0].details["broken"]) == 1


# ── 4. Every check has a deadline ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_one_hung_check_cannot_hang_the_whole_run(monkeypatch):
    """``run_full_diagnostic`` is awaited by the self-healer on the loop that
    serves requests. One check that never returns used to mean the process never
    served another request."""
    from security.diagnostics import DiagnosticsEngine

    engine = DiagnosticsEngine()

    async def _never_returns(*a, **k):
        await asyncio.sleep(3600)

    monkeypatch.setattr(engine, "_check_route_health", _never_returns)
    monkeypatch.setenv("DIAG_CHECK_TIMEOUT", "0.5")

    t0 = time.monotonic()
    report = await asyncio.wait_for(engine.run_full_diagnostic(parallel=True), timeout=60)
    elapsed = time.monotonic() - t0

    assert elapsed < 55, f"the run took {elapsed:.1f}s with a 0.5s per-check deadline"
    timed_out = [r for r in report.results if r.check_name == "route_health" and r.status == "error"]
    assert timed_out, "the hung check produced no finding — a silent hang is the worst outcome"
    assert "deadline" in timed_out[0].message


@pytest.mark.asyncio
async def test_a_raising_check_is_named_in_the_report(monkeypatch):
    """The old serial branch reported ``check_name='unknown'``, which tells an
    operator nothing about which of ten checks failed."""
    from security.diagnostics import DiagnosticsEngine

    engine = DiagnosticsEngine()

    async def _boom(*a, **k):
        raise ValueError("check exploded")

    monkeypatch.setattr(engine, "_check_redis", _boom)
    report = await engine.run_full_diagnostic(parallel=False)

    named = [r for r in report.results if r.check_name == "redis" and r.status == "error"]
    assert named, [r.check_name for r in report.results]
    assert "check exploded" in named[0].message


# ── 5. Route health is read-only ─────────────────────────────────────────────


class _RecordingResponse:
    status_code = 200


class _RecordingClient:
    """Stands in for httpx.AsyncClient and records every verb attempted."""

    calls: list[tuple[str, str]] = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, path, **k):
        type(self).calls.append(("GET", path))
        return _RecordingResponse()

    async def post(self, path, **k):
        type(self).calls.append(("POST", path))
        return _RecordingResponse()

    async def put(self, path, **k):
        type(self).calls.append(("PUT", path))
        return _RecordingResponse()

    async def delete(self, path, **k):
        type(self).calls.append(("DELETE", path))
        return _RecordingResponse()


@pytest.mark.asyncio
async def test_route_health_only_ever_issues_gets(engine, monkeypatch):
    """A health check on a system that moves money must not write.

    The old sweep POSTed ``{}`` to every registered POST route that was not on a
    thirteen-entry prefix blocklist, and sent ``X-Internal-Health-Check: 1`` so
    the CSRF middleware would wave it through. Every route added after that list
    was written was probed by default — the unsafe direction for a default to
    fail in.
    """
    import httpx

    _RecordingClient.calls = []
    monkeypatch.setattr(httpx, "AsyncClient", _RecordingClient)

    await engine._check_route_health()

    verbs = {v for v, _ in _RecordingClient.calls}
    assert _RecordingClient.calls, "the sweep probed nothing at all"
    assert verbs == {"GET"}, f"route health issued non-GET requests: {sorted(verbs)}"


@pytest.mark.asyncio
async def test_route_health_sends_no_csrf_bypass_header(engine, monkeypatch):
    """The bypass header exists so an unattended prober can write past CSRF.
    Nothing that only reads needs it."""
    import httpx

    seen_headers: list[dict] = []

    class _HeaderSpy(_RecordingClient):
        async def get(self, path, **k):
            seen_headers.append(k.get("headers") or {})
            return await super().get(path, **k)

    _RecordingClient.calls = []
    monkeypatch.setattr(httpx, "AsyncClient", _HeaderSpy)

    await engine._check_route_health()

    for headers in seen_headers:
        assert "X-Internal-Health-Check" not in headers, headers


@pytest.mark.asyncio
async def test_route_health_stops_at_its_budget(engine, monkeypatch):
    """Fifty routes at DIAG_HTTP_TIMEOUT each is over eight minutes of a single
    check. The sweep is bounded in wall-clock time, not just in route count."""
    import httpx

    class _SlowClient(_RecordingClient):
        async def get(self, path, **k):
            await asyncio.sleep(0.05)
            return await super().get(path, **k)

    _RecordingClient.calls = []
    monkeypatch.setattr(httpx, "AsyncClient", _SlowClient)
    monkeypatch.setenv("DIAG_ROUTE_BUDGET", "0.2")

    t0 = time.monotonic()
    results = await engine._check_route_health()
    elapsed = time.monotonic() - t0

    assert elapsed < 3, f"the sweep ran {elapsed:.1f}s against a 0.2s budget"
    assert results[0].status == "ok"


# ── 6. Remediation must not fork on the loop either ──────────────────────────


@pytest.mark.asyncio
async def test_the_frontend_rebuild_does_not_fork_on_the_event_loop(monkeypatch, tmp_path):
    """``auto_remediate`` runs ``npm run build`` when the healer is set to
    aggressive or nuclear. Same construct, larger child: an unguarded fork on
    the loop thread. It belongs in a worker."""
    import security.diagnostics as diag
    from security.diagnostics import DiagnosticResult, DiagnosticsEngine

    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "package.json").write_text("{}")
    monkeypatch.setattr(diag, "PROJECT_ROOT", tmp_path)

    def _forbidden(*a, **k):
        raise AssertionError("remediation forked from the event loop")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _forbidden)

    calling_thread: list[str] = []
    import subprocess as _sp

    class _Completed:
        returncode = 0
        stderr = b""

    def _fake_run(*a, **k):
        calling_thread.append(__import__("threading").current_thread().name)
        return _Completed()

    monkeypatch.setattr(_sp, "run", _fake_run)

    engine = DiagnosticsEngine()
    action = await engine._remediate_result(
        DiagnosticResult(check_name="frontend_build", status="error", message="stale")
    )

    assert action is not None
    assert action["success"] is True
    assert calling_thread, "npm was never invoked"
    assert "MainThread" not in calling_thread[0], f"the build ran on the event loop thread ({calling_thread[0]})"


# ── 7. An operator can switch the whole subsystem off ────────────────────────


@pytest.mark.asyncio
async def test_heal_diag_enabled_false_stops_the_loop(monkeypatch):
    """When this subsystem is the suspect, an operator must be able to take it
    out of the path with an env var — not by editing code, and not by disabling
    the entire self-healer."""
    from security.self_healer import SelfHealer

    healer = SelfHealer()
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("HEAL_DIAG_ENABLED", "false")

    ran = False

    async def _spy():
        nonlocal ran
        ran = True
        return {}

    monkeypatch.setattr(healer, "_run_diagnostics", _spy)

    # Returns immediately — no 30 s startup stagger, no run.
    await asyncio.wait_for(healer._diagnostics_loop(), timeout=5)
    assert ran is False


@pytest.mark.asyncio
async def test_the_loop_is_on_by_default_in_production(monkeypatch):
    """The off switch must be opt-in. A default that silently disables
    diagnostics would be its own silent failure."""
    from security.self_healer import SelfHealer

    healer = SelfHealer()
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("HEAL_DIAG_ENABLED", raising=False)

    # Collapse the 30 s startup stagger and the inter-run interval. Bind the
    # real sleep first — referring to asyncio.sleep from inside the replacement
    # would call the replacement.
    real_sleep = asyncio.sleep
    monkeypatch.setattr(asyncio, "sleep", lambda *_a, **_k: real_sleep(0))

    healer._running = True
    healer._enabled = True
    runs = 0

    async def _spy():
        nonlocal runs
        runs += 1
        healer._running = False  # one pass is enough
        return {}

    monkeypatch.setattr(healer, "_run_diagnostics", _spy)

    await asyncio.wait_for(healer._diagnostics_loop(), timeout=5)
    assert runs == 1, "the loop took the early-return path with no override set"
