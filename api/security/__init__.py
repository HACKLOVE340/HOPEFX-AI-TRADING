# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
api/security — Security-related API routers.

Routers
-------
    fixes_router   LLM auto-heal fix queue: approve, decline, scan endpoints.
                   Mounted at /api/security/fixes in app.py.

Usage in app.py::

    from api.security import fixes_router
    app.include_router(fixes_router)
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from api.security.fixes import router as fixes_router
except Exception as _exc:  # pragma: no cover
    logger.warning("api.security.fixes router unavailable: %s", _exc)
    fixes_router = None  # type: ignore[assignment]

__all__ = ["fixes_router"]
