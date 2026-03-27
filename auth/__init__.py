# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""Auth package."""

from .router import router as auth_router
from .service import AuthService

__all__ = ["AuthService", "auth_router"]
