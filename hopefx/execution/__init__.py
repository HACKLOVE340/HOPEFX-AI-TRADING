"""hopefx.execution — delegates to src/execution."""
import os as _os

_src_exec = _os.path.normpath(
    _os.path.join(_os.path.dirname(__file__), '..', '..', 'src', 'execution')
)
if _src_exec not in __path__:
    __path__.append(_src_exec)

# Re-export oms for backwards compatibility
try:
    from hopefx.execution.oms import *  # noqa: F401,F403
except Exception:
    pass
