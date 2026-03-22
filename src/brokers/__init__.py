"""Broker integrations."""

def __getattr__(name):
    _map = {
        "Broker": ("src.brokers.base", "Broker"),
        "OandaBroker": ("src.brokers.oanda", "OandaBroker"),
        "PaperBroker": ("src.brokers.paper", "PaperBroker"),
    }
    if name in _map:
        import importlib
        mod = importlib.import_module(_map[name][0])
        return getattr(mod, _map[name][1])
    raise AttributeError(f"module 'src.brokers' has no attribute {name!r}")

__all__ = ["Broker", "OandaBroker", "PaperBroker"]
