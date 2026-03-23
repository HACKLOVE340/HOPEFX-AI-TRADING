"""hopefx.risk — merged with src/hopefx/risk via path extension."""
import os as _os

_src_risk = _os.path.normpath(
    _os.path.join(_os.path.dirname(__file__), '..', '..', 'src', 'hopefx', 'risk')
)
if _src_risk not in __path__:
    __path__.append(_src_risk)
