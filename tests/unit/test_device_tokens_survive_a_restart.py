# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""A registered device must still be registered after a deploy.

F220, and it is what makes the F219 fix incomplete. F219 stopped
`send_notification` reporting success when it had reached no device — the send
is honest now. F220 is why it has nobody to reach: `_device_tokens` is a
module-level dict.

    _device_tokens: dict[str, list[str]] = {}

Two consequences, both live behind `api/mobile.py`:

* **Every deploy silently unregisters every device.** A correctly configured
  FCM — real credentials, real tokens, a working send path — stops delivering,
  and nothing reports an error, because from the server's point of view the
  user simply has no devices.
* **Each worker holds a different set.** Registering through one gunicorn
  worker and sending from another finds nothing, so delivery is intermittent in
  a way that looks like a flaky client.

And `register_device` returns `True` unconditionally, so `POST /register-push`
answers `{"registered": true}` for a registration it knows will not outlive the
process. That is the F219 shape one level up: a success reported for work that
did not durably happen.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

USER = "user-42"
TOKEN = "fcm-token-abcdef"  # pragma: allowlist secret


@pytest.fixture
def fake_redis():
    import fakeredis

    return fakeredis.FakeStrictRedis(decode_responses=True)


@pytest.fixture(autouse=True)
def _clean_module_state():
    """Each test starts with no tokens and no resolved client."""
    import mobile.push_notifications as pn

    pn._device_tokens.clear()
    if hasattr(pn, "_reset_token_store_for_tests"):
        pn._reset_token_store_for_tests()
    yield
    pn._device_tokens.clear()
    if hasattr(pn, "_reset_token_store_for_tests"):
        pn._reset_token_store_for_tests()


def _manager(monkeypatch, redis_client=None):
    """A manager whose token store is backed by *redis_client*, or by nothing."""
    import mobile.push_notifications as pn

    monkeypatch.setattr(pn, "_resolve_token_store", lambda: redis_client, raising=False)
    if hasattr(pn, "_reset_token_store_for_tests"):
        pn._reset_token_store_for_tests()
    return pn.PushNotificationManager()


def test_a_registration_survives_a_restart(monkeypatch, fake_redis):
    """The whole finding, in one assertion.

    A second manager stands in for the process that comes up after a deploy —
    same shared store, no shared memory.
    """
    before = _manager(monkeypatch, fake_redis)
    before.register_device(USER, TOKEN)
    assert before.get_tokens(USER) == [TOKEN]

    import mobile.push_notifications as pn

    pn._device_tokens.clear()  # the restart: process memory is gone
    after = _manager(monkeypatch, fake_redis)

    assert after.get_tokens(USER) == [TOKEN], (
        "the device was unregistered by a restart — a correctly configured FCM stops "
        "delivering after a deploy, with no error anywhere"
    )


def test_a_token_registered_on_one_worker_is_visible_to_another(monkeypatch, fake_redis):
    """Registration and delivery routinely happen in different processes."""
    import mobile.push_notifications as pn

    worker_a = _manager(monkeypatch, fake_redis)
    worker_a.register_device(USER, TOKEN)

    # Separate processes do not share module state. Without clearing it, both
    # "workers" read the same in-process dict and this passes whether or not a
    # shared store exists — which is no test at all.
    pn._device_tokens.clear()
    worker_b = _manager(monkeypatch, fake_redis)

    assert worker_b.get_tokens(USER) == [TOKEN]


def test_unregistering_on_one_worker_removes_it_everywhere(monkeypatch, fake_redis):
    """Otherwise a revoked device keeps receiving until every worker recycles."""
    import mobile.push_notifications as pn

    worker_a = _manager(monkeypatch, fake_redis)
    worker_a.register_device(USER, TOKEN)

    pn._device_tokens.clear()  # worker B is a different process
    worker_b = _manager(monkeypatch, fake_redis)
    assert worker_b.get_tokens(USER) == [TOKEN], "setup: B should see A's registration"

    worker_a.unregister_device(USER, TOKEN)

    assert worker_b.get_tokens(USER) == []


