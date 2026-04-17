# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
data_layer/lineage — Immutable append-only audit trail for all data events.

Public API
----------
    DataLineageStore   Content-addressed, append-only SQLite/PostgreSQL store.
                       Records TICK, NEWS, MACRO, SIGNAL, and QUALITY events.
                       Every record carries a SHA-256 content hash and the
                       lineage_id of its upstream source.

Usage
-----
    from data_layer.lineage import DataLineageStore
    store = DataLineageStore()
    await store.record_tick(tick, source="goldapi", quality=0.95)
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from data_layer.lineage.store import DataLineageStore  # noqa: F401
except Exception as _exc:
    logger.debug("data_layer.lineage: DataLineageStore unavailable: %s", _exc)
    DataLineageStore = None  # type: ignore[assignment,misc]

__all__ = ["DataLineageStore"]
