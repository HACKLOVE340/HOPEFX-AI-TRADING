# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
auth/dependencies.py
====================
Compatibility re-export module.

The canonical FastAPI dependency functions live in api/auth.py.
This module re-exports them so that code using the older import path
``from auth.dependencies import get_current_user, require_role``
continues to work without modification.

New code should import directly from api.auth:
    from api.auth import get_current_user, require_role, TokenPayload
"""

from __future__ import annotations

from api.auth import TokenPayload, get_current_user, require_role

__all__ = ["TokenPayload", "get_current_user", "require_role"]
