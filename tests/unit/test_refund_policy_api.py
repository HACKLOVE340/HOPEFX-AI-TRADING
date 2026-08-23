# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
The superadmin endpoints that read and set the refund policy.

This setting decides where money goes when a settled sale is refunded, so the
write path has to do three things beyond storing a string: reject anything that
is not one of the three policies, record who changed it in the tamper-evident
audit chain, and refuse the change outright if the store could not persist it —
reporting success for a setting that did not save is the defect shape this audit
keeps finding (F219).
"""

from __future__ import annotations

import pytest

from monetization.refund_policy import DEFAULT_REFUND_POLICY, REFUND_POLICY_KEY, RefundPolicy

pytestmark = pytest.mark.unit


class RecordingStore:
    def __init__(self, value=None, set_ok=True):
        self._value = value
        self._set_ok = set_ok
        self.sets: list[tuple] = []

    def get(self, key, default=None):
        return self._value if self._value is not None else default

    def set(self, key, value, changed_by="system"):
        self.sets.append((key, value, changed_by))
        if self._set_ok:
            self._value = value
        return self._set_ok


@pytest.fixture
def api(monkeypatch):
    import api.superadmin.financial as fin

    store = RecordingStore()
    audit: list[tuple] = []
    monkeypatch.setattr(fin, "_get_config_store", lambda: store, raising=False)
    monkeypatch.setattr(fin, "_log_superadmin_action", lambda u, a, d="": audit.append((a, d)))
    return fin, store, audit


class FakeUser:
    sub = "superadmin-1"


@pytest.mark.asyncio
async def test_get_returns_the_current_policy_and_all_the_options(api):
    fin, store, _audit = api
    result = await fin.get_refund_policy(user=FakeUser())

    assert result["policy"] == DEFAULT_REFUND_POLICY.value
    assert {o["value"] for o in result["options"]} == {p.value for p in RefundPolicy}
    # Every option must explain what it does to money — this is the UI's only
    # source for that wording.
    assert all(o["description"].strip() for o in result["options"])


@pytest.mark.asyncio
async def test_setting_a_valid_policy_persists_it_and_is_audited(api):
    fin, store, audit = api

    result = await fin.set_refund_policy(
        body={"policy": RefundPolicy.PLATFORM_ABSORBS.value},
        user=FakeUser(),
    )

    assert result["policy"] == RefundPolicy.PLATFORM_ABSORBS.value
    assert store.sets == [(REFUND_POLICY_KEY, RefundPolicy.PLATFORM_ABSORBS.value, "superadmin-1")]
    assert audit, "changing where money goes was not written to the audit chain"
    action, detail = audit[0]
    assert "refund_policy" in action
    assert RefundPolicy.PLATFORM_ABSORBS.value in detail


@pytest.mark.asyncio
async def test_an_unknown_policy_is_rejected_not_stored(api):
    from fastapi import HTTPException

    fin, store, audit = api

    with pytest.raises(HTTPException) as exc:
        await fin.set_refund_policy(body={"policy": "refund_everything"}, user=FakeUser())

    assert exc.value.status_code == 422
    assert store.sets == [], "an unrecognised policy reached the store"
    assert audit == [], "a rejected change was written to the audit chain"


@pytest.mark.asyncio
async def test_a_failed_write_is_not_reported_as_success(api):
    from fastapi import HTTPException

    fin, _store, audit = api
    store = RecordingStore(set_ok=False)
    fin._get_config_store = lambda: store

    with pytest.raises(HTTPException) as exc:
        await fin.set_refund_policy(body={"policy": RefundPolicy.ALLOW_NEGATIVE_BALANCE.value}, user=FakeUser())

    assert exc.value.status_code == 503
    assert audit == [], "an unsaved change was recorded as having happened"


@pytest.mark.asyncio
async def test_no_config_store_is_refused_rather_than_silently_defaulted(api):
    from fastapi import HTTPException

    fin, _store, _audit = api
    fin._get_config_store = lambda: None

    with pytest.raises(HTTPException) as exc:
        await fin.set_refund_policy(body={"policy": RefundPolicy.PLATFORM_ABSORBS.value}, user=FakeUser())
    assert exc.value.status_code == 503
