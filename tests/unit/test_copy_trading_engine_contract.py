# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_copy_trading_engine_contract.py
================================================
``api/copy_trading.py`` was written against an engine that does not exist.

The router calls seven methods — ``get_user_copies``, ``pause_copy``,
``resume_copy``, ``stop_copy``, ``adjust_risk``, ``get_copy_performance``,
``get_master_traders``. There are three copy-trading engine classes in this
repository and **none of them defines any of the seven**:

* ``social/copy_trading.py::CopyTradingEngine`` — the one production uses.
  ``social/__init__`` constructs the singleton, ``init_social`` assigns it to
  ``app_state``. It offers ``start_copying`` / ``stop_copying`` /
  ``get_active_relationships``.
* ``social/copy_trading_engine.py::AdvancedCopyTradingEngine`` — what the
  router's fallback constructed. Different interface again.
* ``social/advanced_copy_trading.py::CopyTradingEngine`` — a third, unused.

So every route raised ``AttributeError``. ``GET /my-copies`` caught it and
returned ``{"copies": [], "total": 0}``, which is exactly what a user with no
subscriptions sees, so a feature that could not work presented as one nobody
had used. The rest returned HTTP 500.

Two things this fix had to avoid introducing, both tested below:

**Ownership.** ``copy_id`` came straight from the URL and nothing tied it to the
caller. The ids are ``follower_leader``, so they are guessable. Once these
methods existed, any professional-plan user could pause, re-risk or stop
somebody else's copy.

**The email leak.** ``get_master_traders`` builds on ``TraderProfile.to_dict()``,
which includes ``email`` — and ``GET /masters`` has no auth dependency at all.
Returning the profile dict would have published every public trader's email
address to unauthenticated callers.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from social.copy_trading import CopyTradingEngine

pytestmark = pytest.mark.unit

_ROUTER_METHODS = (
    "get_user_copies",
    "pause_copy",
    "resume_copy",
    "stop_copy",
    "adjust_risk",
    "get_copy_performance",
    "get_master_traders",
)


@pytest.fixture
def engine():
    eng = CopyTradingEngine(broker=None)
    eng.start_copying("alice", "leader-1", copy_ratio=0.5)
    eng.start_copying("bob", "leader-1", copy_ratio=1.0)
    return eng


def _copy_id(follower: str, leader: str) -> str:
    return f"{follower}_{leader}"


@pytest.mark.parametrize("name", _ROUTER_METHODS)
def test_the_engine_implements_what_the_router_calls(name):
    assert hasattr(CopyTradingEngine, name), (
        f"api/copy_trading.py awaits engine.{name}(), which does not exist — "
        "every request to that route raises AttributeError"
    )


# ── Listing ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_user_sees_their_own_copies_only(engine):
    copies = await engine.get_user_copies("alice")
    assert [c["leader_id"] for c in copies] == ["leader-1"]
    assert all(c["follower_id"] == "alice" for c in copies)


@pytest.mark.asyncio
async def test_a_paused_copy_is_still_listed(engine):
    """Otherwise there is no way to resume it."""
    await engine.pause_copy(_copy_id("alice", "leader-1"), user_id="alice")

    copies = await engine.get_user_copies("alice")
    assert len(copies) == 1
    assert copies[0]["status"] == "paused"


# ── Pause / resume / stop ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pausing_stops_the_copy_receiving_trades(engine):
    """The pause has to reach the routing gate, not just the label."""
    await engine.pause_copy(_copy_id("alice", "leader-1"), user_id="alice")

    followers = engine.sync_trade("t-1", "leader-1")
    assert "alice" not in followers.values()
    assert "bob" in followers.values()


@pytest.mark.asyncio
async def test_resuming_puts_it_back(engine):
    cid = _copy_id("alice", "leader-1")
    await engine.pause_copy(cid, user_id="alice")
    await engine.resume_copy(cid, user_id="alice")

    assert "alice" in engine.sync_trade("t-2", "leader-1").values()


@pytest.mark.asyncio
async def test_stopping_removes_the_relationship(engine):
    cid = _copy_id("alice", "leader-1")
    await engine.stop_copy(cid, user_id="alice")

    assert cid not in engine.relationships
    assert await engine.get_user_copies("alice") == []


@pytest.mark.asyncio
async def test_an_unknown_copy_raises_value_error(engine):
    """The router maps ValueError to 404."""
    with pytest.raises(ValueError):
        await engine.pause_copy("nobody_nothing", user_id="alice")


# ── Ownership ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["pause_copy", "resume_copy", "stop_copy"])
async def test_one_user_cannot_touch_another_users_copy(engine, method):
    bobs_copy = _copy_id("bob", "leader-1")

    with pytest.raises(ValueError):
        await getattr(engine, method)(bobs_copy, user_id="alice")

    assert engine.relationships[bobs_copy].is_active, "alice altered bob's copy"


@pytest.mark.asyncio
async def test_another_users_copy_is_not_confirmed_to_exist(engine):
    """Same error for 'no such copy' and 'not yours' — a distinguishable one
    would confirm the existence of someone else's subscription."""
    with pytest.raises(ValueError) as not_yours:
        await engine.pause_copy(_copy_id("bob", "leader-1"), user_id="alice")
    with pytest.raises(ValueError) as no_such:
        await engine.pause_copy(_copy_id("zoe", "leader-9"), user_id="alice")

    assert str(not_yours.value).replace("bob_leader-1", "X") == str(no_such.value).replace("zoe_leader-9", "X")


