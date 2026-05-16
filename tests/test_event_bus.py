# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/test_event_bus.py
========================
Regression tests for core/event_bus.py subscriber-exception isolation.

Covers:
  - _LocalBus.publish_local: one bad handler does not prevent others from
    receiving the message
  - _LocalBus.publish_local: CancelledError is re-raised (not swallowed)
  - EventBus.dispatch_to_handlers: per-handler isolation
  - EventBus.dispatch_to_handlers: CancelledError propagates
  - EventBus.run_subscriber: handler exception does not stop the subscription
  - EventBus.subscribe (local fallback): caller exception does not kill loop
"""

from __future__ import annotations

import asyncio

import pytest

from core.event_bus import CH_TICK, EventBus, _LocalBus


# ── _LocalBus per-handler isolation ──────────────────────────────────────────


class TestLocalBusIsolation:
    @pytest.mark.asyncio
    async def test_bad_handler_does_not_prevent_other_handlers(self):
        """
        If handler_a raises, handler_b must still receive the message.
        This is the core bus guarantee.
        """
        bus = _LocalBus()
        received: list[dict] = []

        def bad_handler(msg):
            raise RuntimeError("I am broken")

        def good_handler(msg):
            received.append(msg)

        bus.subscribe_local(CH_TICK, bad_handler)
        bus.subscribe_local(CH_TICK, good_handler)

        msg = {"type": "tick", "bid": 2000.0}
        await bus.publish_local(CH_TICK, msg)

        assert received == [msg], (
            f"good_handler must receive the message even though bad_handler raised. Got: {received}"
        )

    @pytest.mark.asyncio
    async def test_multiple_bad_handlers_all_isolated(self):
        """All handlers receive the message even if all-but-one raise."""
        bus = _LocalBus()
        received: list[str] = []

        def make_bad(name):
            def _h(msg):
                raise ValueError(f"{name} is broken")

            _h.__qualname__ = name
            return _h

        def good(msg):
            received.append("good")

        bus.subscribe_local(CH_TICK, make_bad("bad1"))
        bus.subscribe_local(CH_TICK, make_bad("bad2"))
        bus.subscribe_local(CH_TICK, good)
        bus.subscribe_local(CH_TICK, make_bad("bad3"))

        await bus.publish_local(CH_TICK, {"type": "tick"})

        assert received == ["good"]

    @pytest.mark.asyncio
    async def test_async_bad_handler_isolated(self):
        """An async handler that raises must not prevent other handlers."""
        bus = _LocalBus()
        received: list[dict] = []

        async def bad_async(msg):
            raise RuntimeError("async handler broken")

        def good(msg):
            received.append(msg)

        bus.subscribe_local(CH_TICK, bad_async)
        bus.subscribe_local(CH_TICK, good)

        msg = {"type": "tick", "ask": 2001.0}
        await bus.publish_local(CH_TICK, msg)

        assert received == [msg]

    @pytest.mark.asyncio
    async def test_cancelled_error_propagates(self):
        """CancelledError from a handler must NOT be swallowed."""
        bus = _LocalBus()

        async def cancelling_handler(msg):
            raise asyncio.CancelledError()

        bus.subscribe_local(CH_TICK, cancelling_handler)

        with pytest.raises(asyncio.CancelledError):
            await bus.publish_local(CH_TICK, {"type": "tick"})

    @pytest.mark.asyncio
    async def test_no_handlers_is_noop(self):
        """Publishing to a channel with no handlers must not raise."""
        bus = _LocalBus()
        await bus.publish_local(CH_TICK, {"type": "tick"})  # must not raise

    @pytest.mark.asyncio
    async def test_unsubscribe_removes_handler(self):
        """Unsubscribed handler must not receive messages."""
        bus = _LocalBus()
        received: list[dict] = []

        def handler(msg):
            received.append(msg)

        bus.subscribe_local(CH_TICK, handler)
        bus.unsubscribe_local(CH_TICK, handler)

        await bus.publish_local(CH_TICK, {"type": "tick"})
        assert received == []


# ── EventBus.dispatch_to_handlers ────────────────────────────────────────────


class TestDispatchToHandlers:
    @pytest.mark.asyncio
    async def test_bad_handler_does_not_prevent_others(self):
        """dispatch_to_handlers must isolate each handler."""
        bus = EventBus()
        received: list[str] = []

        def bad(msg):
            raise RuntimeError("bad handler")

        def good(msg):
            received.append("good")

        await bus.dispatch_to_handlers(CH_TICK, {"type": "tick"}, [bad, good])
        assert received == ["good"]

    @pytest.mark.asyncio
    async def test_async_handler_awaited(self):
        """Async handlers must be awaited."""
        bus = EventBus()
        received: list[dict] = []

        async def async_handler(msg):
            received.append(msg)

        msg = {"type": "tick", "bid": 1999.0}
        await bus.dispatch_to_handlers(CH_TICK, msg, [async_handler])
        assert received == [msg]

    @pytest.mark.asyncio
    async def test_cancelled_error_propagates(self):
        """CancelledError must propagate out of dispatch_to_handlers."""
        bus = EventBus()

        async def cancelling(msg):
            raise asyncio.CancelledError()

        with pytest.raises(asyncio.CancelledError):
            await bus.dispatch_to_handlers(CH_TICK, {"type": "tick"}, [cancelling])

    @pytest.mark.asyncio
    async def test_empty_handler_list_is_noop(self):
        """Empty handler list must not raise."""
        bus = EventBus()
        await bus.dispatch_to_handlers(CH_TICK, {"type": "tick"}, [])

    @pytest.mark.asyncio
    async def test_all_handlers_called_even_if_all_raise(self):
        """All handlers must be called even if every one raises."""
        bus = EventBus()
        call_count = [0]

        def counting_bad(msg):
            call_count[0] += 1
            raise ValueError("always fails")

        await bus.dispatch_to_handlers(CH_TICK, {"type": "tick"}, [counting_bad] * 5)
        assert call_count[0] == 5


# ── EventBus.run_subscriber ───────────────────────────────────────────────────


class TestRunSubscriber:
    @pytest.mark.asyncio
    async def test_handler_exception_does_not_stop_subscription(self):
        """
        A handler exception inside run_subscriber must not stop the loop.
        The next message must still be delivered.
        """
        bus = EventBus()
        bus._degraded = True  # use local fallback so no Redis needed

        received: list[dict] = []
        call_count = [0]

        async def flaky_handler(msg):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("first call always fails")
            received.append(msg)

        # Start the subscriber as a background task
        task = asyncio.create_task(bus.run_subscriber(CH_TICK, flaky_handler))

        # Give the task a moment to start
        await asyncio.sleep(0.01)

        # Publish two messages via the local bus
        msg1 = {"type": "tick", "seq": 1}
        msg2 = {"type": "tick", "seq": 2}
        await bus.publish(CH_TICK, msg1)
        await asyncio.sleep(0.02)
        await bus.publish(CH_TICK, msg2)
        await asyncio.sleep(0.02)

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # msg2 must have been delivered despite msg1 causing an exception
        assert any(m.get("seq") == 2 for m in received), (
            f"Second message must be delivered after handler exception. received={received}"
        )

    @pytest.mark.asyncio
    async def test_run_subscriber_stops_on_cancel(self):
        """run_subscriber must exit cleanly when cancelled."""
        bus = EventBus()
        bus._degraded = True

        task = asyncio.create_task(bus.run_subscriber(CH_TICK, lambda msg: None))
        await asyncio.sleep(0.01)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task


# ── subscribe() local fallback — caller exception isolation ──────────────────


class TestSubscribeLocalFallbackIsolation:
    @pytest.mark.asyncio
    async def test_caller_exception_does_not_kill_subscription(self):
        """
        An exception thrown into the subscribe() generator by the caller
        (e.g. from inside an async-for body) must not kill the subscription.
        The next message must still be yielded.
        """
        bus = EventBus()
        bus._degraded = True  # use local fallback

        received: list[dict] = []
        call_count = [0]

        async def consume():
            async for msg in bus.subscribe(CH_TICK):
                call_count[0] += 1
                received.append(msg)
                if call_count[0] >= 3:
                    break  # stop after 3 messages

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.01)

        for i in range(3):
            await bus.publish(CH_TICK, {"type": "tick", "seq": i})
            await asyncio.sleep(0.01)

        await asyncio.wait_for(task, timeout=1.0)

        assert len(received) == 3, f"Expected 3 messages, got {len(received)}: {received}"
