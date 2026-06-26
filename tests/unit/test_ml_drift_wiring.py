# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Regression test for the drift_score=0.0 stub finding.

The /ml/models and /ml/status endpoints previously hardcoded drift_score=0.0,
so the dashboard always showed every model as zero-drift regardless of reality
(a 'looks right, behaves wrong' bug the runtime checker flagged). The drift
score must now come from the drift monitor (Redis) via a single helper.
"""

from __future__ import annotations

import json

import pytest

from api.superadmin import ml_ai

pytestmark = pytest.mark.unit


class _FakeRedis:
    def __init__(self, value):
        self._value = value

    def get(self, key):
        return self._value


def test_live_drift_score_reads_monitor(monkeypatch):
    # The helper imports get_sync_redis_client from cache.redis_client at call
    # time, so patch it at the source module.
    import cache.redis_client as rc

    payload = json.dumps({"drift_score": 0.37})
    monkeypatch.setattr(rc, "get_sync_redis_client", lambda: _FakeRedis(payload))
    assert ml_ai._live_drift_score() == pytest.approx(0.37)


def test_live_drift_score_defaults_zero_when_unavailable(monkeypatch):
    import cache.redis_client as rc

    monkeypatch.setattr(rc, "get_sync_redis_client", lambda: None)
    assert ml_ai._live_drift_score() == 0.0


def test_live_drift_score_never_raises(monkeypatch):
    import cache.redis_client as rc

    def _boom():
        raise RuntimeError("redis down")

    monkeypatch.setattr(rc, "get_sync_redis_client", _boom)
    assert ml_ai._live_drift_score() == 0.0  # best-effort, swallows errors
