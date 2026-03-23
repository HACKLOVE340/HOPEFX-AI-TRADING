"""hopefx.brain — re-exports from brain package"""
from brain.brain import HOPEFXBrain, SystemState, MarketRegime

# ── path extension: merge with src/hopefx/brain ──────────────────────────
import os as _os_brain
_src_brain = _os_brain.path.normpath(
    _os_brain.path.join(_os_brain.path.dirname(__file__), '..', '..', 'src', 'hopefx', 'brain')
)
if _src_brain not in __path__:
    __path__.append(_src_brain)
