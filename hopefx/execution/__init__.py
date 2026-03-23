"""hopefx.execution — merged with src/hopefx/execution via path extension."""
import os as _os, sys as _sys

_src_exec = _os.path.join(_os.path.dirname(__file__), '..', '..', 'src', 'hopefx', 'execution')
_src_exec = _os.path.normpath(_src_exec)
if _src_exec not in __path__:
    __path__.append(_src_exec)

# Re-export oms for backwards compatibility
try:
    from hopefx.execution.oms import *  # noqa: F401,F403
except Exception:
    pass
