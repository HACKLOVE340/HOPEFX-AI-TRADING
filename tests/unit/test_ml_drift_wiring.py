# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The drift score must not report "no drift" when it measured nothing.

## What this file used to assert, and why it changed

The first version of this file pinned a real fix: `/ml/models` and `/ml/status`
had hardcoded `drift_score = 0.0` on every row, so the dashboard showed every
model as zero-drift regardless of reality. Routing both through
`_live_drift_score()` — one helper, reading the drift monitor — was right, and
those tests still stand.

But two of them pinned the fallback as well:

    def test_live_drift_score_defaults_zero_when_unavailable(...):
        assert ml_ai._live_drift_score() == 0.0

    def test_live_drift_score_never_raises(...):
        assert ml_ai._live_drift_score() == 0.0  # best-effort, swallows errors

`0.0` is the *best* value on this scale. So "Redis is down", "the monitor has
never run" and "the JSON was malformed" all rendered as a green **0.000** next
to a healthy model — and a passing test said that was the requirement. The
helper's own docstring claimed it existed "so the dashboard never shows a
hardcoded zero while real drift exists", while being the hardcoded zero.

This was found by running the application, not by reading it: a booted server
answered `GET /api/superadmin/ml/status` with `drift_score: 0.0` alongside
`predictions_today: 0` — a no-drift verdict from a monitor that had never seen
a prediction.

Rule 2: an unmeasured value is absent, never best case. `_live_drift_score()`
now returns `None` when it could not measure, and the endpoints carry a
`drift_state` of `"measured"` or `"unmeasured"` so a caller cannot mistake one
for the other. "Never raises" is preserved — that part was always right; only
the value it fell back to was wrong.
"""

from __future__ import annotations

import json
import logging

import pytest

from api.superadmin import ml_ai

pytestmark = pytest.mark.unit


class _FakeRedis:
    def __init__(self, value):
        self._value = value

    def get(self, key):
        return self._value


def _patch_redis(monkeypatch, factory):
    # The helper imports get_sync_redis_client from cache.redis_client at call
    # time, so patch it at the source module.
    import cache.redis_client as rc

    monkeypatch.setattr(rc, "get_sync_redis_client", factory)


class TestAMeasurementIsReportedAsMeasured:
    def test_live_drift_score_reads_monitor(self, monkeypatch) -> None:
        _patch_redis(monkeypatch, lambda: _FakeRedis(json.dumps({"drift_score": 0.37})))
        assert ml_ai._live_drift_score() == pytest.approx(0.37)

    def test_a_genuine_zero_is_still_zero(self, monkeypatch) -> None:
        # The point is not "0.0 is forbidden". A monitor that ran and measured
        # no drift must still be able to say so, and must be distinguishable
        # from a monitor that never ran.
        _patch_redis(monkeypatch, lambda: _FakeRedis(json.dumps({"drift_score": 0.0})))
        assert ml_ai._live_drift_score() == 0.0


class TestAbsenceIsReportedAsAbsence:
    """Each of these used to answer 0.0 — "no drift" — and be asserted as correct."""

    def test_no_redis_client_is_unmeasured(self, monkeypatch) -> None:
        _patch_redis(monkeypatch, lambda: None)
        assert ml_ai._live_drift_score() is None

    def test_missing_monitor_key_is_unmeasured(self, monkeypatch) -> None:
        # The monitor has never written a status. Nothing has been measured.
        _patch_redis(monkeypatch, lambda: _FakeRedis(None))
        assert ml_ai._live_drift_score() is None

    def test_malformed_payload_is_unmeasured(self, monkeypatch) -> None:
        _patch_redis(monkeypatch, lambda: _FakeRedis("{not json"))
        assert ml_ai._live_drift_score() is None

    def test_payload_without_a_drift_score_is_unmeasured(self, monkeypatch) -> None:
        # A status document that carries no drift_score is not a zero drift
        # score; .get(..., 0.0) used to turn it into one.
        _patch_redis(monkeypatch, lambda: _FakeRedis(json.dumps({"updated_at": "now"})))
        assert ml_ai._live_drift_score() is None

    def test_non_numeric_drift_score_is_unmeasured(self, monkeypatch) -> None:
        _patch_redis(monkeypatch, lambda: _FakeRedis(json.dumps({"drift_score": "high"})))
        assert ml_ai._live_drift_score() is None


class TestItStillNeverRaises:
    """That part of the old contract was right and is kept."""

    def test_a_raising_redis_client_is_unmeasured_not_an_exception(self, monkeypatch) -> None:
        def _boom():
            raise RuntimeError("redis down")

        _patch_redis(monkeypatch, _boom)
        assert ml_ai._live_drift_score() is None


class TestTheFailureIsAudible:
    """`except Exception: logger.debug(...)` is off in production.

    Four alert call sites in this repository failed silently for months behind
    exactly that (F248). A drift monitor that cannot be reached is an
    operational fact somebody needs to see.
    """

    def test_a_redis_failure_logs_above_debug(self, monkeypatch, caplog) -> None:
        def _boom():
            raise RuntimeError("redis down")

        _patch_redis(monkeypatch, _boom)
        with caplog.at_level(logging.INFO, logger=ml_ai.logger.name):
            ml_ai._live_drift_score()
        assert any(r.levelno >= logging.WARNING for r in caplog.records), (
            "the drift monitor was unreachable and nothing was logged above DEBUG"
        )


class TestTheEndpointDistinguishesTheTwo:
    """A number alone cannot carry "I could not measure this"."""

    @staticmethod
    def _status(monkeypatch, drift):
        # @router.get returns the original coroutine function, so it is called
        # directly; the auth dependency is a default argument and is not
        # evaluated outside a request.
        import asyncio

        monkeypatch.setattr(ml_ai, "_live_drift_score", lambda: drift)
        return asyncio.run(ml_ai.get_ml_status(user=None))

    def test_unmeasured_drift_is_not_reported_as_zero(self, monkeypatch) -> None:
        body = self._status(monkeypatch, None)
        assert body["drift_score"] is None, "an unmeasured drift score was reported as a number"
        assert body["drift_state"] == "unmeasured"

    def test_measured_drift_is_reported_with_its_value(self, monkeypatch) -> None:
        body = self._status(monkeypatch, 0.42)
        assert body["drift_score"] == pytest.approx(0.42)
        assert body["drift_state"] == "measured"

    def test_a_measured_zero_is_measured(self, monkeypatch) -> None:
        body = self._status(monkeypatch, 0.0)
        assert body["drift_score"] == 0.0
        assert body["drift_state"] == "measured"
