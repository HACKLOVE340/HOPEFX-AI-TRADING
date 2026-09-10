# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""What happens to work that arrives while the price feed is down.

`data_layer/feeds/gold/manager.py` already fails over across six providers with
per-feed circuit breakers, and `MarketDataOrchestrator.get_latest_tick()`
already refuses to serve a stale or future-dated cached tick, returns `None`
rather than guessing, and no longer answers a non-gold symbol with the gold
price. That half is built and wired.

What did not exist is the other half: when every source is down, work still
arrives — a signal fires, an operator clicks, a scheduled rebalance comes due —
and there was nowhere for it to go except a `None` and a log line.

`data_layer/outage.py` gives it somewhere to go, under one rule that shapes
every test here:

    **A deferred trade action is never replayed automatically.**

The market moved while the feed was down. An order intent formed against a
price from before the outage is not a valid intent after it — replaying it is
the same defect as serving a stale tick, one layer up, and with an order at the
end of it. The queue therefore hands back each item *with its age and its price
context*, and the caller re-decides. Draining is not executing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest


def _at(seconds_ago: float) -> datetime:
    return datetime.now(UTC) - timedelta(seconds=seconds_ago)


# ── the state anything can read ───────────────────────────────────────────────


class TestFeedHealthIsObservable:
    def test_a_fresh_tick_is_healthy(self):
        from data_layer.outage import FeedHealth

        h = FeedHealth.from_tick(last_tick_at=_at(1.0), sources_up=3, sources_total=6)
        assert h.state == "healthy"
        assert h.is_live is True
        assert h.age_s == pytest.approx(1.0, abs=0.5)

    def test_an_old_tick_is_degraded_not_healthy(self):
        from data_layer.outage import FeedHealth

        h = FeedHealth.from_tick(last_tick_at=_at(45.0), sources_up=1, sources_total=6)
        assert h.state == "degraded"
        assert h.is_live is False

    def test_no_tick_at_all_is_an_outage_not_a_zero_age(self):
        """Rule 2 at the feed layer: never measured is not "0 seconds old"."""
        from data_layer.outage import FeedHealth

        h = FeedHealth.from_tick(last_tick_at=None, sources_up=0, sources_total=6)
        assert h.state == "outage"
        assert h.is_live is False
        assert h.age_s is None, "an unmeasured age must be None, never 0.0"

    def test_every_source_down_is_an_outage_even_with_a_recent_tick(self):
        """A cached tick does not mean the feed is up.

        This is the case that makes a dashboard lie: the last tick is 3 seconds
        old and every provider is dead, so the next second there will be no
        tick at all. Reporting "healthy" here is how an operator learns about
        an outage from a customer.
        """
        from data_layer.outage import FeedHealth

        h = FeedHealth.from_tick(last_tick_at=_at(3.0), sources_up=0, sources_total=6)
        assert h.state == "outage"
        assert h.is_live is False

    def test_health_serialises_for_an_api_and_a_dashboard(self):
        import json

        from data_layer.outage import FeedHealth

        h = FeedHealth.from_tick(last_tick_at=_at(2.0), sources_up=2, sources_total=6)
        payload = json.loads(json.dumps(h.as_dict()))
        assert set(payload) >= {"state", "is_live", "age_s", "sources_up", "sources_total", "observed_at"}
        assert payload["state"] in ("healthy", "degraded", "outage")


# ── the queue ─────────────────────────────────────────────────────────────────


class TestDeferredWorkIsHeldNotLost:
    def test_work_deferred_during_an_outage_comes_back(self):
        from data_layer.outage import DeferredWorkQueue

        q = DeferredWorkQueue(maxlen=10)
        q.defer(kind="signal", payload={"symbol": "XAUUSD", "side": "buy"}, reason="feed_outage")
        assert q.pending() == 1

        items = q.drain()
        assert len(items) == 1
        assert items[0].kind == "signal"
        assert items[0].payload["symbol"] == "XAUUSD"
        assert q.pending() == 0, "drain must empty the queue"

    def test_each_item_reports_how_long_it_waited(self):
        """The caller cannot re-decide without knowing how stale the intent is."""
        from data_layer.outage import DeferredWorkQueue

        q = DeferredWorkQueue(maxlen=10)
        q.defer(kind="signal", payload={}, reason="feed_outage", at=_at(120.0))
        item = q.drain()[0]
        assert item.age_s() == pytest.approx(120.0, abs=1.0)

    def test_the_queue_is_bounded_and_drops_the_oldest(self):
        """Unbounded queues turn a feed outage into an out-of-memory outage.

        The oldest goes first deliberately: during a long outage the newest
        intents are the ones formed against the most recent known price.
        """
        from data_layer.outage import DeferredWorkQueue

        q = DeferredWorkQueue(maxlen=3)
        for i in range(5):
            q.defer(kind="signal", payload={"n": i}, reason="feed_outage")
        items = q.drain()
        assert [i.payload["n"] for i in items] == [2, 3, 4]
        assert q.dropped == 2, "a dropped intent must be counted, not silently lost"

    def test_dropping_is_visible_in_the_health_report(self):
        from data_layer.outage import DeferredWorkQueue

        q = DeferredWorkQueue(maxlen=1)
        q.defer(kind="signal", payload={}, reason="feed_outage")
        q.defer(kind="signal", payload={}, reason="feed_outage")
        assert q.as_dict()["dropped"] == 1


