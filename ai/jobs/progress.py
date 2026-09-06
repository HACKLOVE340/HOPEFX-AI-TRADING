# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Push each job's state to the operator watching it.

The workbench polls every 900ms while anything is live. That works — and it puts
a floor under how fast a panel can react, and a load under a page nobody is
looking at. Pushing each state change over the WebSocket that already carries
prices removes both, and polling stays as the fallback rather than the mechanism.

## The security property

A job frame carries the operator's prompt and the model's answer. `ws_live`
delivers a channel to a connection with an EMPTY subscription unless that
channel is listed private — which is exactly the S8-02 defect, where
`send_to_user` had the right user and the wrong channel and private account
data reached a connection subscribed only to `prices`.

So `ai_jobs` is in `_PRIVATE_CHANNELS`, and every frame goes through
`send_to_user` addressed to the operator who submitted the job. One operator's
prompt must never appear on another's screen.

## The thread hop

Jobs run on the AI pool; `send_to_user` is a coroutine on the event loop. The
bridge is `run_coroutine_threadsafe` against the loop captured at install time —
explicit rather than incidental, because a worker thread calling into a loop it
does not own is where this kind of code usually goes wrong.

**A publish failure never fails the job.** A browser that went away, a closed
socket, a full send buffer: none of those are the work's problem. Logged at
WARNING rather than ERROR — unlike the audit trail, a missed progress frame
costs an operator a second of staleness, not a record of what happened.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

#: The channel name. Must also be in `ws_live.ConnectionManager._PRIVATE_CHANNELS`
#: or an empty-subscription connection receives it, which is the whole risk.
CHANNEL = "ai_jobs"

_SEND: Callable[..., Any] | None = None
_LOOP: asyncio.AbstractEventLoop | None = None


def install(*, send_to_user: Callable[..., Any], loop: asyncio.AbstractEventLoop) -> None:
    """Wire the publisher to a live WebSocket manager and its loop."""
    global _SEND, _LOOP
    _SEND, _LOOP = send_to_user, loop


def installed() -> bool:
    """Whether progress is being pushed. Read by the health surface."""
    return _SEND is not None and _LOOP is not None


def publish(job: Any) -> None:
    """Send one job's current state to its operator. Never raises.

    Shaped as an `on_change` listener so `JobRunner` calls it directly — the
    runner knows nothing about WebSockets, and this knows nothing about pools.
    """
    send, loop = _SEND, _LOOP
    if send is None or loop is None:
        # A dev box with no WebSocket, or a test. Polling still works; there is
        # nothing wrong and nothing to say about it on every state change.
        return

    try:
        payload = job.as_dict() if hasattr(job, "as_dict") else dict(job)
        # `ws_live` stamps the channel; the browser routes on `type`, and every
        # other handler in `useWebSocket` reads the body from `data`. A frame
        # without a `type` falls through the client's switch and is dropped —
        # a push channel that pushes into nothing — and a flat body would put
        # the job's own keys in the same namespace as `type`/`channel`/`seq`.
        frame = {"type": "ai_job_update", "data": payload}
        operator = getattr(job, "operator", "") or ""
    except Exception:
        logger.warning("ai.jobs.progress: could not render a job frame", exc_info=True)
        return

    if not operator:
        # No operator means no addressee. Broadcasting instead would put a
        # prompt on every connected screen, so this drops the frame.
        logger.warning("ai.jobs.progress: job %s has no operator; not published", payload.get("id"))
        return

    try:
        asyncio.run_coroutine_threadsafe(send(operator, CHANNEL, frame), loop)
    except Exception:
        # A closed socket, a stopped loop, a full buffer. The work is unaffected
        # and the panel falls back to its poll, so this is a warning rather than
        # an error — the job's own record is the audit trail, not this.
        logger.warning("ai.jobs.progress: could not publish job %s", payload.get("id"), exc_info=True)


def reset_for_testing() -> None:
    global _SEND, _LOOP
    _SEND = _LOOP = None


__all__ = ["CHANNEL", "install", "installed", "publish", "reset_for_testing"]
