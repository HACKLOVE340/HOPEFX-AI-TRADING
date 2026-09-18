"""`/health` must say whether this process is trading, not just whether it is up.

M04 of an external source-inspection review: *an API process can have trading
responsibilities; process health alone does not establish engine or broker
readiness.*

Grounded here, it is sharper than that. Production runs ``python app.py`` — the
Dockerfile's CMD — not `run.py`, so the run-mode resolver is not in that path at
all. `app.py` builds the component registry, the registry registers `engine`,
and `init_trading_engine` auto-starts it whenever ``TRADING_MODE`` is not live
(``ENGINE_AUTOSTART`` defaults to **true** on that branch). Live is properly
gated — it needs ENGINE_AUTOSTART **and** LIVE_TRADING_ENABLED — so the exposure
is paper, not real money.

Two things were missing rather than wrong:

* `core/health.py::_probe_components` reports api, config, database, cache,
  auth, risk_manager, compliance, prop_enforcer, strategy_brain, websocket,
  email, broker and kill_switch. It does **not** report the engine. So `/health`
  answered "healthy" identically whether a trading engine was running in this
  process or not.
* `ComponentRegistry.status_summary()` and `all_required_ok()` carry the
  docstring *"for health endpoints"* and had **zero** consumers — written for a
  caller that never arrived.

`ENGINE_AUTOSTART=false` is the API-only profile and already works. It is
deliberately reused rather than replaced with a new name: a fourth spelling of
one run-configuration concept is the defect MODE-SPLIT was about. What it lacked
was documentation and any way to see its effect from outside the process.

The engine is reported but NOT folded into the overall verdict — an API-only
deployment with no engine is correct, and marking it degraded would train
operators to ignore the field.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.unit


class _Kill:
    @staticmethod
    def is_active() -> bool:
        return False


def _state(**over):
    base = dict(
        config=SimpleNamespace(environment="test", api_configs=[]),
        db_engine=None,
        cache=None,
        auth_service=None,
        risk_manager=None,
        compliance_manager=None,
        prop_enforcer=None,
        strategy_brain=None,
        ws_manager=None,
        broker=None,
        engine=None,
        engine_task=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _probe(**over):
    from core.health import _probe_components

    return _probe_components(_state(**over), _Kill())


class TestHealthReportsTheEngine:
    def test_the_engine_appears_at_all(self):
        assert "engine" in _probe(), (
            "/health reported broker, risk and brain but never the engine, so it answered "
            "identically whether or not this process was trading"
        )

    def test_no_engine_reads_unavailable(self):
        assert _probe(engine=None)["engine"] == "unavailable"

    def test_a_constructed_but_unstarted_engine_is_not_healthy(self):
        """The API-only profile. The engine object exists; nothing is running."""
        engine = SimpleNamespace(_running=False)
        assert _probe(engine=engine)["engine"] == "stopped"

    def test_a_running_engine_is_healthy(self):
        engine = SimpleNamespace(_running=True)
        assert _probe(engine=engine)["engine"] == "healthy"

    def test_an_engine_that_raises_when_probed_is_degraded_not_fatal(self):
        class _Angry:
            @property
            def _running(self):
                raise RuntimeError("boom")

        assert _probe(engine=_Angry())["engine"] == "degraded"


class TestAnApiOnlyDeploymentIsStillHealthy:
    def test_a_missing_engine_does_not_degrade_the_overall_verdict(self):
        """Otherwise every API-only deployment reads degraded forever, and an
        operator learns to ignore the field — which is worse than not having it.
        """
        from core.health import _probe_components

        components = _probe_components(_state(engine=None), _Kill())
        critical = ["api", "config", "database"]
        assert "engine" not in critical
        assert components["engine"] == "unavailable"


class TestTheApiOnlyProfileActuallyRefusesToTrade:
    @pytest.mark.asyncio
    async def test_engine_autostart_false_schedules_no_engine(self, monkeypatch):
        """The assertion M04 asks for: absence of order activity."""
        import core.startup_factories as F

        monkeypatch.setenv("ENGINE_AUTOSTART", "false")
        monkeypatch.setenv("TRADING_MODE", "paper")

        started: list[str] = []

        class _Engine:
            _running = False

            async def start(self):
                started.append("start")

        monkeypatch.setattr("hopefx_engine.HopeFXEngine", lambda *a, **k: _Engine())

        state = _state()
        await F.init_trading_engine(state)

        assert started == [], "ENGINE_AUTOSTART=false still scheduled the engine"
        assert getattr(state, "engine_task", None) is None

    @pytest.mark.asyncio
    async def test_the_default_paper_deployment_does_schedule_it(self, monkeypatch):
        """The positive control. If this also refused, the 'fix' would be
        'never trade', which passes the test above while removing the product.
        """
        import core.startup_factories as F

        monkeypatch.delenv("ENGINE_AUTOSTART", raising=False)
        monkeypatch.setenv("TRADING_MODE", "paper")

        class _Engine:
            _running = False

            async def start(self):
                return None

        monkeypatch.setattr("hopefx_engine.HopeFXEngine", lambda *a, **k: _Engine())

        state = _state()
        await F.init_trading_engine(state)
        assert getattr(state, "engine_task", None) is not None
        state.engine_task.cancel()


class TestTheSwitchIsDocumented:
    def test_engine_autostart_is_named_in_claude_md(self):
        """It was documented nowhere — audit F58 said so, and F118 downgraded
        the severity of the gating while leaving that half standing. An off
        switch nobody can find is not a profile."""
        from pathlib import Path

        text = Path(__file__).resolve().parents[2].joinpath("CLAUDE.md").read_text(encoding="utf-8")
        assert "ENGINE_AUTOSTART" in text
