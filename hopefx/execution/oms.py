"""hopefx.execution.oms — OMS singleton shim.

Imports from src.execution.oms (canonical implementation).
Falls back to a no-op stub when optional deps (structlog, etc.) are absent.
"""
from __future__ import annotations

try:
    from src.execution.oms import OMS, OrderManagementSystem  # noqa: F401
    from src.brokers.paper import PaperBroker  # noqa: F401
    oms = OMS(broker=PaperBroker())
except Exception:
    class _Stub:  # type: ignore[no-redef]
        def __getattr__(self, name):
            return None
    OMS = OrderManagementSystem = _Stub  # type: ignore[assignment,misc]
    PaperBroker = _Stub  # type: ignore[assignment,misc]
    oms = _Stub()

__all__ = ["oms", "OMS", "OrderManagementSystem"]
