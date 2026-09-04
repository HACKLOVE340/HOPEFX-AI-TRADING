# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
A health probe that contacted nothing must not report ok.

``infrastructure/health_engine.py`` ``_probe_broker`` tries Redis for a real
``broker:connection_status``. When Redis is unreachable the exception is
swallowed at DEBUG and it falls through to an environment variable:

    broker_type = os.getenv("BROKER_TYPE", os.getenv("BROKER_DEFAULT", "paper"))
    return {"status": "ok" if broker_type == "paper" else "warning", ...}

Measured with Redis pointed at a dead port (F160):

    BROKER_TYPE=paper   -> status=ok       detail='broker=paper (config only)'
    BROKER_TYPE=oanda   -> status=warning  detail='broker=oanda (config only)'

With ``BROKER_TYPE=paper`` — the active mode — the broker component reported
**ok** having contacted nothing. It read an env var. The broker could be absent,
misconfigured, or an alias with no ``place_market_order`` at all (F107), and the
probe would still be green.

The ``detail`` string says "(config only)", which is honest. But
``HealthReport.ok_count``/``error_count`` and ``_STATUS_RANK`` aggregate on
``status``, not ``detail``, so every rollup, badge and dashboard tile derived
from it showed green. An operator reads the colour, not the string.
"""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.unit


async def _probe(monkeypatch, redis_value=None, redis_raises=False):
    """Run the registered "broker" probe through the engine's own path.

    The probe functions are locals inside ``_register_default_probes``, not class
    attributes, so they cannot be called directly — and going through
    ``probe_one`` exercises the real registration and result mapping rather than
    a function in isolation.
    """
    import cache.redis_client as rc
    import infrastructure.health_engine as he

    class _Redis:
        async def get(self, _key):
            return redis_value

    async def _get_redis():
        if redis_raises:
            raise ConnectionError("redis unreachable")
        return _Redis()

    monkeypatch.setattr(rc, "get_redis", _get_redis, raising=False)

    engine = he.HealthEngine()
    he._register_default_probes(engine)
    result = await engine.probe_one("broker")
    return {"status": result.status, "detail": result.detail, **result.extra}


@pytest.mark.asyncio
@pytest.mark.parametrize("broker_type", ["paper", "oanda", "mt5"])
async def test_no_redis_never_reports_ok(monkeypatch, broker_type):
    """The finding, for every broker type. paper reported ok; the others
    reported warning. None of them had contacted anything."""
    monkeypatch.setenv("BROKER_TYPE", broker_type)

    result = await _probe(monkeypatch, redis_raises=True)

    assert result["status"] != "ok", (
        f"BROKER_TYPE={broker_type} reported ok having contacted nothing — "
        "every rollup and badge derived from this shows green"
    )


@pytest.mark.asyncio
async def test_the_detail_still_says_it_is_config_only(monkeypatch):
    """The detail string was already honest; keep it."""
    monkeypatch.setenv("BROKER_TYPE", "paper")

    result = await _probe(monkeypatch, redis_raises=True)

    assert "config only" in result["detail"]
    assert result["broker_type"] == "paper"


@pytest.mark.asyncio
async def test_a_live_connected_broker_is_ok(monkeypatch):
    """The probe must still be able to report health, or it is useless."""
    monkeypatch.setenv("BROKER_TYPE", "paper")
    payload = json.dumps({"connected": True, "broker_type": "paper"})

    result = await _probe(monkeypatch, redis_value=payload)

    assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_a_live_disconnected_broker_is_not_ok(monkeypatch):
    monkeypatch.setenv("BROKER_TYPE", "paper")
    payload = json.dumps({"connected": False, "broker_type": "paper"})

    result = await _probe(monkeypatch, redis_value=payload)

    assert result["status"] != "ok"


@pytest.mark.asyncio
async def test_an_unverified_status_is_distinguishable_from_a_failure(monkeypatch):
    """"Could not check" and "checked, and it is broken" are different facts.
    Collapsing them into "warning" would make a dead broker and an unreachable
    Redis look identical to whoever is on call."""
    monkeypatch.setenv("BROKER_TYPE", "paper")

    unverified = await _probe(monkeypatch, redis_raises=True)
    disconnected = await _probe(monkeypatch, redis_value=json.dumps({"connected": False, "broker_type": "paper"}))

    assert unverified["status"] != disconnected["status"]
