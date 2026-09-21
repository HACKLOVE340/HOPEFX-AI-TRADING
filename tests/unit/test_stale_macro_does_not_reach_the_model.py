# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_stale_macro_does_not_reach_the_model.py
=======================================================
Making the macro staleness signal *act*, instead of only being visible.

The previous change gave ``MacroStoreBridge`` an honest ``data_age_days()`` and
``is_stale()``. Nothing consumed them. Measured on the deployed data, which ends
2026-03-25, against hourly bars in August::

    macro_store.align_to_hourly(ohlcv).tail(1)
      dxy            99.60
      us10y           4.328
      vix            25.33      ← March's VIX, presented as today's
    all-NaN cols: []

``align_to_hourly`` calls ``.ffill()`` with **no limit**, so the last daily
observation is carried forward indefinitely. The model does not receive a gap,
a NaN, or any indication of age — it receives 142-day-old macro as current fact,
on every prediction. The staleness was reported on a health endpoint while the
inference path consumed the stale values regardless.

Two fabrications in the same function feed the same lie:

* ``.ffill()`` unbounded — old observations become current ones.
* a series that is not loaded is filled with ``0.0`` — and a VIX of 0.0 is not
  "unknown", it is the most extreme calm reading possible. This is the exact
  defect already fixed in ``analysis/chart_analysis.load_macro()`` (a
  ``MacroSnapshot`` defaulting ``vix=0.0`` classified LOW_VOL and cast three
  votes for a calm market on a field nobody filled in).

The fix routes staleness into the actuator that already exists.
``InferenceEngine._features_are_unusable`` abstains on any NaN feature (S4-02 /
S4-03), so capping the forward-fill at ``MACRO_MAX_AGE_DAYS`` turns silent
staleness into an abstention that is already tested and already understood.

**Operational consequence, stated plainly:** with ``FRED_API_KEY`` unset the
bundled CSVs are months old, so the engine will now abstain rather than score.
That is the intended behaviour for a money-moving system — not scoring is safe,
scoring on fabricated macro is not — and ``MACRO_STALE_POLICY=passthrough``
exists for an operator who decides otherwise, deliberately.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

pytestmark = pytest.mark.unit


def _hours(start: str, n: int = 48) -> pd.DatetimeIndex:
    return pd.date_range(start, periods=n, freq="h", tz="UTC")


def _ohlcv(idx) -> pd.DataFrame:
    return pd.DataFrame(
        {"open": 2000.0, "high": 2001.0, "low": 1999.0, "close": 2000.0, "volume": 1.0},
        index=idx,
    )


def _store(series: dict[str, pd.Series]):
    from ml.macro_store import MacroStore

    s = MacroStore()
    s._series = series
    return s


def _daily(dates: list[str], values: list[float]) -> pd.Series:
    return pd.Series(values, index=pd.DatetimeIndex(dates, tz="UTC"), dtype=float)


# ── The forward-fill must not manufacture current data ───────────────────────


def test_a_recent_observation_is_still_carried_forward():
    """Control. Daily macro on hourly bars requires forward-fill; that is
    correct and must keep working."""
    store = _store({"vix": _daily(["2026-08-10"], [17.5])})
    aligned = store.align_to_hourly(_ohlcv(_hours("2026-08-11", 24)))
    assert (aligned["vix"] == 17.5).all()


def test_an_observation_older_than_the_limit_is_not_carried_forward():
    """The deployed failure. March's VIX must not appear on August bars."""
    store = _store({"vix": _daily(["2026-03-25"], [25.33])})
    aligned = store.align_to_hourly(_ohlcv(_hours("2026-08-14", 24)))

    assert aligned["vix"].isna().all(), (
        f"stale macro was forward-filled onto current bars: {aligned['vix'].tail(1).to_dict()}"
    )
    assert not (aligned["vix"] == 25.33).any()


def test_the_cutoff_is_the_configured_age(monkeypatch):
    import ml.macro_store as ms

    store = _store({"vix": _daily(["2026-08-01"], [17.5])})
    idx = _hours("2026-08-06", 24)  # 5 days after the observation

    monkeypatch.setattr(ms, "MACRO_MAX_AGE_DAYS", 7)
    assert (store.align_to_hourly(_ohlcv(idx))["vix"] == 17.5).all()

    monkeypatch.setattr(ms, "MACRO_MAX_AGE_DAYS", 2)
    assert store.align_to_hourly(_ohlcv(idx))["vix"].isna().all()


def test_the_boundary_is_inclusive_not_off_by_one(monkeypatch):
    import ml.macro_store as ms

    monkeypatch.setattr(ms, "MACRO_MAX_AGE_DAYS", 7)
    store = _store({"vix": _daily(["2026-08-01"], [17.5])})

    # Exactly 7 days later: still within the window.
    within = store.align_to_hourly(_ohlcv(pd.DatetimeIndex(["2026-08-08T00:00:00Z"])))
    assert within["vix"].iloc[0] == 17.5

    # A hair past it: gone.
    past = store.align_to_hourly(_ohlcv(pd.DatetimeIndex(["2026-08-08T01:00:00Z"])))
    assert np.isnan(past["vix"].iloc[0])


