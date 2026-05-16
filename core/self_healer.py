# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
Compatibility shim: core.self_healer → security.self_healer.

The canonical SelfHealer implementation lives in security/self_healer.py.
This shim re-exports it under the core.self_healer namespace so that
existing callers (celery_app.py, etc.) don't need to be changed.

Also provides:
  get_self_healer()  — alias for security.self_healer.get_healer()
  SelfHealer         — re-export of the class
"""

from __future__ import annotations

from security.self_healer import SelfHealer, get_healer


async def _scan_wrapper(healer: SelfHealer) -> dict:
    """
    Thin wrapper that calls _scan_integrity() and returns a standardised
    actions_taken dict expected by celery_app.self_healer_scan.
    """
    try:
        await healer._scan_integrity()
        drift_events = list(healer._drift_events)[-10:]
        return {
            "actions_taken": [
                {"type": "drift_alert", "path": e.get("path"), "drift_type": e.get("type")}
                for e in drift_events
                if e.get("ts", "") > getattr(healer, "_last_celery_scan_ts", "")
            ]
        }
    except Exception:
        return {"actions_taken": []}


class _SelfHealerProxy:
    """
    Proxy that wraps a SelfHealer instance and exposes the scan() method
    expected by celery_app.self_healer_scan.
    """

    def __init__(self, healer: SelfHealer) -> None:
        self._healer = healer

    async def scan(self) -> dict:
        result = await _scan_wrapper(self._healer)
        self._healer._last_celery_scan_ts = (
            __import__("datetime")
            .datetime.now(  # type: ignore[attr-defined]
                __import__("datetime").timezone.utc
            )
            .isoformat()
        )
        return result

    def __getattr__(self, name: str):
        return getattr(self._healer, name)


def get_self_healer() -> _SelfHealerProxy:
    """
    Return the SelfHealer singleton wrapped in a proxy that exposes scan().

    Drop-in replacement for the (non-existent) core.self_healer.get_self_healer()
    call in celery_app.py.
    """
    return _SelfHealerProxy(get_healer())


__all__ = ["SelfHealer", "get_healer", "get_self_healer"]
