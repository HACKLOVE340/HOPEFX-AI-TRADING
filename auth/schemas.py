# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
auth/schemas.py
===============
Pydantic models for the auth subsystem.
"""

from __future__ import annotations

from pydantic import BaseModel


class TokenPayload(BaseModel):
    """Decoded JWT access-token payload."""

    sub: str
    exp: int | None = None
    type: str = "access"
    role: str = "user"
