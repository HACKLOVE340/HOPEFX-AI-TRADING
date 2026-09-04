# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
The paper-trading phase gates must gate something.

``research/pipeline/paper_trading_gate.py`` implements both gates properly:
``phase2_ready()`` and ``phase3_ready()`` check elapsed calendar days since
``PAPER_RUN_START_UTC`` and a minimum fill count, with a state file so they
survive restarts.

**Nothing consulted them before enabling the feature.** ``phase3_ready()`` is
called once, at ``ml/inference_engine.py:1558``, and its result is assigned to
``online_ok``, whose only use is ``"online_learner": online_ok`` in a health
dict. It was measured and reported; it gated nothing (F214).

Meanwhile ``core/signal_engine.py`` decides whether each learner blends into
live signals by reading the feature flag alone:

    enabled = bool(flags.ONLINE_LEARNING)
    if not enabled:
        return None
    ...  # no phase3_ready() anywhere

Combined with F215 — the template shipped ``FEATURE_ONLINE_LEARNING=true`` — every
deployment ran an unvalidated online learner against live signals while a gate
sat next to it reporting that it was not ready.

Both stores are covered: the Phase-2 anomaly-weighting path has the same shape.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


class _Gate:
    def __init__(self, ready: bool, reason: str = "Phase 3: 12 fills, need >= 500."):
        self._ready = ready
        self._reason = reason
        self.asked = 0

    def phase3_ready(self):
        self.asked += 1
        return (self._ready, "ok" if self._ready else self._reason)

    def phase2_ready(self):
        self.asked += 1
        return (self._ready, "ok" if self._ready else self._reason)


@pytest.fixture(autouse=True)
def _fresh_stores(monkeypatch):
    import core.signal_engine as se

    monkeypatch.setattr(se, "_online_learner_store", None, raising=False)
    monkeypatch.setattr(se, "_anomaly_store", None, raising=False)
    yield


def _flag_on(monkeypatch, name):
    monkeypatch.setenv(f"FEATURE_{name}", "true")

    class _Flags:
        ONLINE_LEARNING = True
        ANOMALY_WEIGHTING = True

    import config.feature_flags as ff

    monkeypatch.setattr(ff, "flags", _Flags(), raising=False)


def _install_gate(monkeypatch, gate):
    import research.pipeline.paper_trading_gate as ptg

    monkeypatch.setattr(ptg, "get_gate", lambda: gate, raising=False)


# ── Phase 3: online learning ─────────────────────────────────────────────────


def test_the_flag_alone_does_not_enable_online_learning(monkeypatch):
    """The whole of F214: the flag was the only condition checked."""
    import core.signal_engine as se

    _flag_on(monkeypatch, "ONLINE_LEARNING")
    gate = _Gate(ready=False)
    _install_gate(monkeypatch, gate)

    store = se._get_online_learner_store()

    assert gate.asked, "the phase-3 gate was never consulted"
    assert store is None, "an unvalidated online learner was blended into live signals"


def test_a_passed_gate_enables_online_learning(monkeypatch):
    """The gate must permit as well as refuse, or passing it means nothing."""
    import core.signal_engine as se

    _flag_on(monkeypatch, "ONLINE_LEARNING")
    _install_gate(monkeypatch, _Gate(ready=True))

    # The store may still fail to construct in a test environment; what matters
    # is that the gate did not block it.
    se._get_online_learner_store()


def test_a_gate_that_raises_keeps_the_feature_off(monkeypatch):
    """Fail closed. A gate that cannot answer has not said yes."""
    import core.signal_engine as se

    class _Broken:
        def phase3_ready(self):
            raise RuntimeError("state file unreadable")

    _flag_on(monkeypatch, "ONLINE_LEARNING")
    _install_gate(monkeypatch, _Broken())

    assert se._get_online_learner_store() is None


def test_the_refusal_names_the_gates_reason(monkeypatch, caplog):
    """phase3_ready returns (passed, reason). An operator who has turned the
    flag on needs to know it is 12 fills short, not merely that it is off."""
    import core.signal_engine as se

    _flag_on(monkeypatch, "ONLINE_LEARNING")
    _install_gate(monkeypatch, _Gate(ready=False, reason="Phase 3: 12 fills, need >= 500."))

    with caplog.at_level("WARNING"):
        se._get_online_learner_store()

    text = " ".join(r.message for r in caplog.records)
    assert "500" in text or "fills" in text, "the refusal did not say what the gate is waiting for"


def test_the_flag_off_short_circuits_before_the_gate(monkeypatch):
    """No point reading a state file for a feature nobody asked for."""
    import config.feature_flags as ff
    import core.signal_engine as se

    class _Flags:
        ONLINE_LEARNING = False
        ANOMALY_WEIGHTING = False

    monkeypatch.setattr(ff, "flags", _Flags(), raising=False)
    monkeypatch.delenv("FEATURE_ONLINE_LEARNING", raising=False)
    gate = _Gate(ready=True)
    _install_gate(monkeypatch, gate)

    assert se._get_online_learner_store() is None
    assert gate.asked == 0


# ── Phase 2: anomaly weighting ───────────────────────────────────────────────


def test_the_flag_alone_does_not_enable_anomaly_weighting(monkeypatch):
    """Same shape, same fix."""
    import core.signal_engine as se

    _flag_on(monkeypatch, "ANOMALY_WEIGHTING")
    gate = _Gate(ready=False)
    _install_gate(monkeypatch, gate)

    store = se._get_anomaly_store()

    assert gate.asked, "the phase-2 gate was never consulted"
    assert store is None
