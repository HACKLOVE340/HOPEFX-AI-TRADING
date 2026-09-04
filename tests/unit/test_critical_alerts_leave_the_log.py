# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
A critical alert must reach a channel, or say that it did not.

`AlertEngine.send_alert` logs the alert and then tries to hand it to "the
notifications singleton" so it also reaches Telegram / Discord / webhook:

    from notifications import get_alert_engine as _get_singleton
    singleton = _get_singleton()
    if singleton is not None and singleton is not self and ...:

But `notifications/__init__.py` re-exports `get_alert_engine` **from
`notifications.alert_engine`** — it is the same function, returning the same
`AlertEngine` singleton. Every caller reaches that singleton, so `singleton is
self` and the delegation never runs. The guard and the delivery are the same
branch (F159). Emergency stops, drawdown breaches, circuit-breaker trips and
position drift have only ever been log lines.

Three more of the same shape travel with it:

* `notifications.send_alert()` — the module-level "Global alert function" — only
  calls `logger.log`. `execution/sl_tp_monitor.py` uses it for "CLOSE FAILURE —
  MANUAL INTERVENTION REQUIRED" (F247).
* `core/position_reconciler.py`, `ml/performance_monitor.py` and
  `ml/sharpe_circuit_breaker.py` call `send_alert(title=..., severity=...)`.
  Those are not parameters of `send_alert`; the call raises TypeError into a
  surrounding `except Exception` and is logged at warning — or debug (F248).
  The unit tests covering them pass a bare `MagicMock`, which accepts any
  signature, so they were green against a call the real object rejects.
* `api/superadmin/alerting.py` reports `sent_channels` from the rule's *config*
  after a send that reached nothing — success for work that did not happen.

These tests pin the delivery, not the logging.
"""

from __future__ import annotations

import inspect

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def captured(monkeypatch):
    """Replace the notifications singleton's manager with a recorder."""
    import notifications as nf

    sent: list = []

    class _Recorder:
        channels = {"telegram": True}

        async def start(self):
            return None

        async def stop(self):
            return None

        async def send(self, notification):
            sent.append(notification)

    monkeypatch.setattr(nf.notifications, "_manager", _Recorder())
    monkeypatch.setattr(nf.notifications, "_started", False)
    return sent


# ── F159: the delegation guard ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_critical_alert_reaches_a_channel(captured):
    from notifications.alert_engine import get_alert_engine

    await get_alert_engine().send_alert("critical", "EMERGENCY STOP", {"reason": "drawdown"})

    assert captured, "the alert never left the log — nothing was handed to a notification channel"
    assert "EMERGENCY STOP" in captured[0].message


@pytest.mark.asyncio
async def test_the_process_singleton_is_not_its_own_delegation_target(captured):
    """The guard compared the AlertEngine against a function that returns that
    same AlertEngine. The delivery path must not be reachable only by objects
    nobody constructs."""
    from notifications.alert_engine import AlertEngine, get_alert_engine

    singleton = get_alert_engine()
    await singleton.send_alert("critical", "from the singleton")
    await AlertEngine().send_alert("critical", "from a fresh instance")

    messages = [n.message for n in captured]
    assert "from the singleton" in messages, "the process-wide engine cannot deliver"
    assert "from a fresh instance" in messages


@pytest.mark.asyncio
async def test_send_alert_reports_whether_it_was_delivered(captured):
    from notifications.alert_engine import get_alert_engine

    assert await get_alert_engine().send_alert("critical", "delivered") is True


@pytest.mark.asyncio
async def test_an_undeliverable_critical_alert_says_so(monkeypatch, caplog):
    """No channel configured is a legitimate state. Reporting it as sent is not."""
    import logging

    import notifications as nf

    class _NoChannels:
        channels: dict[str, bool] = {}

        async def start(self):
            return None

        async def send(self, notification):
            raise AssertionError("must not dispatch with no channel configured")

    monkeypatch.setattr(nf.notifications, "_manager", _NoChannels())
    monkeypatch.setattr(nf.notifications, "_started", False)

    from notifications.alert_engine import get_alert_engine

    with caplog.at_level(logging.ERROR):
        delivered = await get_alert_engine().send_alert("critical", "nowhere to go")

    assert delivered is False
    assert any("no notification channel" in r.message.lower() for r in caplog.records), (
        "a critical alert that reached nobody was not reported as undelivered"
    )


@pytest.mark.asyncio
async def test_send_alert_does_not_recurse_into_itself(captured, monkeypatch):
    """The old delegation reached back into `notifications.get_alert_engine()`,
    which returns an AlertEngine — the same class it was called on. Only the
    `is not self` guard stopped an infinite loop, and that guard was also what
    stopped delivery. The target must be a different type entirely."""
    from notifications.alert_engine import AlertEngine, get_alert_engine

    calls: list[str] = []
    original = AlertEngine.send_alert

    async def _counting(self, level, message, data=None):
        calls.append(message)
        assert len(calls) < 5, "AlertEngine.send_alert re-entered itself"
        return await original(self, level, message, data)

    monkeypatch.setattr(AlertEngine, "send_alert", _counting)
    await get_alert_engine().send_alert("critical", "once")

    assert calls == ["once"]


