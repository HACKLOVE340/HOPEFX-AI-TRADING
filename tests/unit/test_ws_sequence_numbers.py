# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_ws_sequence_numbers.py
======================================
Round 3 audit, Slice 8 (docs/HARDENING_BACKLOG.md S8-03).

There was no sequence number anywhere in `api/ws_live.py`, so a client that
dropped and reconnected could not tell whether it had missed anything.

For `prices` that is tolerable — the next tick supersedes. For **state**
channels it is not: `positions`, `account` and `risk` are delivered as deltas,
so a missed `positions` message leaves the UI showing a position that has since
closed, or omitting one that opened, *indefinitely*, until some later update
happens to correct it. Combined with S8-01 (drops were silent) and S7-03
(server-side state could itself be wrong after a restart), no layer in the
stack reconciled what the UI showed against what the broker held.

The sequence is **per channel**, not per connection, so the payload is still
serialised once per broadcast rather than once per client — the O(1) fan-out
that S8-01 depends on. A client tracks the last seq it saw on each channel; a
jump means it missed something and should resynchronise.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest


def _manager():
    from api.ws_live import LiveConnectionManager

    return LiveConnectionManager()


def _attach(mgr, cid: str, channels: set[str], user_id: str | None = None):
    ws = MagicMock()
    ws.send_text = AsyncMock()
    mgr._connections[cid] = ws
    mgr._subscriptions[cid] = set(channels)
    if user_id is not None:
        mgr._user_ids[cid] = user_id
    return ws


def _sent(ws) -> list[dict]:
    return [json.loads(c.args[0]) for c in ws.send_text.await_args_list]


@pytest.mark.asyncio
async def test_broadcast_stamps_a_sequence_number():
    mgr = _manager()
    ws = _attach(mgr, "c1", {"positions"})

    await mgr.broadcast("positions", {"type": "positions", "data": {}})

    msgs = _sent(ws)
    assert msgs, "nothing was sent"
    assert "seq" in msgs[0], (
        "broadcast messages carry no sequence number, so a client cannot detect "
        "that it missed a positions update (S8-03)"
    )


@pytest.mark.asyncio
async def test_sequence_increases_monotonically_within_a_channel():
    mgr = _manager()
    ws = _attach(mgr, "c1", {"positions"})

    for _ in range(4):
        await mgr.broadcast("positions", {"type": "positions", "data": {}})

    seqs = [m["seq"] for m in _sent(ws)]
    assert seqs == sorted(seqs), f"sequence went backwards: {seqs}"
    assert len(set(seqs)) == len(seqs), f"sequence repeated: {seqs}"
    assert seqs[-1] - seqs[0] == len(seqs) - 1, f"sequence is not contiguous for a client that missed nothing: {seqs}"


@pytest.mark.asyncio
async def test_channels_are_sequenced_independently():
    """A quiet channel must not inherit a noisy one's gaps."""
    mgr = _manager()
    ws = _attach(mgr, "c1", {"prices", "positions"})

    # Interleaved on purpose: with a single shared counter the positions seqs
    # would come out 2 and 4, and the client would infer a gap that never
    # happened. Consecutive broadcasts per channel would hide that.
    await mgr.broadcast("prices", {"type": "tick"})
    await mgr.broadcast("positions", {"type": "positions"})
    await mgr.broadcast("prices", {"type": "tick"})
    await mgr.broadcast("positions", {"type": "positions"})

    msgs = _sent(ws)
    pos = [m["seq"] for m in msgs if m["type"] == "positions"]
    prices = [m["seq"] for m in msgs if m["type"] == "tick"]
    assert pos[1] - pos[0] == 1, f"positions sequence jumped because prices traffic shared the counter: {pos}"
    assert prices[1] - prices[0] == 1, f"prices sequence is not contiguous: {prices}"


@pytest.mark.asyncio
async def test_the_channel_is_named_on_the_message():
    """A seq is only actionable if the client knows which counter it belongs to."""
    mgr = _manager()
    ws = _attach(mgr, "c1", {"positions"})

    await mgr.broadcast("positions", {"type": "positions", "data": {}})

    assert _sent(ws)[0].get("channel") == "positions"


@pytest.mark.asyncio
async def test_send_to_user_is_sequenced_too():
    """The private path carries the state channels that most need gap detection."""
    mgr = _manager()
    ws = _attach(mgr, "c1", {"account"}, user_id="u1")

    await mgr.send_to_user("u1", "account", {"type": "account", "data": {}})
    await mgr.send_to_user("u1", "account", {"type": "account", "data": {}})

    seqs = [m["seq"] for m in _sent(ws)]
    assert len(seqs) == 2
    assert seqs[1] - seqs[0] == 1, f"send_to_user sequence is not contiguous: {seqs}"


@pytest.mark.asyncio
async def test_caller_supplied_fields_are_not_clobbered():
    mgr = _manager()
    ws = _attach(mgr, "c1", {"positions"})

    await mgr.broadcast("positions", {"type": "positions", "data": {"symbol": "XAUUSD"}})

    msg = _sent(ws)[0]
    assert msg["type"] == "positions"
    assert msg["data"] == {"symbol": "XAUUSD"}


@pytest.mark.asyncio
async def test_stamping_does_not_mutate_the_caller_s_dict():
    """Broadcasters reuse dicts; stamping must not leak a stale seq into one."""
    mgr = _manager()
    _attach(mgr, "c1", {"positions"})

    payload = {"type": "positions", "data": {}}
    await mgr.broadcast("positions", payload)

    assert "seq" not in payload, "broadcast mutated the caller's message dict"


@pytest.mark.asyncio
async def test_one_serialisation_per_broadcast_regardless_of_client_count():
    """Per-channel (not per-connection) sequencing keeps the fan-out O(1).

    S8-01's fix depends on serialising once before the loop; a per-connection
    sequence would force a re-serialise per client and reintroduce the cost.
    """
    mgr = _manager()
    sockets = [_attach(mgr, f"c{i}", {"positions"}) for i in range(5)]

    await mgr.broadcast("positions", {"type": "positions", "data": {}})

    payloads = {ws.send_text.await_args.args[0] for ws in sockets}
    assert len(payloads) == 1, (
        "clients received different payload strings — the message is being "
        "serialised per connection, undoing the S8-01 fan-out optimisation"
    )
