"""hopefx.backtesting — merged with src/hopefx/backtesting via path extension."""
import os as _os
_src = _os.path.normpath(_os.path.join(_os.path.dirname(__file__), '..', '..', 'src', 'hopefx', 'backtesting'))
if _src not in __path__:
    __path__.append(_src)