@pytest.mark.asyncio
async def test_risk_adjustment_is_owner_only(engine):
    with pytest.raises(ValueError):
        await engine.adjust_risk(_copy_id("bob", "leader-1"), {"copy_ratio": 9.0}, user_id="alice")

    assert engine.relationships[_copy_id("bob", "leader-1")].copy_ratio == 1.0


# ── Risk adjustment ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_adjusting_the_ratio_changes_copied_size(engine):
    cid = _copy_id("alice", "leader-1")
    await engine.adjust_risk(cid, {"copy_ratio": 2.0}, user_id="alice")

    assert engine.relationships[cid].copy_ratio == 2.0


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [0, -1, 11, "abc", None])
async def test_a_bad_ratio_is_rejected_rather_than_stored(engine, bad):
    """copy_ratio scales real orders in broadcast_trade. A negative or absurd
    value would mis-size every copied trade until someone noticed."""
    cid = _copy_id("alice", "leader-1")
    before = engine.relationships[cid].copy_ratio

    if bad is None:
        # None means "not supplied" and must leave the value alone.
        await engine.adjust_risk(cid, {"copy_ratio": None}, user_id="alice")
    else:
        with pytest.raises(ValueError):
            await engine.adjust_risk(cid, {"copy_ratio": bad}, user_id="alice")

    assert engine.relationships[cid].copy_ratio == before


@pytest.mark.asyncio
async def test_caps_must_be_positive(engine):
    cid = _copy_id("alice", "leader-1")
    with pytest.raises(ValueError):
        await engine.adjust_risk(cid, {"max_per_trade": -5}, user_id="alice")

    await engine.adjust_risk(cid, {"max_per_trade": 2.5}, user_id="alice")
    assert engine.relationships[cid].max_per_trade == Decimal("2.5")


# ── Performance ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_performance_does_not_invent_a_pnl(engine):
    """Per-copy P&L is not recorded anywhere: copied fills carry the leader's
    fill id in order metadata and nothing reads it back. Reporting a plausible
    zero would be worse than reporting none."""
    perf = await engine.get_copy_performance(_copy_id("alice", "leader-1"), user_id="alice")

    assert perf["pnl_available"] is False
    assert perf["pnl_unavailable_reason"]
    assert "pnl" not in {k for k in perf if k not in ("pnl_available", "pnl_unavailable_reason")}


@pytest.mark.asyncio
async def test_performance_is_owner_only(engine):
    with pytest.raises(ValueError):
        await engine.get_copy_performance(_copy_id("bob", "leader-1"), user_id="alice")


# ── Master traders ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_master_traders_never_expose_an_email(engine, monkeypatch):
    """GET /masters has no auth dependency. TraderProfile.to_dict() carries the
    trader's email address."""
    import social

    class _Profile:
        def to_dict(self):
            return {
                "trader_id": "leader-1",
                "username": "carol",
                "email": "carol@example.com",
                "total_pnl": 1000.0,
                "win_rate": 0.6,
                "sharpe_ratio": 1.2,
                "total_trades": 40,
            }

    class _Mgr:
        def list_profiles(self, public_only=False):
            return [_Profile()]

    monkeypatch.setattr(social, "profile_manager", _Mgr())

    masters = await engine.get_master_traders()
    assert masters, "no masters returned"
    for row in masters:
        assert "email" not in row, f"the master traders listing leaks an email address: {row}"


@pytest.mark.asyncio
async def test_follower_counts_come_from_live_relationships(engine, monkeypatch):
    """``profile.total_followers`` is never updated when a copy starts or stops,
    so it would have drifted from first use."""
    import social

    class _Profile:
        def to_dict(self):
            return {"trader_id": "leader-1", "username": "carol", "total_followers": 999}

    class _Mgr:
        def list_profiles(self, public_only=False):
            return [_Profile()]

    monkeypatch.setattr(social, "profile_manager", _Mgr())

    masters = await engine.get_master_traders()
    assert masters[0]["followers"] == 2, "expected the two live relationships, not the stale profile field"


@pytest.mark.asyncio
async def test_every_sort_key_the_router_accepts_is_supported(engine, monkeypatch):
    """The router validated ``sort_by`` against a pattern that included values
    the engine never handled, so they fell through to an arbitrary order that
    still looked ranked."""
    import inspect
    import re

    import social
    import api.copy_trading as mod

    # The values the route will actually let through, read off its own regex so
    # this test cannot drift from the router.
    src = inspect.getsource(mod.get_master_traders)
    allowed = set(re.search(r'pattern="\^\(([^)]+)\)\$"', src).group(1).split("|"))
    assert allowed, "could not read the sort_by pattern out of the route"

    profiles = [
        {"trader_id": "a", "username": "a", "total_pnl": 1.0, "win_rate": 0.9, "sharpe_ratio": 0.1, "total_trades": 5},
        {"trader_id": "b", "username": "b", "total_pnl": 9.0, "win_rate": 0.1, "sharpe_ratio": 2.0, "total_trades": 1},
    ]

    class _P:
        def __init__(self, d):
            self._d = d

        def to_dict(self):
            return dict(self._d)

    class _Mgr:
        def list_profiles(self, public_only=False):
            return [_P(d) for d in profiles]

    monkeypatch.setattr(social, "profile_manager", _Mgr())

    expected_top = {"profit": "b", "win_rate": "a", "sharpe": "b", "trades": "a"}
    for key in sorted(allowed):
        rows = await engine.get_master_traders(sort_by=key)
        assert rows, f"sort_by={key} returned nothing"
        if key in expected_top:
            assert rows[0]["trader_id"] == expected_top[key], (
                f"sort_by={key} did not rank by that field — it fell through to the default"
            )