class TestReplayIsNeverAutomatic:
    def test_draining_does_not_execute_anything(self):
        """The queue holds data. It has no broker, no OMS, no execute path.

        Stated as a test because "it just returns a list" is the property that
        makes the whole design safe, and a future edit that adds an `on_drain`
        callback would quietly turn a 40-minute-old intent into a live order.
        """
        from data_layer.outage import DeferredWorkQueue

        q = DeferredWorkQueue(maxlen=5)
        forbidden = {"execute", "submit", "send", "place_order", "replay_now", "on_drain"}
        surface = {name for name in dir(q) if not name.startswith("_")}
        assert not (surface & forbidden), f"the queue must not be able to act: {surface & forbidden}"

    def test_an_item_older_than_the_limit_is_marked_expired(self):
        from data_layer.outage import DeferredWorkQueue

        q = DeferredWorkQueue(maxlen=5, max_replay_age_s=60.0)
        q.defer(kind="signal", payload={}, reason="feed_outage", at=_at(600.0))
        q.defer(kind="signal", payload={}, reason="feed_outage", at=_at(5.0))

        items = q.drain()
        assert [i.expired for i in items] == [True, False]

    def test_expired_items_are_still_returned_not_dropped(self):
        """An expired intent is evidence about the outage, not rubbish.

        Silently discarding it would leave no record that a signal fired and
        nothing happened — the same invisibility this whole programme keeps
        removing.
        """
        from data_layer.outage import DeferredWorkQueue

        q = DeferredWorkQueue(maxlen=5, max_replay_age_s=1.0)
        q.defer(kind="signal", payload={"id": "s1"}, reason="feed_outage", at=_at(500.0))
        items = q.drain()
        assert len(items) == 1
        assert items[0].expired is True
        assert items[0].payload["id"] == "s1"

    def test_the_price_context_at_deferral_is_carried(self):
        """Re-deciding needs to know what the price was believed to be."""
        from data_layer.outage import DeferredWorkQueue

        q = DeferredWorkQueue(maxlen=5)
        q.defer(
            kind="signal",
            payload={"symbol": "XAUUSD"},
            reason="feed_outage",
            price_context={"last_mid": 2400.5, "last_tick_age_s": 31.2, "source": "goldapi"},
        )
        item = q.drain()[0]
        assert item.price_context["last_mid"] == 2400.5
        assert item.price_context["source"] == "goldapi"

    def test_no_price_context_is_none_not_an_invented_price(self):
        from data_layer.outage import DeferredWorkQueue

        q = DeferredWorkQueue(maxlen=5)
        q.defer(kind="signal", payload={}, reason="feed_outage")
        assert q.drain()[0].price_context is None


# ── the two together ──────────────────────────────────────────────────────────


class TestTheSupervisorTiesThemTogether:
    def test_it_defers_while_down_and_reports_on_recovery(self):
        from data_layer.outage import FeedOutageSupervisor

        sup = FeedOutageSupervisor(maxlen=10)

        sup.observe(last_tick_at=None, sources_up=0, sources_total=6)
        assert sup.health.state == "outage"
        sup.defer(kind="signal", payload={"symbol": "XAUUSD"}, reason="feed_outage")

        recovered = sup.observe(last_tick_at=_at(0.5), sources_up=4, sources_total=6)
        assert sup.health.state == "healthy"
        assert recovered is not None, "recovery must hand back what was held"
        assert len(recovered) == 1

    def test_recovery_returns_nothing_when_nothing_was_deferred(self):
        from data_layer.outage import FeedOutageSupervisor

        sup = FeedOutageSupervisor(maxlen=10)
        sup.observe(last_tick_at=None, sources_up=0, sources_total=6)
        assert sup.observe(last_tick_at=_at(0.5), sources_up=4, sources_total=6) == []

    def test_staying_healthy_is_not_a_recovery_event(self):
        """A recovery hand-back on every healthy tick would replay forever."""
        from data_layer.outage import FeedOutageSupervisor

        sup = FeedOutageSupervisor(maxlen=10)
        sup.observe(last_tick_at=_at(0.5), sources_up=4, sources_total=6)
        assert sup.observe(last_tick_at=_at(0.4), sources_up=4, sources_total=6) is None

    def test_the_outage_start_is_recorded(self):
        from data_layer.outage import FeedOutageSupervisor

        sup = FeedOutageSupervisor(maxlen=10)
        sup.observe(last_tick_at=_at(0.5), sources_up=4, sources_total=6)
        assert sup.outage_since is None
        sup.observe(last_tick_at=None, sources_up=0, sources_total=6)
        assert sup.outage_since is not None
        sup.observe(last_tick_at=_at(0.5), sources_up=4, sources_total=6)
        assert sup.outage_since is None, "recovery clears the outage start"
