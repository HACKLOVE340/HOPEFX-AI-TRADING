"""execution package — re-exports from root execution.py"""
import importlib.util as _ilu, os as _os

_spec = _ilu.spec_from_file_location(
    "_execution_module",
    _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "execution.py")
)
if _spec and _spec.loader:
    _mod = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    PaperExecutor   = getattr(_mod, "PaperExecutor", None)
    SmartOrderRouter = getattr(_mod, "SmartOrderRouter", None)
    Order           = getattr(_mod, "Order", None)
    OrderStatus     = getattr(_mod, "OrderStatus", None)
    ExecutionResult = getattr(_mod, "ExecutionResult", None)

# Sub-module imports (position_tracker, trade_executor, etc.) work normally
