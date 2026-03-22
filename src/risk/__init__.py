"""Risk management module."""

def __getattr__(name):
    _map = {
        "RiskManager": ("src.risk.manager", "RiskManager"),
        "PositionSizer": ("src.risk.position_sizing", "PositionSizer"),
        "RiskMetrics": ("src.risk.var_cvar", "RiskMetrics"),
        "KillSwitch": ("src.risk.kill_switch", "KillSwitch"),
        "KillSwitchState": ("src.risk.kill_switch", "KillSwitchState"),
        "PropFirmCompliance": ("src.risk.prop_firms", "PropFirmCompliance"),
        "PropFirmRules": ("src.risk.prop_firms", "PropFirmRules"),
    }
    if name in _map:
        import importlib
        mod = importlib.import_module(_map[name][0])
        return getattr(mod, _map[name][1])
    raise AttributeError(f"module 'src.risk' has no attribute {name!r}")

__all__ = ["RiskManager","PositionSizer","RiskMetrics","KillSwitch",
           "KillSwitchState","PropFirmCompliance","PropFirmRules"]
