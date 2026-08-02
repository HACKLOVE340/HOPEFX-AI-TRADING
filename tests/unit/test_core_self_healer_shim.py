# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_core_self_healer_shim.py
========================================
`core/self_healer.py` — 21 statements, previously 0% covered.

A compatibility shim that exists solely so `celery_app.self_healer_scan` can
call `get_self_healer().scan()`. Nothing tested the contract it was written to
satisfy, and the whole thing is one broad `except Exception: return
{"actions_taken": []}` — a scan that crashes and a scan that finds nothing
produce byte-identical output, so a broken integrity scanner would show up as a
permanently clean system.

These pin the shape celery depends on, and the watermark behaviour that stops
the same drift event being reported on every scan.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


class _Healer:
    """Stands in for security.self_healer.SelfHealer."""

    def __init__(self, drift_events=None, raises=False):
        self._drift_events = list(drift_events or [])
        self._raises = raises
        self.scans = 0
        self.some_other_attribute = "passed through"

    async def _scan_integrity(self):
        self.scans += 1
        if self._raises:
            raise RuntimeError("integrity scanner exploded")


# ── _scan_wrapper ─────────────────────────────────────────────────────────────


async def test_the_wrapper_reports_drift_events_in_the_shape_celery_expects():
    from core.self_healer import _scan_wrapper

    healer = _Healer(
        drift_events=[
            {"ts": "2026-01-02T00:00:00", "path": "risk/manager.py", "type": "modified"},
            {"ts": "2026-01-02T00:00:01", "path": "kill_switch.py", "type": "deleted"},
        ]
    )

    result = await _scan_wrapper(healer)

    assert healer.scans == 1
    assert result["actions_taken"] == [
        {"type": "drift_alert", "path": "risk/manager.py", "drift_type": "modified"},
        {"type": "drift_alert", "path": "kill_switch.py", "drift_type": "deleted"},
    ]


async def test_a_clean_scan_reports_no_actions():
    from core.self_healer import _scan_wrapper

    result = await _scan_wrapper(_Healer(drift_events=[]))

    assert result == {"actions_taken": []}


async def test_a_crashing_scan_is_swallowed_and_looks_clean():
    """Documents a real weakness rather than asserting it is fine.

    The shim cannot distinguish "scanned, found nothing" from "scanner threw",
    so a permanently broken integrity check reports a permanently clean system.
    Pinned here so the behaviour is visible and a future fix has a test to
    change rather than a silence to discover.
    """
    from core.self_healer import _scan_wrapper

    healer = _Healer(drift_events=[{"ts": "z", "path": "p", "type": "t"}], raises=True)

    assert await _scan_wrapper(healer) == {"actions_taken": []}


async def test_only_the_last_ten_drift_events_are_considered():
    from core.self_healer import _scan_wrapper

    healer = _Healer(
        drift_events=[{"ts": f"2026-01-{i:02d}", "path": f"f{i}", "type": "modified"} for i in range(1, 21)]
    )

    result = await _scan_wrapper(healer)

    assert len(result["actions_taken"]) == 10
    assert result["actions_taken"][0]["path"] == "f11", "the window took the oldest ten, not the newest"


async def test_events_at_or_before_the_last_scan_watermark_are_not_re_reported():
    """Otherwise every celery beat re-alerts on the same drift forever."""
    from core.self_healer import _scan_wrapper

    healer = _Healer(
        drift_events=[
            {"ts": "2026-01-01T00:00:00", "path": "old.py", "type": "modified"},
            {"ts": "2026-06-01T00:00:00", "path": "new.py", "type": "modified"},
        ]
    )
    healer._last_celery_scan_ts = "2026-03-01T00:00:00"

    result = await _scan_wrapper(healer)

    paths = [a["path"] for a in result["actions_taken"]]
    assert paths == ["new.py"]


# ── _SelfHealerProxy ──────────────────────────────────────────────────────────


async def test_the_proxy_scan_advances_the_watermark():
    from core.self_healer import _SelfHealerProxy

    healer = _Healer(drift_events=[{"ts": "2026-01-01T00:00:00", "path": "p", "type": "t"}])
    proxy = _SelfHealerProxy(healer)

    assert not hasattr(healer, "_last_celery_scan_ts")
    first = await proxy.scan()
    watermark = healer._last_celery_scan_ts

    assert first["actions_taken"], "the first scan should report the pending event"
    assert watermark, "the watermark was never set"

    # A second scan with no new events reports nothing.
    second = await proxy.scan()
    assert second["actions_taken"] == []


def test_the_proxy_forwards_unknown_attributes_to_the_healer():
    """celery only needs scan(); everything else must still reach the real object."""
    from core.self_healer import _SelfHealerProxy

    proxy = _SelfHealerProxy(_Healer())

    assert proxy.some_other_attribute == "passed through"


def test_the_proxy_raises_for_an_attribute_the_healer_does_not_have():
    from core.self_healer import _SelfHealerProxy

    proxy = _SelfHealerProxy(_Healer())

    with pytest.raises(AttributeError):
        _ = proxy.definitely_not_a_real_attribute


# ── Module surface ────────────────────────────────────────────────────────────


def test_get_self_healer_returns_a_proxy_exposing_scan():
    """The exact call celery_app.self_healer_scan makes."""
    from core.self_healer import _SelfHealerProxy, get_self_healer

    proxy = get_self_healer()

    assert isinstance(proxy, _SelfHealerProxy)
    assert callable(proxy.scan)


def test_the_shim_re_exports_the_canonical_implementation():
    """The whole point of the shim: core.self_healer is security.self_healer."""
    import security.self_healer as canonical

    from core.self_healer import SelfHealer, get_healer

    assert SelfHealer is canonical.SelfHealer
    assert get_healer is canonical.get_healer


def test_the_public_surface_is_declared():
    import core.self_healer as shim

    assert set(shim.__all__) == {"SelfHealer", "get_healer", "get_self_healer"}
