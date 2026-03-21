"""Core infrastructure module."""

def __getattr__(name):
    _map = {
        "Settings": ("src.core.config", "Settings"),
        "get_settings": ("src.core.config", "get_settings"),
        "settings": ("src.core.config", "settings"),
        "Event": ("src.core.events", "Event"),
        "EventBus": ("src.core.events", "EventBus"),
        "get_event_bus": ("src.core.events", "get_event_bus"),
        "HopeFXError": ("src.core.exceptions", "HopeFXError"),
        "configure_logging": ("src.core.logging_config", "configure_logging"),
        "get_logger": ("src.core.logging_config", "get_logger"),
        "TradingEngine": ("src.core.trading_engine", "TradingEngine"),
        "LifecycleManager": ("src.core.lifecycle", "LifecycleManager"),
        "LifecycleState": ("src.core.lifecycle", "LifecycleState"),
    }
    if name in _map:
        mod_path, attr = _map[name]
        import importlib
        mod = importlib.import_module(mod_path)
        return getattr(mod, attr)
    raise AttributeError(f"module 'src.core' has no attribute {name!r}")

__all__ = ["Settings","get_settings","settings","Event","EventBus","get_event_bus",
           "HopeFXError","configure_logging","get_logger","TradingEngine",
           "LifecycleManager","LifecycleState"]
