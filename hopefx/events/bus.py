"""hopefx.events.bus — module-level event bus singleton.

Imports from src.core.events (canonical implementation).
Falls back to a no-op stub when optional deps are absent.
"""
from __future__ import annotations

try:
    from src.core.events import get_event_bus as _get
    event_bus = _get()
except Exception:
    class _NullBus:
        def subscribe(self, *a, **kw): pass
        def publish(self, *a, **kw): pass
        def __getattr__(self, name): return lambda *a, **kw: None
    event_bus = _NullBus()

__all__ = ["event_bus"]