def test_registering_the_same_token_twice_does_not_duplicate_it(monkeypatch, fake_redis):
    """A client that retries must not receive every notification twice."""
    m = _manager(monkeypatch, fake_redis)

    m.register_device(USER, TOKEN)
    m.register_device(USER, TOKEN)

    assert m.get_tokens(USER) == [TOKEN]


def test_registration_reports_whether_it_will_survive(monkeypatch, fake_redis):
    """`register_device` must not claim success for a registration it will lose.

    With a store, durable. Without one, the token is still accepted — refusing
    to register a device because Redis is down would turn a delivery gap into an
    outage — but the caller is told, rather than being handed an unqualified
    True.
    """
    assert _manager(monkeypatch, fake_redis).register_device(USER, TOKEN) is True
    assert _manager(monkeypatch, None).register_device(USER, TOKEN) is False


def test_without_a_store_tokens_still_work_within_the_process(monkeypatch):
    """The fallback must degrade, not break. Dev and test have no Redis."""
    m = _manager(monkeypatch, None)

    m.register_device(USER, TOKEN)

    assert m.get_tokens(USER) == [TOKEN]


def test_a_failing_store_does_not_lose_the_registration(monkeypatch):
    """A store that raises must fall back, loudly, not drop the device.

    The alternative is an exception out of an HTTP handler for something the
    in-process path can still serve.
    """
    from unittest.mock import MagicMock

    broken = MagicMock()
    broken.sadd.side_effect = RuntimeError("redis is down")
    broken.smembers.side_effect = RuntimeError("redis is down")

    m = _manager(monkeypatch, broken)

    assert m.register_device(USER, TOKEN) is False
    assert m.get_tokens(USER) == [TOKEN]


def test_the_endpoint_tells_the_client_whether_the_registration_is_durable(monkeypatch, fake_redis):
    """`{"registered": true}` was returned even when it would not survive."""
    import api.mobile as mobile_api
    import mobile.push_notifications as pn

    monkeypatch.setattr(pn, "_resolve_token_store", lambda: fake_redis, raising=False)
    pn._reset_token_store_for_tests()

    body = mobile_api.RegisterPushBody(fcm_token=TOKEN, platform="ios")

    class _User:
        sub = USER

    import asyncio

    result = asyncio.run(mobile_api.register_push(body, _User()))

    assert result["registered"] is True
    assert result["durable"] is True, result


# ── Broadcast ─────────────────────────────────────────────────────────────────


def test_a_broadcast_reaches_users_this_process_never_registered(monkeypatch, fake_redis):
    """`broadcast_signal` says "all registered users" and enumerated a local dict.

    Fixing per-user lookup without this leaves the defect one level up: after a
    deploy the dict is empty, so a broadcast reaches nobody, returns
    `notified: 0`, and reports that as a successful send. Persisting the tokens
    while still enumerating process memory would have hidden the problem rather
    than fixed it — the per-user endpoints would look correct and the broadcast
    would stay silently empty.
    """
    import mobile.push_notifications as pn

    registrar = _manager(monkeypatch, fake_redis)
    registrar.register_device("user-a", "token-a")  # pragma: allowlist secret
    registrar.register_device("user-b", "token-b")  # pragma: allowlist secret

    pn._device_tokens.clear()  # the deploy
    after = _manager(monkeypatch, fake_redis)

    assert sorted(after.registered_users()) == ["user-a", "user-b"], (
        "a broadcast after a restart would reach nobody and call it a success"
    )


def test_registered_users_falls_back_to_process_memory(monkeypatch):
    """With no shared store, the local view is all there is — and is still served."""
    m = _manager(monkeypatch, None)
    m.register_device("user-a", "token-a")  # pragma: allowlist secret

    assert m.registered_users() == ["user-a"]


def test_registered_users_survives_a_failing_store(monkeypatch):
    """A store that raises mid-scan must degrade to the local view, not except."""
    from unittest.mock import MagicMock

    broken = MagicMock()
    broken.sadd.side_effect = RuntimeError("down")
    broken.scan_iter.side_effect = RuntimeError("down")

    m = _manager(monkeypatch, broken)
    m.register_device("user-a", "token-a")  # pragma: allowlist secret

    assert m.registered_users() == ["user-a"]
