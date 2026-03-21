"""Execution layer - order management and routing."""

def __getattr__(name):
    _map = {
        "OrderManagementSystem": ("src.execution.oms", "OrderManagementSystem"),
        "SmartOrderRouter": ("src.execution.router", "SmartOrderRouter"),
        "VenueScore": ("src.execution.router", "VenueScore"),
    }
    if name in _map:
        import importlib
        mod = importlib.import_module(_map[name][0])
        return getattr(mod, _map[name][1])
    raise AttributeError(f"module 'src.execution' has no attribute {name!r}")

__all__ = ["OrderManagementSystem", "SmartOrderRouter", "VenueScore"]