# ── F247: the module-level global alert function ──────────────────────────────


@pytest.mark.asyncio
async def test_the_global_send_alert_helper_dispatches(captured):
    """execution/sl_tp_monitor.py raises 'CLOSE FAILURE — MANUAL INTERVENTION
    REQUIRED' through this function."""
    from notifications import send_alert

    await send_alert("critical", "CLOSE FAILURE — MANUAL INTERVENTION REQUIRED")

    assert captured, "notifications.send_alert() only wrote a log line"


# ── F248: call sites that cannot succeed ──────────────────────────────────────


@pytest.mark.parametrize(
    "module_path",
    ["core.position_reconciler", "ml.performance_monitor", "ml.sharpe_circuit_breaker"],
)
def test_no_caller_passes_kwargs_send_alert_does_not_accept(module_path):
    """A TypeError swallowed by `except Exception` is indistinguishable from a
    delivered alert at the call site, so check the calls themselves.

    Parsed with `ast`, not a regex: a regex over the source matches the method
    name inside docstrings and comments too, and a lazy `.*?` then runs past the
    real argument list into the next one.
    """
    import ast
    import importlib
    from pathlib import Path

    from notifications.alert_engine import AlertEngine

    valid = set(inspect.signature(AlertEngine.send_alert).parameters) - {"self"}
    tree = ast.parse(Path(importlib.import_module(module_path).__file__).read_text())

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
        if name != "send_alert":
            continue
        for kw in node.keywords:
            assert kw.arg in valid, (
                f"{module_path}:{node.lineno} calls send_alert({kw.arg}=...), which AlertEngine.send_alert rejects"
            )
        assert len(node.args) + len(node.keywords) >= 2, (
            f"{module_path}:{node.lineno} calls send_alert with too few arguments"
        )


# ── F249: a channel that is advertised and never dispatched ───────────────────


def test_no_channel_is_advertised_that_dispatch_cannot_send():
    """`channels['email']` was set from an smtp_host the singleton never passes,
    and `_dispatch` has no email branch — an operator reading `channels` was
    told email alerts were on."""
    import inspect as _inspect

    from notifications import NotificationManager

    dispatch_src = _inspect.getsource(NotificationManager._dispatch)
    mgr = NotificationManager({"smtp_host": "smtp.example.com"})
    for channel, enabled in mgr.channels.items():
        if enabled:
            assert channel in dispatch_src, f"channels['{channel}'] is advertised but _dispatch never sends it"


# ── Defects introduced by the F159 fix itself, caught before they shipped ─────


def test_the_notification_manager_is_actually_constructible():
    """Adding `has_channel()` mid-`__init__` left `self.queue` and
    `self._running` stranded after a `return`, so every manager was built
    without them. Ruff does not flag unreachable code, and no test exercised the
    queue — the alert tests substitute the manager wholesale.

    So: assert the real object, not a stand-in."""
    from notifications import NotificationManager

    mgr = NotificationManager({"discord_webhook": "https://discord.com/api/webhooks/x"})
    assert mgr.queue is not None, "NotificationManager was built without its queue"
    assert mgr._running is False
    assert mgr.has_channel() is True


def test_an_alert_from_synchronous_code_is_delivered_not_queued_into_a_dying_loop(monkeypatch):
    """`send_alert_nowait` with no running loop drives the dispatch with
    `asyncio.run`, whose loop closes the moment it returns. A *queued*
    notification is drained by a background task on that loop — so the alert was
    discarded with the loop while the caller was told True.

    This is the path `execution/sl_tp_monitor.py` uses for "CLOSE FAILURE —
    MANUAL INTERVENTION REQUIRED"."""
    import notifications as nf

    delivered: list[str] = []

    class _Manager(nf.NotificationManager):
        async def _dispatch(self, notification):
            delivered.append(notification.message)

    monkeypatch.setattr(
        nf.notifications, "_manager", _Manager({"discord_webhook": "https://discord.com/api/webhooks/x"})
    )
    monkeypatch.setattr(nf.notifications, "_started", False)
    monkeypatch.setattr(nf.notifications, "_loop", None)

    assert nf.send_alert_nowait("critical", "CLOSE FAILURE") is True
    assert delivered == ["CLOSE FAILURE"], "the alert was queued into a loop that had already closed"


def test_a_second_sync_alert_still_arrives(monkeypatch):
    """The loop-affinity guard: `_started` stayed True after the first
    `asyncio.run` loop closed, so every later send queued into a dead queue."""
    import notifications as nf

    delivered: list[str] = []

    class _Manager(nf.NotificationManager):
        async def _dispatch(self, notification):
            delivered.append(notification.message)

    monkeypatch.setattr(
        nf.notifications, "_manager", _Manager({"discord_webhook": "https://discord.com/api/webhooks/x"})
    )
    monkeypatch.setattr(nf.notifications, "_started", False)
    monkeypatch.setattr(nf.notifications, "_loop", None)

    nf.send_alert_nowait("critical", "first")
    nf.send_alert_nowait("critical", "second")
    assert delivered == ["first", "second"]
