"""hopefx.risk — delegates to src/risk."""
import os as _os

_src_risk = _os.path.normpath(
    _os.path.join(_os.path.dirname(__file__), '..', '..', 'src', 'risk')
)
if _src_risk not in __path__:
    __path__.append(_src_risk)
