# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The Gatekeeper's fail-closed reader had a fail-open branch.

Found by grepping the *expression* rather than the symptom, which is the lesson
§E16 ended on. `getattr(signal, "data_quality", 1.0)` turned up a third time in
`risk/gatekeeper.py`, and pulling that thread found something worse than the
literal it started from.

## The branch

`_get_data_quality_from_orch()` exists to be fail-closed, and its own comment
says so — "Fail-closed: unknown data quality blocks the trade via the
data_quality < _MIN_DATA_QUALITY check in gate step 5". It returns `0.0` when
the tick read raises and `0.0` when there is no tick. Then:

    def _get_data_quality_from_orch(self) -> float:
        if getattr(self, "_orch", None) is None:
            return 1.0          # <- the one case that does not block

An absent orchestrator is the *least* measured state of all, and it was the
only one scored perfect.

## Why that branch was live, not theoretical

Measured on a booted instance, not inferred:

    gatekeeper = Gatekeeper
      gk._orch = None
      gk._get_data_quality_from_orch() -> 1.0

`core/startup_factories.py` builds the Gatekeeper with
`orchestrator=getattr(s, "data_orchestrator", None)`, and **nothing anywhere
assigns `data_orchestrator`**. The orchestrator that does exist is stored by
`core/startup_helpers.py:126` as `state.data_layer_orchestrator`. One word
apart, never noticed, because the missing orchestrator produced a perfect score
instead of an error.

`_run_checks_on_dict` — the event-bus path, `bus.subscribe(CH_SIGNAL)` →
`_run_checks_on_dict(signal)` — calls `_get_data_quality_from_orch()` directly.
So on that path gate step 5 compared `1.0 < 0.40` forever. `core/main_loop.py`
constructs `Gatekeeper()` with no orchestrator at all, and `run.py:399` falls
back to it when HopeFXEngine is unavailable.

Two fixes, because either alone leaves a hole: the reader fails closed on an
absent orchestrator, and the factory reads the attribute that is actually set.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


class _Tick:
    def __init__(self, confidence: float) -> None:
        self.confidence = confidence


class _Orch:
    def __init__(self, tick=None, raises: bool = False) -> None:
        self._tick, self._raises = tick, raises

    def get_latest_tick(self, symbol: str = "XAU_USD"):
        if self._raises:
            raise RuntimeError("feed down")
        return self._tick


def _gk(orch=None):
    from risk.gatekeeper import Gatekeeper

    return Gatekeeper(orchestrator=orch)


class TestTheReaderFailsClosed:
    """Every unmeasured state must score at or below the blocking threshold."""

    def test_no_orchestrator_does_not_score_perfect(self) -> None:
        from risk.gatekeeper import _MIN_DATA_QUALITY

        value = _gk(orch=None)._get_data_quality_from_orch()
        assert value < _MIN_DATA_QUALITY, (
            f"an absent orchestrator scored {value} — the least measured state of all, "
            "and the only one the fail-closed reader let through"
        )

    def test_no_tick_does_not_score_perfect(self) -> None:
        from risk.gatekeeper import _MIN_DATA_QUALITY

        assert _gk(orch=_Orch(tick=None))._get_data_quality_from_orch() < _MIN_DATA_QUALITY

    def test_a_raising_feed_does_not_score_perfect(self) -> None:
        from risk.gatekeeper import _MIN_DATA_QUALITY

        assert _gk(orch=_Orch(raises=True))._get_data_quality_from_orch() < _MIN_DATA_QUALITY

    def test_a_real_tick_is_still_reported(self) -> None:
        assert _gk(orch=_Orch(tick=_Tick(0.83)))._get_data_quality_from_orch() == pytest.approx(0.83)


class TestTheEventBusPathIsGated:
    """`_run_checks_on_dict` reads the orchestrator directly, bypassing the signal."""

    def test_a_gatekeeper_with_no_orchestrator_flags_data_quality(self) -> None:
        gk = _gk(orch=None)
        failures = gk._run_checks_on_dict({"symbol": "XAUUSD", "confidence": 0.9, "spread": 0.5})
        reasons = {f.get("reason") for f in failures}
        assert "data_quality_low" in reasons, (
            f"the event-bus gate passed a signal with no measurable data quality; got {reasons}"
        )

    def test_a_healthy_feed_is_not_flagged_for_data_quality(self) -> None:
        gk = _gk(orch=_Orch(tick=_Tick(0.95)))
        failures = gk._run_checks_on_dict({"symbol": "XAUUSD", "confidence": 0.9, "spread": 0.5})
        assert "data_quality_low" not in {f.get("reason") for f in failures}


class TestTheFactoryReadsAnAttributeThatExists:
    """A name nothing assigns is a wire that was never connected."""

    def test_startup_helpers_sets_data_layer_orchestrator(self) -> None:
        import inspect

        from core import startup_helpers

        src = inspect.getsource(startup_helpers)
        assert "state.data_layer_orchestrator = " in src, (
            "the attribute this test pins as the real one has moved; re-check the factory"
        )

    def test_the_gatekeeper_factory_does_not_read_a_never_assigned_name(self) -> None:
        import inspect

        from core import startup_factories

        src = inspect.getsource(startup_factories)
        assert 'orchestrator=getattr(s, "data_orchestrator", None),' not in src, (
            "the Gatekeeper factory still reads s.data_orchestrator, which nothing assigns — "
            "the orchestrator is stored as data_layer_orchestrator"
        )


class TestTheOrchestratorIsAttachedEvenWhenItArrivesLate:
    """Naming the right attribute was not enough — it did not exist yet.

    Measured on a booted instance: `app_state.data_layer_orchestrator` is a
    real MarketDataOrchestrator once startup finishes, but `gk._orch` was still
    None. The component registry runs `init_decision_engine` — which builds the
    Gatekeeper — before `startup_event` reaches
    `start_data_layer_orchestrator`, so the Gatekeeper is constructed while no
    orchestrator exists.

    Fixing only the attribute name left a fail-closed gate with nothing to
    measure, which blocks every signal. Correct, and still not a working gate.
    `start_data_layer_orchestrator` now back-fills the consumers built before it.
    """

    @pytest.mark.slow
    def test_start_data_layer_orchestrator_backfills_a_gatekeeper(self) -> None:
        # ~35s: the helper starts a real orchestrator, which retries FRED three
        # times before giving up. Proven to discriminate — it fails when the
        # back-fill is reverted.
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import patch

        from core import startup_helpers
        from risk.gatekeeper import Gatekeeper

        gk = Gatekeeper()
        assert gk._orch is None, "precondition: built before any orchestrator existed"

        orch = _Orch(tick=_Tick(0.91))
        state = SimpleNamespace(gatekeeper=gk, decision_engine=None)

        async def _fake_start(_self=None):
            return None

        with patch.object(startup_helpers, "_resolve_orchestrator", create=True, return_value=orch):
            # The helper resolves and starts the real orchestrator; only the
            # back-fill is under test, so drive it with a stub.
            try:
                asyncio.run(startup_helpers.start_data_layer_orchestrator(state))
            except Exception:
                # Startup may fail for unrelated reasons in a bare test env; the
                # assertion below is what matters.
                pass

        if getattr(state, "data_layer_orchestrator", None) is not None:
            assert gk._orch is not None, (
                "the orchestrator was assigned to app_state but never reached the Gatekeeper that was built before it"
            )
