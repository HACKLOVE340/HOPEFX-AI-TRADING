"""Regression tests: one slow WebSocket client must not stall the others.

Round 3 audit findings S8-01 and S8-02 (docs/HARDENING_BACKLOG.md).

S8-01 — ``LiveConnectionManager.broadcast`` fanned out **sequentially**,
awaiting each socket in turn, with no per-client queue, no bounded buffer and
no send timeout. Every ``asyncio.wait_for`` in the 2,249-line module wrapped a
``receive_text``; not one wrapped a send.

A laptop that sleeps with the dashboard open freezes its TCP window. The
socket is not reset, so ``send_text`` **blocks** once the kernel buffer fills
rather than raising. The tick broadcaster is a single coroutine consuming
``bus.subscribe(CH_TICK)`` and calling ``broadcast()`` per tick, so it was then
blocked inside that one client's send: **every other trader stopped receiving
prices**. The 30-second stale-feed watchdog could not fire either, because its
deadline is only refreshed at the top of a loop that was no longer iterating.

For a trading UI a frozen price is not cosmetic — it is the input a human uses
to decide whether to intervene (see S9-01, where the client cannot detect this
either).

S8-02 — ``send_to_user`` kept the "empty subscription = all channels" fallback
without the ``_PRIVATE_CHANNELS`` guard that ``broadcast`` has, so private
account and risk messages reached connections that never subscribed. Right
user, wrong channel: the Round 2 fix was not carried to the sibling method.
"""

import asyncio

import pytest


class _SlowSocket:
    """A socket whose send never completes — a frozen TCP window."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_text(self, payload: str) -> None:
        await asyncio.Event().wait()  # blocks forever


class _FastSocket:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_text(self, payload: str) -> None:
        self.sent.append(payload)


def _manager():
    from api.ws_live import LiveConnectionManager

    return LiveConnectionManager()


def _attach(mgr, cid: str, sock, channels=None, user_id=None):
    mgr._connections[cid] = sock
    mgr._subscriptions[cid] = set(channels or [])
    mgr._user_ids[cid] = user_id
    mgr._hb_misses[cid] = 0


@pytest.mark.unit
class TestBroadcastDoesNotHeadOfLineBlock:
    @pytest.mark.asyncio
    async def test_slow_client_does_not_stall_the_others(self):
        """The whole point: a frozen socket must not hold the fan-out (S8-01)."""
        mgr = _manager()
        slow, fast = _SlowSocket(), _FastSocket()
        _attach(mgr, "slow", slow, ["prices"])
        _attach(mgr, "fast", fast, ["prices"])

        await asyncio.wait_for(
            mgr.broadcast("prices", {"type": "price_tick", "data": {"mid": 3300.0}}),
            timeout=5.0,
        )

        assert fast.sent, (
            "The fast client received nothing — broadcast is still blocked behind the slow socket's send (S8-01)."
        )

    @pytest.mark.asyncio
    async def test_broadcast_returns_promptly_with_many_slow_clients(self):
        """Fan-out latency must not scale with the slowest consumer."""
        mgr = _manager()
        for i in range(5):
            _attach(mgr, f"slow{i}", _SlowSocket(), ["prices"])
        fast = _FastSocket()
        _attach(mgr, "fast", fast, ["prices"])

        loop = asyncio.get_running_loop()
        t0 = loop.time()
        await asyncio.wait_for(mgr.broadcast("prices", {"type": "price_tick"}), timeout=5.0)
        elapsed = loop.time() - t0

        assert elapsed < 3.0, f"broadcast took {elapsed:.1f}s with 5 stalled clients"
        assert fast.sent

    @pytest.mark.asyncio
    async def test_send_is_bounded_by_a_timeout(self):
        """A single send must not be able to block indefinitely."""
        mgr = _manager()
        slow = _SlowSocket()
        _attach(mgr, "slow", slow, ["prices"])

        await asyncio.wait_for(mgr.send("slow", {"type": "ping"}), timeout=5.0)


@pytest.mark.unit
class TestPrivateChannelsRequireSubscription:
    @pytest.mark.asyncio
    async def test_send_to_user_does_not_firehose_private_channels(self):
        """A connection that never subscribed must not receive private data (S8-02)."""
        mgr = _manager()
        sock = _FastSocket()
        # Empty subscription set — mid-handshake, or subscribed to prices only.
        _attach(mgr, "c1", sock, [], user_id="u1")

        await mgr.send_to_user("u1", "account", {"type": "account_update", "data": {}})

        assert not sock.sent, (
            "A private 'account' message was delivered to a connection with no "
            "explicit subscription — broadcast() guards this, send_to_user() "
            "did not (S8-02)."
        )

    @pytest.mark.asyncio
    async def test_send_to_user_delivers_when_subscribed(self):
        """Control case: an explicit subscription must still receive it."""
        mgr = _manager()
        sock = _FastSocket()
        _attach(mgr, "c1", sock, ["account"], user_id="u1")

        await mgr.send_to_user("u1", "account", {"type": "account_update", "data": {}})

        assert sock.sent, "an explicitly subscribed connection must receive its channel"

    @pytest.mark.asyncio
    async def test_public_channel_still_uses_the_implicit_fallback(self):
        """Non-private channels keep the pre-subscribe convenience path."""
        mgr = _manager()
        sock = _FastSocket()
        _attach(mgr, "c1", sock, [], user_id="u1")

        await mgr.send_to_user("u1", "prices", {"type": "price_tick"})

        assert sock.sent
