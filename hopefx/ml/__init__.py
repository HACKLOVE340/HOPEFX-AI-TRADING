"""hopefx.ml — re-exports from ml package"""

# ── path extension: merge with src/hopefx/ml ───────────────────────────
import os as _os_ext
_src_ext = _os_ext.path.normpath(
    _os_ext.path.join(_os_ext.path.dirname(__file__), '..', '..', 'src', 'hopefx', 'ml')
)
if _src_ext not in __path__:
    __path__.append(_src_ext)
