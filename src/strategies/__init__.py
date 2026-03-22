"""Trading strategies."""

def __getattr__(name):
    _map = {
        "Strategy": ("src.strategies.base", "Strategy"),
        "XAUUSDMLStrategy": ("src.strategies.xauusd_ml", "XAUUSDMLStrategy"),
    }
    if name in _map:
        import importlib
        mod = importlib.import_module(_map[name][0])
        return getattr(mod, _map[name][1])
    raise AttributeError(f"module 'src.strategies' has no attribute {name!r}")

__all__ = ["Strategy", "XAUUSDMLStrategy"]