def test_bars_before_the_first_observation_are_unchanged():
    """Leading fill stays 0.0. It is a different case — pre-history in a 58-year
    training set, not a staleness claim — and changing it would make historical
    backtests abstain."""
    store = _store({"vix": _daily(["2026-08-10"], [17.5])})
    aligned = store.align_to_hourly(_ohlcv(_hours("2026-08-08", 24)))
    assert (aligned["vix"] == 0.0).all()


def test_a_series_that_is_not_loaded_is_unknown_not_zero():
    """A VIX of 0.0 is not "no data" — it is the calmest reading possible, and
    _classify_macro reads it as LOW_VOL."""
    store = _store({"vix": _daily(["2026-08-10"], [17.5])})
    aligned = store.align_to_hourly(_ohlcv(_hours("2026-08-11", 8)), series=["vix", "absent_series"])

    assert (aligned["vix"] == 17.5).all()
    assert aligned["absent_series"].isna().all(), "an unloaded series was fabricated as 0.0"


def test_passthrough_policy_restores_the_old_behaviour(monkeypatch):
    """An operator may decide to accept stale macro. It must be a decision."""
    import ml.macro_store as ms

    monkeypatch.setattr(ms, "MACRO_STALE_POLICY", "passthrough")
    store = _store({"vix": _daily(["2026-03-25"], [25.33])})
    aligned = store.align_to_hourly(_ohlcv(_hours("2026-08-14", 8)))
    assert (aligned["vix"] == 25.33).all()


# ── Staleness reaches the abstain path ───────────────────────────────────────


def test_the_engine_abstains_when_macro_is_stale():
    """End to end: NaN macro features route to the existing S4-02 abstain."""
    from ml.inference_engine import InferenceEngine

    eng = InferenceEngine()
    frame = pd.DataFrame({"a": [1.0], "macro_vix": [np.nan]})
    assert eng._features_are_unusable(frame, "XAUUSD") is True


def test_the_engine_does_not_abstain_on_fresh_macro():
    """Control — without it the test above passes by abstaining always."""
    from ml.inference_engine import InferenceEngine

    eng = InferenceEngine()
    frame = pd.DataFrame({f"f{i}": [float(i) + 1.0] for i in range(20)})
    assert eng._features_are_unusable(frame, "XAUUSD") is False


# ── The bridge's flat features must not fabricate either ─────────────────────


def _bridge(dates: dict, monkeypatch):
    import ml.macro_store as ms
    from data_layer.feeds.macro.store_bridge import MacroStoreBridge

    class _Store:
        def __init__(self, d):
            self._d = d
            self._series = dict.fromkeys(d, object())

        def snapshot(self):
            return self._d

        def load_defaults(self):
            return None

    monkeypatch.setattr(ms, "macro_store", _Store(dates))
    b = MacroStoreBridge()
    b._loaded = True
    return b


def _iso(days_ago: int) -> str:
    from datetime import datetime, timedelta, timezone

    return (datetime.now(tz=timezone.utc) - timedelta(days=days_ago)).date().isoformat()


def test_get_ml_features_omits_a_series_with_no_value(monkeypatch):
    """`macro_vix = 0.0` for a missing series is the same fabrication one layer
    down. Omitting the key lets a consumer see it is absent."""
    b = _bridge({"vix": None, "dxy": {"value": 99.6, "date": _iso(1)}}, monkeypatch)
    features = b.get_ml_features()

    assert features.get("macro_dxy") == pytest.approx(99.6)
    assert "macro_vix" not in features, "a missing series was emitted as 0.0"


def test_get_ml_features_omits_stale_values(monkeypatch):
    b = _bridge({"vix": {"value": 25.33, "date": _iso(142)}}, monkeypatch)
    assert "macro_vix" not in b.get_ml_features(), "a 142-day-old value was served as current"


def test_get_ml_features_keeps_fresh_values(monkeypatch):
    """Control."""
    b = _bridge({"vix": {"value": 17.5, "date": _iso(1)}}, monkeypatch)
    assert b.get_ml_features()["macro_vix"] == pytest.approx(17.5)


def test_get_ml_features_reports_its_own_age(monkeypatch):
    """A consumer that gets fewer keys than it expected needs to know why."""
    b = _bridge({"vix": {"value": 25.33, "date": _iso(142)}}, monkeypatch)
    features = b.get_ml_features()
    assert features["macro_data_age_days"] == pytest.approx(142)
    assert features["macro_stale"] == 1.0


def test_fresh_data_reports_not_stale(monkeypatch):
    b = _bridge({"vix": {"value": 17.5, "date": _iso(1)}}, monkeypatch)
    features = b.get_ml_features()
    assert features["macro_stale"] == 0.0
    assert features["macro_data_age_days"] == pytest.approx(1)


def test_the_features_stay_json_serialisable(monkeypatch):
    """NaN is not valid JSON and these reach API responses — omit, never NaN."""
    import json

    b = _bridge({"vix": {"value": 25.33, "date": _iso(142)}, "dxy": None}, monkeypatch)
    features = b.get_ml_features()
    json.dumps(features)  # raises on NaN with allow_nan=False below
    json.dumps(features, allow_nan=False)
    assert all(isinstance(v, float) and np.isfinite(v) for v in features.values())
