"""hopefx.events — merged with src/hopefx/events via path extension."""
import os as _os

_src_events = _os.path.normpath(
    _os.path.join(_os.path.dirname(__file__), '..', '..', 'src', 'hopefx', 'events')
)
if _src_events not in __path__:
    __path__.append(_src_events)

# Re-export common symbols so `from hopefx.events import event_bus` works
try:
    from hopefx.events.bus import event_bus  # noqa: F401
except Exception:
    pass
