"""hopefx.events.bus — module-level event bus singleton"""
from src.core.events import get_event_bus as _get
event_bus = _get()
