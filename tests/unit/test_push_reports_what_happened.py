# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
A push notification nobody received is not a success.

``mobile/push_notifications.py:173`` returned ``True`` when FCM was disabled or
the user had no device tokens. All three Firebase variables are blank in
``.env.example``, so that is the default state of a fresh deployment: every push
returned ``True`` and reached no device (F219).

Executed on the running configuration when the finding was written:

    fcm_enabled                 : False
    send_notification() returned: True
    device tokens registry      : {}

The callers cannot tell. ``api/trading.py:780`` ``_send_fill_push`` and
``api/signals.py`` both invoke it and receive ``True``. A trader who enabled fill
notifications gets none and nothing registers a failure.

The two no-send cases are not the same and are logged differently. FCM switched
off is the expected state of a dev box. FCM configured but the user having no
tokens is a real gap — somebody enabled notifications and will not receive any.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def manager(monkeypatch):
    from mobile.push_notifications import PushNotificationManager, _device_tokens

    _device_tokens.clear()
    m = PushNotificationManager()
    m.fcm_enabled = False
    yield m
    _device_tokens.clear()


def test_fcm_disabled_is_not_reported_as_sent(manager):
    manager.fcm_enabled = False
    result = manager.send_notification("u1", "Filled", "XAUUSD 1.0 @ 3300")

    assert not result, "a notification reached no device and reported success"


def test_no_device_tokens_is_not_reported_as_sent(manager):
    manager.fcm_enabled = True  # configured, but this user has no device
    result = manager.send_notification("u1", "Filled", "XAUUSD 1.0 @ 3300")

    assert not result


def test_the_dev_log_line_is_kept(manager, capsys):
    """The [FCM-LOG] print is why the branch existed — dev and test
    environments observe notifications without a real key. Fixing the return
    value must not remove the observability."""
    manager.send_notification("u1", "Filled", "XAUUSD 1.0 @ 3300")

    assert "[FCM-LOG]" in capsys.readouterr().out


def test_a_configured_fcm_with_no_tokens_warns(manager, caplog):
    """Somebody turned notifications on and will receive nothing. That is worth
    a warning; FCM simply being off on a dev box is not."""
    manager.fcm_enabled = True

    with caplog.at_level("WARNING"):
        manager.send_notification("u1", "Filled", "body")

    assert any("token" in r.message.lower() for r in caplog.records)


def test_fcm_switched_off_does_not_warn_on_every_notification(manager, caplog):
    """A dev box would otherwise emit a warning per fill."""
    manager.fcm_enabled = False

    with caplog.at_level("WARNING"):
        for _ in range(5):
            manager.send_notification("u1", "Filled", "body")

    assert not [r for r in caplog.records if r.levelname == "WARNING"]


def test_a_real_send_still_reports_success(manager, monkeypatch):
    """The fix must not make delivery look like failure.

    The manager dispatches to ``_send_admin`` when the Firebase Admin SDK is
    present and ``_send_legacy`` otherwise; both are stubbed here so the test is
    about the return value rather than either transport.
    """
    from mobile import push_notifications as pn

    manager.fcm_enabled = True
    pn._device_tokens["u1"] = ["tok-1"]

    called = {}

    def _ok(tokens, title, body, data):
        called["tokens"] = tokens
        return True

    monkeypatch.setattr(manager, "_send_admin", _ok, raising=False)
    monkeypatch.setattr(manager, "_send_legacy", _ok, raising=False)

    result = manager.send_notification("u1", "Filled", "body")

    assert called.get("tokens") == ["tok-1"], "the send path was not reached"
    assert result


def test_a_failed_delivery_is_reported_as_failed(manager, monkeypatch):
    """The other half: a transport that fails must not report success either."""
    from mobile import push_notifications as pn

    manager.fcm_enabled = True
    pn._device_tokens["u1"] = ["tok-1"]

    monkeypatch.setattr(manager, "_send_admin", lambda *a, **k: False, raising=False)
    monkeypatch.setattr(manager, "_send_legacy", lambda *a, **k: False, raising=False)

    assert not manager.send_notification("u1", "Filled", "body")
