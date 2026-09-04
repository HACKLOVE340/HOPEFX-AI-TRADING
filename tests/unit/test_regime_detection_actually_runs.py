# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
Regime detection has to actually run.

``RegimeRouter.route()`` is the only writer of ``_last_regime`` and
``_last_confidence``, and nothing in the repo calls it. ``get_current_regime()``
reads ``router.status()``, which reads those fields — so it returned the
constructor's ``"unknown"`` for the life of the process, and
``_REGIME_SIZE_MAP["UNKNOWN"] == 0.5`` scaled **every** position on the platform
(F94).

The previous commit made that visible. This makes it stop happening: the read
point now runs the detector against real bars, cached briefly so a per-signal
call does not re-detect on every order.

**It stays conservative when it cannot detect.** No bars, no router, or a
detector that raises all leave the regime UNKNOWN — which keeps the 0.5 scalar.
Inventing a regime to avoid the halving would be worse than the halving.
"""

from __future__ import annotations

import sys

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _fresh_router(monkeypatch):
    import core.regime_router as rr

    monkeypatch.setattr(rr, "_router", None, raising=False)
    monkeypatch.setattr(rr, "_last_detect_at", 0.0, raising=False)
    yield


class _Router:
    def __init__(self, regime="TRENDING_UP", confidence=0.82):
        self.routed_with = []
        self._regime = regime
        self._confidence = confidence

    def route(self, df):
        self.routed_with.append(df)
        return self._regime, "trend_following"

    def status(self):
        if not self.routed_with:
            return {"current_regime": "UNKNOWN", "confidence": 0.0}
        return {"current_regime": self._regime, "confidence": self._confidence}


def _bars(n=200):
    pd = pytest.importorskip("pandas")
    return pd.DataFrame(
        {
            "open": [2000.0 + i for i in range(n)],
            "high": [2001.0 + i for i in range(n)],
            "low": [1999.0 + i for i in range(n)],
            "close": [2000.5 + i for i in range(n)],
            "volume": [100.0] * n,
        }
    )


def _with_bars(monkeypatch, df):
    import data_layer.orchestrator  # noqa: F401 — populate sys.modules

    class _Orch:
        @staticmethod
        def get_ohlcv_window(symbol="XAU_USD", bars=200, timeframe="H1"):
            return df

    # sys.modules, not the package attribute: data_layer/__init__.py shadows its
    # own submodule with a MarketDataOrchestrator instance (F245).
    monkeypatch.setattr(sys.modules["data_layer.orchestrator"], "orchestrator", _Orch(), raising=False)


def test_the_detector_is_actually_run(monkeypatch):
    """The whole of F94: route() was never called by anything."""
    import core.regime_router as rr

    router = _Router()
    monkeypatch.setattr(rr, "_get_router", lambda: router)
    _with_bars(monkeypatch, _bars())

    result = rr.get_current_regime("XAUUSD")

    assert router.routed_with, "route() was never called — the regime is still the constructor default"
    assert result is not None
    assert result["regime"] == "TRENDING_UP"
    assert result["confidence"] == pytest.approx(0.82)


def test_a_detected_regime_stops_the_universal_halving(monkeypatch):
    """The consequence that matters: a real regime yields a real scalar."""
    import core.regime_router as rr
    from core.signal_engine import get_regime_position_scalar

    monkeypatch.setattr(rr, "_get_router", lambda: _Router(regime="TRENDING_UP"))
    _with_bars(monkeypatch, _bars())

    regime = rr.get_current_regime("XAUUSD")["regime"]

    assert get_regime_position_scalar(regime) == 1.0, "a detected trending regime is still being halved"


def test_detection_is_not_repeated_on_every_call(monkeypatch):
    """This sits on the per-signal path. Re-detecting per order would put a
    DataFrame build and a fit in front of every trade."""
    import core.regime_router as rr

    router = _Router()
    monkeypatch.setattr(rr, "_get_router", lambda: router)
    _with_bars(monkeypatch, _bars())

    for _ in range(20):
        rr.get_current_regime("XAUUSD")

    assert len(router.routed_with) == 1, f"detector ran {len(router.routed_with)} times for 20 signals"


def test_detection_reruns_once_the_cache_expires(monkeypatch):
    """Cached, not frozen — a cache that never expires is the original defect
    with a shorter duration."""
    import core.regime_router as rr

    router = _Router()
    monkeypatch.setattr(rr, "_get_router", lambda: router)
    _with_bars(monkeypatch, _bars())

    rr.get_current_regime("XAUUSD")
    monkeypatch.setattr(rr, "_last_detect_at", 0.0, raising=False)
    rr.get_current_regime("XAUUSD")

    assert len(router.routed_with) == 2


def test_no_bars_leaves_the_regime_unknown(monkeypatch):
    """Conservative. UNKNOWN keeps the 0.5 scalar; inventing a regime to avoid
    the halving would be worse than the halving."""
    import core.regime_router as rr
    from core.signal_engine import get_regime_position_scalar

    router = _Router()
    monkeypatch.setattr(rr, "_get_router", lambda: router)
    _with_bars(monkeypatch, None)

    result = rr.get_current_regime("XAUUSD")

    assert router.routed_with == [], "the detector was run on no data"
    assert result is None or result["regime"] == "UNKNOWN"
    if result is not None:
        assert get_regime_position_scalar(result["regime"]) == 0.5


def test_a_detector_that_raises_leaves_the_regime_unknown(monkeypatch):
    import core.regime_router as rr

    class _Boom(_Router):
        def route(self, df):
            raise RuntimeError("detector unfitted")

    monkeypatch.setattr(rr, "_get_router", lambda: _Boom())
    _with_bars(monkeypatch, _bars())

    result = rr.get_current_regime("XAUUSD")

    assert result is None or result["regime"] == "UNKNOWN"


def test_too_few_bars_is_not_detected_on(monkeypatch):
    """detect_regime on a handful of bars is noise, not a regime."""
    import core.regime_router as rr

    router = _Router()
    monkeypatch.setattr(rr, "_get_router", lambda: router)
    _with_bars(monkeypatch, _bars(n=5))

    rr.get_current_regime("XAUUSD")

    assert router.routed_with == [], "the detector was run on 5 bars"
