# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
events — Domain event store and typed event definitions.

Public API
----------
    EventStore      Append-only event store with Redis pub/sub publishing.
    DomainEvent     Base class for all typed domain events.
    typed_events    Module containing all concrete event types.
"""

from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

try:
    from events.event_store import EventStore
except Exception as _exc:
    logger.debug("events.event_store unavailable: %s", _exc)
    EventStore = None  # type: ignore[assignment,misc]

try:
    from events.typed_events import DomainEvent
except Exception as _exc:
    logger.debug("events.typed_events unavailable: %s", _exc)
    DomainEvent = None  # type: ignore[assignment,misc]

__all__ = ["DomainEvent", "EventStore"]
