# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""A typed publish/subscribe bus for messages between agents. §12.

Until this, an agent handed work to another agent by calling it. That is a
call graph, not a message protocol: the caller has to know who implements the
work, the callee cannot be replaced without editing the caller, and nothing
records that the handoff happened.

## What this deliberately is not

**Not an execution path.** `publish()` moves an `AgentMessage`. It cannot run
a tool, and this module does not import the thing that can — see the package
docstring. A subscriber is handed one frozen dataclass with nothing callable on
it and no operator identity to act as; if it wants to act, it goes to
`ai/tools/bus.py` with its own authority and takes both gates like everybody
else.

**Not a second envelope.** `publish()` accepts `ai.hub.contracts.AgentMessage`
and refuses a dict. A bus that accepts dicts grows a second, untyped envelope
beside the typed one, and then two definitions of what a message is.

## Operator scoping is the first key, not a filter

Every subscription and every publish carries an operator, and delivery happens
only within one. The precedent is a P0 in `ai/jobs/runner.py`, where one
operator's prompt and the model's answer could reach another operator's screen:
the scoping was applied at the read, so anything that forgot to apply it leaked.
Here the scope is the dictionary key, so a lookup that forgets it finds nothing
rather than finding everything.

The operator does **not** travel inside the envelope. `AgentMessage` is §12's
ten fields and an operator is not one of them; more usefully, a subscriber that
never receives an operator identity cannot borrow one.

## The cross-worker leg, stated rather than implied

`API_WORKERS` can be greater than 1, and then an in-process bus reaches one
worker of several. `core/event_bus.py` is the Redis pub/sub transport this
repository already runs — but note its shape: when Redis is healthy,
`publish()` goes to Redis and `subscribe_local` handlers hear nothing, because
local handlers are the *degraded* path. A subscription registered there would
work in every test (no Redis, degraded, delivered locally) and fire never in
production. That is `hopefx-dead-controls` exactly.

So in-process delivery here is direct and guaranteed, Redis fan-out is
additive, and `Delivery.fanout` always says which of the two happened. Silence
about the other workers reads, to a caller, like having reached them.

Receiving another worker's message requires a reader loop; `consume()` is that
loop, and `enable_fanout()` is what a startup factory calls to install it.
Until a factory calls it, `fanout` says so in words.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ai.hub.contracts import AgentMessage

logger = logging.getLogger(__name__)

#: Base Redis channel. The per-operator channel is `f"{CHANNEL}:{operator}"`, so
#: a worker subscribing for one operator is not handed another's traffic by the
#: transport in the first place.
CHANNEL = "hopefx:ai:agent"

#: A subscription to every topic within one operator's scope. Auditors and the
#: workbench want this; it is still bounded by the operator.
WILDCARD = "*"

_FANOUT_NOT_INSTALLED = (
    "in-process only: cross-worker fan-out is not installed, so subscribers in other API workers did not receive this"
)


@dataclass(frozen=True)
class Subscription:
    """A handle. Held so it can be given back to `unsubscribe`."""

    topic: str
    operator: str
    subscriber: str
    callback: Callable[[AgentMessage], Any]


@dataclass(frozen=True)
class Delivery:
    """What actually happened to one published message.

    Every field is a measurement. `rejected` non-empty means nothing was
    delivered and this is the reason; `failed` names subscribers that raised,
    so they are never folded into `delivered` and counted as reached.
    """

    delivered: int = 0
    failed: tuple[str, ...] = ()
    rejected: str = ""
    #: Always populated. The cross-worker leg reports in words, never by omission.
    fanout: str = _FANOUT_NOT_INSTALLED

    @property
    def accepted(self) -> bool:
        return not self.rejected


class AgentBus:
    """In-process publish/subscribe over `AgentMessage`, keyed by operator."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        #: operator -> topic -> subscriptions. Operator first, on purpose.
        self._subs: dict[str, dict[str, list[Subscription]]] = {}
        self._fanout: Callable[[str, dict[str, Any]], None] | None = None
        self._fanout_label = _FANOUT_NOT_INSTALLED

    # -- subscription ----------------------------------------------------------

    def subscribe(
        self,
        topic: str,
        callback: Callable[[AgentMessage], Any],
        *,
        operator: str,
        subscriber: str,
    ) -> Subscription:
        """Register `callback` for `topic` within `operator`'s scope.

        `subscriber` is a name, used when reporting which callback raised. An
        anonymous failing subscriber cannot be found and fixed.
        """
        if not operator or not operator.strip():
            raise ValueError("a subscription needs an operator; an unscoped subscriber receives everybody's messages")
        if not topic or not topic.strip():
            raise ValueError("a subscription needs a topic")
        if not subscriber or not subscriber.strip():
            raise ValueError("a subscription needs a subscriber name, so a raising callback can be named")
        if not callable(callback):
            raise TypeError("callback must be callable")

        sub = Subscription(topic=topic, operator=operator, subscriber=subscriber, callback=callback)
        with self._lock:
            self._subs.setdefault(operator, {}).setdefault(topic, []).append(sub)
        return sub

    def unsubscribe(self, subscription: Subscription) -> bool:
        """Remove a subscription. Returns whether it was registered."""
        with self._lock:
            topics = self._subs.get(subscription.operator, {})
            handlers = topics.get(subscription.topic, [])
            if subscription in handlers:
                handlers.remove(subscription)
                return True
        return False

    def subscriber_count(self, *, operator: str) -> int:
        with self._lock:
            return sum(len(v) for v in self._subs.get(operator, {}).values())

    # -- publishing ------------------------------------------------------------

    def publish(self, message: Any, *, operator: str, topic: str = "") -> Delivery:
        """Deliver `message` to this operator's subscribers on `topic`.

        `topic` defaults to `message.recipient`, so addressing an agent needs no
        naming convention agreed out of band.
        """
        if not isinstance(message, AgentMessage):
            raise TypeError(
                f"publish takes an AgentMessage, got {type(message).__name__}; "
                "a dict here becomes a second, untyped envelope beside the typed one",
            )
        if not operator or not operator.strip():
            raise ValueError("publishing needs an operator; an unscoped message is deliverable to anybody")

        if message.is_expired():
            return Delivery(
                rejected="expired: its evidence has aged out and must not be delivered as current",
                fanout="not attempted: the message was rejected",
            )

        subject = topic or message.recipient
        delivered, failed = self._dispatch(message, operator=operator, topic=subject)
        return Delivery(delivered=delivered, failed=failed, fanout=self._fan_out(operator, message))

    def _dispatch(self, message: AgentMessage, *, operator: str, topic: str) -> tuple[int, tuple[str, ...]]:
        """Call every matching subscriber. One broken one must not stop the rest,
        and must not be counted as reached."""
        with self._lock:
            by_topic = self._subs.get(operator, {})
            targets = list(by_topic.get(topic, ())) + list(by_topic.get(WILDCARD, ()))

        delivered = 0
        failed: list[str] = []
        for sub in targets:
            try:
                sub.callback(message)
            except Exception:
                logger.exception(
                    "agent bus: subscriber %r raised on topic %s; continuing with the others",
                    sub.subscriber,
                    topic,
                )
                failed.append(sub.subscriber)
            else:
                delivered += 1
        return delivered, tuple(failed)

    # -- the cross-worker leg --------------------------------------------------

    def enable_fanout(self, publisher: Callable[[str, dict[str, Any]], None], *, label: str) -> None:
        """Install the cross-worker publisher, and the words `fanout` reports.

        `label` is written by the caller that knows what it installed, because
        this object cannot tell whether the transport it was handed reaches
        anything.
        """
        with self._lock:
            self._fanout = publisher
            self._fanout_label = label

    def disable_fanout(self) -> None:
        with self._lock:
            self._fanout = None
            self._fanout_label = _FANOUT_NOT_INSTALLED

    def _fan_out(self, operator: str, message: AgentMessage) -> str:
        publisher = self._fanout
        if publisher is None:
            return self._fanout_label
        try:
            publisher(f"{CHANNEL}:{operator}", {"type": "agent_message", **message.as_dict()})
        except Exception as exc:
            # A transport failure is never the message's failure: it was
            # delivered in this process, and the report says what the other
            # workers did not get.
            logger.warning("agent bus: cross-worker fan-out failed: %s", exc)
            return f"in-process only: cross-worker fan-out failed ({type(exc).__name__})"
        return self._fanout_label

    def deliver_remote(self, payload: dict[str, Any], *, operator: str) -> Delivery:
        """Deliver a message that arrived from another worker.

        Rebuilt through `AgentMessage.from_dict`, which is already the one
        definition of how a payload becomes a message — a second one here would
        be free to drift from it. A payload that is not a valid message raises at
        this boundary rather than reaching a subscriber half-formed.

        Local delivery only. Re-publishing what was received would send it back
        out, and every worker would rebroadcast every message for ever.
        """
        fields = {k: v for k, v in payload.items() if k not in {"type", "_trace"}}
        message = AgentMessage.from_dict(fields)
        delivered, failed = self._dispatch(message, operator=operator, topic=message.recipient)
        return Delivery(delivered=delivered, failed=failed, fanout="received from another worker")


_BUS: AgentBus | None = None
_BUS_LOCK = threading.Lock()


def get_agent_bus() -> AgentBus:
    """The process-wide bus. One per process, like the tool bus and the cache."""
    global _BUS
    with _BUS_LOCK:
        if _BUS is None:
            _BUS = AgentBus()
        return _BUS


def reset_for_testing() -> None:
    global _BUS
    with _BUS_LOCK:
        _BUS = None


def install_redis_fanout(bus: AgentBus, loop: asyncio.AbstractEventLoop) -> str:
    """Point `bus`'s fan-out at `core.event_bus`, from a startup factory.

    Returns the label it installed, so the caller can log the same words the
    `Delivery` will report — one description of the transport, not two.

    The publish is fire-and-forget onto `loop`: a bus publish happens on a
    worker thread (jobs run on a pool), and blocking it on a Redis round trip
    would put network latency inside an in-process message send.
    """
    from core.event_bus import bus as core_bus

    def _publish(channel: str, payload: dict[str, Any]) -> None:
        asyncio.run_coroutine_threadsafe(core_bus.publish(channel, payload), loop)

    label = (
        "published to core.event_bus for other workers; a worker receives them only where AgentBus.consume is running"
    )
    bus.enable_fanout(_publish, label=label)
    return label


async def consume(bus: AgentBus, operator: str) -> None:
    """Read one operator's channel and deliver into this process. Runs forever.

    Kept explicit rather than started automatically: an unread channel is a
    visible gap, and a subscription that silently never fires is not.
    """
    from core.event_bus import bus as core_bus

    async for payload in core_bus.subscribe(f"{CHANNEL}:{operator}"):
        if not isinstance(payload, dict) or payload.get("type") != "agent_message":
            continue
        try:
            bus.deliver_remote(payload, operator=operator)
        except Exception as exc:
            logger.warning("agent bus: dropped a malformed remote message: %s", exc)
